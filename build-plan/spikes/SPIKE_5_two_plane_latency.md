# Spike 5 — Two-Plane Latency

**Type:** 🟢 degrade-not-stop · **Status:** ⬜ Not started
**Owner:** Generalist + Claude (dev-time only)
**Kill threshold written:** 2026-06-27 (before any spike code)

---

## The bet being proved

The single "150 ms full recompile" clock is a fiction; the real UX is two planes:

- **(A) Drag preview:** during a slider drag, the client GPU-interpolates a **precomputed
  morph-target mesh family** across the bounded slider range (constant topology) — geometry
  *appears* to move at 30 Hz with zero server round-trips per frame.
- **(B) Analytic HUD:** mass / CG / print-time tick from **closed-form arithmetic** (mass = Σρ·V,
  CG = mass-moment/total, print-time = volume/flow-rate), not from a kernel regen.

Real B-rep regen is debounced to **slider-release** (Tier 1, async).

## Kill criteria (numeric, pre-committed) — DEGRADES, does not stop the product

Fall back to **rigid proxy-transform + regen-on-release** (a worse but shippable UX) if **either**:

- the analytic HUD proxy **diverges > 2–3%** on mass/CG anywhere in the slider range (the HUD would
  have to show `"unknown"` too often to be useful), **OR**
- the morph-valid sub-range (before a topology change breaks the constant-topology assumption) is
  **too narrow to feel like "the slider moves the geometry."**

This is a UX-quality gate, not an existential one. **It must never stop the product** — but if it
degrades, say so honestly rather than faking smoothness.

## Method / protocol

**Part A:**
1. Precompute a morph-target mesh family across one bounded slider (constant topology).
2. GPU-interpolate client-side; confirm sustained 30 Hz.
3. Find the valid sub-range — where along the slider does a topology change break the morph?

**Part B:**
1. Compute the analytic proxy (mass/CG/print-time) at 10 sample points across the range.
2. Compute the real OCCT regen + true mass integration at the same 10 points.
3. Measure divergence; build a **drift monitor** that plots where analytic-vs-real exceeds tolerance.

## Claude's role

- **Dev-time only.** Claude builds the morph-precompute job + the drift monitor so the kill decision
  is **data, not vibes**.
- **No runtime Claude.** The 30 Hz HUD is closed-form arithmetic — an LLM in this loop is the
  original sin the whole architecture exists to avoid.

## Results (fill in)

| Field | Value |
|-------|-------|
| Sustained 30 Hz on morph interpolation? | _yes/no_ |
| Morph-valid sub-range | _TBD_ (fraction of slider range) |
| Max analytic-vs-real divergence (mass/CG) | _TBD_ % (threshold: <2–3%) |
| **Classification** | _PASS / DEGRADE-fallback_ |
| Decision & rationale | _TBD_ |
