"""Command-line interface: ``python -m phone_use ...``"""

from __future__ import annotations

import argparse
import os
import sys

from .adb import ADBDevice, ADBError
from .agent import AgentLoop
from .llm import OpenAICompatibleClient
from .safety import CaptchaGuard, HandoffRequired, SafetyPolicy


def _console_confirm(action, reason) -> bool:
    answer = input(f"[phone-use] {reason}. Allow {action.describe()}? [y/N] ")
    return answer.strip().lower() in ("y", "yes")


def _console_handoff(handoff: HandoffRequired) -> None:
    print(f"\n[phone-use] HUMAN TAKEOVER NEEDED: {handoff.reason}",
          file=sys.stderr)
    for hit in handoff.evidence:
        print(f"  evidence: {hit}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="phone-use",
        description="Let an AI agent operate an Android phone/emulator "
                    "you own or are authorized to control.")
    p.add_argument("--serial", help="adb device serial (default: only device)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="list connected devices/emulators")

    shot = sub.add_parser("screenshot", help="save a screenshot from the device")
    shot.add_argument("out", help="output PNG path")

    run = sub.add_parser("run", help="run an agent task")
    run.add_argument("task", help="natural-language task for the agent")
    run.add_argument("--model", required=True,
                     help="vision-capable model id at the endpoint")
    run.add_argument("--base-url",
                     default=os.environ.get("PHONE_USE_BASE_URL",
                                            "http://localhost:11434/v1"),
                     help="OpenAI-compatible base URL "
                          "(default: local Ollama; env PHONE_USE_BASE_URL)")
    run.add_argument("--api-key",
                     default=os.environ.get("PHONE_USE_API_KEY", ""),
                     help="API key if the endpoint needs one "
                          "(env PHONE_USE_API_KEY)")
    run.add_argument("--no-images", action="store_true",
                     help="text-only mode: send UI tree, no screenshots")
    run.add_argument("--max-steps", type=int, default=30)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "devices":
            devices = ADBDevice.list_devices()
            if not devices:
                print("no devices; start an emulator or enable USB debugging")
                return 1
            for d in devices:
                print(f"{d.serial}\t{d.state}")
            return 0

        device = ADBDevice(serial=args.serial)

        if args.command == "screenshot":
            with open(args.out, "wb") as fh:
                fh.write(device.screenshot_png())
            print(f"saved {args.out}")
            return 0

        if args.command == "run":
            llm = OpenAICompatibleClient(
                base_url=args.base_url, api_key=args.api_key,
                model=args.model, send_images=not args.no_images)
            loop = AgentLoop(
                device=device, llm=llm,
                guard=CaptchaGuard(),
                policy=SafetyPolicy(require_confirmation=_console_confirm),
                max_steps=args.max_steps,
                on_handoff=_console_handoff,
                send_screenshots=not args.no_images)
            result = loop.run(args.task)
            print(f"status: {result.status}")
            print(f"summary: {result.summary}")
            for step in result.steps:
                action = step.action.describe() if step.action else "-"
                print(f"  {step.index:>3}. {action}  ({step.note})")
            return 0 if result.status == "done" else 2
    except ADBError as exc:
        print(f"adb error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
