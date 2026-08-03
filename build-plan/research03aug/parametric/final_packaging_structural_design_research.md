# Final packaging: composing atomic parts into a complete structural product — prior-art research + project fit

**Date:** 2026-08-04
**Status:** Exploratory research only — nothing here is built or scheduled. Captured so future work
doesn't re-derive it from scratch.

## Context / the question being evaluated

Beyond a single functional part or subsystem, how do you package a full set of atomic parts and
subsystems (gears, shafts, bearings, PCBs, motors, ...) into one complete, manufacturable, structural
product — the housing, the ribs, the spacers, the bosses, the retention features, the covers, all
the "glue" that turns a pile of functional components into a shippable thing? Gearbox housing design
is used as ONE concrete, well-documented worked example in this research — explicitly not the whole
scope; the question is the general final-packaging/structural-design pattern.

Four parallel research agents (Sonnet 5, via the Workflow tool) investigated: (U) established DFM
design rules for the individual retention/mounting parts (bosses, snap-fits, standoffs/spacers,
retaining rings/shaft shoulders), (V) the housing/enclosure ruleset itself (wall thickness, rib-to-wall
ratio, draft, parting lines, boss placement) and whether any tool automates/checks it, (W) how CAD/PLM
represents atomic-part → subassembly → product hierarchies and whether prior art exists for
*automatically generating* packaging geometry from a component spec, (X) gearbox housing design as a
grounded worked example, with an explicit instruction to separate what generalizes from what's
gearbox-specific. A fifth agent synthesized the four raw reports. Citation status (directly fetched vs.
search-snippet-only vs. recalled/unverified) is preserved exactly as each agent reported it. No URL
below was invented.

**Headline finding**: the individual DFM rules are real, numeric, cross-confirmed by independent
sources, and standardized where it matters (ASME B27.7/DIN 471 for retaining rings, real bearing-
manufacturer shoulder-height tables, published boss/snap-fit closed-form design ratios). What does
**not** exist anywhere found is a tool that *automatically* applies these rules to a set of specified
components and generates the packaging geometry — every real source is a rule a human engineer
applies by hand, not a generator. That gap lines up exactly with this project's own situation (see
Part B): the catalog already has the *parts* (`standoff`, `hex_standoff`, `pcb_stack_standoff`,
`prop_spacer`, `stepped_spacer`, `threaded_boss`, `press_fit_boss`, `snap_fit_box`,
`inspection_cover`, `sliding_lid_box`, and more) but nothing that *decides* how many of them a given
layout needs or where they go.

---

## Part A — External research synthesis (read this first for "what's out there")

# How to package atomic parts into a structural product: synthesis of research findings

**Methodology caveat up front, because it affects how much weight to put on everything below:** all four research passes lost WebSearch access almost immediately (session budget exhausted) and worked almost entirely through WebFetch — either direct URL fetches or DuckDuckGo/Bing HTML result pages used as a search substitute. A meaningful number of leads 403'd, timed out, returned JS-shell pages, or were PDFs whose body text didn't extract. Where that happened, I've kept the source flagged as "found but not verified" rather than folding it in as a citation. Also note: Semantic Scholar, Google Scholar, IEEE Xplore, and ACM DL were never reachable in any of the four sessions — real academic literature on automated enclosure/packaging synthesis likely exists beyond what's below; this is a coverage gap, not a "nothing exists" finding.

---

## 1. DFM rules for the "glue" parts (bosses, snap-fits, standoffs/spacers, shaft retention)

### Screw bosses (injection molding)
Cross-confirmed by two independent sources:
- Boss OD = **2× screw diameter** (unfilled thermoplastic), **2.5×** for glass-filled; boss wall thickness = **0.5–0.6× nominal wall T**; pilot hole = screw major dia minus one thread depth; draft **0.5–1°/side**; boss height ≤**3× OD** (gussets recommended above 2×OD); gusset thickness ≈**0.5×T**; base fillet ≥**0.25×T**; boss-to-boss spacing ≥**2×OD** center-to-center — [plasticmoulds.net, "Designing Bosses for Injection Molding: A Complete Guide"](https://www.plasticmoulds.net/designing-bosses-for-injection-molding-a-complete-guide.html)
- Independently corroborates the core ratio: boss wall = **40–60% of adjoining wall thickness**, draft **0.5°–3°** (a wider range than plasticmoulds.net's, not a contradiction, just less specific) — [Protolabs, "Plastic Boss Design on Molded Parts"](https://www.protolabs.com/resources/design-tips/plastic-boss-design-on-molded-parts/)

Not extracted (found, not verified): RapidDirect's screw-boss article (timed out), Microns Hub's boss-design-rules page (rate-limited).

### Snap-fits
Real, standard closed-form cantilever-beam mechanics, confirmed by two independently-fetched, readable commercial sources that agree in functional form:
- Max strain εmax = 1.5·t·Y/(L²·Q); deflection force P = b·t²·ε·E/(6L); mating force W = P·[(μ+tanα)/(1−μ·tanα)] — [Fictiv, "How to Design Snap Fit Components"](https://www.fictiv.com/articles/how-to-design-snap-fit-components)
- Max deflection Y = 0.67·(ε·L²/H); deflection force P = (B·H²·E·ε)/6L; mating force W = P·F — [Synectic, "Snap Fit Design"](https://synectic.net/snap-fit-design/)

Both trace to the classic Bayer/GE Plastics snap-fit manuals. Two likely copies of that manual were located and actually downloaded but not text-extractable this session ([MIT-hosted PDF](https://fab.cba.mit.edu/classes/S62.12/people/vernelle.noel/Plastic_Snap_fit_design.pdf), [productdesignonline.com PDF](https://productdesignonline.com/wp-content/uploads/2019/08/Snap-Fit-Design-Manual.pdf)) — flagged as found-but-unread, not cited as content. An interactive snap-fit calculator was located but not fetched ([Qlution Mold](https://qlutionmold.com/snap-fit-design-guide/), 403).

### Standoffs/spacers — thinnest sub-topic
- **PCB standoffs:** standard body heights by thread (M2: 3–15mm, M2.5: 4–20mm, M3: 5–25mm, M4: 6–30mm), hole clearance-over-screw-diameter tables, soft rule of "4 corner supports minimum" for small boards — [bestpcbs.com PCB Standoffs guide](https://www.bestpcbs.com/blog/2026/07/pcb-standoffs/). (fastturnpcbs.com's equivalent guide 403'd.)
- **Shaft/gear spacers between bearings: genuinely unconfirmed, not disconfirmed.** The right authoritative sources were located — [Timken Bearing Installation Calculations](https://engineering.timken.com/engineering-tool/bearing-installation-calculations/), [Schaeffler "Design of bearing arrangements"](https://medias.schaeffler.us/en/knowledge-center/rolling-bearings/design-of-bearing-arrangements) — but both returned JS-shell pages with no extractable body text. One low-quality hit (truegeometry.com) gave a unit-mismatched "formula" that reads like AI-generated SEO content and was explicitly rejected rather than cited.

### Shaft/bearing retention (retaining rings, shaft shoulders) — solid
- **Retaining rings:** standard is real — [ASME B27.7](https://www.asme.org/codes-standards/find-codes-standards/b27-7-general-purpose-tapered-reduced-cross-section-retaining-rings-metric) (title/scope confirmed, dimension table itself paywalled); real sample dimensions sourced "per ANSI B27.7" via a downstream vendor table — [RivCut retaining ring chart](https://www.rivcut.com/resources/retaining-ring-chart) (e.g., 1" shaft → 0.955" groove dia, 0.054" groove width). Metric/DIN equivalent confirmed with a real numeric table (e.g., 20mm shaft → 19.0mm groove dia, 1.3mm width, 0.50mm depth, tolerances h11/H13) — [mechcodex.com DIN 471 table](https://mechcodex.com/reference/retaining-ring-sizes-external).
- **Shaft shoulders for bearings:** a genuine bearing-manufacturer engineering reference with real tables — shoulder diameter must exceed the ball-set pitch diameter for thrust loads; Table 14-2 tabulates fillet radius and shoulder height against the bearing's own chamfer dimension across two load cases; Table 14-3 covers shaft-undercut dimensions — [Koyo/JTEKT Bearing Knowledge, Mounting Dimensions](https://koyo.jtekt.co.jp/en/support/bearing-knowledge/14-2000.html).

### Parametric generators (the closest existing prior art for "auto-derive the glue part")
- [cq_warehouse fastener module (CadQuery)](https://cq-warehouse.readthedocs.io/en/latest/fastener.html) — real, documented, genuinely auto-sizes: `.clearanceHole()`, `.tapHole()`, `.threadedHole()` compute hole geometry from a fastener spec via lookup tables and can auto-place matching washers/fasteners. Scoped to holes/fasteners, not boss/snap-fit/shaft-retention geometry.
- [build123d-parts-lib (GitHub)](https://github.com/baibai2013/build123d-parts-lib/blob/main/README_EN.md) — real repo with a parametric heat-set-insert boss generator and a snap-fit-latch generator, plus static circlip/standoff parts. No groove-cutting or shaft-shoulder generator.
- **The gap, stated plainly:** nothing found anywhere derives spacer length/OD, boss placement, or retaining-ring groove position *from the geometry of the components being retained* (e.g., "this gear and this bearing on this shaft" → spacer). Everything found is either a human-driven parametric part (you still choose the dimensions) or single-feature auto-sizing from a single fastener spec.

---

## 2. DFM rules for the enclosing housing itself

### The numbers (Xometry + Protolabs, cross-corroborated commercial sources)
- Rib thickness ≤ **60% of nominal wall** (Xometry notes 40% for glossy/class-A surfaces); rib height ≤ **3× rib thickness**; rib draft **0.5–1.5°**; thickness-transition run length = **3× the change in thickness** — [Xometry, "Plastic Ribs for Injection-Molding Design"](https://www.xometry.com/resources/injection-molding/plastic-ribs-for-injection-molding-design/)
- Boss wall thickness **40–60%** of the wall it rises from, tied back to the wall via ribs/gussets rather than solid fill — [Protolabs, boss design](https://www.protolabs.com/resources/design-tips/plastic-boss-design-on-molded-parts/)
- Draft: rule of thumb **1° per inch of cavity depth**; minimum **0.5°** on all vertical faces; **1–2°** typical; **3°** minimum for metal-to-metal shutoffs; **3°/5°+** for light/heavy texture — [Protolabs, "Draft Angle Guidelines"](https://www.protolabs.com/resources/design-tips/improving-part-moldability-with-draft/)
- Parting line placement is genuinely algorithmic: must trace the path where **surface tangent is parallel to the mold-opening direction**; dictates draft direction per feature; place on sharp edges, avoid crossing radiused/cosmetic surfaces — [Protolabs, "Planning for Parting Lines"](https://www.protolabs.com/resources/design-tips/planning-for-parting-lines-in-injection-molding/)
- Material-specific nominal wall ranges (ABS 0.045–0.140in, PP 0.025–0.150in), min slot width 0.040in — [Protolabs, "Solving Wall Thickness Issues"](https://www.protolabs.com/resources/design-tips/solving-wall-thickness-issues-in-molded-parts/)

**Two real numeric conflicts across sources, not resolved — flagging rather than picking a winner:**
- Rib base fillet radius: Xometry says **0.5–1× wall thickness**; DFMPro's built-in rule set (below) uses **0.25–0.4× wall**.
- Rib spacing: Xometry says **≥2.5–3× nominal wall**; DFMPro's rule set uses **≥2× wall**.
- Also worth flagging: the "50–60%" figure often quoted in casual DFM talk isn't what any source actually says — the real recurring phrasing is "**≤60% (40% for class-A/glossy surfaces)**."

### Automated checkers: real, multiple, mature
- **DFMPro (HCL/Sigmetrix)** — commercial CAD plug-in (SolidWorks/Creo/NX/CATIA/3DEXPERIENCE) that checks wall uniformity, rib parameters, draft, undercuts against a built-in rule set — [dfmpro.com](https://dfmpro.com/manufacturing-processes/dfmpro-for-injection-molding/). Validates existing geometry; does not generate.
- **CadexSoft MTK toolkit** — a C++ SDK enumerating named automated checks matching the exact sub-questions asked (High Rib, Small Base Radius Rib, Small Draft Angle Rib, High Screw Boss, Small Distance Between Ribs, etc.) — [docs.cadexsoft.com](https://docs.cadexsoft.com/mtk/mtk_molding_dfm). Detection/flagging only.
- **`by-carrot/cad-auditor`** (GitHub, small/obscure, real and functional) — an open-source rule-based checker on STL meshes via trimesh ray-casting: material-adjusted draft thresholds, wall-thickness min/max, undercuts, rib/boss ratio flagged at >60% of nominal wall (matches Xometry), sharp-corner detection. Cites a real textbook, *Malloy, Plastic Part Design for Injection Molding* (Hanser, 2nd ed. 2010) — [github.com/by-carrot/cad-auditor](https://github.com/by-carrot/cad-auditor). Closest thing found to "the rules formalized as code," but tiny/unadopted.
- Autodesk Fusion's "Plastic rules" DFM feature clearly exists (confirmed via search listings) but its doc pages 403/503'd — feature existence confirmed, thresholds not.

### Automated generators (propose rib/boss placement from scratch): weak-to-none
- Fusion's "Web and Rib" commands exist but content couldn't confirm whether placement is automatic vs. human-sketched (likely semi-parametric rendering of a human-chosen profile — unverified this session, general knowledge only).
- [arXiv 2403.12098, "Deep Generative Design for Mass Production"](https://arxiv.org/abs/2403.12098) — topology optimization incorporating manufacturability constraints (including "rib design") into the generation loop, but generates overall part shape/topology, not rib/boss placement inside a pre-existing enclosure wrapping internal components.
- [arXiv 2607.02448, "AgentsCAD"](https://arxiv.org/abs/2607.02448) — LLM multi-agent pipeline that detects and fixes FDM manufacturability defects; structurally the nearest pattern (checker + geometry-proposing agent) but targets FDM printing, nothing rib/boss/enclosure-specific.
- Direct arXiv searches for `"boss" AND "rib" AND "plastic part"` and `"enclosure design" AND "rule-based" AND "CAD"` returned **zero results** — found nothing. Semantic Scholar rate-limited throughout — a real coverage gap.

**Verdict for this section:** the rule-definition half and the automated-checking half are both mature, multi-vendor, well-precedented. The generation half — automatically placing ribs/bosses in a housing around internal components — is not: nothing found does it.

---

## 3. The general pattern: hierarchy, DFA, and prior art for automatic packaging generation

### Multi-level BOM: the standard hierarchy, confirmed
"Multi-level (indented) BOM... lists the assemblies, components, and parts required to make a product in a parent-child, top-down method," recursive, vs. a flat single-level BOM — [Wikipedia, Bill of materials](https://en.wikipedia.org/wiki/Bill_of_materials) (directly fetched). Vendor phrasing corroborating "top-level assembly as root of hierarchy" (StartProto) and "product structure as a tree with final product at top" (PTC) was surfaced via search snippet only, not independently fetched — lower confidence than the Wikipedia citation. This atomic-part → subassembly → final-product pattern is industry-standard, not something to invent, and matches the tree structure already used by this codebase's instance-graph ledger (`instances[<id>].params`).

### Is DFA the right name for this problem? No — it's narrower.
[Wikipedia, Design for assembly](https://en.wikipedia.org/wiki/Design_for_assembly) (directly fetched): DFA's core mechanism is **part-count minimization** (Boothroyd's three elimination criteria) plus assembly-time scoring tables (grasping/orientation/insertion difficulty). It is an **evaluative/scoring methodology applied to a design a human already produced**, not a generator of new geometry, and the article has **no discussion of retention geometry, housings, ribs, bosses, or spacers**. DFA is the right name for "reduce part count / make assembly cheap" — it does not cover "synthesize the packaging/retention geometry," which is the actual question.

### Prior art for automatic packaging/retention generation — real but fragmented, none matches fully
- **Fusion 360 generative design** — verified directly against Autodesk's own help docs ([Preserve Geometry](https://help.autodesk.com/cloudhelp/ENU/Fusion-GenerativeDesign/files/GD-PRESERVE-GEOM.htm)): optimizes material/shape connecting a fixed set of preserve-geometry anchor points subject to loads and obstacle geometry. Single-part (or local-region) topology optimization between prescribed attachment points — not multi-component packaging synthesis.
- **Packaging Optimization (PO)**, a real named academic subfield (Il Yong Kim's group, Queen's University): [Roper & Kim, IMechE/SAGE](https://journals.sagepub.com/doi/10.1177/09544070221113895) defines PO as positioning components within a design domain under no-overlap/CoG constraints, coupled with structural topology optimization (their iTOPO method), demonstrated on up to 43 simultaneous components in an EV chassis — but stated explicitly to optimize placement/structural material, not generate retention geometry. [LeFrancois & Kim, TRB/TRID](https://trid.trb.org/View/2692106) — automated two-stage placement + A*-routing for automotive wire harnesses/ducts — the closest hit to "parts + relationships → laid-out arrangement," but stops at placement and routing, not the physical retaining shell.
- **Knowledge-Based Engineering (KBE)** — real, industrial, with an important caveat. [Rulestream](https://www.productspace.com/products/cad/rulestream) automatically generates custom CAD/drawings/BOMs from pre-authored rules for engineer-to-order manufacturers ("days or weeks into minutes"). [CATIA KBE via plmcoach.com](https://plmcoach.com/3dexperience-catia-knowledge-based-engineering-guide/) confirmed as parameter/rule-driven templating. **Critical caveat:** KBE generates geometry automatically only for product *families* whose generative rules a human pre-authored in advance — it does not infer novel packaging/retention geometry for an arbitrary, previously-unseen set of components from first principles of their spatial/functional relationships. Two more on-point-sounding leads (a Linköping thesis on automated bracket design in Siemens NX, a ScienceDirect KBE paper) were located but could not be fetched to verify content — flagged as unverified, not cited as findings.
- Retention-feature analysis literature (snap-fit retention-force papers, additive-manufacturing snap-fit methodology papers) — found via snippet, not deep-fetched — is design-methodology/analysis for a human sizing one feature at a time, not automated multi-component generation.

**Verdict for this section:** the hierarchy half of the question is solidly standardized (multi-level BOM). The generative-packaging half has real but fragmented, non-general prior art: placement/routing optimization solves layout-from-relationships; KBE solves geometry-from-pre-authored-rules for known families; Fusion generative design solves single-part shape optimization between fixed points. **No system found takes a novel set of functional components + their relationships and generally synthesizes the enclosing housing/ribs/bosses/spacers** without a human having pre-designed that retention scheme or product family's rules first.

---

## 4. The gearbox worked example — what generalizes and what doesn't

| Gearbox-specific practice | Real citations | Generalizes to broader packaging pattern? |
|---|---|---|
| **Bearing bore alignment / line boring across a housing split** | Fit governed by ISO 286 + DIN 620 ([Engineers Edge](https://www.engineersedge.com/bearing/bearing_shaft_and_housing_16016.htm), snippet only, fetch 403'd); uneven bearing seating causes ring creep/fretting/seizure ([theengineeringblog.com](https://theengineeringblog.com/fits-and-tolerances-on-gearbox-shaft-and-housing/), fetched); line boring achieves ~0.002in coaxiality across bores specifically because standard machining can't guarantee it ([specialtygeardrives.com](https://specialtygeardrives.com/everything-you-need-to-know-about-line-boring-machining/), fetched); identical technique confirmed on split pump casings (swbplus.com.au, ssmiratechsystem.com, snippet-level) | **Strongly generalizes.** This is really "precision co-location of two features that share a kinematic datum across a joint" — applies to any two bearing pillow blocks, pivot bores, or bushings on a rigid frame, gear-unrelated. |
| **Oil seal gland design** | Standardized under ISO 6194-1:1982 and DIN 3760/3761 ([Wikipedia, Radial shaft seal](https://en.wikipedia.org/wiki/Radial_shaft_seal), fetched); [Kalsi Engineering gland guidelines PDF](https://www.kalsi.com/handbook/D05_Kalsi_Seal_gland_guidelines.pdf) title/subject confirmed (body not extractable); Parker Hannifin / Apple Rubber gland-calculation guides confirmed via distributor mirrors (snippet-level) | **Strongly generalizes**, and already is generic outside gearboxes — Parker's guide is fluid-power (cylinders), Kalsi's is rotary drilling motors. Applies to any shaft/rod penetrating an enclosure wall. |
| **Breather/vent** | Thermal cycling causes trapped-air expansion that can deform the housing and compromise seals/admit contaminants without venting; modern ePTFE membrane vents — [CTI Symposium](https://cti-symposium.world/why-venting-is-needed-to-protect-drivetrain-components/), fetched (industry-symposium source, not a textbook) | **Strongly generalizes** — any sealed volume with internal heat generation and external exposure (electronics enclosures, battery boxes, hydraulic reservoirs) needs this; the source itself frames it as "drivetrain components" broadly, not gearbox-specific. |
| **Inspection/access cover** | Weakest sub-topic — only generic component-catalog pages and a student document confirm the feature category exists and is named; **no design-rule source found** (sizing, gasket/bolt pattern, placement relative to internals) | **Generalizes conceptually** (place a removable panel over the parts needing periodic access) but this is closer to common sense than documented prior art from what was found. |
| **Rib placement around bearing bosses for stiffness** | Two real DAGA/DEGA acoustics conference papers specifically on gearbox-housing rib/NVH design, snippet-level only (full PDF text not extractable); IRJET gearbox-casing paper, snippet only | **Strongly generalizes** — arguably the most general of the six: the identical "don't let a load-bearing boss cantilever off a thin shell" principle was independently found in a plastics-DFM guide ([seawinindustrial.com](https://seawinindustrial.com), boss ≈60% wall — same number as section 2) and in metal gearbox-housing NVH papers. Numeric ratios themselves are plastics-specific and should not be reused verbatim for cast/machined metal — flagged explicitly by the source. |
| **Horizontal- vs. vertical-split housing** | Strongest direct evidence is from **compressor** casings, not gearboxes — [ScienceDirect Topics "Compressor Case"](https://www.sciencedirect.com/topics/engineering/compressor-case) (snippet, 403'd on fetch), [ThePipingTalk](https://thepipingtalk.com/types-and-classification-of-centrifugal-compressor/) (snippet). A gearbox-specific citation attempt failed (CAPTCHA-blocked search). | **Generalizes** — parting-plane-vs-shaft-axis tradeoff (assembly access vs. pressure/structural continuity) recurs across pumps, compressors, turbines. The fact that the best-confirmed source is compressor-side rather than gearbox-side is itself evidence this isn't gearbox-only. |

**Standards located:** [AGMA 6001-F19](https://www.normsplash.com/Samples/AGMA/176718566/AGMA-6001-F19-en.pdf) (front matter confirmed real via preview PDF; couldn't confirm whether it has a dedicated housing section) and AGMA 6013-A06 (existence confirmed via ANSI webstore snippet, preview PDF 403'd). Shigley's coverage of housing design specifically was **not verified this session** — flagged explicitly as recalled-not-verified, not cited.

**Net finding:** every one of the six gearbox-specific practices maps cleanly onto a broader, independently-documented packaging pattern (precision datum-sharing, shaft-penetration sealing, sealed-enclosure venting, maintenance-access panels, load-boss stiffening, parting-plane-vs-axis tradeoffs). None of the six turned out to be genuinely gearbox-only once checked — the gearbox is a representative example, not a special case, matching the framing in your original question.

---

## 5. Bottom-line verdict

**What's established enough to encode as deterministic checks/generators right now**, based only on what was actually retrieved above:

- **Glue-part sizing ratios with numeric, cross-corroborated, or standardized sources:** boss OD/wall-thickness/draft/gusset/spacing ratios (plasticmoulds.net × Protolabs agreement); snap-fit cantilever-beam equations (Fictiv × Synectic agreement, both traceable to the Bayer manual); retaining-ring groove dimensions (ASME B27.7 / DIN 471 — real standards with sample values retrieved); bearing shaft-shoulder dimensions (Koyo/JTEKT manufacturer tables). These are all, structurally, lookup-table or closed-form relationships between *a component being retained* and *the retention feature* — exactly the shape of computation a deterministic templater can perform, and there's a direct precedent for the pattern (cq_warehouse's `clearanceHole()`/`tapHole()` already do this for holes-from-fasteners; it would need extending to bosses/rings/glands, not invented from nothing).
- **Housing-shell ratios**, with one caveat: rib thickness/height/draft and general wall-thickness/draft rules are solid (Xometry × Protolabs), but **two of the specific ratios have real, unresolved disagreement across sources** (rib base fillet: 0.25–0.4× wall vs. 0.5–1× wall; rib spacing: ≥2× wall vs. ≥2.5–3× wall) — a deterministic checker should encode this as a documented range or pick one named authority explicitly, not silently split the difference.
- **Parting-line placement logic** (tangent-parallel-to-pull-direction) is genuinely algorithmic and already implemented as an automated check in commercial tools (DFMPro, CadexSoft MTK) and even a small open-source one (cad-auditor) — this is provably adoptable, not aspirational.
- **The product hierarchy itself** — atomic part → subassembly → final product as a tree — is industry-standard (multi-level BOM) and already matches this codebase's existing instance-graph ledger design.

**What still requires human judgment, because no report found deterministic prior art for it:**

- **Automatic derivation of a retention feature from a set of components' spatial relationships** (e.g., "this gear and bearing on this shaft → correct spacer length/OD") — every generator found across all four reports is either a human-driven parametric part library, single-feature auto-sizing from a single spec, placement/routing optimization that stops before generating a retaining shell, or KBE that requires a human to have pre-authored the family's rules already. This piece would be genuinely new work.
- **Automatic rib/boss *placement*** inside a housing wrapping a novel internal-component layout — the DFM numbers say how big/thick a rib should be once you've decided to put one somewhere; nothing found decides *where*. Even the two closest academic leads (generative topology-optimization for manufacturability, and AgentsCAD's LLM-driven fix-proposals for FDM) don't match this specific problem.
- **Split-line/parting-plane orientation choice** for a novel housing, and **inspection/access-cover placement** — both confirmed as real named design decisions with a clear tradeoff logic, but neither reduced to a closed-form rule in what was retrieved.

**The most direct, grounded, non-AI-per-instance path**, built only from what these four reports actually found: treat this as two separable layers, not one problem. Layer one — glue-part *sizing* — has enough closed-form/standardized lookup-table prior art (section 1) to be built as deterministic generators today, following the cq_warehouse precedent of deriving a feature from a component spec. Layer two — housing DFM compliance — has enough precedent (DFMPro, CadexSoft, cad-auditor) to be built as a deterministic *validator* against generated geometry, which is a fundamentally easier and already-proven-adoptable problem than a generator. What has no established deterministic prior art anywhere in this research — and should be treated as the genuinely open, human-judgment-requiring piece rather than assumed solvable by pattern-matching to gearbox practice — is the step that goes from "here are N components and their relationships" to "here is the placed, retained, ribbed enclosure," i.e., placement/topology decisions themselves. Section 4's finding that gearbox practices generalize cleanly is useful precisely because it tells you *which* rules to encode once you reach layer one and two — it does not supply the missing layer-three placement logic.

---

## Part B — How this maps onto THIS project's existing architecture (grounded in code, not speculation)

This section is written directly by the orchestrating session, grounded in the subsystem catalog and
composition mechanisms already read/audited earlier the same day (the ribs/gussets research, the
regions research, and the parametric-drivetrains codebase audit all touch pieces of this).

### B1. The catalog already has a real, substantial "packaging glue" parts library

A direct listing of `packages/subsystems/` for retention/spacing/enclosure-adjacent names turns up:
`standoff.py`, `hex_standoff.py`, `pcb_stack_standoff.py`, `pcb_stack_rail.py`, `prop_spacer.py`,
`stepped_spacer.py`, `flat_shim.py`, `tapered_shim.py`, `flat_gasket.py`, `washer.py`,
`fender_washer.py`, `thrust_washer.py`, `threaded_boss.py`, `press_fit_boss.py`, `oring_boss.py`,
`cable_gland_boss.py`, `cable_passthrough_boss.py`, `snap_fit_box.py`, `snap_pin.py`,
`inspection_cover.py`, `sliding_lid_box.py`, `cover_plate.py`, `rail_clip.py`, `cable_clip.py`,
`wire_clip.py`, `mic_clip.py`, plus a wide bracket family (`bracket.py`, `lbracket.py`, `cbracket.py`,
`z_bracket.py`, `frame_corner_bracket.py`, `corner_bracket_gusseted.py`, and more). This is exactly the
vocabulary the external research (Part A, sections 1–2) confirms is the real, established
DFM "glue parts" list — bosses, spacers, standoffs, snap-fits, retention features — and this
project already has named, parametrized, `fea_eligible`-tagged (where relevant) catalog entries for
most of it. This is a genuinely strong starting position most from-scratch projects wouldn't have.

### B2. What's missing is the DECISION layer, not the parts

Per Part A's own bottom-line verdict: every real DFM source found (Protolabs' boss ratios, the Fictiv/
Synectic snap-fit beam equations, ASME B27.7/DIN 471 retaining-ring tables, bearing-manufacturer
shoulder-height tables) is a rule a human engineer looks up and applies by hand — nothing found
automatically decides, from a set of positioned components, how many standoffs a board needs, where a
boss goes relative to a wall, or what retaining-ring groove a given shaft diameter needs. This project's
own composition tooling has the identical shape:

- `packages/subsystems/compose.py` already provides the right *mechanical* primitives —
  `call(name, **overrides)` (instantiate a child from the registry), `place(part, x, y, z, rx, ry, rz)`,
  `place_polar(part, radius, theta_deg, z)` (angular-array convenience), `compose(scope_map)`, and
  `fuse(**scope_map)`. This is a real, working, hand-authorable composition toolkit — confirmed
  used today by `table.py` (`flat_bar` top + N `round_post` legs) and other Phase-F subsystems.
- But per the earlier ribs/gussets/lattices research and the parametric-drivetrains codebase audit
  (both filed the same day), `assembly_template.py`'s `ChildSpec` only carries a static
  `Transform` + flat `params: dict[str, float]` — every existing user (`table.py`,
  `standoff_frame.py`, `rail_mount_assembly.py`) computes placement via **hand-written positional math
  in Python**, not a rule engine reading DFM ratios. There is no mechanism today that takes "here are
  N components at these positions" and outputs "here are the M standoffs/bosses/spacers this layout
  needs, sized per the boss-diameter-is-2x-screw-diameter rule" — a human (or an LLM proposing
  `instance_ops`) still has to decide the count/placement/sizing explicitly, the same gap Part A found
  in the external world.

### B3. The `assembly_template` nesting limitation matters even more here than for drivetrains

The same single-level limitation flagged in the drivetrain research
(`reconcile_all()`'s own docstring: *"does not (yet) handle an assembly-template instance whose OWN
children are themselves assembly-template instances"*) is arguably a bigger blocker for general
packaging than for gear trains: a realistic "package this drivetrain into a gearbox" job is naturally
a THREE-level hierarchy (atomic parts → functional subsystem, e.g. a gear-and-shaft assembly →
the housing that packages several such subsystems together) — exactly the nesting this mechanism
doesn't support today.

### B4. Regions research (same day) supplies the missing spatial-reasoning half

The `build-plan/research03aug/regions/` research (same day) found that build123d has no native
"leftover free space" computation, but the primitives (`Mode.SUBTRACT`/boolean cut, plus `Shape.label`
for tagging) are real and composable. A genuine "final packaging" generator would need exactly that
capability — compute the housing's interior cavity minus the placed functional components, and
whatever's left over is where spacers/ribs/bosses could go — tying these two same-day research
threads together directly: DFM rules (this doc) decide WHAT glue part and HOW BIG; the regions
research's leftover-volume computation decides WHERE it's even possible to put one.

### B5. Net assessment

Nothing here is a blocker, and this project starts from an unusually strong position (the parts
catalog already exists). The concrete, nameable gap is a **rule-encoding layer**: a deterministic
function (not an LLM call, matching the project's own "never free Python, never a fabricated number"
discipline) that reads a component layout + the real DFM ratios found in Part A and proposes
`instance_ops` for the needed standoffs/bosses/spacers — essentially a domain-specific
"auto-layout" pass sitting above `compose.py`'s existing mechanical primitives, informed by leftover-
space computation (B4) and eventually able to nest (B3) once `assembly_template` supports it.

---

## Part A raw agent reports (unedited)

### Agent U — component retention/mounting hardware: established DFM design rules and any parametric generators

## Findings: DFM design rules for retention/mounting hardware (screw bosses, snap-fits, standoffs/spacers, shaft/bearing retention)

**Note on method:** WebSearch ran out of session budget almost immediately, so after the first four queries I worked entirely through WebFetch — using DuckDuckGo's static HTML endpoint (`html.duckduckgo.com/html/?q=`) to get real result URLs, then fetching those URLs directly. Every URL below was actually retrieved this session. A few promising URLs (Bing results, Schaeffler, Timken, EngineersEdge bearing page, Micronshub, qlutionmold) 403'd, timed out, or returned JS-shell/no-content pages — I've flagged those as "found but not extractable" rather than citing content I never actually saw.

---

### 1. Screw bosses (injection molding)

**[Designing Bosses for Injection Molding: A Complete Guide — plasticmoulds.net](https://www.plasticmoulds.net/designing-bosses-for-injection-molding-a-complete-guide.html)**
This is the strongest, most quantitative hit and matches exactly the kind of rule the question asked about:
- Boss OD = **2× screw diameter** (unfilled thermoplastic), **2.5×** for glass-filled
- Boss wall thickness = **0.5–0.6× nominal wall thickness T** (prevents sink)
- Pilot hole for self-tapping screws = screw major dia minus one thread depth
- Draft: **0.5–1°/side**
- Boss height ≤ **3× OD**; gussets recommended above 2× OD
- Gusset thickness ≈ **0.5× T**
- Base fillet ≥ **0.25× T**
- Boss-to-boss spacing ≥ **2× OD** center-to-center

**[Protolabs — Plastic Boss Design on Molded Parts](https://www.protolabs.com/resources/design-tips/plastic-boss-design-on-molded-parts/)**
Real, well-known manufacturer DFM source. Confirms the wall-thickness rule independently: **40–60% of adjoining wall thickness**, draft **0.5°–3°**. Qualitative on gussets/sink avoidance rather than numeric — but corroborates plasticmoulds.net's ratio from an independent, more authoritative source.

**[RapidDirect — Screw Boss Design](https://www.rapiddirect.com/blog/screw-boss-design-injection-molding/)** — found via search, timed out/429'd on fetch, not verified in content.
**Microns Hub boss-design-rules page** — found, 429'd, not verified in content.

→ Verdict for this sub-topic: **solid prior art**, numbers cross-confirmed by two independent sources (a molder-authored guide + Protolabs).

### 2. Snap-fits

Confirmed: real, closed-form beam-mechanics equations exist and are widely published (these trace back to the classic Bayer/GE Plastics snap-fit design manuals).

**[Fictiv — How to Design Snap Fit Components](https://www.fictiv.com/articles/how-to-design-snap-fit-components)**
Gives: max strain εmax = 1.5·t·Y/(L²·Q); deflection force P = b·t²·ε·E/(6L); mating force W = P·[(μ+tanα)/(1−μ·tanα)].

**[Synectic — Snap Fit Design](https://synectic.net/snap-fit-design/)**
Independently gives the same family of equations with matching structure: max allowable deflection Y = 0.67·(ε·L²/H); deflection force P = (B·H²·E·ε)/6L; frictional/mating force combination W = P·F.

Two independent commercial DFM sources give matching cantilever-beam formulas (strain ∝ t/L², force ∝ E·ε·b·t²/L) — this is the standard textbook cantilever snap-fit derivation, confirmed as real and citable.

**[MIT-hosted PDF, "Plastic_Snap_fit_design.pdf"](https://fab.cba.mit.edu/classes/S62.12/people/vernelle.noel/Plastic_Snap_fit_design.pdf)** and **[productdesignonline.com Snap-Fit Design Manual PDF](https://productdesignonline.com/wp-content/uploads/2019/08/Snap-Fit-Design-Manual.pdf)** — both retrieved (real files, ~1-2.5MB), almost certainly the well-known Bayer "Snap-Fit Joints for Plastics" design manual given the filenames/hosting, but WebFetch's PDF extraction failed on both (returned binary/garbled), so I could not read/quote their content this session — flagging as found-but-unverified rather than citing.

**[Qlution Mold — Snap Fit Design Guide & Free Calculator](https://qlutionmold.com/snap-fit-design-guide/)** — found via search (indicates an interactive calculator exists), but fetch 403'd, content not verified.

→ Verdict: **solid prior art**, equations confirmed from two independently-fetched, readable sources.

### 3. Standoffs/spacers

**PCB standoffs:** **[fastturnpcbs.com PCB Standoffs Guide](https://www.fastturnpcbs.com/blog/pcb-standoffs-guide/)** fetch 403'd. **[bestpcbs.com PCB Standoffs guide](https://www.bestpcbs.com/blog/2026/07/pcb-standoffs/)** fetched successfully: standard body heights by thread (M2: 3–15mm, M2.5: 4–20mm, M3: 5–25mm, M4: 6–30mm), hole clearance-over-screw-diameter tables (e.g., M3 screw 3.0mm → finished hole 3.2–3.5mm), and a soft rule of "4 corner supports minimum" for small/light boards, no quantified edge-distance/spacing rule.

**Shaft spacers (between bearings/gears):** This is the weakest sub-topic. I found real vendor engineering-tool pages — **[Timken Bearing Installation Calculations](https://engineering.timken.com/engineering-tool/bearing-installation-calculations/)**, **[Schaeffler "Design of bearing arrangements"](https://medias.schaeffler.us/en/knowledge-center/rolling-bearings/design-of-bearing-arrangements)** — that clearly exist and are the right authoritative source, but both returned JS-shell pages with no extractable body text via WebFetch, so I cannot quote their actual rules. One low-quality hit, **truegeometry.com**, gave a spacer-thickness "formula" that mixes units nonsensically (looks like AI-generated SEO content, not a real engineering source) — I'm explicitly not treating that as a citable finding.

→ Verdict: PCB standoffs have decent numeric prior art; **shaft/gear spacer sizing rules were not actually retrieved this session** despite locating the right authoritative sources (Timken/Schaeffler) — this piece is unconfirmed, not disconfirmed.

### 4. Shaft/bearing retention (retaining rings, shaft shoulders)

**Retaining rings — standard confirmed real:** **[ASME B27.7](https://www.asme.org/codes-standards/find-codes-standards/b27-7-general-purpose-tapered-reduced-cross-section-retaining-rings-metric)** — title confirmed: "General Purpose Tapered and Reduced Cross Section Retaining Rings, Metric," scope covers groove dimension recommendations for three ring series across standard shaft/housing sizes. Table itself is paywalled ($39), so I could not pull actual numbers from ASME directly, but a downstream vendor table citing it, **[RivCut retaining ring chart](https://www.rivcut.com/resources/retaining-ring-chart)**, gave real sample values (e.g. 1" shaft → 0.955" groove dia, 0.054" groove width) sourced "per ANSI B27.7."

**Metric/DIN equivalent confirmed:** **[mechcodex.com DIN 471 table](https://mechcodex.com/reference/retaining-ring-sizes-external)** gave a real dimension table (shaft dia → groove dia d₂/width m/depth t, e.g. 20mm shaft → 19.0mm groove dia, 1.3mm width, 0.50mm depth), tolerances h11/H13 noted, citing DIN 471.

**Shaft shoulders — confirmed with real numbers:** **[Koyo/JTEKT Bearing Knowledge — Mounting Dimensions](https://koyo.jtekt.co.jp/en/support/bearing-knowledge/14-2000.html)** is a genuine bearing-manufacturer engineering reference: shoulder diameter da (shaft) must exceed the ball-set pitch diameter for thrust bearings; a standard table (their Table 14-2) tabulates fillet radius ra(max) and shoulder height h(min) against the bearing's own chamfer dimension r(min), across two load cases ("general" vs "special/light axial load," the latter permitting reduced shoulder height); a separate Table 14-3 covers ground shaft-undercut dimensions (r = 1–7.5mm). This is exactly the "shaft shoulder" standard the question asked about, from a primary bearing manufacturer.

→ Verdict: **solid prior art**, both the retaining-ring standard (ANSI/ASME B27.7, DIN 471) and shaft-shoulder-for-bearings standard (bearing-mfr mounting-dimension tables) are real, named, standardized, and I retrieved real numeric excerpts from each family.

### 5. Parametric/algorithmic generators (the actual novel-content question)

This is the most important finding for your purposes, since it's the closest thing to prior art for what your ledger/templater would need to do:

**[cq_warehouse "fastener" module (CadQuery)](https://cq-warehouse.readthedocs.io/en/latest/fastener.html)** — real, documented, and genuinely does *automatic sizing*: given a fastener spec, its `Workplane.clearanceHole()`, `.tapHole()`, and `.threadedHole()` methods compute and cut correctly-sized holes automatically (using tables like `clearance_hole_diameters`/`tap_hole_diameters`), and can auto-place matching washers/fasteners into an assembly. This is a real precedent for "given the component (a screw), automatically size the retention feature (a hole)" — but it's scoped to holes/fasteners, not full boss geometry (boss OD/height/gusset), and not snap-fits or shaft retention.

**[build123d-parts-lib (GitHub, baibai2013)](https://github.com/baibai2013/build123d-parts-lib/blob/main/README_EN.md)** — real repo with parametric generators for a **heat-set-insert boss** ("standard fastening for FDM printed parts") and a **snap-fit latch** ("screw-free lid/enclosure fastening"), plus static circlip/retainer parts and standoff/fastener parts. No groove-cutting or shaft-shoulder generator found in its README.

I did not find any generator (in build123d, CadQuery, or elsewhere) that takes a *set of components to be retained* (e.g. "this gear and this bearing on this shaft") and *derives* the correct spacer length/OD, boss placement, or retaining-ring groove position from their geometry — everything found is either (a) a human-driven parametric *part* (you still choose dimensions/placement) or (b) auto-sizing a single feature from a single fastener spec (cq_warehouse holes). Nothing implements the "given retained components → compute retention feature" inference your question is really asking about.

---

### One-line verdict

Solid, real, well-documented DFM prior art exists for **boss sizing ratios, snap-fit beam mechanics, and standardized retaining-ring/shaft-shoulder dimensions** (all independently cross-confirmed this session); PCB standoff sizing has decent but thinner numeric prior art and shaft/gear spacer sizing rules exist at authoritative sources (Timken/Schaeffler) I located but could not extract this session; and on the parametric-generator question specifically, real but narrow precedent exists (cq_warehouse auto-sized fastener holes, build123d-parts-lib's heat-set-boss and snap-fit generators) — nothing found does full automatic derivation of retention-feature geometry from the components being retained, so that piece would be genuinely new work, not reimplementation of existing art.

---

### Agent V — housing/enclosure design methodology: ribs, walls, parting lines, boss placement as a formalized ruleset

# Research Findings: Housing/Enclosure DFM Rules — Rib, Wall, Draft, Parting-Line, Boss Placement

**Methodology note:** WebSearch was unavailable for this entire session (budget exhausted before my first query fired). All findings below come from WebFetch — either direct fetches of pages I could name/discover through link-following, or fetches of DuckDuckGo HTML results pages used as a search substitute. Every URL below was actually retrieved this session; where a lead existed but I could not get past a paywall/403/503, I say so explicitly rather than citing it as verified content.

## Part 1: Do the numeric DFM rules exist and are they real/standard?

**Yes — confirmed with real, fetched sources, and the numbers cluster consistently across independent publishers.**

1. **Xometry — "Plastic Ribs for Injection-Molding Design"** (Aaron Lichtig)
   https://www.xometry.com/resources/injection-molding/plastic-ribs-for-injection-molding-design/
   - Rib thickness ≤ **60% of nominal wall** ("Glossy materials may require ribs with a thickness of 40%")
   - Rib height ≤ **3× rib thickness** (else underfill risk)
   - Rib base fillet radius = **0.5–1× wall thickness**
   - Rib draft = **0.5–1.5°**
   - Rib spacing ≥ **2.5–3× nominal wall thickness**
   - Thickness-transition run length = **3× the change in thickness**
   - Directly answers the rib-ratio, spacing, and draft sub-questions with exact numbers.

2. **Protolabs — "Plastic Boss Design on Molded Parts"**
   https://www.protolabs.com/resources/design-tips/plastic-boss-design-on-molded-parts/
   - Boss wall thickness = **40–60% of the wall it rises from**; draft **0.5°–3°**; use ribs (not solid fill) to tie a boss back to a nearby wall, with gussets for added strength — this is the specific "boss near a wall to avoid sink" rule.

3. **Protolabs — "Draft Angle Guidelines for Injection Molding"**
   https://www.protolabs.com/resources/design-tips/improving-part-moldability-with-draft/
   - Rule of thumb: **1° per inch of cavity depth**; minimum **0.5°** on all vertical faces, **1–2°** typical; **3°** minimum for metal-to-metal shutoffs; **3°/5°+** for light/heavy texture (PM-T1/PM-T2).

4. **Protolabs — "Planning for Parting Lines in Injection Molding"**
   https://www.protolabs.com/resources/design-tips/planning-for-parting-lines-in-injection-molding/
   - Codifiable logic found: the parting line must trace the path where the **surface tangent is parallel to the mold-opening direction**; it dictates draft direction for every feature; place on sharp edges (hides flash/seam), avoid crossing radiused/cosmetic surfaces; LSR parts keep the line off sealing surfaces.

5. **Protolabs — "Solving Wall Thickness Issues in Molded Parts"**
   https://www.protolabs.com/resources/design-tips/solving-wall-thickness-issues-in-molded-parts/
   - Material-specific nominal wall ranges (e.g., ABS 0.045–0.140in, PP 0.025–0.150in), min slot width 0.040in.

**Nuance on the "50-60%" figure in the prompt:** the number that actually recurs across every independent real source I retrieved (Xometry, Protolabs, and both tools in Part 2) is **"up to 60% of nominal wall,"** with 40% showing up as a floor for glossy/cosmetic surfaces or as the low end of boss thickness. "50-60%" isn't the exact phrasing anyone uses — "≤60% (40% for class-A surfaces)" is closer to the real rule.

Fictiv's design-guide index page and Xometry's guide-hub were reachable, but their actual article bodies didn't render through WebFetch (landing/index pages only) — I don't have quotable rib numbers from Fictiv specifically, only confirmation their guide exists.

## Part 2: Does anything encode these rules as an automatic checker or generator?

**Automated CHECKERS: yes, multiple real, working examples exist.**

- **DFMPro (HCL/Sigmetrix)** — commercial CAD plug-in (SolidWorks/Creo/NX/CATIA/3DEXPERIENCE)
  https://dfmpro.com/manufacturing-processes/dfmpro-for-injection-molding/
  Automatically checks uniform wall thickness, rib parameters, draft on core/cavity, undercuts, thin-steel mold conditions against a built-in rule set (rib base fillet 0.25–0.4× wall, rib draft ~1–1.5°/min 0.5°, rib spacing ≥2× wall). It's a **validator running against existing geometry**, not a generator.

- **CadexSoft MTK toolkit** (C++ SDK, geometry-kernel level)
  https://docs.cadexsoft.com/mtk/mtk_molding_dfm
  Enumerates named automated checks matching almost exactly the sub-questions asked: *High Rib, Irregular Thickness Rib, Small Base Radius Rib, Small Draft Angle Rib, High Screw Boss, Small Base Radius Boss, Small Draft Angle Screw Boss, Irregular Wall Thickness Screw Boss, Small Distance Between Ribs*. Detection/flagging only, no evidence of auto-fix generation.

- **`by-carrot/cad-auditor`** (open source, GitHub, 0 stars — small/obscure but real and functional)
  https://github.com/by-carrot/cad-auditor
  A working rule-based DFM checker operating on STL meshes via trimesh ray-casting: draft angle (material-adjusted: ABS 1.0°, PC 1.5°, TPE 3.0°), wall thickness min/max per material, undercuts (>15° past perpendicular), **rib/boss thickness ratio flagged at >60% of nominal wall** (matches Part 1 exactly), sharp corners (<45° dihedral), boss detection via thickness clustering. Notably cites **Malloy, *Plastic Part Design for Injection Molding*, Hanser, 2nd ed. 2010** — a real textbook — plus Protolabs/Fictiv as its rule sources. It has an Anthropic-API layer for *interpreting* results in natural language, not for generating geometry. This is the single closest thing I found to "the rules formalized as code," but it's a tiny, unadopted project, not established prior art.

- **Autodesk Fusion — "Plastic rules" DFM setup** and an Autodesk University class ("Design Molded Plastic Parts Faster with Plastic Design Rules") clearly exist (found via real search-result listings), but the actual doc pages returned HTTP 403/503 every time I tried to fetch them — I can confirm the feature's existence but **not** its specific rule thresholds this session.

**Automated GENERATORS (propose rib/boss placement from scratch): weak-to-none found.**

- **Fusion Design Extension "Web and Rib" commands** — real feature (confirmed via a fetched Autodesk help snippet: "Use the Web and Rib commands to reinforce your design"), but the fetched content couldn't confirm whether placement is automatic vs. user-sketched. General knowledge (not verified this session) is that this is a semi-parametric tool where the human still selects the profile/edges — i.e., parametric *rendering* of a human-specified rib, not autonomous placement.

- **arXiv 2403.12098, "Deep Generative Design for Mass Production" (2024)**
  https://arxiv.org/abs/2403.12098
  Topology-optimization-style generative design that folds die-casting/injection-molding manufacturability constraints (removing non-manufacturable overhangs, wall thickness, explicitly "rib design") into the generation loop via 2D depth-image simplification. This generates overall part *shape/topology* under manufacturing constraints — not the placement of ribs/bosses inside a pre-existing enclosure wrapping internal components, which is the actual ask. Closest academic generator-side analog, but not a match.

- **arXiv 2607.02448, "AgentsCAD: Automated Design for Manufacturing of FDM Parts via Multi-Agent LLM Reasoning"**
  https://arxiv.org/abs/2607.02448
  An LLM-agent pipeline (Claude Sonnet reasoning agent + vision-language verifier + a GraphSAGE network trained on ~59,665 CAD parts) that detects manufacturing defects (overhangs >45°) and **recommends/generates specific fixes** (reorientation, fillets, chamfers). Structurally this is the nearest pattern to "an agent that both checks against DFM rules and proposes geometry changes" — but it targets **FDM 3D printing**, not injection-molded enclosures, and has nothing rib/boss/wall-thickness specific.

- Direct arXiv searches for `"boss" AND "rib" AND "plastic part"` and `"enclosure design" AND "rule-based" AND "CAD"` both returned **zero results** — found nothing there.
- Two more directly on-topic-sounding papers turned up only as titles via search-result snippets, and I could not get past access walls to verify their content, so I am not citing their claims: *"An Automated System for Design for Manufacturability Analysis for Die-Casting"* (ResearchGate, 403) and *"Automatic detection of manufacturing issues in CAD parts for DFM analysis"* (Springer chapter, login-walled; ResearchGate copy 403).
- Semantic Scholar's API rate-limited every attempt (HTTP 429), so I could not do a systematic academic-literature sweep there — this is a real gap in coverage, not a "nothing found" result.

## Verdict

Solid prior art exists for the **rule-definition** half of this question — the wall/rib/boss/draft/parting-line numbers are real, standard, and consistently cited across independent commercial DFM sources (Protolabs, Xometry) and are reproduced verbatim as thresholds inside at least two real automated checkers (DFMPro commercially, CadexSoft MTK as an SDK) plus one small open-source one (cad-auditor). Solid prior art also exists for **automated rule-checking as a category** — this is a mature, multi-vendor space. But prior art for the specific thing being asked — a tool that **generates/proposes** rib layout and boss placement automatically for a housing wrapping internal components, rather than a human placing them and software flagging violations — is thin: the closest hits (Fusion's Web/Rib commands, the 2024 generative-design paper, the 2026 AgentsCAD multi-agent paper) each match only part of the ask and none targets rib/boss placement in an injection-molded enclosure specifically. Net: **the rules are well-established and the checker side is well precedented; the generator side is not** — that's the open piece, not something to assume already solved.

---

### Agent W — multi-level assembly/BOM composition and automated packaging-generation prior art

## Findings: Assembly Hierarchy & Automated Packaging Generation Prior Art

### 1. Multi-level BOM / product structure — yes, there's a standard pattern

**[Bill of materials — Wikipedia](https://en.wikipedia.org/wiki/Bill_of_materials)** (fetched directly). Confirms the standard term is **multi-level (indented) BOM**: "a bill of materials that lists the assemblies, components, and parts required to make a product in a parent-child, top-down method." Each sub-component can itself have children, recursively, forming a tree. Contrasted with a single-level BOM (flat, no nesting). Vocabulary: **top-level/final assembly → sub-assemblies/intermediate assemblies → atomic parts/raw materials**.

A follow-up DuckDuckGo-surfaced pass (search results only, not independently fetched per-source) added corroborating phrasing from vendor/PLM sources — StartProto describing the top-level assembly as "the root of the hierarchy," and PTC describing product structure as "a hierarchy, or tree-like format, with the final product at the top." I did not independently fetch startproto.com or ptc.com pages to confirm wording beyond the DDG snippet, so treat those two attributions as lower-confidence than the Wikipedia citation.

**Relevance**: this is exactly the "atomic part → subassembly → final product" pattern the question asks about, and it's industry-standard, not something to invent. It also lines up with what your own memory notes describe as the instance-graph/tree ledger model (`instances[<id>].params`) — that's structurally the same tree PLM systems already use for product structure/multi-level BOM.

### 2. Design for Assembly (DFA) / Boothroyd-Dewhurst — confirmed narrower than the question

**[Design for assembly — Wikipedia](https://en.wikipedia.org/wiki/Design_for_assembly)** (fetched directly). DFA's core mechanism, per the article, is **part-count minimization** — Boothroyd's three criteria for whether a part can be eliminated or combined with another — plus tables scoring assembly time against grasping/orientation/insertion difficulty. It is an **evaluative/scoring methodology** applied to a design a human already produced, not a generator of new geometry. The article contains **no discussion of retention geometry, housings, ribs, bosses, or spacers** — that's outside DFA's documented scope.

**Verdict on this sub-question**: DFA is the right established name for "reduce part count / make assembly cheap," but it does **not** answer "automatically synthesize the retention/packaging geometry."

### 3. Fusion 360 "generative design" — confirmed to be a narrower thing than packaging

Verified via Autodesk's own help documentation (surfaced and then directly fetched):
- **[help.autodesk.com — Preserve Geometry](https://help.autodesk.com/cloudhelp/ENU/Fusion-GenerativeDesign/files/GD-PRESERVE-GEOM.htm)** (fetched directly): "A preserve geometry is one of the geometry types in the design space. You assign it to bodies to incorporate them in the final shape of the design." Preserve geometry = fixed connection points (bolt holes, attachment areas) that must remain; obstacle geometry = volumes to avoid; loads are applied to the preserve geometry.

Direct summary of the mechanism: Fusion 360 generative design **optimizes the material/shape of the region connecting a fixed set of preserve-geometry anchor points**, subject to loads and obstacles — the classic example given in Autodesk's own docs is a single caster-wheel bracket. It does **not** take "here are N functional components and how they relate" and produce a complete enclosing housing with ribs/bosses/spacers for all of them. It's single-part (or small local region) topology optimization between prescribed attachment points, not multi-component packaging synthesis.

(Autodesk's marketing pages at autodesk.com returned HTTP 403 to WebFetch directly — bot-blocked — so this is sourced from Autodesk's own help.autodesk.com technical documentation instead, which is more authoritative anyway.)

### 4. "Component packaging optimization" — real, established research area, but it solves *placement/routing*, not *housing synthesis*

This is a genuine, named academic subfield, confirmed via two papers (both fetched directly), both from Il Yong Kim's group (Queen's University):

- **[Roper & Kim, "Integrated topology and packaging optimization for conceptual-level electric vehicle chassis design via the component-existence method," Proc IMechE (SAGE)](https://journals.sagepub.com/doi/10.1177/09544070221113895)** — defines **Packaging Optimization (PO)** as "a class of numerical design tool for solving component distribution problems," positioning parts within a design domain subject to no-overlap and center-of-gravity constraints, and couples it with structural topology optimization (their method: iTOPO) so material distribution and component placement co-evolve. Demonstrated on up to 43 simultaneous components in an EV chassis. **Scope limit, stated explicitly in my fetch summary**: it optimizes placement/structural material around pre-defined component candidates — it does not generate retention geometry (housings, ribs, bosses).

- **[LeFrancois & Kim, "Multi-Stage Packaging and Routing Optimization for Automotive Component Layout, Wire Harness and Duct Route Design," TRB/TRID](https://trid.trb.org/View/2692106)** — an automated two-stage pipeline: stage 1 optimizes component placement in a bounded design space, stage 2 runs A* pathfinding + gradient optimization to route wire harnesses/ducts between the placed components. Demonstrated on automotive dashboard design. This is the closest thing found to "parts + relationships → laid-out packaged arrangement," but it stops at **placement and routing**, not synthesizing the physical retaining shell.

**Verdict on this sub-question**: real, citable prior art exists for automated spatial layout/routing given components + connectivity constraints. It does not extend to generating the housing/rib/boss geometry itself.

### 5. Knowledge-Based Engineering (KBE) — the closest real industrial prior art to "generate geometry from rules," with an important caveat

KBE (CATIA Knowledgeware, Siemens NX KBE, and commercial engineer-to-order tools) is a real, established industrial field. Confirmed via direct fetch:

- **[Rulestream, via productspace.com](https://www.productspace.com/products/cad/rulestream)** (fetched directly): "captures and reuses your product, engineering, and business rules to automatically generate custom designs" — produces complete 3D CAD models, drawings, and BOMs by applying pre-authored rules, for engineer-to-order/configure-to-order manufacturers (e.g., "days or weeks into minutes").

- **CATIA KBE**, via a secondary source (**[plmcoach.com](https://plmcoach.com/3dexperience-catia-knowledge-based-engineering-guide/)**, fetched directly): confirmed as parameter/rule-driven ("contextual and automatic topological changes," templates encapsulating "feature, part and assembly specifications") — but my fetch could not confirm it does fully automatic *structural* geometry synthesis beyond parameter-driven template instantiation.

**The critical caveat, load-bearing for your question**: KBE systems generate geometry automatically only for product *families* whose generative rules a human engineer pre-authored in advance (e.g., "this conveyor bracket family always gets this rib pattern given these load/span inputs"). They do not infer novel packaging/retention geometry for an arbitrary, previously-unseen set of components from first principles of their spatial/functional relationships — that inference-from-novel-relationships step is exactly what's not covered.

I also found, but could **not** fetch to verify content (403/connection-refused — reporting title/URL only, unverified beyond the search snippet):
- A Linköping University master's thesis, title as surfaced by search: "Development of a Knowledge-Based System for Automated Bracket Design in Siemens NX" — `liu.diva-portal.org/smash/get/diva2:2003801/FULLTEXT01.pdf`. Sounds directly on-point (automated bracket generation) but I have not verified its actual content this session — flagging explicitly rather than reporting it as confirmed.
- A ScienceDirect paper on a "Knowledge-Based Automated Design System" (`sciencedirect.com/science/article/pii/S0957417421004012`) — same caveat, snippet-only, not independently verified.

### 6. Retention-feature (snap-fit/boss) literature — design guidance, not automated generation

Found via search (titles/URLs surfaced, not independently deep-fetched beyond DDG snippets):
- "Experimental Analysis on Retention Forces of Cantilever Hook Snap-Fits" — `link.springer.com/chapter/10.1007/978-981-99-8819-8_29`
- "Methodology for design process of a snap-fit joint made by additive..." — `sciencedirect.com/science/article/pii/S2212827119301350`

Both are **design methodology / analysis** papers (how to size a snap-fit given a joint, how to compute retention force) — guidance for a human designing one retention feature at a time, not automated multi-component enclosure generation.

### 7. Adjacent-but-not-matching: recent LLM-CAD papers found by accident

While searching I surfaced **[arXiv:2607.05573, "Foundation Models for Automatic CAD Generation" (fetched directly)](https://arxiv.org/abs/2607.05573)** by de Curtò, Guillén, de Zarzà — real paper, benchmarks LLMs generating single mechanical parts (plates with holes, boxes, flanged cylinders, L-brackets) from text via a framework called LLMForge. This is tangential to your own project's problem space but **not** about multi-component packaging/enclosure generation, so not direct prior art for this question.

---

### What I could not do this session

WebSearch's session budget was exhausted before I could run any of it (0 successful calls — all four parallel queries returned "budget used"), so everything above came from WebFetch against Wikipedia, Autodesk's help docs, arXiv, SAGE/TRID, and DuckDuckGo/Bing HTML result pages used as a search substitute. That's a real constraint: I did not get to do iterative scholarly-database searching (Google Scholar, IEEE Xplore, ACM DL were not reachable — Semantic Scholar returned only nav chrome, JS-rendered), so there is likely additional academic literature on "automated enclosure/packaging design synthesis" (this looks like an active CAD-research niche — e.g., possibly ASME IDETC / CAD journal / Computer-Aided Design papers) that a proper database search would surface and I did not find.

### One-line verdict

**Partial prior art, not full prior art**: the *hierarchy* half of the question (atomic part → subassembly → final product) is solidly standardized (multi-level BOM/product structure, confirmed on Wikipedia and PLM vendor sources); the *generative packaging* half has real but **fragmented, non-general** prior art — component-placement/routing optimization (Kim et al.) solves layout-from-relationships, KBE/Rulestream solves geometry-from-pre-authored-rules for known product families, and Fusion 360 generative design solves single-part shape optimization between fixed attachment points — but no system found this session takes "here are novel functional components + their spatial/functional relationships" and **generally synthesizes the enclosing housing/ribs/bosses/spacers** without a human having pre-designed that specific retention scheme or product family's rule set first.

---

### Agent X — gearbox housing design as a concrete worked example (generalized, not the only focus)

# Research Report: Gearbox Housing Design as a Worked Example of "Packaging" Pattern

**Method note:** The WebSearch tool was unavailable this session (session search budget exhausted before I could use it). All findings below come from WebFetch calls against DuckDuckGo/Bing HTML search-result pages and then fetching the actual source pages/PDFs. Every URL below was actually retrieved this session — none are reconstructed from memory. Where I could not get readable page text (several PDFs returned only binary/metadata), I say so explicitly and only cite what was actually confirmed (title, existence, subject line).

---

## 1. Bearing bore alignment / coaxiality across a housing

**What I found, with real citations:**

- **Engineers Edge — "Bearing Shaft and Housing Installation Tolerances"** (`www.engineersedge.com/bearing/bearing_shaft_and_housing_16016.htm`) — found via search snippet, direct fetch was blocked (403). Snippet confirms: fit/tolerance for bearing seats is governed by **ISO 286** (shaft/housing tolerance grades) combined with bearing-specific deviations **Δdmp/ΔDmp per DIN 620**.
- **theengineeringblog.com — "Fits and Tolerances on Gearbox Shaft and Housing"** (`theengineeringblog.com/fits-and-tolerances-on-gearbox-shaft-and-housing/`) — fetched successfully. Confirms real content: oversized/undersized shaft and bore both cause failure modes (ring creep, seizure, fretting); explicitly states bearing seating "must not be uneven, causing distortion or an out-of-round condition" — cylindricity and perpendicularity matter, not just diameter. Did **not** explicitly address split-line/cross-wall alignment.
- **specialtygeardrives.com — "Everything You Need to Know About Line Boring Machining"** (`specialtygeardrives.com/everything-you-need-to-know-about-line-boring-machining/`) — fetched successfully, this is the strongest hit. States line boring exists specifically because "ensuring multiple bearing pockets share a common centerline... standard machining cannot guarantee this coaxiality"; typical achieved tolerance ~0.002 in across bores; explicitly ties bore misalignment to bearing seizure and unplanned downtime ("a single worn bore in a gearbox housing can knock a conveyor line offline for days").
- **swbplus.com.au** and **ssmiratechsystem.com** (split-case pump boring machines) — snippets confirm the same technique ("maintains concentricity across casing halves using datum and dowel references") applied to split pump housings — i.e., the identical problem recurs outside gearboxes.
- **SKF — "Tolerances and Resultant Fits"** page (`www.skf.com/group/products/rolling-bearings/...`) — confirmed to exist via search result, but fetch returned no usable body text (page likely JS-rendered), so I could not extract its actual content this session.

**Verdict on this sub-topic:** solid, real, multiply-corroborated. This is a genuinely standardized design/manufacturing concern (ISO 286 + DIN 620 for fit, line boring as the manufacturing answer to cross-wall coaxiality).

---

## 2. Oil seal gland design

**Confirmed as a real, standardized feature** (this was one of the explicit things to confirm):

- **Wikipedia — "Radial shaft seal"** (`en.wikipedia.org/wiki/Radial_shaft_seal`) — fetched successfully. Confirms radial lip seals have standardized nominal dimensions/tolerances under **ISO 6194-1:1982** and **DIN 3760 / DIN 3761**. Describes the sealing-lip contact mechanics (line contact, asymmetric pressure distribution, elastomer durometer 70–85 Shore A).
- **Kalsi Engineering — "Seal gland guidelines & dimensions"** (`www.kalsi.com/handbook/D05_Kalsi_Seal_gland_guidelines.pdf`) — fetched; PDF body wasn't text-extractable, but the document's own title/subject metadata (retrieved directly, not guessed) confirms it is literally "Seal gland guidelines & dimensions" covering "dimensions and tolerances for... rotary shaft seals." This is a real, industry-standard reference document, and its existence + subject line was verified this session even though I couldn't read the body.
- **Parker Hannifin PTFE/Fluid Power Seal Design Guides** (catalogs EPS 5340, EPS 5370) and **Apple Rubber Products seal design guide** — all confirmed to exist via search snippets (mirrored on distributor sites `repurvis.com`, `mfcp.com`, `applerubber.com`); snippets confirm these are gland-calculation-table documents ("gland calculation tables for standard profiles... conform to conventional gland and cylinder designs").

**Verdict on this sub-topic:** confirmed real and standardized — the term "gland" is the correct industry term (housing groove/bore that locates and compresses the seal), governed by named ISO/DIN standards and multiple manufacturer design-guide PDFs.

---

## 3. Breather / vent design

- **CTI Symposium — "Why Venting is Needed to Protect Drivetrain Components"** (`cti-symposium.world/why-venting-is-needed-to-protect-drivetrain-components/`) — fetched successfully, good content. Explains the mechanism precisely: thermal cycling causes trapped air to expand/contract, and without venting this "can deform the housing and compromise seals, admit contaminants, or allow undesirable fluid leaks." Describes the dual requirement (equalize pressure, exclude water/dirt) and modern ePTFE membrane vents replacing long breather hoses.
- Lower-quality/vendor sources also found (Viox, Alibaba buying guides) — directionally consistent but not authoritative; noted only as corroboration, not leaned on.

**Verdict on this sub-topic:** the underlying physical need (sealed cavity + thermal cycling → must vent or risk seal/gasket failure and contamination ingress) is real and documented, though my best source is an industry-symposium marketing/technical article rather than a textbook.

---

## 4. Inspection / access cover design

**Weakest sub-topic in my results.** I found only generic component-catalog pages (CNFX "Inspection Cover" / "Access Cover" component descriptions, a Scribd student document "Design of Gear Box Cover", a GrabCAD model listing). None of these are authoritative engineering-design-rule sources — they confirm the *feature category exists and is named* ("inspection cover," "access cover" as a machinery component class) but I found **no design-rule reference** (sizing, gasket/bolt-pattern rules, placement relative to mesh) this session. I'm flagging this explicitly rather than padding it.

**Verdict on this sub-topic:** the feature is real and named, but I did not find solid prior-art design guidance for it this session — treat as **weak/unconfirmed** on the "how do you design one" question, though "does it exist as a recognized feature" is confirmed.

---

## 5. Rib placement around bearing bosses for stiffness

- **DAGA/DEGA acoustics conference papers** — two real academic papers confirmed via search snippet and directly fetched (as binary PDFs, not fully text-readable, but titles/existence confirmed via retrieval + search snippet):
  - "Effect of Lightweight Design on NVH Behaviour" (DAGA 2024, `pub.dega-akustik.de/DAGA_2024/files/upload/paper/362.pdf`) — snippet: "investigates how ribs on gearbox housing surfaces affect vibration and noise using vibro-acoustic simulation."
  - "Influence of Rib Dimensions on NVH Performance" (DAGA/DAS-DAGA 2025, `pub.dega-akustik.de/DAS-DAGA_2025/files/upload/paper/189.pdf`) — snippet: "Ribs enhance local stiffness and contribute to weight reduction, though their design and placement are critical for balancing rigidity with weight efficiency."
- **IRJET — "Design Analysis of Industrial Gear Box Casing"** (`www.irjet.net/archives/V3/i11/IRJET-V3I11263.pdf`) — real paper, confirmed via snippet ("The gearbox casing is an important transmission component whose strength must be carefully considered during design"); could not extract full text (binary PDF).
- **seawinindustrial.com — "Designing Ribs And Bosses For Structural Integrity"** — fetched successfully. This is an **injection-molded-plastic** DFM guide, not metal casting, but gives the general structural principle directly: "integrating gussets (rib-like supports) around the base of tall bosses to increase stiffness," outer boss wall ≈ 60% of nominal wall thickness. I'm flagging the domain mismatch (plastics DFM vs. cast/machined metal gearbox housing) explicitly — the *geometric principle* (gusset a boss into the surrounding wall so a concentrated load doesn't cantilever off a thin shell) transfers, but the specific numeric guidance (60% wall ratio, draft angles) is plastics-specific and should not be reused verbatim for a cast-iron/aluminum gearbox housing.

**Verdict on this sub-topic:** real and documented (two real academic conference papers specifically on gearbox-housing rib/stiffness/NVH design exist), but I only got snippet-level confirmation, not full extracted design rules, since the PDFs weren't text-extractable in this environment.

---

## 6. Split-line design (horizontal split vs vertical split)

**Confirmed as real terminology** — but my best direct evidence is from **compressor casings**, not gearboxes specifically, so I'm flagging that gap honestly:

- **ScienceDirect Topics — "Compressor Case"** (`www.sciencedirect.com/topics/engineering/compressor-case`) — confirmed via search snippet only (direct fetch 403'd): "Both the horizontally split and vertically split casing designs allow removal of bearings and shaft end seals for maintenance."
- **ThePipingTalk — "Types and Classification of Centrifugal Compressor"** (`thepipingtalk.com/types-and-classification-of-centrifugal-compressor/`) — snippet: vertically split casings are "formed by a cylinder closed by two end covers," advantage is pressure capability from one-piece construction.
- Gearbox-specific confirmation was weaker: a forum thread (ThumperTalk, motorcycle engine cases) uses "vertically split cases"/"horizontally split cases," which is adjacent (engine crankcase, not a reduction-gearbox housing) but the same design vocabulary.
- I explicitly tried and **failed** to get a strong industrial-gear-reducer-specific citation for this term this session (DuckDuckGo CAPTCHA-blocked that particular query). So: the terminology is confirmed real in rotating-machinery casings broadly (compressors, engine cases); its application specifically to industrial gearboxes is highly plausible and consistent with general mechanical-engineering knowledge, but I did **not** get a live citation nailing it to "gearbox" specifically — flagging this as **recalled/plausible, only adjacently verified this session**, not fully verified for the gearbox case.

---

## 7. Standards / textbook references

- **AGMA 6001-F19 — "Design and Selection of Components for Use in Enclosed Gear Drives"** — real standard, confirmed by directly fetching a preview PDF (`www.normsplash.com/Samples/AGMA/176718566/AGMA-6001-F19-en.pdf`), which showed genuine document structure (Foreword, Scope §1, Normative References §2, Terms and Definitions §3). I could not get past the front matter to confirm whether it has a dedicated housing/casing section, so I'm not claiming that detail.
- **AGMA 6013-A06 — "Standard for Industrial Enclosed Gear Drives"** — confirmed to exist via ANSI webstore preview URL and search snippet ("design, rating, lubrication, testing and selection information for enclosed gear drives, including foot mounted, shaft mounted, screw conveyor drives and gearmotors"); direct fetch of the preview PDF was blocked (403).
- **Shigley's Mechanical Engineering Design — housing design coverage:** I was **not able to verify this** — every DuckDuckGo query on this specific question either hit a CAPTCHA wall or returned irrelevant results (Windows support pages). I am **not** citing anything for Shigley's here. From general knowledge (not verified this session, flagging explicitly as recalled-not-verified): Shigley's is organized around individual machine elements (shafts, keys, fasteners, springs, gears, rolling bearings) and, to my recollection, does not have a dedicated "housing/casing design" chapter — housing-level design (ribbing, split lines, gland/breather details) is more the domain of manufacturer application guides and specialized casting/machine-design texts than of Shigley's. Treat this specific claim as unverified.

---

## Explicit generalization: gearbox-specific vs. general packaging pattern

| Gearbox practice | Generalizes to (general packaging pattern) | Judgment |
|---|---|---|
| **Bearing bore alignment / line boring across a housing split** | *Precision co-location of two features that support a shared moving/rotating axis, when those features are cast/machined on either side of a joint.* Any product where two supports must share a datum — e.g., two bearing pillow blocks on a frame, two pivot bores in a linkage housing, two bushings for a slide rail — has the identical problem and the identical fix (machine both features in one setup, or use dowels/jig-bore to a shared datum after assembly). | **Strongly generalizes.** This is really a statement about *precision inter-feature tolerancing across a rigid structure that carries a kinematic constraint*, not about gears at all. |
| **Oil seal gland (housing groove that locates + compresses a rotary lip seal)** | *Environmental/fluid sealing at any shaft or rod penetration through an enclosure wall* — hydraulic cylinder rod seals, pump shaft seals, robot-joint dust/oil seals, any enclosure with a rotating or reciprocating through-shaft. The "gland" concept (a controlled-geometry groove/bore sized to a named standard, sized off the shaft OD and seal cross-section) is completely general. | **Strongly generalizes**, and is itself already used generically outside gearboxes (Parker's guide is "fluid power," i.e., cylinders, not gearboxes; Kalsi's is for "mud motor"/rotary drilling seals). Gearbox oil seals are just one instance of a much older, broader "rotary/reciprocating shaft seal gland" pattern. |
| **Breather/vent** | *Pressure equalization + contamination exclusion for any sealed enclosure subject to thermal cycling* — electronics enclosures, battery boxes, axle housings, hydraulic reservoirs, even a sealed camera housing. The CTI Symposium source is explicitly about "drivetrain components" broadly, not gearboxes narrowly. | **Strongly generalizes.** The gearbox is almost an arbitrary example here — any sealed volume with internal heat generation and external environment exposure needs this. |
| **Inspection/access cover** | *A removable panel sized/placed to reach the parts that need periodic maintenance or verification without disassembling the whole enclosure* — same pattern as an electronics chassis access panel, an automotive timing-cover inspection plug, a piping cleanout. | **Generalizes conceptually**, but I have the weakest evidence for this one specifically (no design-rule source found, only "this feature category exists"). The generalization itself (place a removable feature over the parts most likely to need periodic eyes-on or hands-on access) is common sense / low-content — I'd treat it as real but not deeply "prior art"-backed from what I found. |
| **Rib placement around bearing bosses** | *Local stiffening of a thin shell wall at a concentrated load-introduction point* — this is a completely general structural/casting-design principle (also seen in plastics-DFM boss/gusset guidance, in cast pump volutes around bearing housings, in any sheet-metal or cast bracket that has to carry a load through a boss into a thin wall). | **Strongly generalizes** — arguably the *most* general of the six, since I found essentially the identical principle stated independently in an injection-molding DFM guide and in gearbox-NVH acoustics papers: don't let a load-bearing boss cantilever unsupported off a thin shell. |
| **Horizontal-split vs. vertical-split housing** | *Choice of parting-plane orientation relative to the shaft axis, trading off assembly/maintenance access (split parallel to shaft, "clamshell" access to internals) against pressure/structural continuity (split perpendicular to shaft, "one-piece bore" with end caps).* This exact tradeoff recurs in pumps, compressors, and turbines (my best-confirmed sources are actually compressor casings, not gearboxes). | **Generalizes**, and I'd go further: the fact that my strongest citation was for compressors rather than gearboxes is itself evidence this is *not* gearbox-specific — it's a general parting-plane-vs-shaft-axis decision for any rotating-machinery housing. |

---

## Bottom line / one-line verdict

**Solid prior art exists** for this sub-question — but unevenly across the six features. Bearing-bore-alignment/line-boring, oil-seal-gland design, and breather/vent design each have real, directly-retrieved, reasonably authoritative citations (a Wikipedia-confirmed ISO/DIN standard, a real manufacturer gland-design PDF, real machining-service technical articles, a real drivetrain-venting technical article). Rib-placement-for-stiffness and split-line terminology are confirmed real but with thinner/adjacent-domain sourcing (academic conference papers I could only get snippets of; compressor rather than gearbox split-line sources). Inspection/access-cover design is the one sub-topic where I found the feature confirmed to exist but no real design-rule source. And critically, **the generalization exercise itself came out clean**: every one of the six gearbox-specific practices maps onto a broader, independently-documented "packaging" pattern (precision datum-sharing across a joint, shaft-penetration sealing, sealed-enclosure venting, maintenance-access panels, load-boss stiffening, parting-plane-vs-axis tradeoffs) — none of them turned out to be genuinely gearbox-only once I looked for the general form.

---

