# Subsystem Proposals — curation-first list

**How to use this file**: skim the tables and **delete any row you don't want built**. What survives becomes the next expansion phase (probably split into 2–3 batches of ~30 each). Every row that survives will land as one self-contained file under `packages/subsystems/` — no central-file edits per part.

- **Type**: `Single` = one printed body. `Compound` = one design intent, ≥2 printed bodies (following the enclosure-with-lid principle: matched dims by construction).
- ✅ = already implemented in the current catalog (23 parts as of 2026-07-02). Kept for context; do not need to be listed again but shown so you can see gaps.
- 🔴 = deferred until the corresponding cut-list solver / physics is approved (from `DOMAIN_TAXONOMY.md`). Do not check these in without explicit go.

Wedge scope: functional printable/machinable parts, no aerospace/CFD/propulsion/kinematics. Thread geometry is not modeled (heat-set inserts, clearance holes, tapping pockets are enough).

---

## 1. Fasteners & receiving hardware

| Name | Description | Type | Notes |
|---|---|---|---|
| `hex_nut` ✅ | Regular hex prism with through-bore | Single | |
| `wing_nut` | Hex bore + two winged tabs for hand-tightening | Single | winged geometry |
| `cap_nut` (acorn) | Hex nut with a domed closed end | Single | hex + half-sphere |
| `T_nut` | Flanged nut for wood/T-slot channels | Single | flanged hex |
| `slot_nut` | Rectangular nut for T-slot extrusion | Single | e.g. 2020 T-slot |
| `knurled_nut` | Small cylindrical thumb nut with knurled OD | Single | approximated (no knurl grooves) |
| `dome_nut` | Sealing dome (blind acorn) | Single | |
| `hex_bolt_blank` | Hex-head bolt (unthreaded shaft) | Single | head + shank |
| `socket_cap_bolt_blank` | Cylindrical head with hex socket | Single | |
| `button_head_bolt_blank` | Dome head + shank | Single | |
| `flat_head_bolt_blank` | Countersunk head + shank | Single | 90° or 82° cs |
| `thumb_screw` | Knurled cylindrical head + shank | Single | |
| `set_screw_pocket` | A block with a threaded-boss pocket for a set screw at 90° | Single | worker piece |
| `heat_set_boss` = `threaded_boss` ✅ | Stepped-bore cylinder | Single | |
| `press_fit_boss` | Boss with a slightly-undersized pilot for a press-fit metal insert | Single | |
| `dowel_pin` ✅ | Solid cylindrical pin | Single | |
| `cotter_pin_slot` | A plate with a slot sized for a cotter pin | Single | |
| `flat_washer` = `washer` ✅ | Annular ring | Single | |
| `fender_washer` | Very wide flat washer (larger OD ratio) | Single | parametric ratio |
| `wave_washer` | Sine-wave-formed axial spring washer | Single | swept |
| `keyhole_slot_plate` | Plate with keyhole-shape hanging slots | Single | slot geom |
| `cable_tie_anchor` | Flat mount with a cable-tie pass-through slot | Single | |

## 2. Brackets & mounts

| Name | Description | Type | Notes |
|---|---|---|---|
| `bracket` ✅ | Flat plate + row of bolt holes | Single | |
| `lbracket` ✅ | Two-flange angle | Single | |
| `z_bracket` ✅ | Three-flange Z offset | Single | |
| `cbracket` | C-shape (two flanges + short web) | Single | |
| `u_mounting_bracket` | U-shape (two vertical walls, base) — like uchannel but short mounting-focused | Single | |
| `corner_bracket_gusseted` | L-bracket + triangular gusset for stiffness | Single | wedge geom |
| `gusset_plate` | Right-triangle plate (a corner brace) | Single | |
| `floor_flange` | Round disc + upright collar (e.g. rod-to-floor) | Single | disc + collar |
| `wall_mount_plate` | Plate with mounting slots + peg attachment point | Single | |
| `hook_bracket` | Small plate + upturned hook | Single | swept curve |
| `foot_mount` | Rubber-foot-style pad with a fastener boss | Single | |
| `cable_clip` | Semi-circular clip with mounting flange | Single | |
| `pipe_saddle` | Round trough with base + hole pattern (for clamping a tube) | Single | |
| `mic_clip` | Flexible-arm clip for a cylindrical body | Single | flexure-style |
| `camera_mount_plate` | Small plate with a 1/4"-20 clearance boss | Single | |
| `motor_mount` ✅ | Square plate + corner holes + center bore | Single | |
| `nema17_face_mount` | Motor mount with the NEMA17 hole pattern preset | Single | preset dims |
| `nema23_face_mount` | Same, NEMA23 | Single | |
| `servo_bracket` | Two-flange bracket with servo-body pocket + horn clearance | Single | pocket |
| `hinge` | Two mating leaves that pivot around a shared pin bore | Compound | 2 leaves + interlocking knuckles |
| `hinge_with_pin` | Hinge + a dowel pin sized to the knuckle bore | Compound | 3 bodies |
| `door_stop` | Wedge + fastener boss | Single | |

## 3. Enclosures & covers

| Name | Description | Type | Notes |
|---|---|---|---|
| `enclosure` ✅ | Box shell + matching lid (7 params) | Compound | box + lid |
| `hinged_box` | Box + lid + integrated hinge knuckles | Compound | ~3 bodies |
| `sliding_lid_box` | Box + rail-and-slot sliding lid | Compound | 2 bodies |
| `split_shell_case` | Two mirror halves that clamshell together | Compound | 2 mirror halves |
| `snap_fit_box` | Box + lid with snap-fit tabs | Compound | 2 bodies |
| `stackable_bin` | Base + tapered walls sized so bins nest and stack | Single | |
| `junction_box` | Enclosure + cable-gland pass-through bosses + mounting flanges | Compound | box + lid + bosses |
| `endcap_round` | Cap that fits over a round tube OD | Single | |
| `endcap_square` | Cap for a square tube OD | Single | |
| `threaded_endcap_blank` | Endcap with a threaded-insert receiver in the center | Single | |
| `cable_gland_boss` | Standalone gland-mounting boss (splices into an enclosure wall) | Single | |
| `bezel_display` | Rectangular frame for a display window | Single | |
| `LCD_16x2_bezel` | Bezel preset for a 16×2 LCD module | Single | preset |

## 4. Panels & plates

| Name | Description | Type | Notes |
|---|---|---|---|
| `panel` ✅ | Plate + window + 4 corner holes | Single | |
| `cover_plate` ✅ | Plate + one central bore | Single | |
| `mounting_plate_grid` ✅ | Plate + N×M hole grid | Single | |
| `blank_plate` | Featureless rectangular plate | Single | | 
| `perforated_plate` | Plate with a dense hole pattern for airflow / grille | Single | |
| `breakout_plate` | Plate with a labelled hole cluster for connectors (USB, Ethernet…) | Single | 3–4 keyed cut-outs |
| `keystone_plate` | Plate with the keystone-jack rectangular cut-outs | Single | |
| `terminal_strip_plate` | Plate + strip of pass-through holes | Single | |
| `handle_plate` | Plate + integrated pull handle | Single | |
| `label_plate` | Plate with recessed label pocket | Single | |
| `pcb_carrier` | Plate with 4 boss standoffs sized to a PCB hole pattern | Compound | plate + 4 bosses (one body) |

## 5. Structural sections

| Name | Description | Type | Notes |
|---|---|---|---|
| `flat_bar` ✅ | Solid rectangular bar | Single | |
| `square_tube` ✅ | Hollow square section | Single | |
| `round_tube` | Hollow round section | Single | |
| `rectangular_tube` | Hollow rectangular section (non-square) | Single | |
| `hex_bar` ✅ | Solid hex prism | Single | |
| `round_bar` | Solid round bar (long dowel; distinct from `dowel_pin` by intent) | Single | |
| `t_bar` ✅ | T cross-section | Single | |
| `i_beam` | I / H cross-section | Single | |
| `angle_iron` | Extruded L cross-section (structural stock length) | Single | |
| `c_channel` | Extruded C cross-section (open one side) | Single | |
| `uchannel` ✅ | Extruded U cross-section | Single | |
| `2020_extrusion_blank` | 20mm × 20mm T-slot extrusion (slot geometry, not fully accurate) | Single | |
| `2040_extrusion_blank` | 20mm × 40mm T-slot extrusion | Single | |
| `frame_corner_bracket` | 3-axis corner bracket for T-slot framing | Single | |

## 6. Spacers & standoffs

| Name | Description | Type | Notes |
|---|---|---|---|
| `standoff` ✅ | Round through-bore cylinder | Single | |
| `hex_standoff` ✅ | Hex profile through-bore | Single | |
| `washer` ✅ (flat) | Annular ring | Single | |
| `stepped_spacer` | Two-diameter cylindrical spacer | Single | shoulder |
| `tapered_shim` | Wedge-shaped shim (variable thickness) | Single | |
| `flat_shim` | Very thin flat plate | Single | |
| `snap_ring_shim` | Split-ring shim | Single | thin split gap |

## 7. Rotational & transmission

| Name | Description | Type | Notes |
|---|---|---|---|
| `shaft_collar` ✅ | Cylinder + bore + set-screw hole | Single | |
| `hub` ✅ | Stepped cylinder + through-bore | Single | |
| `flange_collar` | Collar with an outboard mounting flange | Single | |
| `pulley_blank_v` | V-groove pulley (no teeth) | Single | |
| `pulley_blank_flat` | Flat-face pulley | Single | |
| `pulley_blank_timing` | Timing-pulley profile without teeth (smooth OD) | Single | |
| `sprocket_blank` | Sprocket disc with hub, no teeth | Single | |
| `gear_blank` | Gear disc with hub, no teeth (spec: dp, N) | Single | |
| `pinion_blank` | Small gear blank (short axial length, hub optional) | Single | |
| `wheel_blank` | Disc + hub, wide radial rim | Single | |
| `castor_blank` | Wheel + fork mount + swivel post | Compound | 2 bodies |
| `rigid_coupling` | Two-half tubular coupling with set-screw holes | Compound | 2 halves |
| `jaw_coupling` | Two hubs with mating jaws (elastomer spider excluded) | Compound | 2 hubs |
| `flex_coupling_blank` | Solid cylindrical coupling with slit relief | Single | |
| `worm_blank` | Long helical/screw blank (worm-drive input) | Single | approximated helix |

## 8. Bearings / bushings / linear (housings only, no rolling elements)

| Name | Description | Type | Notes |
|---|---|---|---|
| `sleeve_bushing` | Simple cylindrical bushing (OD/ID/length) | Single | |
| `flanged_bushing` | Bushing with an outboard flange | Single | |
| `thrust_washer` | Annular thrust bearing washer | Single | (topologically = washer) |
| `pillow_block_housing` | Pillow-block bearing shell (bearing not modelled) | Single | |
| `flange_bearing_housing` | 4-bolt flange bearing shell | Single | |
| `linear_bearing_block` | Rectangular slider block with a bore | Single | |
| `lm_rail_end_cap` | End cap for a linear rail | Single | |

## 9. Alignment, locating, jigs

| Name | Description | Type | Notes |
|---|---|---|---|
| `dowel_pin` ✅ | | Single | |
| `locating_pin` | Stepped-diameter locating pin (bullet nose) | Single | |
| `taper_pin` | Tapered alignment pin | Single | |
| `keyway_shaft` | Round shaft with a keyway slot | Single | |
| `v_block` | Rectangular block with a V-groove | Single | |
| `parallel_block_pair` | Precision parallel blocks (matched pair) | Compound | 2 bodies |
| `jig_plate` | Plate with a grid of dowel-pin bores and mounting slots | Single | |
| `drill_jig` | Plate + drill-bushing bores | Single | |
| `alignment_fork` | Two-prong locator | Single | |

## 10. Sealing

| Name | Description | Type | Notes |
|---|---|---|---|
| `flat_gasket` | Rectangular gasket blank with bolt holes | Single | |
| `oring_boss` | Cylindrical boss with an O-ring groove | Single | |
| `oring_groove_plate` | Plate with a rectangular O-ring groove and bolt holes | Single | |
| `grommet_blank` | Grommet profile (flexible material) | Single | |
| `cable_gland_body` | Cylindrical gland with strain relief | Single | |

## 11. Handles, knobs, ergonomic

| Name | Description | Type | Notes |
|---|---|---|---|
| `round_knob` | Cylindrical knob with a central boss | Single | |
| `star_knob` | Star-shape (n lobes) hand knob | Single | polygon |
| `hex_knob` | Hex-outer hand knob | Single | |
| `T_handle` | T-shape handle grip | Single | |
| `cabinet_pull` | Cabinet-drawer pull (two mounting posts + span) | Single | |
| `bar_pull` | Straight-bar drawer pull | Single | |
| `cylindrical_grip` | Longitudinal cylindrical grip with texture ribs | Single | |
| `tapered_grip` | Ergonomic tapered grip | Single | |

## 12. Cable, wire, plumbing

| Name | Description | Type | Notes |
|---|---|---|---|
| `wire_clip` | Small clip that holds one or two round conductors | Single | |
| `zip_tie_saddle` | Small mount with a zip-tie pass-through | Single | |
| `cable_gland_flange` | Flanged gland (compound with retainer nut) | Compound | 2 bodies |
| `strain_relief` | Two-jaw strain-relief clamp | Compound | 2 halves |
| `wire_labeler` | Cylindrical/rectangular label sleeve | Single | |
| `hose_barb` | Hose-barb fitting (ridged cylinder + optional flange) | Single | |

## 13. Assemblies / composites (multi-body)

| Name | Description | Type | Notes |
|---|---|---|---|
| `table` ✅ | Tabletop + 4 legs | Compound | already merged |
| `tri_stand` | Tripod: top plate + 3 legs | Compound | |
| `four_leg_stand` | Rectangular table with adjustable leg heights | Compound | |
| `motor_bracket_stack` | Motor mount + backing bracket | Compound | 2 bodies |
| `pillow_block_pair_on_rail` | Two pillow blocks on a rectangular rail | Compound | 3 bodies |
| `hinged_box_with_stop` | Hinged box + integral doorstop for the lid | Compound | 2 bodies |
| `sensor_mount_pair` | Two matched sensor mounts (e.g. IR emitter/receiver) | Compound | 2 bodies |
| `clamp_two_halves` | Generic bolted clamp: matching top + bottom half | Compound | 2 halves |
| `flanged_socket_and_peg` | Mating socket + peg for a snap connection | Compound | 2 bodies |
| `bearing_block_and_cap` | Bearing housing + a bolted cap | Compound | 2 bodies |

---

## Not-yet-worth-modelling (parked)

Kept off the list until there's a use-case that demands them (all needs specialty geometry or physics we can't ground):

- Helical retaining ring, garter spring, wave spring stack, coil spring geometry, thread modelling (any), gear tooth generation, spiral bevel geometry, chain link, elastomer spider (jaw coupling), o-ring elastomer material, actual bearing rolling elements, compliant flexures with buckling behaviour, chain conveyor slats.
- Any part that requires FEA-grounded surface loft (winglets, airfoils, blades, propellers) — 🔴 cut-list until the aero solver goes.
