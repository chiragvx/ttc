"""Provider selection — OpenRouter (DeepSeek) when a key is set, otherwise NO LLM.

There is no mock fallback: if no key is configured, `get_provider` returns None and callers must show
a "no LLM configured" state rather than silently faking results.
"""

from __future__ import annotations

import os

from packages.agents.llm_provider import LLMProvider


def get_provider(api_key: str | None = None, model: str | None = None) -> LLMProvider | None:
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return None
    from packages.agents.openrouter_provider import OpenRouterDeltaProvider
    return OpenRouterDeltaProvider(api_key=key, model=model)
