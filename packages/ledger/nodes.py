"""Canonical ledger node paths — so modules don't hard-code dotted strings.

After the Phase A-E refactor: only CROSS-CUTTING discipline paths live here. Per-subsystem geometry
params are addressed as `domains.geometry.<param_name>` and declared by each subsystem's ParamSpec
(packages/subsystems/<name>.py). Legacy bracket/hole constants now point at the geometry bag so
existing solver code and tests keep working.
"""

# cross-cutting discipline paths
MATERIAL = "domains.structure.material_profile"
BUILD_ORIENTATION = "domains.manufacturing.build_orientation_deg"
SLIP_FIT = "domains.manufacturing.slip_fit_clearance_mm"
OPERATING_TEMP = "domains.thermal.operating_temp_c"
POWER_DISSIPATION = "domains.thermal.power_dissipation_w"

# bracket geometry — now in the generic bag (Phase D). Kept as named constants for solver code
# (analysis.py, sweep.py) that reads a params dict keyed by these strings.
SKIN = "instances.root.params.skin_thickness_mm"
RIB = "instances.root.params.internal_rib_spacing_mm"
WIDTH = "instances.root.params.plate_width_mm"
DEPTH = "instances.root.params.plate_depth_mm"
HOLE_DIA = "instances.root.params.hole_diameter_mm"
