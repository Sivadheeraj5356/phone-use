"""Pluggable LLM backends.

The agent loop talks to any object implementing :class:`LLMClient`.
An OpenAI-compatible chat-completions client (stdlib ``urllib`` only)
covers hosted providers such as OpenRouter as well as local servers
like Ollama's OpenAI shim or llama.cpp's server. Bring your own
endpoint and key; nothing here is tied to a paid provider.
"""

from __future__ import annotations

import base64
import json
import urllib.request
from typing import List, Optional, Protocol


class LLMClient(Protocol):
    """Minimal interface the agent loop needs."""

    def step(self, *, system: str, history: List[dict],
             screenshot_png: Optional[bytes], screen_text: str) -> str:
        """Return the model's raw reply for one agent step."""
        ...


class OpenAICompatibleClient:
    """Chat-completions client with optional image input.

    ``model`` must be a vision-capable model id at the chosen
    ``base_url`` for screenshots to be used; when the endpoint or
    model cannot take images, pass ``send_images=False`` and the agent
    works from the UI-tree text alone.
    """

    def __init__(self, *, base_url: str, api_key: str = "", model: str,
                 send_images: bool = True, timeout: int = 60,
                 extra_headers: Optional[dict] = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.send_images = send_images
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def step(self, *, system: str, history: List[dict],
             screenshot_png: Optional[bytes], screen_text: str) -> str:
        content: list = []
        if self.send_images and screenshot_png:
            b64 = base64.b64encode(screenshot_png).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })
        content.append({
            "type": "text",
            "text": "Current UI hierarchy (text/ids/bounds):\n" + screen_text,
        })
        messages = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": content})
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "max_tokens": 600,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]


class MockLLM:
    """Scripted backend for tests and dry runs.

    Replies are consumed in order; when the script runs out the mock
    raises, so a test that loops forever fails loudly instead of
    hanging.
    """

    def __init__(self, replies: List[str]):
        self._replies = list(replies)
        self.calls: List[dict] = []

    def step(self, *, system: str, history: List[dict],
             screenshot_png: Optional[bytes], screen_text: str) -> str:
        self.calls.append({"system": system, "screen_text": screen_text})
        if not self._replies:
            raise RuntimeError("MockLLM script exhausted")
        return self._replies.pop(0)
