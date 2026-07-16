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

**2026-07-16 addition (§§6–8):** sections 1–5 below define the pipeline mechanics (the 8 stages) and
how each step gets tested. §§6–8 answer the higher-level question of how this maps onto how real
aircraft programs actually work — how design really starts, the low-fidelity/approval-gate/high-fidelity
phase structure, and a precise definition of "fidelity" grounded in real sources rather than assumed.
Read §§6–8 first if you want the big picture before the stage-by-stage mechanics.

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

- **Stage 3's aggregate invariants are exactly, not approximately, blind to reversed taper direction —
  confirmed, and fixed (2026-07-16).** `packages/subsystems/naca_wing.py::_check()` validated
  positivity and a min-wall floor but never `root_chord_mm >= tip_chord_mm`, so a `ParameterDelta`
  could legally build a wing narrowest at the root and widest at the tips (a backward "paddle"
  planform — the wrong end holding the most material for where bending load is highest). Wing area,
  aspect ratio, and MAC are each an integral (or ratio of integrals) of a symmetric linear chord ramp
  and are *algebraically* identical whether root/tip values are swapped — no tightening of tolerance
  on those same checks could ever separate the two shapes, and OCCT's watertight/manifold checks don't
  distinguish taper direction either; `naca_wing` is also `fea_eligible=False`, so nothing downstream
  caught it either. **Fixed:** `_check()` now rejects `root_chord_mm < tip_chord_mm` outright (equal —
  the declared "straight wing" case — still passes); `winged_fuselage.py`'s own `_check()` delegates to
  `NACA_WING.invariants(p)` verbatim, so the fix covers it for free, confirmed by a regression test
  there too rather than assumed. Covered by `tests/subsystems/test_naca_wing.py::
  test_reversed_taper_root_narrower_than_tip_is_rejected` /
  `test_equal_root_and_tip_chord_is_not_a_reversed_taper` and
  `tests/subsystems/test_winged_fuselage.py::test_invariants_catch_child_violations`'s extended case.
  The general lesson stands for every other taper-schedule generator this catalog grows later: a
  pointwise monotonicity/ordering assertion is needed alongside any aggregate integral check, since the
  latter can never distinguish which end holds the extremum.

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

---

## 6. How real aircraft design actually starts (grounded in real practice, not assumed)

Researched against NASA's Systems Engineering Handbook, a peer-reviewed requirements-methodology paper,
and NASA's own published system-design-process description — cited inline, confidence noted.
**Methodology note:** the automated synthesis step of this research run itself failed (returned a
literal placeholder instead of a report — a reminder that "the tool ran without error" and "the tool's
output is trustworthy" are different claims, the same lesson §5 exists to teach). What follows was
reconstructed directly from the underlying verified claims and primary-source extractions, not from
that broken synthesis — each claim below is marked confirmed (adversarially checked, 2-of-3 votes) or
sourced-but-not-independently-reverified (extracted from a primary source, not put through the
adversarial vote in this pass).

**Design doesn't start with geometry — it starts with a small set of specific, named artifacts.**
NASA's earliest formal technical review, the Mission Concept Review (MCR), requires as entrance
criteria a concept of operations, an analysis of alternative concepts, and a preliminary risk
assessment with defined Measures of Effectiveness/Measures of Performance — *confirmed*, and directly
answers "what's the first deliverable": not a sketch, a decision framework. Requirements flow-down (the
V-model, applied to a real program) is not ad hoc either — a peer-reviewed methodology paper
(*Chinese Journal of Aeronautics*, Vol. 30, 2017) derives quantitative aircraft requirements using
formal systems-engineering techniques (objective tree, analytic hierarchy process, quality function
deployment) rather than engineering intuition alone — *confirmed*.

**Real system design is explicitly non-linear, by NASA's own account, not just in retrospect.** NASA's
SE Handbook §4.0 characterizes its four system design processes (Stakeholder Expectations Definition →
Technical Requirements Definition → Logical Decomposition → Design Solution Definition) as
"interdependent, highly iterative and recursive" — *sourced, primary*. The documented recursive pattern:
build a straw-man architecture/ConOps/derived-requirements, validate it against stakeholder
expectations, and **repeat the cycle whenever gaps appear**. "Design Solution Definition" — the step
that actually produces a design — works by generating *multiple* alternative solutions and evaluating
them via formal trade studies (effectiveness, cost, schedule, risk, with assumptions/results archived)
before selecting a preferred one — the real-world anchor for this doc's own Stage 1 (configuration
selection) and Stage 5 (convergence sweep). One specific down-select mechanism proposed in the
literature — a morphological matrix plus TOPSIS ranking — was checked and **refuted (0-3 votes)** as
*the* established practice; don't present a single ranking algorithm as how real programs down-select
configurations. It's a reviewed, documented baseline decision, not a leaderboard.

**Honesty check on "AI-first":** NASA's Aviary team documents that real historical conceptual-design
practice was human-in-the-loop and discipline-siloed — engine/aero/performance experts worked largely
independently and a *human* manually drove the iteration loop to reconcile them, and even today's
legacy tools (FLOPS, GASP) still require experts to hand-build data tables — *sourced, primary*
(Aviary's own published documentation). A fully AI-orchestrated multi-fidelity loop is not yet an
established industry practice to point to as precedent; it's the emerging direction tools like Aviary
are only beginning to formalize. Say that plainly rather than implying this project is automating
something that already runs itself elsewhere.

---

## 7. The low-fidelity → approval gate → high-fidelity phase structure

**Why gate at all — the economic case, not just caution.** NASA's SE Handbook reproduces the classic
INCOSE life-cycle cost-commitment curve: the *bulk* of a program's total cost gets locked in early —
while only a small fraction of the actual budget has been *spent* by then (the source's own figure
gives illustrative percentages; treat the shape of the finding — cost committed far outpaces cost
spent, early — as the load-bearing point, not any single number, and not the specific milestone
anchor either, since the extracted quote was partial: it can't confirm PDR specifically, versus SRR or
end-of-Phase-A, as the textbook-exact inflection point). This is the formal reason to explore cheaply
and get a
decision *before* committing to expensive validation: that's where the leverage over total cost
actually lives, not merely where the risk of wasted effort lives.

### Phase 1 — Low-Fidelity Exploration (Stages 0–3, run at L0/L1)

Mission capture, configuration selection, conceptual sizing, and geometry generation all run on
closed-form/empirical methods — never the AI, per Inversion #1 — and the system is *meant* to explore
broadly: many candidate configurations, many sized variants, cheaply, matching NASA's own Phase A
(Concept Studies) posture. This maps directly onto an existing project rule (`DOMAIN_TAXONOMY.md` §2):
L0 estimates never ground an export on their own and are always labeled — the same posture NASA's own
PDR success criteria take, which explicitly *allow open requirement items as long as a resolution plan
exists* (**confirmed**) — a gate about demonstrated maturity-with-a-plan, not 100% closure.

Real precedent for what the AI should actually be doing here, not hand-wavy judgment: Bayesian
optimization with a Kriging surrogate and an Expected-Improvement infill criterion, deciding which
candidate points earn a more expensive follow-up evaluation — **confirmed**, and validated in the
literature on a real aircraft MDO testbed (an OpenAeroStruct wing aero-structural optimization
minimizing fuel burn via the Breguet range equation, subject to lift-weight and structural-safety-factor
constraints — the same OpenAeroStruct already surfaced in the 2026-07-15 data-sources research).

### The Gate — modeled on NASA's PDR, not CDR

What gets reviewed mirrors a real PDR, not a rubber stamp and not a demand for perfection: is the
configuration and sizing mature enough, with a credible plan for anything still open, to justify
spending real solver time on it. What the gate formally *approves*, mirroring NASA's SRR→PDR sequence:
(a) **requirements freeze** — the `VerificationMatrix` stops silently accreting (NASA: "a successful SRR
freezes program/project requirements," **confirmed**); (b) **configuration/geometry baselines** — the
sized candidate becomes the "design-to" baseline, authorizing the move from exploration toward final
design (NASA: PDR "approves the design-to baseline" and "authorizes the project to proceed... toward
final design," **confirmed**). This is this project's real equivalent of "configuration freeze" —
deliberately not "down-select," per §6's finding above.

Who actually has sign-off authority is itself a real, load-bearing distinction, not a UX nicety: NASA
separates the Standing Review Board (assesses, advises) from the Decision Authority (decides) —
**confirmed**, and a real Decision Authority can knowingly accept a design *despite* specific open SRB
findings (documented risk acceptance with rationale). **This project has the two INPUTS that
separation needs, but not yet the separation itself** — checked directly against the code, not assumed:
a discipline's `evaluate_gate`/`GateFinding` is a real assessment input, and the human engineer's
explicit sign-off (`ReviewState.ENGINEER_REVIEWED`) is a real, distinct decision input, but
`packages/ledger/gates.py::evaluate_export_gates` folds both into one flat `reasons` list with a single
AND-gate (`EXPORT_ELIGIBLE` iff `not reasons`) — the `/signoff` endpoint is an unconditional state flip
with no reference to any `GateFinding` at all, and there is no waiver/risk-acceptance path anywhere in
the ledger letting a human proceed past one named, non-`unknown` discipline finding while others still
hold. Unlike real SRB/DA practice, `ENGINEER_REVIEWED` cannot selectively override anything — that's a
deliberate consequence of Inversion #1 ("never a fabricated green light"), not an oversight, but it
means this project does *not* yet have NASA's actual authority split, only its two raw ingredients. A
true split would need an explicit waiver mechanism (e.g. a `waived_reasons` field `gates.py` excludes
from the block) — a real, open design decision, not something to assume already exists.

### Phase 2 — High-Fidelity Validation (Stages 4–7, escalating to L1/L2)

Stage 4 now runs real, expensive solvers against the *one* approved baseline — not a sweep across many
candidates. Stage 5's convergence sweep still runs, but narrowly: bounded refinement around the
approved candidate, not configuration-level exploration — matching a real industrial precedent,
Bombardier Aviation's own documented multi-level MDO framework, whose stated philosophy is to
"progressively narrow the design space while increasing analysis fidelity" moving from Conceptual MDO
to Preliminary MDO (**confirmed**). (A separate, more specific claim — that Bombardier has deployed
Bayesian optimization, SEGO/SEGOMOE, in production — was checked and **not supported**; cite the
fidelity-narrowing *philosophy* as real-industry precedent, not the specific optimizer claim.) **Precedent
scope, stated plainly:** Bombardier's narrowing was executed by a human MDO engineering team over a
multi-month program, not by an AI autonomously deciding to escalate one candidate's fidelity within a
single session — it precedents the *shape* of the transition (broad→narrow, low-fi→hi-fi), not that
automating the decision itself is proven safe or established practice; see §8's Aviary discussion for
the same distinction. Stage 6
and 7 now judge against the high-fidelity, authoritative numbers, matching CDR's own framing: margins
and risk-acceptability of the *detailed* design, with interfaces mature enough to authorize the
equivalent of fabrication (**confirmed**) — this project's real export.

### Gates are not one-way — build the return path in, don't assume it away

A KDP failure can send a program *back* to fix deficiencies, not just terminate it (**confirmed**) —
this project's architecture should let a failing/unknown Stage-4 verdict kick the design back to
Stage 2/3 for re-sizing, not just block export with no path back. This isn't theoretical: a real NASA
concurrent-engineering spacecraft study documented total mass *oscillating* across design iterations
(rising, then falling, then ticking back up), and a requirement discovered only in a *later* iteration's
trajectory analysis forced retroactive changes to propulsion hardware chosen *earlier* — genuinely
bidirectional, not a funnel (sourced from a primary NASA account, not independently re-adjudicated this
pass — treat as strong, not certain). **Concrete design implication for Stage 5's own step-test (§1):**
if Stage 4's high-fidelity result significantly contradicts what Stage 2's low-fidelity sizing assumed,
the design should loop back to Stage 2 with the new data informing a re-sized candidate — not silently
patch over the mismatch downstream. This is a genuine addition this research surfaced, not something
§1 already covered.

**This rule is underspecified as stated, and checked against the actual code, the gap is concrete, not
hypothetical.** `ReviewState` (`packages/ledger/schema.py`) is a single ledger-wide flag, not scoped to
"which decision it represents," and `packages/ledger/events.py` auto-resets it to `AI_PROPOSED` on any
geometry-class mutation (a Stage-2 re-sizing that regenerates Stage-3 geometry is exactly such a
mutation) — but no file under `packages/truth_plane` ever checks `review.state` before invoking a real
solver. Walked literally: a human approves the Gate on candidate C0 (authorizing Phase 2 spend); Stage 4
contradicts Stage 2's assumption; the design loops back to a re-sized C1; regenerating C1's geometry
silently flips `review.state` back to `AI_PROPOSED` — which correctly re-blocks *export* later, but
nothing stops Stage 4 from immediately re-running the real, expensive solver on C1 with **no human back
in the loop**, spending exactly the Phase-2-grade compute this section's own opening economic argument
says a human gate should ration — on a candidate the original Gate decision was never asked about. If
C1 contradicts again (plausible — see the oscillating-mass account above), this repeats with no stated
tolerance for "significantly," no loop-count cap, and no convergence requirement analogous to Stage 5's
own. Three concrete additions close this, none of them optional: (1) a numeric, per-metric contradiction
threshold (relative error in CL/CD, FS, MTOW, etc. between what Stage 2 assumed and Stage 4 measured) —
not "significantly" — one per discipline, as concrete as the FS floor already is; (2) a loop-count cap
on the Stage-2↔Stage-4 cycle itself with mandatory human escalation on non-convergence (e.g. N=2),
reusing Stage 5's own "successive iterations change by less than a stated tolerance" step-test rather
than leaving this as the one iterative mechanism in the pipeline with no convergence obligation; (3) a
distinct "Gate approved this baseline" flag, separate from Stage 7's export sign-off, that Stage 4 must
itself check before running a real solver on any loop-back-produced candidate — so a re-sized candidate
can never silently consume Phase-2-grade compute without a fresh, explicit human Gate decision.

---

## 8. What "fidelity" means here, precisely

Aerospace practice has **two distinct, established meanings** of "fidelity," and conflating them is a
real risk this project should avoid:

1. **NASA's own SE Handbook usage** — physical test-article maturity (breadboard = low fidelity,
   brassboard = medium, engineering unit = high fidelity) and simulation fidelity for
   verification/validation. This is adjacent to, but formally *distinct* from, Technology Readiness
   Level (TRL) — its own separately KDP-gated maturity metric via a Technology Readiness Assessment
   (**confirmed**).
2. **MDO research-literature usage** — the tier of *analysis/modeling method* used to compute a number:
   empirical/historical-regression ↔ linear/potential-flow/beam-theory ↔ nonlinear/RANS-CFD/detailed
   FEA. A literature review formally classifies this as a *structured, multi-dimensional* axis
   (application domain, surrogate type if any, the nature of the fidelity difference, the fusion
   method) — not a single scalar (**confirmed**).

**This doc and `DOMAIN_TAXONOMY.md` use meaning (2) exclusively.** Don't reach for NASA-SE-Handbook-style
TRL/hardware-maturity language when talking about this project's L0/L1/L2 — they answer different
questions ("how mature is this physical thing" vs. "how trustworthy is this number").

A real, concrete instance of meaning (2) that matches this project's own tiers almost exactly: a
published MDO study of high-aspect-ratio wing design defines low-fidelity as an Equivalent Beam Model
plus a Panel Method for aero, and high-fidelity as the *same* beam model plus RANS CFD (**confirmed**)
— structures stays L1 while aero alone escalates to L2, precisely how `DOMAIN_TAXONOMY.md` already
scopes fidelity *per discipline*, not per-aircraft. The field's canonical technique for formally
*combining* fidelity levels (rather than replacing a cheap model outright) is Kennedy & O'Hagan
autoregressive co-kriging — the high-fidelity response modeled as a scaled version of the low-fidelity
response plus a discrepancy/bias term (**confirmed**) — worth knowing exists even though this project
isn't required to implement it yet. The primary documented motivation for bothering with multiple
fidelity tiers at all is computational time savings, reported as high as 90% in some surveyed studies
— but explicitly "highly problem-dependent" (**confirmed**); treat that as a plausible order of
magnitude, never a number to promise.

**NASA's own Aviary tool is the clearest real-world instance of meaning (2) done right** for its
per-discipline method choice: Aviary lets a user pick FLOPS-based vs. GASP-based methods *per
discipline* (not one global fidelity knob) and offers multiple mission-analysis fidelity tiers
(**confirmed** — these are genuine meaning-(2) analysis-fidelity-tier examples, sourced, primary,
Aviary's own README and peer-reviewed AIAA paper).

Aviary also formally splits user complexity into three access levels — Level 1 (CSV/command-line,
replicates legacy low-fidelity behavior, no external coupling: "just get a sized aircraft fast") up to
Level 3 (full Python/OpenMDAO access for custom high-fidelity subsystem coupling: "an expert wiring in a
new solver"). **This is a third, distinct axis, and it is NOT precedent for what this project actually
needs.** Level 1→3 is a *static, human-chosen* tooling/skill-access axis — a human analyst picks an
interface once, up front, based on how much manual coupling code *they* want to write; nothing in Aviary
observes one candidate design's maturity mid-run and promotes *it*. This project's Phase 1→Gate→Phase 2
structure needs the opposite: a *dynamic, per-candidate* decision about when a specific generated design
has earned promotion from cheap exploration to expensive solver time. "How much manual coupling a human
wants to write for their whole project" and "has this AI-generated candidate demonstrated enough
maturity to justify real solver spend" are different questions — Aviary supplies no mechanism for the
second one, and citing it as if it does contradicts §6's own honesty check that a fully AI-orchestrated
multi-fidelity loop is not yet an established industry practice. **The escalation trigger/decision
logic itself — what evidence a candidate must show, what fires the promotion, what the stopping rule
is — has no industry precedent to borrow from Aviary or from Bombardier's philosophy (§7). It remains
this project's own mechanism to design, test, and keep behind explicit human sign-off**, not an assumed
solved problem.

**A cautionary tale worth internalizing, not just a success story:** Aviary's own published paper
documents a real failure mode — low-accuracy (finite-difference) derivative approximations destabilized
a gradient-based optimizer's (SNOPT) convergence in a coupled run; specific constraint types (throttle,
engine-scaling, mass-defect) had unacceptable derivative error, stalling the optimizer after roughly
three major iterations (sourced, primary — not independently re-adjudicated this pass; treat the general
failure mode — finite-difference derivative error can destabilize a coupled gradient-based optimizer —
as strong, the specific iteration count and constraint list as illustrative, not verified). This
directly corroborates §1's own Stage 5 step-test concern (convergence, not just "did it return
something") with a documented real failure in the exact class of tool (OpenMDAO-based gradient
optimization) this project's own roadmap points toward — not a hypothetical risk invented for this doc.

---

## 9. Red-team pass on §§6–8 (2026-07-16) — what got corrected before this was trusted

Five independent critics attacked §§6–8 immediately after they were written, hunting specifically for:
decorative NASA analogies with no operational consequence, an underspecified "loop back" rule, overclaimed
industry precedent (category mismatch between what Aviary/Bombardier actually demonstrate and what an
AI-driven system needs), fabricated precision from partial source extraction, and internal consistency
against this project's actual code (not just the doc's own paraphrase of it). **5 of 5 found a genuine
issue** — two independently converged on the same root cause (the SRB/Decision-Authority analogy) and
were merged; the code-grounded claims were verified directly against `packages/ledger/{gates,events,
schema}.py` and `packages/transport/app.py`, not taken on faith. All four surviving corrections have
already been applied in place above, not just appended here:

- **The "Review Board vs. Decision Authority" split doesn't exist in code — only its two raw inputs
  do.** `evaluate_export_gates` folds a discipline's `GateFinding` and `ENGINEER_REVIEWED` into one flat
  `reasons` list with a single AND-gate; `/signoff` is an unconditional flip with no reference to any
  finding; there is no waiver/risk-acceptance path anywhere in the ledger, unlike real NASA practice
  where a Decision Authority can knowingly accept a design despite specific open findings. §7's Gate
  section now says this plainly instead of implying the separation was already built.
- **The Stage 4 ↔ Stage 2 loop-back had no tolerance, no cap, and no re-authorization check.** Confirmed
  against `events.py`: any geometry-class mutation auto-resets `review.state`, but nothing under
  `packages/truth_plane` checks it before invoking a solver — so a loop-back candidate could silently
  re-consume Phase-2-grade solver compute with no fresh human gate decision. §7 now specifies a numeric
  per-metric contradiction threshold, a loop-count cap with mandatory human escalation, and a distinct
  Gate-approval flag Stage 4 must check.
- **Aviary's Level 1→3 and Bombardier's CMDO→PMDO precedent the phase *shape*, not decision
  *automation*.** Both are human-executed (a session-level tooling choice; a multi-month engineering-team
  phase transition), not precedent for an AI autonomously deciding when one candidate has earned fidelity
  escalation — which directly contradicted §6's own honesty hedge until corrected. §§7–8 now say the
  escalation-trigger logic itself has no industry precedent and remains this project's own mechanism to
  design and gate behind human sign-off.
- **Inconsistent hedging on partial source extraction.** The INCOSE milestone anchor ("around and before
  PDR") and the Aviary/SNOPT iteration-count specifics were stated with more confidence than a sibling
  claim from the *same* research pass that got an explicit "not independently re-adjudicated" caveat.
  Both now carry the same qualifier — the general findings stay intact, the specific numbers don't.

Same lesson as §5, applied one level up: this pass didn't just check whether the new content was
internally coherent — it checked the internally coherent parts against the actual repository, and found
that a passage which *read* as "we verified this matches our code" had in fact never touched the code at
all. That's precisely the gap a purely textual review would have missed.
