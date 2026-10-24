# phone-use

Give AI agents a phone. Like [computer-use](https://www.anthropic.com/news/3-5-models-and-computer-use), but for Android.

`phone-use` is a small Python framework that lets an LLM agent operate an Android phone or emulator you own or are authorized to control. The agent perceives the screen (screenshot + accessibility UI tree), decides the next action, and executes it over ADB: tap, swipe, type, key events, app launches.

```python
from phone_use import AgentLoop, CaptchaGuard, OpenAICompatibleClient, SafetyPolicy
from phone_use.adb import ADBDevice

loop = AgentLoop(
    device=ADBDevice(),                      # any adb-connected device/emulator
    llm=OpenAICompatibleClient(
        base_url="http://localhost:11434/v1",  # local Ollama, or any
        model="qwen2.5vl",                     # OpenAI-compatible endpoint
    ),
    guard=CaptchaGuard(),                    # stops on human-verification screens
    policy=SafetyPolicy(),                   # payment apps need a human's OK
)
result = loop.run("Open Settings and turn on Battery Saver")
print(result.status, result.summary)
```

## On CAPTCHAs: detection and handoff, never bypass

When a CAPTCHA, "verify you are human", reCAPTCHA/hCaptcha/Cloudflare challenge, or image-selection grid appears, the agent **stops and hands off to a human**. It saves what it saw and tells you why. This project does not, and will not, solve, bypass, or route around anti-bot protections, and it does not integrate CAPTCHA-solving services. Pull requests that add bypass behavior will not be merged.

Additional safety rails:

- **Protected apps** (payment/banking apps by default) - every action requires a human confirmation callback; without one the framework fails closed.
- **Blocked packages** - a hard denylist of apps the agent refuses to open or act inside.
- **Bounded autonomy** - max step count, malformed-output retries, and a full action log for every run.
- Only run this against phones you own or emulators you control, and respect the terms of the apps and sites you automate.

## Setup

Requirements: Python 3.9+, the Android SDK platform-tools (`adb` on PATH), and a target:

- **Emulator**: Android Studio's AVD, or `adb connect` to a remote one.
- **Physical phone**: enable Developer options > USB debugging, plug in, `adb devices`, accept the prompt on the phone.

```bash
pip install -r requirements.txt   # core is stdlib-only; this is just pytest
python -m phone_use devices       # confirm your device shows up
python -m phone_use screenshot /tmp/screen.png
```

## Picking a model

The agent needs a vision-capable, OpenAI-compatible chat endpoint. Two zero-cost routes:

- **Fully local**: `ollama pull qwen2.5vl` then `ollama serve`, and use `--base-url http://localhost:11434/v1`.
- **OpenRouter free tier** (free account, no card): as of 2026-10-25 the live model API lists free vision models including `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free` and `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free`. Check `https://openrouter.ai/api/v1/models` for the current `:free` list before relying on it - free availability changes.

Text-only mode (`--no-images`) works from the accessibility UI tree alone, for models without image input.

## CLI

```bash
python -m phone_use devices
python -m phone_use screenshot out.png
python -m phone_use run "Open Chrome and search for weather in Surat" \
    --model qwen2.5vl --base-url http://localhost:11434/v1
```

## Architecture

```
phone_use/
  adb.py      ADBDevice: screenshots, UI tree, tap/swipe/type/key/launch over adb
  actions.py  Action dataclass + tolerant JSON parser for model replies
  safety.py   CaptchaGuard (challenge detection -> HandoffRequired) + SafetyPolicy
  agent.py    AgentLoop: perceive -> think -> act, with retries and step limits
  llm.py      LLMClient protocol, OpenAI-compatible client, MockLLM for tests
  cli.py      devices / screenshot / run commands
tests/        Unit tests against an in-memory fake device (no phone needed)
examples/     Real-device quickstart
```

## Testing - and what it does and doesn't prove

Two levels of automated evidence:

1. **Unit tests (fake device):** `python -m pytest tests/ -q` runs 30 tests against a scripted in-memory device - action parsing, CAPTCHA-detection handoff, payment-app gating, retry and step-limit behavior.
2. **Real emulator integration smoke test:** the `emulator-smoke` GitHub Actions workflow (free on this public repo) boots a real Android emulator and exercises `ADBDevice` end to end - boot wait, screen size, screenshot, UI hierarchy, a HOME key press and a tap. Latest passing run: https://github.com/Sivadheeraj5356/phone-use/actions/runs/40135913402

Together these prove framework logic plus screenshot/UI-tree/action-level operation against a real emulator. They do **not** prove a full LLM-agent task completed end to end on a device - `examples/quickstart.py` is the path for that, and contributions of recorded real-device agent runs are welcome.

## License

MIT - see [LICENSE](LICENSE).
