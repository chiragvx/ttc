# Parametric drivetrains (gears, ratios, multi-gear interactions) — prior-art research + project fit

**Date:** 2026-08-03
**Status:** Exploratory research only — nothing here is built or scheduled. Captured so future work
doesn't re-derive it from scratch.

## Context / the question being evaluated

How can complex parametric drivetrains — multiple gears, gear ratios, different gear types, and
their meshing interactions — be built, ideally via an "instantly generated" (closed-form, not
iterative/optimization-based) parametric method? What's the best approach, and specifically: how would
this tie into this project's own architecture — the EKG (Engineering Knowledge Graph:
Component/Interface/Connection/Coupling), build123d, and the subsystem catalog already built?

This research has two halves, run in parallel:
- **External research** (4 agents, Sonnet 5, via the Workflow tool): (Q) build123d/CadQuery native gear
  support and existing gear-generation libraries, (R) the actual closed-form involute-tooth-profile
  math, (S) gear-train topology — ratio formulas and meshing/center-distance constraints for simple/
  compound/planetary trains, (T) whether a complete open-source parametric drivetrain/gearbox generator
  exists anywhere. A fifth agent synthesized the four raw reports.
- **Internal codebase audit** (a separate Explore agent, read-only, this repo only): exactly what
  already exists here that's gear/rotation/ratio-adjacent — subsystems, the relation catalog, the
  interface helpers, the `Coupling` primitive's actual (not documented) schema, and the
  `assembly_template` compound-part mechanism. This half answers the "how does this tie into what we've
  already built" question directly, grounded in real file:line references, not speculation.

Citation status for the external research (directly fetched vs. search-snippet-only vs. recalled/
unverified) is preserved exactly as each agent reported it. No URL was invented. The internal audit is
grounded entirely in files actually read this session, with file:line references throughout.

**Headline finding**: neither build123d nor CadQuery has a native gear primitive, but there are three
real, actively-maintained libraries to build on — two of them **build123d-native**
(`py_gearworks`, `bd_warehouse.gear`) — so "generate real involute gear geometry in build123d" is
close to a solved, off-the-shelf problem. The much bigger finding is on the project-fit side: this
repo has **zero** gear-domain vocabulary anywhere (confirmed by exhaustive grep — no "ratio",
"involute", "module", "backlash", "planetary", "drivetrain" hits at all), every existing
gear/pulley/sprocket subsystem is a bare dimensioned cylinder with no teeth (deliberately, per an
explicit permanent cut-list entry), and the `Coupling` primitive as actually implemented (not as
documented in the architecture doc) cannot yet propagate a derived rotational quantity (RPM/torque
through a ratio) to a target part — it would need a new relation, new rotational-duty params on gear
subsystems, and a new consumption path downstream of `resolve.py`, not a drop-in registry entry.

---

## Part A — External research synthesis (read this first for "what's out there")

# Parametric Drivetrain Generation — Synthesis of 4 Research Reports

## 1. Native support + real existing libraries for gear tooth geometry

**Neither kernel has native gear primitives.** Confirmed by direct fetch: `github.com/gumyr/build123d`'s README/feature list has no mention of gears; `github.com/CadQuery/cadquery`'s README likewise has none. Both are general-purpose sketch/solid frameworks (lines, arcs, extrude, fillet, loft, sweep) — not gear generators.

Real, independently-confirmed libraries built on top:

- **cq_gears** (CadQuery-based) — https://github.com/meadiode/cq_gears. Correct owner is `meadiode`; one sub-agent noted `github.com/CadQuery/cq_gears` 404s, so don't use that org. "CadQuery based involute profile gear generator," needs CadQuery *dev* (not 2.1) + NumPy. Types: spur, helical, herringbone, ring gears (helical/herringbone), **planetary gearsets**, straight/helical bevel, racks. Apache 2.0. Last commit reported Dec 27 2024, ~96–159 stars (varied between two fetches), self-described v0.51 "work in progress... might be unstable." Not confirmed on PyPI (page load errors both attempts — inconclusive, not a confirmed "no").
- **py_gearworks** (formerly gggears) — https://github.com/GarryBGoode/py_gearworks (docs: gggears.readthedocs.io), **build123d-native**. Types: spur, helical, bevel, cycloid, inside-ring. Explicitly *not yet*: hypoid, worm, face, crown. Confirmed classes `SpurGear`, `HelicalGear`, `BevelGear`, `CycloidGear`, plus a `mesh_to()` method that aligns two meshing gears with configurable backlash (also: undercut, profile shift, root/tip fillet, crowning). Apache 2.0, 71 stars/8 forks/221 commits. Listed in the community `awesome-build123d` list (github.com/phillipthelen/awesome-build123d).
- **bd_warehouse** `gear` module — build123d-native, docs at https://bd-warehouse.readthedocs.io/en/latest/gear.html, on PyPI as `bd-warehouse`. **Spur only** (ISO metric involute), no helical/bevel. Confirmed real classes/args from the actual doc page: `InvoluteToothProfile`, `SpurGearPlan`, `SpurGear` (`module`, `tooth_count`, `pressure_angle`, `root_fillet`, `addendum`, `dedendum`, `thickness`, `rotation`, `align`, `mode`). Confirmed example: `SpurGear(module=2, tooth_count=12, pressure_angle=14.5, root_fillet=0.5*MM, thickness=5*MM)`.
- **FreeCAD Gear Workbench** — https://github.com/looooo/freecad.gears. Mature: GPLv3, 347 stars/114 forks/403 commits, FreeCAD ≥1.0/Python ≥3.8. Types: cylindrical involute, involute rack, cycloid + cycloid rack, spherical(bevel) involute, crown, worm, timing, plus helical/undercut/fillet options. Cites "Elements of Metric Gear Technology" as its reference but the exact algorithm (closed-form vs. hobbing simulation) wasn't confirmed from what was fetched. Not build123d-importable — would need porting. Three separate agents independently confirm it generates **individual gears only**, no train/assembly logic.
- **pymadcad** — https://pymadcad.readthedocs.io/ (standalone kernel, not OCCT-based) — confirmed real gear module at .../reference/gear/: `rackprofile()`, `gearprofile(step, teeth, height, offset, asymetry, pressure_angle, resolution)`, `spherical_gearprofile()`/`bevelgear()` (helical via `helix_angle`), `gearexterior()`, plus math helpers `involute()`, `involuteat()`, `involuteof()`, `spherical_involute()`. Mathematically explicit — a plausible porting reference even though it's a different kernel.
- **Weaker/unverified leads**, reported honestly: **pyGear** (pythonOCC-based, sourceforge.net/projects/pygear) was flagged "not independently verified" by one agent but was separately confirmed to exist by another (alpha status, last updated 2023, hobbing-kinematics simulation, single-gear only — **note this is one real discrepancy between two reports on verification confidence, though not on the underlying facts**); **sphinxxxx's involute gear generator** (JS web tool, not Python, never fetched); **manim-gearbox** and **yapCAD** (only in an aggregated search snippet, never independently fetched — do not treat as confirmed).

## 2. The involute tooth-profile math — genuinely closed-form/O(1)?

**Yes**, confirmed by two independent math sources for the base curve and two independent gear-engineering sources for the sizing equations.

Involute of a circle (identical in both sources):
- Wikipedia, "Involute" — https://en.wikipedia.org/wiki/Involute — `X(t)=r(cos(t+a)+t·sin(t+a))`, `Y(t)=r(sin(t+a)−t·cos(t+a))`
- Wolfram MathWorld, "Circle Involute" — https://mathworld.wolfram.com/CircleInvolute.html — `x=a(cos t + t sin t)`, `y=a(sin t − t cos t)`, plus arc length `s(t)=½at²`, curvature `κ(t)=1/(at)`

Gear sizing (module `m`, teeth `z`, pressure angle `α₀`):
- tec-science, "Geometry of Involute Gears" — https://www.tec-science.com/mechanical-power-transmission/involute-gear/geometry-of-involute-gears/ — `d₀=m·z`, `p₀=m·π`, `cos(α₀)=d_b/d₀`, `h_a=m`, `h_d=m+c`, `d_a=m(z+2)`, `d_d=m(z−2)−2c`
- tec-science, "Calculation of Involute Gears" — same domain, .../calculation-of-involute-gears/ — involute function `inv(α)=tan(α)−α`, `d_b=m·z·cos(α₀)`, and the tooth-thickness-at-any-radius formula `s = d·(s₀/d₀ + inv(α₀) − inv(α))` with `s₀=m·(π/2+2x·tanα₀)` — stated as a **direct, non-iterative** evaluation.
- KHK Gears — https://khkgears.net/new/gear_knowledge/gear_technical_reference/involute_gear_profile.html and .../calculation_gear_dimensions.html — same formula family (`inv α = tanα − α`, `p_b=π·m·cosα`, `h_a=1.00m`, `h_f=1.25m`, `d_b=d·cosα`), citing **JIS B 1701**.

Standards: **ISO 53:1998** cited by Wikipedia's "Involute gear" article; **JIS B 1701** cited by KHK; **AGMA** confirmed to exist and be ANSI-accredited for U.S. gearing standards (en.wikipedia.org/wiki/Gear, en.wikipedia.org/wiki/American_Gear_Manufacturers_Association), but a specific standard number (e.g. AGMA 908-B89) is explicitly flagged by the researcher as **"recalled from general knowledge, not verified this session"** — treat as unconfirmed. `sdp-si.com`'s well-known "Elements of Metric Gear Technology" handbook returned an HTTP 307 redirect and was never actually retrieved.

Per-tooth generation is genuinely O(1): evaluate the involute for `t` up to `t_max = tan(α_a)` (from `cos α_a = r_b/r_a`, itself direct), mirror the flank via the closed-form thickness-angle formula, array both flanks at `2π/z` spacing. No root-finding anywhere in this path. The one place real iteration enters gear math is inverting `inv(α)` for an *operating* pressure angle under profile shift (`inv(α_b) = 2(x₁+x₂)/(z₁+z₂)·tanα₀ + inv(α₀)`, no closed-form inverse → Newton's method) — but that's a meshing/center-distance problem, separate from single-tooth generation.

## 3. Multi-gear trains — ratio formulas and meshing constraints

*Caveat carried over from the research: WebSearch was unavailable for the entirety of this sub-investigation (shared session budget exhausted), so everything below came from direct WebFetch to specific URLs rather than broad search — coverage here is narrower than the other sections.*

- **Simple train** — https://en.wikipedia.org/wiki/Gear_train — `R_AB = |ω_A|/|ω_B| = r_B/r_A = N_B/N_A`; mechanical advantage `MA = T_B/T_A = N_B/N_A`.
- **Compound train** — same page, `#Compound_gear_train` — worked 3-gear example (A→idler I→B) showing idler-teeth cancellation: `R_final = (N_I/N_A)·(N_B/N_I) = N_B/N_A`. Note: the page demonstrates but does **not** state verbatim the general multi-stage "product of driven teeth / product of driving teeth" formula — the researcher describes the general formula as consistent with what's shown, not as a directly-quoted extension.
- **Planetary/epicyclic (Willis equation)** — https://en.wikipedia.org/wiki/Epicyclic_gearing — `N_s·ω_s + N_r·ω_r = (N_s+N_r)·ω_c`; carrier fixed → `ω_s/ω_r = −N_r/N_s`; ring fixed → `ω_s/ω_c = 1+N_r/N_s`; sun fixed → `ω_r/ω_c = 1+N_s/N_r`.
- **Center distance (meshing constraint)** — confirmed by two independent sources: KHK — https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html — `a = m(z₁+z₂)/2`; and Wikipedia's gear-train page — `center distance = r_A + r_B` with pitch compatibility `r_B/r_A = N_B/N_A`.

**Generators for trains specifically:** cq_gears (https://github.com/meadiode/cq_gears) is the one real candidate — it explicitly lists "planetary gearsets" as a supported type, has example imagery and a dedicated notebook (`examples/ring_gears_and_planetary_gearsets.ipynb`), exposes pitch radius (`r0`) for positioning, and demonstrates a "4 meshing gears" array via CadQuery's `rarray()`. However, the researcher could **not** fetch the actual notebook or `planetary.py` source (both attempts 404'd on guessed paths) — so the *capability and documentation are confirmed*, but it's **not confirmed** whether center-distance/ratio enforcement is automatic vs. left to the caller (README phrasing suggested user-managed positioning). FreeCAD Gears was re-checked for this specific question and reconfirmed as single-gear geometry only. **No standalone open-source "parametric gear-train generator" or "planetary gearbox generator" beyond cq_gears was located** — but the researcher is explicit this reflects the WebSearch outage (a real coverage gap), not a confirmed absence.

## 4. Does a complete generator (tooth geometry + train topology + ratio, all-in-one) exist?

**No, across all four reports, converging independently.** Every real tool does one half well at most, or does both but only for a single pair — never an arbitrary train, never (working) planetary.

- **py_gearworks** — closest to combining both halves, but only for a **single meshing pair**: real geometry + `mesh_to()` correctly positions gear 2 against gear 1 (center distance + backlash). **Planetary drive design is explicitly listed as planned/upcoming, not implemented.** "Early development, no API stability yet" per its own docs.
- **bd_warehouse gear**, **FreeCAD Gear Workbench**, **pyGear** — geometry only, no auto-positioning/train assembly.
- **python-gearbox** (PyPI) — AGMA-2101/ISO-6336 stress calc + single-tooth export to FEA tools, not a CAD/train generator, early-stage (0.1.2.a, 2015).
- **hyperair/planetary-gears** (GitHub, OpenSCAD) + assorted Thingiverse/Printables/MakerWorld "parametric planetary gearbox" scripts — these genuinely produce a real meshing planetary assembly parametrically, but are maker-community scripts sized to specific hardware (e.g. NEMA stepper mounts), not general "ratio+torque in → correct geometry out" engineering generators.
- **cq_gears** — documented planetary capability (§3) but automatic ratio/center-distance enforcement unconfirmed from source. Worth flagging: the report specifically surveying "full generators" (§4's source report) did **not** list cq_gears at all in its library table, while the two reports covering §1 and §3 both treat it as real and planetary-capable — this looks like a coverage gap between reports rather than a factual contradiction.

**Commercial tools** (confirmed to exist, not integration candidates given the open-source framing): **KISSsoft** (kisssoft.com) — calculation/optimization-first, not confirmed to auto-generate 3D geometry as its core function; **GearTrax** (camnetics.com/geartrax) — CAD-plugin generator for individual components (spur/helical/bevel/worm/splines/sprockets/pulleys/cycloidal), you place them yourself; **Gearotic Motion** (gearoticmotion.com) — hobbyist/CNC component templates; **MITCalc** (mitcalc.com) — Excel calc suite with CAD export.

**Academic work:** Holder & Rudolph 2019 ("Automated requirements-driven design synthesis of gearboxes with graph-based design languages," Springer, doi 10.1007/s10010-019-00322-z) is exactly on-topic by title/abstract but **paywalled, unverified in detail**. A ResearchGate paper (pub. 267488322) returned HTTP 403, snippet-only. A ScienceDirect result on gearbox loss modeling is snippet-only. One paper *was* fully retrieved — arxiv.org/pdf/2409.06016v3, "Deep Generative Model for Mechanical System Configuration Design" — and it's explicitly an **AI/trained-generative-model** approach, not closed-form — a negative data point confirming that recent published "automated" gear-train synthesis leans AI, not deterministic.

## 5. Bottom line

- **Single-tooth geometry is genuinely closed-form/O(1)** — two independent math sources agree on the base involute curve, two independent gear-engineering references agree on the sizing/thickness equations. No search needed to go from `(module, teeth, pressure angle, addendum, dedendum)` to one tooth.
- **Train ratios are also closed-form** — simple/compound trains reduce to teeth-ratio products (Wikipedia; general product formula is consistent-with-but-not-verbatim-quoted from what was fetched), planetary trains reduce to the Willis equation (Wikipedia epicyclic-gearing page), center distance is `m(z₁+z₂)/2` (confirmed twice, independently). The only real iteration is inverting `inv(α)` for an operating pressure angle under profile shift — irrelevant to basic instant generation.
- **Nobody has published the fully-combined generator.** All four reports converge on this: the field splits into geometry libraries (single gears, at best a meshing pair) and textbook-level topology/ratio math, with **py_gearworks** and **cq_gears** the only two crossing the line at all — py_gearworks for one meshing pair (planetary explicitly not yet built), cq_gears with documented-but-unverified-as-automatic planetary/multi-gear positioning. No open tool takes {ratio, RPM/torque, gear count} and deterministically emits a correctly-meshing multi-gear or planetary assembly in one pass. The one paper claiming that exact scope is paywalled; the one fully-read "automated" paper is AI-based, not deterministic.

**The most direct, grounded, deterministic (non-AI) path**, built only from what's actually confirmed above:

1. **Tooth geometry** — use **py_gearworks** (build123d-native; spur/helical/bevel/cycloid/inside-ring; confirmed `SpurGear`/`HelicalGear`/`BevelGear`/`CycloidGear` classes; `mesh_to()` for pair alignment) as the primary geometry engine, since it's the only build123d-native option with broad type coverage. Cross-check/fall back to **bd_warehouse**'s `SpurGear`/`SpurGearPlan`/`InvoluteToothProfile` for its clean, confirmed spur-gear API, and to the tec-science/KHK closed-form equations (§2) directly wherever library coverage runs out (e.g. specific profile-shift or internal-ring cases) — this math is simple enough to implement in-repo rather than reverse-engineer from a library.
2. **Train topology and ratios** — no library needed here; implement the Wikipedia simple/compound-ratio formulas and the Willis planetary equation (§3) as plain closed-form Python over teeth counts, using the KHK/Wikipedia center-distance formula `a = m(z₁+z₂)/2` as the constraint that positions each gear instance.
3. **For a second reference on planetary geometry or broader tooth-form conventions**, consult **cq_gears**'s planetary-gearset code/notebook (real, documented, internals unverified) and **FreeCAD Gear Workbench** (mature, cross-checks tooth-form conventions across 8-9 gear types, not importable into build123d but useful as a math/parameter reference).
4. This composition — deterministic involute math (§2) + deterministic train-ratio math (§3) + an existing build123d-native geometry library (py_gearworks/bd_warehouse) for the solid — matches this repo's own guardrail: the LLM would only ever emit `ParameterDelta`-style inputs (teeth counts, module, target ratio, gear types), while 100% of tooth curves, center distances, and Willis-equation ratio math stays closed-form and deterministic — the ratio/placement math fits the "closed-form arithmetic, no OCCT, no LLM" interactive-plane tier, and only the actual OCCT solid build goes to the kernel-regen tier.

The honest gap: nobody has open-sourced the "topology + ratio + geometry" glue as a single library — that glue layer (deciding gear counts/types from a target ratio, driving `py_gearworks`/`bd_warehouse` positioning from the Willis/product-ratio math) would be net-new code this project writes, sitting on top of the two real geometry libraries and the textbook-confirmed ratio math cited above — not a from-scratch involute or ratio derivation.

---

## Part B — How this maps onto THIS project's existing architecture (grounded in code, not speculation)

This section is written directly by the orchestrating session from a dedicated read-only codebase
audit (a separate Explore agent, this repo only) — every claim below cites a real file:line. This is
the part the external web-research agents structurally cannot answer, since they cannot see this repo.

### B1. Every gear/pulley/sprocket subsystem today is a bare cylinder — confirmed by reading the actual `_build` functions, not the filenames

`packages/subsystems/gear_blank.py`, `pinion_blank.py`, `sprocket_blank.py`, `pulley_blank_flat.py`,
`pulley_blank_timing.py`, `pulley_blank_v.py`, `jaw_coupling.py` — every one of these is, in its
`_build` function, literally `bd.Cylinder(radius=p.dia_mm/2.0, height=p.height_mm)`. **Zero tooth,
groove, spline, or sprocket-tooth geometry exists anywhere in this set.** This is explicit and
permanent, not an oversight:

- `gear_blank.py`'s own module docstring: *"Gear disc with hub, no teeth... Fine surface/profile
  detail this part's real-world name implies (knurling, a domed end, hex flats, a countersunk/rounded
  head, wing tabs, **gear/sprocket teeth**) is deliberately NOT modeled... This represents the part's
  structural envelope/mounting geometry, not its full cosmetic profile."*
- `build-plan/reference/SUBSYSTEM_PROPOSALS.md:256` lists **"gear tooth generation"** explicitly among
  a permanent "parked" list — "Kept off the list until there's a use-case that demands them (all
  needs specialty geometry or physics we can't ground)."

`hub.py` is the one partial exception — a genuinely stepped (disc + boss) shape with bespoke
`InterfaceSpec` frames — but it's still a plain mount/press-fit interface, not a mesh-aware one.
`rigid_coupling.py`, `flex_coupling_blank.py`, `shaft_collar.py`, `wheel_hub.py`, `prop_hub_blank.py`,
`keyway_shaft.py` are all the same `render_standoff` cylinder-with-bore archetype, and none are
`fea_eligible` (the gear/pulley/sprocket/pinion blanks ARE `fea_eligible=True`, but only as plain
cylinders — the FS check has nothing gear-specific to say about them).

### B2. The relation catalog has 12 relations — all static-structural, zero rotational-kinematics

`packages/couplings/relations.py` (expanded to 12 relations the same day as this research, see the
grounding-repair work): `force_from_mass_accel`, `force_from_pressure_area`,
`torque_from_force_radius`, `bending_from_distributed_load`, `stress_from_force_area`,
`deflection_of_cantilever_beam`, `spring_force_from_rate_deflection`, `shear_stress_from_torque_radius`,
`bending_from_cantilever_point_load`, `bending_from_cantilever_distributed_load`,
`second_moment_of_area_rectangular`, `second_moment_of_area_circular`,
`polar_second_moment_of_area_circular`, `euler_buckling_critical_load_pinned_pinned`,
`bolt_preload_from_torque`, `bolt_shear_stress_from_transverse_force`. None compute a ratio, a
gear-mesh torque/speed relationship, or anything angular-velocity/RPM-related.
`torque_from_force_radius` is the closest superficial neighbor, but it's a static lever-arm torque
(`force_n × radius_mm`), not a rotational-transmission relation — there is no
`torque_from_ratio`/`speed_from_ratio` counterpart. A repo-wide grep for "ratio", "mesh" (gear sense),
"module" (gear sense), "pitch diameter", "backlash", "planetary", "drivetrain", "gear train":
**zero hits, anywhere in the repository.** This is a from-scratch domain for this project, not an
extension of anything partial.

### B3. No interface anywhere is axis-aware enough to express a gear mesh

Every gear/pulley/sprocket/hub/coupling part above declares interfaces via
`packages/subsystems/base.py::cylinder_end_interfaces` — confirmed: this returns exactly two
`Frame`s (`origin=(0,0,±height/2)`, `normal=(0,0,±1)`), a purely **axial end-cap stacking**
interface (mount this cylinder's flat face against another part's flat face along a *shared* Z axis).
It carries no pitch-diameter/radius information and no notion of a second, laterally-offset, parallel
shaft axis. It cannot express "gear A and gear B mesh when their two *parallel* axes are held
`center_distance = (d1+d2)/2` apart" — that's a fundamentally different geometric relationship
(two parallel axes, radial contact) than "one shared axis, flat faces touch," which is all any
existing interface helper can represent. `base.py`'s own docstring on `box_face_interfaces` already
discloses this class of limitation generally: *"HONEST LIMITATION shared with every interface pair in
this v1 (translation-only mating, rotation deferred to Phase 1b...)."* `InterfaceSpec.kind="port"` is
documented as *"a future coupling attach point, Phase 2"* but has zero real usages anywhere in the
registry — a placeholder, not a mechanism.

### B4. The `Coupling` primitive: what's documented vs. what's actually implemented — a real, specific gap

`build-plan/reference/ENGINEERING_GRAPH_ARCHITECTURE.md` §2 states the Coupling shape as:
```
Coupling:
  source:   { instance, interface, quantity }
  relation: <a registered relation id>
  target:   { instance, interface }
```
The **actual** Pydantic models (`packages/ledger/schema.py:219-253`) are different in three concrete
ways:
- `CouplingInput` has no `interface` field — sourcing is `from_instance` + `from_param` (a raw
  part **param name**), not an interface reference. Interfaces are a wholly separate concept used only
  by `Connection`, never `Coupling`.
- `target_instance: str` is a whole instance, not `{instance, interface}` — and there is no
  target-*param* addressing at all.
- Consumption is hard-wired: `packages/couplings/resolve.py`'s
  `LOAD_BEARING_OUTPUT_QUANTITIES = {"force_n", "torque_nmm", "moment_nmm", "preload_n"}` and
  `derived_load_n()` only know how to turn a coupling's output into a force feeding a cantilever FS
  check. There is no generic "write this derived value into target param X" mechanism.

**So the Coupling primitive does *not* already generalize cleanly to "gear A's RPM/torque drives gear
B's RPM/torque via a ratio."** A gear-ratio relation would resolve fine *numerically* through the
existing `resolve_coupling()` machinery (that part IS generic), but three real gaps remain: (1) no
`gear_ratio`/`speed_from_ratio`/`torque_from_ratio` relation exists yet — straightforward to add,
same pattern as the 12 that exist; (2) no gear subsystem has an `rpm`/`torque` param to source from
today; (3) the *consumer* side (`resolve.py`, the FS gate) is hard-typed to the structural-load
vocabulary — an `rpm_out` output would resolve but nothing downstream would know what to do with
it. This is a new **quantity category** (rotational-duty propagation) layered onto the existing
DAG-of-relations mechanism, not a drop-in reuse of the load path.

### B5. `assembly_template.py` could spawn N meshing gears — but only the placement half, not the ratio half

The compound-part mechanism (`packages/subsystems/assembly_template.py`, used today by `table.py`,
`standoff_frame.py`, `rail_mount_assembly.py`) lets one "master" instance auto-spawn N typed children
via `ChildSpec(local_id, subsystem_type, transform, params)`. This is structurally reusable for "one
drivetrain instance spawns N gear-blank children" as a pure geometry/placement convenience — but
two real limitations bear directly on gear trains:
- **Single-level only** — `reconcile_all()`'s own docstring states it explicitly: *"does not (yet)
  handle an assembly-template instance whose OWN children are themselves assembly-template instances
  — no such nesting exists in the registry today."* A planetary stage that needed to be its own
  nested sub-assembly is exactly what this rules out.
- **Purely positional** — `ChildSpec`/`Transform` carry only static translation + fixed Euler
  angles and a flat params dict. Nothing analogous to "child B's rotation is driven by child A's
  rotation at ratio R" exists. Every current user only computes static placement (corner-ring math,
  even spacing) — none declares any inter-child coupling.

A gear train's defining relationship — gear B's speed/torque being *derived from* gear A's via a
ratio — would have to be bolted on separately through the `Coupling` mechanism (itself gapped per
B4), not expressed through `assembly_children` alone.

### B6. `Connection.kind` has no rotational/kinematic value either

`packages/ledger/schema.py:176-190`: `Connection.kind` is a closed `Literal["mate", "bolted",
"slip_fit", "containment"]`, and the class's own docstring says *"`kind` is advisory today (all kinds
mate the same way in Phase 1)"* — even the four kinds that exist don't yet differentiate mating
*behavior*. `gap_mm` is the only relationship data carried, a static offset, not an angle or ratio.
There is no field anywhere for "these two interfaces rotate relative to each other at ratio R." Worth
noting by contrast with B4: `Connection` IS interface-typed but has no rotational semantics; `Coupling`
DOES carry derived-relationship semantics but isn't interface-typed at all — neither half of the
schema currently has both properties a gear mesh would need simultaneously.

### B7. What this adds up to

Nothing here is a blocker — every gap above is a specific, nameable extension of a pattern that
already exists (a new relation in the same registry shape; new params on gear subsystems; a new
interface-frame helper alongside the existing four; a new `Connection.kind` value; a generalization of
`resolve.py`'s output-quantity handling beyond the structural-load allowlist). But it is accurate to
say this project has built zero of the domain-specific groundwork for drivetrains today, and the
external prior art (Part A) supplies the missing tooth-geometry half almost completely
(`py_gearworks`/`bd_warehouse` are build123d-native and ready to use) while the *system*-level half
(ratio propagation through the EKG, axis-aware meshing interfaces) is a real, if bounded, extension
this project would be first to build.

---

## Part A raw agent reports (unedited)

### Agent Q — build123d / CadQuery native gear generation and existing gear libraries

Now I have solid, verified findings across all sub-topics. Compiling the report.

## Findings

**1. build123d core — no built-in gear primitive.**
Fetched `github.com/gumyr/build123d` directly: the README/feature list has no mention of gears at all. Confirmed: build123d ships general-purpose sketch/solid primitives (lines, arcs, extrude, etc.), not gear tooth generation.

**2. CadQuery core — no built-in gear primitive either.**
Fetched `github.com/CadQuery/cadquery`: no mention of "gear" in the README/description. It's a general parametric-modeling framework (fillets, lofts, sweeps), same conclusion as build123d.

**3. cq_gears — real, confirmed, actively maintained.**
- URL: **https://github.com/meadiode/cq_gears**
- What it is: "CadQuery based involute profile gear generator." Requires the CadQuery *dev* version (not 2.1) + NumPy.
- Gear types supported: spur, helical, herringbone, ring gears (helical/herringbone), planetary gearsets, straight and helical bevel gears, and gear racks — a broad set.
- API confirmed (partial): `SpurGear` class, plus a `gear()`/`addGear()` extension on `cq.Workplane` for producing solids; similarly-named classes exist for the other gear types (e.g. bevel, planetary) though I did not pull full constructor signatures for every class.
- Maintenance: last commit **Dec 27, 2024** ("Add addendum_coeff and dedendum_coeff to SpurGear constructor..."), commit history running from Aug 2021 through Dec 2024, 96 stars / 8 forks / 4 open... (stats varied slightly between two fetches, ~96-159 stars, 8-9 forks) — active, not abandoned, but the repo itself self-describes as v0.51 "work in progress... might be unstable."
- License: Apache 2.0.
- Not confirmed published on PyPI under `cq-gears`/`cq_gears` (PyPI project and search pages returned load errors both times I tried — inconclusive, not a confirmed "no").

**4. build123d-specific gear library — real, and a strong match: py_gearworks.**
- URL: **https://github.com/GarryBGoode/py_gearworks** (docs at gggears.readthedocs.io, project apparently renamed/rebranded from "gggears")
- Built directly on **build123d**, optional viz via OCP VSCode/CQ-editor.
- Gear types supported: spur, helical, bevel, cycloid, inside-ring gears. Explicitly **not yet supported**: hypoid, worm, face, crown.
- Confirmed classes: `SpurGear`, `HelicalGear`, `BevelGear`, `CycloidGear`, with a `mesh_to()` method for aligning meshing gears with configurable backlash; supports undercut, profile shift, root/tip fillet, crowning.
- License: Apache 2.0. Maintenance: 71 stars, 8 forks, 7 open issues, 221 commits on main — reasonably active.
- Listed in the community-curated `awesome-build123d` list (github.com/phillipthelen/awesome-build123d) under "Part Libraries and Part Generators," which is where I found it.

**5. bd_warehouse — also build123d-native, narrower scope, confirmed real signatures.**
- Docs: **https://bd-warehouse.readthedocs.io/en/latest/gear.html**, package on PyPI as `bd-warehouse`.
- Only **spur gears** (ISO metric involute), no helical/bevel.
- Confirmed real classes and constructor args (I fetched the actual doc page):
  - `InvoluteToothProfile`, `SpurGearPlan`, `SpurGear` — shared params: `module` (float), `tooth_count` (int), `pressure_angle` (float, typically 14.5 or 20°), optional `root_fillet`, `addendum`, `dedendum`; `SpurGearPlan`/`SpurGear` add `rotation`, `align`, `mode`, and `SpurGear` adds `thickness`.
  - Example from the docs: `SpurGear(module=2, tooth_count=12, pressure_angle=14.5, root_fillet=0.5*MM, thickness=5*MM)`.

**6. Kernel-independent Python involute gear generators — two credible ones found, plus non-Python prior art.**
- **pymadcad** — `https://pymadcad.readthedocs.io/` — a standalone Python CAD kernel (not built on OCCT/CadQuery). Its gear reference page (`https://pymadcad.readthedocs.io/en/latest/reference/gear/`) confirmed real functions: `rackprofile(...)` (rack), `gearprofile(step, teeth, height, offset, asymetry, pressure_angle, resolution)` (spur tooth profile), `spherical_gearprofile(...)` / `bevelgear(...)` (bevel, straight or helical via `helix_angle`), `gearexterior(...)` (supports helical), plus math helpers `involute()`, `involuteat()`, `involuteof()`, `spherical_involute()`. This is a genuinely CAD-kernel-independent, mathematically-explicit involute implementation that could plausibly be ported/adapted.
- **pyGear** — surfaced via search summary as a CAE/CAD preprocessor for involute gears "based on pythonOCC," available on GitHub/SourceForge — **not independently verified this session** (I did not WebFetch its repo directly), so treat as recalled-from-search-snippet only, not confirmed.
- **sphinxxxx's involute gear generator** — surfaced via search as an interactive web tool for involute gear profiles (parametrizes pitch, pressure angle, addendum, profile shift, clearance, backlash) — this is a **JavaScript/web tool, not a Python library**, per the search snippet; not independently fetched/confirmed, and not directly usable as a Python library, only as an algorithmic reference.
- **manim-gearbox**, **yapCAD** — turned up in a search-engine summary as "also provide gear generation functionality" — **found only in an aggregated snippet, not independently verified**; I did not fetch either repo, so I can't confirm gear-type coverage or maintenance for these two.

**7. FreeCAD Gear Workbench — real, mature, confirmed name/URL.**
- Real name/repo: **Gear Workbench**, at **https://github.com/looooo/freecad.gears** (external FreeCAD addon, not core-bundled; installed via FreeCAD's Addon Manager).
- Confirmed supported types: cylindrical involute, involute rack, cylindrical cycloid, cycloid rack, spherical (bevel) involute, crown gear, worm gear, timing gear — plus helical variants, undercut, and fillets.
- License: GPLv3. Maintenance: 347 stars, 114 forks, 403 commits, compatible with FreeCAD ≥1.0 / Python ≥3.8 — clearly mature and actively used.
- The README cites "Elements of Metric Gear Technology" as its technical reference, but the fetched page didn't expose the actual algorithm/implementation details (e.g., whether it's a closed-form involute-parametric approach or a rack-generation/hobbing-simulation approach) — so it's confirmed as a **good candidate reference for the domain math and parameter conventions**, but I could not confirm the exact algorithmic approach from what I fetched, and it is Python+FreeCAD(OCCT)-specific, not directly build123d-usable code (would need porting, not importing).

## Verdict

Solid prior art exists. build123d and CadQuery have **no native gear primitives**, but there are at least three real, actively-maintained open-source options to build on rather than writing involute math from scratch: **py_gearworks** (build123d-native, broadest type coverage: spur/helical/bevel/cycloid/ring), **bd_warehouse.gear** (build123d-native, spur-only but with clean confirmed API), and **cq_gears** (CadQuery-native, broadest type coverage overall including planetary/racks, active through Dec 2024). FreeCAD's Gear Workbench (`looooo/freecad.gears`) is mature and citable for domain math/parameter conventions even though it isn't directly importable into a build123d stack.

---

### Agent R — the actual parametric math: deterministic, instant involute gear tooth generation

## Findings

**1. Involute-of-a-circle parametric equations — CONFIRMED, closed-form, from two independent sources**

- **Wikipedia, "Involute"** — https://en.wikipedia.org/wiki/Involute
  Gives the parametric equations of the involute of a circle:
  `X(t) = r(cos(t+a) + t·sin(t+a))`, `Y(t) = r(sin(t+a) − t·cos(t+a))`, where `r` = base circle radius, `t` = the unwinding/roll angle parameter, `a` = optional phase offset. Directly on point — this is exactly the curve family gear teeth are built from.

- **Wolfram MathWorld, "Circle Involute"** — https://mathworld.wolfram.com/CircleInvolute.html
  Independently gives the identical equations (with `a` = base radius): `x = a(cos t + t sin t)`, `y = a(sin t − t cos t)`, plus arc-length `s(t)=½at²` and curvature `κ(t)=1/(at)`. Two independent, reputable sources agree exactly on the formula — this is as solid as citation gets for the base curve.

**2. Gear tooth design equations (module/teeth/pressure-angle → geometry) — CONFIRMED, closed-form**

- **tec-science, "Geometry of Involute Gears"** — https://www.tec-science.com/mechanical-power-transmission/involute-gear/geometry-of-involute-gears/
  Gives the direct sizing relations: pitch diameter `d₀ = m·z`, circular pitch `p₀ = m·π`, `cos(α₀) = d_b/d₀` (base circle from pressure angle), addendum `h_a = m`, dedendum `h_d = m + c`, tip/root diameters `d_a = m(z+2)`, `d_d = m(z−2)−2c`. All direct algebraic evaluations from `m`, `z`, `α₀`.

- **tec-science, "Calculation of Involute Gears"** — https://www.tec-science.com/mechanical-power-transmission/involute-gear/calculation-of-involute-gears/
  This is the most directly relevant hit. It gives the **involute function** `inv(α) = tan(α) − α`, the base-circle diameter `d_b = m·z·cos(α₀)`, and — critically — the **tooth-thickness-at-any-radius formula**: `s = d·(s₀/d₀ + inv(α₀) − inv(α))`, with `s₀ = m·(π/2 + 2x·tan α₀)`. This is exactly the equation used to compute, at each radius along the tooth flank, the angular half-thickness needed to place/mirror the involute curve into a full tooth — and it is stated to be a **direct, non-iterative** evaluation (you get `α` at a given diameter from `cos α = d_b/d`, no search needed).
  It also explicitly flags where iteration *does* enter gear math: **the reverse/inverse of the involute function has no closed form** (`inv(α)` is not algebraically invertible), so solving for an *unknown operating pressure angle* (e.g., when computing the actual mesh center-distance of two profile-shifted gears from `inv(α_b) = 2(x₁+x₂)/(z₁+z₂)·tanα₀ + inv(α₀)`) genuinely requires Newton's method. This is a meshing/center-distance problem, **not** a single-tooth profile-generation problem.

- **KHK Gears technical reference** — https://khkgears.net/new/gear_knowledge/gear_technical_reference/involute_gear_profile.html and https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html
  Confirms the same formula family from an industry (Japanese gear manufacturer) reference: `inv α = tan α − α`, `p_b = π·m·cos α`, addendum `h_a = 1.00m`, dedendum `h_f = 1.25m` (standard, non-profile-shifted case), base diameter `d_b = d·cos α`. Cites **JIS B 1701** as the governing standard, not AGMA.

**3. Standards referenced**

- **ISO 53:1998** is cited by Wikipedia's "Involute gear" article (https://en.wikipedia.org/wiki/Involute_gear) as the standard behind the tooth-proportion diagram shown there.
- **JIS B 1701** is cited by both KHK pages as the standard defining module/tooth-profile dimensions.
- **AGMA**: Wikipedia's "Gear" article (https://en.wikipedia.org/wiki/Gear) confirms AGMA/ANSI standards exist and are cited in its footnotes ("the page cites 'ANSI/AGMA' standards in footnotes"), and Wikipedia's AGMA article (https://en.wikipedia.org/wiki/American_Gear_Manufacturers_Association) confirms AGMA is ANSI-accredited to write all U.S. gearing standards (terminology, dimensions, tolerances). However, I could **not** pull a specific AGMA standard number (e.g., AGMA 908 or 917) from a page I actually fetched — I recall from general knowledge that AGMA 908-B89 ("Geometry Factors for Determining the Pitting Resistance and Bending Strength of Spur, Helical and Herringbone Gear Teeth") and AGMA 2001 cover related tooth geometry/strength standards, but **that specific number is recalled, not verified this session** — do not treat it as confirmed. `sdp-si.com`'s "Elements of Metric Gear Technology" handbook (a well-known free closed-form gear design reference) redirected (HTTP 307) and I did not get its content, so I'm not citing it.

**4. Is profile generation genuinely closed-form / O(1) per tooth?**

Yes, per what was actually retrieved: evaluate `x(t) = r_b(cos t + t sin t)`, `y(t) = r_b(sin t − t cos t)` for `t` from 0 up to the value corresponding to the addendum radius (`t_max` from `cos(α_a) = r_b/r_a`, `t_max = tan α_a` — direct, no search), mirror the flank using the closed-form tooth-thickness-angle formula from tec-science's calculation page, then array both flanks around the gear at `2π/z` spacing for `z` teeth. Every step here is direct algebraic/trig evaluation — no root-finding. The one place standard gear engineering genuinely needs Newton's-method iteration is inverting `inv(α)` to solve for an *operating* pressure angle in center-distance/meshing problems with profile shift — a separate concern from generating a single tooth's shape from `(m, z, α, addendum, dedendum)`.

## Verdict

Solid prior art exists for this sub-question: the involute-of-a-circle parametric equations are confirmed identically by two independent authoritative sources (Wikipedia, MathWorld), and the standard closed-form gear-tooth sizing/thickness equations (module → base circle → tooth thickness at radius via the involute function) are confirmed by two independent gear-engineering references (tec-science, KHK), with the one genuinely iterative sub-problem (inverse involute / operating pressure angle) clearly identified and shown to be irrelevant to basic per-tooth profile generation. "Instantly generated" (O(1)-per-point, direct evaluation, no simulation/optimization) is realistic and matches the real math.

---

### Agent S — gear TRAINS: drivetrain topology, ratio chains, and multi-gear interaction representation

## Findings — Gear Trains (multi-gear ratio/meshing representation)

**Caveat on method:** WebSearch was unavailable all session — the shared session budget (200/200) was already exhausted before my first query ran, and every WebSearch call failed immediately with a budget error. All findings below come from WebFetch hitting specific URLs directly. I'm reporting only URLs that actually returned content; guessed URLs that 404'd are listed at the bottom for transparency.

### 1. Simple gear train ratio
**URL:** https://en.wikipedia.org/wiki/Gear_train (fetched)
- Speed ratio: `R_AB = |ω_A|/|ω_B| = r_B/r_A = N_B/N_A`
- Torque/mechanical advantage: `MA = T_B/T_A = N_B/N_A`
- Confirms the standard inverse-teeth-ratio relationship. Directly on-topic.

### 2. Compound gear train ratio (idler cancellation → product formula)
**URL:** https://en.wikipedia.org/wiki/Gear_train (fetched, `#Compound_gear_train`)
- Worked 3-gear example (A→I→B): `R_final = R_AI · R_IB = (N_I/N_A)·(N_B/N_I) = N_B/N_A` — shows idler teeth cancel.
- Page did not state the general "product of driven teeth / product of driving teeth" formula verbatim in the extracted text, but the stage-multiplication principle it demonstrates is exactly that formula's derivation (overall ratio = product of each stage's driven/driving ratio). I could not independently verify a textbook page stating the general product formula explicitly this session — treat the general multi-stage product formula as consistent with what Wikipedia shows, not as a separately-cited direct quote.

### 3. Planetary/epicyclic ratio — Willis equation
**URL:** https://en.wikipedia.org/wiki/Epicyclic_gearing (fetched)
- Core Willis relation: `N_s·ω_s + N_r·ω_r = (N_s + N_r)·ω_c`
- Carrier fixed: `ω_s/ω_r = −N_r/N_s`
- Ring fixed: `ω_s/ω_c = 1 + N_r/N_s`
- Sun fixed: `ω_r/ω_c = 1 + N_s/N_r`
- Matches standard epicyclic-train theory (sun/planet/ring + carrier, tabular/Willis method). Directly on-topic, confirms the exact formula shape asked about.

### 4. Center distance (meshing constraint)
**URL:** https://khkgears.net/new/gear_knowledge/gear_technical_reference/calculation_gear_dimensions.html (fetched)
- `a = m(z₁ + z₂)/2` — i.e. `center distance = module·(teeth1+teeth2)/2`, exactly the formula the question asked me to confirm. KHK is a real gear-manufacturer technical reference, a solid citation.
- Also got the same relation independently from the Wikipedia gear-train page (`center distance = r_A + r_B`, with `p_A = p_B` pitch-compatibility giving `r_B/r_A = N_B/N_A`) — two independent sources agree.

### 5. Parametric multi-gear (train) generators — the actual sub-question of interest

**cq_gears** — real, found at **https://github.com/meadiode/cq_gears** (note: `github.com/CadQuery/cq_gears` — the org a previous agent may have assumed — 404's; correct owner is `meadiode`).
- Confirmed gear classes: SpurGear, HelicalGear, HerringboneGear, RingGear (helical/herringbone), straight & helical BevelGear, GearRack, and **"Planetary gearsets" explicitly listed as a supported type**, with example imagery (planetary01.png/02.png) and a dedicated example notebook `examples/ring_gears_and_planetary_gearsets.ipynb`.
- Confirmed it supports positioning multiple meshing gears (a "4 meshing gears" array example using CadQuery's `rarray()`/`addGear()`, spaced by pitch diameter) and exposes pre-computed pitch radius (`r0`) so a caller can position gears correctly.
- **Not confirmed:** I could not retrieve the actual notebook code or the library's source (`planetary.py`) — two direct fetch attempts 404'd (wrong guessed paths/filenames). So I can confirm the *capability exists and is documented as supported*, but I could not verify from source whether center-distance/ratio computation is done *automatically* by the library versus left to the user to wire up manually — the README text specifically suggested the latter ("documentation doesn't explicitly detail automatic center-distance computation or gear ratio calculations — these appear to be user-managed through manual positioning and parameter referencing").

**FreeCAD Gears workbench** — real, found at **https://github.com/looooo/freecad.gears** (fetched).
- Only generates individual gears (involute, cycloid, bevel, worm, timing, lantern, crown). No evidence in the README of train/planetary-assembly generation, automatic center-distance, or ratio computation across multiple gears. This is single-gear tooth geometry only, same category as what "another agent" apparently already covered — not new prior art for trains.

**Not found:** No standalone open-source "parametric gear train generator" or "planetary gearbox generator" project beyond cq_gears was located — WebSearch being dead meant I couldn't cast a wide net (e.g., PyPI search, GitHub topic search all failed to load or returned no content). This is a real gap in my coverage, not a confirmed "nothing exists" — I did not get to search broadly.

### Failed lookups (reported for honesty, not used as findings)
- `https://github.com/CadQuery/cq_gears` — 404 (wrong org)
- `https://raw.githubusercontent.com/meadiode/cq_gears/master/examples/planetary_gearset.py` — 404 (wrong filename)
- `https://raw.githubusercontent.com/meadiode/cq_gears/master/cq_gears/planetary.py` — 404 (couldn't verify exact source path)
- `https://www.tec-science.com/.../planetary-gear-ratio/` and `/planetary-gear-ratio-of-different-designs/` — both 404 (guessed slugs, wrong)
- `https://pypi.org/search/?q=planetary+gear+train` — page didn't load real content for the fetcher
- All WebSearch queries — session budget exhausted before any ran

### Verdict
**Partial prior art exists, not full prior art.** The math side is solidly confirmed from real sources: simple/compound train ratio (Wikipedia), Willis-equation planetary ratio (Wikipedia), and the center-distance meshing constraint `a = m(z₁+z₂)/2` (KHK Gears + Wikipedia, two independent confirmations). On the generator side, **cq_gears is real, documented, and explicitly claims planetary-gearset support with multi-gear positioning helpers** — the closest thing to a parametric multi-gear-train generator I could verify — but I could not confirm from source code whether it *automatically* enforces the ratio/center-distance constraints versus requiring the caller to compute and pass them in manually, and I could not verify a compound-train (non-planetary) generator or confirm no better tool exists, since WebSearch was unavailable for the entirety of this task.

---

### Agent T — existing full drivetrain / gearbox parametric generators — prior art for the whole pipeline

## Research Findings: Prior Art for Full Parametric Drivetrain/Gearbox Generators

**Bottom line up front:** No open-source tool combines (a) real involute tooth geometry generation and (b) automatic multi-gear positioning/meshing/ratio computation into one instant, non-iterative pipeline. Every real tool found does one half or the other, or does both but only for a single gear pair (not a full train or planetary system). Commercial tools (KISSsoft, GearTrax, Gearotic) get closer but are calculation-suites or single-component generators, not "give me RPM-in/RPM-out and get a fully meshing assembly" generators.

---

### Open-source libraries (geometry generation)

**1. py_gearworks (formerly gggears)** — github.com/GarryBGoode/py_gearworks, gggears.readthedocs.io
- Built on build123d/OCCT. Generates real involute (and cycloid) tooth geometry.
- Does handle **two-gear pair positioning/meshing** — README shows moving gear 2 into mesh with gear 1 along an axis, with correct center distance and optional backlash.
- Explicitly lists "Planetary drive design" under **planned/upcoming features** — not implemented yet. No support for arbitrary N-gear trains, no RPM/torque/ratio-driven auto-layout.
- Closest thing found to "combines both halves" — but only for a single meshing pair, and is explicitly "early development, no API stability yet."

**2. bd_warehouse `gear` module** — bd-warehouse.readthedocs.io/en/latest/gear.html
- Generates ISO metric involute spur gears (`InvoluteToothProfile`, `SpurGearPlan`, `SpurGear` classes) only.
- Gives you the *formula* for center distance (`module·(n₀+n₁)/2`) but does not automatically position or assemble gears — that's left to the user. Single-gear-type geometry tool, not an assembly generator.

**3. FreeCAD Gear Workbench (freecad.gears, github.com/looooo/freecad.gears)**
- Confirmed via the actual repo (wiki.freecad.org itself is bot-walled by Anubis, so verified from the source repo instead): generates individual gears across 8-9 categories (involute, cycloid, bevel, worm, timing, crown, lantern, racks), with helical/double-helical/shifting/undercut options.
- Explicitly does **not** auto-calculate center distances or assemble complete gear trains/transmissions — user positions everything manually. This directly answers the "single gears only vs. full trains" question: **single gears only**.

**4. pyGear** — sourceforge.net/projects/pygear
- pythonOCC-based CAE/CAD preprocessor for involute spur/helical gears (external and internal), simulates actual hobbing-tool kinematics for manufacturing-accurate profiles. Alpha status, last updated 2023, single-gear generation only, no train/assembly logic.

**5. python-gearbox** (PyPI) — AGMA-2101/ISO-6336 stress calculation + single-tooth geometry export to FEA tools (MATLAB/ABAQUS/ANSYS). Calculation/analysis tool, not a multi-gear CAD generator. Early-stage (0.1.2.a, 2015).

**6. hyperair/planetary-gears** (GitHub, OpenSCAD) and multiple Thingiverse/Printables/MakerWorld "parametric planetary gearbox" OpenSCAD scripts — these do produce a real meshing planetary assembly (sun/planets/ring) parametrically, but they're maker-community OpenSCAD scripts sized around specific use cases (e.g., NEMA stepper mounts), not general-purpose "give me ratio+torque, get correct module/teeth/geometry" engineering generators. Could not verify a documented computation pipeline (README detail wasn't retrievable beyond "parametric planetary gear generator").

### Commercial software (confirmed to exist, for context — not integration candidates per the task)

- **KISSsoft** (kisssoft.com, owned by Gleason) — confirmed: full commercial gearbox calculation/sizing/optimization suite with a "System Module" for powertrain modeling, plus manufacturing/tool-design features. Analysis/optimization-focused, not stated to auto-generate 3D geometry as its core (calculation-first tool).
- **GearTrax** (Camnetics, camnetics.com/geartrax) — SolidWorks/Inventor/Solid Edge plugin. Generates solid models for spur/helical/bevel/worm gears, splines, sprockets, pulleys, cycloidal drives from basic specs (teeth, module, pressure angle). This is real geometry generation integrated in CAD, but it produces **individual components** you place yourself — not evidence of automatic full-train layout from RPM/ratio inputs.
- **Gearotic Motion** (gearoticmotion.com) — hobbyist/CNC-oriented gear template generator (DXF/STL/3D solids), popular for scrollsaw/automata gears. Component generator, not a train synthesizer.
- **MITCalc** (mitcalc.com) — Excel-based engineering calc suite (ANSI/ISO/DIN/BS/JIS standards) with 2D/3D CAD export (e.g. AutoCAD). Calculation-first, spreadsheet-driven.

### Academic work on "automated gearbox synthesis"

- **"Automated requirements-driven design synthesis of gearboxes with graph-based design languages"** (Holder & Rudolph, Springer, 2019, doi 10.1007/s10010-019-00322-z) — title/abstract snippet confirms it addresses exactly this: automated gear synthesis **and** automated 3D arrangement of gearset parts via graph-based design languages. Full text is paywalled (Springer login-gated); I could not retrieve the actual content to verify how "instant/deterministic" vs. search-based the method is. This is the single most on-topic academic hit found, but unverified in detail this session.
- **"A Method and Software Tool for Automated Gearbox Synthesis"** (ResearchGate, publication 267488322) — snippet: "a new method for automated gearbox design, tailored for integration within an existing commercial gearbox analysis tool." Full page returned HTTP 403 (blocked), so content unverified beyond the search snippet.
- **"Efficient loss modeling for automated computational design synthesis"** (ScienceDirect) — snippet suggests fast parametric loss models for gearbox components as part of a synthesis pipeline; not independently verified beyond snippet.
- **"Deep Generative Model for Mechanical System Configuration Design"** (arxiv.org/pdf/2409.06016v3) — verified via full-text fetch: this is explicitly an **AI/learned generative model** (trained on a synthetic dataset) for gear-train synthesis, not a closed-form/deterministic method. Directly the kind of approach your question says you're trying to avoid — useful as a negative data point confirming that recent "automated gear train design" research leans AI/generative rather than deterministic-instant.

### Direct answer to the "combines both halves" question

Across everything retrieved this session:
- Tools that do real involute geometry + basic 2-gear meshing in one pipeline: **py_gearworks**, arguably (partial, 2-gear-only, planetary explicitly not-yet-supported).
- Tools that do geometry only, no train/positioning logic: FreeCAD Gear Workbench, bd_warehouse gear, pyGear, GearTrax (per-component).
- Tools/software that do transmission-level calculation (ratios, stresses, standards compliance) without generating a full meshing 3D assembly: python-gearbox, KISSsoft, MITCalc.
- Nothing found — open-source or in the papers whose full text I could access — takes {input RPM, output RPM/ratio, torque, gear count} and deterministically emits a complete, correctly-meshing, real-geometry multi-gear (let alone planetary) assembly in one instant closed-form pass. The academic work that claims to do the closest thing (Holder & Rudolph 2019) is paywalled and unverified in detail; the one AI paper found (arxiv 2409.06016) explicitly uses a trained generative model, not closed-form computation, which is the opposite of what's being asked about.

**Verdict: No solid prior art exists for a complete, open, deterministic pipeline that does both halves (real tooth geometry + automatic multi-gear/planetary meshing and positioning) from a small RPM/ratio/torque input set — every real tool/library found does one half well at most, commercial suites are calculation-first not geometry-generation-first, and the one academic paper that claims the full scope is paywalled and unverifiable from this session's access.**

---

