"""Typed actions an agent can take on a phone, plus a tolerant parser.

The LLM is asked to answer with one JSON object per step, e.g.::

    {"action": "tap", "x": 540, "y": 1170}
    {"action": "type", "text": "hello world"}
    {"action": "done", "summary": "Battery saver is now on."}

The parser accepts the object bare, inside a ```json fence, or embedded
in surrounding prose, because real models do all three.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Every action the framework knows how to execute.
VALID_ACTIONS = (
    "tap",
    "swipe",
    "type",
    "key",
    "launch",
    "wait",
    "handoff",  # agent voluntarily asks a human to take over
    "done",     # task finished
)

#: Actions that change device state and therefore go through the
#: safety policy before execution. "wait" and "done" are passive.
SIDE_EFFECT_ACTIONS = frozenset({"tap", "swipe", "type", "key", "launch"})


class ActionError(ValueError):
    """Raised when the model's reply cannot be turned into an Action."""


@dataclass
class Action:
    """One validated step.

    Coordinates are always in device pixels; the agent loop is
    responsible for telling the model the real screen size.
    """

    kind: str
    x: Optional[int] = None
    y: Optional[int] = None
    x2: Optional[int] = None
    y2: Optional[int] = None
    text: Optional[str] = None
    key: Optional[str] = None          # e.g. "BACK", "HOME", "ENTER"
    package: Optional[str] = None      # e.g. "com.android.settings"
    ms: Optional[int] = None           # wait duration / swipe duration
    summary: Optional[str] = None      # for done / handoff
    raw: dict = field(default_factory=dict, repr=False)

    def describe(self) -> str:
        if self.kind == "tap":
            return f"tap({self.x}, {self.y})"
        if self.kind == "swipe":
            return f"swipe({self.x},{self.y} -> {self.x2},{self.y2}, {self.ms or 300}ms)"
        if self.kind == "type":
            return f"type({self.text!r})"
        if self.kind == "key":
            return f"key({self.key})"
        if self.kind == "launch":
            return f"launch({self.package})"
        if self.kind == "wait":
            return f"wait({self.ms or 1000}ms)"
        if self.kind in ("done", "handoff"):
            return f"{self.kind}({(self.summary or '').strip()!r})"
        return self.kind


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BRACE_RE = re.compile(r"\{[^{}]*\"action\"[^{}]*\}", re.DOTALL)


def _extract_json_object(reply: str) -> dict:
    """Pull the first JSON object containing an "action" key out of a reply."""
    candidates = []
    fence = _FENCE_RE.search(reply)
    if fence:
        candidates.append(fence.group(1))
    candidates.extend(m.group(0) for m in _BRACE_RE.finditer(reply))
    if not candidates and reply.strip().startswith("{"):
        candidates.append(reply.strip())
    for blob in candidates:
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "action" in obj:
            return obj
    raise ActionError(f"no JSON action found in model reply: {reply[:200]!r}")


def _int_field(obj: dict, name: str, *, required_for: tuple = ()) -> Optional[int]:
    value = obj.get(name)
    if value is None:
        if obj.get("action") in required_for:
            raise ActionError(f"action {obj['action']!r} requires {name!r}")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ActionError(f"field {name!r} must be an integer, got {value!r}")


def parse_action(reply: str) -> Action:
    """Validate a model reply into an :class:`Action`.

    Raises :class:`ActionError` on anything malformed, so the agent
    loop can ask the model to correct itself instead of executing
    garbage on a real device.
    """
    obj = _extract_json_object(reply)
    kind = str(obj.get("action", "")).lower().strip()
    if kind not in VALID_ACTIONS:
        raise ActionError(f"unknown action {kind!r}; expected one of {VALID_ACTIONS}")

    action = Action(
        kind=kind,
        x=_int_field(obj, "x", required_for=("tap", "swipe")),
        y=_int_field(obj, "y", required_for=("tap", "swipe")),
        x2=_int_field(obj, "x2", required_for=("swipe",)),
        y2=_int_field(obj, "y2", required_for=("swipe",)),
        ms=_int_field(obj, "ms"),
        raw=obj,
    )
    if kind == "type":
        text = obj.get("text")
        if not isinstance(text, str) or text == "":
            raise ActionError("action 'type' requires non-empty 'text'")
        action.text = text
    elif kind == "key":
        key = obj.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ActionError("action 'key' requires a 'key' name like 'BACK'")
        action.key = key.strip().upper()
    elif kind == "launch":
        package = obj.get("package")
        if not isinstance(package, str) or "." not in package:
            raise ActionError("action 'launch' requires a 'package' like 'com.android.settings'")
        action.package = package.strip()
    elif kind in ("done", "handoff"):
        summary = obj.get("summary", "")
        action.summary = summary if isinstance(summary, str) else str(summary)
    if action.ms is not None and action.ms < 0:
        raise ActionError("'ms' must be >= 0")
    return action
