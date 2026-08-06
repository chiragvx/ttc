"""derived_housing (`packages/subsystems/derived_housing.py`) — Phase 5, gearbox-housing-generation
initiative.

Stage 1 coverage: registration + envelope_socket wiring, ParamSpec/invariant grounding (the 3.5-8mm
casting-wall floor — a disclosed engineering-judgment range, NOT a verbatim single-source citation; an
R3 review, 2026-08-06, CONFIRMED, high, caught an earlier revision falsely attributing this exact figure
to build-plan/research03aug/parametric/final_packaging_structural_design_research.md section 2, which
does not contain it — see derived_housing.py's own module docstring DFM section for the fix), no
`box_*_mm`-style guessed dims, and the geometry contract — a REAL HOLLOW
SHELL whose outer bounding box is at least as large as the wrapped group's own bbox (the housing must
actually contain what it wraps), whose cavity genuinely removes material.

Stage 2 coverage (2026-08-06, this file's own additions): bearing-seat bosses + oil-seal grooves at the
REAL world position of every wrapped `round_bar`/`spur_gear` member (a real shaft/bearing axis this
catalog can ground — see `derived_housing.py`'s own module docstring point 1), 4 `foot_mount` pads
composed via `assembly_children` at the housing's own real footprint corners, the two new DFM params
(`boss_rib_thickness_mm`/`outer_draft_deg`) that activate `validate.py`'s previously-dormant
`_dfm_wall_rib_params`/`_dfm_draft_param` checks, and real applied draft (a tapered-frustum outer
shell, `_outer_solid`/`_frustum_volume_mm3`).

Mirrors `tests/subsystems/test_envelope.py`'s own two-member synthetic-ledger pattern (root: 40x20x10
`flat_bar` at the origin; member2: 30x10x8 `flat_bar` translated to (100, 0, 0) — every extent hand-
computable integer arithmetic, no OCCT round-off) for the integration-style test that exercises the
REAL `compute_envelope` -> this subsystem's `outer_*_mm` params -> `_build_with_ledger` pipeline end to
end."""

from __future__ import annotations

import importlib.util

import pytest

from packages.ledger.parameter import ParameterDef
from packages.ledger.schema import Connection, InterfaceRef, Transform
from packages.subsystems import SUBSYSTEM_REGISTRY, add_instance, get_subsystem, get_subsystem_model
from packages.subsystems.assembly import instance_world_offsets
from packages.subsystems.assembly_template import reconcile_children
from packages.subsystems.envelope import compute_envelope

HAS_B123D = importlib.util.find_spec("build123d") is not None


def _pd(value: float, lo: float = -1e6, hi: float = 1e6, unit: str = "mm") -> ParameterDef:
    return ParameterDef(value=value, unit=unit, bounds=(lo, hi))


def _set_bar_dims(led, instance_id: str, length: float, width: float, thickness: float) -> None:
    """Same direct-mutation convention as test_envelope.py/test_geometry_query.py::_set_bar_dims —
    bounds are advisory-only (packages/ledger/CLAUDE.md), Instance/params are plain non-frozen models."""
    led.instances[instance_id].params["length_mm"] = _pd(length)
    led.instances[instance_id].params["width_mm"] = _pd(width)
    led.instances[instance_id].params["thickness_mm"] = _pd(thickness)


def _two_member_ledger(base_ledger, seeded):
    """Identical fixture shape to test_envelope.py::_two_member_ledger — root 40x20x10 flat_bar at the
    origin, member2 30x10x8 flat_bar at (100, 0, 0). Union bbox: x [-20, 115] -> 135; y [-10, 10] -> 20;
    z [-5, 5] -> 10 (hand-computable, exact — see test_envelope.py's own comment for the arithmetic)."""
    led = seeded(base_ledger, "flat_bar")
    root_id = led.root_id
    _set_bar_dims(led, root_id, length=40.0, width=20.0, thickness=10.0)

    led = add_instance(led, "flat_bar", "member2")
    _set_bar_dims(led, "member2", length=30.0, width=10.0, thickness=8.0)
    led.instances["member2"].transform = Transform(x_mm=100.0, y_mm=0.0, z_mm=0.0)

    return led, root_id


# ------- registration / catalog shape -------


def test_registered():
    assert "derived_housing" in SUBSYSTEM_REGISTRY
    sub = get_subsystem("derived_housing")
    assert sub.name == "derived_housing"
    assert isinstance(sub.applicable_disciplines, tuple)
    assert len(sub.applicable_disciplines) >= 1


def test_declares_envelope_socket_mapping_hull_bbox_keys_to_outer_dims():
    model = get_subsystem_model("derived_housing")
    assert model.envelope_socket is not None
    assert model.envelope_socket.dim_params == {
        "hull_bbox_x_mm": "outer_width_mm",
        "hull_bbox_y_mm": "outer_depth_mm",
        "hull_bbox_z_mm": "outer_height_mm",
    }


def test_fea_not_eligible_no_validated_housing_load_path_methodology():
    assert get_subsystem_model("derived_housing").fea_eligible is False


def test_wall_thickness_bounds_match_the_cited_casting_range():
    spec = {p.name: p for p in get_subsystem_model("derived_housing").params}["wall_thickness_mm"]
    assert spec.min == pytest.approx(3.5)
    assert spec.max == pytest.approx(8.0)


def test_no_independently_guessed_box_dimension_params_declared():
    # The exact violation this initiative exists to prevent (CLAUDE.md-equivalent rule, plan text): a
    # box_width_mm/box_depth_mm/box_height_mm-style triple the LLM could type independently, with
    # nothing tying it to what the housing actually contains.
    names = {p.name for p in get_subsystem_model("derived_housing").params}
    assert "box_width_mm" not in names
    assert "box_depth_mm" not in names
    assert "box_height_mm" not in names
    # the real, derived-not-guessed replacement names ARE present
    assert {"outer_width_mm", "outer_depth_mm", "outer_height_mm"} <= names
    assert "wall_thickness_mm" in names
    assert "clearance_mm" in names


# ------- invariants -------


def test_invariants_ok_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "derived_housing")
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert reasons == [], f"derived_housing default seeds must satisfy invariants: {reasons}"


def test_wall_thickness_below_casting_floor_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "derived_housing", wall_thickness_mm=(1.0, 0.1, 50.0))
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert any("casting-wall floor" in r for r in reasons)


def test_zero_outer_dims_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "derived_housing", outer_width_mm=(0.0, -1e6, 1e6))
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert any("must all be > 0" in r for r in reasons)


def test_negative_clearance_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "derived_housing", clearance_mm=(-1.0, -1e6, 1e6))
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert any("clearance_mm" in r and ">= 0" in r for r in reasons)


# ------- geometry: _dims/_volume arithmetic (pure python, no OCCT needed) -------


def test_volume_matches_nested_box_arithmetic(base_ledger, seeded_with):
    # outer_draft_deg=0.0 explicitly pinned: Stage 2 added real draft (default 1.0 deg, see
    # test_volume_with_draft_matches_the_closed_form_frustum_formula below) — this test's own point is
    # the UNDRAFTED, plain-nested-box formula, so it must not pick up Stage 2's nonzero default.
    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(100.0, 1.0, 1000.0), outer_depth_mm=(60.0, 1.0, 1000.0),
        outer_height_mm=(40.0, 1.0, 1000.0), wall_thickness_mm=(5.0, 0.1, 50.0),
        clearance_mm=(3.0, 0.0, 50.0), outer_draft_deg=(0.0, 0.0, 45.0),
    )
    v = get_subsystem("derived_housing").volume_mm3(led)
    cavity = (100.0 + 6.0) * (60.0 + 6.0) * (40.0 + 6.0)
    shell = (100.0 + 6.0 + 10.0) * (60.0 + 6.0 + 10.0) * (40.0 + 6.0 + 10.0)
    assert v == pytest.approx(shell - cavity)
    assert v > 0.0


def test_volume_with_draft_matches_the_closed_form_frustum_formula(base_ledger, seeded_with):
    # Same nested-box setup as the undrafted test above, but with a real, nonzero outer_draft_deg AND
    # generous wall_thickness_mm slack above the casting floor (8.0 mm -> up to 4.5mm of taper allowed
    # per side before _drafted_outer_dims's own safety clamp would kick in) so this test exercises the
    # UNCLAMPED arithmetic path — the volume must come in LOWER than the undrafted formula (a frustum
    # has less material than a box of the same footprint), by EXACTLY the closed-form frustum-minus-box
    # arithmetic (not just "smaller"). See test_draft_taper_is_clamped_... below for the CLAMPED path.
    import math

    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(100.0, 1.0, 1000.0), outer_depth_mm=(60.0, 1.0, 1000.0),
        outer_height_mm=(40.0, 1.0, 1000.0), wall_thickness_mm=(8.0, 3.5, 8.0),
        clearance_mm=(3.0, 0.0, 50.0), outer_draft_deg=(2.0, 0.0, 45.0),
    )
    v = get_subsystem("derived_housing").volume_mm3(led)
    cavity = (100.0 + 6.0) * (60.0 + 6.0) * (40.0 + 6.0)
    shell_w, shell_d, shell_h = 100.0 + 22.0, 60.0 + 22.0, 40.0 + 22.0  # +2*wall(8.0)+2*clearance(3.0)
    raw_taper_per_side = shell_h * math.tan(math.radians(2.0))
    max_taper_per_side = 8.0 - 3.5  # wall_thickness_mm - the casting floor -- see _drafted_outer_dims
    assert raw_taper_per_side < max_taper_per_side, "this test's own point is the UNCLAMPED path"
    a = 2.0 * raw_taper_per_side / shell_h
    outer = (shell_w * shell_d * shell_h - a * (shell_w + shell_d) * shell_h ** 2 / 2.0
             + a ** 2 * shell_h ** 3 / 3.0)
    assert v == pytest.approx(outer - cavity)
    undrafted_shell_volume = shell_w * shell_d * shell_h
    assert outer < undrafted_shell_volume  # a real frustum, not silently still a box


# ------- geometry: real OCCT build -------


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_geometry_builds_a_valid_hollow_solid_at_defaults(base_ledger, seeded):
    led = seeded(base_ledger, "derived_housing")
    part = get_subsystem("derived_housing").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    assert "housing.shell" in part.tag_keys
    assert "housing.cavity" in part.tag_keys


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_cavity_genuinely_removes_material(base_ledger, seeded_with):
    # "genuinely removes material" — the built solid's volume must be LESS than a solid block of the
    # same outer envelope, not just "some tags say there's a cavity".
    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(80.0, 1.0, 1000.0), outer_depth_mm=(60.0, 1.0, 1000.0),
        outer_height_mm=(50.0, 1.0, 1000.0), wall_thickness_mm=(5.0, 0.1, 50.0),
        clearance_mm=(5.0, 0.0, 50.0),
    )
    part = get_subsystem("derived_housing").geometry_builder(led)
    solid = part.solid
    assert solid is not None
    assert solid.is_valid

    hb = solid.bounding_box()
    outer_block_volume = hb.size.X * hb.size.Y * hb.size.Z
    assert solid.volume < outer_block_volume
    assert solid.volume > 0.0


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_housing_shell_bbox_is_at_least_as_large_as_the_wrapped_groups_own_bbox(base_ledger, seeded):
    """The core contract this stage exists to prove: given a synthetic ledger with a wrapped group +
    populated envelope_socket dims, the built shell's own outer bounding box actually CONTAINS the
    wrapped group's own real bbox — not merely "doesn't crash". Runs the REAL `compute_envelope`
    (Phase 2) over a real two-member group, then simulates Phase 3's async job writing its output
    through `envelope_socket`'s dim_params mapping into this housing's own params (the real write-
    through wiring is Phase 3's job, already landed elsewhere — this test recreates its end state
    directly, matching this stage's own scope: `_build` consuming already-populated params)."""
    from packages.subsystems import geometry_query as gq

    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, "derived_housing", "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]

    env = compute_envelope(led, "housing1")
    assert env.ok is True, env.reason

    led.instances["housing1"].params["outer_width_mm"] = _pd(env.values["hull_bbox_x_mm"])
    led.instances["housing1"].params["outer_depth_mm"] = _pd(env.values["hull_bbox_y_mm"])
    led.instances["housing1"].params["outer_height_mm"] = _pd(env.values["hull_bbox_z_mm"])

    group_bbox = gq.group_world_bbox(led, [root_id, "member2"])
    assert group_bbox is not None
    group_size = tuple(group_bbox[1][ax] - group_bbox[0][ax] for ax in range(3))
    assert group_size == pytest.approx((135.0, 20.0, 10.0))  # hand-computed, see module docstring

    part = get_subsystem("derived_housing").geometry_builder(led, "housing1")
    assert part.solid is not None
    assert part.solid.is_valid
    hb = part.solid.bounding_box()
    shell_size = (hb.size.X, hb.size.Y, hb.size.Z)

    for axis in range(3):
        assert shell_size[axis] >= group_size[axis] - 1e-6, (
            f"axis {axis}: housing shell size {shell_size[axis]} is SMALLER than the wrapped group's "
            f"own bbox size {group_size[axis]} — the housing fails to contain what it wraps")

    # Exact numeric check, not just an inequality: shell = hull_bbox_extent + 2*(wall + clearance),
    # using this housing instance's OWN default wall_thickness_mm/clearance_mm (5.0/5.0 — never
    # overridden in this test), so the expected margin is exact, hand-computable arithmetic.
    margin = 2.0 * (5.0 + 5.0)
    expected_shell = tuple(env.values[k] + margin for k in
                           ("hull_bbox_x_mm", "hull_bbox_y_mm", "hull_bbox_z_mm"))
    assert shell_size == pytest.approx(expected_shell, abs=1e-4)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_housing_shell_grows_outward_not_inward_from_the_derived_extent(base_ledger, seeded_with):
    """Directly guards the GROW-outward-from-the-hull-extent construction `_dims` documents (as opposed
    to a reversed/shrink-inward bug, which would silently produce a housing SMALLER than what it wraps
    — the exact failure mode the previous test's containment assertion is designed to catch, this test
    isolates it to the arithmetic alone, independent of compute_envelope/group_world_bbox)."""
    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(50.0, 1.0, 1000.0), outer_depth_mm=(50.0, 1.0, 1000.0),
        outer_height_mm=(50.0, 1.0, 1000.0), wall_thickness_mm=(4.0, 0.1, 50.0),
        clearance_mm=(2.0, 0.0, 50.0),
    )
    part = get_subsystem("derived_housing").geometry_builder(led)
    hb = part.solid.bounding_box()
    # 50 + 2*(4+2) = 62 on every axis (a cube in, a cube out).
    assert (hb.size.X, hb.size.Y, hb.size.Z) == pytest.approx((62.0, 62.0, 62.0))


# ======================================================================================
# Stage 2 (2026-08-06): bearing-seat bosses, oil-seal grooves, foot mounts, real DFM params.
# ======================================================================================

# ------- registration / catalog shape -------


def test_build_with_ledger_hook_is_registered_alongside_the_ledger_free_fallback():
    model = get_subsystem_model("derived_housing")
    assert model.build_with_ledger is not None
    assert model.build is not None  # compose.py::call() and other ledger-free callers still work


def test_boss_rib_and_draft_params_declared_with_expected_bounds():
    specs = {p.name: p for p in get_subsystem_model("derived_housing").params}
    assert specs["boss_rib_thickness_mm"].min == pytest.approx(0.5)
    assert specs["boss_rib_thickness_mm"].max == pytest.approx(5.0)
    assert specs["outer_draft_deg"].min == pytest.approx(0.5)
    assert specs["outer_draft_deg"].max == pytest.approx(5.0)


def test_boss_rib_default_is_compliant_with_the_cited_60pct_rib_ratio():
    specs = {p.name: p for p in get_subsystem_model("derived_housing").params}
    assert specs["boss_rib_thickness_mm"].value <= 0.6 * specs["wall_thickness_mm"].value


def test_outer_draft_default_is_at_or_above_the_cited_05deg_floor():
    specs = {p.name: p for p in get_subsystem_model("derived_housing").params}
    assert specs["outer_draft_deg"].value >= 0.5


# ------- invariants -------


def test_boss_rib_thickness_must_be_positive(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "derived_housing", boss_rib_thickness_mm=(0.0, -10.0, 10.0))
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert any("boss_rib_thickness_mm" in r and "> 0" in r for r in reasons)


def test_outer_draft_deg_out_of_range_violates(base_ledger, seeded_with):
    led = seeded_with(base_ledger, "derived_housing", outer_draft_deg=(90.0, 0.0, 180.0))
    reasons = get_subsystem("derived_housing").check_invariants(led)
    assert any("outer_draft_deg" in r and "[0, 90)" in r for r in reasons)


# ------- geometry: real draft applied to the outer shell -------


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_outer_draft_deg_actually_tapers_the_built_solid(base_ledger, seeded_with):
    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(50.0, 1.0, 1000.0), outer_depth_mm=(50.0, 1.0, 1000.0),
        outer_height_mm=(50.0, 1.0, 1000.0), wall_thickness_mm=(6.0, 0.1, 50.0),
        clearance_mm=(2.0, 0.0, 50.0), outer_draft_deg=(5.0, 0.0, 45.0),
    )
    part = get_subsystem("derived_housing").geometry_builder(led)
    solid = part.solid
    assert solid is not None
    assert solid.is_valid

    hb = solid.bounding_box()
    top_z, bottom_z = hb.max.Z, hb.min.Z
    verts = [(v.X, v.Y, v.Z) for v in solid.vertices()]
    top_x = max(abs(x) for x, _y, z in verts if abs(z - top_z) < 1e-3)
    bottom_x = max(abs(x) for x, _y, z in verts if abs(z - bottom_z) < 1e-3)
    assert top_x < bottom_x, (
        "the shell's own TOP cross-section must be narrower than its BOTTOM — real applied draft, "
        "not a cosmetic param nothing reads")

    tag = part.tags["housing.shell"]
    assert tag["outer_draft_deg"] == pytest.approx(5.0)
    assert tag["draft_taper_per_side_mm"] > 0.0


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_draft_taper_is_clamped_so_the_wall_never_thins_past_the_casting_floor(base_ledger, seeded_with):
    # A large draft + a tall shell + a wall right at the casting floor would, unclamped, taper the
    # outer surface literally INSIDE the cavity — `_drafted_outer_dims`'s own safety clamp must catch
    # this and still produce a VALID solid, never a broken/self-intersecting one.
    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(30.0, 1.0, 1000.0), outer_depth_mm=(30.0, 1.0, 1000.0),
        outer_height_mm=(400.0, 1.0, 1000.0), wall_thickness_mm=(3.5, 3.5, 8.0),
        clearance_mm=(1.0, 0.0, 50.0), outer_draft_deg=(5.0, 0.0, 45.0),
    )
    part = get_subsystem("derived_housing").geometry_builder(led)
    assert part.solid is not None
    assert part.solid.is_valid
    # wall_thickness_mm sits exactly AT the casting floor -> the clamp allows ZERO taper (max_taper =
    # wall - floor = 0), so the shell stays a plain (undrafted) box despite outer_draft_deg=5.0.
    assert part.tags["housing.shell"]["draft_taper_per_side_mm"] == pytest.approx(0.0, abs=1e-9)


# ------- geometry: bearing-seat bosses + oil-seal grooves at a real, grounded shaft axis -------


def _housing_wrapping_a_round_bar(base_ledger, seeded):
    """A derived_housing (as the ROOT instance) wrapping ONE top-level `round_bar` member at an
    explicit Transform — the recursion-safe position source `_member_world_xy` reads (see
    derived_housing.py's own module docstring 'recursion hazard' section). Outer dims sized generously
    so the shaft's own (12, -7) position sits well inside the housing's own footprint."""
    led = seeded(base_ledger, "derived_housing")
    housing_id = led.root_id
    led = add_instance(led, "round_bar", "shaft1")
    led.instances["shaft1"].transform = Transform(x_mm=12.0, y_mm=-7.0, z_mm=0.0)
    led.instances["shaft1"].params["dia_mm"] = _pd(8.0)
    led.instances["shaft1"].params["height_mm"] = _pd(40.0)
    led.instances[housing_id].wraps = ["shaft1"]
    led.instances[housing_id].params["outer_width_mm"] = _pd(80.0)
    led.instances[housing_id].params["outer_depth_mm"] = _pd(60.0)
    led.instances[housing_id].params["outer_height_mm"] = _pd(50.0)
    return led, housing_id


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_tag_reports_the_shaft_members_real_derived_world_position(base_ledger, seeded):
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert "housing.bearing_boss[shaft1]" in part.tags
    boss = part.tags["housing.bearing_boss[shaft1]"]
    # (12.0, -7.0) is shaft1's own explicit Transform -- NOT re-guessed, read straight off the ledger.
    assert boss["center_xy"] == pytest.approx([12.0, -7.0])
    assert boss["dia_mm"] > 0.0
    assert boss["height_mm"] == pytest.approx(led.instances[housing_id].params["wall_thickness_mm"].value)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_oil_seal_groove_tag_exists_at_the_same_shaft_axis_position(base_ledger, seeded):
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert "housing.oil_seal_groove[shaft1]" in part.tags
    groove = part.tags["housing.oil_seal_groove[shaft1]"]
    assert groove["center_xy"] == pytest.approx([12.0, -7.0])
    assert 0.0 < groove["inner_dia_mm"] < groove["outer_dia_mm"]
    assert groove["depth_mm"] > 0.0


# ------- R1 regression (2026-08-06, Phase 5, CONFIRMED, medium severity): the boss used to be a SOLID
# pad with only a cosmetic top-face groove -- nothing removed material for a real shaft to pass through
# the housing wall, and no bore/pocket existed for a bearing OD to seat into. See derived_housing.py's
# own module docstring "Fix note" for the full writeup.


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_tag_reports_a_bore_and_a_distinct_bearing_seat_tag_exists(base_ledger, seeded):
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    boss = part.tags["housing.bearing_boss[shaft1]"]
    assert boss["bore_dia_mm"] > 0.0
    assert boss["bore_dia_mm"] < boss["dia_mm"]  # the bore is narrower than the boss's own OD

    assert "housing.bearing_seat[shaft1]" in part.tags
    seat = part.tags["housing.bearing_seat[shaft1]"]
    assert seat["center_xy"] == pytest.approx([12.0, -7.0])
    assert seat["depth_mm"] > 0.0
    # a real, non-degenerate step: strictly between the through-bore and the boss's own OD
    assert boss["bore_dia_mm"] < seat["outer_dia_mm"] < boss["dia_mm"]


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_shaft_clearance_bore_actually_passes_through_the_boss_and_the_housing_wall(base_ledger, seeded):
    # The core of the confirmed defect: "nothing removes material for the actual shaft to pass through
    # the housing wall". Proved with real point-containment checks (bd.Solid.is_inside), not just tag
    # bookkeeping -- a point ON the shaft axis, deep inside what used to be solid wall material directly
    # beneath the boss, must now be OUTSIDE the built solid.
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    solid = part.solid

    # Geometry at this fixture's defaults (wall_thickness_mm=5.0, boss_rib_thickness_mm=2.0; outer dims
    # from the fixture -> cavity 90x70x60 -> shell 100x80x70, see _dims): top_z = shell_h/2 = 35, the
    # boss spans z in [35, 40] (boss_h == wall_thickness_mm == 5.0), the shell's own top wall cap spans z
    # in [30, 35] (thickness == wall_thickness_mm). shaft1's own housing-local axis is (12.0, -7.0) (this
    # fixture's housing sits at world (0, 0), see the sibling tag test above).
    axis_x, axis_y = 12.0, -7.0

    # On-axis, mid-way down the shell's own top wall cap -- solid material before this fix (the
    # confirmed defect), now hollowed out by the through-bore.
    assert not solid.is_inside((axis_x, axis_y, 32.0))
    # On-axis, mid-way up the boss itself, below the bearing-seat counterbore's own depth -- same bore.
    assert not solid.is_inside((axis_x, axis_y, 37.0))


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_seat_counterbore_leaves_a_real_shoulder_the_bore_alone_does_not_reach(base_ledger, seeded):
    # The other half of the confirmed defect: "no bore/pocket exists for a bearing OD to seat into". A
    # real bearing seat must be a genuinely STEPPED feature (a real shoulder a bearing's outer race can
    # register against), not merely a hole that happens to be wide. At the SAME radius (strictly between
    # the through-bore and the seat's own outer diameter), a point within the seat's own depth range must
    # be OUTSIDE the solid, while the SAME (x, y) further down (below the seat, within the wall cap,
    # where only the narrower through-bore has removed material) must be genuinely back INSIDE solid
    # material -- proving the step/shoulder actually exists, not just a wider hole all the way down.
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    solid = part.solid

    axis_x, axis_y = 12.0, -7.0
    r = 3.0  # strictly between bore_dia_mm/2 (2.5) and the seat's own outer_dia_mm/2 (3.5) at defaults
    seat_point = (axis_x + r, axis_y, 39.0)      # within the seat's own depth range [37.5, 40.5]
    shoulder_point = (axis_x + r, axis_y, 32.0)  # below the seat, within the wall cap -- only the
                                                  # narrower through-bore (radius 2.5) reaches here
    assert not solid.is_inside(seat_point), "the bearing-seat counterbore must remove material here"
    assert solid.is_inside(shoulder_point), (
        "material at this radius/depth must remain solid -- this IS the shoulder a bearing's outer race "
        "would register against; if this is also hollow, the 'seat' isn't a real stepped feature")


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_and_groove_produce_a_valid_solid_with_more_volume_than_the_bare_shell(base_ledger, seeded):
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    part_with_shaft = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert part_with_shaft.solid is not None
    assert part_with_shaft.solid.is_valid

    led.instances[housing_id].wraps = []  # same ledger/params, minus the wrap -- apples-to-apples
    part_bare = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert part_with_shaft.solid.volume > part_bare.solid.volume, (
        "the bearing boss must add real, net-positive material (boss volume clearly exceeds the "
        "shallow oil-seal groove's own removed volume)")


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_no_bearing_boss_for_a_non_shaft_wraps_member_type(base_ledger, seeded):
    # both wrapped members are flat_bar -- not in _SHAFT_AXIS_INTERFACE_BY_SUBSYSTEM -- no boss/groove
    # must be fabricated for either of them.
    led, root_id = _two_member_ledger(base_ledger, seeded)
    led = add_instance(led, "derived_housing", "housing1")
    led.instances["housing1"].wraps = [root_id, "member2"]
    led.instances["housing1"].params["outer_width_mm"] = _pd(135.0)
    led.instances["housing1"].params["outer_depth_mm"] = _pd(20.0)
    led.instances["housing1"].params["outer_height_mm"] = _pd(10.0)

    part = get_subsystem("derived_housing").geometry_builder(led, "housing1")
    assert not any(k.startswith("housing.bearing_boss") for k in part.tags)
    assert not any(k.startswith("housing.oil_seal_groove") for k in part.tags)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_also_recognizes_a_wrapped_spur_gear_member(base_ledger, seeded):
    # The OTHER recognized shaft-axis member type (see _SHAFT_AXIS_INTERFACE_BY_SUBSYSTEM) -- its
    # "mesh" interface sits at its own local origin (0, 0, 0) regardless of module_mm/tooth_count, so
    # the world axis position is just its own explicit Transform, unlike round_bar's off-axis check.
    led = seeded(base_ledger, "derived_housing")
    housing_id = led.root_id
    led = add_instance(led, "spur_gear", "gear1")
    led.instances["gear1"].transform = Transform(x_mm=5.0, y_mm=15.0, z_mm=0.0)
    led.instances[housing_id].wraps = ["gear1"]
    led.instances[housing_id].params["outer_width_mm"] = _pd(80.0)
    led.instances[housing_id].params["outer_depth_mm"] = _pd(60.0)
    led.instances[housing_id].params["outer_height_mm"] = _pd(50.0)

    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert "housing.bearing_boss[gear1]" in part.tags
    assert part.tags["housing.bearing_boss[gear1]"]["center_xy"] == pytest.approx([5.0, 15.0])
    assert "housing.oil_seal_groove[gear1]" in part.tags


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_shaft_axis_tipped_off_world_z_is_excluded_from_boss_placement(base_ledger, seeded):
    # rx_deg != 0 tips the shaft's own axis off world-Z -- out of this stage's honest scope (see module
    # docstring point 1) -- must be silently excluded, never given a fabricated boss position.
    led, housing_id = _housing_wrapping_a_round_bar(base_ledger, seeded)
    led.instances["shaft1"].transform = Transform(x_mm=12.0, y_mm=-7.0, z_mm=0.0, rx_deg=30.0)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    assert "housing.bearing_boss[shaft1]" not in part.tags
    assert "housing.oil_seal_groove[shaft1]" not in part.tags


# ------- R2 regression (2026-08-06, Phase 5, CONFIRMED, high severity): a mate-solved wrapped member's
# real world position must include `assembly.py::_component_shifts`'s shelf-packer correction, not just
# `placement.py::resolve_placements()`'s raw, per-connected-component DATUM-RELATIVE transform. That
# correction is what `assembly.instance_world_offsets` (the function that actually governs what
# renders) adds for every member of the SECOND and later UNANCHORED connected components -- e.g. the
# second stage of a two-stage gear reduction, exactly this initiative's primary target scenario. See
# derived_housing.py's own module docstring, third "Fix note", for the full defect/fix writeup.

def _two_independent_mesh_stage_ledger(base_ledger, seeded):
    """A `derived_housing` (root, explicitly pinned at world origin) wrapping ONLY the second of two
    independent, unanchored spur_gear mesh pairs (stage A: gA1<->gA2, stage B: gB1<->gB2) -- neither
    pair anchored, and the two pairs are not connected to each other, mirroring
    `tests/subsystems/test_assembly.py::_two_stage_gearbox_ledger` exactly (this is the SAME synthetic
    shape R2's own live repro used). Housing pinned at world (0, 0, 0) via an explicit identity
    `Transform` -- housing-local == world for every assertion below, isolating this test to Finding 2
    (the member-side shift) independent of Finding 1 (the housing's own offset, fixed separately)."""
    led = seeded(base_ledger, "derived_housing")
    housing_id = led.root_id
    led.instances[housing_id].transform = Transform()  # pinned at world origin, explicitly

    for iid in ("gA1", "gA2", "gB1", "gB2"):
        led = add_instance(led, "spur_gear", iid)
    led.connections = [
        Connection(id="stageA", a=InterfaceRef(instance_id="gA1", interface="mesh"),
                   b=InterfaceRef(instance_id="gA2", interface="mesh")),
        Connection(id="stageB", a=InterfaceRef(instance_id="gB1", interface="mesh"),
                   b=InterfaceRef(instance_id="gB2", interface="mesh")),
    ]
    led.instances[housing_id].wraps = ["gB1", "gB2"]
    led.instances[housing_id].params["outer_width_mm"] = _pd(200.0)
    led.instances[housing_id].params["outer_depth_mm"] = _pd(120.0)
    led.instances[housing_id].params["outer_height_mm"] = _pd(60.0)
    return led, housing_id


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_position_matches_the_real_rendered_position_for_the_second_unanchored_mesh_stage(
        base_ledger, seeded):
    led, housing_id = _two_independent_mesh_stage_ledger(base_ledger, seeded)

    # Ground truth: what actually renders (assembly.instance_world_offsets), exactly as R2's own live
    # repro checked it. The shelf-packer must have moved stage B off the pre-shift datum-relative
    # origin to avoid colliding with stage A's own real footprint -- that's the whole premise of the
    # confirmed bug (an all-zero shift here would make this test meaningless).
    real_offsets = instance_world_offsets(led)
    real_gb1_xy = (real_offsets["gB1"][0], real_offsets["gB1"][1])
    assert real_gb1_xy != pytest.approx((0.0, 0.0)), (
        "test setup did not actually force a nonzero shelf-packer shift on stage B -- fix the fixture")

    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    boss = part.tags["housing.bearing_boss[gB1]"]
    # housing is pinned at world (0, 0) -- HOUSING-LOCAL == WORLD here, so the tag must match the real
    # rendered position exactly, not the pre-shift datum-relative (0, 0) `resolve_placements` alone
    # would have given gB1 (it is stage B's own datum -- the confirmed bug's old behavior).
    assert boss["center_xy"] == pytest.approx(list(real_gb1_xy), abs=1e-6)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_oil_seal_groove_position_matches_the_real_rendered_position_for_the_second_unanchored_mesh_stage(
        base_ledger, seeded):
    # same defect, the groove tag (concentric with the boss) must match too.
    led, housing_id = _two_independent_mesh_stage_ledger(base_ledger, seeded)
    real_offsets = instance_world_offsets(led)
    real_gb1_xy = (real_offsets["gB1"][0], real_offsets["gB1"][1])

    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    groove = part.tags["housing.oil_seal_groove[gB1]"]
    assert groove["center_xy"] == pytest.approx(list(real_gb1_xy), abs=1e-6)


# ------- R5 regression (2026-08-06, Phase 5, CONFIRMED, high severity): a wrapped shaft/gear member's
# boss/groove HOUSING-LOCAL offset must still land on the shaft's REAL world position once the housing's
# own built solid is placed at ITS real world offset, even when the HOUSING ITSELF carries no explicit
# Transform and is not the sole/first auto-laid-out top-level instance. `_housing_world_xy`'s recursion-
# breaking fallback approximates this instance's own Y-extent as the bare, boss-free `shell_d` -- exact
# only when every boss stays within the bare shell's own footprint; an ordinary, unrelated filler part
# seeded earlier in the same file (zero manual configuration) displaces the housing into a non-origin
# auto-layout slot, which can push a boss placed against the WRONG (approximated) origin outside that
# footprint, inflating the housing's own REAL built Y-extent past what the approximation assumed --
# exactly the same "filler part pushes an un-transformed housing off its wraps group" scenario
# tests/backend/test_envelope_ops_transport.py's own R5 "sibling finding" fixed for the housing's SIZE/
# POSITION (`housing_alignment_transform`); this finding is the sibling: the BOSS/GROOVE placement, for a
# housing that has never gone through that alignment (a plain, never-derived, auto-laid-out housing --
# the state this flow passes through before a user ever runs wrap_group, or a housing whose `wraps` were
# hand-set directly). See derived_housing.py's own `_build_with_ledger`/`_housing_world_xy` docstrings for
# the fix (a bounded, iterative fixed-point correction).

def _housing_pushed_by_a_filler_part_wrapping_a_round_bar(base_ledger, seeded):
    """An ordinary, unrelated top-level `flat_bar` filler seeded FIRST (no explicit transform of its own,
    no relation to the housing or its wraps group), THEN a `derived_housing` (also no explicit transform
    -- relies on auto-layout, the ordinary case) wrapping a `round_bar` shaft at an EXPLICIT `Transform`
    (so the shaft's own real world position is fixed/known regardless of anything else in the ledger)."""
    led = seeded(base_ledger, "flat_bar")
    filler_id = led.root_id

    led = add_instance(led, "derived_housing", "housing1")
    led.instances["housing1"].params["outer_width_mm"] = _pd(80.0)
    led.instances["housing1"].params["outer_depth_mm"] = _pd(60.0)
    led.instances["housing1"].params["outer_height_mm"] = _pd(50.0)

    led = add_instance(led, "round_bar", "shaft1")
    led.instances["shaft1"].transform = Transform(x_mm=12.0, y_mm=-7.0, z_mm=0.0)
    led.instances["shaft1"].params["dia_mm"] = _pd(8.0)
    led.instances["shaft1"].params["height_mm"] = _pd(40.0)
    led.instances["housing1"].wraps = ["shaft1"]
    return led, filler_id, "housing1"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_bearing_boss_world_position_matches_the_shaft_even_when_a_filler_part_displaces_the_housings_auto_layout_slot(
        base_ledger, seeded):
    led, _filler_id, housing_id = _housing_pushed_by_a_filler_part_wrapping_a_round_bar(base_ledger, seeded)

    # sanity: the housing must actually have been displaced off the origin by the filler -- otherwise
    # this test would prove nothing (mirrors the fixture-sanity-check style the R2 regression above uses;
    # this is also literally the same "test setup did not actually displace..." style check
    # test_envelope_ops_transport.py's own sibling R5 test uses for the analogous filler-part fixture).
    before = instance_world_offsets(led)
    assert before[housing_id][1] != pytest.approx(0.0, abs=1e-3), (
        "test setup did not actually displace the housing via auto-layout -- fix the fixture")

    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    boss = part.tags["housing.bearing_boss[shaft1]"]

    # Ground truth: what actually renders once the (now boss-inflated) housing geometry is placed at its
    # own REAL resolved world offset -- exactly what render_assembly/compose.place would do.
    real_offsets = instance_world_offsets(led)
    housing_wx, housing_wy, _hwz = real_offsets[housing_id]
    boss_world_xy = (boss["center_xy"][0] + housing_wx, boss["center_xy"][1] + housing_wy)
    shaft_wx, shaft_wy, _swz = real_offsets["shaft1"]

    # A bounded, iteratively-converged fixed-point correction (see _build_with_ledger's own docstring),
    # not exact to float precision -- but must land well within any physical manufacturing tolerance.
    # The pre-fix behavior missed by tens of mm on this exact fixture shape (confirmed live this session,
    # before this fix: a live repro against the same fixture shape, differing only in the filler's exact
    # dims, measured an ~18-23mm miss with zero correction and only a partial ~9mm residual after a
    # single, non-iterative correction pass) -- 0.05mm is a bright, unambiguous line between "the fix
    # works" and "the fix is still broken", not a loosened tolerance chasing a flaky float comparison.
    assert boss_world_xy == pytest.approx((shaft_wx, shaft_wy), abs=0.05)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_oil_seal_groove_world_position_matches_the_shaft_even_when_a_filler_part_displaces_the_housings_auto_layout_slot(
        base_ledger, seeded):
    # same defect/fix, the groove tag (concentric with the boss) must match too.
    led, _filler_id, housing_id = _housing_pushed_by_a_filler_part_wrapping_a_round_bar(base_ledger, seeded)
    part = get_subsystem("derived_housing").geometry_builder(led, housing_id)
    groove = part.tags["housing.oil_seal_groove[shaft1]"]

    real_offsets = instance_world_offsets(led)
    housing_wx, housing_wy, _hwz = real_offsets[housing_id]
    groove_world_xy = (groove["center_xy"][0] + housing_wx, groove["center_xy"][1] + housing_wy)
    shaft_wx, shaft_wy, _swz = real_offsets["shaft1"]
    assert groove_world_xy == pytest.approx((shaft_wx, shaft_wy), abs=0.05)


# ------- foot-mount composition (assembly_children/ChildSpec) -------


def test_foot_mount_children_created_via_assembly_children(base_ledger, seeded):
    led = seeded(base_ledger, "derived_housing")
    root_id = led.root_id
    led = reconcile_children(led, root_id)
    for i in range(4):
        assert f"{root_id}_foot{i}" in led.instances
        assert led.instances[f"{root_id}_foot{i}"].subsystem_type == "foot_mount"


def test_foot_mount_children_sit_at_the_shells_own_real_footprint_corners(base_ledger, seeded):
    led = seeded(base_ledger, "derived_housing")
    root_id = led.root_id
    led = reconcile_children(led, root_id)
    # defaults: outer 80x60x50, wall 5, clearance 5 -> cavity 90x70x60 -> shell 100x80x70 (see _dims).
    # inset 10mm -> half_w = 100/2-10=40, half_d = 80/2-10=30; z = -70/2 - 8/2 = -39 (foot_height=8).
    expected = {
        "foot0": (-40.0, -30.0, -39.0),
        "foot1": (40.0, -30.0, -39.0),
        "foot2": (-40.0, 30.0, -39.0),
        "foot3": (40.0, 30.0, -39.0),
    }
    for local_id, (ex, ey, ez) in expected.items():
        t = led.instances[f"{root_id}_{local_id}"].transform
        assert t is not None
        assert (t.x_mm, t.y_mm, t.z_mm) == pytest.approx((ex, ey, ez))


def test_children_pass_explicit_outer_dia_matching_the_corner_spacing_constant(base_ledger, seeded):
    """R5 review, CONFIRMED, medium fix: the feet's own REAL BUILT outer_dia_mm must match
    `_FOOT_OUTER_DIA_MM` -- the value `_foot_corner_xy` assumes when it guarantees non-interpenetration
    -- not an implicit foot_mount-registered default that could silently drift out of sync with it."""
    from packages.subsystems.derived_housing import _FOOT_OUTER_DIA_MM

    led = seeded(base_ledger, "derived_housing")
    root_id = led.root_id
    led = reconcile_children(led, root_id)
    for i in range(4):
        foot = led.instances[f"{root_id}_foot{i}"]
        assert foot.params["outer_dia_mm"].value == pytest.approx(_FOOT_OUTER_DIA_MM)


def test_foot_corners_never_interpenetrate_on_a_small_housing(base_ledger, seeded_with):
    """R5 review, CONFIRMED, medium — regression for the confirmed defect: a housing whose derived
    footprint falls under roughly `2*_FOOT_INSET_MM + _FOOT_OUTER_DIA_MM` (~40mm/axis) used to place 4
    foot_mount children close enough to physically overlap each other (see derived_housing.py's own
    "Fix note" for the full writeup). Reproduces the reviewer's own live repro shape: an 8mm outer_*_mm
    hull extent (matching a single 8mm round_bar's own derived hull) at this subsystem's own default
    wall_thickness_mm/clearance_mm -> a 28x28mm shell (see `_dims`), well under that threshold."""
    from packages.subsystems.derived_housing import _FOOT_OUTER_DIA_MM

    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(8.0, 1.0, 600.0), outer_depth_mm=(8.0, 1.0, 600.0),
        outer_height_mm=(8.0, 1.0, 600.0),
    )
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    x = {i: led.instances[f"{root_id}_foot{i}"].transform.x_mm for i in range(4)}
    y = {i: led.instances[f"{root_id}_foot{i}"].transform.y_mm for i in range(4)}
    # Every pair of feet sharing an axis must sit at least one full foot diameter apart center-to-center
    # (foot0/foot1 share y and differ in x; foot2/foot3 share y and differ in x; foot0/foot2 and
    # foot1/foot3 share x and differ in y — see `_foot_corner_xy`'s own corner ordering).
    for i, j in [(0, 1), (2, 3)]:
        assert abs(x[i] - x[j]) >= _FOOT_OUTER_DIA_MM - 1e-9
    for i, j in [(0, 2), (1, 3)]:
        assert abs(y[i] - y[j]) >= _FOOT_OUTER_DIA_MM - 1e-9


def test_foot_corners_never_collapse_to_a_single_point_on_an_extreme_small_housing(base_ledger, seeded_with):
    """R5 review, CONFIRMED, medium — regression for the MORE EXTREME case the reviewer flagged: the
    OLD `max(0.0, ...)` clamp collapsed all 4 feet onto the EXACT SAME coordinate on an axis once
    shell/2 fell below `_FOOT_INSET_MM` (shell under 20mm on that axis). Reproduced here at every
    relevant param's own registered minimum (outer 10mm, wall 3.5mm, clearance 1mm -> shell ~19mm on
    each axis, see DERIVED_HOUSING's own ParamSpec bounds)."""
    from packages.subsystems.derived_housing import _FOOT_OUTER_DIA_MM

    led = seeded_with(
        base_ledger, "derived_housing",
        outer_width_mm=(10.0, 10.0, 600.0), outer_depth_mm=(10.0, 10.0, 600.0),
        outer_height_mm=(10.0, 10.0, 600.0),
        wall_thickness_mm=(3.5, 3.5, 8.0), clearance_mm=(1.0, 1.0, 25.0),
    )
    root_id = led.root_id
    led = reconcile_children(led, root_id)

    xs = [led.instances[f"{root_id}_foot{i}"].transform.x_mm for i in range(4)]
    ys = [led.instances[f"{root_id}_foot{i}"].transform.y_mm for i in range(4)]
    assert len(set(xs)) == 2  # two distinct +-half_w values — never collapsed onto one coordinate
    assert len(set(ys)) == 2
    assert (max(xs) - min(xs)) >= _FOOT_OUTER_DIA_MM - 1e-9
    assert (max(ys) - min(ys)) >= _FOOT_OUTER_DIA_MM - 1e-9


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_render_assembly_produces_the_housing_shell_plus_four_separate_feet(base_ledger, seeded):
    from packages.subsystems.assembly import render_assembly

    led = seeded(base_ledger, "derived_housing")
    led = reconcile_children(led, led.root_id)
    part = render_assembly(led)
    assert part.solid is not None
    solids = list(part.solid.solids())
    assert len(solids) == 5  # 1 housing shell + 4 feet, NOT fused (compose(), not fuse())


# ------- DFM param naming: proves validate.py's dormant checks are now LIVE, not just name-matching -------


def test_dfm_wall_rib_params_resolve_non_none_against_this_subsystem():
    from packages.truth_plane.validate import _dfm_wall_rib_params
    model = get_subsystem_model("derived_housing")
    assert _dfm_wall_rib_params(model) == ("wall_thickness_mm", "boss_rib_thickness_mm")


def test_dfm_draft_param_resolves_non_none_against_this_subsystem():
    from packages.truth_plane.validate import _dfm_draft_param
    model = get_subsystem_model("derived_housing")
    assert _dfm_draft_param(model) == "outer_draft_deg"


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_dormant_dfm_check_actually_fires_for_a_noncompliant_rib_ratio(base_ledger, seeded_with):
    from packages.truth_plane.validate import validate_geometry

    led = seeded_with(
        base_ledger, "derived_housing",
        wall_thickness_mm=(5.0, 3.5, 8.0), boss_rib_thickness_mm=(4.0, 0.1, 10.0),  # 80% > 60% ceiling
    )
    report = validate_geometry(led)
    dfm_issues = [i for i in report.issues if i.check == "dfm"]
    assert dfm_issues, (
        "boss_rib_thickness_mm at 80% of wall_thickness_mm must trip the dormant rib-ratio DFM check "
        "-- this is the concrete proof the check is now LIVE, not just that the param names match")
    assert any("boss_rib_thickness_mm" in i.message for i in dfm_issues)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_dormant_dfm_check_fires_for_a_draft_angle_below_the_cited_minimum(base_ledger, seeded_with):
    from packages.truth_plane.validate import validate_geometry

    led = seeded_with(base_ledger, "derived_housing", outer_draft_deg=(0.1, 0.0, 45.0))  # < 0.5 deg floor
    report = validate_geometry(led)
    dfm_issues = [i for i in report.issues if i.check == "dfm"]
    assert dfm_issues, "outer_draft_deg below the cited 0.5 deg floor must trip the dormant draft DFM check"
    assert any("outer_draft_deg" in i.message for i in dfm_issues)


@pytest.mark.skipif(not HAS_B123D, reason="needs build123d")
def test_defaults_do_not_trip_the_dormant_dfm_checks(base_ledger, seeded):
    from packages.truth_plane.validate import validate_geometry

    led = seeded(base_ledger, "derived_housing")
    report = validate_geometry(led)
    assert not [i for i in report.issues if i.check == "dfm"]
