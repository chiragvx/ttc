"""Sandboxed execution of LLM-generated `build(p)` code — Phase 1 of the AI-generated-custom-geometry
initiative (7-phase, user-approved plan: C:\\Users\\Chirag\\.claude\\plans\\spicy-exploring-cupcake.md).
This is the primitive that actually EXECUTES untrusted, generated build123d code safely enough to find
out whether it works, before anything downstream (a mechanical-correctness gate, later phases) ever
trusts its output. Nothing here judges whether the geometry is any GOOD — only whether it built at all,
in bounded time, into something non-degenerate. That is deliberately a separate, later concern.

Built on top of `run_sandboxed` (packages/truth_plane/sandbox.py) — this module is that function's
FIRST real production caller (confirmed by repo-wide grep before writing this: previously only its own
tests, tests/backend/test_sandbox.py, called it).

HONEST CONTAINMENT SCOPE (inherited from sandbox.py's own module docstring — not something this phase
fixes or changes): on Windows (this dev box) the ONLY real containment is the host-side wall-clock
SIGKILL. The process-group isolation (`os.setsid` + `killpg`) and the `RLIMIT_AS` memory cap are both
POSIX-gated no-ops here — `run_sandboxed` falls back to a plain, single-process `proc.kill()` on
timeout. Real memory/process-tree containment only exists on Linux, this system's actual deployment
target (packages/truth_plane/CLAUDE.md: "All of this is Linux-only ... and runs inside the sandbox").

WHY A SHIM NAMESPACE, NOT THE REAL ONE (packages/subsystems/base.py::Namespace): `run_sandboxed` invokes
the child as `python -I -c <code>` — isolated mode, which (per the `-I`/`-P` docs) drops the current
working directory from `sys.path`. Verified directly before writing this file: under `python -I`,
`sys.path` contains only the interpreter's own stdlib/site-packages entries, never the repo root. So a
bare `import packages.subsystems.base` would need the repo root re-injected onto `sys.path` from
*inside* the sandboxed child — tying this supposedly self-contained bootstrap script to a specific
on-disk repo layout, and (more importantly) dragging in `packages.ledger.parameter` (pydantic) purely
to satisfy read-only attribute access this harness can trivially replicate itself. The bootstrap below
instead defines a tiny inline `_Namespace` shim with the exact same `__getattr__` contract (name ->
stored float value, `AttributeError` on a miss) — behaviourally identical for what `build(p)` can
observe, zero extra imports, zero path assumptions.

WHY build123d IS NOT PRE-IMPORTED BY THE HARNESS: every real subsystem's own `_build(p)` does its own
local `import build123d as bd` (confirmed directly — see lofted_spindle.py's `_build`), not a
module-level import. The bootstrap here follows the exact same convention: candidate `build_code` is
responsible for importing build123d itself if it needs geometry. This is not just stylistic parity — it
means the BUILD_ERROR and TIMEOUT_KILLED paths never touch build123d at all, so `tests/backend/
test_sandbox_subsystem.py`'s tests for those two outcomes need no kernel/build123d dependency and run
on any machine; only a candidate that actually builds geometry pays that cost.
"""

from __future__ import annotations

import base64
import json
import math
import secrets
from dataclasses import dataclass
from typing import Literal, Optional

from packages.truth_plane.sandbox import run_sandboxed

SandboxSubsystemStatus = Literal["OK", "BUILD_ERROR", "TIMEOUT_KILLED", "MALFORMED_OUTPUT", "DEGENERATE"]
BBoxMM = tuple[tuple[float, float, float], tuple[float, float, float]]

# 8s: generous headroom over a cold OCCT/build123d import (~1.8s on this dev box, measured directly via
# `import time; t=time.monotonic(); import build123d; print(time.monotonic()-t)` in three separate fresh
# processes) plus a simple boolean build -- a full `run_sandboxed` round trip for the trivial
# `bd.Box(10,10,10)` candidate (subprocess spawn + `-I`-isolated import + build + teardown) measures
# ~2.56s end to end, leaving ~5.4s of real headroom under this bound -- while keeping the deliberate-
# timeout test (`while True: pass`) bounded to a predictable, not-too-long wait. Not shrunk just to make
# tests faster — a tighter bound would make legitimate-but-slower candidate geometry (a multi-station
# loft, several booleans) indistinguishable from a genuinely wedged build.
_DEFAULT_WALL_CLOCK_S = 8.0
_DEFAULT_MEM_LIMIT_MB = 512

# A solid with volume at/below this (mm^3) is treated as "at/near zero" -- see _is_degenerate below.
_DEGENERATE_VOLUME_EPS_MM3 = 1e-6


@dataclass(frozen=True)
class SandboxSubsystemResult:
    """The typed outcome of running one candidate `build(p)` in the sandbox — what Phase 3's mechanical-
    correctness gate consumes directly. Exactly one of the 5 `status` values below, each carrying only
    the payload that makes sense for it:
      - "OK": build succeeded, produced non-degenerate geometry -> `volume_mm3` + `bbox_mm` populated.
      - "BUILD_ERROR": the candidate code raised (or never defined `build`) -> `message` is the
        exception text, `traceback` a short trace, both from INSIDE the sandbox.
      - "TIMEOUT_KILLED": the candidate exceeded the wall-clock deadline and was killed -> `message`
        explains the deadline; `stdout`/`stderr` carry whatever the child produced before the kill.
      - "MALFORMED_OUTPUT": the subprocess exited but stdout never contained one parseable, correctly-
        shaped JSON result line -> `stdout`/`stderr` are the raw child output, for debugging.
      - "DEGENERATE": the build reported success but the geometry is physically nonsensical (near-zero
        volume, or a zero/negative/non-finite bbox axis) -> `volume_mm3` + `bbox_mm` still populated so
        a caller can see WHY it was flagged.
    """

    status: SandboxSubsystemStatus
    message: str = ""
    volume_mm3: Optional[float] = None
    bbox_mm: Optional[BBoxMM] = None
    traceback: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


# The bootstrap script that runs INSIDE the sandboxed child. Three placeholder tokens
# (`__PARAMS_B64__` / `__BUILD_CODE_B64__` / `__RESULT_TOKEN_B64__`) are substituted via plain
# `.replace()`, not `.format()` — the script's own body is full of literal `{`/`}` (dict/set syntax, an
# f-string), so `.format()` would need every one of those escaped; base64's alphabet ([A-Za-z0-9+/=])
# can never collide with a `__..._B64__`-shaped token, so `.replace()` is both simpler and safer.
# Untrusted `build_code` and the `params` JSON are both passed through base64, not interpolated as
# literal source text — candidate code could otherwise contain a stray `'''`/`"""` sequence that breaks
# out of whatever quoting scheme embedded it directly.
#
# `__RESULT_TOKEN_B64__` is NOT untrusted input — it is a fresh `secrets.token_hex()` value generated
# by `_render_bootstrap` (the parent, host-side) on every call, embedded here purely so the CHILD can
# echo it back inside its own genuine result line. `_parse_last_result_line` (parent-side, below) then
# requires an exact match before trusting a line at all. This is the fix for a CONFIRMED "fabricated
# green light": a candidate's `build(p)` can `print()` a hand-crafted, correctly-shaped fake `{"ok":
# True, ...}` line itself, then short-circuit the harness's own genuine result print via `sys.exit()`
# (a `BaseException`, not caught by a plain `except Exception`) or `os._exit()` (which bypasses *all*
# Python-level exception handling, uncatchable by definition) — either way making the candidate's own
# forged line the physically last (or only) thing on stdout. Requiring an unguessable per-run token the
# candidate cannot obtain through ordinary name lookup (see `_main`'s use of it below) means a forged
# line without it is simply rejected, falling through to the honest `MALFORMED_OUTPUT` verdict instead
# of a fabricated `OK` — exactly CLAUDE.md's guardrail #1 ("a missing safety input is unknown and
# BLOCKS export — never a fabricated green light").
_BOOTSTRAP_TEMPLATE = '''\
import base64, json, math, traceback


class _Namespace:
    """Minimal read-only attribute-access shim -- see sandbox_subsystem.py's module docstring for why
    this is a standalone shim rather than importing the real packages.subsystems.base.Namespace."""
    __slots__ = ("_values",)

    def __init__(self, values):
        object.__setattr__(self, "_values", values)

    def __getattr__(self, name):
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(f"no such param: {name!r}")


def _main():
    # Captured as LOCAL variables before any candidate code runs, and used exclusively below (never
    # `print`/`json.dumps` looked up fresh by name again after this point) for the harness's own two
    # result emissions. `_candidate_globals` (below) is a bare `{"math": math}` dict, unlinked to this
    # function's own locals, so ordinary name lookup from inside candidate code cannot reach
    # `_emit`/`_dumps`/`_token` -- but `json`/`builtins` ARE shared, live module objects the candidate
    # can `import` and mutate (e.g. `json.dumps = ...`, `import builtins; builtins.print = ...`), which
    # would otherwise let it corrupt or intercept whatever the harness itself tries to print AFTER
    # `build_fn(p)` runs. Holding direct references captured before that point stays genuine no matter
    # what happens to the shared objects afterward.
    _emit = print
    _dumps = json.dumps
    _token = base64.b64decode("__RESULT_TOKEN_B64__").decode("utf-8")
    try:
        _params = json.loads(base64.b64decode("__PARAMS_B64__").decode("utf-8"))
        _build_code = base64.b64decode("__BUILD_CODE_B64__").decode("utf-8")
        p = _Namespace({d["name"]: d["value"] for d in _params})

        # `math` is handed to candidate code as a convenience -- the same thing every real subsystem's
        # own build module already imports at the top (e.g. lofted_spindle.py: `import math`).
        # build123d is deliberately NOT pre-imported/pre-bound here: candidate code imports it itself,
        # exactly like every real subsystem's own _build(p) already does (`import build123d as bd`
        # inside the function body). __builtins__ is left for exec() to auto-populate.
        _candidate_globals = {"math": math}
        exec(_build_code, _candidate_globals)
        build_fn = _candidate_globals.get("build")
        if build_fn is None or not callable(build_fn):
            raise RuntimeError("build_code did not define a callable build(p) function")

        result = build_fn(p)
        # Unwrap a TaggedPart-like {.solid, .tags} wrapper (packages/truth_plane/regen/templated.py) --
        # every real subsystem's own build() returns one of these; a candidate may also return the raw
        # build123d object directly (this phase's harness accepts either). Gated on BOTH `.solid` AND
        # `.tags` being present, not `.solid` alone -- verified directly before writing this: a raw
        # build123d shape (Box/Part/Compound/...) already carries its OWN `.solid` -- a bound METHOD
        # (Mixin3D.solid()), not a plain attribute -- so a `.solid`-only check would grab that callable
        # instead of the shape itself. No raw build123d shape carries `.tags`, so requiring both is an
        # unambiguous TaggedPart signature.
        solid = result.solid if hasattr(result, "solid") and hasattr(result, "tags") else result

        bb = solid.bounding_box()
        volume = float(solid.volume)
        bbox = [[float(bb.min.X), float(bb.min.Y), float(bb.min.Z)],
                [float(bb.max.X), float(bb.max.Y), float(bb.max.Z)]]
        _emit(_dumps({"ok": True, "volume_mm3": volume, "bbox_mm": bbox, "_token": _token}))
    except BaseException as exc:
        # `BaseException`, not `Exception`: a candidate's `build(p)` calling `sys.exit()` raises
        # `SystemExit`, which is a `BaseException` subclass, NOT an `Exception` subclass -- a plain
        # `except Exception` here lets it propagate straight past this handler and out of `_main()`
        # entirely, silently skipping the genuine result emission below and leaving whatever the
        # candidate already `print()`-ed standing as the only (and therefore "last") line of stdout.
        # Widening the catch to `BaseException` closes that specific escape (confirmed live). It does
        # NOT, and cannot, cover `os._exit()`, which terminates the process at the OS level without
        # running any more Python at all, including this `except` block -- that half of the fix is the
        # `_token` requirement above and in `_parse_last_result_line`: if the harness's own genuine line
        # is never emitted (killed before reaching it, however that happened), no token-matching line
        # exists on stdout and the parent correctly falls through to MALFORMED_OUTPUT instead of trusting
        # the candidate's forged one.
        #
        # Bounded traceback -- keep the single JSON line itself boundedly sized even if the candidate
        # raises from deep inside a pathological recursive structure.
        tb = traceback.format_exc()
        # `str(exc)` is NOT automatically safe the way `traceback.format_exc()` is: CPython hardens the
        # latter internally (a broken `__str__` inside the traceback becomes the literal substitute text
        # "<exception str() failed>"), but a plain `str(exc)` call here has no such guard -- a candidate
        # exception whose own `__str__` itself raises would make THIS line raise a second, uncaught
        # exception, escaping `_main()` before the JSON line below is ever printed (confirmed live: the
        # child then prints nothing and exits with only a raw traceback on stderr, and the parent-side
        # harness misreports the honest BUILD_ERROR as MALFORMED_OUTPUT, discarding the real message).
        # Guard it exactly the same way CPython guards the traceback formatter.
        try:
            _error_str = str(exc)
        except BaseException:
            _error_str = f"{type(exc).__name__}: <exception str() failed>"
        _emit(_dumps({"ok": False, "error": _error_str, "traceback": tb[-4000:], "_token": _token}))


_main()
'''


def _render_bootstrap(build_code: str, params: list[dict]) -> tuple[str, str]:
    """Returns `(script, token)`: the rendered bootstrap source AND the fresh per-call secret token
    embedded into it. The caller must hold onto `token` and pass it to `_parse_last_result_line` -- it
    is what lets the parent tell a genuine harness result line apart from a candidate forging the same
    JSON shape (see the `__RESULT_TOKEN_B64__` note above `_BOOTSTRAP_TEMPLATE`)."""
    params_b64 = base64.b64encode(json.dumps(params).encode("utf-8")).decode("ascii")
    build_code_b64 = base64.b64encode(build_code.encode("utf-8")).decode("ascii")
    token = secrets.token_hex(16)
    token_b64 = base64.b64encode(token.encode("utf-8")).decode("ascii")
    script = (_BOOTSTRAP_TEMPLATE
              .replace("__PARAMS_B64__", params_b64)
              .replace("__BUILD_CODE_B64__", build_code_b64)
              .replace("__RESULT_TOKEN_B64__", token_b64))
    return script, token


def _matches_result_shape(payload: object, expected_token: str) -> bool:
    """True iff `payload` is a dict shaped like the bootstrap's own unconditional JSON contract (see
    item (e) in this phase's own spec / the bootstrap template above) AND carries the exact per-call
    `expected_token` (see `_render_bootstrap`). The token check is not optional hardening layered on top
    of the shape check -- shape alone is exactly what a candidate can trivially forge by `print()`-ing
    its own hand-crafted `{"ok": True, ...}` line; only the harness itself ever knows `expected_token`,
    so this is what actually distinguishes a genuine result line from candidate-printed noise or an
    outright forgery."""
    if not isinstance(payload, dict) or not isinstance(payload.get("ok"), bool):
        return False
    if payload.get("_token") != expected_token:
        return False
    if payload["ok"]:
        if not isinstance(payload.get("volume_mm3"), (int, float)):
            return False
        bbox = payload.get("bbox_mm")
        if not (isinstance(bbox, list) and len(bbox) == 2):
            return False
        return all(
            isinstance(corner, list) and len(corner) == 3 and all(isinstance(v, (int, float)) for v in corner)
            for corner in bbox
        )
    return isinstance(payload.get("error"), str)


def _parse_last_result_line(stdout: str, expected_token: str) -> Optional[dict]:
    """Scan `stdout` from the END for the last line that both parses as JSON and matches the harness's
    own result shape, INCLUDING the exact per-call `expected_token` (see `_matches_result_shape`).
    Scanning from the end (rather than requiring stdout to contain EXACTLY one line) tolerates a
    candidate's own accidental `print()` noise inside `build_code` landing before the genuine line.

    Positional trust ("physically last") is deliberately NOT what makes this safe -- a candidate can
    make its OWN forged, correctly-shaped line the physically last (or only) line on stdout, either by
    raising `SystemExit` from `build(p)` (escaped a plain `except Exception`; the bootstrap now catches
    `BaseException` instead) or via `os._exit()` (terminates the process outright, which NO amount of
    exception-handling inside the child can intercept -- confirmed live both ways). What actually makes
    this safe is `expected_token`: a fresh secret generated host-side per call (`_render_bootstrap`)
    that the candidate has no ordinary way to read (it lives only in a local variable of the child's own
    `_main()`, never in the exec namespace `build_code` runs in), so a forged line lacking it is rejected
    regardless of where it sits in stdout. If the harness's own genuine line was never emitted at all
    (killed before reaching it, however that happened), no token-matching line exists and this returns
    None -- the caller reports MALFORMED_OUTPUT, an honest "unknown", never a fabricated OK."""
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _matches_result_shape(payload, expected_token):
            return payload
    return None


def _is_degenerate(volume: float, bbox: BBoxMM) -> bool:
    if not math.isfinite(volume) or volume <= _DEGENERATE_VOLUME_EPS_MM3:
        return True
    for lo, hi in zip(bbox[0], bbox[1]):
        if not (math.isfinite(lo) and math.isfinite(hi)) or (hi - lo) <= 0.0:
            return True
    return False


def _degenerate_reason(volume: float, bbox: BBoxMM) -> str:
    reasons: list[str] = []
    if not math.isfinite(volume) or volume <= _DEGENERATE_VOLUME_EPS_MM3:
        reasons.append(f"volume {volume!r} mm^3 is at/near zero or non-finite")
    for axis, lo, hi in zip("xyz", bbox[0], bbox[1]):
        if not (math.isfinite(lo) and math.isfinite(hi)) or (hi - lo) <= 0.0:
            reasons.append(f"{axis} extent [{lo}, {hi}] is zero/negative/non-finite")
    return "; ".join(reasons) if reasons else "degenerate geometry"


def sandbox_build_and_validate(
    build_code: str,
    params: list[dict],
    *,
    wall_clock_s: float = _DEFAULT_WALL_CLOCK_S,
    mem_limit_mb: Optional[int] = _DEFAULT_MEM_LIMIT_MB,
) -> SandboxSubsystemResult:
    """Execute a candidate `build(p)` definition out-of-process and classify the outcome.

    `build_code`: a Python source string that defines a top-level `def build(p): ...` returning a
    build123d solid (or a TaggedPart-like `{.solid, .tags}` wrapper — see the bootstrap docstring above).
    Nothing else in `build_code` is inspected or restricted at this phase — a static allow/deny-list on
    what candidate code may import/do is a LATER phase's concern (see this module's own docstring);
    this phase only answers "did it build, in bounded time, into something real."

    `params`: `[{"name": str, "value": float, "unit": str}, ...]` — enough to construct a read-only
    Namespace with each declared param at ONE resolved value (its default, typically). Deliberately NOT
    the full `ParamSpec` shape (no min/max/step) — bounds validation belongs to a different layer.

    Never raises: every failure mode (a harness-internal bug, a candidate exception, a wedged build, a
    corrupted stdout contract, degenerate geometry) resolves to a typed `SandboxSubsystemResult`.
    """
    bootstrap, token = _render_bootstrap(build_code, params)
    result = run_sandboxed(bootstrap, wall_clock_s=wall_clock_s, mem_limit_mb=mem_limit_mb)

    if result.status == "TIMEOUT_KILLED":
        return SandboxSubsystemResult(
            status="TIMEOUT_KILLED",
            message=f"candidate build exceeded the {wall_clock_s:.1f}s wall-clock limit and was killed",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    payload = _parse_last_result_line(result.stdout, token)
    if payload is None:
        return SandboxSubsystemResult(
            status="MALFORMED_OUTPUT",
            message="sandbox subprocess produced no parseable, correctly-shaped single-line JSON result",
            stdout=result.stdout,
            stderr=result.stderr,
        )

    if not payload["ok"]:
        return SandboxSubsystemResult(
            status="BUILD_ERROR",
            message=str(payload.get("error", "unknown build error")),
            traceback=payload.get("traceback"),
        )

    volume = float(payload["volume_mm3"])
    bbox_raw = payload["bbox_mm"]
    bbox: BBoxMM = (
        (float(bbox_raw[0][0]), float(bbox_raw[0][1]), float(bbox_raw[0][2])),
        (float(bbox_raw[1][0]), float(bbox_raw[1][1]), float(bbox_raw[1][2])),
    )

    if _is_degenerate(volume, bbox):
        return SandboxSubsystemResult(
            status="DEGENERATE",
            message=_degenerate_reason(volume, bbox),
            volume_mm3=volume,
            bbox_mm=bbox,
        )

    return SandboxSubsystemResult(status="OK", message="build succeeded", volume_mm3=volume, bbox_mm=bbox)
