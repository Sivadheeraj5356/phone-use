"""Real-emulator smoke test, run by GitHub Actions.

The android-emulator-runner action provides a booted emulator reachable
over adb; this script exercises ADBDevice end to end: screen size,
screenshot, UI hierarchy, a key event and a tap. No LLM involved.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from phone_use.adb import ADBDevice


def wait_for_boot(timeout_s: int = 300) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        out = subprocess.run(
            ["adb", "shell", "getprop", "sys.boot_completed"],
            capture_output=True, text=True)
        if out.stdout.strip() == "1":
            return
        time.sleep(5)
    raise SystemExit("emulator did not boot in time")


def ui_hierarchy_with_retry(device, attempts: int = 4) -> str:
    last = None
    for _ in range(attempts):
        try:
            xml = device.ui_hierarchy_xml()
            if "<hierarchy" in xml:
                return xml
        except Exception as exc:  # uiautomator can race right after boot
            last = exc
        time.sleep(5)
    raise SystemExit(f"UI hierarchy unavailable: {last}")


def screenshot_with_retry(device, attempts: int = 3) -> bytes:
    last = None
    for _ in range(attempts):
        try:
            return device.screenshot_png()
        except Exception as exc:  # first screencap can race the display
            last = exc
            time.sleep(10)
    raise SystemExit(f"screenshot failed after {attempts} attempts: {last}")


def main() -> None:
    wait_for_boot()
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_WAKEUP"],
                   check=False, capture_output=True)
    device = ADBDevice()
    width, height = device.screen_size()
    assert width > 0 and height > 0, f"bad screen size {width}x{height}"
    shot = screenshot_with_retry(device)
    assert shot.startswith(b"\x89PNG"), "screenshot is not a PNG"
    xml = ui_hierarchy_with_retry(device)
    device.key("HOME")
    device.tap(width // 2, height // 2)
    print(f"SMOKE OK: {width}x{height}, screenshot {len(shot)} bytes, "
          f"UI tree {len(xml)} chars")


if __name__ == "__main__":
    main()
