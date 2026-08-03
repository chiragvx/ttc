# Ribs, gussets, grids, and routed structural/wiring channels — prior-art research

**Date:** 2026-08-03
**Status:** Exploratory research only — nothing here is built or scheduled. Captured so future work
doesn't re-derive it from scratch.

## Context / the question being evaluated

How can ribs, gussets, and grid/lattice structures — plus rigid structural inserts (carbon fiber
rods, steel/aluminium tubes/spars) or wiring channels passing through complex geometry — be
reconstructed easily using build123d, **mostly without needing an AI present at all times**? What does
build123d already offer natively, and what other deterministic/algorithmic experiments and prior art
exist?

Four parallel research agents (Sonnet 5, via the Workflow tool) investigated: (I) build123d/CadQuery's
native array/pattern/sweep/shell/loft primitives, (J) deterministic (explicitly non-ML) algorithms for
generating ribs/lattices/infill from a shell — including whether SIMP topology optimization counts
as "AI" (it does not), (K) automatic gusset/joint-reinforcement generation, (L) routing rigid inserts
or wiring channels through complex geometry. A fifth agent synthesized the four raw reports. Citation
status (directly fetched vs. search-snippet-only vs. recalled/unverified) is preserved exactly as each
agent reported it. No URL below was invented.

**Headline finding**: every one of the four sub-questions has a genuine, established, deterministic
(non-AI) algorithm or shipped commercial feature behind it — consistent with build123d's own
templated-parametric philosophy. Lattices/infill are the most solved (real CAD-kernel bridges into
build123d/CadQuery already exist: **Microgen**, **dl4to4ocp**). Gusset *geometry* and routing
*pathfinding+sweep* are each solved as separate primitives that need connective code written, not new
algorithmic invention. Ribs-from-a-shell and load-based gusset *sizing* are the two spots with a real
optimization/FEA-based inference step (SIMP, ESO/BESO, the Uniform Force Method, principal-stress rib-
flow) — still not AI, but not a one-line call either.

---

## Synthesis (read this first)

# Ribs, gussets, grids, and routed inserts in build123d — synthesis of 4 research passes

Note on method: everything below is reorganized/deduplicated from 4 independent research sessions. Every URL is copied verbatim from the report that found it — I did not verify, modify, or re-fetch any of them myself. Where a report flagged something as unverified/secondhand, I've kept that flag. Where two reports disagree, it's called out explicitly rather than resolved silently.

---

## 1. What build123d/CadQuery already offer natively

**Patterns (arrays of locations):**
- build123d: `GridLocations(x_spacing, y_spacing, x_count, y_count, align=...)`, `PolarLocations(radius, count, start_angle=0.0, angular_range=360.0, rotate=True, endpoint=False)`, `HexLocations(radius, x_count, y_count, major_radius=False, align=...)`, `Locations(*pts)` — all confirmed as context managers via build123d.readthedocs.io (`builder_api_reference.html`, `operations.html`, `examples_1.html`).
- CadQuery: `Workplane.rarray(xSpacing, ySpacing, xCount, yCount, center=True)`, `Workplane.polarArray(radius, startAngle, angle, count, fill=True)` — confirmed via cadquery.readthedocs.io.
- `HexLocations` is the closest thing to a native "lattice" primitive in either library — but it places *points* at hex-packed positions, it does not generate honeycomb *walls*. No community lattice helper lives inside build123d itself.

**Sweep / shell / offset / loft (real, quoted signatures):**
- build123d: `offset(objects=None, amount=0, openings=None, kind=Kind.ARC, side=Side.BOTH, closed=True, min_edge_length=None, mode=Mode.REPLACE)` (this *is* the shell op), `sweep(sections=None, path=None, multisection=False, is_frenet=False, transition=Transition.TRANSFORMED, normal=None, binormal=None, clean=True, mode=Mode.ADD)`, `loft(sections=None, ruled=False, clean=True, mode=Mode.ADD)`.
- CadQuery: `sweep(path, sweepAlongWires=False, makeSolid=True, isFrenet=False, combine=True, clean=True)`, `shell(thickness)`, `loft(filled=True, ruled=False, combine=True)`. No dedicated `offset`/`offset2D` was surfaced for CadQuery in that pass.

Neither library ships a purpose-built "add ribs to this surface" or "add a gusset" function — both are compositions you write on top of the primitives above.

**Sweeping along an arbitrary 3D path** — a second report independently confirmed and added nuance here:
- build123d: define a 3D path with `Spline(pt1, pt2, ..., tangents=..., tangent_scalars=...)`, position cross-sections along it with the `^` operator (`path ^ 0.5`), then `sweep(sections, path=path, multisection=True)`. Confirmed via the library's own Handle and Tea Cup examples (build123d.readthedocs.io/en/stable/examples_1.html) — described as first-class and working.
- CadQuery: same base pattern (`Workplane("XZ").spline(pts)` → `Workplane("XY").circle(r).sweep(path, isFrenet=True)`), confirmed via github.com/CadQuery/cadquery/blob/master/examples/Ex023_Sweep.py. **But** genuinely non-planar 3D-spline sweeps are a known rough edge in CadQuery specifically: open issue github.com/CadQuery/cadquery/issues/1860 (non-uniform cross-section / wrong depth on a true 3D path) and github.com/CadQuery/cadquery/issues/507 (multisection tapered sweep along a 3D path only varies in one coordinate). build123d, being closer to raw OCP, was described as less affected.

**Real projects found on top of these primitives:**
- *Ribs*: only one concrete hit — build123d's own keycap tutorial, which hand-builds a rib pair (two thin rectangles + a circle, `extrude(until=Until.NEXT)`). No general "ribbed panel following a surface" generator exists in either ecosystem.
- *Gussets*: `archimedes-market/parametric-bracket-library` (github.com/archimedes-market/parametric-bracket-library) — a CadQuery library of an L-bracket, gusseted L, U-bracket, Z-bracket, shelf bracket, and right-angle plate. Its `brackets/l_gusset.py` was fetched directly and quoted: builds a right-triangle profile with `Workplane("XZ").polyline(pts).close().extrude(gusset_t)` then `bracket.union(gusset)`. Also `CadQuery/cadquery-contrib`'s `Reinforce_Junction_UsingFillet.py` (fillet-based joint reinforcement, adjacent but not a true gusset web).
  - **⚠️ Flagged conflict:** a separate research pass (gusset-focused) searched for exactly this kind of thing and reported: *"a parametric library of 6 production-grade mounting brackets including a gusseted L-bracket, built in CadQuery" recurred verbatim across three separate searches but no actual URL was ever produced for it... flagging as likely a fabricated/synthesized search-snippet... excluded from citations."* That description (6 bracket types, one of them a gusseted L-bracket) matches the archimedes-market find almost exactly. One pass fetched a real URL and quoted real code from it; the other pass encountered the same-sounding claim with no attached URL and treated it as probably fabricated. I can't resolve this myself — I did not fetch anything this session — so treat `archimedes-market/parametric-bracket-library` as the specific, checkable claim (it has a URL and quoted code) but be aware another independent search for the same-sounding library came up empty/suspicious.
- *Lattices/TPMS* — the strongest native-adjacent prior art:
  - **LatticeQuery** (github.com/jalovisko/LatticeQuery) — "based on the CadQuery GUI editor," beam lattices (simple cubic, BCC, FCC, S-FCC, BCCz, FCCz, Diamond, Rhombicuboctahedron, Truncated cube) and TPMS (Gyroid, Schwarz Primitive, Schwarz Diamond), variable per-region beam thickness.
  - **cqMore** `examples/gyroid.py` (github.com/JustinSDK/cqMore, fetched raw) — evaluates the gyroid implicit function on a grid, runs `skimage.measure.marching_cubes`, feeds verts/faces into `Workplane().polyhedron(points, faces)`. Real, but goes through meshing, not a native CAD primitive.
  - **microgen** (github.com/3MAH/microgen) — built on OCCT via CadQuery (`cadquery-ocp-novtk`); octet-truss/honeycomb + TPMS (gyroid, Fischer-Koch) + periodic meshing.
  - **Pyroid** (github.com/tazomatalax/Pyroid) — standalone gyroid/STL tool; its CadQuery/build123d backend was **not verified** (source not fetched).

---

## 2. Deterministic algorithms for ribs/lattices/infill from a shell

**Topology optimization (SIMP) — confirmed classical/deterministic, not ML:**
SIMP is density-based and gradient-based (Optimality Criteria / MMA solvers on FEA sensitivity fields), confirmed via [The SIMP method in topology optimization](https://www.researchgate.net/publication/269224546_The_SIMP_method_in_topology_optimization_-_Theoretical_background_advantages_and_new_applications). Real, open implementations:
- Sigmund/Aage's 99-line MATLAB lineage — [DTU TopOpt 99-line code](https://www.topopt.mek.dtu.dk/apps-and-software/a-99-line-topology-optimization-code-written-in-matlab), extension paper [arXiv 2005.05436](https://arxiv.org/pdf/2005.05436).
- **ToPy** — [github.com/williamhunter/topy](https://github.com/williamhunter/topy) (Python SIMP for compliance/mechanism/heat-conduction; stable release is Python-2-only). No CAD-kernel integration.
- **zfergus/topopt** — [github.com/zfergus/topopt](https://github.com/zfergus/topopt) (MMA/OC/GA solvers, outputs a density array, no CAD integration); related, unfetched: [TopOpt-MMA-Python](https://github.com/arjendeetman/TopOpt-MMA-Python).

**CAD-kernel bridges — this is the load-bearing finding for build123d specifically:**
- **dl4to4ocp** (github.com/yeicor-3d/dl4to4ocp) runs topology optimization *directly on OCP-based build123d/CadQuery solids* — build green/red/gray solids in build123d, it optimizes, exports the result. It's listed on build123d's own docs: *"Library that helps perform topology optimization on your OCP-based CAD models (CadQuery/Build123d/…) using the dl4to library"* ([build123d external tools](https://build123d.readthedocs.io/en/latest/external.html)). Caveat: the underlying engine [dl4to](https://github.com/dl4to/dl4to) is architecturally PyTorch/autograd-based and its main selling point is NN integration, though it does implement classical SIMP usable with zero neural-network involvement — you'd be using only that sub-mode.
- **Microgen** — again confirmed here as a real, deterministic, non-ML, CAD-kernel-integrated (CadQuery/OpenCascade) lattice/TPMS/Voronoi-polycrystal generator, with Gmsh/MMG for periodic meshing ([github.com/3MAH/microgen](https://github.com/3MAH/microgen), [docs](https://microgen.readthedocs.io/en/latest/)).

**Other deterministic infill/lattice tools:**
- Gyroid/TPMS via implicit-surface (F-Rep) isosurface threshold — not ML: [ScienceDirect: gyroid load-path design](https://www.sciencedirect.com/science/article/abs/pii/S2214860424006328), [ScienceDirect: gyroid FGM cellular structures](https://www.sciencedirect.com/science/article/abs/pii/S0010448518300381).
- **Voronizer** (github.com/tjwill95/voronizer) — Voronoi-foam infill on STL, GPL-3.0, Python/CUDA, mesh-based not B-rep.
- **Voro++** ([math.lbl.gov/voro++](https://math.lbl.gov/voro++/)) — mature C++ 3D Voronoi tessellation library.
- **TPMSgen** ([github.com/albertforesg/TPMSgen](https://github.com/albertforesg/TPMSgen)) — recalled from a search snippet only, not fetched/verified.
- **PySLM** — actively confirmed via docs fetch to do slicing/hatching/support generation only; it does **not** do lattice/infill/rib generation ([pyslm.readthedocs.io](https://pyslm.readthedocs.io/)).

**Rib/stiffener placement from a loaded shell — closest direct match to the question:**
- "Rib‑reinforced Shell Structure" (Li, Zheng, You, Yang, Zhang, Liu — CGF/Pacific Graphics 2017): FEA → principal-stress field → cross-field-aligned quad mesh → initial rib network → rib-flow-optimization simplification → cross-section optimization. Fully deterministic/geometric, no ML. **Caveat: full-text PDF fetch failed (connection refused)** — this description rests on a WebSearch summary, not a direct read. [Wiley abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.13268), [Semantic Scholar](https://www.semanticscholar.org/paper/Rib%E2%80%90reinforced-Shell-Structure-Li-Zheng/da8700aeb85ffab6371d417a4d42ab8d88097fd4).
- Related (titles/venues confirmed, not fetched in full): [Principal stress field-guided rib generation](https://www.sciencedirect.com/science/article/abs/pii/S0010448525001162), [Reinforcement of General Shell Structures, ACM TOG](https://dl.acm.org/doi/10.1145/3375677), [Automated rib location/optimization 2002, Springer](https://link.springer.com/article/10.1007/s00158-002-0270-7) (paywalled).
- **AUTORIB** (Siemens/Genesis, commercial) — real, shipped, deterministic rib-candidate generation along mesh edges + sizing/pruning: [Siemens community article](https://community.sw.siemens.com/s/article/33481-designing-rib-stiffeners-the-easy-way-with-autorib).
- Venation-inspired (leaf-vein growth simulation) stiffener layout — biomimetic but deterministic, title/venue only: [scientific.net/JBBTE.18.1](https://www.scientific.net/JBBTE.18.1).
- Several more gradient/evolutionary stiffener-layout papers, titles/URLs real but not individually fetched: [Springer 2021 component-based](https://link.springer.com/article/10.1007/s00158-021-02945-9), [Springer 2020 concurrent topo+cross-section](https://link.springer.com/article/10.1007/s10409-020-01034-2), [Springer 2021 modular stiffeners](https://link.springer.com/article/10.1007/s00158-021-03081-0).

**Found nothing / explicit gap:** none of ToPy, zfergus/topopt, Voronizer, or the 99-line SIMP code have a built-in bridge into build123d/CadQuery/OCCT. Converting a density field into a usable B-rep solid generally requires marching-cubes/mesh reconstruction, and no off-the-shelf pipeline for *that specific step* (for these tools) was found — `dl4to4ocp` is the one exception that already closes this loop.

---

## 3. Automatic gusset/joint-reinforcement generation

**Commercial rule-based auto-gusset tools (real, shipped, algorithm mostly undisclosed):**
- **Autodesk Advance Steel** — literal "Automatic" checkbox for gusset plates; algorithm not disclosed. [help.autodesk.com](https://help.autodesk.com/cloudhelp/2015/ENU/ASD-Steel/files/GUID-2E8401F0-DEB6-4DE8-A297-335A441E911C.htm).
- **Tekla Structures** — named parametric components ("Bolted gusset," "Gusseted cross," "Gusset+T") drive plate/bolt/weld/clip-angle generation from a `joints.def` parameter file; internal geometry algorithm not public. [support.tekla.com links: bracing simple gusset](https://support.tekla.com/doc/tekla-structures/2025/det_bracing_simple_gusset_conns), [bolted gusset](https://support.tekla.com/doc/tekla-structures/2026/det_bracing_bolted_gusset), [gusseted cross](https://support.tekla.com/doc/tekla-structures/2026/det_bracing_gusseted_cross), [gusset+T](https://support.tekla.com/doc/tekla-structures/2025/conn_1_help_gusset_plus_t).
- **IDEA StatiCa Connection** — gusset plate as a "manufacturing operation" resolved into an auto-generated CBFEM mesh, but the *placement/sizing* still looks user-parametrized, not derived purely from member geometry — the "fully automatic" framing is **unverified** (page gave no algorithm detail on fetch). [ideastatica.com](https://www.ideastatica.com/support-center/gusset-plate-design-in-idea-statica-connection), [technical PDF, not text-extracted](https://assets-us-01.kc-usercontent.com/1ca05609-4ad1-009e-bc40-2e1230b16a75/5b5b2544-b78c-4e08-9816-c0c547d03146/Gusset_plate_connections_in_IDEA_StatiCa_Connection.pdf).
- **RISAConnection** — auto-limits gusset dimensions per AISC 14th-ed. equations under the Uniform Force Method; tapered-cut parametric definition. [blog.risa.com tapered gusset](https://blog.risa.com/post/tapered-gusset-plates-using-custom-angle), [blog.risa.com gusset tag](https://blog.risa.com/tag/gusset-plate).
- **Inventor Frame Generator** — confirmed gap: users have requested native gusset support since 2002, still absent ([forum thread](https://forums.autodesk.com/t5/inventor-ideas/gussets-for-frame-generator/idi-p/4704127)); filled by third-party **SolidSteel parametric** plugin (select bolted + welded face → preview → generate from presets; proprietary, algorithm undocumented). [klietsch.com](https://klietsch.com/inventor/?m=%2FSolidSteelparametric%2FFunctions&lang=en).

**The one publicly documented closed-form algorithm — Uniform Force Method (UFM):**
Thornton 1991, in the AISC Manual since 1992. Given beam depth, column geometry, brace angle, work-point, it computes eccentricities/forces at the gusset-to-beam and gusset-to-column interfaces such that no moment exists at either interface. [AISC EJ derivation](https://ej.aisc.org/index.php/engj/article/view/1341), [AISC: Designing Compact Gussets with UFM](https://www.aisc.org/Designing-Compact-Gussets-with-the-Uniform-Force-Method). **Important limit: UFM gives interface forces/eccentricities, not a full boundary polygon** — it's explicitly criticized ("sometimes results in oddly shaped or disproportionately large gusset plates"), with follow-on work trying to fix the boundary output ([ScienceDirect, abstract only, 403](https://www.sciencedirect.com/science/article/abs/pii/S0141029618304334)).

**Whitmore section** (30° dispersion rule) — a genuinely deterministic geometric construction, but it defines a *capacity-check region*, not the plate's physical boundary. [eng-tips thread](https://www.eng-tips.com/threads/gusset-plate-whitmore-section.479700/), [IOP conference PDF](https://iopscience.iop.org/article/10.1088/1757-899X/852/1/012004/pdf).

**Deterministic shape/topology optimization of gussets (not instant, iterative):**
- ESO/BESO element-removal shape optimization of gusset plates under given loads — deterministic FE-driven, but presupposes the connection topology already chosen. [ResearchGate](https://www.researchgate.net/publication/223388919_Evolutionary_structural_optimization_of_steel_gusset_plates).
- A real research tool combining truss size optimization with per-joint gusset topology optimization (Three.js front end, Scilab+DAKOTA backend, benchmarked against IS 800-2007) — minutes-scale optimization pipeline, not an interactive-plane operation. [arXiv abstract](https://arxiv.org/abs/1512.02881), [PDF](https://arxiv.org/pdf/1512.02881).

**Does gusset generation reduce to a general CAD primitive already in build123d? — Yes, partially, and this is the clearest actionable finding:**
Mainstream parametric CAD already ships a generalized version of this, just not called "gusset":
- **SolidWorks Weldments → Gusset**: select two planar faces → pick profile (triangular/polygonal) + thickness + chamfer → solid constructed automatically. Real, shipped, "two-face + scalars → gusset solid." [GoEngineer writeup](https://www.goengineer.com/blog/solidworks-weldments-corners-gussets-bounding-box), corroborating [GrabCAD tutorial](https://grabcad.com/tutorials/tutorial-gusset-in-weldment-in-solidworks).
- **Fusion 360 Rib/Web command**: sketch one line indicating rib path/thickness; Fusion auto-extends/trims it against surrounding bodies — "you don't have to make the lines go all the way to the bottom plate — Fusion will fill in the gaps itself." [Autodesk tutorial](https://www.autodesk.com/learn/ondemand/tutorial/add-webs-and-ribs-to-solid-bodies), [forum corroboration](https://forums.autodesk.com/t5/fusion-design-validate-document/a-good-way-to-create-ribs/td-p/7203976).
- At the OCCT-kernel level (the same kernel under build123d/CadQuery): `GeomFill_ConstrainedFilling`/n-sided surface fill and `BRepFilletAPI` fillet/chamfer ([OCCT modeling algos overview](https://dev.opencascade.org/doc/overview/html/occt_user_guides__modeling_algos.html), [OCCT boolean ops wiki](https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations)) are the general primitives a gusset-fill would be built on — raw capability, not a packaged "gusset" feature.

**Not found:** no public documentation of Advance Steel's/Tekla's/IDEA StatiCa's actual outline-construction algorithm; no build123d/CadQuery-specific "gusset generator" repo *confirmed by this pass* (see the flagged conflict in Section 1 above with the other pass's archimedes-market find); the only other adjacent hits were a title-only OpenSCAD "parametric joint generator" listing (unfetched) and github.com/YieldingData/GridfinityStructure, which per its own description has "gusset plate **placeholders**" — not a real generator.

---

## 4. Routing rigid inserts / wiring channels through complex geometry

**Commercial CAD routing modules — real, but manual/assisted, not automatic pathfinding:**
- **SOLIDWORKS Routing** — confirmed real add-in; workflow is a user-drawn 3D sketch (line segments, Tab to reorient), tool auto-inserts fittings/elbows at corners and sweeps the profile along the authored path. Manual/assisted, not obstacle-avoiding. [help.solidworks.com (snippet)](https://help.solidworks.com/2025/English/SolidWorks/sldpiping/c_routing_overview.htm), [GoEngineer walkthrough (fetched)](https://www.goengineer.com/blog/solidworks-routing-101-pipe-design).
- **Fusion 360** — no native cable-routing/pathfinding tool (per an Autodesk forum thread: "no current projects underway to support wire harness design in Fusion"). Community add-in **F360WireGenerator** ([github.com/hyweric/F360WireGenerator](https://github.com/hyweric/F360WireGenerator)) generates spline *variations* for slack/appearance between chosen endpoints — not obstacle-aware.

**Academic/algorithmic pipe & harness routing — this is where the real deterministic prior art is:**
- Ship pipe routing (mature literature; grid-decomposed 3D space, A*/GA/ACO/NSGA-II hybrids for collision-free paths around equipment): [IEEE — improved A* + GA](https://ieeexplore.ieee.org/document/9172005/), [Springer — improved GA branch-pipe routing](https://link.springer.com/article/10.1007/s11465-016-0384-z), [ScienceDirect — engine room case study](https://www.sciencedirect.com/science/article/abs/pii/S0957417402000490), [Wiley — NSGA-II + coevolution](https://onlinelibrary.wiley.com/doi/10.1155/2016/7912863), [Springer JMSA 2022 — automated pipe routing](https://link.springer.com/article/10.1007/s11804-022-00269-8). **Verified via search-result titles/snippets only, not full-text-fetched.**
- Aircraft wire-harness/EWIS routing as shortest-path/Steiner-tree, reading/writing CAD geometry directly: [ScienceDirect/CAD journal (403'd, snippet-verified)](https://www.sciencedirect.com/science/article/pii/S0010448523002038), [CEAS Aeronautical Journal — A* to minimize harness weight](https://link.springer.com/article/10.1007/s13272-017-0238-3).
- **Closest single match found**: "Automatic cable routing based on improved pathfinding algorithm and B-spline optimization for collision avoidance" — a **JPS–Theta\*** hybrid for an initial voxel-grid path, refined by an ant-colony-style **RFACOR** optimizer into a smooth B-spline, checked against obstacle point clouds. **Uses OpenCascade** (the same kernel build123d/CadQuery sit on), ingests STEP/XML, validated on an electrical-panel case study. Fetched successfully: [academic.oup.com/jcde](https://academic.oup.com/jcde/article/11/5/303/7810276).
- "Cable route planning in complex environments using constrained sampling" — title only, ResearchGate fetch 403'd, not independently verified. "Projection and Geodesic-Based Pipe Routing Algorithm" — title only, not fetched.

**Wires/channels embedded inside a 3D-printed solid — the closest domain analog to "route through a solid":**
- "Topology-Aware Routing of 3D-Printed Circuits" (TAMS, Univ. Hamburg): converts the printed-object volume into a graph (shape boundary + infill grid + z-connections), runs a **modified A\*** to find a collision-free, printable wire path, emits G-code with the wire embedded. PDF located ([tams.informatik.uni-hamburg.de](https://tams.informatik.uni-hamburg.de/theses/printed-electronics-routing-paper.pdf), also indexed at [ScienceDirect, 403'd](https://www.sciencedirect.com/science/article/pii/S2214860420308952)) but **not independently text-extracted** — this description is secondhand from a search snippet.

**Medial-axis/Voronoi skeleton routing** — generalized-Voronoi-diagram-as-medial-axis-of-free-space is well established for path planning generally ([gamma.cs.unc.edu/VORONOI/FPLAN](https://gamma.cs.unc.edu/VORONOI/FPLAN/fplan.pdf)), and separately computing the medial axis *of a CAD solid* is an established CAD/meshing operation ([arXiv 2411.06471](https://arxiv.org/pdf/2411.06471)). **No case study connecting the two was found** — i.e., no paper using a CAD solid's own medial axis as a routing corridor for a physical insert. Reported as a real gap, not a search failure.

**A usable open-source building block for the "search" half:**
- **pathfinding3D** — actively maintained Python library (fork of `python-pathfinding`), A*, Dijkstra, Best-First, Bi-directional A*, BFS, IDA*, MST, Theta* over 3D NumPy occupancy grids. No CAD awareness of its own. [PyPI](https://pypi.org/project/pathfinding3d/0.4.0), [GitHub](https://github.com/harisankar95/pathfinding3D).

**Explicit gap:** no connection between any of the routing algorithms above and build123d/CadQuery was found anywhere. That integration does not exist in public prior art — it would have to be hand-built (voxelize the solid → run pathfinding3D or the JPS-Theta*/RFACOR pattern → hand waypoints to build123d's `Spline` + `sweep(multisection=True)`).

---

## 5. Bottom-line verdict

Across all four sub-areas, the honest answer is: **most of this can genuinely be built as deterministic, algorithmic generators with no AI inference per instance — but as of what was found this session, none of it is wired into build123d/CadQuery off the shelf. The gap is integration engineering, not a missing algorithm, with one caveat below on gussets/ribs.**

Broken down piece by piece:

- **Grids/lattices/infill — the most solved piece.** SIMP topology optimization is decades-old, gradient-based, and unambiguously non-ML (99-line MATLAB lineage, ToPy, zfergus/topopt). TPMS/gyroid lattices are pure isosurface/implicit-function math. Voronoi infill is classical computational geometry (Voro++, Voronizer). And, unlike the other three areas, **real CAD-kernel bridges into the build123d/CadQuery ecosystem already exist and were confirmed**: Microgen generates lattice/TPMS geometry natively through CadQuery/OpenCascade, and dl4to4ocp runs topology optimization directly on build123d/CadQuery OCP solids (with a pure-classical-SIMP mode that needs zero neural-network involvement, despite the underlying dl4to engine's ML-first architecture). This is the sub-question where "purely algorithmic, no AI, and already pluggable into build123d" is true today, not hypothetically.

- **Ribs from a shell — algorithmically solved in the literature, not solved as a build123d tool.** The FEA-driven principal-stress-field → rib-network → rib-flow-optimization pipeline (Li et al. 2017) and its commercial equivalent (Siemens AUTORIB) are fully deterministic. But no open implementation of that pipeline was found wired to build123d/CadQuery — you'd be reimplementing a research paper, not calling a library. The only "ribs" code actually inside build123d's own docs is one hand-built rib pair (the keycap example) — not a generator.

- **Gussets — the geometry-construction part is essentially already a solved CAD primitive; the sizing/shape part is not.** SolidWorks' Weldments Gusset feature and Fusion 360's Rib/Web command prove this reduces cleanly to "select two faces or one guide line → sweep/loft/fillet + boolean union, auto-trimmed" — exactly the primitives build123d already ships (`sweep`, `loft`, boolean ops, `offset`/shell). That part needs no research, no optimization, and no AI — it's straightforward composition of existing operations, and one concrete open-source example (`archimedes-market/parametric-bracket-library`, with the caveat about a conflicting/unverifiable second sighting of a similarly-described library noted above) shows it done in CadQuery already. Where judgment genuinely enters is *sizing*: the one public closed-form structural algorithm (AISC's Uniform Force Method) only produces interface forces/eccentricities, not a boundary polygon, and the literature itself says its raw output is often "oddly shaped" and needs further optimization (ESO/BESO) or engineering review. That's a modeling/judgment step about *what load case and shape criteria to accept* — not a case for putting an LLM in the loop; it's the same kind of human-supplied-input problem this project already treats as "missing input, not a fabricated answer."

- **Routing rigid inserts/wiring channels — both halves exist deterministically, separately, with no glue between them.** The *search* half (find a collision-free path through obstacles) is a mature, purely algorithmic field: A*/Theta*/JPS/GA/ACO/NSGA-II on voxelized or graph-decomposed 3D spaces, applied for decades to ship pipe routing and aircraft wire-harness/EWIS design, plus one directly OpenCascade-integrated implementation (JPS-Theta*+RFACOR). The *sweep* half is native and working in build123d (`Spline` + `^` positioning + `sweep(multisection=True)`), with CadQuery's version having known rough edges on true 3D paths. `pathfinding3D` is a real, pip-installable, ready piece for the search half. What doesn't exist anywhere in public prior art is the glue connecting them to build123d/CadQuery — that would be a genuine (if modest) integration project: voxelize the target solid, run A*/Theta* for the corridor, smooth it into a spline, hand it to `sweep()`.

**So, addressing the framing directly:** the category as a whole does *not* require an AI model in the loop for each instance in any of the four areas — every piece has a real deterministic algorithm or shipped commercial feature behind it, consistent in spirit with build123d's own templated-parametric philosophy. Lattices are the closest to "just go use it" today. Gusset *geometry* and routing *pathfinding*+*sweep* are each solved as separate primitives that need someone to write the connective code, not new algorithmic invention. Ribs-from-a-shell and load-based gusset sizing are the two spots where a real inference-like step remains — but it's optimization/FEA-based deterministic inference (SIMP, ESO/BESO, UFM, principal-stress rib-flow), or plain engineering judgment about load cases and acceptable shapes, never a place where an LLM's involvement was shown to be necessary or even present in any of the prior art surveyed.

---

## Raw agent reports (unedited)

### Agent I — build123d / CadQuery native pattern, lattice, sweep and shell primitives

# Research findings: build123d/CadQuery native support for ribs, gussets, and lattice structures

## 1. Native array/pattern operations

**build123d** (confirmed via `builder_api_reference.html` and `operations.html`, build123d.readthedocs.io, current dev docs):
- `GridLocations(x_spacing, y_spacing, x_count, y_count, align=(Align.CENTER, Align.CENTER))` — rectangular array context manager.
- `PolarLocations(radius, count, start_angle=0.0, angular_range=360.0, rotate=True, endpoint=False)` — circular/polar array.
- `HexLocations(radius, x_count, y_count, major_radius=False, align=...)` — hexagonal/honeycomb-grid array of locations (this is close to a lattice primitive — it places objects at hex-packed points, but doesn't generate hex *cell walls* itself).
- `Locations(*pts)` — arbitrary point list.
These are used as Python context managers (`with GridLocations(...): Circle(...)`), confirmed live from the docs, e.g. a circuit-board example: `with GridLocations(60, 20, 2, 2): Circle(2, mode=Mode.SUBTRACT)` (build123d.readthedocs.io/en/stable/examples_1.html).

**CadQuery** (confirmed via cadquery.readthedocs.io class reference, mirrored at cadquerytest.readthedocs.io):
- `Workplane.rarray(xSpacing, ySpacing, xCount, yCount, center=True)` — rectangular array of points pushed onto the stack.
- `Workplane.polarArray(radius, startAngle, angle, count, fill=True)` — polar array of points.

Both libraries name this "array," not "pattern" — confirmed real names/signatures, not guessed.

## 2. Sweep, shell, offset, loft

**build123d** (`operations.html`, quoted verbatim from the docs):
- `offset(objects=None, amount=0, openings=None, kind=Kind.ARC, side=Side.BOTH, closed=True, min_edge_length=None, mode=Mode.REPLACE)` — this is the shell operation ("Also commonly known as a shell... `openings` lets you select faces to be deleted, like a hollow box with no lid").
- `sweep(sections=None, path=None, multisection=False, is_frenet=False, transition=Transition.TRANSFORMED, normal=None, binormal=None, clean=True, mode=Mode.ADD)`.
- `loft(sections=None, ruled=False, clean=True, mode=Mode.ADD)`.

**CadQuery** (classreference, quoted verbatim):
- `sweep(path, sweepAlongWires=False, makeSolid=True, isFrenet=False, combine=True, clean=True)`.
- `shell(thickness)`.
- `loft(filled=True, ruled=False, combine=True)`.
(No dedicated `offset`/`offset2D` surfaced in the summary I fetched; `shell` is CadQuery's direct thickness-offset op.)

So: both libraries have real, first-class sweep/shell/offset/loft/array primitives you'd combine yourself (e.g., sketch a rib cross-section → `sweep()` along a guide curve/surface; array a triangular profile with `rarray`/`GridLocations`). Neither library ships a purpose-built "add ribs to this surface" or "add gusset" function — those are compositions you'd write on top.

## 3. Real projects: ribs, gussets, lattices

**(a) Ribbed/stiffened panel — partial, not a general tool.** The only concrete "ribs" hit is build123d's own official keycap example (build123d.readthedocs.io/en/stable/examples_1.html), which builds support ribs by sketching two perpendicular thin rectangles + a circle on a plane and extruding `until=Until.NEXT`:
```python
with BuildSketch(Plane(origin=(0, 0, 4*MM))):
    Rectangle(15*MM, 0.5*MM); Rectangle(0.5*MM, 15*MM); Circle(radius=5.5*MM/2)
extrude(until=Until.NEXT)
```
This is a single hand-built rib pair, not a generalized "ribbed panel following a surface" generator, and no such generator was found elsewhere.

**(b) Gusset/triangular reinforcement — found a real, working example.** Repo `archimedes-market/parametric-bracket-library` (github.com/archimedes-market/parametric-bracket-library) is a CadQuery parametric bracket library (L-bracket, gusseted L, U-bracket, Z-bracket, shelf bracket, right-angle plate; exports STEP/STL/DXF). Its `brackets/l_gusset.py` genuinely builds a triangular gusset:
```python
pts = [(0, 0), (gusset_h, 0), (0, gusset_h)]
gusset = (cq.Workplane("XZ").polyline(pts).close().extrude(gusset_t)
          .translate((thickness, -gusset_t/2, thickness)))
return bracket.union(gusset)
```
This is exactly "sketch a right-triangle profile, extrude, union onto the bracket" — direct, verified prior art for a gusset generator, fetched from the raw file this session.
Also found: `CadQuery/cadquery-contrib` (github.com/CadQuery/cadquery-contrib) contains a `Reinforce_Junction_UsingFillet.py` example — reinforces a joint via fillet rather than a true gusset web, so it's adjacent but not a gusset per se.

**(c) Lattice/grid infill — strong prior art, mostly beyond core build123d/CadQuery, built on top of them:**
- **LatticeQuery** (github.com/jalovisko/LatticeQuery) — open-source lattice-structure modeler explicitly "based on the CadQuery GUI editor." Supports beam-based topologies (simple cubic, BCC, FCC, S-FCC, BCCz, FCCz, Diamond, Rhombicuboctahedron, Truncated cube, etc.) and TPMS types (Gyroid, Schwarz Primitive, Schwarz Diamond), with per-region variable beam thickness. This is the closest thing to a general lattice generator built on the CadQuery stack.
- **cqMore** (github.com/JustinSDK/cqMore), specifically `examples/gyroid.py` (fetched raw) — builds a true gyroid TPMS by evaluating the gyroid implicit function on a grid, running `skimage.measure.marching_cubes` to extract a mesh, then feeding the verts/faces into cqMore's `Workplane().polyhedron(points, faces)`. So CadQuery *can* host a gyroid, but only via marching-cubes meshing, not a native CAD primitive.
- **microgen** (github.com/3MAH/microgen) — uses OCCT directly (`cadquery-ocp-novtk`), not CadQuery/build123d proper. Generates octet-truss/honeycomb lattices and TPMS (gyroid, Fischer-Koch) plus periodic meshing — a heavier, FEA/microstructure-oriented tool, adjacent but not "built with build123d/CadQuery."
- **Pyroid** (github.com/tazomatalax/Pyroid) — a standalone gyroid generator/STL-volume-gyroidizer; did not confirm it uses build123d/CadQuery specifically (didn't fetch its source, so treat the CAD-backend claim as unverified).
- No community lattice helper was found living inside build123d itself; `HexLocations` (confirmed above) is the only native "grid-like" primitive build123d ships, and it places points, not honeycomb walls.

## Verdict

Solid prior art exists for (b) gusset generation and (c) lattice/grid/TPMS structures (LatticeQuery, cqMore's gyroid, microgen), all built on or adjacent to CadQuery/build123d's real `sweep`/`shell`/`offset`/`loft`/`rarray`/`polarArray`/`GridLocations`/`PolarLocations`/`HexLocations` primitives (all names and signatures confirmed live from the official docs). For (a) ribbed/stiffened panels specifically, only a single hand-coded rib pair example was found (build123d's keycap tutorial) — no general "rib pattern following a surface" tool exists in either ecosystem, so that sub-question is the weak spot: build from primitives, don't expect to find a ready-made ribbing generator.

---

### Agent J — deterministic/algorithmic (NOT AI-based) rib and lattice generation from a shell

## Findings: Deterministic/algorithmic rib, lattice, and infill generation from a shell surface

### 1. Topology optimization (SIMP method) — confirmed classical/deterministic, NOT ML

- **SIMP classification, confirmed via search:** Solid Isotropic Material with Penalization is a density-based, **gradient-based** method (uses Optimality Criteria or Method of Moving Asymptotes solvers on FEA sensitivity fields). No inference/training/neural net involved. [The SIMP method in topology optimization](https://www.researchgate.net/publication/269224546_The_SIMP_method_in_topology_optimization_-_Theoretical_background_advantages_and_new_applications) — verdict: **confirmed deterministic, not ML.**
- **The famous "99-line" code exists and is real.** Ole Sigmund's 1999/2001 99-line MATLAB SIMP implementation, later updated/sped up by Niels Aage; a "new generation" 99-line (2D) / 125-line (3D) successor also exists. Fetched directly: [DTU TopOpt — 99 line code](https://www.topopt.mek.dtu.dk/apps-and-software/a-99-line-topology-optimization-code-written-in-matlab); extension paper: [arXiv 2005.05436](https://arxiv.org/pdf/2005.05436). Confirmed deterministic/gradient-based, takes a design domain + load case + volume fraction and outputs a material-density field — visually the rib/lattice-like patterns the question describes.
- **ToPy** — real open-source Python SIMP framework (solves compliance, mechanism-synthesis, and heat-conduction topology optimization in 2D/3D), config via text file or Python dict, outputs PNG/VTK density fields. Stable release is Python-2-only, "unstable" branch targets Python 3. No CAD-kernel integration mentioned. Fetched: [github.com/williamhunter/topy](https://github.com/williamhunter/topy).
- **zfergus/topopt** — another real open-source Python topology-optimization library (MMA, optimality-criterion, genetic-algorithm solvers), deterministic/FEA-based, outputs a density array; no CAD integration mentioned. Fetched: [github.com/zfergus/topopt](https://github.com/zfergus/topopt). Related: [TopOpt-MMA-Python](https://github.com/arjendeetman/TopOpt-MMA-Python) (found via search, not fetched in full).

### 2. CAD-kernel (OCCT/build123d/CadQuery) connections

- **dl4to4ocp** — a real project (yeicor-3d org) that runs topology optimization directly on **OCP-based CAD solids (CadQuery/build123d)**: you build green (fixed) / red (loaded) / gray (design-space) solids in build123d/CadQuery, it runs the optimizer, exports the resulting solid. Confirmed listed on the official build123d docs' external-tools page (exact quote fetched): *"Library that helps perform topology optimization on your OCP-based CAD models (CadQuery/Build123d/…) using the dl4to library."* — [build123d external tools](https://build123d.readthedocs.io/en/latest/external.html), repo: [github.com/yeicor-3d/dl4to4ocp](https://github.com/yeicor-3d/dl4to4ocp).
  - **Caveat:** the underlying engine, **dl4to**, is a *hybrid* library — confirmed via fetch that it does implement classical deterministic SIMP with a standard FE solver usable with **zero neural-network involvement**, but its architecture is fundamentally PyTorch/autograd-based and its main selling point is neural-network integration. [github.com/dl4to/dl4to](https://github.com/dl4to/dl4to). So this is the closest verified bridge to build123d, but it isn't a "pure classical" tool by design — you'd be using only its SIMP sub-mode and ignoring the ML half.
- **Microgen** — a strong, more directly relevant find: an open-source Python library for **microstructure/lattice/TPMS generation** (gyroid, Schwarz, Schoen, Neovius surfaces, octet-truss/lattice unit cells, Voronoi polycrystals) that explicitly **uses Open CASCADE via CadQuery** for the geometry and Gmsh/MMG for periodic meshing. This is a real, deterministic, non-ML, CAD-kernel-integrated lattice generator. [github.com/3MAH/microgen](https://github.com/3MAH/microgen), [docs](https://microgen.readthedocs.io/en/latest/).

### 3. Lattice / infill generation (gyroid, Voronoi)

- **Gyroid/TPMS lattices** are generated deterministically via implicit/function-representation (F-Rep) of triply-periodic minimal surfaces — an isosurface threshold, not ML. [ScienceDirect: gyroid lattice via load-path design](https://www.sciencedirect.com/science/article/abs/pii/S2214860424006328), [ScienceDirect: gyroid-based FGM cellular structures](https://www.sciencedirect.com/science/article/abs/pii/S0010448518300381).
- **Voronizer** — real, open-source (GPL-3.0) Python/CUDA tool that generates Voronoi-foam infill and supports directly on STL files; confirmed deterministic computational geometry, no ML, but not integrated with a B-rep CAD kernel (works on meshes, needs an Nvidia GPU). [github.com/tjwill95/voronizer](https://github.com/tjwill95/voronizer).
- **Voro++** — real, mature open-source C++ library for 3D Voronoi tessellation, usable as a building block for Voronoi lattices. [math.lbl.gov/voro++](https://math.lbl.gov/voro++/).
- **TPMSgen** — another real open-source Python TPMS generator (10 surface topologies) found via search but not independently fetched/verified this session: [github.com/albertforesg/TPMSgen](https://github.com/albertforesg/TPMSgen) (recalled from search snippet only, not fetched).
- **PySLM** is real and is an active, maintained Python AM library (Trimesh + Clipper2-based), but I fetched its docs directly and confirmed it does **NOT** do lattice/infill/rib generation — it only does slicing, hatching/scan-strategy, and support-structure generation. Its docs mention implicit fields "can be" used for lattice volumes as a general aside, but that's not a shipped module. [pyslm.readthedocs.io](https://pyslm.readthedocs.io/).

### 4. Rib/stiffener placement from a shell — the closest direct match to the question

- **"Rib-reinforced Shell Structure"** (Li, Zheng, You, Yang, Zhang, Liu — Computer Graphics Forum / Pacific Graphics 2017) is exactly the algorithm class asked about: given a shell surface + user-specified external loads, it runs FEA to get a principal-stress field, builds a cross-field-aligned quad mesh, extracts an initial rib network from it, simplifies via "rib flow optimization," then optimizes rib cross-sections — fully deterministic/geometric, no ML. Confirmed via search snippet (direct PDF fetch failed — connection refused to the university mirror, so treat the algorithmic description as **verified via WebSearch summary, not full-text-fetched**): [Wiley abstract](https://onlinelibrary.wiley.com/doi/abs/10.1111/cgf.13268), [Semantic Scholar](https://www.semanticscholar.org/paper/Rib%E2%80%90reinforced-Shell-Structure-Li-Zheng/da8700aeb85ffab6371d417a4d42ab8d88097fd4).
- Follow-on/related deterministic work in the same vein, found via search (titles/venues confirmed, not fetched in full): "Principal stress field-guided optimization for rib structure generation" ([ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0010448525001162)), "Reinforcement of General Shell Structures" (ACM TOG, [dl.acm.org/doi/10.1145/3375677](https://dl.acm.org/doi/10.1145/3375677)), "Automated rib location and optimization for plate structures" (2002, Structural and Multidisciplinary Optimization — [Springer](https://link.springer.com/article/10.1007/s00158-002-0270-7), paywalled, abstract-level only from search snippet).
- **AUTORIB** (Siemens/Genesis, commercial, not open-source) automatically creates candidate rib elements along every mesh edge, then sizes/prunes them — a real, shipped, deterministic (non-ML) commercial feature. [Siemens community article](https://community.sw.siemens.com/s/article/33481-designing-rib-stiffeners-the-easy-way-with-autorib).
- **Venation-Inspired Growth Technique for Stiffener Layout Design** — a biomimetic but still fully deterministic growth-simulation algorithm (models leaf-vein growth) for placing stiffeners on plates/shells, found via search only: [scientific.net/JBBTE.18.1](https://www.scientific.net/JBBTE.18.1) (not fetched, title/venue-level confirmation only).
- Several more stiffener-layout-optimization papers (component-based, concurrent topology+cross-section, modular-stiffener simultaneous topology/layout) turned up in search, all describing gradient-based/evolutionary (non-ML) methods integrated with FEA tools like Abaqus — titles/URLs real but not individually fetched: [Springer 2021 component-based](https://link.springer.com/article/10.1007/s00158-021-02945-9), [Springer 2020 concurrent topo+cross-section](https://link.springer.com/article/10.1007/s10409-020-01034-2), [Springer 2021 modular stiffeners](https://link.springer.com/article/10.1007/s00158-021-03081-0).

### Not found / not verified this session
- Could not fully fetch the ribShell PDF itself (connection refused) — algorithm description above rests on the WebSearch-tool's summary of that paper's abstract/page, not a direct full-text read.
- Could not verify TPMSgen's or PyScaffolder's actual implementation details beyond their existence/description in search snippets.
- Found nothing suggesting ToPy, zfergus/topopt, Voronizer, or the 99-line SIMP code have any built-in, ready-made bridge into build123d/CadQuery/OCCT — the density-field/mesh output of classical topology optimizers is not natively a B-rep solid; getting one into build123d requires either marching-cubes/mesh reconstruction (not found as an off-the-shelf pipeline for these specific tools) or a purpose-built bridge like dl4to4ocp.

### Verdict
Solid prior art exists for this sub-question. There's a well-established, decades-old, genuinely deterministic algorithmic literature and toolset (SIMP topology optimization — 99-line code lineage, ToPy, zfergus/topopt; TPMS/gyroid implicit-surface lattices via Microgen; Voronoi-cell infill via Voronizer/Voro++; principal-stress-field-guided rib generation from a loaded shell) that requires no ML inference at all. The CAD-kernel bridge is thinner but real: **Microgen already generates TPMS/lattice geometry through CadQuery/OpenCascade**, and **dl4to4ocp already runs (optionally pure-classical) topology optimization directly on build123d/CadQuery solids** — both are genuine, fetched-and-confirmed starting points rather than something that would need to be built from scratch.

---

### Agent K — automatic gusset/joint-reinforcement generation

## Findings: Automatic gusset/joint-reinforcement generation — web research

### A. Commercial structural-steel CAD/design tools that DO auto-generate gusset geometry (rule-based, not AI)

**1. Autodesk Advance Steel — "Bracing - Gusset Plates"**
https://help.autodesk.com/cloudhelp/2015/ENU/ASD-Steel/files/GUID-2E8401F0-DEB6-4DE8-A297-335A441E911C.htm
Confirmed by direct fetch: there is a literal "Automatic" checkbox — "To generate a gusset plate automatically, select Automatic. If Automatic is cleared, all dimensions of the plate will be user-defined." The doc does *not* disclose the underlying algorithm (which member-geometry inputs feed it or the outline math). So: real, shipped auto-generation feature; algorithm undisclosed publicly.

**2. Tekla Structures — parametric "gusset" components**
https://support.tekla.com/doc/tekla-structures/2025/det_bracing_simple_gusset_conns , https://support.tekla.com/doc/tekla-structures/2026/det_bracing_bolted_gusset , https://support.tekla.com/doc/tekla-structures/2026/det_bracing_gusseted_cross , https://support.tekla.com/doc/tekla-structures/2025/conn_1_help_gusset_plus_t
Multiple named components ("Bolted gusset," "Gusseted cross," "Gusset+T") connect 1–10 braces to a beam/column and generate the gusset plate, bolts/welds, and clip angles automatically from the selected members. Tekla explicitly uses a `joints.def` parameter file to drive plate gap/dimensions/shape ("Picture tab" controls). This is real, deterministic, rule-driven auto-generation in a mainstream tool — but the exact geometric algorithm inside `joints.def` isn't public in what I found.

**3. IDEA StatiCa Connection — "Gusset plate" as a Manufacturing Operation**
https://www.ideastatica.com/support-center/gusset-plate-design-in-idea-statica-connection (page itself gave no algorithm detail on direct fetch) + a technical PDF found but not text-extracted: https://assets-us-01.kc-usercontent.com/1ca05609-4ad1-009e-bc40-2e1230b16a75/5b5b2544-b78c-4e08-9816-c0c547d03146/Gusset_plate_connections_in_IDEA_StatiCa_Connection.pdf
Search snippet (not directly verified by full fetch) states gusset plate is one of several "manufacturing operations" (cuts, offsets, holes, stiffeners, ribs, gusset plates, splices) that get resolved into an automatically-generated CBFEM mesh — i.e., the *analysis* model is automatic once the operation is placed, but placing/sizing the plate itself still looks user-parametrized, not derived purely from member geometry. Treat the "fully automatic" framing here as unverified.

**4. RISAConnection — tapered/rectangular gusset with UFM-driven size limits**
https://blog.risa.com/post/tapered-gusset-plates-using-custom-angle , https://blog.risa.com/tag/gusset-plate
RISAConnection auto-limits gusset dimensions per AISC 14th-ed. equations when the Zero-Moment/Uniform Force Method is selected, and supports a parametric tapered-cut definition (left/right cut angles + extensions) rather than free sketching. Real, deterministic, formula-driven — algorithm is the AISC Uniform Force Method (see B below), not a novel outline generator.

**5. Autodesk Inventor Frame Generator — confirmed gap, filled by third party**
https://forums.autodesk.com/t5/inventor-ideas/gussets-for-frame-generator/idi-p/4704127 — users have requested a native gusset feature since 2002; still absent from Frame Generator as of what's documented.
Third-party plugin: https://klietsch.com/inventor/?m=%2FSolidSteelparametric%2FFunctions&lang=en — "SolidSteel parametric": user selects the bolted face and welded face, a gusset preview appears immediately and is generated from presets. This is a real deterministic two-face → gusset-solid generator, but third-party/proprietary, algorithm undocumented.

### B. The one genuinely public, documented *algorithm* closest to "compute gusset geometry from member geometry"

**Uniform Force Method (UFM), Thornton 1991, in the AISC Manual since 1992**
https://ej.aisc.org/index.php/engj/article/view/1341 (AISC Engineering Journal derivation), https://www.aisc.org/Designing-Compact-Gussets-with-the-Uniform-Force-Method
This is a fully closed-form, deterministic procedure: given the beam depth, column geometry, brace angle and work-point, it computes the eccentricities and forces at the gusset-to-beam and gusset-to-column interfaces such that no moment exists at any interface. It's the standard method underlying RISAConnection's and (likely) other tools' automatic sizing. Caveat found directly in the search results: "one criticism of the method is that it sometimes results in oddly shaped or disproportionately large gusset plates" — later papers (e.g. a ScienceDirect piece, "Proposed design procedure for gusset plate dimensions and force distribution," https://www.sciencedirect.com/science/article/abs/pii/S0141029618304334 — abstract not retrievable, 403) explicitly try to fix the boundary-shape output of UFM. So: UFM gives you interface forces/eccentricities algorithmically; it is *not* itself a full outline/boundary generator — real engineering judgment (or a further optimization step) still typically sets the actual polygon.

**Whitmore section (30° dispersion rule)**
https://www.eng-tips.com/threads/gusset-plate-whitmore-section.479700/ , https://iopscience.iop.org/article/10.1088/1757-899X/852/1/012004/pdf
A genuinely deterministic geometric construction: extend two lines at 30° from the first row of fasteners to the last row to define an "effective width" for capacity checks. This is closed-form and CAD-automatable, but it's a *capacity-check region*, not the plate's actual physical boundary.

### C. Topology/shape optimization of gusset plates (deterministic, non-AI, but not "instant CAD op")

- ResearchGate: "Evolutionary structural optimization of steel gusset plates" — https://www.researchgate.net/publication/223388919_Evolutionary_structural_optimization_of_steel_gusset_plates — uses ESO/BESO (element-removal) to shape-optimize a gusset plate under given loads/boundary conditions. Deterministic FE-driven algorithm, not AI — but iterative/optimization-based, not a single closed-form geometric construction, and it presupposes the connection topology (which edges are fixed to which members) already chosen.
- arXiv paper (abstract confirmed via fetch): "Web application for size and topology optimization of trusses and gusset plates," https://arxiv.org/pdf/1512.02881 (also https://arxiv.org/abs/1512.02881) — a real tool combining truss size optimization with per-joint gusset-plate topology optimization (Three.js front end, Scilab+DAKOTA backend), benchmarked against IS 800-2007. This is the closest concrete "automatic gusset generation" research artifact I found, but it's an optimization pipeline (minutes-scale, needs load cases), not a <1ms closed-form CAD operation — i.e., not compatible with an interactive-plane tier.

### D. Is "auto-gusset" just a special case of a general CAD fillet/loft primitive that build123d/CadQuery/OCCT already has?

**Yes, partially — mainstream parametric CAD already ships a generalized version of exactly this, under the names "Gusset," "Rib," or "Web":**

- **SolidWorks Weldments → Gusset feature** (real, verified via direct fetch of https://www.goengineer.com/blog/solidworks-weldments-corners-gussets-bounding-box ; official docs page 403'd but corroborated by search snippets and https://grabcad.com/tutorials/tutorial-gusset-in-weldment-in-solidworks ): user selects **two planar faces** where members meet, picks a profile (triangular or polygonal), thickness, and chamfer/relief, and SolidWorks constructs the solid automatically. This is a real, shipped, deterministic "two-face + a few scalars → gusset solid" primitive — semi-automatic (profile shape is chosen, not derived from load), and notably it does *not* auto-populate the weldment cut-list without an extra manual "Create Bounding Box" step.
- **Fusion 360 Rib / Web command** (https://www.autodesk.com/learn/ondemand/tutorial/add-webs-and-ribs-to-solid-bodies , corroborated by forum thread https://forums.autodesk.com/t5/fusion-design-validate-document/a-good-way-to-create-ribs/td-p/7203976 ): you sketch a single line indicating the rib's path/thickness and Fusion auto-extends/trims it to the surrounding solid bodies — "you don't have to make the lines... go all the way to the... bottom plate—Fusion will fill in the gaps itself." This is functionally a generalized, automatic "fill the gap between two intersecting bodies with a reinforcing wall" operation — very close conceptually to a gusset generator, just not named "gusset."

**At the geometric-kernel level (OCCT itself):** OCCT has `GeomFill_ConstrainedFilling` / n-sided surface-fill and `BRepFilletAPI` fillet/chamfer algorithms (https://dev.opencascade.org/doc/overview/html/occt_user_guides__modeling_algos.html , https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations ) — these can fill a gap bounded by 2–4 curves/tangency constraints, which is the general primitive a gusset-fill could be built on. But this is a raw surface-filling capability, not a packaged "gusset between two members" feature — build123d/CadQuery expose OCCT's loft, sweep, and fillet ops directly but I found **no existing build123d/CadQuery example, snippet, or library specifically named "gusset."** (One search result described a "parametric library of 6 production-grade mounting brackets including a gusseted L-bracket, built in CadQuery" — this description recurred verbatim across three separate searches but **no actual URL was ever produced for it**. I could not verify it exists; flagging as likely a fabricated/synthesized search-snippet, not a confirmed finding — excluded from citations.)

### E. Not found

- No public documentation of IDEA StatiCa's or Tekla's actual outline-construction algorithm (only that the feature exists and is parametric/rule-based).
- No build123d/CadQuery-specific "gusset generator" code example or repo found.
- No truss-joint-plate open-source generator beyond the OpenSCAD "parametric joint generator" 3D-model listing (https://creazilla.com/media/3d-model/7839609/openscad-library-parametric-joint-generator — title only, not fetched/verified further) and the GridfinityStructure repo (https://github.com/YieldingData/GridfinityStructure), which per its own description has "gusset plate **placeholders**," i.e., not a real generator.

### Verdict

Solid prior art exists, but it's split and none of it is a single off-the-shelf closed-form algorithm you could port directly. Concretely: (1) mainstream CAD already generalizes this as a "Gusset"/"Rib"/"Web" feature (SolidWorks, Fusion 360) — a deterministic **two-face(s)-plus-scalar-parameters → auto-trimmed solid** operation, which is realistically buildable directly on build123d/OCCT primitives (loft/sweep/boolean-fuse + face-to-face trim) without inventing new kernel math; (2) structural-steel software (Advance Steel, RISAConnection, Tekla) ships "Automatic" gusset generation in production but keeps the actual outline algorithm proprietary/undisclosed; (3) the one publicly documented closed-form structural algorithm (AISC's Uniform Force Method) gives you interface forces/eccentricities, not a full boundary polygon, and is explicitly criticized in the literature for producing awkward shapes that still need a follow-on optimization or engineering-judgment step. So: build on the CAD-primitive pattern (two-member-face selection → parametric profile → trimmed boolean fill, à la SolidWorks Gusset/Fusion Rib) for the geometry, and treat any load-based sizing (UFM, Whitmore) as a separate, optional downstream check — there is no single published "the algorithm" to copy wholesale.

---

### Agent L — routing rigid inserts, spars, and wiring channels through complex 3D geometry

## Findings

### 1. Commercial "Routing" CAD modules — real, but manual/assisted, not automatic pathfinding

- **SOLIDWORKS Routing** — https://help.solidworks.com/2025/English/SolidWorks/sldpiping/c_routing_overview.htm (search-snippet) and https://www.goengineer.com/blog/solidworks-routing-101-pipe-design (fetched directly). Real, documented add-in in SW Premium/Ultimate for pipe/tube/cable/duct routes. Confirmed workflow: the user places a 3D sketch and manually draws line segments (with Tab to reorient planes) that become the route; the tool then auto-inserts fittings/elbows at the corners and sweeps the pipe profile along that user-authored sketch. **This is manual/assisted route authoring, not obstacle-avoiding automatic pathfinding.** Closeness: moderate — confirms the "sweep profile along an authored path" pattern is industry-standard, but does not solve the "find the path" half of the question.
- **Fusion 360** — no native automatic cable-routing/pathfinding tool (per Autodesk forum thread found in search: "no current projects underway to support wire harness design in Fusion"). Standard method is manually dragging a 3D sketch spline off-plane, then Sweep. A community add-in, **F360WireGenerator** (https://github.com/hyweric/F360WireGenerator), auto-generates spline *variations* between a chosen start/end point (for wire slack/appearance), but it is not obstacle-aware routing. Closeness: low.

### 2. Academic/algorithmic pipe & harness routing — this is where real solid prior art lives

- **Ship pipe routing literature** (large, mature body of work): "Ship Pipe Route Design Using Improved A* Algorithm and Genetic Algorithm" (IEEE Xplore, https://ieeexplore.ieee.org/document/9172005/), "Branch-pipe-routing approach for ships using improved genetic algorithm" (Springer, https://link.springer.com/article/10.1007/s11465-016-0384-z), "Pipe-routing algorithm development: case study of a ship engine room design" (ScienceDirect, https://www.sciencedirect.com/science/article/abs/pii/S0957417402000490), "Ship Pipe Routing Design Using NSGA-II and Coevolutionary Algorithm" (Wiley, https://onlinelibrary.wiley.com/doi/10.1155/2016/7912863), "Automated Pipe Routing Optimization for Ship Machinery" (Springer JMSA 2022, https://link.springer.com/article/10.1007/s11804-022-00269-8). These decompose the 3D routing space into a grid and run A*/GA/ACO/NSGA-II hybrids to find near-optimal collision-free pipe paths around equipment obstacles. **This is exactly the algorithmic pattern being asked about** (find path A→B through obstacles inside a 3D volume), just applied to ship engine rooms rather than a printed part. Note: I only verified these via search-result titles/snippets, not full-text fetch — the URLs are real (returned by search), but I have not read the papers directly.
- **Aircraft wire-harness / EWIS routing**: "Automatic Cable Harness Layout Routing in a Customizable 3D Environment" (ScienceDirect/CAD journal, https://www.sciencedirect.com/science/article/pii/S0010448523002038, page fetch blocked 403 so only search-snippet verified) — formulates harness routing as shortest-path + Steiner-tree problem, reads geometry directly from 3D CAD and writes results back. "A methodology to enable automatic 3D routing of aircraft Electrical Wiring Interconnection System" (CEAS Aeronautical Journal, https://link.springer.com/article/10.1007/s13272-017-0238-3) — A* used to minimize wire-harness weight in 3D. Closeness: high — same problem, applied to wire bundles instead of a rigid insert, and directly tied to CAD data.
- **"Automatic cable routing based on improved pathfinding algorithm and B-spline optimization for collision avoidance"** (Oxford Academic / J. Computational Design and Engineering, https://academic.oup.com/jcde/article/11/5/303/7810276 — fetched successfully). This is the closest single match found: a **JPS–Theta\*** hybrid (Jump Point Search + Theta* line-of-sight smoothing) searches a voxel grid for an initial collision-free path, then **RFACOR** (an ant-colony-style continuous optimizer) refines the path into a smooth B-spline cable shape while checking cable-surface point clouds against obstacles for collision. Uses the **OpenCascade** kernel for geometry, ingests STEP/XML. Validated on an electrical-panel case study. This is essentially "find a valid channel path through obstacles, then generate swept cable geometry along it" — the exact question, with a named, described algorithm and OCCT (the same kernel build123d/CadQuery sit on) in the loop.
- **"Cable route planning in complex environments using constrained sampling"** — found only as a title via search (ResearchGate fetch returned 403, not independently verified this session).
- **"Projection and Geodesic-Based Pipe Routing Algorithm"** — found only as a title via search, not fetched/verified.

### 3. Routing embedded wires/channels inside 3D-printed parts (closest domain analog to "route through a solid")

- **"Topology-Aware Routing of 3D-Printed Circuits"** (TAMS, Univ. Hamburg — PDF confirmed reachable at https://tams.informatik.uni-hamburg.de/theses/printed-electronics-routing-paper.pdf, also indexed on ScienceDirect at https://www.sciencedirect.com/science/article/pii/S2214860420308952, which 403'd on direct fetch). Per the search-engine's synopsis of it (I could not extract readable text from the PDF binary myself, so this description is secondhand from the search snippet, not independently confirmed by reading the paper): converts the volumetric printed-object model into a **graph** (mixing the object's free-form shape boundary with a grid structure in infill regions, plus layer-to-layer z-connections), then runs a **modified A\*** over that graph to find a collision-free, printable wire path, and emits G-code with the wire embedded along the found path. This is genuinely the "channel routed through a complex solid" case, algorithmically described, though for embedded-wire 3D printing rather than a rigid rod/spar insert.

### 4. Medial-axis / Voronoi-skeleton approaches

Generalized-Voronoi-diagram-as-medial-axis-of-free-space, with paths searched on the skeleton for maximum obstacle clearance, is well-established in general path-planning (e.g. https://gamma.cs.unc.edu/VORONOI/FPLAN/fplan.pdf). Separately, computing the medial axis *of a CAD solid itself* is an established CAD/meshing operation (e.g. "Approximate medial axis for CAD models," "Towards Voronoi Diagrams of Surface Patches," https://arxiv.org/pdf/2411.06471). I found **no case study that connects these two** — i.e., no paper using a CAD-solid's medial axis specifically as a routing corridor for a physical channel/insert. This looks like a real gap rather than an oversight in my search.

### 5. `sweep()` along an arbitrary 3D path — confirmed real APIs, with an important library-quality caveat

- **build123d**: confirmed real, current API via official docs (https://build123d.readthedocs.io/en/stable/examples_1.html, fetched). Define an arbitrary 3D path with `Spline(pt1, pt2, pt3, ..., tangents=..., tangent_scalars=...)`, position cross-sections along it with the `^` operator (e.g. `path ^ 0.5`), and call `sweep(sections, path=path, multisection=True)` (or a plain single-profile `sweep(profile, path=path)`). This is a first-class, working pattern per the library's own Handle and Tea Cup examples.
- **CadQuery**: confirmed real base API via the official example file (https://github.com/CadQuery/cadquery/blob/master/examples/Ex023_Sweep.py, fetched) — `cq.Workplane("XZ").spline(pts)` builds the path, `cq.Workplane("XY").circle(r).sweep(path, isFrenet=True)` sweeps a profile along it. **However**, genuinely non-planar 3D paths are shakier: GitHub issue #1860 (https://github.com/CadQuery/cadquery/issues/1860, fetched) is an open, unresolved report that sweeping a truly 3D spline path produces a non-uniform cross-section and wrong depth; issue #507 (https://github.com/CadQuery/cadquery/issues/507, fetched) shows multisection tapered sweeps along a 3D path are awkward because the offset mechanism only varies in one coordinate. So: real API, but treat arbitrary-3D-path sweep as a known rough edge in CadQuery specifically, less so in build123d (built more directly on OCP with cleaner primitives).
- Neither library has any built-in pathfinding/obstacle-avoidance — `sweep()` unconditionally takes a path you already computed. **No connection between any of the routing algorithms above and build123d/CadQuery was found** — that integration doesn't exist in public prior art; it would have to be hand-built (grid-search for the path, then hand the resulting waypoints to `Spline()`/`sweep()`).

### 6. A usable open-source building block for the "search" half

- **pathfinding3D** (PyPI: https://pypi.org/project/pathfinding3d/0.4.0, GitHub: https://github.com/harisankar95/pathfinding3D, fetched and confirmed real) — an actively maintained Python library (fork of `python-pathfinding`) implementing A*, Dijkstra, Best-First, Bi-directional A*, BFS, IDA*, MST, and Theta* over 3D NumPy occupancy grids (0 = obstacle, 1 = free). Purely grid-based, no CAD/geometry awareness of its own, but it's a real, directly pip-installable piece that could be voxelize-the-solid → run A*/Theta* → feed waypoints into build123d's `Spline`+`sweep`.

## Verdict

Solid prior art **exists for the algorithmic sub-question** — "find a collision-free path through obstacles in a 3D volume, then sweep geometry along it" is a well-published research area (ship pipe routing, aircraft wire-harness/EWIS routing, and one close analog for embedded-wire 3D printing), predominantly using A*/Theta*/JPS variants, genetic/ant-colony optimization, and Dijkstra/Steiner-tree formulations on voxelized or graph-decomposed routing spaces. What does **not** exist in any documented, verifiable form is a ready-made bridge from that algorithmic literature into build123d or CadQuery specifically, nor a commercial CAD "auto-router" that does true obstacle-avoiding pathfinding (SolidWorks Routing and Fusion 360 are both manual/assisted route authoring) — that integration (e.g., pathfinding3D or a custom A*/Theta* voxel search feeding waypoints into build123d's native `Spline`/`sweep(multisection=True)`) would have to be built from these separate, individually-real pieces rather than adopted off the shelf.

---

