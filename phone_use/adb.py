"""ADB device control.

Wraps the ``adb`` binary so the rest of the framework never shells out
directly. Works with physical devices (USB debugging on) and emulators.
Only ever point this at a phone or emulator you own or are authorized
to control.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


class ADBError(RuntimeError):
    """Raised when an adb command fails or no device is reachable."""


@dataclass
class DeviceInfo:
    serial: str
    state: str  # "device", "unauthorized", "offline", ...


def _run_adb(args: List[str], serial: Optional[str], timeout: int = 30,
             binary: bool = False) -> bytes:
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ADBError(f"adb {' '.join(args)} timed out after {timeout}s")
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace").strip()
        raise ADBError(f"adb {' '.join(args)} failed: {stderr or 'exit %d' % proc.returncode}")
    return proc.stdout if binary else proc.stdout


class ADBDevice:
    """One Android device or emulator reachable over adb."""

    def __init__(self, serial: Optional[str] = None):
        self.serial = serial

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def list_devices() -> List[DeviceInfo]:
        out = _run_adb(["devices"], serial=None).decode("utf-8", "replace")
        devices = []
        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            serial, _, state = line.partition("\t")
            devices.append(DeviceInfo(serial=serial, state=state))
        return devices

    def _shell(self, *args: str, timeout: int = 30) -> str:
        return _run_adb(["shell", *args], self.serial, timeout).decode("utf-8", "replace")

    def _exec_out(self, *args: str, timeout: int = 30, binary: bool = False) -> bytes:
        return _run_adb(["exec-out", *args], self.serial, timeout, binary=binary)

    # -- perception --------------------------------------------------------
    def screenshot_png(self, timeout: int = 60) -> bytes:
        """Raw PNG bytes of the current screen.

        The default 60s timeout covers the slow first screencap on a
        freshly booted emulator.
        """
        data = self._exec_out("screencap", "-p", timeout=timeout, binary=True)
        if not data.startswith(b"\x89PNG"):
            raise ADBError("screencap did not return a PNG")
        return data

    def screen_size(self) -> Tuple[int, int]:
        out = self._shell("wm", "size")
        m = re.search(r"(\d+)x(\d+)", out)
        if not m:
            raise ADBError(f"could not parse screen size from {out!r}")
        return int(m.group(1)), int(m.group(2))

    def ui_hierarchy_xml(self) -> str:
        """Accessibility UI tree via uiautomator - text, ids, bounds.

        Tries ``uiautomator dump /dev/tty`` over exec-out first (no file
        round-trip on the device), falling back to the /sdcard file
        method. Both raise ADBError when uiautomator itself fails.
        """
        text = self._exec_out("uiautomator", "dump", "/dev/tty",
                              timeout=30).decode("utf-8", "replace")
        start = text.find("<hierarchy")
        end = text.rfind("</hierarchy>")
        if start != -1 and end != -1:
            return text[start:end + len("</hierarchy>")]
        self._shell("uiautomator", "dump", "/sdcard/__phone_use_window.xml",
                    timeout=30)
        return self._shell("cat", "/sdcard/__phone_use_window.xml", timeout=30)

    def foreground_app(self) -> str:
        out = self._shell("dumpsys", "window", "displays", timeout=20)
        m = re.search(r"mCurrentFocus=\S+\s+\S+\s+([\w.]+)/", out)
        return m.group(1) if m else ""

    # -- actuation ---------------------------------------------------------
    def tap(self, x: int, y: int) -> None:
        self._shell("input", "tap", str(x), str(y))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        self._shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))

    def type_text(self, text: str) -> None:
        # `input text` treats % as the escape introducer; %s = space, %% = %.
        escaped = text.replace("%", "%%").replace(" ", "%s")
        self._shell("input", "text", escaped, timeout=max(30, len(text)))

    def key(self, name: str) -> None:
        allowed = {"BACK", "HOME", "ENTER", "TAB", "DELETE",
                   "APP_SWITCH", "POWER", "VOLUME_UP", "VOLUME_DOWN",
                   "MOVE_UP", "MOVE_DOWN", "MOVE_LEFT", "MOVE_RIGHT"}
        key = name.upper()
        if key not in allowed:
            raise ADBError(f"key {name!r} not in allowlist {sorted(allowed)}")
        self._shell("input", "keyevent", f"KEYCODE_{key}")

    def launch(self, package: str) -> None:
        self._shell("monkey", "-p", package, "-c",
                    "android.intent.category.LAUNCHER", "1", timeout=20)

    def wait(self, ms: int) -> None:
        time.sleep(ms / 1000.0)
