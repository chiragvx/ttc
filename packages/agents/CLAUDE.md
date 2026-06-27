# packages/agents — the runtime LLM layer

Runtime LLM = **OpenRouter** (OpenAI-compatible), default model **DeepSeek**
(`packages/agents/openrouter_provider.py`). Key via `OPENROUTER_API_KEY` (see `.env.example`).
Role split (enforced as routing, not prompt convention):
- **Strategic Systems Engineer** = a capable model on the human-timescale conversational turn.
- **Geometric delta-emitter** = a fast model on slider-release (the OpenRouter provider; forced function-calling).
- **Validator = NOT a model** — it lives in truth_plane as a rules/solver router.

Hard rules:
- Every model call goes through `LLMProvider`. Swap vendors by adding a provider class — never wire an
  SDK into call sites (`scripts/check_llm_provider_imports.py` still forbids `import anthropic` anywhere;
  the OpenRouter provider uses httpx, no vendor SDK).
- The delta-emitter is bound to `parameter_delta_tool_schema()` with forced `tool_choice` + strict
  mode. Its only output is a `DeltaProposal`. Free prose / Python must be impossible at the wire.
- Use a **manual** tool-use loop — a tool call is an AI-PROPOSED diff; a separate explicit human
  accept commits it. Never auto-apply geometry changes.
- Cache the schema/system/tools prefix; inject live solver verdicts as mid-conversation messages,
  NEVER at the front of the system prompt (a timestamp/UUID there zeroes the cache, ~10×'s cost).
- Wiring a real provider is Phase 1 — do not add SDK calls in Phase 0.
