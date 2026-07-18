"""Visual self-check (2026-07-19) — the qualitative half of the self-verifying build loop: render the
current assembly as a blueprint, hand it to a VISION model, get back "does this read as what was asked
for?" This is what geometry can't quantify ("looks goofy", proportions off, wings sweep the wrong way).

GATED and OFF by default. The runtime delta-emitter is `deepseek/deepseek-chat` — text-only, CANNOT see
images. So this runs ONLY when a separate vision model is configured via the `VISION_MODEL` env var (the
"configurable vision model" the user approved). No `VISION_MODEL` / no API key -> `validate_visual`
returns None and the caller relies on the deterministic geometric check
(`packages/truth_plane/validate.py`) alone. The model call goes through the `OpenRouterDeltaProvider`
seam (`judge_image`), never a vendor SDK.

Returns the SAME `ValidationReport` shape as the geometric check so the two are uniform to consumers.
Its issues are `severity="warning"` (advisory qualitative judgment, never a hard gate) or `"info"`."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Optional

from packages.truth_plane.validate import ValidationIssue, ValidationReport

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger

_logger = logging.getLogger(__name__)

_PROMPT = """\
You are an aerospace/mechanical design reviewer. The image is an orthographic 3-view blueprint (FRONT,
TOP, RIGHT) of a CAD assembly, with labelled XYZ axes on each view (+X right, +Y aft, +Z up) and a
legend naming each coloured part. The user's design intent is:

    "{intent}"

Judge ONLY what the blueprint shows against that intent — shape, proportions, part layout, symmetry,
orientation. Do NOT invent requirements the user didn't state. Reply with ONLY a JSON object, no prose:
{{"ok": <true if it clearly matches the intent, false if something looks wrong>,
  "issues": [{{"severity": "warning"|"info", "message": "<one concrete, actionable observation>"}}],
  "summary": "<one short sentence>"}}
If it matches well, return "ok": true with an empty issues list."""


def vision_model_configured() -> bool:
    return bool(os.environ.get("VISION_MODEL"))


def validate_visual(
    ledger: "MasterParametricLedger",
    intent: str,
    *,
    api_key: Optional[str] = None,
    vision_model: Optional[str] = None,
) -> Optional[ValidationReport]:
    """Render the assembly's blueprint and have a vision model judge it against `intent`. Returns a
    `ValidationReport` (issues are warnings/info — advisory), or None when no vision model is
    configured, no API key is available, or anything in the path fails (the caller then relies on the
    geometric check alone — a missing visual check must NEVER fabricate a pass or block progress)."""
    model = vision_model or os.environ.get("VISION_MODEL")
    key = api_key or os.environ.get("OPENROUTER_API_KEY")
    if not model or not key:
        return None
    try:
        from packages.truth_plane.regen.blueprint import render_blueprint
        from packages.agents.openrouter_provider import OpenRouterDeltaProvider

        png = render_blueprint(ledger, title="Design self-check")
        provider = OpenRouterDeltaProvider(api_key=key)
        verdict = provider.judge_image(image_png=png, prompt=_PROMPT.format(intent=intent or "(none given)"),
                                       vision_model=model)
    except Exception:
        _logger.exception("visual validation failed; falling back to geometric-only")
        return None

    # No parseable verdict, or one without an explicit boolean `ok`: INCONCLUSIVE, not a pass. Returning
    # None makes the caller rely on the geometric check alone — never fabricate a visual green light
    # from a missing/garbled model reply (2026-07-19 review, two independent fabricated-pass paths).
    if not isinstance(verdict, dict) or not isinstance(verdict.get("ok"), bool):
        _logger.warning("vision verdict missing a boolean 'ok' — treating as inconclusive")
        return None

    raw_issues = verdict.get("issues") or []
    issues: list[ValidationIssue] = []
    for it in raw_issues:
        if not isinstance(it, dict):
            continue
        sev = it.get("severity", "warning")
        if sev not in ("warning", "info"):
            sev = "warning"  # the visual judgment is advisory; never an error-severity hard block
        issues.append(ValidationIssue(check="visual", severity=sev,
                                      message=str(it.get("message", "")).strip()[:400], instances=[]))
    ok = bool(verdict["ok"]) and not any(i.severity == "warning" for i in issues)
    summary = str(verdict.get("summary", "")).strip()[:400] or ("looks right" if ok else "possible visual issues")
    return ValidationReport(ok=ok, issues=issues, summary=f"[vision] {summary}")
