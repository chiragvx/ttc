"""The reference-research seam (2026-08-01) — before the copilot decomposes a NEW compound design
into catalog parts, it may check what a real version of the object actually looks like, so it stops
forcing the nearest generic primitive onto something structurally different (the "a laptop stand is
not a table" failure: `table` got used for an adjustable-riser mechanism because it was the closest
menu item, not because it was right).

GATED and OFF by default, same shape as `vision_validator.py`'s `VISION_MODEL` gate:
`research_provider_configured()` is False, and `get_research_provider()` returns
`NotConfiguredResearchProvider` (every call a no-op — no network call, no cost), unless EITHER
`RESEARCH_PROVIDER_API_KEY` is set (selects `BingResearchProvider` — Bing Web + Image Search, Azure
Cognitive Services) OR `RESEARCH_PROVIDER=duckduckgo` is set (selects `DuckDuckGoResearchProvider` —
no credentials needed at all, the vendor this feature was first actually tried against live).
Adding a further vendor later is a new class here plus a branch in `get_research_provider()`, never
a change at a call site.

Hard scope limits (do not relax without re-reading the plan this shipped under):
- A `ResearchFinding` may only ever inform WHICH catalog part types get proposed
  (`suggested_subsystem_types`, cross-checked by the caller against the real subsystem registry,
  exactly like `InstanceOp.subsystem_type` already is at apply time) — it must NEVER be treated as a
  dimensional or manufacturer source. There is no dimension field on this model on purpose.
- Findings are untrusted external content once they reach an LLM's context. Originally (2026-08-01)
  the caller injected them as a deterministic pre-turn message regardless of the model's own
  judgment; that heuristic over-triggered (fired on literally any first message in an empty file)
  and was replaced the same day with `research_reference` (`ResearchQuery`/`research_tool_schema()`
  below) — a real tool the model itself decides to call, wired into the multi-round tool loop in
  `packages/agents/openrouter_provider.py::stream_chat`. This module still does not itself talk to
  any LLM; it only fetches and returns structured data for the caller to feed back as a tool result.
"""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class ResearchFinding(BaseModel):
    """A single research result for one query. Every field here is advisory reference data, never a
    verified source — see this module's docstring for the hard scope limits."""

    model_config = ConfigDict(extra="forbid")

    query: str
    summary: str                                       # topology/decomposition description ONLY
    suggested_subsystem_types: list[str] = Field(default_factory=list)  # catalog names, unchecked here
    source_urls: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    disclaimer: str = "Reference only — not a dimensional or manufacturer source."


def research_provider_configured() -> bool:
    return bool(os.environ.get("RESEARCH_PROVIDER_API_KEY")) or _duckduckgo_selected()


class ResearchQuery(BaseModel):
    """Arguments for the `research_reference` tool (`research_tool_schema()` below) — the model's own
    decision to look something up, replacing the old deterministic pre-turn heuristic this feature
    originally shipped with (2026-08-01). One field on purpose: the model supplies a short, specific
    search query, never a structured object — `research()` above already does all the real work."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(description=(
        "A short, specific search query describing the real-world object or mechanism you need "
        "reference material for — e.g. 'adjustable laptop stand riser mechanism', not a verbatim "
        "restatement of the whole user request."
    ))


def research_tool_schema() -> dict:
    """The JSON Schema handed to the LLM tool-use API for `research_reference` — same convention as
    `packages/ledger/deltas.py::parameter_delta_tool_schema()` (a Pydantic model's own
    `.model_json_schema()`, `extra=\"forbid\"` so a stray extra field fails loudly)."""
    return ResearchQuery.model_json_schema()


def _duckduckgo_selected() -> bool:
    return os.environ.get("RESEARCH_PROVIDER", "").strip().lower() == "duckduckgo"


class ResearchProvider(ABC):
    """One method, mirroring `packages/agents/llm_provider.py::LLMProvider`'s shape: a single seam,
    swap vendors by adding a class here, never wire a vendor SDK into a call site."""

    @abstractmethod
    def research(self, query: str) -> "ResearchFinding | None":
        """Look up reference images/descriptions for `query`. Returns None on ANY failure (not
        configured, transport error, unparseable vendor response) — a caller must never fabricate a
        finding, same discipline as `vision_validator.py::validate_visual`."""
        raise NotImplementedError


class NotConfiguredResearchProvider(ResearchProvider):
    """The only concrete implementation shipped so far. Wiring a real search/image vendor (Bing/
    Google/SerpAPI/other) is deliberately deferred follow-up work, not part of this seam's initial
    landing — see the plan this shipped under. Until then this makes the whole feature an inert
    no-op end to end: no network call, no cost, no behavior change."""

    def research(self, query: str) -> None:
        return None


_BING_WEB_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/search"
_BING_IMAGE_SEARCH_URL = "https://api.bing.microsoft.com/v7.0/images/search"
_MAX_WEB_RESULTS = 5
_MAX_IMAGE_RESULTS = 4
_MAX_SUGGESTED_TYPES = 5
_MAX_SUMMARY_CHARS = 600

# Words too generic to usefully match a snippet's vocabulary against a subsystem's description —
# without this, near-every subsystem description shares enough of these to look like a match.
_SUGGEST_STOPWORDS = frozenset({
    "a", "an", "the", "for", "with", "of", "and", "to", "is", "are", "this", "that", "it", "its",
    "in", "on", "at", "as", "be", "one", "two", "typical", "typically", "part", "parts",
})


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower())) - _SUGGEST_STOPWORDS


def _suggest_subsystem_types(text: str) -> list[str]:
    """Cross-reference free text (search-result snippets) against the REAL catalog registry —
    `suggested_subsystem_types` must only ever contain names a caller could actually build with, so
    this is computed here rather than trusting anything vendor-supplied. Same tokenize-and-overlap
    idea as `packages/transport/app.py::_research_query_for`'s trigger heuristic, applied the other
    direction (which registered types does this TEXT sound like) — kept in this module rather than
    imported from there since the two heuristics answer different questions and re-deriving the
    small helper is cheaper than coupling this module to transport's."""
    from packages.subsystems import SUBSYSTEM_REGISTRY

    text_tokens = _tokenize(text)
    if not text_tokens:
        return []
    scored: list[tuple[int, str]] = []
    for name, subsystem in SUBSYSTEM_REGISTRY.items():
        overlap = len(text_tokens & (_tokenize(name) | _tokenize(subsystem.description)))
        if overlap > 0:
            scored.append((overlap, name))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))  # highest overlap first, name as a tiebreaker
    return [name for _, name in scored[:_MAX_SUGGESTED_TYPES]]


class BingResearchProvider(ResearchProvider):
    """Wires the deferred vendor decision to Bing Web + Image Search (Azure Cognitive Services) — one
    subscription key covers both endpoints. Never raises: any transport/parse failure degrades to
    None, same discipline as `vision_validator.py::validate_visual` and
    `NotConfiguredResearchProvider` — a caller must never fabricate a finding from a broken vendor
    response. `get=None` mirrors `OpenRouterDeltaProvider`'s injectable `post=`/`stream_post=`
    pattern, so tests never make a real network call."""

    def __init__(self, *, api_key: str, web_search_url: str | None = None,
                 image_search_url: str | None = None, get=None) -> None:
        self.api_key = api_key
        self.web_search_url = web_search_url or os.environ.get("BING_WEB_SEARCH_URL", _BING_WEB_SEARCH_URL)
        self.image_search_url = image_search_url or os.environ.get("BING_IMAGE_SEARCH_URL", _BING_IMAGE_SEARCH_URL)
        self._get = get  # injectable (url=, headers=, params=) -> dict, for tests

    def _do_get(self, url: str, params: dict) -> dict:
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        if self._get is not None:
            return self._get(url=url, headers=headers, params=params)
        import httpx
        resp = httpx.get(url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.json()

    def research(self, query: str) -> "ResearchFinding | None":
        if not query or not query.strip():
            return None
        try:
            web = self._do_get(self.web_search_url, {
                "q": query, "count": _MAX_WEB_RESULTS, "textDecorations": "false", "textFormat": "Raw",
            })
        except Exception:
            logger.exception("Bing web search failed for query %r", query)
            return None
        web_results = ((web or {}).get("webPages") or {}).get("value") or []
        if not isinstance(web_results, list):
            web_results = []
        snippets = [str(r.get("snippet", "")).strip() for r in web_results
                    if isinstance(r, dict) and r.get("snippet")]
        if not snippets:
            # No genuine result — return None (inconclusive), never a finding with an empty summary.
            return None
        source_urls = [str(r.get("url", "")).strip() for r in web_results
                       if isinstance(r, dict) and r.get("url")][:_MAX_WEB_RESULTS]
        summary = " ".join(snippets[:3])[:_MAX_SUMMARY_CHARS]

        image_urls: list[str] = []
        try:
            images = self._do_get(self.image_search_url, {"q": query, "count": _MAX_IMAGE_RESULTS})
            for im in ((images or {}).get("value") or [])[:_MAX_IMAGE_RESULTS]:
                if isinstance(im, dict) and im.get("contentUrl"):
                    image_urls.append(str(im["contentUrl"]))
        except Exception:
            # Image search failing is not fatal — the web-snippet summary above still stands; only a
            # fully-failed WEB search returns None (see above).
            logger.warning("Bing image search failed for query %r — continuing with web results only", query)

        return ResearchFinding(
            query=query,
            summary=summary,
            suggested_subsystem_types=_suggest_subsystem_types(summary + " " + " ".join(snippets)),
            source_urls=source_urls,
            image_urls=image_urls,
        )


_DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
_DDG_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# DuckDuckGo Lite (2026-08-01 markup, fetched and inspected directly before writing this — see the
# plan this shipped under): a plain, JS-free, table-based results page. Each result is a
# `<a ... class='result-link'>TITLE</a>` followed by a separate `<td class='result-snippet'>...</td>`
# row, in the SAME order — no single wrapping element ties a title to its snippet, so they're matched
# up positionally below. `href` wraps the real target in DDG's own click-tracking redirect
# (`//duckduckgo.com/l/?uddg=<url-encoded target>&rut=...`), unwrapped by `_ddg_target_url`.
#
# Sponsored rows are stripped FIRST, before that positional pairing happens — each one is a whole
# `<tr class="result-sponsored">...</tr>` block containing BOTH its own result-link and result-snippet
# (so it would otherwise pair correctly on its own) AND an extra "(Sponsored link - <a ...>more
# info</a>)" link with no snippet of its own, which would silently misalign every result-link/
# result-snippet pairing after it. Dropping the whole block avoids both problems at once, and as a
# side effect keeps `source_urls` pointing at real destination pages instead of ad-click redirects.
_DDG_SPONSORED_ROW_RE = re.compile(r"<tr class=\"result-sponsored\">.*?</tr>", re.DOTALL)
_DDG_RESULT_LINK_RE = re.compile(
    r"<a[^>]+href=\"([^\"]+)\"[^>]*class='result-link'[^>]*>(.*?)</a>", re.DOTALL)
_DDG_SNIPPET_RE = re.compile(r"<td class='result-snippet'>(.*?)</td>", re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    import html
    return html.unescape(_HTML_TAG_RE.sub("", s)).strip()


def _ddg_target_url(href: str) -> str:
    import urllib.parse
    absolute = f"https:{href}" if href.startswith("//") else href
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(absolute).query)
    target = qs.get("uddg", [None])[0]
    return target or absolute


class DuckDuckGoResearchProvider(ResearchProvider):
    """No API key required — scrapes DuckDuckGo's own "Lite" HTML results page (a plain, JS-free
    page DDG serves for exactly this kind of lightweight client), no vendor account/quota to set up.
    This is the FIRST vendor this feature was actually tried against live, specifically because it
    needed zero credentials. Same never-fabricate discipline as every other provider here: any
    transport/parse failure (including DuckDuckGo changing its markup — an HTML-scraping approach is
    inherently exposed to that in a way an official API isn't) degrades to None, never a fake
    finding. No image search — DuckDuckGo's image endpoint needs a token minted from a prior page
    load, real extra complexity not worth it for this first vendor; `image_urls` is always empty
    from this provider. `get=None` mirrors every other provider's injectable-callable test pattern —
    tests never make a real network call."""

    def __init__(self, *, url: str | None = None, get=None) -> None:
        self.url = url or os.environ.get("DUCKDUCKGO_LITE_URL", _DDG_LITE_URL)
        self._get = get  # injectable (url=, headers=, params=) -> str (raw HTML), for tests

    def _do_get(self, params: dict) -> str:
        headers = {"User-Agent": _DDG_USER_AGENT}
        if self._get is not None:
            return self._get(url=self.url, headers=headers, params=params)
        import httpx
        resp = httpx.get(self.url, headers=headers, params=params, timeout=10.0)
        resp.raise_for_status()
        return resp.text

    def research(self, query: str) -> "ResearchFinding | None":
        if not query or not query.strip():
            return None
        try:
            html_text = self._do_get({"q": query})
        except Exception:
            logger.exception("DuckDuckGo lite search failed for query %r", query)
            return None
        try:
            organic_html = _DDG_SPONSORED_ROW_RE.sub("", html_text)
            links = _DDG_RESULT_LINK_RE.findall(organic_html)
            snippet_texts = [_strip_html(s) for s in _DDG_SNIPPET_RE.findall(organic_html)]
        except Exception:
            logger.exception("DuckDuckGo lite response could not be parsed for query %r", query)
            return None
        n = min(len(links), len(snippet_texts))
        if n == 0:
            return None
        source_urls = [u for u in (_ddg_target_url(h) for h, _ in links[:n]) if u][:_MAX_WEB_RESULTS]
        snippet_texts = snippet_texts[:n]
        summary = " ".join(snippet_texts[:3])[:_MAX_SUMMARY_CHARS].strip()
        if not summary:
            return None
        return ResearchFinding(
            query=query,
            summary=summary,
            suggested_subsystem_types=_suggest_subsystem_types(summary + " " + " ".join(snippet_texts)),
            source_urls=source_urls,
            image_urls=[],
        )


def get_research_provider() -> ResearchProvider:
    """Mirrors `packages/agents/provider_factory.py::get_provider`'s shape: one place a caller asks
    for "the current provider" — swapping/adding vendors later is a one-line change here, never at a
    call site. Always returns SOMETHING (never None); `NotConfiguredResearchProvider` IS the "no
    vendor wired" state, so callers call `.research(...)` unconditionally and only branch on ITS
    return value. `RESEARCH_PROVIDER_API_KEY` (Bing) takes priority when set — a real vendor account
    with quota is preferable once you have one; `RESEARCH_PROVIDER=duckduckgo` selects the
    no-credentials-needed vendor otherwise."""
    key = os.environ.get("RESEARCH_PROVIDER_API_KEY")
    if key:
        return BingResearchProvider(api_key=key)
    if _duckduckgo_selected():
        return DuckDuckGoResearchProvider()
    return NotConfiguredResearchProvider()
