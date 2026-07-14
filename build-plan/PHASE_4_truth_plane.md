# Phase 4 — Truth-Plane Activation (the grounded analysis loop, live)

**Status:** 🟢 **DONE & verified live.** Loop green on Windows, real-CalculiX e2e green in the
container, AND the **full wedge stack runs end-to-end via `docker compose up`**: a slider change →
`/analyze` **queued to the Dramatiq worker** → real CalculiX (~8 s) → verdict → the export gate
**flips ELIGIBLE** → Sign off & **Export STEP**; a geometry change makes it **stale**; verdicts +
events **persist in Postgres across a backend restart**. (Docker had wedged on a full C: — fixed by
freeing C: + a hard Docker Desktop restart.)
**Goal:** *chat/slider → change a parameter → real CalculiX FS (durable async job) → the export gate
flips ELIGIBLE in the browser.* Activates the third architecture tier on the documented wedge stack.

## The keystone design — derived resolution

`derived.*` is a **derivation of the current geometry**, not a replayed fact. So a verdict is recorded
keyed by a **geometry signature** (hash of the geometry-affecting params) + toolchain fingerprint, and
the current `derived` is **resolved at read time** from the latest matching verdict — **no match
(params changed) → "unknown" → export blocked.** Replay stays a pure fold over facts; derivations are
resolved, never folded. (`packages/ledger/derived_resolver.py`.)

## Done (in code)

| Piece | Module | Tests |
|---|---|---|
| **Derived resolver** (signature, latest-verdict, resolve, auto-invalidate) | `ledger/derived_resolver.py` | `tests/ledger/test_derived_resolver.py` ✅ |
| **Grounded analysis** (render → CalculiX FS → validity → Verdict; runs in a child process so gmsh gets a main thread) | `truth_plane/analysis.py` | `tests/solvers/test_analysis_flow.py` ✅ (real CalculiX) |
| **Dramatiq actor** (idempotent FS job; StubBroker in tests, Redis in worker) | `truth_plane/jobs.py`, `worker.py` | `tests/backend/test_jobs.py` ✅ |
| **Verdict store** (in-memory + Postgres) | `truth_plane/verdict_store.py`, `ledger/event_store_pg.py` | (pg via compose) |
| **API:** `/analyze` (inline or queued, cached), `/analyze/status`, `/signoff`, `/export/step`; `/export/check` resolver-based | `transport/app.py` | `tests/backend/test_analysis_api.py` ✅ |
| **Postgres persistence** (event store + projects survive restarts) | `ledger/event_store_pg.py` | (compose) |
| **Compose stack** (backend+SPA / worker / redis / postgres) | `docker-compose.yml`, `docker/Dockerfile.app` | (compose) |
| **Frontend:** Analyze rail, FS + solver-time, export chip flip, **stale on change**, **Sign off & Export STEP** | `frontend/src/{AnalysisBar,App,api}` | `npm run build` ✅ |

**Suite:** 91 passed / 15 skipped on Windows; ruff + gates clean; frontend builds. The whole loop
(blocked → analyze → sign-off → **ELIGIBLE** → change → **stale** → re-analyze → eligible, idempotent
cache, real STEP export) is verified in `test_analysis_api.py` with the solver faked (build123d export
is real); the real CalculiX FS is already validated in `test_fs_cantilever` + the hero pipeline.

## Live run

```
docker compose up --build      # -> http://localhost:8000  (backend serves the SPA + solvers)
```
(Docker had wedged on a 100%-full C: — Docker Desktop's data lives on C:. Freeing C: + a hard restart
of Docker Desktop recovered it; the real-CalculiX container e2e is green.) The container test alone:
`docker run --rm -v $PWD:/app gtc-dev pytest tests/solvers/test_analysis_flow.py`.

## Optimization — the 3-variant sweep, wired live

The sanctioned in-scope optimizer (CLAUDE.md cut-list: *use a 3-variant sweep*, not NSGA-II) is now an
**Optimize** action in the running app: find the **lightest** skin that clears the FS floor, then apply it.

| Piece | Module |
|---|---|
| **Sweep + pick** (`_run_optimize`: render each candidate → real CalculiX FS → mass `ρ·A·skin`; pick the thinnest feasible) | `truth_plane/analysis.py` |
| **Subprocess wrapper** (`optimize_in_subprocess`, spawn child — gmsh needs a main thread) | `truth_plane/analysis.py` |
| **Dramatiq actor** `run_optimization` (stores best `Verdict` + variants summary) | `truth_plane/jobs.py`, `worker.py` |
| **API** `POST /optimize` (queued→worker when `REDIS_URL`, else inline/monkeypatchable), `GET /optimize/status` | `transport/app.py` |
| **Optimize-results table** (upsert by project, survives restart) | `ledger/event_store_pg.py`, `verdict_store.py` |
| **Frontend** Optimize button → poll `/optimize/status` → apply best skin via the WS rules path → variants table | `frontend/src/{AnalysisBar,OptimizeResult,App,api}` |

Same uvicorn-can't-spawn constraint as `/analyze`: the sweep runs in the **worker** (where spawn is
clean), the backend only enqueues and the browser polls. `test_analysis_api.py::test_optimize_picks_lightest_feasible_applies_and_flips` covers the inline path (faked solver) — 4 passed.

**Live (compose) verified end-to-end:** `POST /optimize` → `queued` → worker runs the real CalculiX
sweep over skin ∈ {2,3,4,5}mm → FS `0.57 / 1.25 / 2.22 / 3.39` → **best_skin = 4.0** (lightest design
clearing FS ≥ 1.5; 3mm @ 1.25 fails) → frontend applies 4.0 via WS (`2.0→4.0 APPLIED`) → the stored
verdict resolves → export flips **EXPORT_ELIGIBLE** → a real 30 KB ISO-10303-21 **STEP** downloads.

## Goal-grounded conversational design (the AI layer, wired live)

The chat was a stateless delta-puppet — it nudged sliders but had no concept of the user's **goal**.
The strategic requirements layer (`agents/strategic.py`, `ledger/requirements.py`) existed but was
orphaned. Now the session carries the goal as a `VerificationMatrix` and judges the design against it.

| Piece | Module |
|---|---|
| **Goal → targets** (`StrategicAgent.plan`: NL goal → `Requirement`s; never originates a safety value, only TARGETS) | `agents/strategic.py` |
| **Grounded metric snapshot** (`SessionState.metrics`: FS from the **resolved real-solver verdict**, mass/time from deterministic geometry) | `transport/app.py` |
| **API** `POST /requirements` (set goal), `GET /requirements` (compliance readout: per-req SATISFIED/VIOLATED/**UNKNOWN** + `implied_fs_floor`) | `transport/app.py` |
| **Single input** — the goal is stated **in the chat** (no separate box); each user message folds any stated TARGETS into the goal via `StrategicAgent.merge` (upsert by metric; a no-target message is a no-op, so ordinary chat never wipes the goal). The compliance panel is **read-only**. | `agents/strategic.py`, `frontend/src/{chat/Chat,RequirementsCard,App}` |

**The keystone — inversion #1 made conversational:** `factor_of_safety` in the readout comes from the
real verdict, so it is **UNKNOWN until a solver has run for the current geometry** — never assumed
green. Mass / print-time are deterministic geometry and are known immediately. Tests:
`test_requirements_api.py` (goal parse → targets + implied FS floor; FS UNKNOWN→SATISFIED after analyze;
a too-strict goal reported VIOLATED, not hidden) — 4 passed.

**Live (compose) verified:** goal *"holds 200 N at FS 2, under 200 g"* → `implied_fs_floor 2.0`; FS
judged **SATISFIED at 2.22** against the real verdict for the matching geometry; change skin 4→3.5
(no verdict) → FS flips to **UNKNOWN** while mass stays known (160 g). The conversation now knows the
goal and refuses to claim safety it can't prove.

**The goal is ENFORCED, not just reported** (`SessionState.effective_fs_floor` = max(default, goal)):
- The **export gate** raises its FS floor to the goal at read time — an already-eligible design (FS
  2.4 vs default 1.5) goes **BLOCKED** the moment a stricter "FS 3" goal is stated.
- **Optimize is goal-aware** — the sweep targets the effective floor, and the card surfaces a *"Find
  the lightest design meeting FS ≥ N"* action when FS is unmet. Live: with an "FS 3" goal, Optimize
  rejects skin 2/3/4 (FS 0.56/1.24/2.17) and picks **skin 5 (FS 3.36)** — a stronger design than the
  default-floor sweep's skin 4. The LLM sets the target; the deterministic gate + real solver enforce it.

## Domain — a tunable plate footprint (real geometric freedom)

The part was locked to a 60×40 plate. **Width and depth are now tunable** (`structure.plate_width_mm`
40–120, `plate_depth_mm` 30–80) — continuous box dims (no topology change → clear of the identity
wall) that drive the FEA *and* the mass. The agent now designs a 4-DOF mounting plate (footprint +
skin + hole), not one fixed bracket.

| Piece | Module |
|---|---|
| **Schema params** width/depth, **in `GEOMETRY_PARAMS`** (footprint change invalidates the verdict) | `ledger/schema.py`, `ledger/derived_resolver.py` |
| **Threaded through** render, `/mesh`, `current_params`; **mass = density·(w·d)·skin** (real footprint, not a constant) | `truth_plane/analysis.py`, `transport/app.py` |
| **Optimize refactor** — the sweep takes a `base_params` dict (rib/hole/footprint held fixed) instead of one positional arg per param; the actor/endpoint pass it through | `truth_plane/analysis.py`, `jobs.py`, `transport/app.py` |
| **Frontend** width/depth sliders + the viewport re-renders the real geometry on resize | `frontend/src/{FloatingControls,Viewport,App}` |

Tests: `test_resizing_the_plate_footprint_invalidates_verdict`. **Live-verified:** widen 60→100mm →
mass rises (geometry-driven), `/mesh` honors it, and Optimize (base_params → worker) returns variants
whose mass scales exactly with the 100×40 footprint (skin 5 → 24.8 g vs 14.9 g at 60×40) — proving
width reaches both the mass model and CalculiX. (Schema change → demo-DB reset, as before.)

## Domain — a tunable bolt-hole feature (the part gets designable)

The part was a plate with **hardcoded** bolt-holes (`n_holes=4, hole_dia=6mm`) — the agent could only
move wall/rib. Bolt-hole **diameter** is now a tunable ledger param (`manufacturing.hole_diameter_mm`,
bounds 3–10mm), so the AI can design a real feature.

| Piece | Module |
|---|---|
| **Schema param** `hole_diameter_mm` (the hole COUNT stays fixed — it is topology-changing, the OCAF identity wall) | `ledger/schema.py` |
| **In the geometry signature** — resizing a hole invalidates the FS verdict (it changes the stress field) | `ledger/derived_resolver.py` (`GEOMETRY_PARAMS`) |
| **Threaded through** render (`analyze_geometry`), the optimize sweep (held fixed), `/mesh`, `current_params` | `truth_plane/analysis.py`, `transport/app.py` |
| **Frontend** bolt-hole slider + the viewport re-renders the real geometry on resize | `frontend/src/{FloatingControls,Viewport,App}` |

Tests: `test_derived_resolver.py::test_resizing_a_bolt_hole_invalidates_verdict` (Windows). **Live
(compose) verified:** the hole size flows to CalculiX — FS `0.2826` (6mm) vs `0.2802` (9mm) at the
same skin/load, a real signed change (bigger hole → more stress). NB: a schema change needs a demo-DB
reset (`TRUNCATE events,verdicts,optimize_results,artifacts`) — the old genesis lacks the new required
field; in production this is a migration.

## FEA coverage expansion — past bracket-only (2026-07-03)

`analyze_geometry` was hardcoded to `render_bracket` — every OTHER subsystem's `/analyze` would
either crash or silently return nothing meaningful. Generalized to build geometry via the SUBSYSTEM
REGISTRY (any registered part), gated by a new `Subsystem.fea_eligible` flag (default `False`) plus a
runtime single-solid check (defense in depth — a compound assembly never gets a fabricated load case
even if mis-flagged).

| Piece | Module |
|---|---|
| `fea_eligible` opt-in flag + `geometry_paths(subsystem, instance_id)` | `packages/subsystems/base.py` |
| Generalized `analyze_geometry(params, material, load_n, subsystem_name="bracket")` — builds via the registry, gates real FS on `fea_eligible` + single-solid | `packages/truth_plane/analysis.py` |
| Generalized `geometry_signature`/`latest_verdict`/`ledger_with_derived` (optional `geometry_params` override; default preserves bracket-only behavior) | `packages/ledger/derived_resolver.py` |
| Generalized `check_invariants`'s min-wall floor: scans every instance for ANY `*_thickness_mm` param, not just root's `skin_thickness_mm` | `packages/ledger/apply.py` |
| `/analyze` reads the ACTIVE INSTANCE's own subsystem + full param set (`SessionState.current_params()`, `active_instance()`) instead of a fixed bracket param list | `packages/transport/app.py` |

**Eligible today** (single-solid, plate/bar-shaped, span along local X, same validated cantilever
methodology as the original bracket — clamp one end via geometric face-selection, load the other):
`bracket`, `flat_bar`, `cover_plate`, `panel`, `motor_mount`, `mounting_plate_grid`.

**Deliberately NOT eligible** (honest "unknown", not a gap): `t_bar`/`z_bracket` (multi-Box unions —
the min/max-X end face may be split across two co-planar OCCT faces; `_axis_extreme_surface` only
picks ONE, so the boundary condition could silently clamp/load only part of the cross-section — an
unverified risk, not worth the safety tradeoff for two subsystems); every compound/assembly subsystem
(`enclosure`, `table`, `standoff_frame`, …); every cylindrical/rotational part (`standoff`, `hub`,
`shaft_collar`, `hex_nut`, `washer`, …) — a fixed-base torsion/compression load case has no validated
closed-form oracle in this codebase (FEA methodology for those shapes stays FEA-engineer territory,
per `packages/truth_plane/CLAUDE.md`).

`/optimize` (the 3-variant sweep) is now generalized the same way as `/analyze` (see below) — it
discovers and sweeps whatever `*_thickness_mm` param the ACTIVE subsystem declares
(`_thickness_param_name`), instead of a hardcoded `skin_thickness_mm` sweep. A subsystem that isn't
`fea_eligible` (no validated FS oracle) gets an honest `{"status": "unsupported"}` from `/optimize`
rather than a silently wrong or no-op sweep — the sweep needs a real FS number to judge feasibility,
and a non-eligible subsystem's FS is always `None`, so nothing would ever come back "feasible."

Tests: `tests/solvers/test_analysis_multi_subsystem.py` — 15 pass everywhere (including this Windows
dev box, no gmsh needed: the non-eligible path proves it never even imports the solver module) + 8
more (needs_solver, mocked `evaluate_fs`) that run in the Linux container. Live-verified on `:8001`:
`standoff` → `/analyze` returns `{"status":"done","verdict":{"factor_of_safety":null,...}}` cleanly;
`flat_bar`/`bracket` → both reach the real solver import (failing identically on gmsh-less Windows —
proven parity, not a regression).

## Optimize generalized past bracket-only (2026-07-03)

`packages/truth_plane/analysis.py::_run_optimize` used to hardcode `skin_thickness_mm` and a
bracket-shaped `width × depth × skin` mass formula. Generalized: `_thickness_param_name(sub)` finds
whichever param a subsystem declares ending in `thickness_mm` (same convention `_min_wall_ok`
relies on); `_mass_g_for` computes mass via the subsystem's OWN `.volume` function (not a
bracket-specific area formula). `_run_optimize`/`optimize_in_subprocess`/`_optimize_worker` all take
`subsystem_name` now (defaulting to `"bracket"` so nothing pre-2026-07-03 breaks). The result dict's
keys changed (`"skin"` → `"value"`, `"best_skin"` → `"best_value"`, new `"param_name"`) — deliberately,
not preserved for compat, since the value swept is no longer always a skin thickness. `/optimize`
(the endpoint) discovers the target generically and returns `target_node` (the exact dotted path
applied) so the frontend never hardcodes which param it's mutating.

Tests: `tests/solvers/test_optimize_multi_subsystem.py` (mirrors `test_analysis_multi_subsystem.py`'s
two-group split) + `tests/backend/test_analysis_api.py`'s new
`test_optimize_works_for_a_newly_eligible_non_bracket_subsystem`. Live-verified on `:8001`: `flat_bar`
→ `/optimize` reaches the real solver import (same gmsh-less-Windows parity as `/analyze`); `standoff`
→ clean `{"status":"unsupported", "message": "...needs a fea_eligible subsystem with a *_thickness_mm param"}`.

## The multi-instance outliner — with real assembly composition (2026-07-03)

The instance-tree ledger (Phase G) always supported multiple instances; nothing before this exercised
it — every project had exactly one (`root`). Landed the first real multi-instance UX (add/remove/
activate) AND the assembly-composition increment the original MVP explicitly deferred, in the same pass.

| Piece | Module |
|---|---|
| `add_instance`/`remove_instance` (seed/validate a new Instance from a registered subsystem's defaults; refuse deleting root or a parent with children — no silent cascade) | `packages/subsystems/__init__.py` |
| `SessionState.active_instance_id` + `active_instance()` — which instance `/params` targets for editing (mesh/export/telemetry now go wider — see below) | `packages/transport/app.py` |
| `GET /instances`, `POST /instances`, `DELETE /instances/{id}`, `POST /instances/{id}/activate` | `packages/transport/app.py` |
| `mutate()` dispatches invariant checks on the TARGET instance the delta's own dotted path encodes (not the session's active pointer) — correct regardless of what the UI has selected | `packages/transport/app.py` |
| **`INSTANCE_ADDED`/`INSTANCE_REMOVED`** — proper incremental event-sourcing facts (payload = the full `Instance`, or just its id to remove); `replay()` applies them as a pure `ledger.instances` dict update, no import outside `packages.ledger` | `packages/ledger/events.py` |
| **`instance_world_offsets(ledger)`** — every instance's world-space `(x,y,z)` offset: explicit `Transform` honored (recursively, arbitrary parent-chain depth) when set, else auto-laid-out along +Y with a real gap seeded from the PARENT's own footprint AND between every consecutive sibling pair | `packages/subsystems/assembly.py` |
| **`render_assembly(ledger)`** — composes EVERY instance's geometry via `compose.py`'s `place()`/`compose()`, tags namespaced by instance id, skips a broken instance rather than crashing the whole render | `packages/subsystems/assembly.py` |
| `Outliner.tsx` — lists instances, add/remove/select | `packages/frontend/src/Outliner.tsx` |

**What changed from the original MVP:** `/instances` add/remove no longer wipes the event log —
prior mutation/signoff history survives (verified: mutate a param, THEN add an instance, THEN fold —
both effects present). `/mesh`, `/export/step`, and `_telemetry` (mass/CG, plus `cost_usd` in
`packages/disciplines/cost.py`) now compose/sum EVERY instance the moment a project holds more than
one — a single-instance project (still the common case) is byte-for-byte unaffected (same code path,
same output, as guaranteed by `_render_geometry`'s `len(ledger.instances) > 1` branch). `/export/step`
names the file `assembly.step` instead of the single subsystem's name once multi-instance.

**Caught during review, not shipped broken:** the first cut of the auto-layout only inserted a gap
between a parent and its FIRST auto-placed child — later siblings were packed back-to-back with zero
clearance from each other, capable of overlapping outright once a later sibling's extent exceeded an
earlier one's. Fixed to insert the gap before EVERY auto-placed instance; regression-tested with three
same-type siblings asserting identical, non-zero pairwise gaps. Separately, `saddle_clamp`'s (see
below) first cut drilled its mounting holes dead-center under the open channel, where only a ~4mm
floor remained — moved them into genuinely solid "ear" material beside the channel, and widened the
default block so real M4-class ears actually fit beside a 70mm cradle.

Tests: `tests/backend/test_instances.py` — 16 pass (CRUD, activation-scoped `/params`/`/mesh`,
mutate-targets-by-path-not-active-pointer, delete refuses root/parent-with-children, mutation history
survives add, mesh/export compose the whole assembly, telemetry sums mass across instances) +
`tests/subsystems/test_assembly.py` — 9 pass + `tests/ledger/test_events.py` — 9 pass (5 pre-existing
+ 4 new). Live-verified on `:8001` end to end: mutate `saddle_clamp.bore_dia_mm` → add a `standoff`
instance → mutation survives in the ledger → `/mesh` grows from 1400 to 2304 verts (both parts
composed) → `/export/step` downloads `assembly.step` → mutating the SECOND instance's own param
returns a telemetry `cg_mm` genuinely off-origin (proving real mass-weighted composition, not just
echoing one part's centroid).

## A new subsystem, straight from a real chat conversation (2026-07-03)

A user tried to design an EDF (ducted-fan) holder in chat and hit a real gap: nothing in the catalog
could cradle a cylindrical item — the closest fits (`panel`, `motor_mount`) are flat plates with
through-holes, not a saddle/cradle. Added `saddle_clamp`: an open semi-circular channel cut into a
mounting block (the item rests in the channel and lifts straight out, or a strap closes it), plus two
mounting bolts through solid ear material beside the channel. Built with the SAME boolean techniques
every other subsystem already uses (`Box`/`Cylinder` + `Rotation`/`Pos`, an over-cut for a clean
boolean) — no new sweep/loft geometry capability needed, and deliberately NOT `fea_eligible` (the
channel cuts through both X ends, so it isn't a single-face-per-end box — doesn't qualify for the
validated cantilever methodology; FS honestly stays "unknown").

Tests: `tests/subsystems/test_saddle_clamp.py` — 6 pass (registered/`fea_eligible=False`, positive
volume, invariants clean at defaults, an invariant violation correctly flagged, geometry builds as a
single connected manifold — proving a genuinely OPEN channel not a closed/split part, mount holes
verified clear of the channel radius).

## Deterministic cascade deltas (2026-07-03) — prd4.md §2.2, built for real

The product spec's WS contract (§2.2) shows a `PARAMETER_CASCADE_UPDATE` response carrying BOTH the
direct edit AND `cascades_applied` — other params the system automatically adjusts as a side effect
(their example: locking a pin to 4.5mm auto-thickens a coupled wall to 2.2mm, with a reason, instead
of the edit being rejected). This never existed — `apply_delta` only ever touched the one requested
node; a coupled invariant violation was an outright CONFLICT, no matter how reasonable the request.

| Piece | Module |
|---|---|
| `CascadeRule` type (`ledger, target_node, requested_value -> [(companion_node, value, reason), ...]`), `resolve_path(ledger, path)`, `CascadeEffect`, `ApplyOutcome.cascades` | `packages/ledger/apply.py` — stays a LEAF package, no `packages.subsystems` dependency; the caller supplies the rule |
| `apply_delta(..., cascade_rules=...)` — evaluates against the PRE-edit ledger, applies atomically alongside the direct edit (both land or neither does), NEVER overrides a HARD_LOCK param, re-checks invariants with cascades in place before committing | `packages/ledger/apply.py` |
| Bracket's concrete rule: growing `hole_diameter_mm` past the edge-distance limit (`hole_dia ≤ depth/3`) cascades `plate_depth_mm` up to the minimum value that satisfies it | `packages/subsystems/bracket.py::_cascade` |
| `Subsystem.cascades` / `SubsystemContext.cascades` — optional, `None` by default; only bracket declares one so far | `packages/subsystems/base.py`, `packages/subsystems/__init__.py` |
| `CascadeUpdate.cascades_applied: list[CascadeEffect]` on the wire | `packages/transport/protocol.py`, `packages/transport/app.py::mutate` |
| Chat's `ProposalCard` shows cascaded changes nested under the direct edit (↳ *cascaded*) | `packages/frontend/src/chat/ProposalCard.tsx` |

**A real bug caught in review, not shipped broken:** the cascade showed up correctly in the WS
response but was never persisted — `mutate()` only appended the DIRECT edit to the event log, so the
cascaded param's new value would vanish on the next fold/replay. Fixed by committing each cascade as
its own `PARAMETER_MUTATION` event, ordered BEFORE the direct edit's event — `events.py`'s `replay()`
needed zero changes, since by the time the direct edit's event replays, the ledger already carries
the companion value from the cascade event just before it (same trick as ordering matters for a
plain sequence of facts). A second, smaller bug: the frontend only updated the DIRECTLY edited
param's slider on a cascade response, leaving the cascaded param's slider visibly stale until the
next full reload — fixed in the same pass.

Tests: `tests/ledger/test_apply.py` — 11 pass (6 pre-existing regression-free + 5 new: companion
change lands atomically, a cascade targeting a HARD_LOCK is silently skipped, an insufficient
cascade CONFLICTs the WHOLE operation with the ORIGINAL ledger object returned unchanged,
`resolve_path` correctness, omitting `cascade_rules` matches passing `None`). Plus
`tests/subsystems/test_subsystems.py` (bracket's concrete rule, end-to-end through `apply_delta`)
and `tests/backend/test_app.py::test_ws_cascade_grows_plate_depth_for_a_bigger_bolt_hole` (the full
WS round trip, including that the cascaded value survives a `/ledger` re-read). Live-verified on
`:8001`: a 15mm/M12-class hole request (`APPLIED_ADVISORY` — outside `hole_diameter_mm`'s own
recommended range) cascades `plate_depth_mm` from 40 → 45mm with the stated reason, and both values
persist across a fresh ledger fold.

## Rough click-to-select groundwork (2026-07-03) — prd4.md Phase 3, the honest partial version

The spec wants clicking a component in the viewport to anchor a "context-aware floating HUD" to that
specific component. The PRECISE version needs OCCT topological identity — specialist-gated, Spike 1
still only partial. This is a deliberately ROUGH stand-in that needs none of that: every subsystem
already bakes stable, generator-authored tags into its geometry (`hole[0].bore`, `mount[1].bore`, …),
many carrying a `"center"` position computed as plain arithmetic from the subsystem's own params.

| Piece | Module |
|---|---|
| `list_pickable_features(ledger)` — walks every instance, keeps tags with a usable `"center"` (skips whole-body tags and `_placement` positioning metadata), offsets by `instance_world_offsets()` for multi-instance projects | `packages/subsystems/features.py` (pure, no HTTP) |
| `GET /mesh/features` | `packages/transport/app.py` |
| Viewport click handler — nearest feature by WORLD-space distance, using the mesh's own `localToWorld()` so it stays correct under the live auto-rotate animation (no manual transform replication needed) | `packages/frontend/src/Viewport.tsx` |
| `FeatureCard.tsx` — a small card anchored near the click, showing the tag name + its raw metadata | `packages/frontend/src/FeatureCard.tsx` |

**Honest, documented limitations** (not silently "fixed" by inventing precision the data doesn't
support): only a translation offset is applied for multi-instance projects — an instance's own
ROTATION is not applied to its tags' local points; a composite subsystem's internal sub-part
placements (e.g. `standoff_frame`'s legs) are not further corrected. Tags with no `"center"` (whole
solid/pocket bodies) simply aren't pickable yet — that's most of the catalog today, since only
hole/bore/bolt-style tags carry a position.

Tests: `tests/subsystems/test_features.py` — 5 pass (single-instance centers match exactly,
multi-instance centers get the instance's world offset applied and provably differ from the raw
local value, center-less tags excluded, `_placement` tags excluded, an instance with no
`geometry_builder` is skipped without crashing the whole listing). Live-verified on `:8001`:
`/mesh/features` returns bracket's 4 hole-bore points with real world coordinates.

## Out of scope (deferred, as planned)

Firecracker/gVisor sandbox (analysis runs trusted templated code); real PrusaSlicer sidecar (analytic
estimator kept); multi-tenant auth/RLS; optimizer beyond the 3-variant sweep (NSGA-II Pareto). Redis
pub/sub → WS `SOLVER_RESULT` push is wired as a *polling* `/analyze/status` + `/optimize/status` for
now (the documented fallback). No HTTP endpoint to explicitly SET an instance's `Transform` yet
(auto-layout covers every case exercised so far; the underlying field + `instance_world_offsets`'
explicit-transform path are already built and tested — only the HTTP surface is missing, on purpose,
since adding it properly would want its own event-sourcing fact type rather than a regenesis hack).
