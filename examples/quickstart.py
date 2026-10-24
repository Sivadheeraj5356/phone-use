"""Minimal real-device run: ask an agent to open Settings > Battery.

Prereqs:
  1. `adb devices` shows your phone (USB debugging on) or an emulator.
  2. An OpenAI-compatible endpoint with a vision model. Local, free:
       ollama pull qwen2.5vl && ollama serve
     then use --base-url http://localhost:11434/v1 --model qwen2.5vl
     (or point at any hosted OpenAI-compatible API you have access to).

Run:
  python examples/quickstart.py
"""

from phone_use import AgentLoop, CaptchaGuard, OpenAICompatibleClient, SafetyPolicy
from phone_use.adb import ADBDevice


def confirm(action, reason) -> bool:
    return input(f"Allow {action.describe()} ({reason})? [y/N] ").lower() == "y"


def main() -> None:
    device = ADBDevice()  # sole connected device/emulator
    llm = OpenAICompatibleClient(
        base_url="http://localhost:11434/v1",
        model="qwen2.5vl",
    )
    loop = AgentLoop(
        device=device,
        llm=llm,
        guard=CaptchaGuard(),
        policy=SafetyPolicy(require_confirmation=confirm),
        on_handoff=lambda h: print(f"Human takeover: {h.reason}"),
    )
    result = loop.run("Open the Settings app and navigate to the Battery screen")
    print(result.status, "-", result.summary)


if __name__ == "__main__":
    main()
