# packages/interactive_plane — Tier 0 (30 Hz)

**NO OCCT. NO LLM. NO solver. NO I/O. Closed-form arithmetic only, target <1 ms per number.**

An LLM or a kernel call in this loop is the original sin the whole architecture exists to avoid.
This package answers the floor-rail HUD during a slider drag from analytic proxies (mass = Σρ·V,
CG = mass-moment/total, print-time = volume/flow). The real regen + true integration happen in the
Truth Plane on slider-release. If a proxy can't stay within tolerance of the real value, the HUD
shows "unknown" — it never guesses. (Spike 5 sets the tolerance.)
