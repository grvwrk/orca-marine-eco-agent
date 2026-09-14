"""Small provider boundary with Groq and HTTP fallback support."""

import json
import os
from collections.abc import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen


def _groq(prompt: str) -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    payload = json.dumps({
        "model": os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }).encode()
    request = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read())["choices"][0]["message"]["content"]


def _fallback_http(prompt: str) -> str:
    endpoint = os.getenv("ORCA_FALLBACK_URL")
    if not endpoint:
        raise RuntimeError("ORCA_FALLBACK_URL is not configured")
    payload = json.dumps({"prompt": prompt}).encode()
    with urlopen(Request(endpoint, data=payload, headers={"Content-Type": "application/json"}), timeout=8) as response:
        return json.loads(response.read())["text"]


def complete(prompt: str, fallback: Callable[[], str]) -> str:
    """Try primary and secondary providers once each, then use local fallback."""
    for provider in (_groq, _fallback_http):
        try:
            return provider(prompt)
        except (RuntimeError, TimeoutError, URLError, OSError, KeyError, ValueError):
            continue
    return fallback()
