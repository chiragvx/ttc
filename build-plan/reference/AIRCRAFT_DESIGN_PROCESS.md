# The Aircraft Design Process, Prompt to Build — and How Each Step Gets Tested

**Status:** design doc (no code, no stubs) — 2026-07-16. Companion to
[`DOMAIN_TAXONOMY.md`](DOMAIN_TAXONOMY.md), which maps disciplines × subsystems and fidelity tiers.
This doc answers a narrower question: **given a prompt, what are the actual STEPS the AI takes to go
from intent to a built, exportable design — and for each step, what does "this step is correct" mean,
tested in a way that can't be gamed by a lucky final number?**

North star: an A340/A350-class transport is the long-run target, not a day-1 deliverable. Every stage
below is written at that scale on purpose, then annotated with what's actually buildable today under
this repo's cut-list (`CLAUDE.md`) vs. what needs its own explicit go + human sign-off later. Nothing
here authorizes building a cut-list discipline — see `DOMAIN_TAXONOMY.md` §9.

---

## 0. The complaint this doc answers

*"I know it'll pass the tests. It may pass on code but when I see it, it's crap."*

That's a real failure mode, and it has a specific cause: **output-matching tests** ("does the final
number equal what I expected") only prove the pipeline produced *a* number — not that every step along
the way did its own job honestly. A wrong sizing equation, a fabricated aero coefficient, and a solver
that silently didn't converge can all cancel out into a final FS that happens to look plausible. The
fix isn't more end-to-end tests — it's testing **each step's own transformation**, against a real
reference wherever one exists, so a step can't be wrong and get away with it just because a later step
didn't happen to expose it.

This is not a new idea for this repo — it's the same shape as `tests/solvers/test_fs_cantilever.py`
(the real CalculiX solver must reproduce a closed-form beam-theory answer within tolerance) applied to
every stage of the pipeline, not just the structures solver.

---

## 1. The eight stages, prompt to build

Each stage has: **Input** → **AI does** (and is forbidden from doing) → **Output artifact** →
**Step-test** (the falsifiable, reference-grounded check for THIS stage alone).

### Stage 0 — Mission capture
- **Input:** a natural-language goal ("a bracket that holds 200 N at FS 2" today; "a 300-seat, 7,000 nm
  twin-aisle, EIS 2035" at the north-star scale).
- **AI does:** the Strategic layer (`StrategicAgent` today) decomposes intent into a
  `VerificationMatrix` of **targets** — range, payload, MTOW ceiling, FS floor, cost ceiling. It never
  states whether a target is *met* — that's Stage 6's job, against real metrics.
- **Forbidden:** inventing a requirement the user didn't state or imply; silently dropping one they did
  (the exact bug just fixed in `strategic.py` — a stated load used to vanish entirely).
- **Output:** a typed requirements matrix (extends today's `RequirementSpec`/`VerificationMatrix`).
- **Step-test:** feed a corpus of labeled prompts (synthetic + real transcripts) through extraction and
  check *recall and precision of the requirement set itself* against the labels — not against a final
  design. "Did we correctly hear FS≥2 AND the 200 N load" is answerable without ever building geometry.

### Stage 1 — Configuration selection
- **Input:** the requirements matrix.
- **AI does:** pick a subsystem/configuration template from the registry (tube-and-wing vs. BWB vs.
  flying-wing UAV) — today's `switch_subsystem`, generalized.
- **Forbidden:** inventing a configuration with no precedent for the stated mission class.
- **Output:** a selected subsystem type + its `ParamSpec` defaults.
- **Step-test:** does the chosen configuration fall inside the envelope real aircraft with similar
  requirements actually use? Checked against **real reference data**, not opinion — e.g. a 7,000 nm
  twin-aisle mapping to tube-and-wing is checkable against a small table of real certified aircraft
  (EASA/FAA TCDS: MTOW, wingspan, configuration) rather than one hand-picked example.

### Stage 2 — Conceptual sizing (closed-form — never the LLM)
- **Input:** requirements + configuration.
- **AI does:** nothing numeric. A **deterministic sizing method** (wing loading, T/W or P/W, MTOW
  estimate) computes the first-cut geometry parameters — this is exactly what NASA's **Aviary**
  (GASP/FLOPS-derived equations) already does as running code (see the 2026-07-15 data-sources memo).
  Inversion #1 holds: the LLM proposes *which* target to size toward, never the sized number itself.
- **Forbidden:** an LLM-guessed MTOW/wing-area standing in for a computed one, even "just as a
  placeholder" — placeholders that look like real numbers are exactly the failure mode Inversion #1
  exists to prevent.
- **Output:** first-cut geometry parameters (span, chord, taper, fuselage length/diameter, MTOW
  estimate).
- **Step-test — the ground-truth regression:** feed a **real** certified aircraft's actual stated
  requirements (from an EASA TCDS) into the sizing method and check it reproduces that aircraft's real
  MTOW/wing area within an engineering tolerance (conceptual-design methods are validated exactly this
  way in every textbook — this is not a made-up bar). This is the single highest-leverage test in the
  whole pipeline: it's real, it's numeric, and it fails loudly if the sizing math is wrong, regardless
  of what happens downstream.

### Stage 3 — Geometry generation (build123d, generator-baked tags)
- **Input:** sized parameters.
- **AI does:** emits a `ParameterDelta` (strict tool-use, the LLM's only write path); the deterministic
  Jinja2 + build123d templater renders real B-rep geometry — same "generator-baked tags for persistent
  identity" pattern the existing 32-part catalog already uses (`naca_wing`, `winged_fuselage`, etc. are
  proof this kernel can do it, not a hypothetical).
- **Forbidden:** free Python from the LLM; any code path that could construct a HARD_LOCK-violating or
  non-watertight part.
- **Output:** a real solid (or assembly), tagged, exportable.
- **Step-test — invariant checks, not vibes:** does the *built* geometry's measured properties (wetted
  area, aspect ratio, MAC, wing area) match what Stage 2 specified, within numerical tolerance? Is it
  watertight, single-solid, BRepCheck-clean? These are the same class of test this repo already writes
  (e.g. the wall-thickness assertion on `winged_fuselage`) — "did the generator correctly implement the
  math," never "does it look like a plane" as a subjective call.

### Stage 4 — Discipline analysis (real solvers, never the LLM)
- **Input:** the built, tagged geometry.
- **AI does:** for each active discipline, the truth plane calls the **real tool** (AVL/XFOIL for aero,
  Gmsh+CalculiX for structures, QPROP for propulsion, …) against the actual generated solid. A missing
  or non-converged solver result is `"unknown"` and blocks export — already enforced today for
  structures/thermal, generalizes per `DOMAIN_TAXONOMY.md`'s fidelity tiers (L0 estimate-only, L1
  grounds decisions, L2 authoritative).
- **Forbidden:** an LLM stating a CL, CD, FS, or flutter speed; a PASS on an unconverged/un-meshed
  result; blending an L0 estimate into an export-eligible verdict.
- **Output:** typed, per-discipline `Verdict`s written to `derived.*`.
- **Step-test — per-discipline golden oracle:** identical in spirit to
  `tests/solvers/test_fs_cantilever.py` (the real CalculiX FS must reproduce closed-form beam theory).
  Every new discipline needs its own oracle before its first real verdict is trusted: an AVL-computed
  lift-curve slope / induced drag for a known planform checked against a published polar or the NASA
  **Common Research Model**'s own wind-tunnel CL/CD data; a QPROP thrust curve checked against a
  published prop/motor test. No discipline earns an export-eligible verdict without this test existing
  first — that's the actual gate, not a suggestion.

### Stage 5 — Cross-discipline convergence (bounded sweep / MDO)
- **Input:** the per-discipline verdicts, which may conflict (more wing area fixes stall speed, adds
  structural weight, costs range).
- **AI does:** a bounded sweep across the coupled parameters — today's sanctioned 3-variant sweep;
  later, per `DOMAIN_TAXONOMY.md`, a real bounded MDO loop (never NSGA-II — that's cut-list).
- **Forbidden:** an LLM picking "the answer" by judgment where the sweep itself should decide it.
- **Output:** the lightest (or otherwise best-scoring) variant that clears every active gate.
- **Step-test — convergence, not output-matching:** does the sweep actually converge (successive
  iterations change by less than a stated tolerance) and does it correctly select the
  requirement-satisfying, best-scoring variant — a monotonicity/convergence property test. This catches
  a sweep that "returns something" without ever actually converging, which an output-matching test on
  the final value alone would miss entirely.

### Stage 6 — Requirements traceability & compliance judgment
- **Input:** the now-real, solver-grounded metrics.
- **AI does:** `VerificationMatrix.evaluate()` judges each stated target against its real metric —
  exactly today's mechanism for FS/mass/print-time, generalized to every discipline.
- **Forbidden:** marking a requirement satisfied against a metric that's `unknown` or stale.
- **Output:** a per-requirement SATISFIED / VIOLATED / UNKNOWN readout.
- **Step-test — coverage, not correctness-by-assertion:** does *every* stated requirement resolve to a
  real, checkable metric — none silently left permanently unknown with no discipline ever assigned to
  it? A missing allocation is itself a defect, independent of whether the numbers look right.

### Stage 7 — Human gate + export
- **Input:** the fully evaluated design.
- **AI does:** exactly today's mechanism — any geometry-class change is `AI_PROPOSED`; an explicit
  engineer accept + sign-off is required before physical export; any discipline `"unknown"` or failing
  blocks unconditionally (Inversion #1's last line of defense).
- **Output:** an export-eligible (or honestly blocked) design.
- **Step-test — adversarial, not affirmative:** try to construct a case that sneaks an unknown or
  failing discipline past the gate (stale verdict, mismatched geometry signature, a discipline that was
  never wired to the gate at all). A gate is tested by trying to defeat it, not by confirming it lets a
  good design through.

---

## 2. The testing philosophy, stated plainly

> **Test that each step correctly implements the transformation it owns — a specific input→output
> relationship, an invariant, or a regression against a REAL reference case — never "does the whole
> thing look right to me."**

A step-test is automatable and can't be gamed by luck, because it isolates one stage's own math/logic
from everything downstream. Concretely, every step-test in this doc is one of exactly three shapes:

1. **Regression against a real reference** (Stages 0, 1, 2, 4) — a known prompt, a known certified
   aircraft, a known wind-tunnel polar. The 2026-07-15 data-sources survey exists specifically to feed
   these: NASA's Common Research Model (importable geometry + real wind-tunnel/CFD data), EASA TCDS
   (certified dimensions/weights per real aircraft), and Aviary (sizing equations already validated
   against GASP/FLOPS) are the oracles Stages 2 and 4 need.
2. **Invariant / consistency check** (Stages 3, 5, 6) — the output must satisfy a property implied by
   its own inputs (built wing area matches specified wing area; the sweep actually converged; every
   requirement resolves to a real metric). No external reference needed — the step is checked against
   itself.
3. **Adversarial / negative check** (Stage 7, and Stage 0's completeness) — try to break it, don't just
   confirm the happy path. A gate is proven by the attempts that fail to get past it.

**What this does NOT give you:** step-based testing guarantees *groundedness* — no fabricated number,
no silent regression, no discipline quietly skipped. It does **not** guarantee the overall design is
elegant, buildable, or the right call for the mission — that is still, in every real aerospace program
and in this one, a human chief-engineer judgment sitting on top of a pile of trustworthy inputs. The
point of everything above is to make sure that when a human looks at the final design and says "this
is crap," they're reacting to an actual bad design decision — not to a fabricated number that never
should have reached them.

---

## 3. What's buildable now vs. gated

Every stage above already has a **working, if narrow, instance in this codebase**: Stage 0
(`StrategicAgent`), Stage 2 (closed-form sizing exists for the flat-plate bracket), Stage 3
(build123d generators, 32 parts), Stage 4 (the validated Gmsh+CalculiX cantilever pipeline), Stage 6
(`VerificationMatrix.evaluate`), Stage 7 (the export gate). None of that needs new authorization to
extend *within* wedge-legal disciplines (thermal L1, manufacturing, cost — see
`DOMAIN_TAXONOMY.md` §3). Extending Stage 4 to aerodynamics/propulsion/aeroelasticity is cut-list —
each needs its own explicit go + human sign-off before any solver code lands, same rule as today.

## 4. Open questions for a human aerospace engineer (not self-certified here)

- Which specific reference aircraft (and how many) belong in Stage 2's sizing-regression suite, and
  what tolerance band is actually defensible for a conceptual-design method (this doc assumed
  "textbook-typical," which is not the same as an engineer's sign-off on a specific tolerance).
- Which wind-tunnel/CFD case(s) from the CRM dataset are the right oracle(s) for a first AVL/XFOIL
  validation, and what agreement counts as "passing" at L1 fidelity.
- Whether Stage 1's "configuration precedent" check needs a broader reference set than TCDS data alone
  (e.g. failed/unusual configurations) to avoid over-fitting to "what already got certified."

---

## 5. Red-team pass (2026-07-16) — adversarial validation of the step-tests above

Section 1's step-tests were themselves adversarially attacked before being trusted: five independent
critics, each assigned a different failure class (tolerance gaming, error compounding across stages,
oracle overfitting/extrapolation, gate-defeat, and defects invisible to numeric invariants), tried to
construct a concrete scenario where every listed step-test passes and the output is still bad. All
five found a genuine, non-redundant gap — this was not a rubber stamp, and one finding turned out to
be a **live bug in this repo, not a hypothetical**, which has already been fixed (see below). The
surviving gaps, to be closed before Section 1 is treated as sufficient:

- **Stage 2's regression checks only 2 of its own output scalars.** The ground-truth regression
  reproduces MTOW and wing area against the reference aircraft, but never aspect ratio, wing loading,
  span, or the weight-and-CG budget the identical sizing call also emits. A first-order weight buildup
  is only weakly coupled to AR, so a sizing bug (e.g. a wrong airframe-class lookup) can leave MTOW/S
  inside a normal tolerance while span is 2–3× wrong — and Stage 3's invariant check only diffs built
  geometry against Stage 2's *own* (possibly wrong) spec, so self-consistency passes too, hiding the
  error completely. **Fix:** extend the regression to independently check AR, wing loading, span, and
  CG-%MAC/tail-volume-coefficient against the same reference aircraft, each with its own tolerance;
  when running a regression case, have Stage 3 diff against the reference aircraft's true value, not
  just Stage 2's own output.

- **Stability & Control has no golden oracle or export-gate wiring.** `DOMAIN_TAXONOMY.md` lists
  Aerodynamics (§3.2) and Stability & Control (§3.3, static margin = CG vs. neutral point) as separate
  discipline cells; Stage 4's golden-oracle requirement as written only demands an aero (CL/CD) oracle,
  so the same AVL run's neutral-point output ships unvalidated. A user prompt rarely states "must be
  longitudinally stable," so Stage 6's coverage test has nothing to trace it to, and
  `packages/ledger/gates.py::evaluate_export_gates` has no `extra_findings` callback for it — a design
  could ship with a computed-but-never-checked negative static margin (CG aft of neutral point — a
  longitudinally unstable airframe). **Fix:** require an S&C golden oracle before trusting any AVL
  stability derivative; wire a `static_margin` `extra_findings` callback into `evaluate_export_gates`
  (mirroring the existing thermal injection point) that blocks on missing/stale/signature-mismatched
  input; have Stage 1's config template auto-inject "positive static margin" into the
  `VerificationMatrix` for every fixed-wing config so it can't stay permanently out of scope just
  because nobody thought to ask for it.

- **The sizing method's calibration domain is never checked, so extrapolation yields a confident wrong
  number instead of `"unknown"`.** Stage 2's regression is a single-point/narrow-class replay; nothing
  asserts the requirement point being sized falls inside the sizing method's own calibration envelope
  (e.g. GASP/FLOPS are fit to general-aviation/transport aircraft, roughly 2,000–800,000+ lb MTOW).
  Sizing a 25 lb electric recon UAV — this project's own stated future direction — through the same
  equations can yield an empty-weight fraction exceeding 1.0, a real float, not `"unknown"`, so the
  missing-input rule never engages and the bad number flows straight into Stage 3. **Fix:** give the
  sizing method a domain-of-validity check (distance of MTOW/Reynolds/propulsion-class from the
  calibration corpus) that forces `"unknown"` outside it, exactly like a missing input; add a negative
  test case (a real small-UAV data point known outside GASP/FLOPS range) asserting refusal; have Stage
  1 select which calibrated coefficient set Stage 2 is allowed to use, so a plausible configuration
  can't silently route into an unvalidated regression.

- **Stage 3's aggregate invariants are exactly, not approximately, blind to reversed taper direction.**
  Confirmed against `packages/subsystems/naca_wing.py`: `_check()` validates positivity and a min-wall
  floor but never `root_chord_mm >= tip_chord_mm`, so a `ParameterDelta` can legally build a wing
  narrowest at the root and widest at the tips (a backward "paddle" planform — the wrong end holding
  the most material for where bending load is highest). Wing area, aspect ratio, and MAC are each an
  integral (or ratio of integrals) of a symmetric linear chord ramp and are *algebraically* identical
  whether root/tip values are swapped — no tightening of tolerance on those same checks could ever
  separate the two shapes, and OCCT's watertight/manifold checks don't distinguish taper direction
  either. `naca_wing` is also `fea_eligible=False`, so nothing downstream catches it. **Fix:** add a
  pointwise monotonicity/ordering assertion (e.g. `root_chord_mm >= tip_chord_mm`, or a structural
  proxy like chord × thickness³ non-increasing root-to-tip) to every taper-schedule generator, since
  aggregate integrals over a symmetric ramp can never distinguish which end holds the extremum.

- **Confirmed live and already fixed: the export gate could serve a stale, wrong-load-case verdict as
  "grounded."** `FileState.resolved_ledger()` — the one function shared by `/export/check` and the
  actual `/export/step` enforcement — called `ledger_with_derived(...)` without `material=`/`load_n=`,
  so `latest_verdict()` matched on geometry signature alone and could hand back a verdict solved at the
  lighter default load (40 N) as current even after a stated goal raised the required load (e.g. to
  200 N) with no re-analysis in between. `/analyze` already guarded against exactly this; this one
  caller was never updated. **Fixed** in `packages/transport/app.py::FileState.resolved_ledger()`
  (2026-07-16), with a regression test
  (`tests/backend/test_requirements_api.py::test_export_blocked_after_goal_raises_load_without_reanalysis`)
  that holds geometry fixed and varies only the requested load across the analyze/export boundary —
  the exact axis the original step-test description didn't separately enumerate. **Standing lesson for
  Stage 7's own step-test:** whenever a "stale verdict served as current" hole is patched in one
  caller, enumerate every other caller of the same resolver (`latest_verdict`/`ledger_with_derived`)
  and confirm each threads the same case-identity fields — that should be a checklist item, not a
  one-time patch.

None of the five restated the doc's own Section 2 honesty limit (that step-testing guarantees
groundedness, not holistic design elegance) — each identified a specific, falsifiable hole in a
specific step-test's *coverage*, which is exactly the class of gap this red-team exercise was meant to
surface before the testing design above is trusted at face value.
