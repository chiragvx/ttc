import { describe, expect, it } from "vitest";
import { computeSliderRange } from "./sliderRange";

describe("computeSliderRange", () => {
  it("clamps the slider to the invariant-valid range when one is given", () => {
    // blend_taper_mm: recommended [0, 1500] but invariant-valid [0, 300] at span=600 — the slider
    // must NOT let you drag past 300 (where the two taper zones overlap = CONFLICT).
    const r = computeSliderRange(200, 0, 1500, { min: 0, max: 300 });
    expect(r.sliderMin).toBe(0);
    expect(r.sliderMax).toBe(300);
    expect(r.outsideRecommended).toBe(false);
  });

  it("flags outsideRecommended against the RECOMMENDED range, not the valid range", () => {
    // a value inside the valid range but outside the recommended envelope still shows the ⚠ cue
    const r = computeSliderRange(20, 6, 21, { min: 6, max: 40 });
    expect(r.sliderMax).toBe(40); // valid range wider than recommended — slider allows it
    expect(r.outsideRecommended).toBe(false); // 20 is inside recommended [6,21]
    const r2 = computeSliderRange(30, 6, 21, { min: 6, max: 40 });
    expect(r2.outsideRecommended).toBe(true); // 30 is outside recommended [6,21] but valid
    expect(r2.sliderMax).toBe(40);
  });

  it("keeps the current value reachable even if it sits outside the valid range", () => {
    // defensive: a stale/racing value beyond valid.max must still be on the track, never clipped off
    const r = computeSliderRange(350, 0, 1500, { min: 0, max: 300 });
    expect(r.sliderMax).toBe(350);
  });

  it("falls back to the recommended range when no valid range is supplied", () => {
    const r = computeSliderRange(50, 0, 100, undefined, 1);
    expect(r.sliderMin).toBe(0);
    expect(r.sliderMax).toBe(100);
  });

  it("extends the fallback range with headroom when the value is outside recommended", () => {
    // an LLM-set 14-legs-style value with no computed valid range: slider must still reach it
    const r = computeSliderRange(140, 0, 100, undefined, 1);
    expect(r.sliderMin).toBe(0);
    expect(r.sliderMax).toBeGreaterThanOrEqual(140);
    expect(r.outsideRecommended).toBe(true);
  });
});
