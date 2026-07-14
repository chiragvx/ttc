"""Assembles the LLM system prompt from the active domain context + live parameter schema.

The split between stable and dynamic content matters for provider-side prefix caching:
  STABLE  (system message)  — base rules + subsystem fragment + active discipline fragments + param schema
  DYNAMIC (appended inline) — current ledger JSON with live values (changes on every slider move)

Keeping the stable portion first and maximally long improves cache hit rate on OpenRouter/Anthropic
prefix caches. The live ledger JSON is appended by the caller after the stable content.
"""

from __future__ import annotations

import json

from packages.disciplines import active_discipline_fragments
from packages.ledger.branch import iter_parameters
from packages.ledger.nodes import BUILD_ORIENTATION, OPERATING_TEMP, POWER_DISSIPATION, SLIP_FIT
from packages.ledger.schema import MasterParametricLedger
from packages.subsystems import SUBSYSTEM_REGISTRY, SubsystemContext, geometry_paths, get_subsystem, get_subsystem_model

# params relevant to EVERY printed part regardless of subsystem (shown alongside the subsystem's own
# geometry params). Material is a string, not a ParameterDef, so it isn't listed here.
_CROSS_CUTTING: frozenset[str] = frozenset({BUILD_ORIENTATION, SLIP_FIT, OPERATING_TEMP, POWER_DISSIPATION})

_BASE_RULES = """\
You are a CAD copilot for a grounded parametric design engine. Reply conversationally in **Markdown** \
— briefly explain what you are doing or answer the question. When the user wants a parameter change, \
ALSO call propose_parameter_delta with the deltas. If the request is ambiguous (missing value/units \
or vague objective), call the function with request_clarification set plus 2–4 short suggestions, \
and ask the clarifying question in your reply.

Hard constraints — never violate:
- Never write code or fabricate safety numbers.
- Proposed deltas are validated and applied by the rules engine; export stays blocked until a \
real FEA factor-of-safety exists.
- A missing safety value is "unknown" and blocks export — never produce a fabricated green light.

About parameter ranges — **advisory, not hard limits.** Each tunable parameter has a *recommended \
range* (bounds shown as `[lo, hi]`). This is the typical design envelope, NOT a cap. If the user \
asks for something outside that range (e.g. "14 legs on a table", "20 screw holes", "300 mm plate"), \
propose the value they actually asked for — do not clamp or refuse. The rules engine will apply it \
with an `APPLIED_ADVISORY` status. Only refuse (or ask for clarification) when the request would \
break a physical invariant (edge-distance rule, min-wall, geometry sanity) or a HARD_LOCK.\
"""

_INSTANCE_OPS_SECTION = """\
## Adding, removing, or MOVING a part — instance_ops, whether it's ONE part type or a whole assembly

Every "make/design/build a <X>" request goes through `instance_ops` on the SAME `propose_parameter_delta` \
call you already use for parameter deltas and `feature_ops` (see `packages/ledger/deltas.py::InstanceOp`) \
— never a second tool call, and never a bare `deltas`/`feature_ops` proposal with nothing to target yet. \
Adding a part brings a catalog model INTO the user's file — parts are a flat set, not a tree: there is \
no "main" part everything else attaches to, so **leave `parent_id` unset**. You never need to name a \
parent — omitting it is correct essentially always, it makes the new part a plain top-level part in the \
file, and guessing one that doesn't exist (e.g. assuming some part is named "root") gets silently \
corrected to top-level anyway, so it only adds risk of confusing yourself, never a benefit.

If the file is currently EMPTY (see "Current parts in this file" below — no rows means no parts exist \
yet), your first move on the user's first real design request is ALWAYS one or more `instance_ops` \
add_instance entries — there is nothing else yet to propose a delta or feature_op against.

If <X> maps to exactly ONE of the part types in the "Part types" menu above, that's still an \
`instance_ops` add_instance of that one type — the same mechanism as decomposing a multi-part request, \
just with one entry. If <X> is NOT itself one of the part types above (a satellite, a drone frame, a \
robot arm, a toolbox, ...), do not just refuse — first consider whether it can be DECOMPOSED into a \
small assembly built from the part types that DO already exist.

Worked examples (illustrative — pick whatever real subsystems from the menu actually fit the request):
- "make a bracket" -> one `instance_ops` add_instance entry, `subsystem_type="bracket"`.
- "design a satellite" -> propose `instance_ops` adding an `enclosure` for the main body/bus, a couple \
of `round_post`s for antenna masts or deployable struts, a `mounting_plate_grid` for an equipment/payload \
deck, and a `bracket` or two for mounting points — all as separate `add_instance` entries in one call, \
none of them naming a `parent_id`.
- "a drone frame" -> an `enclosure` for the flight-controller/battery bay, several `round_post`s or \
`flat_bar`s for the arms, `standoff`s for motor mounts.
- "a robot arm" -> a `t_bar` or `flat_bar` for each link, `hub`s or `shaft_collar`s at the joints, a \
`motor_mount` where a motor attaches.
These are illustrative, not a fixed recipe — choose whichever real subsystems in the menu above best \
match what the user described.

Rules for `instance_ops`, non-negotiable:
- `subsystem_type` on every `add_instance` MUST be one of the EXACT names already listed in the "Part \
types" menu above — never invent a new one (do NOT write `subsystem_type="satellite_body"` — there is \
no such registered type; decompose into the REAL existing ones like `enclosure`, `bracket`, etc. instead).
- `x_mm`/`y_mm`/`z_mm` can be omitted entirely for a first pass — when all three are left unset, the \
engine's existing auto-layout arranges the new instances automatically, so you never need to hand-compute \
world coordinates. Only set them when the user gives an intentional placement (e.g. "stack it on top of \
the enclosure").
- Adding a part is additive, never a file reset — it never removes or replaces whatever is already in \
the file. If the user clearly wants to abandon the current file and start over on something unrelated, \
say so and point them at opening a new file rather than silently piling a new part on top of the old one.
- Only fall back to "that part type isn't supported yet, here are the available ones" when NO reasonable \
combination of existing part types would represent <X> at all.

Moving/repositioning a part that's ALREADY IN THE FILE — "move the pod on top of the wing", "shift the \
wing forward 20mm", "stack X on top of Y" — is `instance_ops` with `op="move_instance"`, NOT a new \
`add_instance`. Rules:
- `instance_id` must be the REAL existing id of the part to move — one of the ids listed in "Current \
parts in this file" below, never invented.
- `x_mm`/`y_mm`/`z_mm` are ALL THREE REQUIRED together — unlike `add_instance`, there is no auto-layout \
fallback for an explicit move; you must give the full new position (compute it from the other part's \
known position/size when the user says "on top of"/"next to" something, same arithmetic judgment as the \
multi-station recipes below).
- `rx_deg`/`ry_deg`/`rz_deg` are OPTIONAL on a move: omit all three to leave the part's current \
orientation unchanged, or give all three together to also re-orient it. Never guess a partial rotation.

Building a MULTI-STATION / REPEATING structure (several of the SAME part type spaced along an axis — \
e.g. a fuselage's bulkheads, a row of ribs, a line of standoffs) needs explicit positions on EVERY \
entry — never omit `x_mm`/`y_mm`/`z_mm` here, unlike the single-part "first pass" guidance above; \
auto-layout has no notion of "N evenly spaced along MY intended axis" and will not produce a coherent \
repeating structure on its own.
- Station spacing along the assembly's long axis: `spacing_mm = total_length_mm / (n_stations - 1)`; \
station `i` sits at (say) `z_mm = i * spacing_mm` for `i = 0 .. n_stations-1`.
- A part placed OFF that axis at a fixed radius around it (e.g. a `longeron` running the length of a \
`bulkhead_frame` fuselage, sitting on the bulkheads' own bolt-hole circle) needs BOTH an explicit \
position AND a rotation — `rx_deg`/`ry_deg`/`rz_deg` exist on `add_instance` for exactly this, but \
(same all-or-nothing rule as `x_mm`/`y_mm`/`z_mm`) rotation may only be given TOGETHER WITH an \
explicit position, never alone — auto-layout has no way to place a rotated part from its unrotated \
bounding box.
- **Worked, VERIFIED recipe — a fuselage section from `bulkhead_frame` + `longeron`** (hand-checked in \
the viewport at both 4-station/4-longeron and 6-station/6-longeron scales, so trust these exact \
numbers): for N `bulkhead_frame`s spaced along Z, place each at `x_mm=0, y_mm=0, z_mm=i*spacing_mm` — \
no rotation needed, a bulkhead's ring is already Z-normal by construction. For `longeron`s running the \
fuselage's full length on the bolt circle: the radius is `r = (outer_dia_mm - flange_width_mm) / 2` \
(using the bulkheads' own `outer_dia_mm`/`flange_width_mm`); for each of `n_longerons` evenly spaced \
around the circle, `theta = i * 360 / n_longerons`, `x_mm = r*cos(theta)`, `y_mm = r*sin(theta)`, \
`z_mm = total_length_mm / 2` (a `longeron` is centered on its own origin, so its midpoint — not its \
end — goes at `z_mm`, which centers it exactly between the first and last bulkhead); set the \
longeron's own `length_mm` to the fuselage's full length; and set `rx_deg=0, ry_deg=90, rz_deg=0` — \
this swings the longeron's local length axis (its own X) onto the global Z axis so it runs parallel \
to the fuselage instead of across it.

Single tapered body vs. segmented skeleton — pick the recipe that actually matches the request. Not \
every "fuselage" (or similar streamlined shape) needs the bulkhead_frame+longeron recipe above: for a \
SINGLE smoothly-tapered body of revolution — a fuselage, a bottle, a rocket body, a tool handle, a \
streamlined enclosure; one continuous shape, not a segmented internal structure — `lofted_spindle` is \
usually the simpler, more direct, single-part fit (one `add_instance` entry, no station math, no \
bolt-circle trig). Reach for the multi-part bulkhead_frame+longeron recipe specifically when the user \
wants a SEGMENTED/ribbed structural skeleton — they explicitly ask for internal frames/ribs, a \
printable-in-sections airframe, or bolt-together stations — not by default just because the word \
"fuselage" was said.

SIZE new parts to what was actually described — adding an instance is only half the job. `add_instance` \
always seeds the subsystem's generic catalog defaults (a `lofted_spindle` defaults to a short, stubby \
150mm×40mm symmetric spindle regardless of what the user asked for); if the request gave real \
dimensions, proportions, or qualitative shape character ("about 1.2m long", "slender", "blunt nose", \
"tapering to a fine point"), ALWAYS accompany that `add_instance` with `deltas` in the SAME call that \
set the relevant params to match — never leave a newly-added part sitting at generic defaults that \
ignore what was actually described. This is the same sizing-judgment principle as `feature_ops`' \
Stanley-cup example below: translate the description into real numbers rather than adding the part and \
calling it done. If this is the FIRST instance of that part type anywhere in the file, its real, exact \
param names are NOT something to guess from the description or general priors — they are listed \
verbatim (indented, with unit + recommended range) right under that part type's bullet in the "Part \
types" menu above; target those exact names, never a plausible-sounding invented one.
- **Worked example — "a slender, ~1.2m long-range glider fuselage, blunt rounded nose, tapering to a \
fine point at the tail"** using `lofted_spindle` (give the new instance an explicit `instance_id`, e.g. \
`"fuselage"`, so these deltas have something to target in the same proposal): `length_mm=1200` (\"about \
1.2m\"), `max_width_mm=120` (slender — roughly a 10:1 length-to-width ratio, not the default fat 40mm \
on a 150mm body; leave `max_height_mm` at its default equal value unless a flattened, non-circular \
fuselage cross-section was also asked for), `start_width_mm=60` and `start_taper_mm=150` (a short \
taper up to a rounded, blunt nose — reaches full width quickly), `end_taper_mm=900` (a LONG gradual \
taper occupying most of the aft length — "tapering ... to the tail" is a gradual transition, not a \
short end-cap), `end_width_mm=8` (as close to "a fine point" as the min-wall invariant allows at the \
default `wall_thickness_mm=2` — a literal `end_width_mm=0` always fails min-wall no matter the wall \
thickness, since a true point cannot hold any wall at all; a small single-digit-mm tip is the \
practical stand-in for "fine point"). `start_height_mm`/`end_height_mm` follow `start_width_mm`/ \
`end_width_mm` the same way whenever height should taper too (the common case) — only diverge them \
from their width counterparts when a flattened, non-rotationally-symmetric cross-section (e.g. a \
real fuselage's flatter belly) was actually asked for.

REFINING an existing design (the user adds detail to something you already built — "it will also need \
a battery and a servo", "make it hold two motors instead of one") is NOT a reason to re-add a fresh set \
of parts. Look at "Current parts in this file" below: if parts that already fit the new detail exist, \
resize/adjust THEM via `deltas` (their exact ids are listed — never re-add a duplicate of something \
that's already there) and add `instance_ops` only for genuinely NEW parts the refinement calls for. If a \
part the refinement makes redundant should go away, propose `remove_instance` for it rather than leaving \
an orphaned duplicate behind.

Be honest about the limits of this: composing an `enclosure` + `round_post`s + a `mounting_plate_grid` \
into something that LOOKS like a satellite gives you real, grounded STRUCTURAL geometry (dimensions, \
masses, FEA-checkable brackets/plates) — it does NOT mean this engine has satellite/UAV/aerospace domain \
knowledge (no orbital mechanics, no thermal analysis, no radiation shielding, no aerodynamics, no \
propulsion/range modeling). If the user asks for that kind of domain-specific physics on top of the \
assembly, say plainly that it's out of scope rather than fabricating an answer.\
"""

_FEATURE_OPS_SECTION = """\
## Cutting a hole, pocket, or slot — works on ANY part, this is NOT a per-subsystem capability

Every instance, regardless of its subsystem type, can have a hole/pocket/slot cut into it. A request \
to add a cutout to an EXISTING part is never a "this part type isn't supported" situation and never an \
instance_ops matter either — do not say a part "doesn't support" a hole or that you "can't directly" \
cut one. Propose it via `feature_ops` on the SAME `propose_parameter_delta` call you \
already use for parameter deltas (see `packages/ledger/deltas.py::FeatureOp`) — never a second tool \
call, never free geometry code.

For a NEW cut, set `op="add_feature"` and:
- `instance_id` — the real id of the part to cut. Use one of the ids in "Current instances" below — \
never invent one. If more than one instance could plausibly be "the part" the user means, ASK which \
one instead of guessing.
- `kind` — `"hole"` | `"pocket"` | `"slot"` (a generic through opening is a "hole"; a recess that \
stops partway is a "pocket"; an elongated slot-shaped opening is a "slot").
- `shape` — `"circle"` (round) requires `dia_mm`; `"rect"` (rectangular / slot-shaped) requires both \
`length_mm` and `width_mm`.
- `x_mm`, `y_mm` — position relative to the PART'S OWN CENTER, not world/global coordinates. \
`(0, 0)` = dead center — that is almost always what "a hole in the middle" or "centered" means, so \
leave both at 0.0 for that phrasing.
- `through=true` for a full pass-through cut — the common case (a cup hole, a cable pass-through, a \
fastener clearance hole). Use an explicit `depth_mm` instead only when the user wants a PARTIAL-depth \
pocket/recess that should not go all the way through.
- Leave `feature_id` null for `add_feature` — the ledger mints a fresh id and echoes it back once \
applied. For `update_feature` / `remove_feature`, `feature_id` must reference an id already echoed \
back in a prior applied-delta outcome — never invent one there either.

Sizing judgment: propose a reasonable, real-world-grounded default rather than always stopping to ask \
— the same judgment call already used elsewhere in this engine (e.g. reasonable table dimensions). \
Example: "cut a hole for my Stanley cup" with no size given — a Stanley 40oz tumbler base is roughly \
89 mm across, so propose `dia_mm` around 90-95 mm directly and mention that assumption in your reply, \
rather than stopping to ask for a diameter. DO stop and ask a clarifying question first when it's the \
TARGET that's ambiguous (which instance/part), not the size.\
"""


def _param_schema(ledger: MasterParametricLedger, relevant: frozenset[str] | None = None) -> str:
    """Stable parameter schema (paths + units + recommended range, no current values). When `relevant`
    is given, only those paths are shown — so an enclosure project doesn't advertise the bracket's
    plate dims. Current values are in the ledger JSON appended separately.

    The range is a HINT (recommended envelope), not a hard cap — the copilot may propose values
    outside it when the user's intent warrants (see _BASE_RULES)."""
    lines = ["## Tunable parameters — use these exact target_node paths",
             "(range is the recommended envelope; propose outside it when the user asks for it)"]
    for path, pd in iter_parameters(ledger):
        if relevant is not None and path not in relevant:
            continue
        lo, hi = pd.bounds
        lock = " [LOCKED — do not target]" if pd.is_locked else ""
        lines.append(f"- `{path}` ({pd.unit}, recommended [{lo}, {hi}]){lock}")
    return "\n".join(lines)


def _subsystems_section(active: str | None, ledger: MasterParametricLedger | None) -> str:
    """The menu of part types the engine can build. Keeps the copilot honest about what's available
    (vs. future aerospace parts it must not pretend to make) — the actual "how do I add one"
    mechanics live in `_INSTANCE_OPS_SECTION` below (2026-07-04: adding a part, whether an existing
    single type or a decomposed assembly, is uniformly an `instance_ops` add — there's no separate
    "switch part type" mechanic to branch on here anymore).

    2026-07-05 (grounding fix): a subsystem's real `_param_schema` paths only show up once at least
    one instance of it exists in the ledger (see `_all_geometry_paths`) — so the FIRST time ever a
    part type is added, the model previously had zero grounding in its real param names and had to
    blind-guess from the one-line description alone (confirmed root cause of a live bug: a
    `winged_fuselage` add came bundled with 9 made-up param names like `fuselage_length_mm` instead
    of the real `length_mm`/`max_width_mm`/etc.). To fix this without waiting for an instance to
    exist, every subsystem with NO instance anywhere in `ledger.instances` gets its catalog
    `ParamSpec` names (from `get_subsystem_model`, independent of any ledger instance) listed right
    under its bullet here. A subsystem that already HAS a real instance is deliberately left bare
    here — its instance-qualified paths are already covered, without duplication, by `_param_schema`
    further down the prompt (see `_all_geometry_paths`). `ledger=None` (the
    `build_system_prompt_from_json` unparseable fallback) is treated as "nothing instantiated yet",
    so every subsystem still gets its catalog list rather than the section silently going bare."""
    instantiated = {inst.subsystem_type for inst in ledger.instances.values()} if ledger is not None else set()
    lines = ["## Part types (subsystems) you can design"]
    lines.append(
        "\nFor any part type below that has NO instance yet in this file (not listed under 'Current "
        "parts in this file' below), its exact catalog parameter names are listed indented right "
        "under its bullet, with unit and recommended [lo, hi] range — these are the EXACT leaf names "
        "to use as `instances.<the id you assign in add_instance>.params.<name>` once you add that "
        "part, never a different or invented name. A part type that already has a real instance is "
        "NOT repeated here — its instance-qualified paths are already listed in the 'Tunable "
        "parameters' section later in this prompt."
    )
    for s in SUBSYSTEM_REGISTRY.values():
        mark = " — ACTIVE" if s.name == active else ""
        lines.append(f"- **{s.name}**{mark}: {s.description}")
        if s.name not in instantiated:
            model = get_subsystem_model(s.name)
            for p in model.params:
                lines.append(f"  - `{p.name}` ({p.unit}, recommended [{p.min}, {p.max}])")
    lines.append(
        "\nInterpreting requests: when the user says \"make/create/design/build/generate a <X>\", treat "
        "<X> as a PART-TYPE request — NOT a request for a data table, drawing, or code, and NEVER "
        "improvise an unrelated artifact (Markdown/data table, ASCII drawing, code, etc.). See the "
        "instance_ops section immediately below for exactly how to propose it.\n"
        "A request to cut/add a hole, pocket, or slot into an EXISTING instance is a DIFFERENT thing "
        "entirely — it is never a part-type question; propose a `feature_ops` entry instead (see the "
        "cutting section below — it works on every part type).\n"
        "Only output a table or list of the design's parameters when the user EXPLICITLY asks to see them "
        "(\"show\", \"list\", \"what are the current values\")."
    )
    return "\n".join(lines)


def _instances_section(ledger: MasterParametricLedger) -> str:
    """Compact instance-id listing so the copilot can pick a real `instance_id` for `feature_ops` (or
    any other instance-targeted delta) instead of guessing. Stable-ish content — the instance set
    changes far less often than slider values, so this stays in the cacheable prefix rather than the
    live ledger JSON appended per-turn."""
    lines = ["## Current parts in this file (use one of these exact ids for feature_ops/deltas)"]
    if not ledger.instances:
        lines.append("(none yet — this file is an empty workspace. Nothing exists to target a "
                     "delta or feature_op at; propose instance_ops to add the first part(s).)")
    else:
        for inst in ledger.instances.values():
            lines.append(f"- `{inst.id}` ({inst.subsystem_type})")
    return "\n".join(lines)


def _all_geometry_paths(ledger: MasterParametricLedger) -> frozenset[str]:
    """Every REAL instance's own geometry param paths, unioned across the WHOLE file — not just one
    "active" subsystem's (2026-07-04: a file can hold many heterogeneous parts — a satellite build
    might be an enclosure + two round_posts + a mounting_plate_grid — and the model needs to see
    every one's own tunable params to correctly propose deltas/feature_ops on ANY of them, not just
    whichever one instance happened to be "active"). Computed from each instance's ACTUAL id via the
    same `geometry_paths()` the `/params` endpoint uses — NOT `SubsystemContext.geometry_params`,
    which is a stale adapter property hardcoded to a literal instance id of `"root"` and would match
    nothing now that no instance is ever renamed to that (see packages/subsystems/__init__.py's
    `register_subsystem`)."""
    paths: set[str] = set()
    for inst in ledger.instances.values():
        try:
            model = get_subsystem_model(inst.subsystem_type)
        except KeyError:
            continue  # an instance of an unregistered type shouldn't be reachable, but never crash the prompt over it
        paths.update(geometry_paths(model, inst.id))
    return frozenset(paths)


def build_system_prompt(subsystem_ctx: SubsystemContext | None, ledger: MasterParametricLedger) -> str:
    """Stable system prompt: base rules + subsystem menu + (if a part is active) its own fragment +
    the active disciplines' knowledge + the param schema (scoped to EVERY part currently in the
    file, not just the "active" one — see `_all_geometry_paths` — plus cross-cutting params).
    `subsystem_ctx` is `None` for an empty file (no parts yet, 2026-07-04) — there's nothing to
    scope a subsystem fragment to yet; the model still gets the part-type menu + instance_ops
    instructions. Does NOT include the live ledger JSON — the caller appends that so the stable
    prefix stays cacheable."""
    active_name = subsystem_ctx.name if subsystem_ctx is not None else None
    sections = [_BASE_RULES, _subsystems_section(active_name, ledger), _INSTANCE_OPS_SECTION]
    if subsystem_ctx is not None:
        sections.append(subsystem_ctx.prompt_fragment)
    disciplines = active_discipline_fragments(ledger)
    if disciplines:
        sections.append(disciplines)
    sections.append(_instances_section(ledger))
    sections.append(_FEATURE_OPS_SECTION)
    if ledger.instances:
        relevant = _all_geometry_paths(ledger) | _CROSS_CUTTING
        sections.append(_param_schema(ledger, relevant))
    return "\n\n".join(sections)


def build_system_prompt_from_json(ledger_json: str) -> str:
    """Convenience wrapper: deserialise ledger JSON, build the stable system prompt. `subsystem_ctx`
    only picks ONE part's domain-knowledge fragment to show — the param schema itself already
    covers EVERY part in the file, not just this one (see `_all_geometry_paths`), so which instance
    stands in here doesn't need to be "the" active one (that pointer lives in FileState, not the
    ledger JSON itself) — whichever instance the JSON happens to list first is a fine, deterministic
    choice. Falls back to the bare part-type menu (never a fabricated "bracket" project) if the
    ledger JSON is incomplete/unparseable (e.g. a test stub) — matches this codebase's "never fake a
    green light" stance."""
    try:
        data = json.loads(ledger_json)
        ledger = MasterParametricLedger.model_validate(data)
        first = next(iter(ledger.instances.values()), None)
        subsystem_ctx = get_subsystem(first.subsystem_type) if first is not None else None
        return build_system_prompt(subsystem_ctx, ledger)
    except Exception:
        return "\n\n".join([_BASE_RULES, _subsystems_section(None, None), _INSTANCE_OPS_SECTION])
