# Engineering Graph — Implementation Plan

**Status: PLAN (2026-07-19).** The build sequence for the direction in
[`ENGINEERING_GRAPH_ARCHITECTURE.md`](ENGINEERING_GRAPH_ARCHITECTURE.md). Read that first; this doc does
not re-explain the *why*, it sequences the *how*.

**Sequencing principle (from the arch doc §10):** build the general primitives, but debug them one real
grounded problem at a time. Each phase is a **shippable, independently-testable increment** that either
*ratifies* a primitive or *exposes* a missing one. **Do not commit to building all of this up front** —
build Phase 1, run it against a real assembly (BWB + wings, then a non-aircraft like a gearbox), and
re-decide. The pump already showed the graph model earns its generality by exposing gaps (it exposed
coupling); keep letting real problems drive it.

## Dependency order

```
P1  Interfaces + Connections        (the substrate — everything below needs it)
     ├─ P2  Coupling primitive + a TINY relation catalog     (needs P1)
     │        └─ P4  Whole-system Solver Tab                  (needs P2)
     │        └─ P3  L0 logic tests (ratings/topology/closed-form)  (needs P1+P2)
     ├─ P6  Manufacturability outputs (assembly instructions, per-part export)  (needs P1)
     └─ (containment is just a P1 connection KIND)
P5  Decomposition + ScopeSpec + clarify loop   (mostly parallel; the planning layer)
P7  Certification pass                          (needs P4 + P5)
Cross-cutting: the reductive fidelity ladder is a workflow layered once P3/P4 exist.
```

Highest leverage + closest to buildable = **P1**. It's specced to schema level below; P2–P7 are sketched
at decreasing detail (deliberately — spec them when their turn comes, against what P1 actually taught).

---

## Phase 1 — Interfaces + Connections (THE SUBSTRATE) 🟡

**Goal:** replace *positional, LLM-hand-computed* placement with *declared mate points + typed
connection objects*, so (a) the LLM wires "A.root ↔ B.mount" instead of computing transforms it keeps
getting wrong, (b) placement is *derived* by satisfying connections, and (c) the self-check reads an
*exact* connection graph instead of a bounding-box heuristic. This is the EKG ontology's
interface/connection made typed + computable.

### 1.1 New types (schema)
- **`InterfaceSpec`** on the `Subsystem` model (`packages/subsystems/base.py`), alongside `params`:
  ```
  InterfaceSpec:
    name: str                 # "root", "spar_mount", "nose_face", "chamber" (unique per subsystem)
    kind: Literal["mount", "containment", "port"]   # port = a future coupling attach point (P2)
    frame: a LOCAL pose on the part = (origin: xyz, normal: xyz [, up: xyz])
           # derived from geometry where possible (reuse TaggedPart tags, which already carry positions),
           # else declared. Orientation matters — mating aligns normals, not just points.
  ```
  Subsystems declare their interfaces the same way they declare params/build/invariants. Start with the
  airframe set (`wing_panel.root`, `bwb_fuselage.tip_left/tip_right`, `tube_fuselage.spar_mount`,
  `motor_mount.face`) — the parts the placement pain actually showed up on.
- **`Connection`** — a new first-class ledger object (sibling of `Instance`), in the instance graph:
  ```
  Connection:
    id: str
    a: { instance_id, interface }      # e.g. wing_left.root
    b: { instance_id, interface }      # e.g. bwb_fuselage.tip_left
    kind: Literal["mate", "bolted", "slip_fit", "containment"]
    offset: optional small pose        # gap / clearance, default identity
  ```
- **`ConnectionOp`** (sibling of `InstanceOp`, `deltas.py`) so the LLM proposes connections via strict
  tool-use: `add_connection` / `remove_connection`. The LLM wires interfaces; it never emits transforms
  for connected parts.

### 1.2 Placement solve (the core new logic)
- A pure function `resolve_placements(ledger) -> {instance_id: Transform}` (new, in
  `packages/subsystems/`, no build123d at module scope — mirrors `assembly.py`):
  - Pick a **datum** (a containment part, or a declared/first root) at world origin.
  - Propagate over the connection graph (BFS/DFS): for each connection, place the not-yet-placed
    instance so its interface `frame` coincides with its partner's world `frame` (align origin, align
    normal → a rotation + translation; `offset` applies the gap). This is the mate math — the same
    class as the sweep/dihedral rotation work, so **frame orientation is the #1 correctness risk**;
    unit-test each mate against a known-good result.
  - An instance with NO connection falls back to the existing +Y auto-layout (unchanged).
- `render_assembly` and the blueprint/self-check consume these derived transforms. Positional
  `Transform` on an instance still works (backward-compatible) and acts as an override when no
  connection governs it.

### 1.3 Wire it through
- **Self-check** (`validate.py`): connectivity becomes EXACT — two parts are connected iff a
  `Connection` joins them, not iff their bboxes overlap. (Keep the bbox check as a secondary "declared a
  connection but the geometry doesn't actually meet" cross-check — that catches a *mis-declared* mate,
  which is itself a useful finding.)
- **Prompt** (`prompt_builder.py`): the BWB/wing and vertical-stab recipes change from "place at
  x=±H, y=H·tan(sweep)…" to "connect `wing_left.root` ↔ `bwb_fuselage.tip_left`" — deleting the
  hand-computed-transform recipes that have been the churn source.
- **Migration:** connections and positional transforms coexist (transform = override / no-connection
  fallback). No big-bang rewrite.

### 1.4 What P1 de-risks / proves
- Does typed mating actually replace positional placement and kill the LLM-transform class of bugs?
- Does the frame/orientation math hold for real mates (the swept wing root onto a swept body tip)?
- Does exact connectivity make the self-check trustworthy enough to drive auto-correct?

### 1.5 Tests
Mate math per interface pair (known-good transform); `resolve_placements` on BWB+wings equals the
hand-verified ~<1mm seam; self-check flags a *declared* connection whose geometry doesn't meet;
no-connection parts still auto-layout; round-trip a `ConnectionOp` through the ledger.

### 1.6 Risks 🔴
- **Orientation math** (aligning normals + up-vectors) is the same footgun as this session's rotation
  bugs — verify every mate against real build123d, never on paper.
- **Over/under-constrained graphs** (conflicting connections, or a floppy part with one mate) — v1:
  first-satisfied-wins + report the conflict as a finding; don't attempt a full constraint solver.
- **Interface frames from geometry:** deriving a clean origin+normal from a `TaggedPart` tag may need
  each airframe subsystem to *declare* its interfaces explicitly at first (a per-part authoring cost,
  like param names were).

---

## Phase 2 — Coupling primitive + a tiny relation catalog 🟡 (needs P1)
**Goal:** loads become *derived* through registered relations, not stated scalars. **Scope v1
deliberately tiny:** 3–4 trivial, unarguable relations (`force_from_mass_accel`,
`force_from_pressure_area`, `bending_from_distributed_load`, `landing_load_from_drop`) — enough to make
the pump-style propagation real end-to-end, nothing hard. `Coupling` object (source.port → relation →
target.port, over P1 interfaces); `CouplingOp` for the LLM to wire (never author). Extends the existing
load-threading (`effective_load_n`) — the target's solver load becomes a graph output. **Unwired
relation → "unknown" → blocks.** De-risks: does changing part A re-derive part B's load and re-flag it
(the "bring a problem, it solves it" behaviour)? Explicit non-goal: fatigue/thermal relations (human
wall — P4+ and a real methodology).

## Phase 3 — L0 logic tests 🟡 (needs P1+P2)
**Goal:** cheap build-time catches. Rating checks (`quantity ≤ interface.rating` — wire gauge/current,
etc.), closed-form gross-error checks (4g spar an order of magnitude too thin), topology-legality (two
consumers illegally sharing one exclusive source → de-link). Needs a **curated ratings/rules catalog**
(the real cost — same shape as the material DB). Runs in the build loop alongside the geometric
self-check; NOT a solver.

## Phase 4 — Whole-system Solver Tab 🟡 (needs P2; 🟢 solvers exist)
**Goal:** a deliberate, whole-system solve that WALKS the coupling graph (crank against casing-derived
pressure), never per-part-in-isolation, never per-edit. Reuses the FEA path (Gmsh+CalculiX, validated
cantilever FS, `fea_eligible`); the new work is (a) feeding derived (coupled) loads in, (b) adding
methodologies for the modes that matter — **fatigue first, because it's the mode that actually bit the
pump** (S-N, stress-concentration, cycle counting; golden values from handbook/PE, never the AI's run).
`"unknown"` blocks anything without a grounded method.

## Phase 5 — Decomposition + ScopeSpec + clarify loop 🟡 (parallel)
**Goal:** "make an X" → AI proposes a part manifest mapped to catalog parts + per-param limits +
operating conditions, **with out-of-scope flagged**, agreed with the user before building. Extends the
existing `RequirementSpec`/`VerificationMatrix`. This is the "define scope, don't throw parts at a wall"
planning layer; can proceed alongside P1–P4.

## Phase 6 — Manufacturability outputs 🟡 (needs P1)
**Goal:** the connection graph generates **assembly instructions** ("print these 6, bolt A.face↔B.mount
here"); each part exports its own STEP/STL (🟢 already separate/never-fused); a make-manifest (mill vs
print, materials, import-substitution candidates). The non-designer payoff.

## Phase 7 — Certification pass 🟡 (needs P4 + P5)
**Goal:** an isolated pass that tests the solved design against the ScopeSpec + external
industry/regulatory *quantitative* criteria and emits a compliance report. **Pre-screening / gap
analysis ONLY — never issues certification** ("meets clause X, unverified on Y"). The trust artifact
that flips make-vs-buy.

---

## Cross-cutting
- **Reductive fidelity ladder:** once P3 (L0) and P4 (solver) exist, formalize a design's *fidelity
  level* (rough-in → refine): L0 checks bite on the rough model, the Solver Tab on the refined one.
  Reframes the build loop from "generate perfect parts" to "chip the stone."
- **Containment-as-connection:** no separate work — it's the `kind: "containment"` connection from P1,
  which dissolves body-vs-frame without an archetype flag.

## Explicit non-goals (now)
Aero/CFD, propulsion/range, flutter, kinematics stay cut-list. The hard relations (fatigue beyond a
first methodology, thermal loops, cyclic feedback couplings) are human-wall — wire "unknown", don't
fake them. No full constraint solver in P1 (first-satisfied + report conflicts).

## Recommendation
**Build Phase 1 next.** It's the substrate every other phase stands on, it directly kills the
placement-churn we lived through this session, it makes the self-check exact, and it's buildable on what
exists (instances, tags, Transforms, the self-check, the blueprint). Then run it against BWB+wings *and*
one non-aircraft assembly, check it against the arch doc's §10 open questions, and re-plan P2 from what
P1 actually taught.
