"""In-memory fake implementing the ADBDevice interface.

Screens are scripted uiautomator-style XML documents; actions mutate
nothing but are recorded so tests can assert exactly what the agent
tried to do. This proves framework behavior (parsing, safety gates,
loop control) without a phone - it is NOT evidence of real-device
operation.
"""

from __future__ import annotations

from typing import List, Optional, Tuple


class FakeDevice:
    def __init__(self, screens: List[str], size: Tuple[int, int] = (1080, 2400),
                 foreground: str = "com.example.fake"):
        self._screens = list(screens) or [""]
        self._size = size
        self._foreground = foreground
        self.actions: List[tuple] = []

    # perception
    def screenshot_png(self) -> bytes:
        # 1x1 transparent PNG - just needs to be real PNG bytes.
        return (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
                b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
                b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
                b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

    def screen_size(self) -> Tuple[int, int]:
        return self._size

    def ui_hierarchy_xml(self) -> str:
        if len(self._screens) > 1:
            return self._screens.pop(0)
        return self._screens[0]

    def foreground_app(self) -> str:
        return self._foreground

    # actuation - recorded, not performed
    def tap(self, x: int, y: int) -> None:
        self.actions.append(("tap", x, y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self.actions.append(("swipe", x1, y1, x2, y2, ms))

    def type_text(self, text: str) -> None:
        self.actions.append(("type", text))

    def key(self, name: str) -> None:
        self.actions.append(("key", name))

    def launch(self, package: str) -> None:
        self.actions.append(("launch", package))

    def wait(self, ms: int) -> None:
        self.actions.append(("wait", ms))


def ui(*nodes: str) -> str:
    """Build a tiny uiautomator document from 'text|desc|id|bounds' rows."""
    body = "".join(
        f'<node text="{t}" content-desc="{d}" resource-id="{r}" bounds="{b}"/>'
        for t, d, r, b in (row.split("|") for row in nodes)
    )
    return f'<hierarchy rotation="0">{body}</hierarchy>'
