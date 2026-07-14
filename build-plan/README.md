# Grounded Text-to-CAD — Build Program Tracker

Master index for turning the `prd-27-8.14` vision into a real product, engineered with Claude
(dev-time) and powered by Claude (runtime).

**Last updated:** 2026-07-14
**Current phase:** Phases 0–4 implemented & green (**502 backend tests pass on Windows** — `python -m
pytest tests -q`, 26 skip on dependency-gated markers, more in the Linux container) and the **full
wedge stack runs end-to-end on `docker compose up`**. Spike 4 fully PASSES (deflection-validated FS +
19/19 auto-mesh). Built across the phases: ledger + rules validator + event store/replay (in-mem + SQL
+ **Postgres**, though only the in-mem/sqlite paths are test-covered — see below), hero-bracket
end-to-end, sandbox kill-primitives, **strategic macro agent**, **OpenRouter/DeepSeek delta-emitter** +
runtime **CLI**, **derived-resolution + Dramatiq FS jobs**, **live `/optimize` 3-variant sweep**,
**project/branch service**, **neutral STEP/STL export**, **cost accounting**, and a **React +
react-three-fiber chat frontend** (builds clean). The live loop — chat/slider → real CalculiX FS /
optimize → export gate flips ELIGIBLE → STEP — is verified on compose. Gated/remaining: live keys (CI
secret), microVM isolation, PG **RLS**/multi-tenant auth, real slicer cost, WS status push (currently
polling), scale-infra, and the specialist spikes (OCAF identity, FEA methodology, legal).

**2026-07-14 — safety-gate hardening pass:** a full audit turned up two bugs directly against
Inversion #1 (a missing safety input must block export, never a fabricated green light), both fixed
and tested this session:
- `GET /export/step` exported geometry **unconditionally** — the export gate was only evaluated in
  the advisory `POST /export/check`, which a client could skip entirely. It now calls
  `evaluate_export_gates` itself and returns 409 with the blocking reasons when ineligible.
- The FS verdict cache ignored **load/material** — a verdict solved at one `(material, load_n)` (e.g.
  `/optimize`'s 25 N sweep) could be served back as "grounded" for a differently-requested case
  (`/analyze`'s 40 N default). `Verdict` now carries the case it was solved for, and the cache lookup
  matches on it.

Also fixed: a malformed WS frame (bad JSON, missing/extra/wrong-type field) killed the whole socket
with no NACK instead of just rejecting that one message; and engineer sign-off never reset after a
later geometry-class change (mutation/cut/instance add-remove-move), so one `ENGINEER_REVIEWED` could
silently cover every subsequent design change for the rest of a session. See
`packages/ledger/events.py`'s `GEOMETRY_CLASS_KINDS` reset and `packages/transport/app.py`'s `/ws`
handler.

**Not yet fixed** (found in the same audit, tracked here, ranked roughly by severity): no auth on any
endpoint + one global session shared by every client + anonymous callers can spend the operator's
OpenRouter budget; `PgEventStore` has no per-file/stream scoping (multi-file sessions corrupt each
other's history under the Postgres/compose path — only in-mem/sqlite are test-covered); Dramatiq jobs
are at-most-once with invisible failure (no retry, no failure surfaced to the poller); a user-added
cut feature can silently fragment the FS solver's boundary-condition face on a `fea_eligible` part,
producing a confident-but-wrong FS; the stated goal's load (e.g. "holds 200 N") never reaches the
solver — `HeuristicStrategicProvider` only parses FS/mass/hours tokens, so the enforced FS floor can
diverge from what the user actually asked for even though the verdict-cache fix above at least stops
the WRONG case's verdict from satisfying the request; full event-log refold + per-event deep-copy on
every read (no snapshotting) will not scale past a demo-length session; zero frontend tests.

**Also uncommitted-until-2026-07-14, now landed:** the whole catalog/architecture wave below was
sitting uncommitted in the working tree for ~2 weeks (HEAD was `a38732d`, dated 2026-06-28) — CI had
validated none of it. It's now split across 7 logical commits (ledger → truth-plane →
subsystems/disciplines → agents → transport → frontend → docs) plus the safety-fix commits above,
tree is green throughout. One real bug was caught and fixed in the process: `ogive_fuselage` dropped
its `wall_thickness_mm` param when it became a solid body, but `winged_fuselage` still forwarded it,
breaking every build of that composite part — fixed, with the stale "hollow shell" docstring language
and a geometry-level test assertion updated to match the solid-body behavior.

**Catalog/architecture work landed 2026-06-28 through 2026-07-06** (kept here as the durable "how we
got here" narrative — no longer "uncommitted", see above):

- **Scalable subsystem model** (`ParamSpec`/`Subsystem`): adding a part = one file, zero central
  edits. See [`reference/SCALABLE_SUBSYSTEM_REFACTOR.md`](reference/SCALABLE_SUBSYSTEM_REFACTOR.md).
- **Instance-tree ledger** (Phase G): `instances[<id>].params` — no single-active-part lock-in.
  See [`reference/INSTANCE_GRAPH_REFACTOR.md`](reference/INSTANCE_GRAPH_REFACTOR.md).
- **Catalog: 32 registered subsystems** — bracket, enclosure, standoff, lbracket, uchannel, panel,
  washer, table, flat_bar, square_tube, dowel_pin, cover_plate, t_bar, z_bracket, mounting_plate_grid,
  shaft_collar, hub, threaded_boss, motor_mount, hex_nut, hex_bar, hex_standoff, standoff_frame,
  round_post (solid cylinder primitive needed by `table` legs), saddle_clamp (an open semi-circular
  P-clamp cradling a cylindrical item, e.g. an EDF fan housing, pipe, or tube + two mounting bolts;
  grew directly out of a real "make an EDF holder" chat conversation the catalog couldn't satisfy),
  and 7 more added since (2026-07-04 through 07-06) reaching into aerospace-shaped geometry —
  **lofted_spindle**, **lofted_hull**, **naca_wing**, **ogive_fuselage**, **winged_fuselage**
  (ogive fuselage + NACA wing, boolean-fused into one printable body), **bulkhead_frame**,
  **longeron** — pure geometry only, no aero/propulsion/flutter analysis, per the `CLAUDE.md`
  cut-list.
- **Soft / advisory bounds** (2026-07-03): `ParameterDef.bounds` is now a recommended range, not a
  hard cap. Values outside range get `APPLIED_ADVISORY` status — the copilot judges context, not a
  clamp (`packages/ledger/{parameter,apply}.py`).
- **Phase F — composition helpers** (`packages/subsystems/compose.py`): `call`/`place`/`place_polar`/
  `compose`. One subsystem's `build` invokes another REGISTERED subsystem with per-instance overrides.
  Two composite-of-registered-parts subsystems live:
  - `standoff_frame` = `flat_bar` top-plate + N × `standoff` (first composite, 2026-07-03)
  - `table` = `flat_bar` tabletop + N × `round_post` legs (Phase F dogfooded 2026-07-03, replacing
    the old `render_table` inline; tags are now `top.bar.body` / `leg[i].post.body`)
  - **`packages/subsystems/assembly.py`** (2026-07-03) generalizes this from "one subsystem composing
    its own children" to "the whole PROJECT composing every instance in the tree" — see the outliner
    bullet below.
- **FEA + optimize coverage expanded** (2026-07-03, +`longeron` 2026-07-06): the Gmsh+CalculiX FS
  pipeline (`/analyze`) covers **7 single-solid plate/bar subsystems** sharing the validated
  cantilever methodology (`fea_eligible=True` on bracket, flat_bar, cover_plate, motor_mount, panel,
  mounting_plate_grid, longeron). One caveat found in the 2026-07-14 audit: `longeron`'s own
  load-bearing dimension is `height_mm`, not a `*_thickness_mm` param, so the generic min-wall floor
  check (`packages/truth_plane/analysis.py::_min_wall_ok`) is trivially satisfied for it — not yet
  fixed, tracked above. The 3-variant sweep (`/optimize`) is now generalized the same way — it
  discovers and sweeps ANY `fea_eligible` subsystem's own `*_thickness_mm` param instead of a
  hardcoded bracket-only `skin_thickness_mm`. Every OTHER subsystem (compounds, cylinders,
  assemblies, or anything not
  explicitly vetted) returns FS = `None` from `/analyze` and `"unsupported"` from `/optimize` —
  never a fabricated load case or a silently-wrong sweep.
- **Multi-instance outliner, now with real assembly composition** (2026-07-03): a project can hold
  more than one independently-editable part (e.g. a bracket AND a standoff in the same project).
  Backend: `/instances` CRUD in `packages/transport/app.py`, backed by proper **`INSTANCE_ADDED`/
  `INSTANCE_REMOVED` event-sourcing facts** (`packages/ledger/events.py`) — adding/removing a part no
  longer wipes the project's prior mutation/signoff history, the gap the original MVP explicitly
  flagged as a known limitation. Frontend: `Outliner.tsx` (add/remove/activate rows) + `SwitchCard.tsx`
  (AI-proposed part-type changes) wired in `App.tsx`. **Assembly-wide rendering is live**: `/mesh`,
  `/export/step`, and telemetry (mass/CG/cost) now compose EVERY instance in the tree — via
  `packages/subsystems/assembly.py`'s auto-layout (instances with no explicit `Transform` are spaced
  apart automatically so they never overlap) or an explicit `Transform` when set — the moment a
  project holds more than one instance. A single-instance project (still the common case) is
  byte-for-byte unaffected.
- **Deterministic cascade deltas** (2026-07-03, prd4.md §2.2): `apply_delta` can now apply a
  companion change to a DIFFERENT param alongside the direct edit — e.g. bracket's edge-distance
  rule cascades `plate_depth_mm` up when a bigger bolt hole would otherwise violate it, instead of
  outright rejecting the request. Purely deterministic (`packages/ledger/apply.py::CascadeRule`, a
  caller-supplied function — `packages/ledger` still has zero dependency on `packages/subsystems`),
  never LLM-originated, and NEVER overrides a `HARD_LOCK` param. Surfaced on the wire as
  `cascades_applied` and in the chat's proposal card.
- **Rough click-to-select** (2026-07-03, prd4.md Phase 3): `GET /mesh/features` +
  `packages/subsystems/features.py` expose every generator-baked tag with a usable position (holes,
  bores, mount points), letting the viewport show a small info card for whichever feature was
  nearest a click. An honest partial version of the PRD's "context-aware floating HUD" — the precise
  face-level version still needs OCCT topological identity (Spike 1, specialist-gated).

> ⚠️ Host note: the dev machine's **C: drive is full** — point Python/npm temp at D:
> (`TEMP=D:/pytmp`) or tests that write temp files will hit `OSError: No space left on device`.

---

## The strategic call (read this first)

> **Do not build the aerospace UAV product first.** Build a **conversational generator for
> functional printable/machinable parts** — brackets, mounts, enclosures, fixtures, jigs — with
> real DFM, a real slicer-backed cost/time number, and a real Gmsh+CalculiX factor-of-safety
> under *one* declared load.

This wedge exercises every load-bearing thesis while shedding everything un-shippable (flutter,
CFD aero, propulsion/range, kinematics, bonded-joint FEA, ITAR, AS9100). **Aerospace is the
Series A/B narrative, matured behind the wedge — never the thing we build first.**

## The three inversions (non-negotiable — pin these in every `CLAUDE.md`)

1. **The LLM never originates a safety scalar and never emits free Python.** It emits
   Pydantic-validated parameter deltas; a deterministic Jinja2 + build123d templater renders the
   script; real solvers (Gmsh+CalculiX, etc.) produce every FS/stall/flutter/range number. Missing
   inputs → `"unknown"` (blocks export), never a fabricated green light.
2. **The single clock is a fiction.** Three honest tiers: 30 Hz analytic HUD / kernel regen on
   slider-release / minutes-scale solver+optimizer DAG.
3. **Persistent topological identity** (generator-baked tags + OCAF/TNaming) is the keystone bet.

## Architecture spine

Grounded **two-plane Python monolith**: an Interactive Plane (closed-form, in-process, <1 ms/number)
and a Truth Plane (OCCT regen, FEA, slicing, optimization — durable async jobs, content-addressed,
never blocks a frame, never re-invoked on replay). Full detail: [`reference/TECH_PLAN.md`](reference/TECH_PLAN.md).

---

## Phase ladder

| Phase | Window | Goal | Status |
|-------|--------|------|--------|
| **0 — De-Risk Spikes** | 0–30 d | Prove/kill the 5 keystone bets | 🟢 Harness green; **determinism** + **Spike 4 (solver)** validated; Spike 1 (identity) partial; legal §3a + arm64 gated → [`PHASE_0.md`](PHASE_0.md) |
| **1 — Foundation** | 30–90 d | Hardened deterministic substrate | 🟢 **Backbone done** (ledger, event store + replay, rules validator, review FSM, determinism, 1 solver) → [`PHASE_1.md`](PHASE_1.md) |
| **2 — MVP** | 3–6 mo | Grounded product w/ human-in-loop | 🟢 **Backbone done** (requirements matrix, BOM/datums, agent loop + evals, WS protocol + NACK, estimator) → [`PHASE_2.md`](PHASE_2.md) |
| **3 — Scale / Aerospace** | 6–12 mo | Multi-tenant, audit-ready | 🟡 **Core arch done** (branching + invariant-aware merge, content-addressed event-sourcing); infra/optimizer/aero gated → [`PHASE_3.md`](PHASE_3.md) |
| **4 — Truth-Plane Activation** | — | The grounded analysis loop, live | 🟢 **Built & verified LIVE on compose**: derived-resolution, Dramatiq FS jobs, Postgres, `/analyze`→export-flip, **`/optimize` 3-variant sweep via the worker**. End-to-end on `docker compose up`: optimize → real CalculiX → export ELIGIBLE → STEP downloads → [`PHASE_4_truth_plane.md`](PHASE_4_truth_plane.md) |

> "Backbone done" = the load-bearing architecture is implemented in code and green under test. It is
> **not** a shippable product: no frontend, no microVM sandbox, no DB, no real LLM/slicer, no
> scale-infra, and the specialist-gated spikes (identity, FEA robustness, legal) remain. See each
> phase doc's "Remains" section.

> ⚠️ **Timeline realism (from the critique):** Claude accelerates the typed-glue ~50%, but the
> critical path is the OCAF identity bet + FEA correctness — the two things Claude does *not*
> accelerate. Treat **~9–12 months to a defensible product** as the real number; 12–16 weeks gets
> the *foundation slice*, not the MVP.

---

## Repository / docs layout

```
build-plan/
  README.md                  ← this file (program tracker)
  PHASE_0.md                 ← active phase tracker + progress + docs
  spikes/                    ← the 5 kill-criteria docs (the actual Phase 0 artifacts)
    SPIKE_1_topological_identity.md
    SPIKE_2_3_codegen_sandbox.md
    SPIKE_4_solver_fs_roundtrip.md
    SPIKE_5_two_plane_latency.md
  reference/
    TECH_PLAN.md                       ← recommended final tech plan (architecture, stack, tiers, event-sourcing)
    DOMAIN_TAXONOMY.md                 ← disciplines × subsystems matrix; the wedge→recon-UAV bridge (grounded, not guessing)
    SCALABLE_SUBSYSTEM_REFACTOR.md     ← 2026-07-02: ParamSpec/Subsystem model + generic Domains.geometry bag; supersedes prd4 §1
    INSTANCE_GRAPH_REFACTOR.md         ← 2026-07-02: instance-tree ledger (Phase G) — supersedes the flat geometry bag with instances[<id>].params
    PLAYBOOK.md                        ← full build playbook (phases, Claude operating model, harness, team)
    gap-analysis-raw.json    ← 8 existential risks, ranked gaps, missing subsystems, judged plans
    playbook-critique.json   ← skeptic reality-check (12 overlooked + 11 overoptimistic items)
```

(Future: `PHASE_1.md`, `PHASE_2.md`, `PHASE_3.md`, plus `decisions/` for the architecture-blocking
decision log once we start resolving them.)

## How to use this tracker

- Each phase has its own `PHASE_N.md` with a live checklist, a progress log, and the exit gate.
- Update the **Status** column above and the phase file's progress log as work lands.
- The reference docs are the durable source of truth; the gap analysis and critique are the
  "why" behind every decision here.
