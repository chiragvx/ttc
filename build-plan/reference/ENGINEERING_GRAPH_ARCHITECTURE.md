# Engineering Graph Architecture — from *prompt-to-CAD* to *problem-to-part*

**Status: DIRECTION doc (2026-07-19).** This captures an architecture direction worked out in a long
design conversation, not a description of what is fully built. Every section is marked:

- 🟢 **BUILT** — exists and is tested in the repo today.
- 🟡 **DESIGNED** — the shape is decided here; not yet implemented.
- 🔴 **OPEN** — a real unknown / risk / human-wall that decides whether this is viable.

The load-bearing discipline of the whole document is the same one the codebase already runs on
(`CLAUDE.md`, the three inversions): **the system is louder about what it cannot ground than about what
it can. A missing input is `"unknown"` and blocks the green light — never a fabricated one.** If any
idea below is read as "the AI now designs X," it has been read wrong.

---

## 0. Why — the strategic reframe

**Text-to-CAD as *editing* is not a value-add.** Natural language is a poor interface for precise
spatial manipulation; a 3D modeller does it faster. Getting an LLM to place a wing correctly took a
dozen rounds in testing that a modeller would do in seconds. "Chat with your CAD" is a worse mouse.

**The value is problem-in, grounded-solution-out.** The customer signal (a real factory, ground-truth,
not hypothetical): a shop building a piston water pump changed its casing diameter a few mm to gain
efficiency; the higher pressure cracked its (under-spec, low-grade aluminium) crankshaft. The proper
fix — a coupled redesign — was available from a domestic design partner in 3–4 weeks incl. prototypes.
Instead they phoned a Guangzhou shop, took a *similar* crankshaft, thinned the shaft to fit and swapped
material — fast, admittedly "not perfect," shipped to hit the contract. Import cost ~10% more with
duties; **time was the deciding factor.**

The lessons that set the whole architecture:

1. **The competitor is not a modeller — it's the "copy a similar part and hack the dimensions" shop.**
   Fast, and ungrounded. Our wedge is to give that speed *with the trust the slow partner would
   provide.*
2. **The problem was a *system* effect, not a part.** Casing → pressure → crankshaft load → crack. You
   only catch it if you model the coupling. A part-in-isolation view never sees it.
3. **The trust that flips make-vs-buy IS the grounding.** For a shop to make a crank in-house instead of
   importing a proven one, it must trust the part won't fail. That trust is the real-solver / FEA /
   fatigue / tolerance work — it is the value, not the plumbing.
4. **Honesty is the selling point, not a limitation.** A tool that says "meets clause X, *unverified* on
   clause Y" is more trustworthy — hence more valuable — than one that stamps "certified."

Strategic north star (🔴 aspirational): an *architecture-first* platform that scales to anything — toy,
UAV, airliner — as the AI riding on it improves. The primitives do not change with domain; the parts
catalog and the solver fidelity do. Think **LLVM**: build the intermediate representation + the grounded
evaluation once; front-ends (the AI) and back-ends (fabrication) improve independently on top. The trap
to avoid is the mirror image: a "designs-anything" architecture with no real problem pulling on it, so
no primitive is ever tested. **General primitives, debugged one real grounded problem at a time.** The
pump is not a vertical to narrow into — it is the forcing function that keeps the general architecture
honest. (It already earned its keep: it *revealed* that coupling/resources is a missing primitive — see
§2.)

### 0.1 Honest bounds on the value

- 🔴 **Design may not always be the bottleneck.** Sometimes the blocker downstream is tooling, QA
  capacity, material sourcing, or first-run risk — none of which a design tool removes. The useful zone
  is: *the shop already has the capability, the part is well-understood enough to ground trustworthily,
  and the only real barrier is a fast + cheap + trustworthy specify-and-validate step.* Real, but a
  subset. Prove design-friction is what's actually blocking before assuming it.
- 🔴 **Prototyping time can't be compressed.** The 3–4 weeks *includes cut-metal-and-test.* The tool
  compresses *design* time to ~a day; it does not remove physical prototyping. Sell "design in a day
  then still prototype," not "instant."
- 🔴 **The failure mode that actually bit them was fatigue, not static overload.** Cracks under higher
  cyclic pressure = fatigue (S-N curves, stress-concentration at the crank fillet, cycle counting), a
  different physics from a static factor-of-safety check. A tool that grounds *static* strength while
  the real enemy is *fatigue* hands a confident green light that still cracks — the exact
  fabricated-green-light failure, aimed at the exact thing that broke. **The gating question is not "can
  we generate a crank" but "can we ground the failure mode that matters."** Where we can't yet, the
  answer must be `"unknown"`, not a static pass in disguise.

---

## 1. The core model: a typed engineering graph

**Adopt the ontology, reject the serialization.** A colleague's "Engineering Knowledge Graph (EKG)"
spec proposes four primitives — **Component, Interface, Connection, Resource** — as a
describe-the-machine format from which CAD/BOM/docs are generated. The *ontology is solid* and we adopt
it as our conceptual model. But EKG is **descriptive, not computable**: it says "pressure flows through
this connection" and stops. It never models the *causal, quantitative* relationship (`crank_load =
f(pressure, geometry)`) — precisely the thing that would have told the factory their crank would crack.
It also deliberately punts geometry, parameters, and validation to "engines later" — which are *our
product*, and it authors free YAML, which loosens the typed-tool-use discipline (Inversion #1).

So: **take EKG's four concepts, make each one typed + computable + grounded, wired by the LLM via strict
tool-use — never free-authored.** Mapping onto the codebase:

| EKG concept | Our realization | Status |
|---|---|---|
| **Component** | an `Instance` of a registered `Subsystem` with typed params (`ParameterDelta`/`InstanceOp`, `extra="forbid"`) | 🟢 BUILT (`packages/subsystems`, `packages/ledger`) |
| **Interface** | declared mate points on a part (an inlet, a mounting face, a spar slot) | 🟡 DESIGNED — today we have `TaggedPart` semantic tags (`wing.panel`, `hole[2].bore`) which are *proto-interfaces*, and *positional* Transforms, but no typed mate points |
| **Connection** | a typed object joining two interfaces (a bolt joint, a slip fit, a bus) | 🟡 DESIGNED — today parts connect by hand-computed position, not by an explicit connection object |
| **Resource / Coupling** | a typed edge carrying a physical quantity with a *computable, grounded relationship* (see §2) | 🟡 DESIGNED — the key missing primitive |

Everything downstream in this doc — the low-fidelity logic tests, the whole-system solve, the
manufacturability outputs, the compliance report — is *impossible without this typing.* You cannot check
`current ≤ wire_rating` unless the interface has a type and a rating. **That is the real verdict on
EKG: the model earns its place because everything else needs it.**

---

## 2. The Coupling primitive 🟡 DESIGNED

A **coupling** is what makes a change in one part propagate to a load on another. It is the primitive the
pump case revealed we lack.

**Shape.** A directed, typed edge over the instance graph:

```
Coupling:
  source:   { instance, interface, quantity }   # casing.chamber emits "pressure" [Pa]
  relation: <a registered relation id>           # "force_from_pressure_area"
  target:   { instance, interface }              # crank.pin receives a force [N] boundary condition
```

**It generalizes the load-threading we already have.** 🟢 Today, a solver's load is a *stated scalar*
(`effective_load_n`, the strategic agent parsing "holds 200 N"). The coupling makes that load a *derived
value* flowing from another part's state: the crank's load is no longer "200 N because you said so" —
it's `pressure × piston_area`, where `pressure` comes from the casing's geometry and duty. Same
plumbing, one level more general.

**The one non-negotiable rule — the LLM wires relations, it never authors the physics.** Exactly as it
picks a `wing_panel` and sets params, it picks `force_from_pressure_area` and connects source→target. It
does **not** write `force = pressure × area` as free math — that is Inversion #1, and an LLM that invents
physics is the Guangzhou hack with a false-confidence sticker. Relations are a **registered,
deterministic, versioned, tested catalog** (`pressure_from_displacement`, `force_from_pressure_area`,
`torque_from_force_radius`, `bending_from_distributed_load`, `landing_load_from_drop`, …) — the same
"catalog the LLM wires but never authors" pattern that already governs subsystems and the geometry
templater. **A coupling whose relation is not in the catalog → the target's load is `"unknown"` → blocks
any grounded claim.** Honest by construction.

**Propagation.** Change a source part's params → recompute the quantity → run the relation → update the
target's boundary condition → the target is re-checkable. Change the casing diameter → chamber pressure
recomputes → crank pin force recomputes → the crank's check flags the crack. This propagation *is* the
"bring a problem, it solves it" behaviour, made concrete.

**Honest bounds:**
- 🔴 The **relation catalog is where fidelity is earned, one relation at a time.** `force = p·A` is
  trivial; *fatigue* is a human-wall (handbook / PE methodology, like the FS golden values — never the
  AI's run). The primitive is general and buildable now; the hard relations are not, and `"unknown"`
  covers the gap honestly.
- 🔴 **v1 is a DAG.** Feedback couplings (thermal loops, etc.) are a later, harder problem.
- 🟡 Sources are often **operating conditions** (duty: rpm, displacement, g-load), not geometry outputs —
  so the coupling graph roots in the *stated problem* (§4 Phase 2), flows through geometry-dependent
  relations, and lands as loads on parts.

---

## 3. Two-tier checking — build-time logic vs. a deliberate Solver Tab

**Solvers do NOT run after every edit.** 🟢 This aligns with the existing three-tier "single clock"
doctrine (interactive / kernel / truth). Checking a part per-edit in isolation gives an *incorrect*
assessment — the crank looks fine alone; its failure lives in the coupling. Two distinct tiers:

### 3.1 Build-time = cheap logic tests (L0) 🟡 DESIGNED
Rating/compatibility and topology-legality checks over the *typed* graph — microseconds, no solver:
- **Rating checks:** a connection carrying 20 A into a 24 AWG wire rated for less → instant reject
  ("use 18 AWG"). `quantity ≤ interface.rating`.
- **Closed-form gross-error checks:** a spar under a 4 g wing load whose `bending_from_load` says it's
  an order of magnitude too thin → caught immediately; no FEA needed to know it's wrong.
- **Topology-legality:** two turbojets fanned into one inlet → illegal (messy airflow / critical) →
  de-link to isolate. Some resources can't fan-in/out the way a generic graph allows.

These are the **coupling primitive at L0 fidelity.** 🔴 They are only as smart as a **curated
ratings/rules catalog** (wire tables, "airflow needs a plenum to merge") — a knowledge-curation burden,
same shape as the material DB / DFM reference we already keep. High value; the tricky rules are a
human-wall.

### 3.2 A separate Solver Tab = deliberate, whole-system truth 🟡 DESIGNED (🟢 solvers exist)
Invoked on purpose, minutes-scale, in the truth plane. It solves the **whole system by walking the
coupling graph** — the crank against the casing-derived pressure, never in isolation — and resolves the
*marginal* cases L0 can't (FS 1.1 vs 1.8), plus fatigue/thermal where a grounded methodology exists.
🟢 The FEA path (Gmsh+CalculiX, validated cantilever FS, `fea_eligible` opt-in) exists; 🟡 making it
consume the coupling graph (whole-system, not per-part) and adding fatigue/thermal methodologies is the
work. `"unknown"` still blocks anything without a grounded method.

**Rule of thumb:** L0 catches the *gross and the dumb* while you build; the Solver Tab resolves the
*marginal and the coupled* when you ask for truth.

---

## 4. The reductive fidelity ladder — chip the stone, don't plop the print

**The design process is subtractive/refining, not generate-perfect-first-shot.** Start with a rough,
complete-but-crude whole (blocky fuselage, flat wings, placeholder mounts) and refine toward polish,
each pass adding fidelity. This is the opposite of what caused every churn cycle in testing (trying to
nail each part perfectly on creation). 🟡 DESIGNED as the explicit build workflow; it reframes the loop.

The fidelity ladder *is* the two-tier checking: **L0 logic tests bite on the rough stone; the Solver Tab
runs on the refined one.** 🔴 One cost: a rough model is only checkable if the L0 relations exist for it
— the ladder is gated by catalog coverage.

### End-to-end walkthrough: "Make a UAV from scratch"
Chosen deliberately because it straddles our grounded / cut-list line — the honesty shows.

- **Phase 0 — Clarify (scope).** 🟡 "UAV" could be a $50 toy or a $2M ISR drone. The system refuses to
  guess: it asks 3–5 sharp questions (mission, payload mass, span envelope, machines+materials, design
  load case) and the answers become the **ScopeSpec** = definition of done. Nothing builds first.
- **Phase 1 — Decompose (cheap), mapped to catalog, out-of-scope flagged.** 🟡 One LLM call proposes the
  system graph mapped to *real* registered parts (`tube_fuselage`, `naca_wing`, `wing_spar`,
  `bulkhead_frame`, `motor_mount`, `enclosure`, …) **and flags what it cannot ground: lift/drag/stall/
  stability (aero, cut-list), battery→range (propulsion, cut-list), flutter.** Output: "here's the
  structural airframe I can ground; here's the flight-performance list I can't — you or a specialist
  bring those." You prune, agree.
- **Phase 2 — Duty → coupling roots.** 🟡 Mission numbers become *stated* boundary conditions (500 g ×
  4 g → payload-mount load; stated wing-loading since aero is cut; stated thrust). The system grounds
  the *structure* against stated loads; it does not fabricate the aero.
- **Phase 3 — Instantiate parts + interfaces/connections.** 🟢 parts / 🟡 typed interfaces. Placement by
  *mating declared interfaces* (`wing_spar.root ↔ fuselage.spar_mount`), not the LLM computing
  transforms (the thing it kept getting wrong). 🟢 The **blueprint** renders the labelled 3-view.
- **Phase 4 — Couplings propagate loads.** 🟡 Registered relations carry payload/lift/thrust/landing
  loads to each structural part. Loads derived, not typed.
- **Phase 5 — Ground it (Solver Tab). `"unknown"` earns its keep.** 🟢 spar FS = 2.3 ✅; motor mount FS =
  1.1 ⚠️; payload mount = *lofted shape the cantilever method doesn't cover* → **FS unknown → export
  blocked for that part**; aero/stall/range → **unknown, out of scope → any "it flies" claim blocked.**
  The system never says "airworthy."
- **Phase 6 — Self-check + auto-correct.** 🟢 geometric self-check (now *exact* connectivity from the
  connection graph, not a bbox heuristic); the FS 1.1 mount triggers auto-correct → thicken → re-ground
  → 1.8 ✅; coupling propagation re-checks downstream automatically. 🟢 visual self-check behind
  `VISION_MODEL`.
- **Phase 7 — Honest partial verdict.** A buildable structural airframe (STEP for every grounded part);
  a make-manifest (mill vs. print, materials, import-substitution candidates); a RED list (payload mount
  unverified; the entire flight-performance question out of scope); one sentence: *"a grounded
  structural design, not a validated aircraft — here is the line."*

---

## 5. Containment-as-connection — dissolving body-vs-frame 🟡 DESIGNED

Two archetypes exist: **skin/OML-driven** (toy, car, aircraft — the outer surface is the design driver,
internals fit inside) and **frame/mechanism-driven** (robot arm, vending machine, gearbox — the internal
structure drives, the shell is derived or optional). Rather than detect-and-branch on an archetype flag,
**make containment just another typed connection.** A part declares a `contains` interface (an envelope
others mate *into*) or a `mounts-to` interface (a frame others hang *off*). A drone's OML part is a datum
others mate into; a robot arm's frame is a datum the shell mates around — *same machinery, no global
mode.* The decomposition step *proposes* which parts are containers vs. mounted (🔴 AI judgment → the
user confirms; hybrids like a car are multi-datum: OML *and* chassis). The "identify and work around it"
becomes: the graph carries containment as an edge type, and nothing global needs to know the archetype.

---

## 6. Manufacturability is sacred — never fuse for a non-designer 🟢 mostly BUILT

**Hard rule (the principle behind "separate parts, not one"): never merge geometry into a manifold the
user can't split.** A non-designer cannot chop a welded blob for printing or for a machine shop. So:
default to **separate, individually-exportable bodies** (🟢 `compose.py` groups without fusing;
`render_assembly` composes; each instance exports its own STEP/STL); **fuse only on explicit request**
(🟢 `fuse()` exists as the deliberate, rare exception — e.g. `winged_fuselage`).

The payoff falls out of the graph: 🟡 **the connection graph generates the assembly instructions.** A
non-designer gets "print these 6 parts, bolt A.face to B.mount here" — the gap between "here's a CAD
file" and "here's a thing I can actually make and assemble." Manufacturability (which part on which
machine, tolerances, stock, assembly order) is a **first-class output**, not an afterthought.

---

## 7. Self-checks 🟢 BUILT

- **Geometric self-check** (`packages/truth_plane/validate.py`): flags floating/disconnected parts,
  engulfed parts (info-severity — may be an intentional internal component), degenerate builds.
  Deterministic, no model. Matters *more* as complexity grows. 🟡 Becomes *exact* once it reads the
  connection graph instead of the current bounding-box heuristic.
- **Visual self-check** (`packages/agents/vision_validator.py`, gated on `VISION_MODEL`): renders the
  blueprint, a vision model judges shape/proportion/orientation against intent. Dark by default (the
  runtime delta-emitter is text-only). Never fabricates a pass from a garbled reply (`None` =
  inconclusive → the geometric check stands).
- **Auto-correct loop** (capped): a failing check feeds findings back to the copilot, which fixes and
  re-checks. Visible as cards.

---

## 8. Certification / validation as an isolated pass 🟡 DESIGNED (🟢 VerificationMatrix exists)

A distinct, deliberate pass that takes the *solved* output, tests it against the user's spec **and**
known industry/regulatory quantitative criteria, and produces a **compliance report.** This is the trust
artifact that flips make-vs-buy — the shop trusts an in-house crank that ships with one. Mechanically
it's the existing `VerificationMatrix` (🟢 `packages/ledger/requirements.py`) extended with
external-standard references, run as its own pass, producing a report.

🔴 **The honesty line, non-negotiable:** the tool does compliance **pre-screening / gap analysis against
a standard's quantitative criteria** — it *cannot issue certification* (FAA/EASA cert is a legal, human
process). The report says "meets clause X, *unverified* on clause Y"; it never stamps "certified." This
is `"unknown blocks the green light"` applied to compliance. Sold honestly, that is *more* compelling to
a serious customer, not less — a tool that claims to certify is one they cannot trust.

---

## 9. How this sits on the existing architecture

Nothing here fights the codebase; it is *on the grain* of it:

- **The three inversions hold unchanged.** The LLM still emits only strict typed objects (now also
  `Interface`/`Connection`/`Coupling` wiring, never free physics); deterministic catalogs render
  geometry and evaluate relations; real solvers produce every truth number; a missing input is
  `"unknown"` and blocks export.
- **The three-tier clock holds.** Interactive plane = the 30 Hz HUD; build-time L0 logic tests sit
  alongside it (closed-form, no kernel). Kernel regen = geometry on slider-release. Truth plane = the
  deliberate Solver Tab, whole-system, never on the hot path.
- **The cut-list holds.** Aero/CFD, propulsion/range, flutter, kinematics remain out of scope. The graph
  can *describe* a turbojet's topology and build its *structural* parts; it cannot design a working jet —
  and says so.
- **Reuses existing patterns:** registered-catalog-the-LLM-wires (subsystems → relations), load-threading
  (stated scalar → derived coupling), `TaggedPart` tags (→ typed interfaces), compose-not-fuse
  (→ manufacturability), VerificationMatrix (→ compliance pass), the self-check + blueprint built this
  session.

---

## 10. What decides whether this is real (🔴 the open questions)

1. **Can we ground the failure mode that matters** (fatigue, not just static)? If not, `"unknown"` — but
   a tool that can only ground the easy mode has thin value on the hard problems.
2. **Is design-and-validation friction actually the bottleneck** for the make-vs-buy decision, or is it
   tooling/QA/risk downstream that a design tool can't touch?
3. **Can the relation catalog and the L0 ratings/rules catalog be curated fast enough** to cover real
   problems? The primitives are general; coverage is earned relation-by-relation.
4. **Can the in-house path be made low-friction enough to beat "click buy"** — near as easy, more
   economical, *and* trusted enough to bet a production run on?
5. **Does the graph model survive contact with the next real problem** (a gearbox, a fixture, a
   load-bearing bracket)? Each should either ratify a primitive or expose a missing one — the way the
   pump exposed coupling. If it stops exposing gaps, the primitives are probably right.

The thing that makes this *not* vaporware is the same thing that makes it useful: at every phase it is
louder about what it cannot ground than what it can. That is what turns "here's a part" from a
hack-with-confidence into something a shop will actually build from.
