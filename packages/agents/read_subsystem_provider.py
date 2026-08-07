"""The subsystem-source-read seam (Phase 4 of the AI-generated-custom-geometry plan, 2026-08-06) —
before the copilot writes NEW, genuinely custom build123d geometry (a LATER phase's
`propose_custom_geometry` write tool, not built here), it may read an EXISTING, already-reviewed
catalog subsystem's own `build()` source as a concrete reference for a technique it needs — a
bellmouth intake wants to see `lofted_spindle.py`'s loft technique, not `bracket.py`'s plain
extrude-and-cut. Confirmed directly valuable by the user this session (see
C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md) before this was built.

Same seam shape as `research_provider.py`'s (a schema + a tool-name-returning schema function + a
never-raising resolver + an env-var-gated `*_configured()`/`*_enabled()` predicate, all consumed by
`packages/agents/openrouter_provider.py::stream_chat`'s tool loop) — deliberately mirrored so the two
read-only "look something up before deciding" tools stay recognizably the same *shape* of thing to
future maintainers, not two unrelated ad-hoc mechanisms that happen to sit near each other.

The one deliberate divergence: `read_subsystem_source_enabled()` below defaults to ON, where
`research_provider_configured()` defaults OFF — see that function's own docstring for why. Every byte
this module can ever return is the project's OWN, already-committed, already-code-reviewed catalog
source; it never makes a network call and never carries `research_provider.py`'s "untrusted external
content reaching an LLM's context" risk.

This module only supplies the schema + the resolver function — it does not know the tool loop exists.
Wiring into `stream_chat`'s generic `{tool_name: handler}` continuation dispatch is entirely
`openrouter_provider.py`'s concern, same separation `research_provider.py` already keeps."""

from __future__ import annotations

import inspect
import logging
import os

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# Mirrors research_provider.py::_MAX_SUMMARY_CHARS's role (a hard cap on how much of a tool result
# rides into the conversation) — sized for SOURCE CODE rather than a search snippet: large enough to
# carry a typical subsystem's whole `build()` (lofted_spindle's — the exact motivating case named in
# this phase's plan — is ~2.5KB), small enough that one abnormally large `build` (e.g. a composite
# subsystem inlining several child builds) can't unboundedly balloon a single chat turn's context the
# way an unbounded file dump would.
_MAX_SOURCE_CHARS = 6000


def read_subsystem_source_enabled() -> bool:
    """Same plain `os.environ.get(...)` shape as
    `research_provider.py::research_provider_configured()`, but DEFAULT-ON rather than default-off:
    this tool only ever returns the project's own catalog source — already committed, already
    code-reviewed — never external/untrusted content fetched over the network, so there is none of
    `research_reference`'s "an LLM ingesting unverified web content" risk to gate behind an opt-in by
    default. Set `ENABLE_SUBSYSTEM_SOURCE_READ=0` (or `false`/`no`/`off`) to turn it off explicitly —
    e.g. to keep a fixed, reproducible tool roster for an eval run, or if a deployment wants to
    minimize the tool surface offered to the model for some other reason."""
    raw = os.environ.get("ENABLE_SUBSYSTEM_SOURCE_READ", "1")
    return raw.strip().lower() not in ("0", "false", "no", "off")


class SubsystemSourceQuery(BaseModel):
    """Arguments for the `read_subsystem_source` tool (`read_subsystem_source_tool_schema()` below) —
    one field on purpose, same convention as `research_provider.py::ResearchQuery`: the model supplies
    just the exact catalog name it wants to see, never a structured object or a free-text description
    — `read_subsystem_source()` below does all the real lookup work."""

    model_config = ConfigDict(extra="forbid")

    subsystem_name: str = Field(description=(
        "The exact registered catalog subsystem name to read reference build123d source for (e.g. "
        "'lofted_spindle', 'bracket') — not a free-text description of the part. Use a name you "
        "already believe is registered (from the catalog already described in your system prompt); "
        "an unregistered name returns a clear not-found result, not an error, so it is safe to try."
    ))


def read_subsystem_source_tool_schema() -> dict:
    """The JSON Schema handed to the LLM tool-use API for `read_subsystem_source` — same convention as
    `research_provider.py::research_tool_schema()` (a Pydantic model's own `.model_json_schema()`,
    `extra="forbid"` so a stray extra field fails loudly)."""
    return SubsystemSourceQuery.model_json_schema()


def read_subsystem_source(name: str) -> str:
    """Return `name`'s registered `build()` callable's real source text, or a clear, short,
    human-readable explanation of why it isn't available. NEVER raises, on any failure — an unknown
    name, a subsystem with no `build` of its own (an assembly-template/master-param node), or
    `inspect.getsource` failing on a dynamically-built/exotic callable are all turned into a plain
    string, never an exception and never fabricated source. Always returns a string, never `None`: a
    model that called this tool always gets a concrete tool-result message back, matching every other
    provider in this codebase's discipline of never silently dropping a tool call's result."""
    try:
        from packages.subsystems import get_subsystem_model
    except Exception:
        logger.exception("read_subsystem_source: could not import the subsystem registry")
        return "Subsystem source is not available right now (the catalog registry could not be loaded)."
    try:
        subsystem = get_subsystem_model(name)
    except KeyError:
        return f"No subsystem named {name!r} is registered in the catalog."
    except Exception:
        logger.exception("read_subsystem_source: unexpected failure looking up %r", name)
        return f"Subsystem {name!r} could not be looked up."
    build_fn = subsystem.build
    if build_fn is None:
        return (f"Subsystem {name!r} has no build() source of its own to show (e.g. an "
                f"assembly-template/master-param node whose children carry the real geometry).")
    try:
        source = inspect.getsource(build_fn)
    except Exception as e:
        # inspect.getsource can raise OSError (no source file — e.g. a dynamically generated
        # function), TypeError (not a module/class/method/function/traceback/frame/code object), or
        # something else entirely for a genuinely exotic callable — every one of them means "can't
        # show real source", never a fabricated stand-in, so this is deliberately a broad catch, not
        # just `except OSError`.
        logger.warning("read_subsystem_source: inspect.getsource failed for %r (%s)", name, e)
        return f"Source for {name!r} is not available (could not be resolved from its build() callable)."
    if len(source) > _MAX_SOURCE_CHARS:
        source = source[:_MAX_SOURCE_CHARS] + "\n... (truncated)"
    return source
