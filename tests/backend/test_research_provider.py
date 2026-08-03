import os

import pytest

from packages.agents.research_provider import (
    BingResearchProvider,
    DuckDuckGoResearchProvider,
    NotConfiguredResearchProvider,
    ResearchFinding,
    ResearchProvider,
    _ddg_target_url,
    get_research_provider,
    research_provider_configured,
)


def _clear_research_env(monkeypatch):
    monkeypatch.delenv("RESEARCH_PROVIDER_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_PROVIDER", raising=False)


def test_get_research_provider_returns_not_configured_without_a_key(monkeypatch):
    _clear_research_env(monkeypatch)
    provider = get_research_provider()
    assert isinstance(provider, NotConfiguredResearchProvider)
    assert provider.research("anything") is None


def test_get_research_provider_returns_duckduckgo_when_selected(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER", "duckduckgo")
    assert isinstance(get_research_provider(), DuckDuckGoResearchProvider)
    assert research_provider_configured() is True


def test_get_research_provider_is_case_insensitive_for_the_selector(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER", "DuckDuckGo")
    assert isinstance(get_research_provider(), DuckDuckGoResearchProvider)


def test_bing_key_takes_priority_over_duckduckgo_selector(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER_API_KEY", "test-key")
    monkeypatch.setenv("RESEARCH_PROVIDER", "duckduckgo")
    assert isinstance(get_research_provider(), BingResearchProvider)


def test_an_unrecognized_selector_value_stays_not_configured(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER", "google")  # not wired in — must not silently no-op-pass
    assert isinstance(get_research_provider(), NotConfiguredResearchProvider)
    assert research_provider_configured() is False


def test_get_research_provider_returns_bing_when_a_key_is_set(monkeypatch):
    _clear_research_env(monkeypatch)
    monkeypatch.setenv("RESEARCH_PROVIDER_API_KEY", "test-key")
    provider = get_research_provider()
    assert isinstance(provider, BingResearchProvider)
    assert provider.api_key == "test-key"


def test_not_configured_provider_always_returns_none():
    provider = NotConfiguredResearchProvider()
    assert provider.research("adjustable laptop stand") is None


def test_research_provider_configured_false_without_env_var(monkeypatch):
    monkeypatch.delenv("RESEARCH_PROVIDER_API_KEY", raising=False)
    assert research_provider_configured() is False


def test_research_provider_configured_true_with_env_var(monkeypatch):
    monkeypatch.setenv("RESEARCH_PROVIDER_API_KEY", "test-key")
    assert research_provider_configured() is True


def test_research_finding_rejects_unknown_fields():
    with pytest.raises(Exception):
        ResearchFinding(query="x", summary="y", not_a_real_field=True)


def test_research_finding_has_no_dimension_field():
    # Hard scope limit (see research_provider.py's module docstring): a finding must never carry a
    # dimensional claim — confirm no such field exists so a future edit can't silently add one back.
    fields = set(ResearchFinding.model_fields.keys())
    banned_suffixes = ("_mm", "_deg", "_kg", "_g")
    banned_words = ("dimension", "width", "height", "length", "depth", "diameter", "thickness")
    assert not any(f.endswith(banned_suffixes) for f in fields)
    assert not any(word in f.lower() for f in fields for word in banned_words)


def test_research_finding_defaults_and_disclaimer():
    finding = ResearchFinding(query="adjustable laptop stand", summary="riser + hinge + platform")
    assert finding.suggested_subsystem_types == []
    assert finding.source_urls == []
    assert finding.image_urls == []
    assert "not a dimensional" in finding.disclaimer


class _FakeResearchProvider(ResearchProvider):
    """Test double mirroring test_openrouter_provider.py's injected-fake convention."""

    def __init__(self, finding: "ResearchFinding | None"):
        self._finding = finding

    def research(self, query: str) -> "ResearchFinding | None":
        return self._finding


def test_fake_research_provider_returns_injected_finding():
    finding = ResearchFinding(
        query="adjustable laptop stand",
        summary="typical adjustable laptop stands use a riser arm/hinge and a platform, not a rigid table",
        suggested_subsystem_types=["hinge", "flat_bar"],
    )
    provider = _FakeResearchProvider(finding)
    assert provider.research("adjustable laptop stand") is finding


# --- BingResearchProvider: real vendor wiring, tested with an injected fake `get` (no real network) --


_WEB_RESPONSE = {
    "webPages": {"value": [
        {"name": "Adjustable Laptop Stands", "url": "https://example.com/a",
         "snippet": "Most adjustable laptop stands use a hinge and riser arm to set height and tilt."},
        {"name": "Best Laptop Risers 2026", "url": "https://example.com/b",
         "snippet": "A folding hinge lets the platform tilt; a telescoping post lets it rise."},
    ]},
}
_IMAGE_RESPONSE = {"value": [
    {"contentUrl": "https://example.com/img1.jpg"},
    {"contentUrl": "https://example.com/img2.jpg"},
]}


def test_bing_provider_returns_a_finding_from_web_and_image_results():
    calls: list[str] = []

    def fake_get(*, url, headers, params):
        calls.append(url)
        assert headers["Ocp-Apim-Subscription-Key"] == "test-key"
        if "images" in url:
            return _IMAGE_RESPONSE
        return _WEB_RESPONSE

    provider = BingResearchProvider(api_key="test-key", get=fake_get)
    finding = provider.research("adjustable laptop stand")

    assert finding is not None
    assert "hinge" in finding.summary
    assert finding.source_urls == ["https://example.com/a", "https://example.com/b"]
    assert finding.image_urls == ["https://example.com/img1.jpg", "https://example.com/img2.jpg"]
    assert len(calls) == 2  # both the web and image endpoints were hit
    # Every suggestion must be a REAL registered catalog type — never invented — and the snippet
    # text here ("hinge", "riser arm", "telescoping post") should surface at least one real match.
    from packages.subsystems import SUBSYSTEM_REGISTRY
    assert 0 < len(finding.suggested_subsystem_types) <= 5
    assert all(name in SUBSYSTEM_REGISTRY for name in finding.suggested_subsystem_types)
    assert any("hinge" in name for name in finding.suggested_subsystem_types)


def test_bing_provider_returns_none_when_web_search_raises():
    def fake_get(*, url, headers, params):
        raise RuntimeError("simulated transport failure")

    provider = BingResearchProvider(api_key="test-key", get=fake_get)
    assert provider.research("adjustable laptop stand") is None


def test_bing_provider_returns_none_when_web_search_has_no_snippets():
    def fake_get(*, url, headers, params):
        return {"webPages": {"value": []}}

    provider = BingResearchProvider(api_key="test-key", get=fake_get)
    assert provider.research("something obscure") is None


def test_bing_provider_degrades_gracefully_when_only_image_search_fails():
    def fake_get(*, url, headers, params):
        if "images" in url:
            raise RuntimeError("simulated image endpoint failure")
        return _WEB_RESPONSE

    provider = BingResearchProvider(api_key="test-key", get=fake_get)
    finding = provider.research("adjustable laptop stand")
    assert finding is not None          # the web summary alone is still a real, usable finding
    assert finding.image_urls == []     # just no images, not a total failure


def test_bing_provider_returns_none_for_an_empty_query():
    provider = BingResearchProvider(api_key="test-key", get=lambda **kw: _WEB_RESPONSE)
    assert provider.research("   ") is None


# --- DuckDuckGoResearchProvider: real vendor wiring, no API key ------------------------------
#
# _DDG_LITE_HTML below is a trimmed, hand-reduced sample of the ACTUAL DuckDuckGo Lite markup
# (fetched and inspected directly, 2026-08-01, before writing the parser — see the plan this shipped
# under) — one sponsored result (to confirm it gets filtered, including its extra "more info" link
# that has no snippet of its own) followed by two organic results, in the exact real structure: a
# `<tr class="result-sponsored">`-wrapped link+snippet pair, then two independent
# `<a class='result-link'>` / `<td class='result-snippet'>` pairs, DDG's own click-tracking redirect
# wrapping every href.

_DDG_LITE_HTML = """
<html><body>
<table>
<tr class="result-sponsored">
<td valign="top">1.&nbsp;</td>
<td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fduckduckgo.com%2Fy.js%3Fad_domain%3Damazon.com&amp;rut=abc" class='result-link'>Sponsored Laptop Stands - Big Savings</a>
(Sponsored link - <a href="https://duckduckgo.com/duckduckgo-help-pages/company/ads-by-microsoft-on-duckduckgo-private-search/" rel="nofollow" class="result-link">more info</a>)
</td>
</tr>
<tr class="result-sponsored">
<td>&nbsp;</td>
<td class='result-snippet'>Ad copy that should never end up in the real summary.</td>
</tr>
<tr>
<td valign="top">2.&nbsp;</td>
<td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.wired.com%2Fgallery%2Fbest%2Dlaptop%2Dstands%2F&amp;rut=def" class='result-link'>Best Laptop Stands (2026)</a>
</td>
</tr>
<tr>
<td>&nbsp;</td>
<td class='result-snippet'>Our top picks for <b>laptop</b> <b>stands</b> and risers use a hinge and telescoping post.</td>
</tr>
<tr>
<td valign="top">3.&nbsp;</td>
<td>
<a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.amazon.com%2Fadjustable%2Dlaptop%2Dstand&amp;rut=ghi" class='result-link'>Amazon.com: Adjustable Laptop Stand</a>
</td>
</tr>
<tr>
<td>&nbsp;</td>
<td class='result-snippet'>A folding hinge lets the platform tilt while a riser arm sets the height.</td>
</tr>
</table>
</body></html>
"""


def test_ddg_target_url_unwraps_the_click_tracking_redirect():
    href = "//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.wired.com%2Fgallery%2Fbest%2Dlaptop%2Dstands%2F&rut=abc"
    assert _ddg_target_url(href) == "https://www.wired.com/gallery/best-laptop-stands/"


def test_duckduckgo_provider_returns_a_finding_and_excludes_sponsored_results():
    provider = DuckDuckGoResearchProvider(get=lambda **kw: _DDG_LITE_HTML)
    finding = provider.research("adjustable laptop stand")

    assert finding is not None
    assert "Ad copy" not in finding.summary
    assert "hinge" in finding.summary
    assert finding.image_urls == []  # DuckDuckGo Lite gives no image results — always empty
    assert finding.source_urls == [
        "https://www.wired.com/gallery/best-laptop-stands/",
        "https://www.amazon.com/adjustable-laptop-stand",
    ]
    # the "more info" link inside the sponsored block must not have leaked in as a phantom result
    assert not any("more info" in u or "ad_domain" in u for u in finding.source_urls)
    from packages.subsystems import SUBSYSTEM_REGISTRY
    assert all(name in SUBSYSTEM_REGISTRY for name in finding.suggested_subsystem_types)


def test_duckduckgo_provider_sends_a_user_agent_and_the_query():
    captured: dict = {}

    def fake_get(*, url, headers, params):
        captured["headers"] = headers
        captured["params"] = params
        return _DDG_LITE_HTML

    DuckDuckGoResearchProvider(get=fake_get).research("adjustable laptop stand")
    assert "User-Agent" in captured["headers"]
    assert captured["params"]["q"] == "adjustable laptop stand"


def test_duckduckgo_provider_returns_none_when_the_request_raises():
    def fake_get(*, url, headers, params):
        raise RuntimeError("simulated transport failure")

    provider = DuckDuckGoResearchProvider(get=fake_get)
    assert provider.research("adjustable laptop stand") is None


def test_duckduckgo_provider_returns_none_for_a_page_with_no_results():
    provider = DuckDuckGoResearchProvider(get=lambda **kw: "<html><body>no results</body></html>")
    assert provider.research("something with zero hits") is None


def test_duckduckgo_provider_returns_none_for_an_empty_query():
    provider = DuckDuckGoResearchProvider(get=lambda **kw: _DDG_LITE_HTML)
    assert provider.research("   ") is None


def test_duckduckgo_provider_returns_none_when_every_result_is_sponsored():
    only_sponsored = """
    <table>
    <tr class="result-sponsored">
    <td>1.</td>
    <td><a href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com" class='result-link'>Ad</a></td>
    </tr>
    <tr class="result-sponsored">
    <td>&nbsp;</td>
    <td class='result-snippet'>Pure ad copy, nothing organic.</td>
    </tr>
    </table>
    """
    provider = DuckDuckGoResearchProvider(get=lambda **kw: only_sponsored)
    assert provider.research("adjustable laptop stand") is None
