"""Safety layer: CAPTCHA detection and human handoff, never bypass.

Design rule: this framework *detects* CAPTCHAs and other human-only
challenges and stops. It does not solve, bypass, route around, or
delegate them to a solving service. When a challenge appears, the
agent pauses and hands the phone to a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Pattern

from .actions import Action


class HandoffRequired(RuntimeError):
    """Raised when a human must take over the device.

    Carries a human-readable reason and, when available, the evidence
    (matched challenge markers) that triggered it.
    """

    def __init__(self, reason: str, evidence: Optional[List[str]] = None):
        super().__init__(reason)
        self.reason = reason
        self.evidence = evidence or []


#: Text patterns that indicate an anti-bot / human-verification
#: challenge. Matching is case-insensitive and works on the flattened
#: UI hierarchy text plus the foreground app name.
DEFAULT_CHALLENGE_PATTERNS: tuple = (
    r"\bi'?m not a robot\b",
    r"\brecaptcha\b",
    r"\bhcaptcha\b",
    r"\barkose\s*labs?\b",
    r"\bfuncaptcha\b",
    r"\bcloudflare\b.{0,40}\b(verify|challenge|checking)\b",
    r"\bverify (that )?you('re| are) (a )?human\b",
    r"\bhuman verification\b",
    r"\bselect all (the )?(images|squares|tiles)\b",
    r"\bsecurity check\b.{0,40}\b(robot|automated|unusual traffic)\b",
    r"\bunusual traffic\b",
    r"\bprove you'?re not a robot\b",
    r"\bare you a robot\??\b",
    r"\bcaptcha\b",
)

#: App packages where an autonomous agent should never act alone -
#: payment / banking flows get an unconditional human gate.
DEFAULT_PROTECTED_PACKAGES: tuple = (
    "com.google.android.apps.walletnfcrel",  # Google Wallet
    "com.paypal.android.p2pmobile",
    "com.venmo",
    "com.cash.app",
)


class CaptchaGuard:
    """Screens what the agent sees for human-verification challenges."""

    def __init__(self, extra_patterns: Iterable[str] = ()):
        self._patterns: List[Pattern[str]] = [
            re.compile(p, re.IGNORECASE | re.DOTALL)
            for p in list(DEFAULT_CHALLENGE_PATTERNS) + list(extra_patterns)
        ]

    def find_markers(self, screen_text: str) -> List[str]:
        """Return every challenge marker present in the screen text."""
        hits = []
        for pat in self._patterns:
            m = pat.search(screen_text or "")
            if m:
                hits.append(m.group(0).strip())
        return hits

    def inspect(self, screen_text: str, foreground_package: str = "") -> None:
        """Raise :class:`HandoffRequired` if a challenge is on screen."""
        haystack = f"{foreground_package}\n{screen_text or ''}"
        hits = self.find_markers(haystack)
        if hits:
            raise HandoffRequired(
                "Human-verification challenge detected on screen; "
                "handing off to a human. This framework detects CAPTCHAs "
                "and never attempts to solve or bypass them.",
                evidence=hits,
            )


@dataclass
class SafetyPolicy:
    """Gate every state-changing action before it reaches the device.

    - ``protected_packages``: any action taken while one of these apps
      is in the foreground requires human confirmation.
    - ``blocked_packages``: the agent refuses to launch or act in
      these at all.
    - ``require_confirmation``: optional callback
      ``(action, reason) -> bool``; when set, protected actions ask the
      human through it. Without a callback, protected actions are
      denied outright (fail closed).
    """

    protected_packages: tuple = DEFAULT_PROTECTED_PACKAGES
    blocked_packages: tuple = ()
    require_confirmation: Optional[Callable[[Action, str], bool]] = None
    denied_log: List[str] = field(default_factory=list)

    def _deny(self, reason: str) -> None:
        self.denied_log.append(reason)
        raise HandoffRequired(reason)

    def check_launch(self, package: str) -> None:
        if package in self.blocked_packages:
            self._deny(f"launch of blocked package {package!r} refused")

    def check_action(self, action: Action, foreground_package: str = "") -> None:
        if action.kind == "launch":
            self.check_launch(action.package or "")
            if action.package in self.protected_packages:
                self._confirm(action, f"launching protected app {action.package!r}")
            return
        if foreground_package in self.blocked_packages:
            self._deny(
                f"device is inside blocked package {foreground_package!r}; "
                "agent must stop"
            )
        if foreground_package in self.protected_packages:
            self._confirm(
                action, f"acting inside protected app {foreground_package!r}"
            )

    def _confirm(self, action: Action, reason: str) -> None:
        if self.require_confirmation is None:
            self._deny(
                f"{reason} requires human confirmation and no confirmation "
                "callback is configured; refusing to act"
            )
        if not self.require_confirmation(action, reason):
            self._deny(f"human declined: {reason}")
