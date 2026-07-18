# Grounded Text-to-CAD — Build Program Tracker

Master index for turning the `prd-27-8.14` vision into a real product, engineered with Claude
(dev-time) and powered by Claude (runtime).

**Last updated:** 2026-07-15
**Current phase:** Phases 0–4 implemented & green (**576 backend tests pass on Windows** — `python -m
pytest tests -q`, 27 skip on dependency-gated markers, more in the Linux container) and the **full
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

**2026-07-15 — per-session isolation + optional AUTH_TOKEN gate:** closed the "one global session
shared by every client + zero auth" gap from the 07-14 audit. `SessionManager`
(`packages/transport/app.py`) now maps an opaque per-browser cookie to its own isolated
`SessionState`; an operator-configured `AUTH_TOKEN` (unset by default — zero-friction local dev is
unchanged) gates who can mint a NEW one, and every REST route except `GET /healthz` sits behind it
(`/ws` does its own cookie/header check, since browser WebSockets can't set custom headers). An
adversarial review before landing this caught and fixed six real gaps in the first pass: FastAPI's
implicit `/docs`/`/redoc`/`/openapi.json` leaked the full private schema even with `AUTH_TOKEN` set
(now gated too); the session cap evicted the OLDEST live session on overflow — an unauthenticated
DoS letting anyone wipe another user's design (now refuses new sessions with 503 instead); each
session's first file was literally `"file_1"`, colliding across tenants in Postgres mode (`file_id`
now carries a random suffix); and — the big one — **`PgEventStore` had no project-scoping column at
all**, so every file from every session shared one global event stream the moment `DATABASE_URL` was
set, silently voiding session isolation in the actual `docker-compose` deployment (fixed with a
`project_id`-scoped composite key — **breaking schema change for any pre-existing dev Postgres
volume**, no migration tooling yet, `docker compose down -v` to reset). Two findings were documented
rather than fixed (matches the cut-list's no-scale-infra stance): a WS session minted via
`Authorization` header — a script/test path the real frontend never takes — isn't reliably reusable
across separate connections; and `SessionManager`'s in-memory dict doesn't extend across multiple
worker processes without a shared store (Redis is already provisioned for Dramatiq; not wired up for
this).

**2026-07-15 — cut-feature boundary-condition fragmentation, closed:** a hole/pocket/slot that
intersects (without severing) the validated cantilever methodology's clamp (min-X) or load (max-X)
face used to pass the existing single-solid check and silently hand the solver a FRAGMENT of the
true boundary face — `solvers/mesh.py::_axis_extreme_surface` picks exactly ONE face by bounding-box
centre, so a cut that splits that face into two ~60mm² pieces (confirmed live against a 200mm² face)
would have the clamp/load applied to only ONE fragment, an under-constrained/under-loaded model
producing a confident, wrong FS with zero error. New `packages/truth_plane/solvers/bc_check.py`
(pure build123d, no gmsh — unit-testable on Windows) compares the clamp/load face area before vs
after cutting and returns the honest "unknown" `analyze_geometry` already gives the severed-island
case whenever a cut compromises either face. Verified end-to-end with a real bracket + an
edge-intersecting cut feature that the block happens BEFORE `evaluate_fs`/gmsh is ever imported.

**2026-07-15 — Dramatiq job status now crosses the process boundary:** a queued `/analyze`/`/optimize`
job's progress used to live only in an in-process `publish` callback — which could never reach the
web process from the separate Dramatiq worker process in the actual compose deployment, so a crashed
job left every poller waiting forever with zero signal anything went wrong (confirmed: the previous
`jobs.configure(store=state.verdict_store, publish=None)` calls inside the web process's `/analyze`/
`/optimize` handlers were dead code — the actor body only ever runs in the worker process, which
configures its OWN globals once at startup). Replaced with a durable, `project_id`-keyed
`JobStatusStore` (in-mem for local dev, a new Postgres `job_status` table in compose — same split as
the verdict store): the web process now writes `"queued"` right after enqueueing, the worker writes
`"running"`/`"done"`/`"failed"` (+ the exception message on failure) as it actually executes, and
`/analyze/status`/`/optimize/status` surface `job_status`/`job_message` alongside the existing
`current`/`result` fields. The frontend's polling loops now stop immediately on a `"failed"` status
instead of silently burning their full 90s/240s budget before giving up unexplained
(`AnalysisBar`'s error line now shows the actual failure message, not just "analysis failed").
`max_retries=0` is unchanged — a deterministic geometry/FEA failure would just fail identically again;
this fix is about surfacing failure honestly, not retrying it.

**2026-07-15 — event-log snapshot cache:** `BaseEventLog.fold()` used to refold the ENTIRE history
from genesis on every single read — every mesh render, telemetry poll, param fetch, WS mutation
response — and `apply_delta` deep-copies the whole ledger per `PARAMETER_MUTATION` it folds, so a
session's total cost was effectively quadratic in reads×mutations-so-far. `fold()` now caches the
last-folded ledger + how many events produced it: a read with no new events returns the cache
directly (zero replay work); a read with k new events folds only those k on top of the cache
(`replay()` gained an `initial` param for this). `SqlEventStore`/`PgEventStore` also override the new
`_events_since(count)` hook with a real `WHERE seq >= ?` query, so a cache-hit read on the Postgres
path doesn't even re-fetch the full history from the DB — the concrete fix for "the Postgres path
where `_all_events()` also re-reads every row". Measured directly: 500 mutations × 5 reads each (2,500
`fold()` calls, roughly what one real editing session produces) — 43.4s uncached vs 0.034s cached, a
~1,277× speedup that widens further with session length since the uncached cost is quadratic and the
cached cost is linear. Cache correctness verified against a from-scratch cold replay after many
incremental appends, and against a different `reconcile` callable correctly invalidating it.

**2026-07-15 — `packages/catalog/`: a local, Supabase-ready reference-data store (not to be confused
with the 32-part *subsystem* catalog below):** every material property, DFM threshold, fastener
clearance dimension, and cost rate used to be a hand-typed Python constant with zero external
grounding (`bom.py`'s own comment: "Values are representative"). New package, two storage tiers
behind one interface — `SeedFileStore` (checked-in JSON, the zero-infra default every test still
runs against) and `PgCatalogStore` (a new `catalog` Postgres schema in the SAME database the
ledger's event/verdict/job-status stores already use — not a new service; pointing `DATABASE_URL` at
a real hosted Supabase instance later needs zero code change, since Supabase is vanilla Postgres).
Schema: a bespoke typed `materials` table (stable shape, matches `Material` 1:1) plus a generic
`reference_datasets`/`reference_entries` pair for everything else, so a brand-new category of
reference data (thread pitches, surface finishes, more processes) is new rows, never a schema
migration — the concrete answer to "scalable to expand exponentially". Seed data is a **faithful
migration** of today's hardcoded values (no new "real" numbers yet — external sourcing is explicitly
deferred): 5 materials, the M3–M8 clearance-hole table, the 0.8/1.2mm wall-thickness floors, and the
$2/hr machine rate. Wired live via `bom.py::set_material_db()` / `cost.py::set_machine_rate()` (pure
reassignment, no I/O in either package — `packages/ledger`'s "no I/O" rule stays intact) called from
`bootstrap.py::apply_to_live_app()` in **both** `create_app()` and `packages/truth_plane/worker.py`
(the separate Dramatiq process where cost/thermal grounding actually executes — easy to miss, and
originally missed in the first draft of this plan). `python -m packages.catalog.seed` /
`make seed-catalog` pushes the JSON into Postgres, upserting + pruning so checked-in JSON always
wins on reseed.

**2026-07-15 — the DFM prompt fragment now reads from the catalog live:** `manufacturing.py`'s
clearance-hole table used to be a string frozen at module-import time (before `apply_to_live_app()`
ever runs). `DisciplineSpec.knowledge_fragment` can now be a zero-arg callable, resolved at
PROMPT-BUILD time (`packages/disciplines/__init__.py::_fragment_text`) instead of import time —
`manufacturing.py`'s fragment is one now, sourcing the clearance-hole quick-ref and the *advisory*
recommended wall thickness from `packages.catalog`. The *hard* min-wall floor quoted in the same
sentence deliberately still reads `packages.ledger.apply.MIN_WALL_MM` directly, never the catalog's
own (informational-only) copy of that number — so the prompt can never claim an enforced floor that
doesn't match what the export gate actually checks. Verified live: overriding the catalog's
clearance-hole dataset changes what `active_discipline_fragments()` (the real prompt-consumption
path) returns, while the min-wall sentence stays pinned regardless of what the catalog says.

**2026-07-15 — `structures.py`/`thermal.py` wired to the catalog too:** both fragments hand-typed
material names/temperatures frozen at import time — `structures.py`'s "suggest a stiffer material
(AL6061/STEEL)" and `thermal.py`'s "PLA ~55°C < PETG ~70°C < ABS ~90°C < AL6061 ~200°C < STEEL
~400°C" ladder. Unlike the DFM fragment, neither needed a NEW catalog dataset: `bom.py::MATERIAL_DB`
is already catalog-sourced (`_apply_materials()` above), so both fragments just became callables
that read it live — `structures.py` names whichever materials are actually stiffest
(`youngs_mod_mpa`), `thermal.py` rebuilds its ladder sorted by `service_temp_c`. The thermal gate's
"upgrade material" suggestion is now live-computed too (materials at/above the failing operating
temp, excluding the current one) rather than a fixed "PETG/ABS/AL6061" list that could recommend a
material too cold for the actual failure.

**2026-07-15 — `cost.py` wired to the catalog too, closing the last gap:** its "$22-25 / $8 / $2"
per-material price quick-ref and "PLA is cheapest thermoplastic; STEEL cheapest metal by mass"
callout were the last hand-typed numbers left in any discipline's knowledge fragment. Same fix again:
`_cost_usd()` already read `MATERIAL_DB` live via `material()`, so only the prompt TEXT was frozen —
it's a callable now, rebuilding the $/kg quick-ref and the "cheapest material" callout (by
`cost_per_kg_usd`, no more hardcoded thermoplastic/metal split) from the live dict. Every discipline
fragment (manufacturing, structures, thermal, cost) is catalog-live now.

**2026-07-15 — the stated goal's load now reaches the solver, closing the top-severity item below:**
`HeuristicStrategicProvider` only ever parsed FS/mass/hours tokens — a goal like "holds 200 N" was
silently dropped, so `/analyze`/`/optimize` always solved a hardcoded 40 N / 25 N tip load regardless
of what was asked; the reported FS was real but for the WRONG load case (and the frontend made it
worse — `App.tsx` hardcoded `analyze(40)`/`optimize(25)` as literal constants, never reading the goal
at all). Fixed at all three layers, mirroring the existing `effective_fs_floor` pattern exactly:
`strategic.py` gained a `_LOAD` regex + `StrategicProvider.extract_load_n()` (deliberately kept OUTSIDE
`RequirementSpec`/`VerificationMatrix` — a stated load is a solver INPUT, not a checkable pass/fail
target, so folding it into the matrix would show as a permanently-UNKNOWN requirement); `FileState`
gained `stated_load_n`/`effective_load_n()` (last-stated-wins, same accretion shape `merge()` already
used for FS); `/analyze`, `/optimize`, `/analyze/status` resolve `load_n` through it (explicit caller
override still wins), and `/analyze`'s response now echoes the RESOLVED load back so a status poller
asks about the exact same case instead of racing a goal that could change mid-poll. The frontend reads
that echoed value instead of hardcoding 40/25, and `RequirementsCard` surfaces `implied_load_n`.

**2026-07-15 — frontend test harness stood up from zero:** `packages/frontend` had NO test tooling at
all (no vitest/jest/testing-library in `package.json`). Added `vitest` + jsdom + React Testing Library
behind their own `vitest.config.ts` (deliberately separate from `vite.config.ts` — the vitest-only
`test` field never risks the working dev/build config). Initial coverage targets the two areas most
worth a regression net right now: `api.ts`'s request-building (pins down the load-threading fix just
above — `analyze()`/`analyzeStatus()`/`optimize()` must OMIT `load_n` by default so the backend's own
goal-resolution applies, only appending it when explicitly overridden; plus the `Authorization` header
behavior) and `RequirementsCard.tsx` (a pure presentational component, no WebGL dependency). Anything
touching the `Viewport.tsx` react-three-fiber tree is deliberately left alone for now — it needs a real
GL context this harness doesn't provide. `npm test` / `npm run build` both green.

**Still not fixed** (ranked roughly by severity): no TLS anywhere in the stack, so the session cookie
has no `Secure` flag (matches existing deployment posture — add both together when TLS termination
lands); no external-standards sourcing yet for the new catalog (deliberately deferred per this
session's own scope); `cost.py`'s knowledge fragment still hand-types its per-material price ranges —
the one discipline fragment not yet catalog-wired.

**2026-07-16 — UAV hardware catalog expansion: 111 new subsystems, all structural/mounting-only.**
`build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md`'s full curated list (14 categories — fuselage/wing/
tail structure, landing gear, propulsion mounts, payload/avionics/power bays, control-surface linkage,
antenna/comms, deployment/recovery, ground handling, CubeSat hardware, fasteners, misc airframe
hardware) is now real, registered `packages/subsystems/<name>.py` code — a copilot querying for "a fin
root fitting" or "a battery tray" finds an exact match instead of inventing geometry. Deliberately
excludes the 2 ⚠-flagged rows (`wing_rib_blank`/`stabilizer_rib_blank`) pending their own explicit
sign-off — an unrelated one-off airfoil-lofted `vertical_fin` subsystem was drafted and then removed
this same session once it became clear `naca_wing`/`winged_fuselage` were an explicit one-time
exception (a real Fusion 360 process the user asked to be replicated directly), not a general license
to keep adding airfoil-lofted surfaces without their own sign-off — the proposals doc's own "any true
airfoil-lofted surface" parked-list entry governs, and this expansion respects it.

Generated via a code generator (10 archetypes reusing the pre-existing catalog's own proven renderers
— `render_bracket`/`render_panel`/`render_lbracket`/`render_standoff`/`render_uchannel`/
`render_bulkhead_frame`, plus `longeron.py`/`square_tube.py`/`saddle_clamp.py`/`enclosure.py`'s inline
patterns), not 111 hand-authored files — mechanical templating over a shared, already-tested geometry
core is more reliable than 111 independent authoring passes at this scale. Verified for real, not
LLM-judged: every one of the 111 builds a valid single-solid positive-volume `build123d` part at its
own defaults, and every closed-form `volume()` estimate is within 5% of the real built volume — both
checked directly and now permanently regression-tested (`tests/subsystems/test_uav_hardware_catalog.py`,
447 tests: registration, invariants-at-defaults, positive volume, real-geometry validity, and
closed-form-vs-real volume accuracy, parametrized over all 111 names). One real bug caught this way:
`tie_down_ring`'s own default `flange_width_mm`/`bolt_hole_dia_mm` combo violated its own edge-distance
invariant — fixed before landing. `fea_eligible` deliberately left at its default `False` for every
new item (including the plain-Box "rail" archetype items that are shape-identical to `longeron.py`,
which IS `fea_eligible=True`) — per `base.py`'s own "opt-in per subsystem, not inferred" rule, that
call is left to whoever explicitly reviews a specific part for it, not inferred here from shape alone.

Known, disclosed consequence: the copilot's "part types you can design" prompt section grew from a
32-entry to a 143-entry catalog (~50 KB of text, verified live) — part of the static, cacheable prompt
prefix (no per-request timestamp/UUID in it, so this doesn't re-cost tokens every turn per
`packages/agents/CLAUDE.md`'s caching rule), but a real, disclosed base-size increase, not a hidden one.

**2026-07-17 — general (non-aerospace) hardware catalog expansion: 121 more subsystems, registry now
264.** Same idea as the 07-16 UAV batch, aimed at the sibling `build-plan/reference/
SUBSYSTEM_PROPOSALS.md` list (13 categories — fasteners/receiving hardware, brackets & mounts,
enclosures & covers, panels & plates, structural sections, spacers & standoffs, rotational &
transmission, bearings/bushings/linear, alignment/locating/jigs, sealing, handles/knobs/ergonomic,
cable/wire/plumbing, and multi-body assemblies): every surviving row is now a real, registered
`packages/subsystems/<name>.py` file, so a copilot querying for "a wing nut" or "a NEMA17 face mount"
finds an exact match instead of inventing geometry.

Same code-generator approach as the UAV batch: 14 archetypes drove the build — the 10 already proven
by the UAV expansion, plus 4 new ones this list needed (puck, stepped, flanged, wedge, plate_bore),
each prototyped directly against build123d before being wired into the generator. Not 121
hand-authored files, for the same reason as the UAV batch: mechanical templating over a shared,
already-tested geometry core beats 121 independent creative passes at this scale. Verified for real,
not LLM-judged: every one of the 121 builds a valid single-solid positive-volume `build123d` part at
its own defaults, and every closed-form `volume()` estimate is within 5% of the real built volume —
both checked directly and now permanently regression-tested
(`tests/subsystems/test_general_hardware_catalog.py`: registration, invariants-at-defaults, positive
volume, real-geometry validity, and closed-form-vs-real volume accuracy, parametrized over all 121
names). Full suite green after landing: **1523 passed, 27 skipped**.

Two real bugs caught this way, both fixed before landing: `2020_extrusion_blank`/`2040_extrusion_blank`
are not legal Python module/identifier names (a bare name can't start with a digit) — renamed to
`extrusion_2020_blank`/`extrusion_2040_blank` (file, `name=`, and the proposals-doc table all updated
to match); and the registry-size regression test's own first draft used a strict `==` on
`len(SUBSYSTEM_REGISTRY)`, which is wrong because other test files (`test_assembly_template.py`,
`test_saddle_clamp.py`) legitimately register their own throwaway subsystems into the same shared
global registry when the full suite runs together — changed to a `>=` floor check with the reasoning
recorded inline, since what actually matters is nothing got silently overwritten, not an exact count.

Deliberately excludes 4 rows pending their own explicit sign-off, same "flag it, don't force an
approximation" policy as the UAV list's ⚠ rows: `wave_washer` (sine-wave spring geometry),
`snap_ring_shim` (split-ring geometry), `worm_blank` (helical thread geometry), `grommet_blank`
(flexible-material profile) — each needs swept/compliant geometry outside this batch's archetypes,
not a scope judgment call.

Known, disclosed consequence, same shape as the UAV entry: the copilot's "part types you can design"
prompt section grows again, from 143 to a 264-entry catalog — still the static, cacheable prompt
prefix, so this is a real, disclosed base-size increase and not a hidden one or a per-turn cost.

**2026-07-18 — two proper fuselage subsystems, replacing "just reuse lofted_spindle" as the default
fuselage answer.** User pushback this session, verbatim: a fuselage built from `lofted_spindle` "looks
stupid" — and the underlying complaint was structural, not aesthetic tuning: real fuselage design
starts from REQUIREMENTS (airliner-tube vs. blended-wing-body are built completely differently), and
`lofted_spindle`/`ogive_fuselage` force every body through ONE global analytic taper curve over pure
circle/ellipse cross-sections, which can't represent either real approach. Two new subsystems, chosen
via `AskUserQuestion` ("both, tube-style first, reuse the plumbing for BWB right after"):

- **`tube_fuselage`** — an airliner-style body: independently-named nose-taper / constant-diameter
  parallel-mid-body / tail-taper regions (not one shared curve) plus a flattened-belly KEEL line across
  the parallel run, all lofted through in a single smooth `bd.loft()` pass. New shared plumbing:
  `_cross_sections.py` (`keeled_ellipse_face`/`station_face`, build123d-dependent) and
  `_loft_profiles.ellipse_segment_kept_area` (pure-python closed-form counterpart).
- **`bwb_fuselage`** — a blended-wing-body: ONE continuous full-span loft (not a separate body + wing)
  through real NACA 4-digit airfoil cross-sections (`_naca_airfoil.py`, the same profile family
  `naca_wing` uses) — thick/"bulgy" at the centerline, smoothly tapering (chord AND thickness_pct
  together) to thin wing-like tips. Deliberately reuses `_loft_profiles.ease_at`/`taper_stations` (the
  SAME cosine-ease `lofted_spindle` uses for its own body) rather than `naca_wing`'s plain-linear taper
  or `ogive_fuselage`'s power-law curve — a BWB's whole premise is a smooth, seamless body/wing blend,
  the exact shape `ease_at` produces and the exact shape a conventional wing's sharp taper (`naca_wing`)
  or a fuselage nose's immediate flare (`ogive_fuselage`) both deliberately avoid.

Four real bugs caught, all verified directly against build123d before landing (not just reasoned
about):
- A hollow (shell) build of `tube_fuselage` — same outer-loft-minus-inner-loft technique
  `lofted_spindle` uses — was numerically UNSTABLE on this keeled, large-diameter, thin-wall shape:
  a station-count sweep produced a broken 2-solid result at 12 stations, `is_valid=False` at 16, 40%+
  error at 20. A SOLID body at the identical proportions was stable across the entire 6-16 sweep
  (~20.5-20.7% error, one valid solid, every time) — so `tube_fuselage` builds solid, same "shell it
  later" deferral `ogive_fuselage`/`winged_fuselage` already established, and empirically the right
  call here too, not just a consistency choice.
- The first keel-cut implementation flattened the TOP instead of the bottom — `build123d`'s
  `Rotation(0, 90, 0)` maps local +X to global **-Z**, not +Z as assumed; verified directly
  (`Rotation(0,90,0) * Pos(10,0,0) * Vertex(0,0,0)` lands at global `(0,0,-10)`). Fixed in
  `_cross_sections.keeled_ellipse_face`, with the sign now documented inline.
- The closed-form ellipse-segment area formula (`ellipse_segment_kept_area`) had kept/removed area
  swapped — traced by comparing its output directly against a real build123d face's own `.area` at a
  known cut, not caught by the loft-volume tolerance test alone (that test only checks the END-TO-END
  number, so a two-sided formula bug could partially cancel there).
- `ogive_fuselage.py`'s own module docstring claimed a stale ~5.4% volume-approximation figure from
  earlier in that file's development; re-measured directly this session at ~13% (still comfortably
  inside its actual enforced `< 0.15` test bound — the shipped behavior was never wrong, only the
  comment).

Verified for real, not LLM-judged, exactly like every other subsystem in this catalog:
`tube_fuselage` swept station counts 6-20, solid-only, stable at ~13-21% closed-form-vs-real error
(disclosed, not hidden — an inherent property of a keeled loft at these proportions, flat across the
whole sweep, not a coarse-sampling artifact); `bwb_fuselage` swept the same range and stayed under
~1% the entire time (an airfoil section is thin relative to its chord, leaving little room for the
smooth loft to bulge past its sampled stations) — both now regression-tested
(`tests/subsystems/test_tube_fuselage.py`, `tests/subsystems/test_bwb_fuselage.py`), including the
same reversed-taper pointwise check `naca_wing.py`'s own fix established this session (`bwb_fuselage`
checks it on BOTH chord and thickness_pct independently, since neither is caught by any aggregate
integral). `naca_wing.py`'s private `_sweep_dihedral_offset` was promoted to a shared
`_naca_airfoil.sweep_dihedral_offset` once `bwb_fuselage` needed the identical math — one fewer
duplicate copy, not a new capability. Full suite green throughout: 1537 passed after `tube_fuselage`
landed, **1550 passed, 27 skipped** with `bwb_fuselage` added.

**2026-07-19 — two live bugs found in `bwb_fuselage` while dogfooding it, plus a first-time-ever
"/mesh hangs the whole server" bug, plus airframe-first pacing.** Three separate findings from live
UAV-building sessions, all fixed:

1. **`/mesh` tessellation was hardcoded at a 0.2mm absolute deflection tolerance** — fine for the
   catalog's original small printable parts (tens of mm), pathological for the fuselage-class
   subsystems added 2026-07-18 (up to 3000mm). Reproduced directly: a ~1800mm `bwb_fuselage` alone
   took **235 seconds** to tessellate (590,500 triangles), blocking the ENTIRE backend process for
   that whole time — not just the one request, since a sync FastAPI route's threadpool worker held
   the lock the whole time. Fixed: `/mesh` now scales the tolerance to 0.1% of the part's own largest
   bounding-box dimension, clamped `[0.1mm, 2.0mm]`. Same 1800mm part now tessellates in ~9 seconds.
2. **`bwb_fuselage`'s chord/thickness taper was inverted** — thick at both outer span edges, pinched
   thin at the true centerline, exactly backwards. Root cause: `_chord_at`/`_thickness_pct_at` fed
   `dist_from_center` (which only ranges `[0, span_mm/2]`) into `ease_at` as if it still ran the FULL
   `[0, span_mm]` one-directional axis `tube_fuselage.py`'s nose-to-tail schedule uses — a units
   mismatch, not a build123d issue. Caught only by evaluating the schedule AT SPECIFIC positions and
   checking by NAME which value landed where — total volume and overall bounding box are both
   symmetric/position-agnostic and provably cannot catch this, the same blind spot `naca_wing.py`'s
   own reversed-taper fix already found this session. Fixed (single-taper-zone formula, `x_a=0.0`
   disabling `ease_at`'s "start zone" branch entirely) and given a permanent two-layer regression test
   (`test_chord_and_thickness_schedule_peaks_at_centerline` checking the pure schedule, plus
   `test_real_build_is_widest_at_center_not_at_the_edges` slicing the REAL built solid at two span
   positions and comparing cross-sectional area).
3. **`render_assembly()`'s per-instance exception handling was completely silent** — `except
   Exception: continue`, no logging anywhere — so if any instance in a multi-part assembly failed to
   build, the WHOLE assembly's mesh came back empty with zero trace, indistinguishable from "nothing
   to render." Added `logging.exception`/`logging.warning` calls (kept the same defensive
   per-instance isolation — one broken part still shouldn't blank the whole scene — just made it
   diagnosable instead of invisible).

**Airframe-first pacing** (live user feedback, explicitly likened to Claude Code's own plan-mode →
execution split): a vague whole-vehicle request ("build me a flying wing UAV") used to make the
copilot propose the wing/fuselage AND every systems/mounting part (electronics bay, spars, motor
mounts) in the same turn. This is Stage 3 (`AIRCRAFT_DESIGN_PROCESS.md`) one level down — the SAME
"explore cheaply, checkpoint, then commit to detail" logic §7 already established between whole
program stages, applied WITHIN Stage 3 instead: propose the airframe (outer mold line) alone first,
pause, then move to systems once that shape exists. Mechanism: a new opt-in `Subsystem.
is_airframe_defining` field (same stance as `fea_eligible` — never inferred from shape/size), tagged
on the 7 real wing/fuselage-class subsystems (`naca_wing`, `bwb_fuselage`, `tube_fuselage`,
`ogive_fuselage`, `winged_fuselage`, `lofted_spindle`, `lofted_hull`). `prompt_builder.py`'s new
`_airframe_pacing_section` reads this off `ledger.instances` directly each turn — no new stored mode,
nothing to desync if the airframe part is later deleted. Deliberately NOT a hard blocking gate (this
project's 2026-07-04 policy: every proposal auto-applies immediately, Undo is the safety net) — this
only paces what gets PROPOSED in one turn; a fully-specified request ("wing plus an electronics bay
and two spars, now") is honored directly, and the rule never applies to an already-narrow request.
Regression-tested in `tests/backend/test_agents.py` (pacing text present/absent by ledger state) and
`tests/subsystems/test_subsystems.py` (the exact tagged-subsystem set, pinned by name).

**2026-07-19 — parameter sliders: live-drag geometry + can't-reach-invalid clamps.** Two live
complaints ("changes do not reflect instantly on 3D", "I dragged the slider... make it instant" and
the earlier `blend_taper_mm` CONFLICT). Both fixed, staying inside the three-tier "single clock"
doctrine (the kernel must never sit in the 30Hz loop):
- **Live-drag regen** (`packages/frontend/src/Viewport.tsx`): replaced the release-only 200ms debounce
  with **single-flight, latest-wins** — at most one `/mesh` regen in flight at a time, and the instant
  it returns, if the slider advanced while it ran, it immediately regens for the newest state. Wedge
  parts (50-170ms full rebuild+tessellate, measured) refresh ~10x/s so the viewport tracks the drag
  live; big lofted bodies refresh as fast as the kernel sustains and NEVER pile up (the pile-up was the
  earlier whole-server freeze). The slider + HUD stay on the instant Tier-0 WS path; the kernel runs
  one-at-a-time, opportunistically — not in the 30Hz loop.
- **Invariant-valid slider clamps** (`packages/subsystems/valid_ranges.py`, new): each slider is
  hard-clamped to the PHYSICALLY-VALID sub-range where the subsystem's own cross-field invariants hold,
  given every other param's current value — NOT the advisory recommended bounds (those stay a soft
  envelope the copilot may exceed, per parameter.py; the ⚠ cue still flags outside-recommended
  separately). You can no longer drag `blend_taper_mm` past `span_mm/2`. Pure closed-form (~1.5ms for
  an 11-param subsystem, sub-µs per invariant eval) so it rides on every Tier-0 WS mutation response
  (`protocol.py` `CascadeUpdate.valid_ranges`) — all sliders' clamps stay live as other params change,
  no kernel call, no extra round trip. `/mesh` tessellation tolerance also retuned (0.1%→0.2% of the
  part's largest dim, cap 2→4mm) after measuring OCCT's per-shape speed cliff — same triangle count,
  3-7x faster on the fuselage-scale bodies.
- **An adversarial-review workflow (5 finder agents + per-finding skeptic verification) caught a
  critical regression in the first draft of the live-drag loop before it shipped**: the effect cleanup
  aborted the in-flight fetch on EVERY slider tick (not just unmount), killing the catch-up re-pump, so
  the viewport froze on a stale mesh the moment you stopped dragging. Confirmed with the exact failing
  interleaving and fixed (no per-tick abort; a liveness flag guards only true unmount). The same review
  found a boundary bug in the valid-range sampler (returned the search bound without invariant-testing
  it) — also fixed, both regression-tested (`tests/subsystems/test_valid_ranges.py`,
  `packages/frontend/src/sliderRange.test.ts`, `tests/backend/test_app.py`). Two PRE-EXISTING
  HARD_LOCK/unlock UI-desync bugs it also surfaced are documented but deliberately left for a separate
  focused pass.

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
    ENGINEERING_GRAPH_ARCHITECTURE.md  ← 2026-07-19 DIRECTION doc: prompt-to-CAD → problem-to-part; typed graph (component/interface/connection/COUPLING), 2-tier checking, reductive fidelity ladder, containment-as-connection, never-fuse, certification-as-a-pass. Marks BUILT/DESIGNED/OPEN honestly.
    ENGINEERING_GRAPH_PLAN.md          ← 2026-07-19 phased implementation plan for the above. P1 (interfaces+connections, the substrate) specced to schema level; P2–P7 sketched. Build P1 next, then re-plan from what it teaches.
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
