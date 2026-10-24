"""The perceive -> think -> act loop."""

from __future__ import annotations

import json
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .actions import Action, ActionError, SIDE_EFFECT_ACTIONS, parse_action
from .llm import LLMClient
from .safety import CaptchaGuard, HandoffRequired, SafetyPolicy

SYSTEM_PROMPT = """You are a phone-use agent controlling an Android device the \
user owns or an emulator they authorized. You receive the current UI \
hierarchy (visible text, content descriptions, resource ids, bounds) \
and sometimes a screenshot, and you reply with exactly ONE action as a \
JSON object.

Available actions:
- {"action": "tap", "x": <int>, "y": <int>}
- {"action": "swipe", "x": <int>, "y": <int>, "x2": <int>, "y2": <int>, "ms": <int>}
- {"action": "type", "text": "<string>"}
- {"action": "key", "key": "BACK" | "HOME" | "ENTER" | "TAB" | "DELETE"}
- {"action": "launch", "package": "<android package name>"}
- {"action": "wait", "ms": <int>}
- {"action": "handoff", "summary": "<why a human must take over>"}
- {"action": "done", "summary": "<what was accomplished>"}

Screen size: {width}x{height} pixels. Prefer tapping the center of the \
bounds of the UI element you want. If you see a CAPTCHA, a \
"verify you are human" screen, or any anti-bot challenge, reply with \
"handoff" immediately - you must never attempt to solve or bypass \
those. If asked to do something harmful, deceptive, or outside the \
user's authorization, reply with "handoff" and explain. Reply with the \
JSON object only."""

#: Matches bounds like "[12,40][300,96]" from uiautomator XML.
_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def flatten_ui_hierarchy(xml_text: str, max_nodes: int = 250) -> str:
    """Compact the uiautomator XML into readable lines for the model.

    Each line is ``text | desc | id | center-x,center-y`` so the model
    can quote coordinates directly. Unparseable XML degrades to the
    raw string rather than failing the step.
    """
    if not xml_text or "<" not in xml_text:
        return (xml_text or "")[:4000]
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return xml_text[:4000]
    lines: List[str] = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        rid = (node.get("resource-id") or "").strip()
        bounds = node.get("bounds") or ""
        if not (text or desc or rid):
            continue
        center = ""
        m = _BOUNDS_RE.match(bounds)
        if m:
            x1, y1, x2, y2 = (int(g) for g in m.groups())
            center = f"{(x1 + x2) // 2},{(y1 + y2) // 2}"
        lines.append(" | ".join(p for p in (text, desc, rid, center) if p))
        if len(lines) >= max_nodes:
            lines.append("... (truncated)")
            break
    return "\n".join(lines) or "(screen has no readable nodes)"


@dataclass
class StepRecord:
    index: int
    action: Optional[Action]
    note: str
    elapsed_s: float


@dataclass
class AgentResult:
    status: str                 # "done" | "handoff" | "aborted"
    summary: str
    steps: List[StepRecord] = field(default_factory=list)


class AgentLoop:
    """Runs an agent on a device until done, handoff, or step limit.

    ``device`` only needs the small interface of
    :class:`phone_use.adb.ADBDevice` (screenshot, size, UI tree,
    tap/swipe/type/key/launch/wait, foreground_app), so tests can
    substitute a fake device.
    """

    def __init__(self, *, device, llm: LLMClient,
                 guard: Optional[CaptchaGuard] = None,
                 policy: Optional[SafetyPolicy] = None,
                 max_steps: int = 30,
                 on_handoff: Optional[Callable[[HandoffRequired], None]] = None,
                 send_screenshots: bool = True):
        self.device = device
        self.llm = llm
        self.guard = guard or CaptchaGuard()
        self.policy = policy or SafetyPolicy()
        self.max_steps = max_steps
        self.on_handoff = on_handoff
        self.send_screenshots = send_screenshots

    # -- helpers -----------------------------------------------------------
    def _perceive(self) -> tuple:
        """(screenshot bytes or None, flattened UI text, foreground app)."""
        shot = None
        if self.send_screenshots:
            try:
                shot = self.device.screenshot_png()
            except Exception:
                shot = None  # UI text alone is still workable
        try:
            ui_text = flatten_ui_hierarchy(self.device.ui_hierarchy_xml())
        except Exception as exc:
            ui_text = f"(UI hierarchy unavailable: {exc})"
        try:
            foreground = self.device.foreground_app()
        except Exception:
            foreground = ""
        return shot, ui_text, foreground

    def _execute(self, action: Action) -> None:
        if action.kind == "tap":
            self.device.tap(action.x, action.y)
        elif action.kind == "swipe":
            self.device.swipe(action.x, action.y, action.x2, action.y2,
                              action.ms or 300)
        elif action.kind == "type":
            self.device.type_text(action.text)
        elif action.kind == "key":
            self.device.key(action.key)
        elif action.kind == "launch":
            self.device.launch(action.package)
        elif action.kind == "wait":
            self.device.wait(min(action.ms or 1000, 10_000))

    # -- main loop ---------------------------------------------------------
    def run(self, task: str) -> AgentResult:
        width, height = self.device.screen_size()
        system = (SYSTEM_PROMPT
                  .replace("{width}", str(width))
                  .replace("{height}", str(height)))
        history: List[dict] = [{
            "role": "user",
            "content": f"Task: {task}\nBegin.",
        }]
        steps: List[StepRecord] = []
        retries = 0

        for index in range(self.max_steps):
            started = time.monotonic()
            shot, ui_text, foreground = self._perceive()

            # 1. Screen-level safety: CAPTCHA / challenge detection.
            try:
                self.guard.inspect(ui_text, foreground)
            except HandoffRequired as handoff:
                return self._handoff(steps, index, started, handoff)

            # 2. Think.
            reply = self.llm.step(system=system, history=history,
                                  screenshot_png=shot, screen_text=ui_text)

            # 3. Parse; give the model one chance to fix malformed output.
            try:
                action = parse_action(reply)
                retries = 0
            except ActionError as exc:
                retries += 1
                steps.append(StepRecord(index, None, f"parse error: {exc}",
                                        time.monotonic() - started))
                if retries >= 3:
                    return AgentResult(
                        "aborted",
                        f"model produced unparsable actions {retries}x in a row",
                        steps)
                history.append({"role": "assistant", "content": reply})
                history.append({"role": "user", "content":
                                "That was not a valid action JSON. Reply with "
                                "exactly one valid action object."})
                continue

            # 4. Voluntary stop conditions from the model itself.
            if action.kind == "done":
                steps.append(StepRecord(index, action, "done",
                                        time.monotonic() - started))
                return AgentResult("done", action.summary or "", steps)
            if action.kind == "handoff":
                return self._handoff(steps, index, started, HandoffRequired(
                    action.summary or "agent requested human takeover"))

            # 5. Action-level safety policy.
            try:
                self.policy.check_action(action, foreground)
            except HandoffRequired as handoff:
                return self._handoff(steps, index, started, handoff)

            # 6. Act.
            if action.kind in SIDE_EFFECT_ACTIONS or action.kind == "wait":
                self._execute(action)
            steps.append(StepRecord(index, action, "executed",
                                    time.monotonic() - started))
            history.append({"role": "assistant", "content": json.dumps(action.raw)})

        return AgentResult(
            "aborted", f"step limit {self.max_steps} reached", steps)

    def _handoff(self, steps: List[StepRecord], index: int, started: float,
                 handoff: HandoffRequired) -> AgentResult:
        steps.append(StepRecord(index, None,
                                f"handoff: {handoff.reason}",
                                time.monotonic() - started))
        if self.on_handoff:
            self.on_handoff(handoff)
        return AgentResult("handoff", handoff.reason, steps)
