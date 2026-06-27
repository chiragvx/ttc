"""Provider selection — OpenRouter (DeepSeek) when a key is set, else the offline mock.

Keeps call sites vendor-agnostic: everything depends on `LLMProvider`, and this is the one place that
decides which concrete provider to instantiate from the environment.
"""

from __future__ import annotations

import os

from packages.agents.llm_provider import LLMProvider


def get_provider() -> LLMProvider:
    if os.environ.get("OPENROUTER_API_KEY"):
        from packages.agents.openrouter_provider import OpenRouterDeltaProvider
        return OpenRouterDeltaProvider()
    from packages.agents.mock_provider import MockProvider
    return MockProvider()
