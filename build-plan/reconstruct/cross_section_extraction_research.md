# Cross-section extraction as real vertex/curve data — prior-art research

**Date:** 2026-08-03
**Status:** Exploratory research only — nothing here is built or scheduled. Captured so future work
doesn't re-derive it from scratch.

## Context / the idea being evaluated

Cut a 3D object into cross-sections at various stations and extract each cross-section not just as a
rendered image but as real vertex/curve data in 3D space — geometry an AI (or deterministic code) can
assess and use to modify/construct complex geometry. Research covered: (1) whether build123d/CadQuery
already expose this, (2) how other CAD tools/kernels/slicers solve it, (3) whether "edit a stack of
cross-section curves, then reconstruct" is an established shape-editing/generative paradigm, and
(4) whether real engineering section properties (I, J, centroid) can be computed from arbitrary
extracted cross-section geometry — this last point connects directly to the project's own physics-
relations gap (`packages/couplings/relations.py` currently only has closed-form formulas for named
rectangular/circular sections).

Four parallel research agents (Sonnet 5, via the Workflow tool) investigated: (E) build123d/CadQuery
section API specifically, (F) cross-section-as-real-geometry in other CAD tools/kernels/slicers,
(G) AI/generative modeling using cross-section-stack representations, (H) section-property computation
from arbitrary cross-section geometry. A fifth agent synthesized the four raw reports. Citation status
(directly fetched vs. search-snippet-only vs. recalled/unverified) is preserved exactly as each agent
reported it. No URL below was invented; each was actually retrieved via WebSearch/WebFetch in that
session.

**Headline finding**: unlike the 3-view reconstruction research, this one lands mostly "yes, already
solved" — build123d has a native, documented `section()` operation returning real OCCT-backed geometry,
and a separate active library (`sectionproperties`) already closes the loop from arbitrary cross-section
vertex data to real engineering section properties (I, J, centroid, section modulus).

---

## Synthesis (read this first)

# Cross-sections as real 3D geometry (not images) — synthesis of 4 research passes

## 1. Direct build123d/CadQuery precedent (the core answer to the question)

**build123d has exactly what was asked about, built-in and documented.** It exposes a first-class
`section()` Part-operation:

```
section(obj: Part | None = None,
        section_by: Plane | Iterable[Plane] = Plane((0,0,0),(1,0,0),(0,-1,0)),
        height: float = 0.0,
        clean: bool = True,
        mode: Mode = Mode.PRIVATE) -> Sketch
```
Source: https://build123d.readthedocs.io/en/latest/operations.html (fetched)

It returns a **`Sketch`** — a real OCCT-backed Compound of Faces, not a raster image. Sketch/Face
objects expose selectors (`.faces()`, `.edges()`, `.vertices()`) and properties (`.area`, vertex
`.X`/`.Y`). One caveat from the reporting agent: the vertex-property claim (`.X`/`.Y` access) was
confirmed only via a search-result summary of the "Introductory Examples" page, not a full fetch of
that specific page — flagged as lightly-verified rather than fully confirmed.

**CadQuery** has the analogous `Workplane.section()`, and — unlike the build123d case — there's a live,
real-world usage example, not just a doc signature:
```python
exp.exportDXF(cq.Workplane().rect(Ws,Hs).extrude(1).section(),'sheet.dxf')
```
Source: https://github.com/CadQuery/cadquery-contrib/blob/master/examples/tray.py (fetched) — the
section result is fed straight into DXF export, i.e., it's genuine Face/Wire geometry driving a
manufacturing output, not a picture. Corroborated by a maintainer confirming this also works on
assemblies (with the caveat that it's a true intersection profile, "only shows what's on the plane,"
and CQ's DXF export is 2D-only): https://github.com/CadQuery/cadquery/discussions/1568 (fetched).

Two rough edges worth knowing about on the CadQuery side:
- True 3D **plane-splitting** (as opposed to a flat profile) has an open, documented bug:
  `Workplane.split()` silently ignores a passed `Plane` object and can raise
  `ValueError: Null TopoDS_Shape` on a rotated plane. https://github.com/CadQuery/cadquery/issues/751
  (fetched)
- At the `Shape` class level, CQ's `split()` is implemented via `BRepAlgoAPI_Splitter`, not
  `BRepAlgoAPI_Section` — confirmed from source at
  https://cadquery.readthedocs.io/en/latest/_modules/cadquery/occ_impl/shapes.html (fetched). A
  dedicated `Shape.section()` OCCT wrapper wasn't found in the portion of source retrieved (may exist
  deeper in the file or live only at the `Workplane` layer — not confirmed either way).

At the raw-OCCT layer underneath both tools, `BRepAlgoAPI_Section` gives you a real `TopoDS_Shape` but
as an unordered soup of edges/wires that you must manually re-chain (e.g. via `TopExp_Explorer`) into
usable Wires — confirmed via a user question with no visible resolution:
https://github.com/tpaviot/pythonocc-core/issues/1031 (fetched).

One concrete example of *doing further construction* with an extracted section rather than just
exporting it: `cqkit.extrude_xsection()` cuts a cross-section and re-extrudes the exposed face by a
given extent. https://pypi.org/project/cqkit/ (fetched) — though whether it's built on `section()` or
`split()` internally wasn't confirmed.

**Bottom line for this section**: build123d's `section()` and CadQuery's `section()` both genuinely
satisfy "real vertex/curve data, not an image" for planar cross-sections. True 3D clipping in CadQuery
has a known rough edge for arbitrary planes.

## 2. How other CAD tools/kernels/slicers expose cross-sections as real geometry

This is where the prior art is deepest and most battle-tested — cross-sectioning at scale is the
literal core operation of every 3D-print slicer.

**Slicers (the highest-volume real-world precedent)**
- **CuraEngine**: triangles are cut into per-Z-layer line segments, then stitched by proximity/winding
  into closed polygons — confirmed pipeline description at
  https://ultimaker.github.io/CuraEngine/docs/slicing.html (fetched); source lives in `src/slicer.cpp`,
  found via search but not fetched:
  https://github.com/Ultimaker/CuraEngine/blob/main/src/slicer.cpp. This runs millions of times a day,
  but it's baked into the slicing monolith, not exposed as a general "give me the polygon" API.
- **PrusaSlicer/libslic3r**: each layer is an `ExPolygon` — a `Polygon contour` + `Polygons holes`,
  built on Clipper — confirmed from source:
  https://github.com/prusa3d/PrusaSlicer/blob/master/src/libslic3r/ExPolygon.hpp (fetched). This is
  the cleaner of the two — a reusable point-list-with-holes type used throughout the codebase for
  area/offset/boolean/medial-axis math, i.e., designed as computable geometry, not just render data.

**FreeCAD** — scriptable path is `Part.Shape.section()` / `TopoShape.section()`, signature
`section(tool, [approximation=False]) -> Shape`, confirmed at
https://freecad-python-stubs.readthedocs.io/en/latest/autoapi/Part/_TopoShape/ (fetched). Since
FreeCAD's Part module wraps OpenCASCADE directly, this is `BRepAlgoAPI_Section` underneath — same
edge-soup caveat as raw OCCT. The GUI "Part CrossSections" tool is documented at
https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Part_CrossSections.md (fetched) but
explicitly produces a **non-parametric** static snapshot, and the doc doesn't state its output type.
Attempts to reach FreeCAD's own current wiki for corroboration failed (DNS failure on one URL, "Access
Denied" on another).

**Fusion 360** — `sketch.intersectWithSketchPlane(entities)` is a real, documented scripting API
returning actual sketch curve entities:
https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/SketchIntersect_Sample.htm (fetched),
corroborated by a separate UI-focused support page found via search:
https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-create-a-sketch-of-a-cross-section-of-a-3D-Model-in-Fusion-360.html.
This was reported as the cleanest commercial-CAD scripting API of the survey.

**SolidWorks** — a working macro pattern exists (`Body2.Operations2()` with `SWBODYINTERSECT`) but
returns a **sheet-body object**, not curve/edge data directly — one step removed from usable loop data.
https://www.codestack.net/solidworks-api/geometry/slice-body/ (fetched). No direct "get section
curves" call was found; a related parametric "Intersection Curves" feature exists per
https://help.solidworks.com/2025/english/solidworks/sldworks/c_Intersection_Curves.htm (found via
search, not fully fetched).

**Purpose-built mesh libraries**
- **trimesh** — `mesh.section(plane_origin=..., plane_normal=...)` returns a 3D `Path3D`;
  `.to_planar()` gives a 2D `Path2D` with `.vertices`/`.entities`/`.polygons_full`;
  `section_multiplane()` explicitly targets repeated-height slicing. https://trimesh.org/section.html
  (fetched). Reported as probably the closest general-purpose match to "mesh + plane in, processable
  boundary geometry out."
- **meshcut** — smaller, narrower library; `cross_section()` returns numpy polyline arrays directly
  from vertex/face arrays + plane. https://github.com/julienr/meshcut (fetched).

**Rhino/RhinoCommon** — `Brep.CreateContourCurves(Brep, Plane)` returns a plain `Curve[]` — reported as
the tidiest API surface in the whole survey, though the API page itself rendered only a bare title on
fetch, so the signature is corroborated from a search snippet plus a live usage/bug thread rather than
the primary doc body: https://developer.rhino3d.com/api/rhinocommon/rhino.geometry.brep/createcontourcurves,
https://discourse.mcneel.com/t/rhinocommon-createcontourcurves-method-returns-empty-array-curve/147130.

**Blender** — `bmesh.ops.bisect_plane(...)` returns cut verts/edges in a `'geom_cut'` key, confirmed
via a bug-tracker thread rather than Blender's own docs (both doc pages 403'd on fetch):
https://projects.blender.org/blender/blender/issues/119980.

**Recurring pattern across nearly every kernel-level implementation** (OCCT, and by inheritance
FreeCAD): raw output is an unordered edge/vertex soup requiring manual re-chaining into closed loops.
The clean pre-built polygon-loop abstraction only shows up in the slicer world (Clipper-based
`ExPolygon`) and the mesh-processing world (trimesh/meshcut). Rhino and Fusion 360 are the exceptions
with clean curve arrays out of the box.

## 3. Is "edit a stack of cross-section curves, then reconstruct" an established paradigm?

Yes, on two separate tracks, and they don't fully agree on how mainstream this is.

**Classical (non-ML) CAD/graphics — well-established, decades old.**
- Generalized cylinders: a cross-sectional B-spline curve swept along a skeleton curve, with the
  surface a NURBS interpolation of the cross-section sequence; user drags a 3D point, it's solved back
  into a cross-section-curve edit, surface regenerates. Chang, Lee, Kim, Hong, *The Visual Computer*
  1998: https://link.springer.com/content/pdf/10.1007/s003710050137.pdf
- "Implicit Generalized Cylinders using Profile Curves" (Grimm) confirms the profile-curve-swept-along-
  axis representation is well-established classical CAD theory:
  https://web.engr.oregonstate.edu/~grimmc/content/papers/is1999ig/is1999ig.pdf
- A 2017 paper on swept-surface editing (trajectory curve + deforming cross-section curves as edit
  handles) was found but its body was behind a paywall/login redirect — title/venue only, not
  independently verified: https://link.springer.com/article/10.1186/s13640-017-0207-0

**AI/ML-specific — real but niche, not mainstream.**
- **LoopDraw** (CVPR 2024 AI4CC workshop) is the closest direct hit: represents 3D shapes as a
  sequence of cross-sectional closed loops across multiple planes, used autoregressively for both
  synthesis *and editing*, explicitly framed by its authors as an alternative to point
  clouds/meshes/implicit functions/voxels. https://arxiv.org/abs/2212.04981
- **Curvy** (2024) — parametric polyline representation of sparse planar cross-sections + GNN
  reconstruction — but this is reconstruction-from-given-cross-sections, not confirmed as an *editing*
  workflow (only the abstract was readable). https://arxiv.org/abs/2409.00829
- Checked specifically and ruled out: **BSP-Net** (https://arxiv.org/abs/1911.06971) and **CSG-Stump**
  (https://arxiv.org/pdf/2108.11305) — neither uses cross-section curves; both operate on
  planes/convexes or 3D primitives respectively. Confirms cross-section-stack representations are a
  genuinely distinct family from the well-known CSG/primitive generative papers.
- The *dominant* CAD-generative-ML paradigm today is actually adjacent but different: sketch-extrude
  models (**DeepCAD**,
  https://openaccess.thecvf.com/content/ICCV2021/papers/Wu_DeepCAD_A_Deep_Generative_Network_for_Computer-Aided_Design_Models_ICCV_2021_paper.pdf;
  **Fusion 360 Gallery**, https://cdfg.csail.mit.edu/assets/files/Fusion360Gallery.pdf) — edit a
  *single* 2D profile then extrude, not a lofted *stack* of cross-sections.
- Aerospace/naval adjacent precedent: Bézier-GAN airfoil design operates on a single 2D profile's
  control points (https://arxiv.org/pdf/2006.12496); a ship-hull generative-design snippet suggests
  waterline-spline stacks (naval architecture's traditional stations/waterlines/buttocks
  representation) are being pulled into ML pipelines, but this was not independently
  fetched/verified — lower confidence, search-snippet only.

**Bottom line**: the classical geometric operation (loft/sweep reconstruction from an edited
cross-section stack) is old and universal. The *specifically AI-native* version of "a model edits
cross-section loops as its representation" is real but small — one clear paper (LoopDraw), sitting well
outside the mainstream generative-CAD-ML paradigm (which is sketch-extrude, not cross-section-stack).

## 4. Can real engineering section properties (I, J, centroid, section modulus) be computed from arbitrary extracted cross-section vertex data?

Yes — this is a solved problem with a mature, actively maintained library.

**`sectionproperties`** — https://github.com/robbievanleeuwen/section-properties (confirmed real,
active repo), docs at https://sectionproperties.readthedocs.io/ and
https://sectionproperties.readthedocs.io/en/stable/user_guide.html, PyPI at
https://pypi.org/project/sectionproperties/. It meshes arbitrary 2D cross-section geometry (quadratic
triangular FE mesh) and computes, per the readthedocs user guide: area, perimeter, mass, first/second
moments of area, elastic and plastic centroids, elastic/plastic section moduli, radii of gyration,
shape factors (all about global/centroidal/principal axes), **torsion constant J**, warping constant,
monosymmetry constants, shear centre (elastic and Trefftz), shear areas, and full stress-field analysis
under combined loading.

Critically for this project's use case, its geometry input directly matches "extracted vertex/curve
data from a CAD cross-section": built on Shapely `Polygon` objects, or raw `(x,y)` vertex lists (legacy
path), or direct CAD import via `Geometry.from_dxf()` and `Geometry.from_3dm()`/`from_rhino_encoding()`
for Rhino BREP — confirmed at
https://sectionproperties.readthedocs.io/en/v3.6.0/user_guide/geometry.html. One documented
limitation: `from_dxf` only imports one contiguous region per call
(https://github.com/robbievanleeuwen/section-properties/issues/246). One thing not fully verified this
session: an explicit end-to-end code example of feeding it a raw `(x,y)` tuple list — only the docs'
textual description that this path exists was confirmed.

Other libraries checked and confirmed to **not** do this: **Shapely** gives `.area`/`.centroid` but no
moment-of-inertia/section-modulus/torsion math — it's `sectionproperties`'s geometry substrate, not a
competitor. **PyNite** and **PyCBA** are structural-analysis libraries that take section properties
(A, I, J...) as direct scalar *inputs* rather than deriving them from geometry — confirmed from
source/docs (https://github.com/JWock82/Pynite, https://ccaprani.github.io/pycba/general.html) and
corroborated by a blog post describing the standard workflow as "compute in `sectionproperties`, feed
into PyNite" (https://www.viktor.ai/blog/177/5-powerful-python-libraries-every-structural-engineer-should-know).

Closed-form math backing this: the shoelace-formula area calculation generalizes cleanly to
vertex-summation formulas for I_x, I_y, I_xy and centroid (Green's theorem special case) — standard,
well-established (https://en.wikipedia.org/wiki/Second_moment_of_area, "Any polygon" section;
https://en.wikipedia.org/wiki/Shoelace_formula). Important distinction: **this closed form covers
area/centroid/I_xx/I_yy/I_xy with zero meshing, but not J** — torsion constant for arbitrary
(non-circular) shapes requires solving a Poisson/warping problem, which is exactly why
`sectionproperties` uses FEA rather than pure closed-form math for J, warping, and shear-center.

## 5. Bottom-line verdict — what's solved vs. what's a genuinely unimplemented combination

**Already solved, and directly usable off the shelf, piece by piece:**
- **Extracting a real (non-image) planar cross-section from a solid**: solved in build123d
  (`section()` → `Sketch`, clean and documented) and CadQuery (`section()`, proven in production
  DXF-export code). This is the most directly relevant precedent and it's genuinely first-class, not a
  workaround.
- **Cross-sectioning at scale as reusable geometry**: solved and battle-tested — PrusaSlicer's
  `ExPolygon`, trimesh's `section()`/`section_multiplane()`, Rhino's `CreateContourCurves`, Fusion
  360's `intersectWithSketchPlane`. Multiple independent, mature implementations across totally
  different ecosystems.
- **Reconstructing a solid from an edited stack of cross-section curves (loft/sweep)**: solved and
  decades-old in classical CAD (generalized cylinders, loft/sweep features in every mainstream kernel
  including build123d/CadQuery/OCCT themselves).
- **Computing real engineering section properties (area, centroid, I_xx, I_yy, section modulus, J,
  warping, shear center) from arbitrary extracted vertex/polygon data**: solved by `sectionproperties`,
  an active, purpose-built FE library that accepts exactly the kind of vertex/DXF/Rhino-BREP data a
  cross-section extraction would produce.

**Rough edges / not quite clean, reported consistently across agents:**
- True 3D plane-splitting (as opposed to a flat profile) has an open bug in CadQuery for arbitrary
  (non-axis-aligned) planes (issue #751).
- The raw-OCCT layer (and FreeCAD, which sits on it) hands back an unordered edge/vertex soup from
  `BRepAlgoAPI_Section` that must be manually re-chained into closed wires — build123d's `Sketch` and
  CadQuery's `section()` appear to already do this reassembly (that's their value-add over raw OCCT),
  but this wasn't explicitly confirmed as "always guaranteed clean loops" in either report.
- The closed-form section-property math (area/centroid/I) is free/cheap; J/warping/shear-center
  genuinely require an FE solve — not a detail to gloss over if torsion matters.

**What looks like a genuinely unimplemented combination**: nobody found a tool that chains all of
these together in one pipeline — i.e., (a) extract a real cross-section stack from a build123d/CadQuery
solid, (b) hand it to an AI model as an editable native representation the way LoopDraw does for its
own learned shapes, (c) let the AI edit that stack, and (d) reconstruct + re-verify engineering section
properties via something like `sectionproperties` in the loop. Each stage individually has solid,
sometimes multiple, precedents (per sections 1–4 above), and the classical geometric "edit profile →
loft/sweep → reconstruct" round-trip is old news — but the specific assembly of "AI edits extracted
cross-section geometry from a real CAD kernel, with engineering-property feedback closing the loop" was
not found as an existing implementation by any of the four searches. LoopDraw is the closest AI-side
analog, but it operates on its own learned shape representation, not on cross-sections pulled live out
of a build123d/CadQuery solid with section-property verification attached. That combination — not any
individual piece — is the part that looks open.

**Project relevance note (not from the research agents — added when filing this finding)**: the
`sectionproperties` piece (section 4) is directly actionable for this codebase's own
`packages/couplings/relations.py`, which today only has closed-form section-property formulas for
named rectangular/circular sections (see the grounding-repair workflow run the same day, Agent A4).
A real `section()` extraction feeding `sectionproperties` would let section-property relations
generalize to any subsystem's actual cross-section instead of an assumed simple shape.

---

## Raw agent reports (unedited)

### Agent E — build123d / CadQuery cross-section API specifically

## Findings

**build123d — `section()` operation**
URL: https://build123d.readthedocs.io/en/latest/operations.html (fetched this session)
build123d has a first-class `section()` Part-operation with signature:
```
section(obj: Part | None = None,
        section_by: Plane | Iterable[Plane] = Plane((0,0,0),(1,0,0),(0,-1,0)),
        height: float = 0.0,
        clean: bool = True,
        mode: Mode = Mode.PRIVATE) -> Sketch
```
It returns a **`Sketch`** — build123d's own 2D-geometry wrapper (a Compound of Faces backed by real
OCCT topology), not an image. Sketch/Face objects expose selectors like `.faces()`, `.edges()`,
`.vertices()`, and properties like `.area` and vertex `.X`/`.Y` (confirmed generically for build123d
geometry objects across the docs, e.g. the "Introductory Examples" page content returned by search,
which references filtering faces by `.area` and pulling `.X`/`.Y` off vertices — this was returned via
search summary, not a full page fetch, so treat that specific claim as lightly-verified). **Verdict for
build123d: yes, this is a clean, documented, programmatically-usable cross-section API.**

**CadQuery — `section()` and `split()`**
1. `Workplane.section()` exists and is used in production-style code. Verified directly in a real
   example file:
   URL: https://github.com/CadQuery/cadquery-contrib/blob/master/examples/tray.py (fetched this
   session)
   ```python
   exp.exportDXF(cq.Workplane().rect(Ws,Hs).extrude(1).section(),'sheet.dxf')
   exp.exportDXF(base.section(),'base.dxf')
   ...
   ```
   The result of `.section()` is passed straight into `exportDXF()` — i.e. it's real Face/Wire geometry
   that gets decomposed into DXF entities, not a picture. This is a genuine "do something programmatic
   with the cross section" example (flat-pattern/manufacturing export).
2. This is corroborated by a maintainer response in:
   URL: https://github.com/CadQuery/cadquery/discussions/1568 (fetched this session) — confirms
   `cq.Workplane().add(assy.toCompound()).section()` works on assemblies too, with the caveat from the
   maintainer that it "only shows what's on the plane" (a true intersection profile, not a solid clip)
   and that CQ's DXF export is 2D-only.
3. For actual 3D **splitting** (not just a flat profile) along an arbitrary plane, there's a real,
   documented rough edge:
   URL: https://github.com/CadQuery/cadquery/issues/751 (fetched this session) —
   `Workplane.split()` silently ignores a passed `Plane` object (splits on XY instead), and passing a
   rotated `Workplane` raises `ValueError: Null TopoDS_Shape`. The reporter's workaround is
   monkey-patching `wp.plane` before calling `split()`.
4. At the `Shape`-class level, I confirmed CadQuery's `split()` is implemented via
   **`BRepAlgoAPI_Splitter`** (not `BRepAlgoAPI_Section`), returning a `Shape` directly — from source:
   URL: https://cadquery.readthedocs.io/en/latest/_modules/cadquery/occ_impl/shapes.html (fetched this
   session)
   ```python
   def split(self, *splitters: Shape) -> Shape:
       split_op = BRepAlgoAPI_Splitter()
       return self._bool_op((self,), splitters, split_op)
   ```
   I could not find a dedicated `Shape.section()` OCCT-wrapper in the portion of that source file
   returned (it may exist further down, or `section()` may live only at the `Workplane`/legacy-`cq.py`
   layer — I could not fetch the full `cq.py` source this session; the fetch of
   `raw.githubusercontent.com/.../cq.py` truncated before reaching a `def section`, so I'm not
   claiming to have seen its body).
   **Verdict for CadQuery: yes for 2D cross-sections (`section()`, proven in real use exporting to
   DXF); real but rougher for true 3D plane-splitting (`split()` has open arbitrary-plane bugs).**

**Underlying OCCT kernel op**
URL: https://github.com/tpaviot/pythonocc-core/issues/1031 (fetched this session) — a user computing
`BRepAlgoAPI_Section(shape, plane_face)` gets a raw `TopoDS_Shape` back via `.Shape()` (a soup of
edges/wires, not a clean Face/Wire), and is asking how to convert that into a usable Curve/Wire. No
answer/resolution was visible on the page as fetched — so at the raw-OCCT layer, `BRepAlgoAPI_Section`
gives you real geometry but you must manually traverse it (e.g. `TopExp_Explorer`) to get usable Wires;
it is not exposed as a one-call clean API at that level. I found (via search, not fetched)
`pythonocc-demos/examples/core_topology_boolean.py` and `core_topology_local_ops.py` as demo files that
use `BRepAlgoAPI_Section`, but did not verify their contents this session.

**Third-party example using cross-section geometry programmatically**
URL: https://pypi.org/project/cqkit/ (fetched this session) —
`cqkit.extrude_xsection(obj, axis, extent, axis_offset=0, cut_only=False)` cuts a cross-section
through a solid along X/Y/Z and then **re-extrudes the exposed cross-sectional face** by a given extent
(or returns just the cut solid via `cut_only=True`). This is a concrete, real example of taking a
cross-section and doing further geometric construction with it (not just displaying it), though the
page didn't state internally whether it's built on CQ's `section()` or `split()` — that detail is
unconfirmed.

## Verdict

Solid prior art exists, and it clears the bar the question set: **build123d's `section()` returns a
real `Sketch` (Face/Wire-backed) object**, and **CadQuery's `section()` returns real geometry that a
live example (`tray.py`) feeds directly into DXF export** — both are genuinely programmatic, not
renders. The one soft spot found is CadQuery's `split()` for true 3D clipping along an arbitrary
(non-axis-aligned) plane, which has a documented, unresolved rough edge (issue #751) at the high-level
`Workplane` API, even though the underlying `Shape.split()`/`BRepAlgoAPI_Splitter` plumbing is sound.

---

### Agent F — cross-section extraction as real geometry in OTHER CAD tools/kernels

## Findings: Cross-section extraction as real geometry, across CAD ecosystems

### 1. 3D-printing slicers — yes, this is the deepest, most battle-tested prior art

**CuraEngine** — https://ultimaker.github.io/CuraEngine/docs/slicing.html (fetched)
Confirms the internal pipeline: triangles are cut into line segments per Z-layer, then loose segments
are stitched end-to-end (by proximity + consistent winding direction) into closed **polygons**. This is
literally "repeated cross-sectioning of a solid at many Z-heights → vertex-loop data," done millions of
times a day. Source lives at `src/slicer.cpp` (found via search, not fetched directly):
https://github.com/Ultimaker/CuraEngine/blob/main/src/slicer.cpp. Caveat: this is an internal C++
pipeline stage feeding wall/path generation, not exposed as a general-purpose "give me the polygon"
library API for arbitrary downstream code — it's baked into the slicing monolith.

**PrusaSlicer / libslic3r** —
https://github.com/prusa3d/PrusaSlicer/blob/master/src/libslic3r/ExPolygon.hpp (fetched)
Each layer slice is an `ExPolygon`: a `Polygon contour` (CCW outer boundary) + `Polygons holes` (CW
inner loops) — literally a point-list-with-holes structure, built on the Clipper library. This is
closer to a clean, reusable data type than Cura's — `ExPolygon`/`ExPolygons` are used throughout the
codebase for area, offset, boolean, and medial-axis operations, i.e., it's designed as real geometry to
compute on, not just render.

Verdict for this angle: **solid, mature prior art** — but framed entirely as "slicer internals," not
exposed as a general "cut this solid, get me a polygon" public API. You'd have to either vendor/embed
libslic3r's geometry types or reimplement the pattern (mesh → per-plane line segments → stitched
polygon-with-holes), not call a documented service.

### 2. FreeCAD

- **Part CrossSections tool (GUI)**:
  https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Part_CrossSections.md (fetched) —
  cuts a shape with one or more planes parallel to a global plane; produces one output object per
  operation but the doc does not state whether it's Wire/Face/Sketch, and explicitly says the result is
  **not parametric** (a static snapshot, not linked back to the source shape). No Python code sample is
  shown on that page.
- **Scriptable path (the real answer)**: `Part.Shape.section()` / `TopoShape.section()` — confirmed via
  https://freecad-python-stubs.readthedocs.io/en/latest/autoapi/Part/_TopoShape/ (fetched): signature
  `section(tool, [approximation=False]) -> Shape` (or a tuple of tools), "Section of this with a given
  (list of) topo shape," optionally approximated to a C1 BSpline. Since FreeCAD's Part module is a thin
  Python wrapper over OpenCASCADE, this **is** `BRepAlgoAPI_Section` underneath (see #4) — it returns a
  compound of edges/vertices, which you then have to re-order into wires yourself (same caveat as raw
  OCCT).
- Attempted to fetch the canonical wiki page at `wiki.freecadweb.org/Part_SectionCross` — DNS failure
  (domain likely retired/redirected); `wiki.freecad.org/Part_CrossSections` returned an "Access Denied"
  page when fetched, so I could not independently confirm the GUI tool's exact output type from
  FreeCAD's own current wiki.

Verdict: **real, documented, scriptable** (`Part.Shape.section()`), returning actual
`Part.Edge`/`Part.Vertex` geometry — but it hands you an unordered edge soup, not a clean closed
polygon, matching the general OCCT pattern.

### 3. Fusion 360 and SolidWorks

- **Fusion 360**:
  https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/SketchIntersect_Sample.htm (fetched) —
  confirms `sketch.intersectWithSketchPlane(entities)` is a real scripting API (Python/C++/TypeScript
  samples given) that "intersects the specified entities with the sketch plane and creates sketch
  geometry that represents the intersection," returning actual sketch curve entities you can then read
  points/curves off of. This is explicitly framed as programmatic, not just the interactive
  "PROJECT > INTERSECT" UI command (corroborated by a second, separate Autodesk support page found via
  search:
  https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/How-to-create-a-sketch-of-a-cross-section-of-a-3D-Model-in-Fusion-360.html,
  describing the UI equivalent).
- **SolidWorks**: https://www.codestack.net/solidworks-api/geometry/slice-body/ (fetched) — a real,
  working macro example, but it does **not** return curve/edge data. It uses `Body2.Operations2()` with
  `SWBODYINTERSECT` between the solid and a constructed planar surface, and the result is a
  **sheet-body `Body2` object** per slice (you can then query `GetMassProperties()` for area etc.), not
  a wire/curve/polygon primitive. Getting to actual boundary-curve data would require an extra step
  (e.g., pulling edges off that sheet body). I found no SolidWorks API page documenting a direct
  "GetSectionCurves"-style call returning curves; only the sheet-body-intersection pattern and the
  separate "Intersection Curves" *feature* (which creates a permanent, parametric sketch feature in the
  tree, per https://help.solidworks.com/2025/english/solidworks/sldworks/c_Intersection_Curves.htm,
  found via search but not fetched in full).

Verdict: **Fusion 360 has a clean, well-documented API for this** (sketch curves out); **SolidWorks has
a real but curve-not-quite-there API** — you get a sheet body, one step removed from loop/curve data.

### 4. Standalone libraries built specifically for mesh-plane cross-sections

- **trimesh** (Python) — https://trimesh.org/section.html (fetched):
  `mesh.section(plane_origin=..., plane_normal=...)` returns a **3D `Path3D`** in the mesh's original
  frame; `.to_planar()` converts to a 2D `Path2D` (with `.vertices`, `.entities`, `.polygons_full`).
  `section_multiplane()` returns a list of `Path2D` objects — explicitly built for repeated-height
  slicing (the docs frame this exactly as "3D printing"-style batch slicing), and the returned polygons
  are meant for downstream computation (Shapely intersection, medial axis, area), not just plotting.
  This is probably the single closest match to "give me a mesh + a plane, get real processable boundary
  geometry" as a *general-purpose, well-known Python library* (trimesh is very widely used).
- **meshcut** — https://github.com/julienr/meshcut (fetched): smaller, purpose-built library;
  `cross_section()` takes vertex/face arrays + plane origin/normal, returns a list of numpy polyline
  arrays (3D points) forming the intersection boundary. Modest but real (112 stars/28 forks at fetch
  time); narrower scope than trimesh, does one thing only.
- **OpenCASCADE (OCCT)** — https://dev.opencascade.org/content/how-get-cross-section-shape (fetched
  forum thread): the canonical low-level answer for real BREP kernels —
  `BRepAlgoAPI_Section(shape, plane)`, `.Build()`, `.Shape()` gives a compound of edges/vertices;
  commonly needs post-processing (`ShapeAnalysis_WireOrder`, or manual edge-chaining) to become a clean
  wire, a friction point explicitly called out in the OCCT forum discussion (also found:
  https://dev.opencascade.org/content/how-build-wires-brepalgosection, via search, not fetched in
  full).
- **Rhino/RhinoCommon** — `Brep.CreateContourCurves(Brep, Plane)` and
  `Mesh.CreateContourCurves(...)`, signature
  `public static Curve[] CreateContourCurves(Brep brepToContour, Plane sectionPlane)` confirmed via
  search-result text quoting the official API page
  (https://developer.rhino3d.com/api/rhinocommon/rhino.geometry.brep/createcontourcurves — page
  fetched directly but rendered only a bare title client-side, so the signature itself is corroborated
  from the search snippet plus a live usage/bug thread at
  https://discourse.mcneel.com/t/rhinocommon-createcontourcurves-method-returns-empty-array-curve/147130,
  found via search). Returns a plain `Curve[]` — real, clean, scriptable curve geometry, the tidiest
  API surface found in this whole survey.
- **Blender** — `bmesh.ops.bisect_plane(bm, geom, dist, plane_co, plane_no, ...)` returns a dict with a
  `'geom_cut'` key holding the new verts/edges from the cut; confirmed via a live bug report thread
  https://projects.blender.org/blender/blender/issues/119980 (found via search) describing exactly that
  return key and a known edge-case bug in it. I could not directly fetch Blender's own docs pages (both
  the current and 2.79b `bmesh.ops.html` pages returned HTTP 403 to WebFetch), so the parameter/return
  list is corroborated via the bug tracker's real-world usage rather than the primary doc text itself.

### Verdict

**Yes — solid prior art exists for "cut a solid, get real vertex/curve/polygon data, not a picture."**
It spans (a) mature production slicer internals (PrusaSlicer's `ExPolygon`, Cura's stitched polygons)
that already do exactly this at scale in production, (b) general BREP-kernel primitives (OCCT
`BRepAlgoAPI_Section`, exposed through FreeCAD's `Part.Shape.section()`) that return raw edge/vertex
compounds needing wire-reassembly, (c) commercial CAD scripting APIs with varying cleanliness (Fusion
360's `intersectWithSketchPlane` → real sketch curves is clean; SolidWorks's `SWBODYINTERSECT` → sheet
body is one step removed; Rhino's `CreateContourCurves` → `Curve[]` is the cleanest of all), and (d)
purpose-built open-source mesh libraries (trimesh's `section()`/`section_multiplane()` returning
`Path3D`/`Path2D`, and the smaller meshcut) that are explicitly designed for downstream computation,
not visualization. The recurring theme across nearly every kernel-level implementation (OCCT, and by
inheritance FreeCAD) is that the raw output is an **unordered edge/vertex soup that must be re-chained
into closed loops yourself** — the polygon-loop abstraction only comes pre-built in the slicer world
(Clipper-based `ExPolygon`) and in the mesh-processing world (trimesh/meshcut).

---

### Agent G — AI / generative modeling using cross-section-stack shape representations

## Research Findings: Cross-Section-Stack Representations for 3D Shape Editing

### Direct hits — cross-section/loop stacks as an editable representation

**1. LoopDraw (CVPR 2024 AI4CC workshop)** — https://arxiv.org/abs/2212.04981
Represents 3D shapes as **a sequence of cross-sectional closed loops** across multiple planes,
organized hierarchically, used in an autoregressive generative model for both **synthesis and
editing**. The paper explicitly argues loops are "an intuitive and natural primitive for analyzing and
editing shapes" because "simple loop manipulations (such as shifts) result in significant structural
changes to the geometry" — i.e., editing at the loop/cross-section level rather than
per-vertex/per-voxel. It's positioned by the authors as a distinct alternative to point clouds, meshes,
implicit functions, and voxels. This is the closest match found to "AI model edits cross-section curves
as its native representation." **This is real, current (2024) ML research doing almost exactly what the
question describes.**

**2. Direct manipulation of generalized cylinders based on B-spline motion** (Chang, Lee, Kim, Hong —
*The Visual Computer*, 1998) — found via ResearchGate/Springer listing,
https://link.springer.com/content/pdf/10.1007/s003710050137.pdf
Classical (non-ML) CAD prior art, very close conceptually: a generalized-cylinder solid is represented
as a **cross-sectional B-spline curve swept along a skeleton (trajectory) curve**; the output surface
is a NURBS surface **interpolating the sequence of cross-section curves**. The user drags a point on
the 3D surface, which is solved back into a modification of the cross-section curve + sweep motion, and
the surface is regenerated. This is a textbook "edit the cross-section, reconstruct via lofting/
sweeping" workflow — just decades old and non-learned.

**3. Surface editing using swept surface 3D models** (EURASIP J. Image and Video Processing, 2017) —
https://link.springer.com/article/10.1186/s13640-017-0207-0 (link resolved to a login/paywall page via
redirect, so I could not read the body text — reporting title/venue only, not verified content beyond
the search-snippet description: it extracts a trajectory curve plus deforming cross-sectional 2D curves
from a swept-surface model and edits them as handles for controlling the geometry).

**4. Curvy: A Parametric Cross-section based Surface Reconstruction** (2024) —
https://arxiv.org/abs/2409.00829
Represents shapes via a **compact parametric polyline representation of sparse planar cross-sections**
and uses a GNN to reconstruct a point cloud/surface from those cross-sections. This is
reconstruction-from-cross-sections, generalized across object classes via learning — but the abstract
(which is all I could read; the PDF text wasn't extractable) does **not** describe an editing workflow,
only reconstruction from given cross-sections. Relevant as representation prior art, not confirmed as
an editing paradigm.

### Adjacent/supporting prior art

- **Ship-hull generative design** (found via the MDPI ship-design search result, not independently
  fetched/verified beyond the search snippet): waterline splines — 2D cross-section curves of a hull at
  fixed vertical intervals — used as one of the representations jointly trained in a conditional
  multimodal autoencoder alongside point clouds. Naval architecture has long used
  "waterlines/buttocks/stations" (literally cross-section stacks) as the native hull-design
  representation; this snippet suggests it's now being pulled into ML pipelines too, but I did not
  fetch the underlying paper directly, so treat this as lower-confidence.
- **Bézier-GAN for airfoil design** (https://arxiv.org/pdf/2006.12496) and related aerodynamic-shape
  GAN work — generative models operating directly on parametric curve control points of a single 2D
  cross-section (airfoil), not a 3D stack, but establishes "edit the profile curve parametrically,
  GAN-generate/optimize it" as an established sub-field (aerospace shape optimization).
- **Sketch-extrude CAD generative models — DeepCAD**
  (https://openaccess.thecvf.com/content/ICCV2021/papers/Wu_DeepCAD_A_Deep_Generative_Network_for_Computer-Aided_Design_Models_ICCV_2021_paper.pdf)
  and **Fusion 360 Gallery**
  (https://cdfg.csail.mit.edu/assets/files/Fusion360Gallery.pdf): represent CAD parts as sequences of
  2D sketch profiles (closed curve loops) + extrude operations, generated/edited at the sketch-curve
  level, then a kernel builds the solid. This is the dominant paradigm in CAD-generative ML today, and
  it's structurally close to "edit a profile curve, reconstruct the solid" — but it's
  single-profile-extrude, not a stack-of-cross-sections-lofted-together representation.
- **Generalized cylinders / profile curves in classical CAD** —
  https://web.engr.oregonstate.edu/~grimmc/content/papers/is1999ig/is1999ig.pdf ("Implicit Generalized
  Cylinders using Profile Curves," Grimm) confirms the profile-curve-swept-along-axis representation is
  decades-old, well-established CAD theory, independent of any ML angle.

### Checked specifically as requested: BSP-Net and CSG-Stump

- **BSP-Net** (https://arxiv.org/abs/1911.06971) — does **NOT** use cross-section curves. It represents
  a shape as a set of **hyperplanes** grouped via a binary-space-partitioning tree into **convex
  primitives**, unioned into a mesh. The intermediate representation is planes/convexes, not 2D profile
  curves.
- **CSG-Stump** (https://arxiv.org/pdf/2108.11305, project page
  https://kimren227.github.io/projects/CSGStump/) — does **NOT** use cross-section curves either. It's
  a 3-level CSG-like structure (complement layer → intersection layer → union layer) over **3D
  primitives** (boxes, spheres, etc.), not planar profiles.

So neither of the two well-known CSG/primitive-based generative-shape papers uses a cross-section-stack
representation — confirming these are a genuinely different family from what the question is asking
about.

### Verdict

**Yes, solid prior art exists**, on two tracks:
1. **Classical (non-ML) CAD/graphics**: "edit cross-section/profile curves → loft or sweep to
   reconstruct the solid" is an established, decades-old paradigm — generalized cylinders, swept
   surfaces, and loft features in every mainstream CAD kernel (this part is well-known/undisputed and
   barely needed verification).
2. **AI/ML-specific**: it is a real but comparatively niche and recent representation choice, with
   **LoopDraw (2024)** as the clearest direct match — an ML model that natively generates/edits 3D
   shapes as stacks of cross-sectional loops, explicitly framed by its authors as an alternative to
   voxels/point-clouds/meshes/implicit fields. It sits alongside — but is much less mainstream than —
   the sketch-extrude-profile paradigm (DeepCAD, Fusion 360 Gallery) which is the dominant profile-
   curve-based generative-CAD approach today. It is not one of the "big five" commonly cited
   3D-generative-ML representations (voxel/point-cloud/mesh/implicit-SDF/CSG-program); it's a smaller,
   less-established sub-direction, but it is not novel/unprecedented either.

---

### Agent H — section-property computation from arbitrary extracted cross-section geometry

## Findings: Section-property computation from arbitrary cross-section geometry

**Verdict up front: solid, mature prior art exists.** This is a solved problem with an actively
maintained open-source Python library built exactly for it, plus the underlying closed-form math is
standard and confirmed.

### 1. `sectionproperties` — real, and it's exactly this

- **GitHub**: https://github.com/robbievanleeuwen/section-properties — "Analysis of an arbitrary
  cross-section in python using the finite element method." Confirmed real, active repo.
- **Docs**: https://sectionproperties.readthedocs.io/ and
  https://sectionproperties.readthedocs.io/en/stable/user_guide.html
- **PyPI**: https://pypi.org/project/sectionproperties/
- **Author's blog walkthrough**:
  https://robbievanleeuwen.github.io/finite%20element%20analysis/cross-section-analysis/
- **VIKTOR.AI writeup**:
  https://www.viktor.ai/blog/178/automate-structural-analysis-of-cross-sections-using-python-and-section-properties

**What it does**: Takes arbitrary 2D cross-section geometry, meshes it (quadratic triangular FE mesh),
and computes a full structural-engineering property set via finite-element analysis (not just
closed-form). Confirmed feature list from the docs (readthedocs user guide):

- Global axis: area, perimeter, mass, first moments of area, second moments of area, elastic centroid
- Centroidal axis: second moments of area, elastic section moduli, yield moment, radii of gyration,
  plastic centroid, plastic section moduli, shape factors
- Principal axis: same set as above about principal axes
- Warping properties: **torsion constant (J)**, warping constant, monosymmetry constants
- Shear properties: shear centre (elastic and Trefftz's methods), shear areas (global and principal
  axis)
- Stress analysis: full cross-sectional stress fields under combined axial/bending/torsion/shear,
  Mohr's circle output

**Input formats — this is the key part for this question**: geometry is built on Shapely `Polygon`
objects and can be constructed multiple ways (confirmed from readthedocs geometry page
https://sectionproperties.readthedocs.io/en/v3.6.0/user_guide/geometry.html and the v3.6.0 user guide):
- Directly from a `shapely.Polygon` object
- From raw lists of `(x, y)` vertex points + facets/control points (legacy method)
- Imported from CAD: `Geometry.from_dxf()` for DXF files, `Geometry.from_3dm()` /
  `from_rhino_encoding()` for Rhino `.3dm`/BREP
- One documented limitation (GitHub issue
  https://github.com/robbievanleeuwen/section-properties/issues/246): `from_dxf` only imports one
  contiguous region per call currently — multi-region DXFs need multiple imports + boolean union.

This directly matches the scenario described: extract a real cross-section from CAD as vertex/polygon
data → feed it in → get real I/J/section modulus/centroid, for **any** shape, not just named
primitives.

### 2. Shapely — confirmed role: geometry container, NOT a structural-properties engine

- Shapely docs: https://shapely.readthedocs.io/en/stable/manual.html,
  https://shapely.readthedocs.io/en/2.1.2/reference/shapely.centroid.html
- Confirmed: Shapely natively gives you `.area` and `.centroid` (and `.exterior`/`.interiors` point
  access) but has **no built-in moment-of-inertia / section-modulus / torsion-constant computation**.
  It's a general-purpose 2D computational-geometry library.
- `sectionproperties` uses Shapely purely as its geometry representation/boolean-ops layer, then does
  its own FE-based structural analysis on top. So the pattern in the wild is "Shapely for polygon
  representation" + "sectionproperties (or your own shoelace-derived code) for the actual engineering
  numbers" — not Shapely alone doing structural math.

### 3. PyNite / PyCBA — confirmed: they do NOT derive section properties from geometry

- PyNite (https://github.com/JWock82/Pynite, via search) is a 3D FE structural-analysis library that
  takes member section properties (A, I, J, etc.) as **inputs you supply**; it does not derive them
  from cross-section geometry itself. Community material (e.g.
  https://www.viktor.ai/blog/177/5-powerful-python-libraries-every-structural-engineer-should-know,
  found via search) explicitly describes computing properties in `sectionproperties` first, then
  feeding those numbers into a PyNite model.
- PyCBA docs (https://ccaprani.github.io/pycba/, https://ccaprani.github.io/pycba/general.html):
  confirmed it takes flexural rigidity `EI` as a **direct scalar input** (e.g.,
  `EI = 30.0e6 * 0.4 * 0.9**3 / 12` in their own example) — no geometry-to-property derivation at all.
  This is a clean negative finding: beam-analysis libraries assume you already have section properties
  in hand; `sectionproperties` is the tool that fills that gap from geometry.

### 4. Closed-form math: shoelace formula generalizes cleanly to I_xx/I_yy/centroid — confirmed well-established

- Shoelace formula (area): https://en.wikipedia.org/wiki/Shoelace_formula,
  https://mathworld.wolfram.com/ShoelaceFormula.html — standard, well-established.
- Second moment of area, arbitrary polygon: https://en.wikipedia.org/wiki/Second_moment_of_area,
  section "Any polygon." Confirmed closed-form vertex-summation formulas exist for I_x, I_y, and I_xy,
  e.g.:
  - I_y = (1/12) Σ (xᵢyᵢ₊₁ − xᵢ₊₁yᵢ)(xᵢ² + xᵢxᵢ₊₁ + xᵢ₊₁²)
  - I_x = (1/12) Σ (xᵢyᵢ₊₁ − xᵢ₊₁yᵢ)(yᵢ² + yᵢyᵢ₊₁ + yᵢ₊₁²)
  - I_xy = (1/24) Σ (xᵢyᵢ₊₁ − xᵢ₊₁yᵢ)(xᵢyᵢ₊₁ + 2xᵢyᵢ + 2xᵢ₊₁yᵢ₊₁ + xᵢ₊₁yᵢ)
  - Wikipedia explicitly states this is "related to the shoelace formula and can be considered a
    special case of Green's theorem" — i.e., established classical 2D statics/geometry, not a novel or
    shaky derivation. Same sum-over-vertices pattern as the shoelace area formula, so it generalizes
    cleanly.
- Note: this closed-form vertex formula gives you area/centroid/I_xx/I_yy/I_xy directly with zero
  meshing. It does **not** by itself give you the torsion constant J for arbitrary (non-circular)
  shapes — J for general cross-sections requires solving a Poisson/warping-function problem (this is
  exactly why `sectionproperties` uses FEA rather than pure closed-form for J, warping, and shear-center
  properties don't have a simple polygon-vertex closed form the way area/I/centroid do). This is a
  meaningful distinction if J matters for the use case — area/centroid/I_xx/I_yy are cheap closed-form,
  but J/warping/shear-center genuinely need an FE (or at least numerical) solve.

### One thing not fully verified this session
I did not find/verify an explicit worked code example of `sectionproperties` ingesting a raw Python
list of `(x,y)` tuples end-to-end (only the documentation's textual description that this "legacy"
input path exists, from the v3.6.0 geometry guide). If the exact call signature is needed, worth a
direct doc/API fetch of `sectionproperties.pre.geometry` before depending on it in a design.

**One-line verdict**: Yes — solid prior art exists. `sectionproperties` (real, active, FE-based,
MIT-licensed on GitHub/PyPI) already does exactly "arbitrary polygon/CAD-derived cross-section in →
area/centroid/I_xx/I_yy/J/section-modulus/warping out," accepting Shapely polygons, raw vertex lists,
and DXF/Rhino imports; and separately, the closed-form vertex-sum generalization of the shoelace
formula for area/centroid/I_xx/I_yy/I_xy is classical, well-established math (Green's theorem), though
J/warping/shear-center still require an FE-style solve rather than a pure closed form.
