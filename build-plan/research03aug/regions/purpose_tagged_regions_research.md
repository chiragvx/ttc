# Purpose-tagged regions (routing-allowed / reserved-for-component / keep-out) — prior-art research

**Date:** 2026-08-03
**Status:** Exploratory research only — nothing here is built or scheduled. Captured so future work
doesn't re-derive it from scratch.

## Context / the question being evaluated

After modeling a complete assembly (e.g. a weather-station enclosure with mounted components inside
it), there is leftover 3D space — some of it should be usable for cable/wire ROUTING, some of it
should be marked RESERVED (allocated for a future part/component, do-not-route-through-here). This is
a post-hoc partition of space, computed AFTER the geometry exists, not authored by hand. Question: can
build123d/CadQuery's existing tools do this, and if not, what's the grounded (non-AI) path to building
it, based on how other established tools solve the same problem?

Four parallel research agents (Sonnet 5, via the Workflow tool) investigated: (M) build123d/CadQuery's
native support for deriving leftover volume and tagging it, (N) how PCB/EDA, BIM, mechanical, and
aerospace tools already solve this exact problem, (O) deterministic algorithms for classifying 3D space
into typed regions, (P) the correct terminology map and whether OCCT itself (the kernel under
build123d) has a native named-attribute-on-shape mechanism. A fifth agent synthesized the four raw
reports. Citation status (directly fetched vs. search-snippet-only vs. recalled/unverified) is
preserved exactly as each agent reported it. No URL below was invented.

**Headline finding**: nobody has built this specific thing for build123d/CadQuery — but the
primitives it would be built from are real and confirmed: boolean Cut for leftover-volume derivation,
and (this is the useful discovery) **build123d's `Shape.label` is a real, persistent, per-solid string
attribute** — not purpose-built for regions, but directly repurposable for exactly this. Multiple
established domains (PCB keep-out zones, BIM's `IfcSpace`/`IfcZone`, mechanical Envelope features) solve
the identical conceptual problem, giving a concrete terminology and design pattern to borrow from rather
than inventing one from scratch.

---

## Synthesis (read this first)

# Purpose-tagged leftover-space regions in build123d — synthesis of 4 research passes

## 1. Can build123d/CadQuery already do this natively?

**Short answer: the two primitives you'd need both exist and are real, but nobody has been found combining them for this purpose — you'd be assembling this from scratch, not adopting a pattern.**

**Boolean-derived leftover volume.** Both libraries wrap OCCT's `BRepAlgoAPI_Cut`. `Mode.SUBTRACT` (and the `-` operator) is confirmed, real, and documented: *"Mode.SUBTRACT, Mode.INTERSECT, and Mode.REPLACE subtract, intersect, or replace (from) the builder's object"* (https://build123d.readthedocs.io/en/latest/key_concepts_builder.html). So `interior_cavity − union(placed_components)` is mechanically standard. There is one real, sourced caveat worth carrying forward: the OCCT wiki (https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations) states the cut argument *"should not be self-interfered, i.e. all sub-shapes... that have geometrical coincidence... must share these entities"* — meaning if your placed components merely touch/overlap without shared topology (e.g., independently-authored brackets flush against the same wall), you should `Fuse` them into one clean tool solid before `Cut`-ing, rather than passing a raw Compound of touching solids. A stronger, more specific version of this claim ("solids in a Compound cut-argument must not touch at all") surfaced only via an AI search summary attributing it to old.opencascade.com — a direct fetch of that URL found no such text, so that stronger claim is **unverified, treat as unconfirmed**.

Despite targeted searches (`build123d "remaining free space"`, `cadquery "leftover space"`, `build123d keepout enclosure`, etc.), **no example was found — in either library — of anyone computing "leftover/routable free space in an enclosure" via boolean subtract.** This is a genuine "found nothing," not a padded negative.

**Tagging/metadata.** build123d has a real, directly-confirmed generic label mechanism: every `Shape` (Solid, Compound, Face, …) carries a persistent `.label` string, plus `color` and (on `Compound`) `material` — confirmed via https://build123d.readthedocs.io/en/latest/assemblies.html: *"In order [to] keep track of objects one can assign a `label` to all Shape objects"* … *"Labels are just strings with no further limitations."* CadQuery's closest analog is `Assembly.add(part, name="...", color=cq.Color(...))` (https://cadquery.readthedocs.io/en/latest/assy.html). CadQuery also has `Workplane.tag("X")`, but this was specifically checked and found to be a **construction-time checkpoint of workplane state for `workplaneFromTagged()` re-selection**, not a durable attribute on an exported solid (https://cadquery.readthedocs.io/en/latest/classreference.html) — not what you want for "query this region later as reserved."

**Verdict:** Neither library has a purpose-built "named region"/"keep-out volume" concept. You'd repurpose the generic `label`/`name` string field yourself — e.g., loop over the disjoint solids that fall out of the Cut result and set `.label = "routing_allowed"` or `.label = "reserved"` per solid based on your own classification logic. The primitives are real; the combination is not prior art anywhere found.

## 2. How other CAD/EDA/BIM tools solve the same problem

**PCB/EDA — real and mature, but fundamentally 2D-per-layer, not a solid 3D volume.**
- KiCad keepout areas are drawn as polygon outlines with three togglable restriction flags (no-tracks/no-vias/no-copper-pour); DRC enforces them (`pcbnew_zones.adoc`, fetched). Purpose-naming (e.g. "Antenna Keepout") is a documented *convention* (KLC F4.5), not a schema field — and that page 403'd on direct fetch, so treat as search-level confirmation only. True 3D-body/height-based keepout is a known, still-open KiCad gap (issues `kicad-library#1443`, `kicad#4503`).
- Altium's **Region Keepout** is likewise a 2D polygon on a layer (fetched: pcb-region-keepout-properties). Altium's **3D Bodies** feature — actual imported solid geometry checked in real time for component-to-component/component-to-housing collisions via the Component Clearance rule (fetched: pcb/3d-bodies) — is the closest thing to a true 3D keepout in mainstream PCB CAD, but it's interference-checking against real geometry, not a "zone" database entity.

**BIM/IFC — the strongest formal match found, across both reports that looked at it.**
- `IfcSpace`: geometry can be a 2D footprint or a full 3D Brep; purpose carried via `ObjectType` (free text) and `PredefinedType` (enum + USERDEFINED escape hatch). Critically, `CompositionType = PARTIAL` is explicitly defined as *"a subdivision of a space"* — i.e., a reserved sub-area of a larger space, which is exactly the "region within a region" pattern in your question.
- `IfcZone`: pure grouping (`IfcRelAssignsToGroup`) — explicitly *"does not have its own shape representation"* — purpose via `ObjectType` (e.g. `FireCompartment`, `ElevatorShaft`, `RisingDuct`).
- `IfcSpatialZone` (IFC4+): unlike `IfcZone`, does carry its own placement/geometry and can overlap other spatial structure — used for thermal/construction/lighting/usable-area zones.
- One report fetched the IFC4.3 docs (https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcSpace.htm, .../IfcZone.htm); the other independently fetched an older IFC2x3 TC1 mirror for `IfcZone` (https://iaiweb.lbl.gov/Resources/IFC_Releases/R2x3_final/ifcproductextension/lexical/ifczone.htm) plus a GitHub issue discussing `IfcZone` vs `IfcSpatialZone` (https://github.com/buildingSMART/IFC4.3.x-development/issues/1), which notes the spec itself flags these two entities as confusingly overlapping. Both independently arrive at the same substantive conclusion, just different spec vintages — not a real conflict, worth noting only because the URLs differ.

**Mechanical CAD Envelope features — real, confirmed for SolidWorks, unconfirmed for Fusion 360.**
An **Envelope** is a normal solid-body component flagged to be excluded from BOM/manufacturing output but still participates in ordinary interference detection — i.e., real B-rep geometry with a "don't manufacture me, but do check clearance against me" flag. **Envelope Publisher** (SW 2020+) propagates an envelope down into subassemblies for multi-level coordination (fetched: https://www.cati.com/blog/solidworks-2020-whats-new-assembly-envelope-publisher/; the official help.solidworks.com page was title-confirmed via search only, 403'd on fetch). Fusion 360's equivalent was **not investigated this session** (search budget ran out) — do not treat any claim about Fusion 360 here as confirmed.

**Aerospace "installation envelope"/keep-out zone as a formal standard — not established.** One report searched directly for a citable standard (NASA-STD, SAE, MIL-STD, ECSS, CubeSat Design Spec) and found nothing fetchable — a CubeSat Design Spec PDF guess 404'd, and an Analog Devices "Keep-Out Zone" glossary page was found by search but every fetch attempt timed out, so its content (apparently PCB/thermal-context per the snippet, not aerospace) is unverified. The other report separately confirms "keep-out zone" (sensor **pointing** sense) and "keep-in zone" (robotics, from patent filings) as real terms in aerospace/robotics contexts, but that's terminology, not a materialized "installation envelope" standard. **Net: this specific sub-question — a formal aerospace installation-envelope standard — remains genuinely unresolved by this research**, flagged consistently by both reports that touched it.

## 3. Deterministic algorithms: is "compute the region, then route in it" how real tools work?

**Split answer, well-sourced on both halves.**

*Yes — "compute free space as its own step before anything routes through it" is a real, mainstream paradigm*, confirmed three independent ways:
- Motion-planning **cell decomposition** (CMU 16-735 lecture notes, Howie Choset, fully fetched: https://www.cs.cmu.edu/~motionplanning/lecture/Chap6-CellDecomp_howie.pdf): exact methods (trapezoidal/cylindrical/Morse decomposition) partition free space precisely along obstacle boundaries; approximate methods (quadtree/octree/voxel grids) label cells free/occupied/mixed — *then* A*/Dijkstra searches the resulting adjacency graph.
- **C-IRIS** (arXiv:2302.12219, abstract fetched): a modern (2023) method using SDP-based convex optimization to generate large, *rigorously certified* collision-free convex polytopes in configuration space, computed once and reused by planners afterward — the same algorithmic pattern, in configuration rather than Cartesian space.
- **Dessia's industrial CAD wiring-harness router** (fully fetched, https://www.dessia.io/case-studies/ai-harness-routing-generative-design-cad) — the single best real-world match to your actual question: it converts a CAD assembly into a voxel-based "available routing space" model (hard constraints = prohibited zones, soft constraints = areas to avoid) **as an explicit first stage**, then runs pathfinding/optimization over that pre-computed grid. This is industrial mechanical CAD, not robotics, doing exactly the two-stage pattern the question asks about.
- Counter-example (explicitly flagged **unverified this session, recalled from general knowledge only**): RRT/PRM sampling-based planners do pointwise/edge-wise collision queries on the fly and never materialize a persistent free-space object at all — the standard "no" case.

*But — materializing free space as an exact continuous B-rep solid via boolean subtraction (as opposed to a voxel/cell grid) has no established named algorithm or shipped tool doing it for a "tag as routable" purpose*, and there's actual evidence pointing the other way:
- **USPTO US11615218B2** ("Mesh void space identification…", fully fetched: https://patents.google.com/patent/US11615218B2/en) — the one patent found that squarely targets void-space-in-CAD — explicitly **avoids** producing a void-space solid, instead using coarse-to-fine discretization to find valid seed points inside the void, stating this avoids having to enclose/model the void as a real geometric body.
- The two closest academic titles (voxel-based unoccupied-space computation — ResearchGate, https://www.researchgate.net/publication/267647297_Voxel-Based_Approach_for_Computation_and_Optimization_of_Unoccupied_Space_in_CAD_Assemblies; octree spatial-conflict modeling — Springer, https://link.springer.com/chapter/10.1007/978-3-030-42250-9_2) both use voxel/octree grids, not exact solids — both paywalled, snippet-level only.
- The mirror-image operation *is* shipped: Autodesk Inventor's `CreateInterference` VBA macro (fully fetched, https://www.cadforum.cz/en/creating-an-interference-solid-from-conflicting-inventor-parts-tip8347) runs boolean intersection on colliding bodies and adds the result as a permanent new solid part — confirming boolean-materialization of a derived "special" region is a standard, shipped capability in mainstream parametric CAD (SolidWorks has an equivalent, per an unfetched Hawkridge Systems search snippet). It's intersection (conflict), not subtraction (free space), but it establishes the toolkit is trivially capable — it's just not a named feature anyone ships for the free-space case.

**Verdict:** the "region first, route second" paradigm is real and mainstream; the specific "boolean-subtract into an exact solid, then tag it as routable" technique is mechanically trivial but has no prior art anyone publishes — real tools that tackle this problem (the one on-target patent, the one on-target industrial CAD tool) both lean toward voxelization/seed-points rather than keeping an exact free-space solid.

## 4. Terminology map, and does a domain-agnostic tagging mechanism exist (including in OCCT itself)?

**Terminology.** "**Keep-out zone**" (must-avoid) / "**keep-in zone**" (must-stay-within) is the genuinely established, cross-domain opposing pair — confirmed across PCB/electronics (Analog Devices glossary and Cadence blog, both search-snippet-sourced only — fetch blocked on both), a real formal-standard usage in IPC-2221/IPC-7351 ("courtyard" clearance) via https://www.nextpcb.com/blog/ipc-2221, semiconductor packaging (patents, snippet-only), aerospace **pointing** keep-out zones (arXiv, snippet-only), and robotics "keep-in zone" / "potential occupancy envelope" (patent filings 11396099, 12420419, 11919173 — real usage, but patent language, not a published standard). "**Exclusion zone**" is real but is a safety/regulatory/geographic term (confirmed via direct fetch of Wikipedia — https://en.wikipedia.org/wiki/Exclusion_zone), not the mechanical-design term you want. "**Allocated volume**"/"**reserved space**" did not turn up as established terms of art in either report's searches. One claim to flag explicitly as **unverified/recalled, not searched**: that SolidWorks Envelope / NX "Space Allocation" / CATIA "Space Reservation" are literally built on the keep-out/keep-in vocabulary — plausible given the SolidWorks Envelope findings in §2, but not independently confirmed this session.

**Domain-agnostic tagging standard: none found.** A CAD Journal paper on ontology-based semantic tagging (fetched: https://www.cad-journal.net/files/vol_17/CAD_17(1)_2020_1-15.pdf) is real but explicitly bespoke to turbine-blade features, not generalizable. STEP AP242/PMI was not independently fetched — real and mature for manufacturing annotation, but no confirmation it has a zone-purpose-tagging entity. USD's `purpose` attribute (`default/render/proxy/guide`) is explicitly flagged **unverified this session and likely off-target anyway** (render-visibility classification, not functional/semantic classification).

**OCCT/OCAF — the directly relevant answer, since this is the kernel under build123d and already this project's long-term identity plan.** Two direct fetches confirm:
- The XDE User Guide (https://dev.opencascade.org/doc/occt-7.3.0/overview/html/occt_user_guides__xde.html): `TDataStd_Name` for labeling shapes/assembly items; `XCAFDoc_ColorTool`/`XCAFDoc_LayerTool` for appearance/layer grouping; validation-property attributes (`XCAFDoc_Centroid`, `XCAFDoc_Area`, `XCAFDoc_Volume`). No dedicated purpose/classification-tag entity ships out of the box.
- The OCAF User Guide (https://dev.opencascade.org/doc/overview/html/occt_user_guides__ocaf.html): confirms `TNaming_NamedShape` — the topological-identity/evolution-tracking mechanism (old-shape→new-shape, PRIMITIVE/GENERATED/MODIFY/DELETE/SELECTED) that is literally this project's own roadmapped "persistent topological identity" bet per CLAUDE.md. It also confirms **`TDataStd_UAttribute`** — *"attribute with a user-defined GUID... used as a marker, which is independent of attributes at the same label"* — a real, native mechanism for attaching an arbitrary custom classification marker to any label/shape, composable with `TNaming_NamedShape` (identity) + `TDataStd_Name` (human-readable name).

This is the most concrete, directly-buildable-on answer found anywhere across all four reports: **OCCT/OCAF already has a native named-attribute-on-shape mechanism** (`TDataStd_UAttribute` + `TDataStd_Name`, riding alongside `TNaming_NamedShape` identity tracking) — it's just generic, not purpose-built for spatial zones, exactly mirroring the situation with build123d's `.label` one layer up.

## 5. Bottom line

**No, build123d cannot do this natively today** — there is no named-region/keep-out-volume concept in either build123d or CadQuery, and no prior art was found (despite direct searching) of anyone using their boolean-subtract machinery for exactly this purpose. Everything you'd need is a *generic* primitive you'd repurpose, not a dedicated feature.

The most direct, deterministic (non-AI) path to building this, using only real primitives surfaced in this research:

1. **Geometry**: use build123d's `Mode.SUBTRACT` (OCCT `BRepAlgoAPI_Cut` underneath) — `enclosure_cavity − Fuse(all placed component solids)` — fusing the components into one clean tool solid first, per the sourced OCCT non-self-interference caveat, rather than passing a raw Compound of mutually-touching parts.
2. **Be honest about what that Cut result is good for**: an exact B-rep "leftover space" solid is mechanically achievable but has no prior-art precedent for *routing through directly* — the one on-target patent (US11615218B2) and the one on-target industrial tool (Dessia's harness router) both back off from an exact solid in favor of voxelization or seed-point search once actual routing is the goal. If routing (not just visualization/reservation) is the end use, plan for a voxel/cell-decomposition layer on top of the exact solid (per the CMU cell-decomposition and Dessia findings), not the solid alone.
3. **Tagging**: for a shallow/prototype version, build123d's own `.label` string on each disjoint solid from the Cut result is real and available today. For the durable, identity-tracked version that fits this project's existing OCAF/TNaming roadmap, combine `TNaming_NamedShape` (topological identity across regen) + `TDataStd_Name` (human-readable name) + `TDataStd_UAttribute` (an arbitrary GUID-marked purpose classifier, e.g. distinguishing "routing_allowed" from "reserved_for_part") — this is the one native, kernel-level mechanism identified that's directly buildable-on rather than invented from scratch.
4. **Vocabulary**: adopt the real, cross-domain established pair "**keep-out zone**" (reserved-for-a-part, must-avoid) / "**keep-in zone**" (routing-allowed corridor, must-stay-within) rather than coining new terms — it's genuinely used in PCB/IPC standards, aerospace, and robotics, unlike "exclusion zone" (wrong domain) or "allocated volume" (unestablished).
5. **Schema shape**: model the two nearest formal analogs as templates — IFC's `IfcSpace`(`CompositionType=PARTIAL`)/`IfcZone`/`IfcSpatialZone` pattern (purpose via `ObjectType`/enumerated `PredefinedType`, optional independent geometry, explicit nested-subzone support) for how to represent purpose + nesting, and the SolidWorks Envelope pattern (a real solid body in the tree, flagged out of BOM/manufacturing but still checked by ordinary interference queries) for how to keep the region a first-class, queryable solid rather than a side-channel metadata blob.

Genuinely open/unresolved after all four passes: whether a formal aerospace "installation envelope" standard exists (searched directly, not found — flag for a dedicated follow-up if that matters to this project specifically), and whether STEP AP242/PMI has anything closer to a generic zone-tagging entity (not independently fetched this session).

---

## Raw agent reports (unedited)

### Agent M — build123d / CadQuery native support for deriving and tagging purpose-regions

## Findings: build123d / CadQuery for free-space computation + region tagging

### (a) Boolean subtract for leftover/free interior volume

**No build123d- or CadQuery-specific example of "compute leftover free space in an enclosure via boolean subtract" was found**, despite multiple targeted searches (`build123d "remaining free space"`, `cadquery "free space"/"leftover space"`, `"interior volume" enclosure minus components github`, `build123d keepout enclosure`). All came back explicitly empty on this specific use case — not "vague plausible hits," genuinely nothing on point. GitHub's own code search requires login (confirmed by fetching a GitHub code-search URL directly — got a sign-in wall, no results), so I could not check it independent of Google-indexed pages.

What I *can* confirm about the mechanics, from real sources fetched this session:

- Both libraries wrap OCCT's `BRepAlgoAPI_Cut`. Directly fetching the OCCT wiki (https://github.com/Open-Cascade-SAS/OCCT/wiki/boolean_operations) got one concrete, quoted caveat: *"The argument should not be self-interfered, i.e. all sub-shapes of the argument that have geometrical coincidence through any topological entities (vertices, edges, faces) must share these entities."* That's the real constraint that matters for `interior_cavity − union(all placed components)`: if your placed components touch/overlap each other without sharing topology (e.g. two brackets flush against the same wall, independently authored), the Cut can misbehave — you generally need to `Fuse` the components into one clean tool-solid first, then `Cut` that from the cavity, rather than passing a raw Compound of mutually-touching solids as the cut tool.
- I could **not** independently verify the more specific claim "solids inside a Compound Boolean argument must not contact each other" — an earlier WebSearch AI summary asserted this, attributing it to `old.opencascade.com`, but when I fetched that exact URL directly it turned out to be a dead/redirected page with no such text. So: that stronger claim is **unverified this session** — treat it as plausible but unconfirmed, not as a citable fact.
- `Mode.SUBTRACT` (and the `-`/boolean-subtract path) is real and documented in build123d — confirmed via direct fetch of https://build123d.readthedocs.io/en/latest/key_concepts_builder.html: *"Mode.SUBTRACT, Mode.INTERSECT, and Mode.REPLACE subtract, intersect, or replace (from) the builder's object."* I did **not** find, in the pages I fetched, an explicit worked example or confirmation that a Cut result naturally decomposes into a Compound of multiple disjoint Solids with a `.solids()` accessor — that behavior is standard for OCCT/build123d topology in general and is what I'd expect from the architecture, but I'm flagging it as **recalled, not textually verified this session**, since the `operations.html` and `key_concepts_builder.html` pages I fetched didn't cover it.
- Net: the boolean-subtract mechanism itself is standard, real, and documented at the OCCT layer that both libraries sit on — there's no reason to doubt it works for this purpose mechanically — but neither library has been shown (by anyone publicly indexed) applying it specifically to compute routing/keep-out free-space, and there's a real, sourced caveat about touching/self-interfering tool geometry that a naive `interior − union(components)` could hit in practice.

### (b) Tagging/labeling a resulting solid with purpose/metadata

**build123d has a real, directly-confirmed mechanism:** every `Shape` (Solid, Compound, Face, etc.) carries a persistent `.label` string attribute, plus `color` and (on `Compound`) `material`. Confirmed by direct fetch of https://build123d.readthedocs.io/en/latest/assemblies.html:

> "In order [to] keep track of objects one can assign a `label` to all Shape objects." — followed by example code `box.label = "box"`, and *"Labels are just strings with no further limitations (they don't have to be unique within the assembly)."*

This is exactly the shape of thing your use case needs (`region.label = "routing_allowed"` / `region.label = "reserved"`), but it is a **generic naming field, not a purpose-built "tagged region" or "keep-out volume" concept** — nothing dedicated to spatial-partition semantics exists in build123d's docs; you'd be repurposing a plain string field. (A separate, narrower mechanism also surfaced only via WebSearch summary, not independently fetched: the `Mesher` export class has an `add_meta_data(namespace, name, value, type, must_preserve)` method for attaching metadata at 3MF-export time — this is export-time metadata, not a general in-memory Shape attribute, and I did not verify it with a direct fetch, so treat it as lower-confidence.)

**CadQuery has two related but distinct mechanisms**, both confirmed by direct fetch:

1. `Assembly.add(part, name="...", color=cq.Color(...))` — confirmed via fetch of https://cadquery.readthedocs.io/en/latest/assy.html, e.g. `.add(make_connector(), name="con_tl", color=cq.Color("black"))`. This is the closest CadQuery analog to build123d's `label` — a persistent name on an assembly member.
2. `Workplane.tag("X")` / `workplaneFromTagged("X")` — also shown in the same assy.html page (`rv.faces(">X").tag("X").end()`), used to mark a construction-time selection/state for later re-reference within the same build script (e.g. for mating constraints). I fetched https://cadquery.readthedocs.io/en/latest/classreference.html specifically to check whether this tags a persistent Shape or just a Workplane checkpoint, and confirmed it's the latter: *tagging preserves the Workplane's coordinate-system/history state for later retrieval via `workplaneFromTagged()`*, not a durable attribute baked onto an exported solid. So CadQuery's `.tag()` is **not** what you'd want for "query this exported region later as reserved" — `Assembly.add(..., name=...)` is the right lever there, analogous to build123d's `label`.

Neither library has a dedicated "named region" / "purpose tag" / "keep-out volume" first-class concept — both only offer generic label/name (+color, +material) strings on the containers you already have (Solid/Compound in build123d, Assembly parts in CadQuery), which you'd repurpose yourself, e.g. by looping over the disjoint solids in the Cut result and setting `.label` per-solid based on some post-hoc classification (adjacent to a routing path vs. isolated pocket).

### Verdict

No solid prior art exists for this specific sub-question (post-hoc free-space computation + purpose-tagging inside an enclosure, in build123d or CadQuery) — nothing found doing this exact thing despite direct searching. The underlying primitives you'd compose it from are real and directly documented: OCCT-backed boolean Cut (with a genuine, sourced non-self-interference caveat on the tool geometry) plus a generic persistent `label` string on any `Shape` in build123d, or `name` on `Assembly` members in CadQuery. You would be building this capability from scratch on top of standard primitives, not adapting an existing pattern.

---

### Agent N — keep-out zones, reserved volumes, and installation envelopes in OTHER CAD/EDA/BIM tools

## Research findings: named/purpose-tagged 3D regions in established design tools

### 1. PCB/electronics CAD — REAL, well-documented, but geometrically it's 2D-per-layer, not a solid 3D volume

**KiCad**
- `pcbnew_zones.adoc` (KiCad official doc, fetched): keepout areas are drawn as **polygon outlines** (same primitive as a copper zone), with three independently-togglable restriction flags: no-tracks, no-vias, no-copper-pour. DRC raises an error if a track/via violates the rule.
- KiCad Library Conventions **F4.5** (`klc.kicad.org/footprint/f4/f4.5.html`, found via WebSearch, direct fetch 403'd so treating as search-result-level confirmation only): footprint keepouts should be **named for purpose** (e.g. "Antenna Keepout") with the name also placed as a text label on the User.Comments layer — i.e. purpose-tagging is a documented *convention*, not an enforced schema field.
- No native "3D body keepout" (height/volume-based mechanical keepout) — GitHub/GitLab issue trackers (`kicad-library#1443`, `kicad#4503`) show this is a **known, still-open gap** in KiCad, not a shipped feature.
- URLs: https://github.com/KiCad/kicad-doc/blob/master/src/pcbnew/pcbnew_zones.adoc , https://klc.kicad.org/footprint/f4/f4.5.html , https://github.com/KiCad/kicad-library/issues/1443 , https://gitlab.com/kicad/code/kicad/-/issues/4503

**Altium Designer**
- **Region Keepout** (fetched `pcb-region-keepout-properties`): a **2D polygonal area** on a layer or the dedicated Keep-Out layer; selectively blocks vias/tracks/copper-regions/SMD-pads/through-hole-pads. Purely a routing constraint, not a solid volume.
- **3D Bodies** (fetched `pcb/3d-bodies`): a 3D Body is "a primitive design object... used as a container into which a standard-format generic 3D model can be imported" to represent a component's real shape; Altium then runs **real-time 3D clearance/collision checking** ("component-to-component and component-to-housing collisions") via the Component Clearance design rule. This is the closest thing to a true 3D keep-out in mainstream PCB CAD — it's actual imported solid geometry checked for interference, not a database "zone" primitive with metadata.
- URLs: https://www.altium.com/documentation/altium-designer/pcb-region-keepout-properties?version=19.0 , https://www.altium.com/documentation/altium-designer/pcb/3d-bodies

**Verdict for #1**: Real and mature, but the "named zone" concept in PCB CAD is fundamentally **2D polygon + boolean/enum rule flags + free-text naming convention**, layered per-board-layer. True 3D solid keep-out only appears via imported mechanical 3D bodies + interference checking, not as a first-class "named 3D zone" entity.

---

### 2. BIM/IFC — REAL, and directly answers the "zone within a zone" question. This is the strongest match found.

Fetched `IfcSpace` (IFC4.3 docs) and `IfcZone`/`IfcSpatialZone` (IFC4.3 docs):

- **IfcSpace**: "an area or volume bounded actually or theoretically" performing "certain functions within a building." Geometry can be a 2D bounded curve footprint *or* full 3D Brep/tessellation via `IfcLocalPlacement` + shape representation. Purpose/classification via **`ObjectType`** (free functional category) and **`PredefinedType`** (enumerated types, with USERDEFINED escape hatch), plus `Name`/`LongName`.
- **Nesting/sub-zones — confirmed real**: `IfcSpace` has a `CompositionType` attribute with values `COMPLEX` (space group), `ELEMENT` (individual space), and **`PARTIAL`** — explicitly "a subdivision of a space." The spec text: "A space may span over several connected spaces" and can be "decomposed in parts, where each part defines a partial space." This is exactly "a reserved sub-area of a room."
- **IfcZone**: pure grouping mechanism (`IfcRelAssignsToGroup`) over spaces/partial-spaces/other zones; explicitly **has no geometric representation of its own** ("A zone does not have its own shape representation"), non-hierarchical, one space can belong to 0..n zones. `ObjectType` carries purpose, e.g. 'FireCompartment', 'ElevatorShaft', 'RisingDuct'.
- **IfcSpatialZone** (IFC4+): unlike `IfcZone`, **does** carry its own placement + shape representation — used for thermal zones, construction zones, lighting zones, usable-area zones — i.e. a named, independently-shaped, purpose-tagged 3D/2D region that can overlap other spatial structure.

URLs: https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcSpace.htm , https://ifc43-docs.standards.buildingsmart.org/IFC/RELEASE/IFC4x3/HTML/lexical/IfcZone.htm (buildingSMART's older TC1 mirror at standards.buildingsmart.org returned 403 to WebFetch, but the same entities are documented at the IFC4x3 URLs above, which did load).

**Verdict for #2**: Real, formal, and closest analog to what's being asked: a database entity with (a) enum/free-text purpose classification, (b) optional independent solid/2D geometry, (c) explicit support for nested/partial sub-zones (`IfcSpace` PARTIAL) and independently-shaped overlapping zones (`IfcSpatialZone`).

---

### 3. Mechanical CAD Envelope features — REAL, solid-geometry, reference-only (non-manufacturing) volume

**SolidWorks** (fetched via cati.com's official SW blog after help.solidworks.com blocked WebFetch with 403; help.solidworks.com URLs were confirmed to exist via WebSearch titles — "Envelope Publisher - 2020/2022/2023/2024/2025 - SOLIDWORKS Design Help" — but I could not fetch their body text directly):
- An **Envelope** is a normal solid-body component flagged so it's excluded from the BOM and typically excluded from mass/interference-critical operations — used specifically to mark **reserved/protected volumes** other components must be designed around.
- **Envelope Publisher** (SW 2020+): propagates a top-level-assembly component down into a subassembly as a referenced envelope, auto-synced to the parent, living in a "Published Envelopes" folder — explicitly for multi-level assembly coordination of reserved geometry without BOM clutter.
- This is **actual solid B-rep geometry** (a real part/body), not a metadata-only bounding box — it participates in interference detection like any solid, just with a special "envelope" flag suppressing BOM/manufacturing output.
- URLs: https://www.cati.com/blog/solidworks-2020-whats-new-assembly-envelope-publisher/ (fetched) ; https://help.solidworks.com/2023/english/SolidWorks/sldworks/c_envelope_publisher.htm (found via WebSearch, title-confirmed, not body-fetched — 403).

**Fusion 360**: I could not verify Fusion 360's equivalent this session — the WebSearch budget was exhausted before I could search it, and I did not attempt an unverified WebFetch guess. **Found nothing verified this session on Fusion 360.**

**Verdict for #3**: Real for SolidWorks, well-documented, confirmed as true solid geometry with a special "don't manufacture/BOM me, but do check clearance against me" semantic. Fusion 360 side unverified — do not treat any claim about it as confirmed.

---

### 4. Aerospace/systems-engineering "installation envelope" / "keep-out zone" — NOT confirmed as a formally-cited standard this session

I ran targeted searches for NASA systems-engineering usage, ICD/payload keep-out-zone usage, and a general "installation envelope" standard definition. Results were thin and tangential before the session's WebSearch budget was exhausted:
- Found: Analog Devices glossary page titled "Keep-Out Zone" (URL surfaced by WebSearch: https://www.analog.com/en/resources/glossary/keep-out-zone.html) — but every WebFetch attempt on it failed (timeout/connection reset), so I could not read/quote its actual definition. Per the search-snippet text only (not independently verified by fetch), it frames "keep-out zone" in a **semiconductor/PCB thermal-and-mounting** context, not aerospace installation.
- Found: an arXiv paper "Safe Deep Reinforcement Learning for Spacecraft Reorientation with Pointing Keep-Out Constraint" — this is the *sensor-pointing* sense of "keep-out zone" (an inertial direction a spacecraft attitude must avoid, e.g. keeping a telescope away from the Sun), which is a different (but related, and definitely real) usage than "reserved installation volume."
- Did **not** find a fetchable, citable standard (SAE, NASA-STD, MIL-STD, ECSS) that formally defines "installation envelope" as a named keep-out-volume term, despite it being a term I recall from general engineering practice (e.g. ICDs for payload integration, CubeSat Design Specification's "keep-out zone" around a P-POD deployer). **That recollection is unverified this session** — I attempted to fetch a CubeSat Design Specification PDF from memory of its likely URL and got a 404 (i.e., I did not find the real link, so I'm not citing one).

**Verdict for #4**: Genuinely unresolved by this session's research. The term is real in my general training knowledge (ICDs and CubeSat/payload-integration docs commonly use "keep-out zone"/"static/dynamic envelope"), but I have **no verified URL** to back it, and search budget ran out before I could confirm it properly — flag this sub-question for a follow-up search pass rather than treating it as established.

---

### Overall verdict

Solid, citable prior art exists for **3 of 4** sub-domains:
- **PCB CAD** (KiCad, Altium): real, 2D-polygon-plus-rule-flags per layer, named by convention, with true-3D handled only via imported solid bodies + interference checking (Altium).
- **BIM/IFC**: real and strongest match — `IfcSpace`/`IfcSpatialZone`/`IfcZone` give a formal database entity with enum+free-text purpose typing, optional independent solid geometry, and **explicit support for a reserved sub-zone nested inside a larger zone** (exactly the pattern asked about).
- **Mechanical CAD Envelopes**: real (confirmed for SolidWorks) — an actual solid body flagged as BOM-excluded/reference-only, checked via normal interference detection, propagated across assembly levels via Envelope Publisher.

**Not established this session**: a formally-documented aerospace "installation envelope"/"keep-out zone" standard — this needs a dedicated follow-up search (budget permitting) rather than being asserted as confirmed prior art.

---

### Agent O — deterministic algorithms for classifying 3D space into free/reserved/routable regions

# Research Report: Deterministic Algorithms for Classifying 3D Space into Free/Reserved/Routable Regions

## Direct hits — academic work specifically on "free/unoccupied space in CAD assemblies"

**1. "Voxel-Based Approach for Computation and Optimization of Unoccupied Space in CAD Assemblies"** (ResearchGate)
https://www.researchgate.net/publication/267647297_Voxel-Based_Approach_for_Computation_and_Optimization_of_Unoccupied_Space_in_CAD_Assemblies
This is the single closest hit to the question as posed — title-exact match. Per WebSearch's indexed summary of the paper (I could not get past ResearchGate's 403 to read the full text, so this is snippet-level, not full-text verified): it fits a uniform voxel grid over an assembly's bounding volume, marks voxels occupied by component geometry, and the remainder is the "unoccupied space," which the paper then optimizes/uses. **Notably this is voxel-grid based, not an exact-boundary (B-rep) solid** — the free region is a discretized approximation, not a single continuous solid produced by CSG subtraction.

**2. "Octree Based Voxel Model for Representation of Spatial Conflicts Across Multiple Design Domains"** (Springer, DOI 10.1007/978-3-030-42250-9_2)
https://link.springer.com/chapter/10.1007/978-3-030-42250-9_2
Also a strong title match — explicitly about representing spatial conflicts (i.e., reserved/occupied vs. available) via octree voxelization across multiple engineering domains simultaneously. Paywalled (redirected to Springer login), so again only search-snippet-level, not full-text verified.

**3. USPTO Patent US11615218B2, "Mesh void space identification and auto seeding detection in computer aided design defined geometries"** — fully fetched and read.
https://patents.google.com/patent/US11615218B2/en
This is real, verified prior art directly on-topic, and it's an interesting *negative* data point for the "materialize as a solid" sub-question: the method does **not** produce an explicit void-space solid. Instead the user picks one bounding surface, the system builds virtual bounding planes/boxes to constrain a search domain, then does coarse-to-fine discretization to find valid *seed points* inside the void for downstream mesh generation — propagating to adjacent surfaces if the first seed attempt fails. The stated advantage is explicitly that this avoids having to enclose/model the void as a real geometric body. This suggests that even inside a patent whose whole subject is "void space in CAD," the chosen solution deliberately sidesteps materializing a persistent free-space solid.

## Interference / reserved-volume side (occupied ∩ occupied, not free = complement)

**4. Inventor "Analyze Interference" + CreateInterference macro** — fully fetched.
https://www.cadforum.cz/en/creating-an-interference-solid-from-conflicting-inventor-parts-tip8347
Standard mainstream CAD capability: Autodesk Inventor's built-in interference check only produces a transient visual/volume number, but a documented VBA macro (`CreateInterference`) runs the boolean intersection of colliding bodies and adds the resulting interference volume as a permanent new solid part in the assembly. This confirms boolean-based materialization of a "special" derived region is a completely standard, shipped capability in mainstream parametric CAD (SOLIDWORKS has the equivalent "interference body as new part" feature, mentioned in a search snippet from Hawkridge Systems, not independently fetched). This is the mirror-image operation of what's asked (intersection→reserved-conflict solid) rather than (bounding envelope minus union→free solid), but it establishes that the same boolean toolkit trivially supports the complement version — it's just not a named standard feature anyone ships.

**5. "Active zones in CSG for accelerating boundary evaluation, redundancy elimination, interference detection, and shading algorithms"** (ACM Transactions on Graphics)
https://dl.acm.org/doi/abs/10.1145/49155.51123
Found via search, genuinely real (classic CSG literature), but WebFetch was blocked (403) — I only have the title, not verified content. Flagging as found-but-unverified.

**6. Generic Boolean subtract explainer** (Spatial/ACIS glossary) — from search snippet, not independently fetched: standard CSG "subtract" computes solid intersection then removes it from the target, rebuilding the B-rep. This is the exact primitive that would be needed to do "bounding envelope − Σ(component solids) = free-space solid"; it's a completely generic, decades-old operation in every solid-modeling kernel (Parasolid, ACIS, OCCT). No special research is needed to prove this is *possible* — the gap is that nobody appears to publish it as a named workflow for "tag as routable."

## Motion-planning literature: is free space its own step before pathfinding?

This is where I found the clearest, best-verified answer, and it's a genuine **yes, for one whole family of algorithms, no for another.**

**7. CMU 16-735 lecture notes, Howie Choset, "Cell Decompositions"** — fully fetched.
https://www.cs.cmu.edu/~motionplanning/lecture/Chap6-CellDecomp_howie.pdf
Confirms explicitly: cell-decomposition planners **pre-compute free space as explicit cells before search begins** — exact methods (trapezoidal decomposition, cylindrical/Morse decomposition) partition free space precisely along obstacle boundaries; approximate methods (quadtree/octree/voxel grids) subdivide uniformly and label each cell free/occupied/mixed. Only after this decomposition does a graph-search algorithm (A*, Dijkstra) run over the adjacency graph of free cells. This is a clean, sourced answer to the "own separate step" half of the question.

**8. C-IRIS ("Certified Polyhedral Decompositions of Collision-Free Configuration Space")**, arXiv:2302.12219 — fully fetched (abstract).
https://arxiv.org/abs/2302.12219
Recent, real, and directly on point methodologically: uses semidefinite-programming-based convex optimization to generate large convex polytopes in configuration space that are *rigorously certified collision-free* — an explicit, verified solid decomposition of free space, computed once and reused by both optimization-based and sampling-based motion planners afterward. This is a modern, rigorous instance of "materialize free space as actual solid regions first, plan inside them second" (in joint/configuration space rather than Cartesian/CAD space, but the algorithmic pattern is identical to what's being asked about).

**9. Generalized Voronoi Diagram / Graph (GVD/GVG)** — from search snippets (direct paper fetch attempts both failed: ResearchGate/academia.edu not fetched, Choset's original 1995 CMU paper hit a dead link/404 on retry).
Represents free space as a lower-dimensional skeleton (the locus of points equidistant from the two nearest obstacles), computed as its own topological structure separate from any specific path query, then searched. This is a second well-established "materialize free space first" paradigm, but I was not able to fully verify a primary source's content this session beyond search-result summaries.

**10. Sampling-based planners (RRT/PRM) — the "no, they skip it" side.**
One search snippet (on the GVD-guided RRT paper, IEEE 9430686) referenced GVDs being used to "guide the sampling process of RRTs," implying RRT itself doesn't normally have a materialized free-space object. I did **not** independently fetch/verify a primary RRT or PRM source this session, so: **recalled from general knowledge, not verified this session** — RRT and PRM are the standard counter-example the question is fishing for: they do pure point-wise/edge-wise collision queries against the obstacle representation on the fly and never build a persistent "free region" object at all. I flag this explicitly as unverified-this-session per instructions, even though it's well-established robotics knowledge.

## Industrial tool doing almost exactly what was asked (CAD assembly → free-space region → routing)

**11. Dessia — "AI-driven wiring harness routing on a powertrain environment"** — fully fetched.
https://www.dessia.io/case-studies/ai-harness-routing-generative-design-cad
This is the best real-world match to the compound question. Verified content: the tool converts a CAD assembly into a **voxel-based spatial model of "available routing space"** as an explicit first stage (hard constraints = prohibited zones/moving parts, soft constraints = areas to avoid, all baked into the voxel grid), and only then runs pathfinding/optimization (length, bend radius, clearance, manufacturability) over that pre-computed grid. This directly confirms, in an industrial mechanical-CAD context (not robotics), the "free space computed first, as its own representation, before routing" pattern — via voxelization, not exact boolean solids.

## Also found, general-context only (not deeply verified)

- OctoMap (https://octomap.github.io/) and generic occupancy-grid literature: tri-state free/occupied/unknown voxel classification, standard in robotics mapping — well-established, general background, not CAD-specific.
- "Space allocation problem" (Wikipedia, https://en.wikipedia.org/wiki/Space_allocation_problem) — real named CS/architecture problem, but the article is a stub with no algorithmic content; not useful beyond confirming the term exists.
- "A survey of computational approaches to three-dimensional layout problems" (ScienceDirect) — good-sounding title, WebFetch blocked (403), not verified.
- ASME "Spatial Packaging and Routing Optimization of Complex Interacting Engineered Systems" — good title match (packaging + routing together), WebFetch blocked (403), not verified beyond the title.
- Aerospace KBE wire-harness routing papers (scispace.com, ResearchGate 220245868) — found, but WebFetch blocked; not verified beyond search snippets.

## Verdict

**Partial, real prior art exists, split across two different techniques — but no single canonical/dominant named algorithm does exactly "assembly → automatic boolean complement → tagged routable solid."**
- For "compute a free-space *region*, as a separate step before any routing/pathfinding runs" — yes, this is a well-established, mainstream paradigm, confirmed via CMU cell-decomposition material, C-IRIS, and (most relevantly) a real industrial CAD harness-routing tool (Dessia) that voxelizes "available routing space" before pathfinding.
- For "materialize that free space as an actual continuous solid via boolean subtraction (not a voxel grid)" — the generic boolean-subtract primitive to do this exists in every solid modeling kernel and is trivial to apply, and the reverse operation (interference solid via boolean intersection) is a shipped, standard CAD feature (Inventor/SOLIDWORKS) — but I found no established named algorithm/tool that runs that subtraction specifically to produce a tagged "reserved for routing" solid; the one patent I fully verified that targets exactly this problem (US11615218B2) explicitly avoids producing such a solid in favor of seed-point discretization, and the closest matching academic paper titles (voxel-based unoccupied-space computation, octree spatial-conflict modeling) use voxel/grid representations rather than exact B-rep solids.

---

### Agent P — terminology and generic purpose-tagging/metadata schemes for CAD sub-volumes

# Research findings: terminology for purpose-tagged CAD sub-volumes, and domain-agnostic tagging schemes

## Part 1 — Terminology map across domains (real usage confirmed)

**"Keep-out zone"** — the dominant, cross-domain term for "volume where something must NOT be placed/enter."
- Confirmed via WebSearch across multiple independent domains in one session:
  - **PCB/electronics**: "a boundary on a PCB where no traces, pads, vias, mechanical outlines, or any other components are allowed" — synthesized from [Analog Devices glossary](https://www.analog.com/en/resources/glossary/keep-out-zone.html) and [Cadence PCB blog](https://resources.pcb.cadence.com/blog/2020-managing-component-keep-out-zones-for-smart-layouts) (WebFetch on both was blocked — timeout / 403 — so treat these two specifically as search-snippet-sourced, not full-page-verified).
  - **IPC standards** (real, formal): [nextpcb.com/blog/ipc-2221](https://www.nextpcb.com/blog/ipc-2221) — "IPC-2221C requires a copper-free keepout around plated mounting holes unless intentionally connected to a ground plane," and IPC-7351 formalizes the related "courtyard" clearance zone around a footprint. This is a genuine standards-body usage, not just informal jargon.
  - **Semiconductor packaging**: keep-out zone used for dicing-protection buffer regions (per patents 9558966, 10049898 — search-snippet only, not fetched).
  - **Aerospace/spacecraft**: "pointing keep-out zone" — an inertial direction sensitive payloads (telescopes) must avoid — from an arXiv spacecraft-attitude paper found via search (not independently fetched).
  - **Robotics**: "keep-in zone" is the paired opposite term — "conventionally defined as prismatic bodies... larger than the total swept volume of the machinery during operation... enforced by the control system" — this phrasing comes from USPTO patent filings on "potential occupancy envelopes" (patents 11396099, 12420419, 11919173). Real usage, but note the source is patent language, not a formal published standard.

**Keep-out vs. keep-in — the semantic split holds across every domain checked**: keep-out = must stay clear of; keep-in = must stay confined within. Both terms are native, first-class primitives in commercial mechanical CAD (SolidWorks "Envelope," NX "Space Allocation," CATIA "Space Reservation" workbenches) — **this specific claim about SolidWorks/NX/CATIA is recalled from general knowledge, not verified via search or fetch this session** — flagging explicitly per the citation-honesty rule.

**"Exclusion zone"** — confirmed real but NOT an engineering-design term in the sense asked about. [Wikipedia — Exclusion zone](https://en.wikipedia.org/wiki/Exclusion_zone) (fetched directly): the article covers geographic/military/nuclear/border/legal exclusion zones. The only engineering-adjacent sense found is construction-site safety perimeters ("defined locations to prohibit entry of personnel into danger areas"). No mechanical/aerospace-design-envelope usage surfaced. **Verdict: "exclusion zone" is a safety/regulatory term, not the mechanical-design term you want — "keep-out zone" is.**

**"Allocated volume" / "reserved space"** — searched directly, found essentially nothing on-topic. Results returned data-storage-allocation and generic dictionary noise, not mechanical/aerospace engineering usage. I could not confirm these as established terms of art in this session — treat any recollection of "space allocation" (e.g., as an NX module name) as unverified.

**BIM/IFC — `IfcZone` is real and is distinct from `IfcSpace`, confirmed by direct fetch:**
- [IfcZone spec, IFC2x3 TC1 (mirror)](https://iaiweb.lbl.gov/Resources/IFC_Releases/R2x3_final/ifcproductextension/lexical/ifczone.htm) — fetched directly. Official definition: "an aggregation of spaces, partial spaces or other zones." Non-hierarchical — one `IfcSpace` can belong to zero, one, or many zones (via `IfcRelAssignsToGroup`, inherited from `IfcGroup`). Recommended `ObjectType` values include `FireCompartment`, `ElevatorShaft`, `RisingDuct`, `RunningDuct` — i.e., exactly "named sub-region reserved for a specific purpose." Formal constraint WR1: only `IfcSpace` or `IfcZone` may be `RelatedObjects` in the aggregation.
- [GitHub buildingSMART/IFC4.3.x-development issue #1](https://github.com/buildingSMART/IFC4.3.x-development/issues/1) — fetched directly. Clarifies `IfcZone` (old, IFC1.0-era, `IfcGroup` subtype, **no own geometry**) vs. `IfcSpatialZone` (added later, `IfcSpatialElement` subtype, **does carry its own spatial/geometric representation**) — the newer entity is closer to what a "purpose-tagged sub-volume with real geometry" would need. The discussion itself flags the two as confusingly overlapping and a candidate for future rationalization.
- This is the closest thing found to a standards-body, domain-agnostic "named purpose region" — but it's BIM/AEC-scoped (buildingSMART/IFC), not a general 3D-geometry-kernel concept.

## Part 2 — Is there a generic, domain-agnostic geometry-tagging scheme?

**Short answer from what was actually found: no single reusable cross-CAD-ecosystem standard exists; every ecosystem reinvents its own.**

- **Semantic tagging research literature** — found a real paper: [CAD Journal, "Semantic Tagging Framework for Contextually Augmented Features," vol 17(1) 2020](https://www.cad-journal.net/files/vol_17/CAD_17(1)_2020_1-15.pdf) (fetched directly). It builds an ontology-based semantic-tagging framework, but it is **explicitly domain-specific to turbine-blade geometry** (leading edge/trailing edge features), not a generic reusable scheme. Confirms the general research pattern: academic semantic-tagging work exists but is bespoke per application, not standardized.
- **STEP AP242 / PMI** — found via search only (not independently fetched this session): AP242 stores PMI (dimensions, tolerances, material specs) plus revision/lifecycle attributes alongside exact B-Rep geometry. This is a real, mature standard for *manufacturing annotation*, but nothing found this session confirms it has a generic "purpose-tag a sub-volume" mechanism distinct from GD&T/PMI semantics — would need a follow-up fetch of the actual AP242 spec to confirm/deny a zone-tagging entity.
- **USD "purpose" attribute** — I recall (from general knowledge, **not verified this session**) that USD/OpenUSD has a `purpose` attribute on `UsdGeomImageable` prims with enum values `default/render/proxy/guide` — but this is a *render-visibility* classification, not a semantic/functional-classification mechanism, so even if confirmed it would not answer the question being asked. Flagging as unverified and likely off-target.
- **glTF `extras`/`extensions`** — not searched this session; no claim made.

**OCCT / OCAF — directly relevant to this project's own long-term plan, confirmed by two direct fetches:**
- [OCCT XDE User Guide (7.3.0)](https://dev.opencascade.org/doc/occt-7.3.0/overview/html/occt_user_guides__xde.html) — fetched directly. Confirms `TDataStd_Name` for labeling shapes/assembly items, `XCAFDoc_ColorTool`/`XCAFDoc_LayerTool` for appearance/layer grouping, and validation-property attributes (`XCAFDoc_Centroid`, `XCAFDoc_Area`, `XCAFDoc_Volume`). No dedicated purpose/classification-tag entity exists out of the box — the doc explicitly notes reserved sub-label tag ranges are for internal use, and custom classification has to ride on generic attributes attached to unreserved sub-labels.
- [OCCT OCAF User Guide](https://dev.opencascade.org/doc/overview/html/occt_user_guides__ocaf.html) — fetched directly. Confirms `TNaming_NamedShape` is real and is exactly the topological-identity/evolution-tracking mechanism (old-shape→new-shape pairs with PRIMITIVE/GENERATED/MODIFY/DELETE/SELECTED evolution types) that this project already tracks as its long-term plan. Crucially, it also confirms **`TDataStd_UAttribute`** — "attribute with a user-defined GUID... used as a marker, which is independent of attributes at the same label" — this is a real, native OCAF mechanism for attaching an arbitrary custom classification marker to any label/shape, and it composes naturally with `TNaming_NamedShape` (geometry identity) + `TDataStd_Name` (human-readable name). This is the most concrete, directly-usable answer found for "how would you attach a purpose tag to a sub-volume inside the kernel this project already uses (OCCT, under build123d)."

## Verdict

Real, confirmed, domain-specific terminology exists and is consistent: **"keep-out zone"** (must-avoid) and **"keep-in zone"** (must-stay-within) are the genuinely established opposing pair, used natively in PCB (IPC-2221/7351-adjacent), semiconductor packaging, aerospace pointing constraints, and robotics motion planning. **"Exclusion zone"** is a real term but belongs to safety/regulatory/geographic usage, not mechanical design. **"Allocated volume"/"reserved space"** did not turn up as established terms of art in this session's searches. In BIM, **`IfcZone`/`IfcSpatialZone`** is a real, standards-body-defined, non-hierarchical named-purpose-region entity distinct from `IfcSpace`.

No genuine domain-agnostic, cross-CAD-ecosystem tagging *standard* was found — the semantic-tagging research is bespoke per domain, IFC's zone concept is AEC-scoped only, and even STEP AP242/PMI (not fully verified this session) is oriented at manufacturing annotation rather than zone-purpose tagging. The one piece of solid, directly relevant, and actionable prior art for **this project specifically** is native OCCT/OCAF: `TNaming_NamedShape` + `TDataStd_Name` + `TDataStd_UAttribute` together give a real, already-in-your-stack mechanism to attach a persistent, topologically-identity-tracked purpose/classification tag to a sub-shape — which is a natural extension of the OCAF/TNaming plan already in this project's roadmap. **So: solid prior art exists for the terminology question; no solid prior art exists for a generic cross-ecosystem tagging standard — this would be a genuine gap to fill, best built directly on the OCAF primitives above rather than invented from scratch.**

---

