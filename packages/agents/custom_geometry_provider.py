"""The subsystem-WRITE seam (Phase 5 of the AI-generated-custom-geometry initiative, 2026-08-06) --
lets the copilot propose genuinely CUSTOM build123d geometry as a brand-new, permanent catalog
subsystem, by wiring Phase 3's already-built-and-verified registration gate
(`packages/subsystems/generated_registration.py::register_generated_subsystem`) into a real
conversational tool call. See the 7-phase plan this implements:
C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md.

Same seam shape as `research_provider.py`/`read_subsystem_provider.py` (a schema + a
tool-name-returning schema function + an env-var-gated `*_enabled()` predicate, all consumed by
`packages/agents/openrouter_provider.py::stream_chat`'s continuation-tool dispatch) -- deliberately
mirrored so a future maintainer recognizes this as the same *shape* of thing, not a third unrelated
ad-hoc mechanism.

The one deliberate divergence: `custom_geometry_enabled()` below defaults OFF, where
`read_subsystem_source_enabled()` defaults ON. `read_subsystem_source` is read-only (it can only ever
return the project's own already-committed, already-code-reviewed catalog source); THIS tool's whole
point is to write a brand-new, permanent catalog subsystem into `packages/subsystems/generated/` and
import it in-process -- a real write/registration consequence, not a lookup -- so it stays an explicit
opt-in via `ENABLE_AI_GENERATED_SUBSYSTEMS` until a deployment has decided it wants that.

This module ONLY supplies the schema + the Pydantic model that parses the LLM-CONTROLLED subset of a
`GeneratedSubsystemCandidate` (see that model's own docstring for the full caller-supplied/
LLM-controlled split) out of a tool call's raw arguments string -- it does not know the tool loop
exists, does not call `register_generated_subsystem()` itself, and never even imports
`GeneratedSubsystemCandidate` -- that composition is entirely `openrouter_provider.py`'s concern
(`_execute_custom_geometry`), same separation `read_subsystem_provider.py` already keeps from its own
caller.

WHY `model`/`project_id`/`user_request_excerpt` ARE DELIBERATELY ABSENT FROM THIS SCHEMA: those three
are caller-supplied request/session context on `GeneratedSubsystemCandidate` -- an LLM must NEVER set
them itself. `GeneratedSubsystemCandidate`'s own docstring says this explicitly: "a hostile/careless
model putting a `model`/`project_id` field in its own tool-call JSON must never be trusted for these."
`GeneratedSubsystemCandidateArgs` below has `extra="forbid"`, so a model that tries to smuggle either
field into its own tool-call JSON gets a clean parse failure (surfaced by
`openrouter_provider.py::_execute_custom_geometry` as a rejected registration result), never a silent
passthrough into the real candidate."""

from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field


def custom_geometry_enabled() -> bool:
    """Same plain `os.environ.get(...)` shape as
    `read_subsystem_provider.py::read_subsystem_source_enabled()`, but DEFAULT-OFF (see module
    docstring for why): set `ENABLE_AI_GENERATED_SUBSYSTEMS=1` (or `true`/`yes`/`on`) to offer the
    model this tool. Unset/`0`/`false`/`no`/`off` (the default) means `propose_custom_geometry` is not
    added to `plain_tools`/`strict_tools` and has no entry in `continuation_handlers` at all -- a
    deployment that hasn't opted in sees no behavior change whatsoever."""
    raw = os.environ.get("ENABLE_AI_GENERATED_SUBSYSTEMS", "0")
    return raw.strip().lower() in ("1", "true", "yes", "on")


class GeneratedParamSpecArgs(BaseModel):
    """The tool-call-arguments mirror of
    `packages.subsystems.generated_registration.GeneratedParamSpec` -- identical fields, kept as a
    SEPARATE model (rather than importing that one directly) so this module never has to import
    `packages.subsystems.generated_registration` (and, transitively, `packages.subsystems`) just to
    describe a JSON schema -- `openrouter_provider.py::_execute_custom_geometry` is what actually
    bridges one shape into the other, the same "schema module vs. composition module" split
    `read_subsystem_provider.py` keeps from its own caller."""

    model_config = ConfigDict(extra="forbid")

    name: str
    default: float
    min: float
    max: float
    unit: str
    step: float | None = None
    label: str | None = None


class GeneratedSubsystemCandidateArgs(BaseModel):
    """Arguments for the `propose_custom_geometry` tool
    (`custom_geometry_tool_schema()` below) -- ONLY the LLM-CONTROLLED subset of
    `GeneratedSubsystemCandidate`'s own fields (see module docstring for why `model`/`project_id`/
    `user_request_excerpt` are excluded on purpose). `extra="forbid"` makes a stray field -- including
    an attempt to set one of those caller-supplied fields -- a parse error, not a silent passthrough."""

    model_config = ConfigDict(extra="forbid")

    subsystem_name: str = Field(description=(
        "A short, unique, snake_case Python identifier for the new catalog subsystem (e.g. "
        "'finned_heat_spreader') -- becomes a permanent packages/subsystems/generated/<name>.py "
        "filename and the name later reachable via add_instance. Must not already exist in the "
        "catalog you were given."
    ))
    description: str = Field(description=(
        "One or two plain-English sentences describing what this part is and what it's for -- shown "
        "to a later reader deciding whether to reuse it."
    ))
    build_code: str = Field(description=(
        "A COMPLETE Python module body defining exactly one top-level function `build(p)`, where `p` "
        "is a read-only namespace exposing each entry in `params` below as an ATTRIBUTE, not a dict "
        "key -- use `p.length_mm`, never `p['length_mm']` or `p.get('length_mm')` (a subscript access "
        "raises TypeError; this is not a dict). Returns a build123d Part/Solid/Compound. Only "
        "`import build123d` / `from build123d import ...` and "
        "`import math` / `from math import ...` are allowed -- no other imports, no filesystem/"
        "process/network access, no reflection primitives (getattr/setattr/globals/... are all "
        "denied). The code is statically checked, then actually built out-of-process before it can "
        "ever be registered -- a rejection is not a crash, it comes back as a clear reason to react to."
    ))
    params: list[GeneratedParamSpecArgs] = Field(default_factory=list, description=(
        "Every tunable dimension `build_code`'s `build(p)` reads from `p`, each with a default/min/"
        "max/unit -- e.g. {'name': 'length_mm', 'default': 40.0, 'min': 5.0, 'max': 200.0, 'unit': "
        "'mm'}. Empty list if the part has no exposed parameters."
    ))


def custom_geometry_tool_schema() -> dict:
    """The JSON Schema handed to the LLM tool-use API for `propose_custom_geometry` -- same convention
    as `research_provider.py::research_tool_schema()` / `read_subsystem_provider.py::
    read_subsystem_source_tool_schema()` (a Pydantic model's own `.model_json_schema()`,
    `extra="forbid"` so a stray extra field -- including a caller-supplied one the model has no
    business setting -- fails loudly rather than passing through silently)."""
    return GeneratedSubsystemCandidateArgs.model_json_schema()
