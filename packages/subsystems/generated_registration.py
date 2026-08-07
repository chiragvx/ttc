"""Template renderer + `register_generated_subsystem` gate — Phase 3 of the AI-generated-custom-geometry
initiative (7-phase, user-approved plan: C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md).

THIS IS THE GATE. Phases 0-2 (already built, reviewed, independently verified) each proved one piece in
isolation:
  - Phase 0 (packages/subsystems/__init__.py): `_discover_generated_subsystems()` scans
    `packages/subsystems/generated/*.py` at startup and imports each file, making a generated subsystem
    SURVIVE a restart. `register_subsystem()` refuses to let a generated file silently overwrite an
    already-registered name while that scan is running.
  - Phase 1 (packages/truth_plane/sandbox_subsystem.py): `sandbox_build_and_validate()` executes an
    untrusted `build(p)` definition out-of-process and classifies the outcome as one of
    OK/BUILD_ERROR/TIMEOUT_KILLED/MALFORMED_OUTPUT/DEGENERATE. Deliberately does NOT restrict what
    candidate code may import/do beyond its own bootstrap namespace — its own docstring says plainly
    "a static allow/deny-list ... is a LATER phase's concern." That later phase is this one.
  - Phase 2 (packages/truth_plane/generated_subsystem_store.py + packages/ledger/events.py):
    `GenerationAttemptStore` (the durable, cross-project corpus of every attempt) and
    `EventLog.append_generated_subsystem_attempt()` (a small per-project hash-chained pointer to a row
    in that corpus) both exist and work, but nothing calls them together with a real mechanical-
    correctness decision yet.

This module composes all three into the thing that actually decides whether a candidate becomes a
real, permanent, restart-surviving catalog entry: `register_generated_subsystem()` runs four
mechanical, deterministic correctness floors — NEVER a human trust-gate, matching the user's own
explicit "no trust gate needed, lets go all out and test with 0 friction" — in a fixed order, records
EVERY attempt (accepted or rejected) via Phase 2's store + ledger pointer regardless of outcome
(structural: every return path funnels through one `_finish()` closure, so a careless early `return`
can never skip capture — the same reason Phase 2 was built before this gate), and on full acceptance
renders a real subsystem module via `render_subsystem_module()`, writes it to
`packages/subsystems/generated/<name>.py`, and imports it in-process immediately so the new type is
usable in the SAME request without waiting for a restart.

TWO SHAPE MISMATCHES BRIDGED HERE (confirmed by reading both real modules, not assumed):

1. Phase 2's own module docstring ASSUMED `GenerationAttempt.params` would be shaped
   `[{"name","default","min","max","unit"}, ...]` (written before Phase 1 existed in this tree) — but
   Phase 1's REAL `sandbox_build_and_validate()` wants `[{"name","value","unit"}, ...]`, a single
   resolved value, not a full ParamSpec. `GeneratedSubsystemCandidate.params` below is the FULL
   ParamSpec-shaped input (name/default/min/max/unit[/step/label]) — that is what gets stored verbatim
   in `GenerationAttempt.params` (matches Phase 2's own documented assumption, richer for later human
   review) — and `_sandbox_params()` DERIVES Phase 1's simpler shape from it (using each param's
   `default` as `value`) at the one call site that invokes `sandbox_build_and_validate`.

2. Phase 1's `SandboxSubsystemResult.bbox_mm` is a `(min_corner, max_corner)` PAIR of 3-tuples; Phase
   2's `GenerationAttempt.bbox_mm` is documented as a flat `[x_mm, y_mm, z_mm]` EXTENTS list. Storing
   the corner-pair shape directly into the corpus row would silently violate Phase 2's own documented
   field contract. `_bbox_extents_mm()` converts one into the other at the one call site that populates
   a `GenerationAttempt`.

WHAT `fragment`/`disciplines` ARE, AND WHY THEY ARE NOT CANDIDATE FIELDS: this phase's own spec lists
the candidate's exact surface as `subsystem_name`, `description`, `build_code`, `params`, plus
caller-supplied `model`/`project_id`/`user_request_excerpt` — `fragment` and `disciplines` are
deliberately absent from that list. Both are LLM-knowledge-fragment / prompt-building text
(`packages/agents/prompt_builder.py`, telemetry) — never read by any correctness floor
(`packages/subsystems/base.py::Subsystem`'s own field comments confirm this) — so inventing a
plausible one here is safe and keeps the candidate schema minimal for Phase 5's tool-call use. See
`_synthesize_fragment()`/`_DEFAULT_DISCIPLINES` below.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import keyword
import logging
import re
import secrets
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

import packages.subsystems as _subsystems_pkg
from packages.ledger.events import EventLog
from packages.truth_plane.generated_subsystem_store import (
    GenerationAttempt,
    GenerationAttemptStore,
    generation_attempt_store_from_env,
)
from packages.truth_plane.sandbox_subsystem import BBoxMM, sandbox_build_and_validate

# Same directory Phase 0's own `_discover_generated_subsystems()` scans
# (packages/subsystems/__init__.py::_GENERATED_SUBSYSTEMS_DIR) — computed independently here since this
# module must not modify __init__.py, but it is the identical path (both files live directly under
# packages/subsystems/).
_DEFAULT_GENERATED_DIR = Path(__file__).resolve().parent / "generated"

logger = logging.getLogger(__name__)

# A generated part has no domain-classification signal of its own (see module docstring) — "structures"
# is the same safe, generic default every general-purpose hand-authored primitive
# (round_post/flat_bar/...) declares at minimum.
_DEFAULT_DISCIPLINES: tuple[str, ...] = ("structures",)

# R3 CONFIRMED FINDING (closed here, 2026-08-06): the floor-1 name-collision check
# (`candidate.subsystem_name in SUBSYSTEM_REGISTRY`) and the later unconditional `path.write_text()`
# that persists the rendered module were unprotected by any lock. Two concurrent
# `register_generated_subsystem()` calls proposing the SAME brand-new `subsystem_name` — a realistic
# shape once Phase 5 wires this gate behind a plain-`def` FastAPI route dispatched to a thread pool, per
# `packages/ledger/events.py`'s own documented concurrency model (see its `_store_lock_` for the
# precedent this lock follows) — could both observe the name as free (floor 1 passes for both, before
# either has written anything), both independently pass floors 2-4 (the expensive, no-shared-state part,
# deliberately left OUTSIDE this lock so unrelated candidates' out-of-process sandbox builds still run
# concurrently), and then both call `path.write_text()` for the identical target path: whichever write
# landed last would silently win on disk, even though Phase 0's own `register_subsystem()` collision
# defense (guarded by `_discovering_generated`) means only the FIRST candidate to reach
# `_import_generated_module` ends up in `SUBSYSTEM_REGISTRY` for the rest of this process's life. On-disk
# content then diverged from in-memory state until the next restart's discovery scan re-imported
# whichever file happened to land last.
#
# Fix: everything from the AUTHORITATIVE floor-1 check through the render+write+import is done while
# holding this lock (see the "All four floors passed" block below) — not just the write. A plain `Lock`
# (not `RLock`): nothing done while holding it calls back into `register_generated_subsystem` or
# otherwise re-enters it on the same thread, so there is no self-deadlock risk `events.py`'s `RLock`
# choice guards against. The EARLIER floor-1 check in this function (before floors 2-4 run) stays
# unlocked — it is only a fast-fail optimization that lets an obviously-already-taken name skip the
# expensive sandbox build; it was never what made the write atomic, and still isn't.
_REGISTRATION_LOCK = threading.Lock()

# Rejection-floor identifiers — distinct, stable strings a caller/test can branch on.
FLOOR_NAME_COLLISION = "name_collision"
FLOOR_INVALID_IDENTIFIER = "invalid_identifier"
FLOOR_DISALLOWED_CODE = "disallowed_code"
FLOOR_SANDBOX_BUILD = "sandbox_build"
# Not one of the four spec'd floors — an internal-error catch-all for the (expected-never) case where
# rendering/writing/importing a candidate that passed all four floors itself raises. Kept distinct so
# tests asserting the four real floor names never accidentally match this one.
FLOOR_POST_SANDBOX_REGISTRATION_ERROR = "post_sandbox_registration_error"

# `GenerationAttempt.sandbox_status` is a required, non-Optional `str`, but a candidate rejected at
# floor 1/2/3 never reaches the sandbox at all — this sentinel makes that honest ("never ran"), never a
# fabricated/blank status string that could be misread as a real SandboxSubsystemStatus value. Public
# (no leading underscore) so a caller/test can assert against it by name instead of a bare literal.
SANDBOX_NOT_RUN = "NOT_RUN"


class GeneratedParamSpec(BaseModel):
    """One tunable knob for a generated subsystem — the input-side mirror of
    `packages.subsystems.base.ParamSpec`, renamed `value` -> `default` (this is a DECLARATION a
    candidate proposes, not yet a resolved value). `extra="forbid"` per this repo's own ledger-model
    convention (packages/ledger/CLAUDE.md)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    default: float
    min: float
    max: float
    unit: str
    step: Optional[float] = None
    label: Optional[str] = None


class GeneratedSubsystemCandidate(BaseModel):
    """Everything `register_generated_subsystem()` needs for one generation attempt.

    Two clearly separated field groups — Phase 5 (not yet built) will construct one of these from an
    LLM tool call plus request context, and must match this split exactly:

    LLM-CONTROLLED (the model's own tool-call arguments):
      - `subsystem_name`, `description`, `build_code`, `params`.
      - Nothing else — `fea_eligible`, `fragment`, `disciplines`, and the provenance banner are never
        on this schema at all; `render_subsystem_module()` bakes all of those in itself (CLAUDE.md
        Inversion #1: "the LLM never originates a safety scalar").

    CALLER-SUPPLIED (request/session context; an LLM never sets these — a hostile/careless model
    putting a `model`/`project_id` field in its own tool-call JSON must never be trusted for these):
      - `model` — the real OpenRouter model identity that produced `build_code` (threaded through to
        `actor=f"ai:{model}"` on the ledger pointer event and the corpus row).
      - `project_id` — which project/ledger this attempt was generated FROM (traceability only; the
        corpus itself is cross-project, see `generated_subsystem_store.py`'s module docstring).
      - `user_request_excerpt` — the user's own NL request, for later human review context.
    """

    model_config = ConfigDict(extra="forbid")

    # --- LLM-controlled ---
    subsystem_name: str
    description: str
    build_code: str
    params: list[GeneratedParamSpec] = Field(default_factory=list)

    # --- caller-supplied ---
    model: str
    project_id: str
    user_request_excerpt: str = ""


@dataclass(frozen=True)
class RegistrationResult:
    """The typed outcome of one `register_generated_subsystem()` call — accepted or rejected, which
    floor (if rejected), and the resulting subsystem_name on success. Mirrors
    `SandboxSubsystemResult`'s own "one frozen dataclass, exactly one status" style.

    `model`/`sha256` (additive, Phase 5, 2026-08-06): threaded through so a caller with no other
    handle on this attempt's own `GenerationAttempt` row — e.g. `packages/transport/app.py`'s `/chat`
    route, which deliberately never receives the candidate or the attempt directly, only this result —
    can still call `EventLog.append_generated_subsystem_attempt(model=..., sha256=...)` for its own
    per-project ledger pointer event without a second lookup. Always populated (both are known before
    any of the four floors run — `candidate.model` is a required field, `sha256` is computed from
    `candidate.build_code` up front), regardless of accepted/rejected outcome or which floor rejected."""

    accepted: bool
    outcome: str  # "registered" | "rejected"
    subsystem_name: str
    attempt_id: str
    rejected_floor: Optional[str] = None
    rejection_reason: Optional[str] = None
    sandbox_status: Optional[str] = None
    volume_mm3: Optional[float] = None
    bbox_mm: Optional[BBoxMM] = None
    model: str = ""
    sha256: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _synthesize_fragment(candidate: "GeneratedSubsystemCandidate") -> str:
    """Synthesize a `Subsystem.fragment` (LLM knowledge-fragment text) from the candidate's own
    `description` + param names — see module docstring for why this is synthesized rather than
    caller-supplied."""
    param_names = ", ".join(p.name for p in candidate.params) or "(no exposed params)"
    return (
        f"## Subsystem: {candidate.subsystem_name} (AI-generated custom geometry)\n"
        f"{candidate.description}\n"
        f"Exposed params: {param_names}.\n"
        f'Generated custom geometry -- factor_of_safety honestly stays "unknown" for this part '
        f"(fea_eligible=False)."
    )


def _sandbox_params(candidate: "GeneratedSubsystemCandidate") -> list[dict]:
    """Bridge mismatch #1 (see module docstring): derive Phase 1's simpler `{"name","value","unit"}`
    shape from the candidate's full ParamSpec-shaped params, using each param's `default` as `value`."""
    return [{"name": p.name, "value": p.default, "unit": p.unit} for p in candidate.params]


def _bbox_extents_mm(bbox_mm: Optional[BBoxMM]) -> Optional[list[float]]:
    """Bridge mismatch #2 (see module docstring): Phase 1's bbox is a (min_corner, max_corner) pair;
    Phase 2's `GenerationAttempt.bbox_mm` is documented as flat [x, y, z] extents."""
    if bbox_mm is None:
        return None
    (min_x, min_y, min_z), (max_x, max_y, max_z) = bbox_mm
    return [max_x - min_x, max_y - min_y, max_z - min_z]


# --- Floor 3: AST-based static denylist -------------------------------------------------------------
#
# R2 CONFIRMED HIGH-SEVERITY FINDING (closed here, 2026-08-06): the original visitor only denied a
# handful of bare Names (open/exec/eval/__import__/subprocess) and `os./sys.` attribute roots. It never
# denied the bare Name `__builtins__` itself, so `__builtins__['open'](...)`,
# `__builtins__['__import__']('os')`, `getattr(__builtins__, 'open')(...)`, and
# `vars(__builtins__)['open'](...)` all reached real filesystem/process access with zero reported
# violations (`sandbox_subsystem.py` itself documents that `exec()` auto-populates `__builtins__` into
# candidate globals — this is a live, reachable name, not a hypothetical one). Separately, a bare
# `().__class__.__base__.__subclasses__()` class-hierarchy chain also passed clean, because none of its
# Attribute nodes have a base that is literally the Name `os`/`sys`.
#
# Closed with three additions, all live in `_DenylistVisitor` below:
#   1. `__builtins__` added to `_DENIED_NAMES` -- directly closes the four `__builtins__[...]`/
#      `getattr(__builtins__, ...)`/`vars(__builtins__)[...]` variants (each still references the bare
#      Name `__builtins__` somewhere in its AST, regardless of the subscript/getattr/vars wrapper).
#   2. `getattr`/`setattr`/`delattr`/`vars`/`globals`/`locals` added to `_DENIED_NAMES` -- these are
#      generic reflection primitives with no legitimate use in constructive build123d/math geometry code;
#      denying them closes the whole *class* of "reach a denied name/attribute via a string argument
#      instead of literal dotted/Name syntax" bypass (e.g. `getattr(x, "__subclasses__")`,
#      `globals()['__builtins__']`), not just the specific spellings R2 tried.
#   3. `_DENIED_ATTRIBUTES` (new): a set of dunder attributes that grant reflective access to live
#      classes/functions/module globals *regardless of what object they are accessed on* -- closes the
#      `().__class__.__base__.__subclasses__()` chain (and equivalents like `func.__globals__`,
#      `cls.__mro__`) structurally, not by trying to enumerate every possible starting literal.
# `visit_Subscript` is also now defined explicitly (previously relied on default `generic_visit`
# dispatch) so a `[...]`-based reference to a denied name is visibly, intentionally handled rather than
# an accident of AST traversal order.

_ALLOWED_MODULES = ("build123d", "math")

# Bare names whose mere presence anywhere in build_code is disallowed: directly dangerous primitives
# (open/exec/eval/__import__/subprocess) plus __builtins__ itself and the reflection primitives
# (getattr/setattr/delattr/vars/globals/locals) that can reach denied functionality indirectly, via a
# string argument rather than literal Name/Attribute syntax.
_DENIED_NAMES = (
    "open", "exec", "eval", "__import__", "subprocess",
    "__builtins__", "getattr", "setattr", "delattr", "vars", "globals", "locals",
)
_DENIED_ATTRIBUTE_ROOTS = ("os", "sys")

# Dunder attributes that grant reflective access to live classes/functions/module namespaces regardless
# of the base expression they're accessed on -- the classic no-import sandbox-escape chain
# (`().__class__.__base__.__subclasses__()`, `some_func.__globals__['os']`, ...). Denied unconditionally
# (any `<expr>.__thisattr__`), not just when the base is a bare `os`/`sys` Name, because the entire point
# of this family of exploit is to reach os/sys/builtins WITHOUT ever naming them.
_DENIED_ATTRIBUTES = (
    "__globals__", "__builtins__", "__base__", "__bases__", "__mro__", "__subclasses__",
    "__class__", "__dict__", "__code__", "__closure__", "__func__", "__self__",
    "__getattribute__", "__reduce__", "__reduce_ex__", "__init_subclass__",
    "__import__", "__loader__", "__spec__",
)

# Subscript keys (string literals) that are disallowed regardless of what they're subscripting out of --
# defense-in-depth for a denied name reached only as a dict/mapping KEY string (e.g.
# `some_namespace_dict['__builtins__']`) rather than as an AST Name/Attribute node.
_DENIED_SUBSCRIPT_KEYS = _DENIED_NAMES + _DENIED_ATTRIBUTE_ROOTS


class _DenylistVisitor(ast.NodeVisitor):
    """Walks the parsed `build_code` AST once, collecting every violation of the floor-3 denylist (see
    module docstring / CONTEXT's five-floor spec) instead of stopping at the first one, so a rejection
    reason can name everything wrong in one pass."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name not in _ALLOWED_MODULES:
                self.violations.append(f"disallowed import: 'import {alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level != 0 or node.module not in _ALLOWED_MODULES:
            dots = "." * node.level
            self.violations.append(f"disallowed import: 'from {dots}{node.module or ''} import ...'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id in _DENIED_NAMES:
            self.violations.append(f"disallowed reference to {node.id!r}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.value, ast.Name) and node.value.id in _DENIED_ATTRIBUTE_ROOTS:
            self.violations.append(f"disallowed attribute access: '{node.value.id}.{node.attr}'")
        if node.attr in _DENIED_ATTRIBUTES:
            self.violations.append(f"disallowed attribute access: '.{node.attr}'")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value in _DENIED_SUBSCRIPT_KEYS:
            self.violations.append(f"disallowed subscript access: [{key.value!r}]")
        self.generic_visit(node)


def _check_denylist(build_code: str) -> Optional[str]:
    """Cheap, parse-only static check — never `exec`/`eval`s `build_code` itself. Returns None when
    clean, else a human-readable reason naming every violation found. A `build_code` that isn't even
    syntactically valid Python is rejected here too (never reaches the sandbox for a SyntaxError the
    static check itself can already report faster and more cheaply)."""
    try:
        tree = ast.parse(build_code)
    except SyntaxError as exc:
        return f"build_code has a syntax error: {exc}"
    visitor = _DenylistVisitor()
    visitor.visit(tree)
    if visitor.violations:
        return "; ".join(visitor.violations)
    return None


# --- Rendering ----------------------------------------------------------------------------------------

_MODULE_TEMPLATE = '''\
# AUTO-GENERATED by the AI-generated-custom-geometry initiative -- DO NOT HAND-EDIT.
# See packages/subsystems/generated/README.md for what happens to files in this directory.
#
# Provenance (baked in by the template at registration time; NEVER supplied by the candidate's own
# build_code, which is inert embedded data below -- see packages/subsystems/generated_registration.py):
#   attempt_id: __ATTEMPT_ID_REPR__
#   model:      __MODEL_REPR__
#   generated:  __TS_REPR__
#   subsystem:  __SUBSYSTEM_NAME_REPR__

from __future__ import annotations

import base64

from packages.subsystems import ParamSpec, Subsystem, register_subsystem

_PROVENANCE = {
    "attempt_id": __ATTEMPT_ID_REPR__,
    "model": __MODEL_REPR__,
    "generated_at": __TS_REPR__,
}

# The candidate's own build_code, base64-embedded as INERT DATA -- never string-concatenated as literal
# source next to this trusted template, so a crafted build_code containing e.g. a stray triple-quote
# sequence can never "close" out of its own boundary and inject code into the surrounding module. Same
# defensive posture packages/truth_plane/sandbox_subsystem.py's own bootstrap uses for build_code and
# params, for the identical reason. Decoded and exec'd exactly once, at import time, into an isolated
# namespace dict -- the resulting `build` callable (already proven to work by Phase 1's sandboxed build,
# floor 4, before this file was ever written) is what gets registered below.
_BUILD_CODE_B64 = "__BUILD_CODE_B64__"
_build_ns: dict = {}
exec(base64.b64decode(_BUILD_CODE_B64).decode("utf-8"), _build_ns)
build = _build_ns["build"]

_PARAMS = [
__PARAMS_BLOCK__
]

register_subsystem(Subsystem(
    name=__SUBSYSTEM_NAME_REPR__,
    description=__DESCRIPTION_REPR__,
    fragment=__FRAGMENT_REPR__,
    disciplines=__DISCIPLINES_REPR__,
    params=_PARAMS,
    build=build,
    # fea_eligible is HARDCODED False by this template -- never a field the candidate/caller can set.
    # CLAUDE.md Inversion #1: "the LLM never originates a safety scalar". factor_of_safety honestly
    # stays "unknown" for every AI-generated part, same posture spur_gear.py/lofted_spindle.py declare.
    fea_eligible=False,
))
'''


# The template's own placeholder tokens. Substitution MUST happen in a single pass over the ORIGINAL
# `_MODULE_TEMPLATE` text (see `render_subsystem_module`'s own docstring for why) -- never via chained
# `.replace()` calls on the progressively-accumulated result, which would re-scan text a PRIOR
# substitution just inserted and let a later token's payload get spliced into an earlier candidate/
# caller string that merely happens to contain that later token's literal text (e.g. a param `unit` of
# `"__BUILD_CODE_B64__"`).
_TEMPLATE_TOKENS = (
    "__ATTEMPT_ID_REPR__",
    "__MODEL_REPR__",
    "__TS_REPR__",
    "__SUBSYSTEM_NAME_REPR__",
    "__DESCRIPTION_REPR__",
    "__FRAGMENT_REPR__",
    "__DISCIPLINES_REPR__",
    "__PARAMS_BLOCK__",
    "__BUILD_CODE_B64__",
)
_TEMPLATE_TOKEN_PATTERN = re.compile("|".join(re.escape(tok) for tok in _TEMPLATE_TOKENS))


def _render_template(template: str, replacements: dict[str, str]) -> str:
    """Substitute every `_TEMPLATE_TOKENS` placeholder in `template` in a SINGLE pass. `re.sub` scans
    the original `template` string left-to-right exactly once and never re-scans replacement text it
    has already spliced in -- so no matter what a replacement value itself contains (even the literal
    text of another placeholder token), it can never be re-interpreted as a further substitution. This
    is what actually delivers the "no candidate/caller string can corrupt another's substitution"
    guarantee `render_subsystem_module` documents; chained `.replace()` calls on the accumulated result
    string do NOT provide this guarantee (each subsequent `.replace()` rescans everything inserted so
    far)."""
    missing = [tok for tok in _TEMPLATE_TOKENS if tok not in replacements]
    if missing:
        raise ValueError(f"_render_template missing replacements for tokens: {missing!r}")
    return _TEMPLATE_TOKEN_PATTERN.sub(lambda m: replacements[m.group(0)], template)


def _param_spec_literal(p: GeneratedParamSpec) -> str:
    parts = [f"name={p.name!r}", f"value={p.default!r}", f"min={p.min!r}", f"max={p.max!r}",
              f"unit={p.unit!r}"]
    if p.step is not None:
        parts.append(f"step={p.step!r}")
    if p.label is not None:
        parts.append(f"label={p.label!r}")
    return f"    ParamSpec({', '.join(parts)}),"


def render_subsystem_module(candidate: GeneratedSubsystemCandidate, attempt_id: str) -> str:
    """Pure string templating (NOT Jinja2 -- no precedent/dependency for it anywhere in this repo,
    confirmed by repo-wide grep) that renders a real `packages/subsystems/generated/<name>.py` file,
    in the exact shape of a hand-authored catalog subsystem: a provenance banner, `_PARAMS` built from
    the candidate's typed params, the candidate's `build_code` embedded as inert base64 data and
    exec'd into a real top-level `build` callable, and a trailing `register_subsystem(Subsystem(...))`
    call with `fea_eligible=False` hardcoded. Every interpolated value is inserted via `repr()` (never
    `.format()` -- the template's own body is full of literal `{`/`}`) so no candidate- or caller-
    supplied string, no matter its content (embedded quotes, newlines, backslashes), can break out of
    its own literal or inject code into the surrounding trusted template.

    Substitution itself is a SINGLE pass over the template via `_render_template` (`re.sub` over the
    fixed `_MODULE_TEMPLATE` text, matching all placeholder tokens at once) -- deliberately NOT a chain
    of `.replace()` calls applied one after another to the progressively-accumulated result. Chaining
    would let a LATER `.replace()` call rescan text an EARLIER one just inserted: if some candidate/
    caller string (a param's `unit`/`name`/`label`, `subsystem_name`, `description`, ...) happens to
    contain the literal text of a placeholder token that is still pending substitution, that token gets
    spliced into the middle of the earlier, already-embedded string -- corrupting it silently (the
    result still parses as valid Python; nothing rejects it). A single `re.sub` pass over the ORIGINAL
    template text has no such hazard: replacement values are inserted verbatim and are never themselves
    rescanned for further token matches, regardless of what they contain."""
    ts = _now_iso()
    build_code_b64 = base64.b64encode(candidate.build_code.encode("utf-8")).decode("ascii")
    params_block = "\n".join(_param_spec_literal(p) for p in candidate.params)
    fragment = _synthesize_fragment(candidate)

    replacements = {
        "__ATTEMPT_ID_REPR__": repr(attempt_id),
        "__MODEL_REPR__": repr(candidate.model),
        "__TS_REPR__": repr(ts),
        "__SUBSYSTEM_NAME_REPR__": repr(candidate.subsystem_name),
        "__DESCRIPTION_REPR__": repr(candidate.description),
        "__FRAGMENT_REPR__": repr(fragment),
        "__DISCIPLINES_REPR__": repr(_DEFAULT_DISCIPLINES),
        "__PARAMS_BLOCK__": params_block,
        "__BUILD_CODE_B64__": build_code_b64,
    }
    return _render_template(_MODULE_TEMPLATE, replacements)


def _import_generated_module(path: Path) -> None:
    """Import ONE freshly-written generated subsystem file in-process, immediately, using the exact
    same importlib mechanics as `packages.subsystems._discover_generated_subsystems()` (synthetic
    module name, `spec_from_file_location`/`module_from_spec`/`exec_module`, the real
    `_discovering_generated` flag toggled around the call so `register_subsystem()`'s own collision
    defense-in-depth applies unchanged).

    Deliberately does NOT call `_discover_generated_subsystems()` itself: that function scans and
    re-execs EVERY `.py` file already in the target directory, not just the one this call just wrote —
    in production `generated/` accumulates one file per prior acceptance, so a full rescan on every
    single new registration would re-run every previously-accepted file's module-level code again (each
    hitting a harmless-but-noisy self-collision rejection, since it's already registered) purely to pick
    up one new file. This targets exactly the one path that was just written, at real per-registration
    cost instead of O(directory size)."""
    module_name = f"packages.subsystems.generated._{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"no import spec for generated subsystem file {path.name!r}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    _subsystems_pkg._discovering_generated = True
    try:
        spec.loader.exec_module(module)
    finally:
        _subsystems_pkg._discovering_generated = False


# --- The gate -------------------------------------------------------------------------------------


def register_generated_subsystem(
    candidate: GeneratedSubsystemCandidate,
    *,
    store: Optional[GenerationAttemptStore] = None,
    event_log: Optional[EventLog] = None,
    generated_dir: Optional[Path] = None,
) -> RegistrationResult:
    """Run the four mechanical correctness floors, in this exact order, on `candidate` — never a human
    judgment call. Every attempt, whether it fails floor 1/2/3/4 or passes all four, is recorded via
    `store.put(...)` (Phase 2's cross-project corpus) and, when `event_log` is supplied,
    `event_log.append_generated_subsystem_attempt(...)` (a small per-project hash-chained pointer) —
    structurally, via the single `_finish()` closure below, so no return path can skip capture.

    `store` defaults to `generation_attempt_store_from_env()` (the same DATABASE_URL-gated honest
    in-memory fallback every other store in this codebase uses) when not supplied. `event_log` is
    optional (None = no project ledger to point from yet — a caller with no live project context, e.g.
    an offline/batch generation run, can still get full corpus capture without one) — a real live
    request (Phase 5) is expected to always pass the requesting project's own EventLog.

    `generated_dir` overrides where an accepted candidate's rendered module is written + imported from
    — purely for tests, exactly like `_discover_generated_subsystems(directory=...)`'s own override;
    production callers leave it at the real `packages/subsystems/generated/`.

    Floors 1-4:
      1. Name collision — `candidate.subsystem_name` must not already be in `SUBSYSTEM_REGISTRY`.
      2. Valid Python identifier — becomes both a filename stem and a name embedded in generated source.
      3. AST-based static denylist on `build_code` (see `_check_denylist`) — run BEFORE the sandbox.
      4. Sandboxed build (`sandbox_build_and_validate`) must resolve exactly `status == "OK"` — which,
         per Phase 1's own confirmed contract, already implies non-degenerate geometry (DEGENERATE is a
         distinct status), so there is no separate 5th floor beyond requiring "OK" specifically.

    Only on passing all four: renders the module (`render_subsystem_module`), writes it to
    `generated_dir/<subsystem_name>.py`, and imports it in-process immediately
    (`_import_generated_module`) so the new type resolves via `get_subsystem_model()` in THIS process
    without waiting for a restart.
    """
    resolved_store = store if store is not None else generation_attempt_store_from_env()
    attempt_id = f"att_{secrets.token_hex(12)}"
    ts = _now_iso()
    sha256 = hashlib.sha256(candidate.build_code.encode("utf-8")).hexdigest()
    actor = f"ai:{candidate.model}"
    params_for_corpus = [p.model_dump() for p in candidate.params]

    def _finish(
        outcome: str,
        *,
        rejected_floor: Optional[str] = None,
        rejection_reason: Optional[str] = None,
        sandbox_status: str = SANDBOX_NOT_RUN,
        sandbox_stdout: str = "",
        sandbox_stderr: str = "",
        volume_mm3: Optional[float] = None,
        bbox_mm: Optional[BBoxMM] = None,
    ) -> RegistrationResult:
        attempt = GenerationAttempt(
            attempt_id=attempt_id, ts=ts, project_id=candidate.project_id, model=candidate.model,
            subsystem_name=candidate.subsystem_name, sha256=sha256, build_code=candidate.build_code,
            params=params_for_corpus,
            sandbox_status=sandbox_status, sandbox_stdout=sandbox_stdout, sandbox_stderr=sandbox_stderr,
            volume_mm3=volume_mm3, bbox_mm=_bbox_extents_mm(bbox_mm),
            outcome=outcome, rejection_reason=rejection_reason,
            user_request_excerpt=candidate.user_request_excerpt,
        )
        # Phase 5 write-path repair (2026-08-06, reviewer R2 CONFIRMED, medium): this call used to sit
        # completely unguarded. `_finish` is the SAME closure that runs for the "registered" outcome —
        # by the time it's called there, `candidate.subsystem_name`'s module has already been rendered,
        # written to `generated_dir/<name>.py`, and imported into SUBSYSTEM_REGISTRY (see the "All four
        # floors passed" block below): that mutation is real, permanent, and NOT rolled back by anything
        # in this function. Letting a `GenerationAttemptStore.put()` failure (e.g.
        # generation_attempt_store_from_env()'s Postgres path hitting a DATABASE_URL outage at exactly
        # this instant) raise straight out of `_finish` did not just skip one corpus row — it also threw
        # away the `RegistrationResult` itself, which is the ONLY thing that tells any caller (starting
        # with packages/agents/openrouter_provider.py::_execute_custom_geometry, whose own "a handler
        # MUST NEVER RAISE" continuation-dispatch contract this broke) that registration happened at
        # all. The candidate would then be live and placeable via add_instance with zero row in the
        # generation-attempt corpus and zero per-project ledger pointer, while the caller only sees a
        # raw exception. A store outage must never be allowed to also hide a real registry mutation from
        # every caller — log it loudly (this is the one place that capture can go silently missing) and
        # still return the accurate `RegistrationResult` below, exactly as if the write had succeeded.
        try:
            resolved_store.put(attempt)
        except Exception as exc:
            logger.error(
                "register_generated_subsystem: GenerationAttemptStore.put() failed for "
                "attempt_id=%r subsystem_name=%r outcome=%r -- the corpus row for this attempt was "
                "NOT recorded, but any registry/filesystem mutation this outcome implies already "
                "happened and is not rolled back (%s)",
                attempt_id, candidate.subsystem_name, outcome, exc,
            )
        if event_log is not None:
            event_log.append_generated_subsystem_attempt(
                attempt_id=attempt_id, sha256=sha256, subsystem_name=candidate.subsystem_name,
                model=candidate.model, outcome=outcome, actor=actor, ts=ts,
            )
        return RegistrationResult(
            accepted=(outcome == "registered"), outcome=outcome, subsystem_name=candidate.subsystem_name,
            attempt_id=attempt_id, rejected_floor=rejected_floor, rejection_reason=rejection_reason,
            sandbox_status=None if sandbox_status == SANDBOX_NOT_RUN else sandbox_status,
            volume_mm3=volume_mm3, bbox_mm=bbox_mm,
            model=candidate.model, sha256=sha256,
        )

    # Floor 1 — name collision. Proactive: checked here, at generation time, before ever writing a file
    # to disk — distinct from (but consistent with) Phase 0's own runtime rejection inside
    # register_subsystem(), which only fires later, at the NEXT process startup's discovery scan.
    if candidate.subsystem_name in _subsystems_pkg.SUBSYSTEM_REGISTRY:
        return _finish(
            "rejected", rejected_floor=FLOOR_NAME_COLLISION,
            rejection_reason=f"subsystem name {candidate.subsystem_name!r} already exists in the catalog",
        )

    # Floor 2 — valid Python identifier (filename stem + name embedded in generated source).
    if not candidate.subsystem_name.isidentifier() or keyword.iskeyword(candidate.subsystem_name):
        return _finish(
            "rejected", rejected_floor=FLOOR_INVALID_IDENTIFIER,
            rejection_reason=(
                f"{candidate.subsystem_name!r} is not a valid Python identifier "
                f"(it becomes a generated/<name>.py filename stem and a name embedded in source)"
            ),
        )

    # Floor 3 — AST-based static denylist, BEFORE the sandbox (cheap check first).
    denylist_reason = _check_denylist(candidate.build_code)
    if denylist_reason is not None:
        return _finish("rejected", rejected_floor=FLOOR_DISALLOWED_CODE, rejection_reason=denylist_reason)

    # Floor 4 — sandboxed build must resolve exactly "OK" (already implies non-degenerate).
    sandbox_result = sandbox_build_and_validate(candidate.build_code, _sandbox_params(candidate))
    if sandbox_result.status != "OK":
        return _finish(
            "rejected", rejected_floor=FLOOR_SANDBOX_BUILD,
            rejection_reason=f"{sandbox_result.status}: {sandbox_result.message}",
            sandbox_status=sandbox_result.status,
            sandbox_stdout=sandbox_result.stdout or "", sandbox_stderr=sandbox_result.stderr or "",
            # DEGENERATE (unlike BUILD_ERROR/TIMEOUT_KILLED/MALFORMED_OUTPUT) still carries a real
            # volume/bbox -- Phase 1's own contract: "still populated so a caller can see WHY it was
            # flagged". None for every other rejecting status (SandboxSubsystemResult's own defaults).
            volume_mm3=sandbox_result.volume_mm3, bbox_mm=sandbox_result.bbox_mm,
        )

    # All four floors passed -- render, write to disk, import in-process immediately. Everything from
    # here through the write+import happens while holding `_REGISTRATION_LOCK` (see its own module-level
    # comment for the R3-confirmed race this closes), INCLUDING a RE-CHECK of floor 1: the floor-1 check
    # earlier in this function ran unlocked, before the expensive floors 2-4, purely as a fast-fail
    # optimization -- it does NOT, by itself, make the write atomic against a concurrent candidate
    # proposing the SAME brand-new name that reaches this point at nearly the same time. The re-check
    # below is the AUTHORITATIVE one.
    target_dir = generated_dir if generated_dir is not None else _DEFAULT_GENERATED_DIR
    path = target_dir / f"{candidate.subsystem_name}.py"
    with _REGISTRATION_LOCK:
        if candidate.subsystem_name in _subsystems_pkg.SUBSYSTEM_REGISTRY:
            # A concurrent request registered this exact name while THIS candidate's own floor-3/4 work
            # (AST parse + out-of-process sandboxed build -- the expensive part, deliberately run outside
            # this lock) was still in flight. Reject now, before writing anything: same floor as the
            # early check above, just caught at the point that is actually authoritative.
            return _finish(
                "rejected", rejected_floor=FLOOR_NAME_COLLISION,
                rejection_reason=(
                    f"subsystem name {candidate.subsystem_name!r} was registered by a concurrent "
                    f"request while this candidate's sandboxed build was running"
                ),
                sandbox_status=sandbox_result.status,
                sandbox_stdout=sandbox_result.stdout or "", sandbox_stderr=sandbox_result.stderr or "",
                volume_mm3=sandbox_result.volume_mm3, bbox_mm=sandbox_result.bbox_mm,
            )

        try:
            module_src = render_subsystem_module(candidate, attempt_id)
            target_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(module_src, encoding="utf-8")
            _import_generated_module(path)
        except Exception as exc:  # pragma: no cover -- not one of the 4 floors; see FLOOR_POST_SANDBOX_...
            # R1 CONFIRMED FINDING (closed here): `path.write_text()` above may already have run before
            # `_import_generated_module()` raised (render succeeded; only the write+import step failed) --
            # every floor-1..4 rejection test in this suite asserts the candidate's file never exists on
            # disk after a 'rejected' outcome, and this catch-all floor is no exception. Leaving the broken
            # .py file behind would be permanent, undiagnosed cruft that the NEXT process restart's
            # `_discover_generated_subsystems()` scan would also trip over, despite the corpus/ledger
            # correctly recording this exact attempt as rejected. `missing_ok=True` covers the case where
            # rendering itself raised before any file was ever written. Also drop any partial `sys.modules`
            # entry `_import_generated_module` may have installed (it assigns the module there BEFORE
            # `exec_module()`, so a mid-exec failure leaves a half-initialized module object registered
            # under its synthetic name) -- same "no partial state survives a rejection" invariant, same
            # except block, same root cause.
            path.unlink(missing_ok=True)
            sys.modules.pop(f"packages.subsystems.generated._{path.stem}", None)
            return _finish(
                "rejected", rejected_floor=FLOOR_POST_SANDBOX_REGISTRATION_ERROR,
                rejection_reason=f"{type(exc).__name__}: {exc}",
                sandbox_status=sandbox_result.status,
                sandbox_stdout=sandbox_result.stdout or "", sandbox_stderr=sandbox_result.stderr or "",
            )

        return _finish(
            "registered", sandbox_status=sandbox_result.status,
            sandbox_stdout=sandbox_result.stdout or "", sandbox_stderr=sandbox_result.stderr or "",
            volume_mm3=sandbox_result.volume_mm3, bbox_mm=sandbox_result.bbox_mm,
        )
