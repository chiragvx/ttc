# UAV Subsystem Proposals — curation-first list

**How to use this file**: skim the tables and **delete any row you don't want built** (same workflow
as `SUBSYSTEM_PROPOSALS.md`). What survives becomes the next expansion phase. Every row that
survives lands as one self-contained file under `packages/subsystems/` — no central-file edits per
part, per the existing scalable-subsystem pattern (see `[[domain-registry-pattern]]`).

**Scope, same guardrail as always**: every item here is **structural/mounting geometry only** —
boxes, cylinders, extrusions, hole patterns, ring/frame shapes. Nothing here needs an aero solver,
propulsion model, or flutter analysis to *build*; whether a design built from these parts actually
*flies* is a separate, cut-list question this catalog does not answer (see
`[[aerospace-uav-direction]]` — disciplines are a distinct axis from subsystems, and every cut-list
discipline still needs its own explicit go before any code lands).

- ⚠ = borderline naming — real aircraft use a shaped (often airfoil-derived) planform for this part.
  Kept structural-only by definition (a lightened flat plate / simple curve, not a true airfoil
  loft), but flagging so it gets a deliberate yes, not a rubber-stamp.
- 🔴 = genuinely out of scope until the corresponding solver is approved — listed in the parked
  section at the bottom, not in the main tables.

---

## 1. Fuselage / airframe structure

| Name | Description | Type | Notes |
|---|---|---|---|
| `bulkhead_frame` | Flat frame perpendicular to the fuselage axis, with a cutout + lightening holes | Single | |
| `fuselage_ring_frame` | Full ring frame (annulus) with mounting flange | Single | |
| `longeron` | Long straight structural rail (fore-aft member) | Single | dimensioned bar |
| `stringer` | Thin structural rail, lighter than a longeron, many per frame | Single | |
| `keel_beam` | Central spine beam running the fuselage length | Single | |
| `nose_ring` | Forward-most bulkhead ring — mount point for nose cone/payload | Single | |
| `tail_cone_ring` | Aft-most ring frame | Single | |
| `skin_attach_frame` | Frame with a flange a skin panel bolts/bonds to | Single | |
| `doubler_plate` | Local reinforcement plate over a stressed area | Single | |
| `access_hatch_frame` | Frame around a fuselage cutout for a hatch | Single | |
| `canopy_frame` | Frame for a canopy/window hatch | Single | |
| `tail_boom` | Boom connecting fuselage to tail | Single | tube or truss stock |
| `tail_boom_clamp` | Clamp that grips the boom and bolts to the fuselage | Compound | 2 halves |

## 2. Wing structure (structural members, not the aero surface)

| Name | Description | Type | Notes |
|---|---|---|---|
| `wing_spar` | Straight structural beam (I or box section) | Single | not airfoil-shaped |
| `wing_rib_blank` ⚠ | Lightened flat plate on a simple (non-airfoil) planform | Single | rib-like, not a loft |
| `wing_root_fitting` | Attachment fitting where the wing meets the fuselage | Single | |
| `wing_tip_fitting` | Structural closure/end cap at the wingtip | Single | |
| `wing_fold_hinge` | Static hinge for ground-transport wing folding | Compound | 2 leaves |
| `wing_strut` | External brace strut (strut-braced wing) | Single | |
| `dihedral_brace` | Fitting that sets/locks the dihedral angle at the root | Single | |
| `spar_joiner_sleeve` | Sleeve that joins two spar sections (multi-piece wings) | Single | |
| `wing_bolt_pair` | Matched bolt + reinforced bore pair for a bolt-on wing | Compound | 2 bodies |
| `wing_tube_joiner` | Tube-and-sleeve wing joiner (common in foam-board builds) | Compound | 2 bodies |

## 3. Tail structure

| Name | Description | Type | Notes |
|---|---|---|---|
| `stabilizer_spar` | Structural beam for horizontal/vertical stabilizer | Single | |
| `stabilizer_rib_blank` ⚠ | Lightened flat plate, simple planform | Single | |
| `elevator_hinge_bracket` | Structural hinge-line bracket (not the control surface itself) | Single | |
| `rudder_hinge_bracket` | Same, for the rudder hinge line | Single | |
| `tail_skid` | Ground-contact skid at the tail | Single | |
| `fin_root_fitting` | Attachment fitting where the vertical fin meets the boom/fuselage | Single | |

## 4. Landing gear

| Name | Description | Type | Notes |
|---|---|---|---|
| `main_gear_leg` | Main landing-gear leg (straight or bowed strut) | Single | |
| `nose_gear_leg` | Nose gear leg | Single | |
| `gear_mount_plate` | Plate the gear leg bolts to on the airframe | Single | |
| `wheel_hub` | Wheel hub with axle bore | Single | |
| `wheel_axle` | Axle pin | Single | |
| `skid_pad` | Flat skid (skid-gear aircraft, no wheels) | Single | |
| `tailwheel_bracket` | Bracket mounting a small steerable tailwheel | Single | |
| `shock_strut_housing` | Housing for a shock strut (spring/damper not modelled) | Single | housing only |
| `gear_door_hinge` | Hinge for a retractable-gear bay door | Compound | 2 leaves |
| `jack_point` | Reinforced point for a ground jack | Single | |
| `tie_down_ring` | Ground tie-down ring/eyelet mount | Single | |

## 5. Propulsion mounting hardware (mounts only — not propulsion itself)

| Name | Description | Type | Notes |
|---|---|---|---|
| `motor_mount_firewall` | Bulkhead plate + bolt-circle for a motor, beefier than `motor_mount` | Single | |
| `engine_bed_rail` | Twin-rail engine bed (glow/gas engines) | Compound | 2 rails |
| `nacelle_ring` | Ring frame forming a nacelle's structural core | Single | |
| `cowl_mount_bracket` | Bracket securing a cowl to the firewall | Single | |
| `prop_hub_blank` | Prop hub spacer/blank (no blade geometry) | Single | |
| `prop_spacer` | Simple spacer disc behind a prop | Single | |
| `spinner_backplate` | Backplate a spinner cone bolts to | Single | |
| `fuel_tank_tray` | Tray/cradle holding a fuel tank or battery pack | Single | |
| `fuel_tank_strap_mount` | Strap anchor points either side of a tank bay | Single | |
| `exhaust_mount_bracket` | Bracket standing off an exhaust/muffler | Single | |

## 6. Payload / avionics bay

| Name | Description | Type | Notes |
|---|---|---|---|
| `avionics_tray` | Plate + standoff bosses sized to a PCB hole pattern | Compound | plate + bosses |
| `equipment_rack_rail` | Rail with a regular hole/slot pitch for stacking equipment | Single | |
| `camera_mount_static` | Fixed (non-gimbaled) camera mount plate + bracket | Single | |
| `sensor_pod_shell` | Shell housing for an external sensor pod | Single | |
| `payload_bay_door` | Hinged or removable door over a payload bay | Compound | door + hinge |
| `payload_bay_ring` | Ring/frame mounting a cylindrical payload inside the bus | Single | |
| `pcb_stack_rail` | Rail supporting a vertical stack of PCBs | Single | |
| `wiring_channel` | Channel/raceway that routes a wiring bundle | Single | |
| `cable_passthrough_boss` | Boss with a grommet bore for a bulkhead cable pass-through | Single | |
| `component_shelf_bracket` | Small shelf bracket for a boxed component | Single | |

## 7. Power / battery

| Name | Description | Type | Notes |
|---|---|---|---|
| `battery_tray` | Tray/cradle sized to a battery pack | Single | |
| `battery_strap_mount` | Strap anchor points on either side of the battery bay | Single | |
| `battery_hatch` | Removable hatch over the battery bay | Single | |
| `power_distribution_mount_plate` | Plate mounting a PDB | Single | |
| `fuse_holder_bracket` | Bracket holding an inline fuse holder | Single | |
| `battery_bay_divider` | Divider wall between two battery bays | Single | |
| `esc_mount_plate` | Plate/standoffs for an ESC with airflow clearance | Single | |
| `charge_port_bezel` | Bezel around an external charge-port cutout | Single | |

## 8. Control-surface linkage hardware (structural, not the aero surface)

| Name | Description | Type | Notes |
|---|---|---|---|
| `control_horn` | Horn arm a pushrod attaches to on a control surface | Single | |
| `pushrod_guide` | Tube/guide keeping a pushrod straight over a span | Single | |
| `servo_mount_tray` | Tray + screw pattern for a standard servo size | Single | |
| `hinge_line_bracket` | Bracket establishing a control-surface hinge line | Single | |
| `bellcrank_mount_plate` | Plate mounting a bellcrank pivot | Single | |
| `servo_arm_blank` | Servo output arm blank | Single | |
| `linkage_clevis` | Clevis end-fitting for a pushrod | Single | |
| `control_rod_coupler` | Coupler joining two control-rod sections | Single | |

## 9. Antenna / comms / GPS

| Name | Description | Type | Notes |
|---|---|---|---|
| `antenna_mount_plate` | Plate + boss for a patch or whip antenna base | Single | |
| `patch_antenna_mount` | Mount sized for a patch-antenna PCB | Single | |
| `whip_antenna_base` | Base fitting for a whip/rod antenna | Single | |
| `gps_mast` | Small mast standing the GPS module off the airframe/ground plane | Single | |
| `comms_bay_bracket` | Bracket mounting a comms/radio module | Single | |
| `telemetry_module_tray` | Tray sized to a telemetry radio module | Single | |
| `rf_shield_mount` | Mount/clip for an RF shield can | Single | |
| `coax_clamp` | Small clamp securing a coax run at intervals | Single | |

## 10. Deployment / recovery

| Name | Description | Type | Notes |
|---|---|---|---|
| `deployment_hinge` | Static two-leaf hinge for solar panels/deployables | Compound | geometry only, no deployment dynamics |
| `parachute_bay_hatch` | Hatch covering a recovery-parachute bay | Single | |
| `tail_fold_joint` | Static fold joint for a folding tail (transport/storage) | Compound | 2 bodies |
| `breakaway_joint_plate` | Plate designed as a deliberate break point | Single | |
| `recovery_harness_anchor` | Anchor point for a recovery harness/parachute line | Single | |
| `deployment_bay_door` | Door over a general deployment bay | Compound | door + hinge |
| `separation_ring` | Ring for staged/droppable payload separation | Single | |

## 11. Ground handling / launch

| Name | Description | Type | Notes |
|---|---|---|---|
| `launch_rail_shoe` | Shoe that rides a launch rail | Single | |
| `catapult_hook` | Hook for a bungee/catapult launch | Single | |
| `ground_dolly_mount` | Mount point for a ground-handling dolly | Single | |
| `wingtip_stand` | Small stand supporting a wingtip on the ground | Single | |
| `handling_handle` | Fixed carry handle on the airframe | Single | |

## 12. CubeSat / small-sat specific

| Name | Description | Type | Notes |
|---|---|---|---|
| `cubesat_rail` | Corner rail: square section, rounded edges, mounting-hole pitch, weight-reduction pockets | Single | more accurate than reusing `square_tube` |
| `deck_plate` | Internal mounting-level plate, satellite-specific sizing presets | Single | overlaps `mounting_plate_grid`, kept as a named variant |
| `kill_switch_mount` | Mount for a remove-before-flight kill switch | Single | |
| `pcb_stack_standoff` | Standoff sized for a satellite PCB stack pitch | Single | |
| `solar_panel_backing_plate` | Backing plate a solar cell array mounts to | Single | |
| `rail_clip` | Clip securing wiring/harness to a cubesat rail | Single | |
| `corner_bumper` | Small compliant-shape bumper at a satellite corner | Single | |

## 13. Fasteners / joinery specific to airframes

| Name | Description | Type | Notes |
|---|---|---|---|
| `quick_release_pin` | Spring-loaded quick-release pin | Single | |
| `snap_pin` | Simple snap pin for a removable joint | Single | |
| `turnbuckle_blank` | Turnbuckle body blank (rigging tension) | Single | |
| `tensioner_bracket` | Bracket anchoring a tensioning cable/wire | Single | |
| `glue_tab` | Small flat tab sized for a bonded joint | Single | |
| `rivet_pattern_plate` | Plate pre-patterned with a rivet/fastener grid | Single | |

## 14. Misc / general airframe hardware

| Name | Description | Type | Notes |
|---|---|---|---|
| `inspection_cover` | Small removable cover over an inspection port | Single | |
| `ballast_tray` | Tray holding removable ballast weight | Single | |
| `cg_adjustment_rail` | Rail letting a component slide to trim CG | Single | |
| `fairing_ring` | Ring frame for a nose-cone/fairing base (the ring only, not the aero skin) | Single | |
| `bulkhead_ring` | Ring-shaped internal frame with lightening holes | Single | |
| `data_port_bezel` | Bezel around an external data-port cutout | Single | |

---

## Not-yet-worth-modelling (parked — needs explicit per-piece sign-off)

Same rule as `SUBSYSTEM_PROPOSALS.md`: kept off the list because it needs either specialty geometry
this catalog doesn't do, or an aero/propulsion solver that hasn't been approved yet
(`[[aerospace-uav-direction]]`):

- 🔴 Any true airfoil-lofted surface: wing skin, winglet, stabilizer skin, fairing outer skin — these
  need an aero-grounded surface, not a flat structural plate.
- 🔴 Propeller/rotor blades (twisted, cambered blade geometry) — needs a propulsion/aero model to
  ground, not just a shape.
- 🔴 Any part whose SIZING depends on an aero/propulsion/flutter number that doesn't exist yet (e.g.
  a spar sized "to the actual bending load" rather than a user-given dimension).
- Landing-gear shock absorber internals (actual spring/damper physics) — housing only is in-scope
  above; the mechanism itself is not.
- Flexible/compliant parts (fabric wing covering, elastomer engine mounts) — no material model for
  compliant behavior yet.
