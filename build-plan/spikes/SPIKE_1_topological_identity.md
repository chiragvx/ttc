# Spike 1 — Persistent Topological Identity

**Type:** 🛑 STOP gate (stop-the-company) · **Status:** ⬜ Not started
**Owner:** OCCT/build123d engineer (⚠️ must be staffed/contracted before scoring — see risk below)
**Kill threshold written:** 2026-06-27 (before any spike code)

---

## The bet being proved

Generator-baked, human-meaningful feature tags emitted at creation time (`joint[7].pin_bore`,
`wing.rib[3].web`) — plus a geometric-signature backstop (centroid / area / normal / adjacency) —
give **persistent identity** that survives OCCT regeneration and sub-shape renumbering, **without**
needing a C++ OCAF/TNaming layer.

This is the keystone bet: it is the single root cause behind kernel mutation, picking, anchored HUD,
delta-mesh diffing, optimizer feature-targeting, and merge. If identity holds, the platform works.
If it doesn't, every one of those silently re-binds to the wrong geometry and "single source of
truth" is a lie. **It also decides whether we are a Python-monolith shop or need the rarest hire on
the board (Rust/OCCT-C++ FFI).**

## Kill criteria (numeric, pre-committed)

The spike is **DEAD** (Python-tag path fails → escalate to C++ OCAF/TNaming in OCCT) if **either**:

- **> 5%** of bindings, across the adversarial regen matrix, **silently re-bind to the wrong
  sub-shape** (re-bound to a geometrically incorrect face/edge without being flagged), **OR**
- **face-splitting booleans cannot be disambiguated** without manual per-case annotation.

A binding that re-resolves correctly **or** is honestly **flagged ambiguous** (refuses to bind,
asks for confirmation) is acceptable. Silent wrong binding is the only true failure.

## Method / protocol

1. **Shared part generator (built once, reused by Spike 4):** a build123d generator producing a
   landing-gear knuckle with a pin bore + a segmented wing-rib section, emitting stable tags at
   feature-creation time.
2. **Adversarial regen matrix — 80–120 edits**, must include the pathological cases:
   - dimension changes that renumber sub-shapes
   - rib add / remove
   - **face-splitting booleans** (one face becomes two)
   - **edge-merging fillets** (two edges become one)
3. **Re-ID harness:** after each regen, attempt to re-resolve every prior tagged binding via
   (a) baked tags, then (b) geometric-signature match within tolerance. Record: correct / flagged-
   ambiguous / **silently-wrong**.
4. **Ground-truth oracle (the hard part — see risk):** for each face-split/edge-merge case, a human
   must specify which sub-shape is the *correct* binding. The OCCT engineer hand-annotates this set.
5. **Score:** judge subagent tallies the silent-wrong count and the unannotatable-face-split count
   against the thresholds above.

## Claude's role

- **Dev-time only.** Claude Code scaffolds the tagged generator + the re-ID harness in a worktree; a
  subagent enumerates pathological boolean/fillet sequences a human wouldn't think of; the judge
  subagent tallies the silent-mismatch count into the scorecard.
- **No runtime Claude.** Identity is deterministic kernel work — the LLM never touches it.
- ⚠️ Claude writes fluent code against *phantom* OCP/pybind11 symbols. Require the OCP-introspection
  MCP + plan mode + a naming-stability property test. Do **not** trust Claude-authored OCAF code.

## Risks specific to this spike

- **R1 — owner-before-spike paradox.** This runs in days 0–30 but is exactly the zone Claude is
  most dangerous, and its kill-criterion needs a re-binding oracle that is itself the unsolved
  problem. **The OCCT engineer must build the ground-truth annotation set; generalists + Claude must
  not self-score this gate.** If the hire slips, the spike slips — accept that rather than fake it.
- **R2 — the wedge exercises this on day one.** A motor-mount bracket's bolt pattern / slip-fit boss
  IS the face-split case; there is no deferring it.

## Results (fill in)

| Field | Value |
|-------|-------|
| Edits run | _TBD_ |
| Silent wrong re-binds | _TBD_ (threshold: <5%) |
| Unannotatable face-splits | _TBD_ |
| **Classification** | _PASS / FALLBACK / STOP_ |
| Decision & rationale | _TBD_ |
| Escalation triggered? | _C++ OCAF/TNaming: yes/no_ |
