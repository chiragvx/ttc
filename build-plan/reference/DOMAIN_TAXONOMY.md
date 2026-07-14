# Domain Taxonomy — From the Wedge to a Reconnaissance UAV

**Status:** design doc (no code, no stubs). **Authorized:** 2026-07-01 — explicit instruction to chart
the path toward the full aerospace fixed-wing recon-UAV vision, grounded by real solvers/tools
(OpenFOAM-class CFD authorized). **This doc plans; it does not build.** Each cut-list solver still
needs its own explicit go + human sign-off before any code lands (see §9).

> The objective: **delegate the majority of the design process to AI** — an AI that *uses code, tools,
> and external software* to converge a finalized aircraft. The load-bearing rule that makes this safe
> and not a hallucination engine: **tools produce the numbers, the LLM orchestrates and reasons.**
> This is Inversion #1 at aircraft scale. OpenFOAM instead of "guessing" is the whole thesis.

---

## 1. The taxonomy is a matrix, not a nested list

The PRD (and our earlier chats) muddled two orthogonal axes. They are separate:

- **Disciplines** — the *analysis lenses*. Each owns: parameters it cares about, a **solver/tool that
  grounds its numbers**, invariants, an export-gate contribution, and an LLM knowledge fragment.
  (aerodynamics, structures, propulsion, thermal, …)
- **Subsystems** — the *physical assemblies*. Each is a part/assembly with a geometry generator that
  **multiple disciplines analyze**. (wing, fuselage, empennage, …)

A UAV is **disciplines × subsystems**. Today the codebase fills essentially **one cell well**:
`structures × flat-plate` (+ `manufacturing × flat-plate`). The wing alone is a *column* of cells
(aero + structures + aeroelasticity + mass + manufacturing + control all touch it).

Naming reconciliation (vs current code):
- The ledger's `domains` node and `schema.Domains` == **disciplines** (structure, manufacturing today).
- The `packages/domains/` registry I added (bracket) is really the **subsystem/part axis** — a bracket
  is the simplest possible single-part "subsystem." It generalizes into the subsystem registry.
- Proposed code axes: `packages/disciplines/` (lenses + solver bindings) and evolve
  `packages/domains/` → the subsystem/part registry. (Implementation is its own PR — §8.)

---

## 2. Fidelity tiers — how "grounded, not guessing" is operationalized

Every discipline exposes its numbers at up to three fidelity tiers, mapped onto the existing
three-tier clock. **A tier is a promise about trust, not just speed.**

| Tier | What it is | Latency | Plane | Trust |
|------|-----------|---------|-------|-------|
| **L0** | closed-form / empirical / handbook | <1 ms | Interactive | **estimate only** — HUD + slider bounds. Never grounds an export on its own; always labeled. |
| **L1** | fast physics tool (XFOIL, AVL, QPROP, linear CalculiX, beam FEA) | seconds–minutes | Truth | **grounds most design decisions**; the working number. |
| **L2** | high-fidelity (OpenFOAM/SU2 RANS, nonlinear CalculiX, DLM flutter) | minutes–hours | Truth | **authoritative** — the check required before physical export / flight. |

Rule: an export gate for a discipline is satisfied only by an **L1-or-better** grounded verdict whose
geometry signature matches the current design. Missing / stale → `"unknown"` → **export blocked**
(same mechanism as today's `derived_resolver` + `gates`). L0 alone never flips a gate green.

---

## 3. Discipline catalog

Legend — **Grounding status:** 🟢 built · 🟡 partial · ⚪ wedge-legal, addable now · 🔴 cut-list
(needs explicit go + human sign-off).

### 3.1 Geometry & Configuration  ⚪ (foundational)
- **Role:** the parametric definition every other discipline reads — planform, airfoil, fuselage loft,
  tail arrangement, spar layout. Owns topological identity (OCAF — human wall).
- **Params (ex.):** `wing.airfoil`, `wing.span_mm`, `wing.chord_root_mm`, `wing.taper`, `wing.sweep_deg`.
- **Tools:** build123d / OCCT (have); airfoil loft + wing-box generators (new).
- **Human wall:** OCAF/TNaming identity for lofted surfaces — OCCT engineer.

### 3.2 Aerodynamics  🔴
- **Role:** lift, drag, moment, stall, drag polar, span efficiency, L/D — the core of flight.
- **Params:** airfoil, planform, incidence, Reynolds/Mach regime.
- **Fidelity:** L0 lifting-line / flat-plate closed form · **L1 XFOIL** (2D viscous polars) + **AVL**
  (3D VLM inviscid lift, induced drag, stability derivatives) · **L2 OpenFOAM/SU2 RANS** (viscous,
  stall, separation — the "not guessing" tier you authorized).
- **Grounds:** CL/CD/CM, stall AoA, L/D → feeds S&C, endurance, structures (loads).
- **Human wall:** turbulence model + mesh-independence validation — CFD engineer. Golden values from
  wind-tunnel / published polars, never Claude's run.

### 3.3 Stability & Control  🔴 (needs aero)
- **Role:** static margin (CG vs neutral point), trim, control-surface authority; dynamic modes
  (phugoid, short-period, dutch-roll, spiral).
- **Fidelity:** L1 AVL static derivatives → state-space eigen-analysis (numpy) for dynamic modes.
- **Depends on:** aero derivatives (§3.2) + inertia tensor (§3.8).

### 3.4 Structures  🟡 (have flat-plate FS; wing-box is new)
- **Role:** spar/rib sizing, wing bending under gust & maneuver load factors, FS, deflection.
- **Fidelity:** L0 beam theory · **L1/L2 Gmsh + CalculiX** (have the validated Spike-4 pipeline; extend
  from plate → wing box). 2nd-order tets mandatory (already enforced).
- **Loads come from:** aero (§3.2) — so structures at UAV scale is downstream of aero.
- **Human wall:** FS methodology for real 3D parts — FEA engineer / PE.

### 3.5 Aeroelasticity / Flutter  🔴 (hardest; specialist)
- **Role:** flutter speed, divergence, control reversal.
- **Fidelity:** DLM (doublet-lattice) coupled to structural modes. No strong free tool; often custom.
- **Human wall:** absolutely PE/specialist. Explicitly cut — plan only.

### 3.6 Propulsion  🔴
- **Role:** motor+prop matching, static & cruise thrust, shaft power, efficiency map.
- **Fidelity:** L0 disk-actuator · **L1 QPROP/QMIL** (Drela BEMT) + motor datasheet η-map + APC prop data.
- **Grounds:** thrust(V), power draw → feeds endurance.

### 3.7 Energy & Endurance  🔴 (the recon KPI)
- **Role:** loiter time, range. For a recon UAV this *is* the mission — everything trades against it.
- **Fidelity:** battery model (capacity, C-rate, sag) → electric endurance/range; P_required from
  drag×V / η_prop (couples aero L/D + propulsion η + weight).
- **Depends on:** aero + propulsion + weights (a genuine multidisciplinary coupling).

### 3.8 Weights, Balance & Inertia  🟡 (have mass/CG; inertia is new)
- **Role:** component mass buildup, CG, **inertia tensor** (needed by S&C).
- **Fidelity:** L1 deterministic geometry + BOM (have `bom.py`, `datum.py`); add inertia tensor.

### 3.9 Thermal  ⚪ (best wedge-legal next discipline — proof of the registry pattern)
- **Role:** motor/ESC/battery/avionics cooling; **thermoplastic service-temp limits** (PLA creeps ~60 °C).
- **Fidelity:** L0 material temp-limit check (closed-form, *honest export gate today*) · **L1 CalculiX
  steady-state heat transfer** (same solver family we already run).
- **Why first:** not on the cut-list, groundable now, exercises the full discipline seam end-to-end.

### 3.10 Payload / ISR (mission)  🔴 (what makes it "reconnaissance")
- **Role:** EO/IR sensor ground-sample-distance vs altitude, field of regard, gimbal; datalink budget.
- **Fidelity:** L0/L1 closed-form — GSD = pixel_pitch × altitude / focal_length; Friis link budget.

### 3.11 Manufacturing / DFM  🟢 (have; extends)
- **Role:** printability, wall/overhang rules, tolerances; large-part sectioning (PRD lip-and-groove);
  composite layup for wings.
- **Fidelity:** L1 slicer CLI for real cost/time (the known slicer-cost gap).

### 3.12 Cost & Logistics  ⚪ (optional)
- BOM cost + build time. Closes the slicer-cost gap.

---

## 4. Subsystem catalog

wing (airfoil/planform/spar/ribs/skin/ailerons/flaps/winglets) · fuselage (loft/bulkheads/bays) ·
empennage (H-stab+elevator / V-stab+rudder, or V-tail) · propulsion group (motor/prop/ESC/mount) ·
power system (battery pack/wiring/BMS) · launch & recovery (gear/catapult/belly/parachute) ·
payload bay (gimbal/EO-IR/window) · avionics (autopilot/GNSS/IMU/air-data/power) · comms
(datalink/antennas) · control-surface actuation (servos/linkages/hinges — cross-cuts wing+empennage).

---

## 5. The matrix — primary disciplines per subsystem (hot cells)

| Subsystem | Primary disciplines |
|-----------|--------------------|
| **Wing** | aero · structures · aeroelasticity · weights · manufacturing · control |
| **Fuselage** | structures · aero (drag) · weights · thermal · manufacturing |
| **Empennage** | aero · S&C · structures · weights |
| **Propulsion group** | propulsion · thermal · structures (mount) · weights |
| **Power system** | energy · thermal · weights · structures |
| **Launch & recovery** | structures · weights · (kinematics — cut) |
| **Payload bay** | ISR · thermal · weights · structures |
| **Avionics** | thermal · weights · ISR (integration) |
| **Comms** | ISR (link budget) · weights |

The **wing is the hot column** — 6 disciplines couple there. That's where MDO (§7) earns its keep and
where identity (§3.1) is hardest.

---

## 6. The AI delegation model — an engineer that *uses tools*

This is the heart of your objective. The AI does not *know* the drag; it *computes* it with a tool.

```
User prompt ("recon UAV, 3 h loiter, 5 kg MTOW, EO/IR, hand-launch")
      │
      ▼
[Chief Engineer agent]  — decomposes intent into a cross-discipline REQUIREMENTS MATRIX
      │                    (extends today's VerificationMatrix; TARGETS only, never values)
      ▼
[Discipline agents]     — each proposes ParameterDeltas within its lens (strict tool-use, as today)
      │
      ▼
[Validator = NOT an LLM] — routes each delta's geometry to the REAL SOLVER/TOOL for that discipline:
      │                    XFOIL · AVL · OpenFOAM · CalculiX · QPROP · slicer
      │                    → typed Verdict written to derived.<discipline>.*  (the SCALAR is the tool's)
      ▼
[MDO loop]              — bounded sweeps across coupled disciplines (wing column). NOT NSGA-II (cut) —
      │                    3-variant / gradient-free now; OpenMDAO-class MDO is a later flagged item.
      ▼
[Human gates]          — geometry-class change = AI_PROPOSED; explicit engineer accept + sign-off
                         before physical export. Any discipline "unknown" → export BLOCKED.
```

Every arrow that produces a *number* is a **tool invocation**, not an LLM token. The LLM's job is to
decompose, propose parameters, read solver verdicts, and iterate — a tool-using systems engineer.
That is what makes "delegate the design to AI" defensible rather than a fabrication risk.

Reused, already-built seams: `ParameterDelta` emission + strict tool-use; `apply.py` rules validator;
`derived_resolver` geometry-signature → verdict caching (generalizes to per-discipline verdicts);
`gates.py` "unknown blocks export"; `StrategicAgent` → the Chief Engineer decomposer;
`requirements.py` VerificationMatrix → the cross-discipline requirements matrix.

---

## 7. Wedge → UAV flip order (dependency DAG)

You cannot do S&C before aero, or endurance before propulsion+aero+weights. The roadmap is
dependency-ordered; each phase flips 🔴/🟡 → 🟢 as a **real solver lands + gets human sign-off**.

- **Phase A — Wedge (now, all wedge-legal):** Structures (plate→wing-box), Manufacturing, Weights/CG,
  **Thermal** (the proof-of-pattern discipline), Cost. All groundable today.
- **Phase B — Aero foundation:** wing/airfoil geometry generators (build123d loft) → **Aerodynamics
  L1** (XFOIL+AVL). Unlocks everything downstream.
- **Phase C — Flight:** Stability & Control (needs aero + inertia), Propulsion, Energy/Endurance.
  Now it "flies" on paper.
- **Phase D — Fidelity & safety:** **Aerodynamics L2 (OpenFOAM)**, gust/maneuver structural loads,
  Aeroelasticity/flutter. The authoritative validation before anything flies.
- **Phase E — Mission:** Payload/ISR, Comms, autonomous launch/recovery. Now it's a *recon* UAV.

---

## 8. Proposed code architecture (proposal — its own implementation PR)

```
packages/disciplines/                 # the analysis-lens axis (NEW)
  __init__.py        registry: register(DisciplineSpec)
  base.py            DisciplineSpec: params, solver bindings (per fidelity tier),
                     invariants, export_gate_contribution, knowledge_fragment
  structures.py  manufacturing.py  thermal.py   ...   (one file per lens)
packages/domains/  → packages/subsystems/   # the physical-assembly axis (evolve existing registry)
  bracket.py (→ a trivial single-part subsystem)  wing.py  fuselage.py  ...
packages/truth_plane/solvers/         # real tools live here (CalculiX today; XFOIL/AVL/OpenFOAM/QPROP later)
```

Typed seams only (Pydantic across boundaries) — as today. A new discipline = one file + `register()`;
schema, prompt builder, validator, and gates pull from the registry (the pattern we already started).

---

## 9. Guardrails & human walls (do not self-certify)

- **Inversion #1 holds at every tier:** the LLM never originates a safety scalar. Tools/solvers do, or
  it's `"unknown"` and blocks export. No fabricated green light — ever.
- **Golden values** come from handbook / wind-tunnel / published data / PE — never Claude's own run.
- **Human walls:** CFD turbulence+mesh validation (CFD eng.) · FS methodology for 3D parts (FEA eng./PE)
  · flutter (specialist) · OCAF identity for lofted surfaces (OCCT eng.) · numerical determinism (BLAS/FMA).
- **Cut-list discipline builds (🔴) each need their own explicit go + sign-off.** This doc authorizes
  *planning* and the *wedge-legal* Phase-A build (esp. Thermal). It does **not** authorize dropping
  aero/propulsion/flutter code — even stubs — until you say so per discipline.
- The wedge is **not abandoned** — it is the *vehicle* to the UAV. Aerospace matures *behind* a
  shipping wedge, exactly as the build-plan says; this doc is the bridge, not a U-turn.

---

## 10. Immediate next step (wedge-legal, buildable now)

1. ✅ **`packages/disciplines/` registry** — `DisciplineSpec` + registry; `structures` and
   `manufacturing` formalized as the first two specs (params, knowledge fragments, geometry params).
2. ✅ **Thermal (§3.9)** added as the third discipline — L0 material service-temp gate live now
   (`bom.Material.service_temp_c`), L1 heat-load margin reports `"unknown"` (blocks export) until the
   CalculiX heat-transfer solver is wired. Opt-in via optional `Domains.thermal`, so existing brackets
   are unaffected. Seams: `gates.evaluate_export_gates(extra_findings=…)`,
   `prompt_builder` active-discipline fragments, `disciplines.all_discipline_findings/_invariants`.
   Covered by `tests/disciplines/test_disciplines.py` (12 tests, green).
3. ✅ Reconciled naming: `packages/domains/` → `packages/subsystems/` (`SubsystemContext`,
   `subsystem_type` on ProjectMetadata). `SubsystemContext` now carries `applicable_disciplines` (the
   matrix cell) + a lazy `geometry_builder`; `/export/step` resolves geometry from the active
   subsystem's registry entry (no hardcoded part type). Covered by `tests/subsystems/`.
4. ⬜ Wire the real **CalculiX steady-state heat-transfer** solver to flip thermal L1 from `"unknown"`
   to a grounded margin (truth plane; FEA-engineer sign-off on methodology).
5. 🟡 **New-geometry subsystems** — model chosen (optional param blocks): each subsystem owns an
   optional schema block; `SubsystemContext` carries `geometry_builder` + `volume_mm3`; the prompt is
   scoped to the active subsystem's params + cross-cutting params (so an enclosure hides the bracket's
   plate dims); the active subsystem's `check_invariants` runs on the live slider path.
   ✅ **Eight subsystems** built: `bracket`, `enclosure` (box shell), `standoff` (cylinder + bore),
   `lbracket` (two flanges), `uchannel` (channel section), `panel` (plate + window + corner holes),
   `washer` (annulus — reuses the standoff generator), and `table` — an **ASSEMBLY/composite**
   (tabletop + four legs). Tests in `tests/subsystems/`.
   ✅ **Scalable subsystem architecture landed** (2026-07-02, Phases A–E). Each subsystem is now a
   single ~30-line file (`packages/subsystems/<name>.py`) declaring a `Subsystem(name, description,
   fragment, disciplines, params: list[ParamSpec], build, volume, invariants)`. The **ParamSpec is the
   single source of truth** for a part's params; ledger storage/dotted paths/sliders/seeding/prompt
   filtering all derive from it. Bracket geometry (and every subsystem's geometry) lives in the
   generic `Domains.geometry: dict[str, ParameterDef]` bag under `domains.geometry.<name>` — NO
   per-part `*Domain` class, NO per-part block in `nodes.py`, NO per-part edit to `schema.py`. Adding
   a subsystem = ONE self-contained file, zero central edits. `StructureDomain` now holds only
   `material_profile` (the discipline); ManufacturingDomain holds only universal DFM inputs. See
   `C:/Users/Chirag/.claude/plans/cosmic-herding-toucan.md`.
   • **Assemblies fit the same registry with no ledger refactor**: a composite is a `SubsystemContext`
   whose `geometry_builder` COMPOSES several positioned sub-bodies (generator-tagged) and whose
   `volume_mm3` SUMS them — the "sum of parts" pattern (see `subsystems/table.py`). Static composition
   only (positioning); motion/kinematics/swept-volume stays on the cut-list. A fuller assembly axis
   (per-instance params, joints/mating, interference checks, assembly STEP, CG via `bom`/`datum`) is a
   later, larger piece.
   ✅ **Live subsystem switching** — `GET /subsystems`, `POST /project/subsystem {name}` reseeds the
   project from that subsystem's `seed_defaults`; telemetry (`volume_mm3`) + geometry (`/mesh`,
   `/export/step`) + `/params` sliders + invariants + prompt all follow the active subsystem.
   `tests/backend/test_subsystem_switch.py`.
   ✅ **Frontend** — header part-type picker; dynamic sliders from `/params`; viewport renders any
   subsystem's mesh; the copilot is subsystem-aware (knows the menu, proposes `switch_subsystem` with a
   human confirm, declines unbuilt aerospace parts honestly).
   ⬜ Fold subsystem `geometry_params` into the verdict signature (`derived_resolver`) once a subsystem
   gets a real solver — deferred (no per-subsystem FEA yet).

Steps 1–2 exercise the full registry → prompt → validator → gate → export path and lay the rails every
🔴 discipline will later ride — without touching the cut-list.
