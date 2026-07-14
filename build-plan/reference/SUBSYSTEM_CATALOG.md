# Subsystem Catalog — vision + phase plan

Inspiration: general mechanical-parts catalog depth (fasteners, brackets, enclosures, sections,
transmission, spacing, mounting hardware). This is the wedge-legal breadth — every entry is a
parametric printable/machinable functional part. No aerospace parts (still cut-list until per-piece
sign-off).

## The full-catalog vision (~80–120 subsystems)

Grouped by category. Each item is ONE file (~30–50 lines) in `packages/subsystems/<name>.py`
declaring a `Subsystem(name, description, fragment, disciplines, params, build, volume, invariants)`.
Zero central edits per addition. Coverage plan:

| Category | Example parts (breadth, not final list) |
|---|---|
| **Fasteners / hardware** | hex_nut, wing_nut, dowel_pin, threaded_boss, heat_set_receiver, snap_peg, cable_tie_anchor, keyhole_slot_plate |
| **Brackets / mounts** | bracket (have), lbracket (have), z_bracket, corner_bracket, gusset_plate, prong_bracket, wall_mount, foot_mount, floor_flange |
| **Enclosures / covers** | enclosure (have), box_lid, cover_plate, endcap, bezel, junction_box, cable_gland_boss |
| **Panels / faceplates** | panel (have), motor_mount, mounting_plate_grid, LCD_bezel, terminal_strip_plate |
| **Structural sections** | flat_bar, square_tube, round_tube, hex_bar, t_bar, i_beam, uchannel (have) |
| **Spacers / standoffs** | standoff (have), hex_standoff, washer (have), fender_washer, split_ring_shim |
| **Rotational / transmission** | shaft_collar, hub, pulley_blank, sprocket_blank, coupling_blank |
| **Bushings / bearings** | flanged_bushing, sleeve_bushing, thrust_washer, pillow_block_shell (housing only) |
| **Alignment / locating** | dowel_pin, locating_pin, keyway_shaft, v_block, jig_riser |
| **Sealing** | gasket, oring_boss, oring_groove_plate |
| **Assemblies (composites)** | table (have), tri_stand, box_with_lid (enclosure+lid), motor_bracket_stack |

**How far to go**: this is the wedge — hundreds of these exist in real catalogs. The scalable
architecture makes each one cheap (one file, no central edits), so growth is a matter of *demand*,
not *architectural cost*. Cap the catalog at what the copilot needs to answer typical requests
("make me a bracket", "make me a motor mount", "make me a shaft collar"). Growth cadence: pick
whatever the last chat surfaced as missing.

## Phase 1 — the first 15

Breadth (categories) over depth (variants within a category). Each is a distinct geometry using
build123d primitives (Box, Cylinder, Pos, RegularPolygon extrude, minor booleans).

| # | Part | Category | Distinct primitive move |
|---|---|---|---|
| 1 | `flat_bar` | Section | solid rectangular bar |
| 2 | `square_tube` | Section | outer Box − inner Box (hollow square) |
| 3 | `dowel_pin` | Alignment | solid cylinder |
| 4 | `cover_plate` | Enclosure | plate − center bore |
| 5 | `t_bar` | Section | T cross-section extruded |
| 6 | `z_bracket` | Bracket | three-leg Z shape |
| 7 | `mounting_plate_grid` | Panel | plate with N×M hole grid |
| 8 | `shaft_collar` | Rotational | cylinder − bore − radial set-screw hole |
| 9 | `hub` | Rotational | stepped-diameter cylinder + through-bore |
| 10 | ~~`box_lid`~~ (merged into `enclosure`) | Enclosure | ~~plate + downward lip (mates to enclosure)~~ — see revision below |
| 11 | `threaded_boss` | Fastener | cylinder + stepped bore (heat-set-insert receiver) |
| 12 | `motor_mount` | Panel | plate + 4 corner holes + center shaft clearance |
| 13 | `hex_nut` | Fastener | hex prism − through-bore |
| 14 | `hex_bar` | Section | hex prism (long) |
| 15 | `hex_standoff` | Spacer | hex prism − through-bore (long) |

**Not-in-Phase-1** (deliberate deferrals): thread modeling (heat-set inserts and clearance holes are
enough for FDM); rolling elements in bearings (housings only); complex sweeps (springs, helical
retaining rings, coil geometry).

## Revision (2026-07-02) — box_lid merged into enclosure

`box_lid` was originally added as its own subsystem, but that split forces the user to keep the
lid's outer dims in sync with the box manually — the exact coupling this axis is meant to eliminate.
Corrected: **`enclosure` now produces BOTH the box shell AND a matching lid as one compound**
(two printed parts from one design intent). Params: box W/D/H, wall_thickness, lid_thickness,
lid_lip_height, lid_clearance — the lid is derived from the box by construction (same outer
footprint; lip fits the interior minus clearance). `box_lid` deleted.

**Principle**: **one design intent → one subsystem, regardless of how many physical parts print.**
Multi-part designs (nut+bolt, box+lid, motor+mount, table+legs) belong in a single subsystem whose
`build` returns a compound of positioned bodies. This is the "sum of parts" pattern from `table.py`
generalized.

## Verification

- Every new subsystem auto-appears in `GET /subsystems`, the dropdown, `/params`, `/mesh`, `/export/step`.
- Parametrized test asserts each: registered, positive volume at defaults, build123d geometry
  produces a solid with expected root tag.
- No central-file edits (schema.py, nodes.py, templated.py, __init__.py's registrar list are
  untouched except the 15 bottom `import` lines).
