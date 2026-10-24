"""phone-use: give AI agents a phone.

Like computer-use, but for Android. Agents perceive the screen
(screenshot + UI hierarchy), decide on an action, and execute it
through ADB - with a safety layer that detects CAPTCHAs and other
human-only challenges and hands off to a person instead of trying
to defeat them.
"""

from .actions import Action, ActionError, parse_action
from .safety import CaptchaGuard, HandoffRequired, SafetyPolicy
from .agent import AgentLoop, AgentResult
from .llm import LLMClient, MockLLM, OpenAICompatibleClient

__version__ = "0.1.0"

__all__ = [
    "Action",
    "ActionError",
    "parse_action",
    "CaptchaGuard",
    "HandoffRequired",
    "SafetyPolicy",
    "AgentLoop",
    "AgentResult",
    "LLMClient",
    "MockLLM",
    "OpenAICompatibleClient",
    "__version__",
]
