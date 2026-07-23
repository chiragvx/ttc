"""Subsystem registry — the physical-assembly axis (bracket, enclosure, standoff, … → wing, fuselage).

Orthogonal to the discipline axis (packages/disciplines/): a subsystem is a *part/assembly* with a
geometry generator; multiple disciplines analyze it (the disciplines × subsystems matrix in
build-plan/reference/DOMAIN_TAXONOMY.md). Each subsystem self-describes: its LLM knowledge fragment,
which disciplines apply, which params drive its geometry, and a (lazy) geometry builder.

Adding a subsystem: create packages/subsystems/<name>.py, build a SubsystemContext, call register().
The prompt builder + geometry endpoints pull from here — no other file changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Optional

# NEW-STYLE (Phase A) — the scalable model. Existing subsystems keep using SubsystemContext below
# until they migrate. Both APIs coexist during the transition.
from packages.subsystems.base import (
    Frame,
    InterfaceSpec,
    Namespace,
    ParamSpec,
    Subsystem,
    bar_end_interfaces,
    box_face_interfaces,
    geometry_paths,
    lbracket_interfaces,
    plate_face_interfaces,
    resolve_namespace,
    seed_instance,
    seed_ledger_geometry,
)
# Phase F (2026-07-03) — composition helpers. A subsystem's `build` invokes another registered
# subsystem's `build` with overrides + positions the result. See packages/subsystems/compose.py.
# Re-exported from the package so a composite subsystem file just imports from `packages.subsystems`.

if TYPE_CHECKING:
    from packages.ledger.schema import MasterParametricLedger


def _no_invariants(ledger: "MasterParametricLedger") -> list[str]:
    return []


def _identity(ledger: "MasterParametricLedger") -> "MasterParametricLedger":
    return ledger


@dataclass(frozen=True)
class SubsystemContext:
    """Self-describing physical part/assembly: knowledge, applicable disciplines, geometry hooks."""

    name: str
    description: str
    prompt_fragment: str
    # which discipline lenses apply to this subsystem (keys into packages/disciplines)
    applicable_disciplines: tuple[str, ...] = ()
    # params (dotted ledger paths) that drive THIS subsystem's geometry AT THE ROOT INSTANCE. For an
    # arbitrary (possibly non-root) instance, use `packages.subsystems.base.geometry_paths(model, id)`.
    geometry_params: tuple[str, ...] = ()
    # subsystem-specific cross-field invariants (beyond the general ones in apply.py). Optional 2nd
    # arg `instance_id` (default None -> ledger.root_id) targets a non-root instance (Item 3 outliner).
    check_invariants: Callable[..., list[str]] = field(default=_no_invariants)
    # ledger [, instance_id] -> TaggedPart. Kept optional + resolved lazily so importing this package
    # never pulls in build123d/OCCT (the pure-python layers must not depend on the kernel).
    geometry_builder: Optional[Callable[..., object]] = None
    # ledger [, instance_id] -> printed-material volume in mm³ (drives mass/print-time telemetry).
    volume_mm3: Optional[Callable[..., float]] = None
    # populate this subsystem's optional geometry block with sensible defaults on a fresh project
    # (identity for subsystems that live entirely in the required core, e.g. bracket).
    seed_defaults: Callable[["MasterParametricLedger"], "MasterParametricLedger"] = field(default=_identity)
    # 2026-07-03 — see Subsystem.fea_eligible: True only for parts sharing the validated cantilever
    # FS methodology. False (default) -> factor_of_safety honestly stays "unknown" for this part type.
    fea_eligible: bool = False
    # 2026-07-03 — see Subsystem.cascades: an optional packages.ledger.apply.CascadeRule this part
    # declares (e.g. bracket's edge-distance rule cascades plate_depth_mm). None = no cascades.
    cascades: Optional[Callable[..., list]] = None
    # 2026-07-19 — see Subsystem.is_airframe_defining: True only for a wing/fuselage-class part that
    # sets the vehicle's own outer mold line. False (default) -> an ordinary systems/structural part.
    is_airframe_defining: bool = False


SUBSYSTEM_REGISTRY: dict[str, SubsystemContext] = {}
# Phase F: parallel model registry — keeps the `Subsystem` dataclass reachable by name so the
# `call(name, **overrides)` compose helper can materialise a child's ParamSpec defaults, apply
# overrides, and invoke the child's build. SubsystemContext (the ledger-facing adapter) doesn't
# carry `params`/`build` on the same shape, so we index the raw model alongside.
SUBSYSTEM_MODELS: dict[str, Subsystem] = {}


def register(ctx: SubsystemContext) -> SubsystemContext:
    SUBSYSTEM_REGISTRY[ctx.name] = ctx
    return ctx


def get_subsystem(name: str) -> SubsystemContext:
    if name not in SUBSYSTEM_REGISTRY:
        raise KeyError(f"Unknown subsystem {name!r}. Available: {sorted(SUBSYSTEM_REGISTRY)}")
    return SUBSYSTEM_REGISTRY[name]


def get_subsystem_model(name: str) -> Subsystem:
    """Fetch the raw `Subsystem` (params + build hooks) — used by the Phase F compose helpers to
    invoke a child subsystem's build with overrides. Prefer `get_subsystem()` when you need the
    ledger-facing SubsystemContext instead."""
    if name not in SUBSYSTEM_MODELS:
        raise KeyError(f"Unknown subsystem {name!r}. Available: {sorted(SUBSYSTEM_MODELS)}")
    return SUBSYSTEM_MODELS[name]


def register_subsystem(sub: Subsystem) -> Subsystem:
    """Register a new-style Subsystem. An adapter presents it as a SubsystemContext so the rest of the
    code (telemetry, prompt builder, /params, /mesh, /export/step) works UNCHANGED. Phase E removes the
    adapter and switches consumers to native Subsystem accessors.

    `_check`/`_build`/`_volume` all accept an optional trailing `instance_id` (default None ->
    `ledger.root_id`) so the SAME registered subsystem can be resolved against ANY instance in the
    tree — the foundation the Item 3 outliner (multiple independently-editable instances) builds on.
    Every pre-existing call site that passes just `ledger` is unaffected."""
    from packages.subsystems.base import geometry_paths as _geometry_paths
    from packages.subsystems.base import resolve_namespace, seed_ledger_geometry
    from packages.subsystems.cut_features import apply_cut_features, swept_volume_mm3

    root_geometry_paths = _geometry_paths(sub, "root")

    def _check(ledger, instance_id=None):
        return sub.invariants(resolve_namespace(sub, ledger, instance_id))

    def _build(ledger, instance_id=None):
        result = sub.build(resolve_namespace(sub, ledger, instance_id)) if sub.build else None
        if result is None:
            return None
        inst = ledger.instances.get(instance_id or ledger.root_id)
        if inst is not None and inst.cut_features:
            result = apply_cut_features(result, inst.cut_features)
        return result

    def _volume(ledger, instance_id=None):
        vol = sub.volume(resolve_namespace(sub, ledger, instance_id)) if sub.volume else 0.0
        inst = ledger.instances.get(instance_id or ledger.root_id)
        if inst is not None and inst.cut_features:
            vol = max(0.0, vol - sum(swept_volume_mm3(f) for f in inst.cut_features))
        return vol

    def _seed(ledger):
        return seed_ledger_geometry(sub, ledger)

    SUBSYSTEM_REGISTRY[sub.name] = SubsystemContext(
        name=sub.name,
        description=sub.description,
        prompt_fragment=sub.fragment,
        applicable_disciplines=sub.disciplines,
        geometry_params=root_geometry_paths,
        check_invariants=_check,
        geometry_builder=_build,
        volume_mm3=_volume,
        seed_defaults=_seed,
        fea_eligible=sub.fea_eligible,
        cascades=sub.cascades,
        is_airframe_defining=sub.is_airframe_defining,
    )
    SUBSYSTEM_MODELS[sub.name] = sub
    return sub


def add_instance(ledger: "MasterParametricLedger", subsystem_name: str, instance_id: str,
                 parent_id: Optional[str] = None) -> "MasterParametricLedger":
    """Add a NEW instance (of any registered subsystem type) to the ledger's instance tree, seeded
    with that subsystem's defaults. Parts are a FLAT set brought into a file (2026-07-04) — no
    root, no auto-parenting: `parent_id` omitted means top-level; an unknown `parent_id` silently
    falls back to top-level rather than rejecting the add (see
    `packages.ledger.apply.resolve_instance_parent`). Raises KeyError for an unknown subsystem
    name; raises ValueError if `instance_id` is already taken. Item 3 outliner CRUD builds on
    this."""
    from packages.ledger.apply import resolve_instance_parent
    if instance_id in ledger.instances:
        raise ValueError(f"instance id {instance_id!r} already exists")
    pid, _parent_note = resolve_instance_parent(ledger, parent_id)
    model = get_subsystem_model(subsystem_name)  # KeyError if unknown — validated before mutating
    inst = seed_instance(model, instance_id, parent_id=pid)
    new_instances = dict(ledger.instances)
    new_instances[instance_id] = inst
    new_ledger = ledger.model_copy(update={"instances": new_instances})
    # Assembly-template mechanism (2026-07-03): a safe no-op unless `subsystem_name` declares
    # `assembly_children` — in that case this materializes the new instance's own child instances too.
    from packages.subsystems.assembly_template import reconcile_children
    return reconcile_children(new_ledger, instance_id)


def remove_instance(ledger: "MasterParametricLedger", instance_id: str) -> "MasterParametricLedger":
    """Remove a childless instance — any part in the file is removable as long as nothing depends
    on it (2026-07-04: parts are a flat set, there's no root carve-out). Raises ValueError for an
    unknown id or an instance that still has children (delete children first — no silent cascade);
    that check alone already prevents orphaning a template's or explicitly-parented instance's
    dependents."""
    if instance_id not in ledger.instances:
        raise ValueError(f"instance id {instance_id!r} does not exist")
    children = [i for i, inst in ledger.instances.items() if inst.parent_id == instance_id]
    if children:
        raise ValueError(f"instance {instance_id!r} has children {children} — remove them first")
    new_instances = dict(ledger.instances)
    del new_instances[instance_id]
    return ledger.model_copy(update={"instances": new_instances})


# Phase F composition helpers — re-exported for composite subsystems' build functions.
from packages.subsystems.compose import call, compose, fuse, place, place_polar  # noqa: E402


# Side-effect imports: each module calls register() on load.
from packages.subsystems import bracket as _bracket  # noqa: E402, F401
from packages.subsystems import enclosure as _enclosure  # noqa: E402, F401
from packages.subsystems import standoff as _standoff  # noqa: E402, F401
from packages.subsystems import lbracket as _lbracket  # noqa: E402, F401
from packages.subsystems import uchannel as _uchannel  # noqa: E402, F401
from packages.subsystems import panel as _panel  # noqa: E402, F401
from packages.subsystems import washer as _washer  # noqa: E402, F401
from packages.subsystems import round_post as _round_post  # noqa: E402, F401 — solid cylinder primitive (used by table legs)
from packages.subsystems import table as _table  # noqa: E402, F401 — composite: flat_bar top + round_post legs
# Phase 1 catalog expansion (2026-07-02) — 15 new subsystems across categories
from packages.subsystems import flat_bar as _flat_bar  # noqa: E402, F401
from packages.subsystems import square_tube as _square_tube  # noqa: E402, F401
from packages.subsystems import dowel_pin as _dowel_pin  # noqa: E402, F401
from packages.subsystems import cover_plate as _cover_plate  # noqa: E402, F401
from packages.subsystems import t_bar as _t_bar  # noqa: E402, F401
from packages.subsystems import z_bracket as _z_bracket  # noqa: E402, F401
from packages.subsystems import mounting_plate_grid as _mounting_plate_grid  # noqa: E402, F401
from packages.subsystems import shaft_collar as _shaft_collar  # noqa: E402, F401
from packages.subsystems import hub as _hub  # noqa: E402, F401
from packages.subsystems import threaded_boss as _threaded_boss  # noqa: E402, F401
from packages.subsystems import motor_mount as _motor_mount  # noqa: E402, F401
from packages.subsystems import hex_nut as _hex_nut  # noqa: E402, F401
from packages.subsystems import hex_bar as _hex_bar  # noqa: E402, F401
from packages.subsystems import hex_standoff as _hex_standoff  # noqa: E402, F401
# Phase F composite — plate + N standoffs, first composite-of-registered-parts (2026-07-03)
from packages.subsystems import standoff_frame as _standoff_frame  # noqa: E402, F401
# Open semi-circular saddle/P-clamp — cradles a cylindrical item (fan housing, pipe, tube) (2026-07-03)
from packages.subsystems import saddle_clamp as _saddle_clamp  # noqa: E402, F401
# Aerospace airframe structural members (2026-07-05)
from packages.subsystems import bulkhead_frame as _bulkhead_frame  # noqa: E402, F401
from packages.subsystems import longeron as _longeron  # noqa: E402, F401
# General body-of-revolution primitive (loft + hollow shell) — not aerospace-specific (2026-07-05)
from packages.subsystems import lofted_spindle as _lofted_spindle  # noqa: E402, F401
# Asymmetric top/bottom hull + localized canopy bump — lofted_spindle's asymmetric sibling (2026-07-05)
from packages.subsystems import lofted_hull as _lofted_hull  # noqa: E402, F401
# Full-span lofted wing panel, real NACA 4-digit symmetric airfoil cross-section (2026-07-05)
from packages.subsystems import naca_wing as _naca_wing  # noqa: E402, F401
# Streamlined body-of-revolution for fuselages/nose cones/nacelles — power-law (ogive) nose/tail
# taper, lofted_spindle's aerospace-shaped sibling (2026-07-06)
from packages.subsystems import ogive_fuselage as _ogive_fuselage  # noqa: E402, F401
# Composite: ogive_fuselage body + naca_wing panel, boolean-fused into one printable body (2026-07-05)
from packages.subsystems import winged_fuselage as _winged_fuselage  # noqa: E402, F401

# UAV hardware catalog expansion (2026-07-16) -- build-plan/reference/UAV_SUBSYSTEM_PROPOSALS.md's
# curated, structural/mounting-only list, built out in full so a copilot querying for any of these
# part types finds a real, registered generator instead of having to invent geometry. Every one of
# these reuses an EXISTING shared archetype (render_bracket/render_panel/render_lbracket/
# render_standoff/render_uchannel/render_bulkhead_frame, or the plain-Box/hollow-tube/cradle inline
# patterns longeron.py/square_tube.py/saddle_clamp.py already established) under this catalog's own
# "one archetype, many named entries" convention (see washer.py reusing the standoff generator).
# Excludes the 2 already-built rows (bulkhead_frame, longeron, imported above) and the 2 (Wing rib
# blank / stabilizer rib blank) rows the proposals doc itself flags with the borderline-naming
# warning (needs its own deliberate yes, not bundled into this bulk pass).
from packages.subsystems import fuselage_ring_frame as _fuselage_ring_frame  # noqa: E402, F401
from packages.subsystems import stringer as _stringer  # noqa: E402, F401
from packages.subsystems import keel_beam as _keel_beam  # noqa: E402, F401
from packages.subsystems import nose_ring as _nose_ring  # noqa: E402, F401
from packages.subsystems import tail_cone_ring as _tail_cone_ring  # noqa: E402, F401
from packages.subsystems import skin_attach_frame as _skin_attach_frame  # noqa: E402, F401
from packages.subsystems import doubler_plate as _doubler_plate  # noqa: E402, F401
from packages.subsystems import access_hatch_frame as _access_hatch_frame  # noqa: E402, F401
from packages.subsystems import canopy_frame as _canopy_frame  # noqa: E402, F401
from packages.subsystems import tail_boom as _tail_boom  # noqa: E402, F401
from packages.subsystems import tail_boom_clamp as _tail_boom_clamp  # noqa: E402, F401
from packages.subsystems import wing_spar as _wing_spar  # noqa: E402, F401
from packages.subsystems import wing_root_fitting as _wing_root_fitting  # noqa: E402, F401
from packages.subsystems import wing_tip_fitting as _wing_tip_fitting  # noqa: E402, F401
from packages.subsystems import wing_fold_hinge as _wing_fold_hinge  # noqa: E402, F401
from packages.subsystems import wing_strut as _wing_strut  # noqa: E402, F401
from packages.subsystems import dihedral_brace as _dihedral_brace  # noqa: E402, F401
from packages.subsystems import spar_joiner_sleeve as _spar_joiner_sleeve  # noqa: E402, F401
from packages.subsystems import wing_bolt_pair as _wing_bolt_pair  # noqa: E402, F401
from packages.subsystems import wing_tube_joiner as _wing_tube_joiner  # noqa: E402, F401
from packages.subsystems import stabilizer_spar as _stabilizer_spar  # noqa: E402, F401
from packages.subsystems import elevator_hinge_bracket as _elevator_hinge_bracket  # noqa: E402, F401
from packages.subsystems import rudder_hinge_bracket as _rudder_hinge_bracket  # noqa: E402, F401
from packages.subsystems import tail_skid as _tail_skid  # noqa: E402, F401
from packages.subsystems import fin_root_fitting as _fin_root_fitting  # noqa: E402, F401
from packages.subsystems import main_gear_leg as _main_gear_leg  # noqa: E402, F401
from packages.subsystems import nose_gear_leg as _nose_gear_leg  # noqa: E402, F401
from packages.subsystems import gear_mount_plate as _gear_mount_plate  # noqa: E402, F401
from packages.subsystems import wheel_hub as _wheel_hub  # noqa: E402, F401
from packages.subsystems import wheel_axle as _wheel_axle  # noqa: E402, F401
from packages.subsystems import skid_pad as _skid_pad  # noqa: E402, F401
from packages.subsystems import tailwheel_bracket as _tailwheel_bracket  # noqa: E402, F401
from packages.subsystems import shock_strut_housing as _shock_strut_housing  # noqa: E402, F401
from packages.subsystems import gear_door_hinge as _gear_door_hinge  # noqa: E402, F401
from packages.subsystems import jack_point as _jack_point  # noqa: E402, F401
from packages.subsystems import tie_down_ring as _tie_down_ring  # noqa: E402, F401
from packages.subsystems import motor_mount_firewall as _motor_mount_firewall  # noqa: E402, F401
from packages.subsystems import engine_bed_rail as _engine_bed_rail  # noqa: E402, F401
from packages.subsystems import nacelle_ring as _nacelle_ring  # noqa: E402, F401
from packages.subsystems import cowl_mount_bracket as _cowl_mount_bracket  # noqa: E402, F401
from packages.subsystems import prop_hub_blank as _prop_hub_blank  # noqa: E402, F401
from packages.subsystems import prop_spacer as _prop_spacer  # noqa: E402, F401
from packages.subsystems import spinner_backplate as _spinner_backplate  # noqa: E402, F401
from packages.subsystems import fuel_tank_tray as _fuel_tank_tray  # noqa: E402, F401
from packages.subsystems import fuel_tank_strap_mount as _fuel_tank_strap_mount  # noqa: E402, F401
from packages.subsystems import exhaust_mount_bracket as _exhaust_mount_bracket  # noqa: E402, F401
from packages.subsystems import avionics_tray as _avionics_tray  # noqa: E402, F401
from packages.subsystems import equipment_rack_rail as _equipment_rack_rail  # noqa: E402, F401
from packages.subsystems import camera_mount_static as _camera_mount_static  # noqa: E402, F401
from packages.subsystems import sensor_pod_shell as _sensor_pod_shell  # noqa: E402, F401
from packages.subsystems import payload_bay_door as _payload_bay_door  # noqa: E402, F401
from packages.subsystems import payload_bay_ring as _payload_bay_ring  # noqa: E402, F401
from packages.subsystems import pcb_stack_rail as _pcb_stack_rail  # noqa: E402, F401
from packages.subsystems import wiring_channel as _wiring_channel  # noqa: E402, F401
from packages.subsystems import cable_passthrough_boss as _cable_passthrough_boss  # noqa: E402, F401
from packages.subsystems import component_shelf_bracket as _component_shelf_bracket  # noqa: E402, F401
from packages.subsystems import battery_tray as _battery_tray  # noqa: E402, F401
from packages.subsystems import battery_strap_mount as _battery_strap_mount  # noqa: E402, F401
from packages.subsystems import battery_hatch as _battery_hatch  # noqa: E402, F401
from packages.subsystems import power_distribution_mount_plate as _power_distribution_mount_plate  # noqa: E402, F401
from packages.subsystems import fuse_holder_bracket as _fuse_holder_bracket  # noqa: E402, F401
from packages.subsystems import battery_bay_divider as _battery_bay_divider  # noqa: E402, F401
from packages.subsystems import esc_mount_plate as _esc_mount_plate  # noqa: E402, F401
from packages.subsystems import charge_port_bezel as _charge_port_bezel  # noqa: E402, F401
from packages.subsystems import control_horn as _control_horn  # noqa: E402, F401
from packages.subsystems import pushrod_guide as _pushrod_guide  # noqa: E402, F401
from packages.subsystems import servo_mount_tray as _servo_mount_tray  # noqa: E402, F401
from packages.subsystems import hinge_line_bracket as _hinge_line_bracket  # noqa: E402, F401
from packages.subsystems import bellcrank_mount_plate as _bellcrank_mount_plate  # noqa: E402, F401
from packages.subsystems import servo_arm_blank as _servo_arm_blank  # noqa: E402, F401
from packages.subsystems import linkage_clevis as _linkage_clevis  # noqa: E402, F401
from packages.subsystems import control_rod_coupler as _control_rod_coupler  # noqa: E402, F401
from packages.subsystems import antenna_mount_plate as _antenna_mount_plate  # noqa: E402, F401
from packages.subsystems import patch_antenna_mount as _patch_antenna_mount  # noqa: E402, F401
from packages.subsystems import whip_antenna_base as _whip_antenna_base  # noqa: E402, F401
from packages.subsystems import gps_mast as _gps_mast  # noqa: E402, F401
from packages.subsystems import comms_bay_bracket as _comms_bay_bracket  # noqa: E402, F401
from packages.subsystems import telemetry_module_tray as _telemetry_module_tray  # noqa: E402, F401
from packages.subsystems import rf_shield_mount as _rf_shield_mount  # noqa: E402, F401
from packages.subsystems import coax_clamp as _coax_clamp  # noqa: E402, F401
from packages.subsystems import deployment_hinge as _deployment_hinge  # noqa: E402, F401
from packages.subsystems import parachute_bay_hatch as _parachute_bay_hatch  # noqa: E402, F401
from packages.subsystems import tail_fold_joint as _tail_fold_joint  # noqa: E402, F401
from packages.subsystems import breakaway_joint_plate as _breakaway_joint_plate  # noqa: E402, F401
from packages.subsystems import recovery_harness_anchor as _recovery_harness_anchor  # noqa: E402, F401
from packages.subsystems import deployment_bay_door as _deployment_bay_door  # noqa: E402, F401
from packages.subsystems import separation_ring as _separation_ring  # noqa: E402, F401
from packages.subsystems import launch_rail_shoe as _launch_rail_shoe  # noqa: E402, F401
from packages.subsystems import catapult_hook as _catapult_hook  # noqa: E402, F401
from packages.subsystems import ground_dolly_mount as _ground_dolly_mount  # noqa: E402, F401
from packages.subsystems import wingtip_stand as _wingtip_stand  # noqa: E402, F401
from packages.subsystems import handling_handle as _handling_handle  # noqa: E402, F401
from packages.subsystems import cubesat_rail as _cubesat_rail  # noqa: E402, F401
from packages.subsystems import deck_plate as _deck_plate  # noqa: E402, F401
from packages.subsystems import kill_switch_mount as _kill_switch_mount  # noqa: E402, F401
from packages.subsystems import pcb_stack_standoff as _pcb_stack_standoff  # noqa: E402, F401
from packages.subsystems import solar_panel_backing_plate as _solar_panel_backing_plate  # noqa: E402, F401
from packages.subsystems import rail_clip as _rail_clip  # noqa: E402, F401
from packages.subsystems import corner_bumper as _corner_bumper  # noqa: E402, F401
from packages.subsystems import quick_release_pin as _quick_release_pin  # noqa: E402, F401
from packages.subsystems import snap_pin as _snap_pin  # noqa: E402, F401
from packages.subsystems import turnbuckle_blank as _turnbuckle_blank  # noqa: E402, F401
from packages.subsystems import tensioner_bracket as _tensioner_bracket  # noqa: E402, F401
from packages.subsystems import glue_tab as _glue_tab  # noqa: E402, F401
from packages.subsystems import rivet_pattern_plate as _rivet_pattern_plate  # noqa: E402, F401
from packages.subsystems import inspection_cover as _inspection_cover  # noqa: E402, F401
from packages.subsystems import ballast_tray as _ballast_tray  # noqa: E402, F401
from packages.subsystems import cg_adjustment_rail as _cg_adjustment_rail  # noqa: E402, F401
from packages.subsystems import fairing_ring as _fairing_ring  # noqa: E402, F401
from packages.subsystems import bulkhead_ring as _bulkhead_ring  # noqa: E402, F401
from packages.subsystems import data_port_bezel as _data_port_bezel  # noqa: E402, F401

# General (non-aerospace) hardware catalog expansion (2026-07-17) --
# build-plan/reference/SUBSYSTEM_PROPOSALS.md's remaining curated list, built out in full (see the
# UAV expansion above for the same reasoning/pattern -- 4 new archetypes this time: puck/stepped/
# flanged/wedge/plate_bore, each prototyped against real build123d before being committed). Excludes
# the already-checkmarked 22 rows, and wave_washer/snap_ring_shim/worm_blank/grommet_blank
# (spring/thread/elastomer-adjacent -- the same "needs unsupported physics" boundary the doc's own
# parked section draws).
from packages.subsystems import wing_nut as _wing_nut  # noqa: E402, F401
from packages.subsystems import cap_nut as _cap_nut  # noqa: E402, F401
from packages.subsystems import T_nut as _T_nut  # noqa: E402, F401
from packages.subsystems import slot_nut as _slot_nut  # noqa: E402, F401
from packages.subsystems import knurled_nut as _knurled_nut  # noqa: E402, F401
from packages.subsystems import dome_nut as _dome_nut  # noqa: E402, F401
from packages.subsystems import hex_bolt_blank as _hex_bolt_blank  # noqa: E402, F401
from packages.subsystems import socket_cap_bolt_blank as _socket_cap_bolt_blank  # noqa: E402, F401
from packages.subsystems import button_head_bolt_blank as _button_head_bolt_blank  # noqa: E402, F401
from packages.subsystems import flat_head_bolt_blank as _flat_head_bolt_blank  # noqa: E402, F401
from packages.subsystems import thumb_screw as _thumb_screw  # noqa: E402, F401
from packages.subsystems import set_screw_pocket as _set_screw_pocket  # noqa: E402, F401
from packages.subsystems import press_fit_boss as _press_fit_boss  # noqa: E402, F401
from packages.subsystems import cotter_pin_slot as _cotter_pin_slot  # noqa: E402, F401
from packages.subsystems import fender_washer as _fender_washer  # noqa: E402, F401
from packages.subsystems import keyhole_slot_plate as _keyhole_slot_plate  # noqa: E402, F401
from packages.subsystems import cable_tie_anchor as _cable_tie_anchor  # noqa: E402, F401
from packages.subsystems import cbracket as _cbracket  # noqa: E402, F401
from packages.subsystems import u_mounting_bracket as _u_mounting_bracket  # noqa: E402, F401
from packages.subsystems import corner_bracket_gusseted as _corner_bracket_gusseted  # noqa: E402, F401
from packages.subsystems import gusset_plate as _gusset_plate  # noqa: E402, F401
from packages.subsystems import floor_flange as _floor_flange  # noqa: E402, F401
from packages.subsystems import wall_mount_plate as _wall_mount_plate  # noqa: E402, F401
from packages.subsystems import hook_bracket as _hook_bracket  # noqa: E402, F401
from packages.subsystems import foot_mount as _foot_mount  # noqa: E402, F401
from packages.subsystems import cable_clip as _cable_clip  # noqa: E402, F401
from packages.subsystems import pipe_saddle as _pipe_saddle  # noqa: E402, F401
from packages.subsystems import mic_clip as _mic_clip  # noqa: E402, F401
from packages.subsystems import camera_mount_plate as _camera_mount_plate  # noqa: E402, F401
from packages.subsystems import nema17_face_mount as _nema17_face_mount  # noqa: E402, F401
from packages.subsystems import nema23_face_mount as _nema23_face_mount  # noqa: E402, F401
from packages.subsystems import servo_bracket as _servo_bracket  # noqa: E402, F401
from packages.subsystems import hinge as _hinge  # noqa: E402, F401
from packages.subsystems import hinge_with_pin as _hinge_with_pin  # noqa: E402, F401
from packages.subsystems import door_stop as _door_stop  # noqa: E402, F401
from packages.subsystems import hinged_box as _hinged_box  # noqa: E402, F401
from packages.subsystems import sliding_lid_box as _sliding_lid_box  # noqa: E402, F401
from packages.subsystems import split_shell_case as _split_shell_case  # noqa: E402, F401
from packages.subsystems import snap_fit_box as _snap_fit_box  # noqa: E402, F401
from packages.subsystems import stackable_bin as _stackable_bin  # noqa: E402, F401
from packages.subsystems import junction_box as _junction_box  # noqa: E402, F401
from packages.subsystems import endcap_round as _endcap_round  # noqa: E402, F401
from packages.subsystems import endcap_square as _endcap_square  # noqa: E402, F401
from packages.subsystems import threaded_endcap_blank as _threaded_endcap_blank  # noqa: E402, F401
from packages.subsystems import cable_gland_boss as _cable_gland_boss  # noqa: E402, F401
from packages.subsystems import bezel_display as _bezel_display  # noqa: E402, F401
from packages.subsystems import LCD_16x2_bezel as _LCD_16x2_bezel  # noqa: E402, F401
from packages.subsystems import blank_plate as _blank_plate  # noqa: E402, F401
from packages.subsystems import perforated_plate as _perforated_plate  # noqa: E402, F401
from packages.subsystems import breakout_plate as _breakout_plate  # noqa: E402, F401
from packages.subsystems import keystone_plate as _keystone_plate  # noqa: E402, F401
from packages.subsystems import terminal_strip_plate as _terminal_strip_plate  # noqa: E402, F401
from packages.subsystems import handle_plate as _handle_plate  # noqa: E402, F401
from packages.subsystems import label_plate as _label_plate  # noqa: E402, F401
from packages.subsystems import pcb_carrier as _pcb_carrier  # noqa: E402, F401
from packages.subsystems import round_tube as _round_tube  # noqa: E402, F401
from packages.subsystems import rectangular_tube as _rectangular_tube  # noqa: E402, F401
from packages.subsystems import round_bar as _round_bar  # noqa: E402, F401
from packages.subsystems import i_beam as _i_beam  # noqa: E402, F401
from packages.subsystems import angle_iron as _angle_iron  # noqa: E402, F401
from packages.subsystems import c_channel as _c_channel  # noqa: E402, F401
from packages.subsystems import extrusion_2020_blank as _extrusion_2020_blank  # noqa: E402, F401
from packages.subsystems import extrusion_2040_blank as _extrusion_2040_blank  # noqa: E402, F401
from packages.subsystems import frame_corner_bracket as _frame_corner_bracket  # noqa: E402, F401
from packages.subsystems import stepped_spacer as _stepped_spacer  # noqa: E402, F401
from packages.subsystems import tapered_shim as _tapered_shim  # noqa: E402, F401
from packages.subsystems import flat_shim as _flat_shim  # noqa: E402, F401
from packages.subsystems import flange_collar as _flange_collar  # noqa: E402, F401
from packages.subsystems import pulley_blank_v as _pulley_blank_v  # noqa: E402, F401
from packages.subsystems import pulley_blank_flat as _pulley_blank_flat  # noqa: E402, F401
from packages.subsystems import pulley_blank_timing as _pulley_blank_timing  # noqa: E402, F401
from packages.subsystems import sprocket_blank as _sprocket_blank  # noqa: E402, F401
from packages.subsystems import gear_blank as _gear_blank  # noqa: E402, F401
from packages.subsystems import pinion_blank as _pinion_blank  # noqa: E402, F401
from packages.subsystems import wheel_blank as _wheel_blank  # noqa: E402, F401
from packages.subsystems import castor_blank as _castor_blank  # noqa: E402, F401
from packages.subsystems import rigid_coupling as _rigid_coupling  # noqa: E402, F401
from packages.subsystems import jaw_coupling as _jaw_coupling  # noqa: E402, F401
from packages.subsystems import flex_coupling_blank as _flex_coupling_blank  # noqa: E402, F401
from packages.subsystems import sleeve_bushing as _sleeve_bushing  # noqa: E402, F401
from packages.subsystems import flanged_bushing as _flanged_bushing  # noqa: E402, F401
from packages.subsystems import thrust_washer as _thrust_washer  # noqa: E402, F401
from packages.subsystems import pillow_block_housing as _pillow_block_housing  # noqa: E402, F401
from packages.subsystems import flange_bearing_housing as _flange_bearing_housing  # noqa: E402, F401
from packages.subsystems import linear_bearing_block as _linear_bearing_block  # noqa: E402, F401
from packages.subsystems import lm_rail_end_cap as _lm_rail_end_cap  # noqa: E402, F401
from packages.subsystems import locating_pin as _locating_pin  # noqa: E402, F401
from packages.subsystems import taper_pin as _taper_pin  # noqa: E402, F401
from packages.subsystems import keyway_shaft as _keyway_shaft  # noqa: E402, F401
from packages.subsystems import v_block as _v_block  # noqa: E402, F401
from packages.subsystems import parallel_block_pair as _parallel_block_pair  # noqa: E402, F401
from packages.subsystems import jig_plate as _jig_plate  # noqa: E402, F401
from packages.subsystems import drill_jig as _drill_jig  # noqa: E402, F401
from packages.subsystems import alignment_fork as _alignment_fork  # noqa: E402, F401
from packages.subsystems import flat_gasket as _flat_gasket  # noqa: E402, F401
from packages.subsystems import oring_boss as _oring_boss  # noqa: E402, F401
from packages.subsystems import oring_groove_plate as _oring_groove_plate  # noqa: E402, F401
from packages.subsystems import cable_gland_body as _cable_gland_body  # noqa: E402, F401
from packages.subsystems import round_knob as _round_knob  # noqa: E402, F401
from packages.subsystems import star_knob as _star_knob  # noqa: E402, F401
from packages.subsystems import hex_knob as _hex_knob  # noqa: E402, F401
from packages.subsystems import T_handle as _T_handle  # noqa: E402, F401
from packages.subsystems import cabinet_pull as _cabinet_pull  # noqa: E402, F401
from packages.subsystems import bar_pull as _bar_pull  # noqa: E402, F401
from packages.subsystems import cylindrical_grip as _cylindrical_grip  # noqa: E402, F401
from packages.subsystems import tapered_grip as _tapered_grip  # noqa: E402, F401
from packages.subsystems import wire_clip as _wire_clip  # noqa: E402, F401
from packages.subsystems import zip_tie_saddle as _zip_tie_saddle  # noqa: E402, F401
from packages.subsystems import cable_gland_flange as _cable_gland_flange  # noqa: E402, F401
from packages.subsystems import strain_relief as _strain_relief  # noqa: E402, F401
from packages.subsystems import wire_labeler as _wire_labeler  # noqa: E402, F401
from packages.subsystems import hose_barb as _hose_barb  # noqa: E402, F401
from packages.subsystems import tri_stand as _tri_stand  # noqa: E402, F401
from packages.subsystems import four_leg_stand as _four_leg_stand  # noqa: E402, F401
from packages.subsystems import motor_bracket_stack as _motor_bracket_stack  # noqa: E402, F401
from packages.subsystems import pillow_block_pair_on_rail as _pillow_block_pair_on_rail  # noqa: E402, F401
from packages.subsystems import hinged_box_with_stop as _hinged_box_with_stop  # noqa: E402, F401
from packages.subsystems import sensor_mount_pair as _sensor_mount_pair  # noqa: E402, F401
from packages.subsystems import clamp_two_halves as _clamp_two_halves  # noqa: E402, F401
from packages.subsystems import flanged_socket_and_peg as _flanged_socket_and_peg  # noqa: E402, F401
from packages.subsystems import bearing_block_and_cap as _bearing_block_and_cap  # noqa: E402, F401

# Airliner-style tube fuselage (2026-07-18) -- named nose/parallel-body/tail stations + keel line,
# lofted in one smooth pass. `ogive_fuselage`'s sibling; see tube_fuselage.py's module docstring.
from packages.subsystems import tube_fuselage as _tube_fuselage  # noqa: E402, F401

# Blended-wing-body fuselage (2026-07-18) -- ONE continuous full-span loft, thick airfoil centerbody
# blending to thin wing-like tips. `naca_wing`'s sibling; see bwb_fuselage.py's module docstring.
from packages.subsystems import bwb_fuselage as _bwb_fuselage  # noqa: E402, F401

# Half-span wing panel (2026-07-19) -- root at the inner/body end, single taper to the outer tip;
# side_sign picks left/right. The side-panel `naca_wing` can't be. See wing_panel.py's docstring.
from packages.subsystems import wing_panel as _wing_panel  # noqa: E402, F401

# Rail-mount assembly (2026-07-22) -- a universal mounting rail + N subassembly plates bolted along
# it, the real pattern an electronics enclosure uses instead of an empty box. assembly_template
# composite (flat_bar rail + mounting_plate_grid plates), same live mechanism as `table.py`.
from packages.subsystems import rail_mount_assembly as _rail_mount_assembly  # noqa: E402, F401
