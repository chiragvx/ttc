// Pure slider-range logic (2026-07-19), extracted from ModelPanel so it can be unit-tested without
// rendering. Decides the hard [min,max] a parameter slider is allowed to reach, plus whether the
// current value sits outside its RECOMMENDED (advisory) envelope for the ⚠ cue.
//
// The clamp is the PHYSICALLY-VALID range (from the backend's cross-field invariants —
// packages/subsystems/valid_ranges.py), NOT the advisory recommended range. A human drag therefore
// cannot reach a CONFLICT (e.g. blend_taper_mm past span_mm/2), while a value the copilot deliberately
// set outside the recommended envelope (the "14 legs on a table" case) still shows on the slider and
// still flags ⚠ — the two concepts are kept separate on purpose. See packages/ledger/parameter.py's
// advisory-bounds docstring for why recommended bounds must never be a hard clamp.

export interface SliderRange {
  sliderMin: number;
  sliderMax: number;
  outsideRecommended: boolean;
}

export function computeSliderRange(
  value: number,
  recMin: number,
  recMax: number,
  valid?: { min: number; max: number },
  step: number = 0,
): SliderRange {
  const outsideRecommended = value < recMin || value > recMax;
  if (valid) {
    // The backend already widens each valid range to include the current value; the Math.min/max
    // guards are belt-and-suspenders so a stale/racing value can never fall outside the slider track.
    return {
      sliderMin: Math.min(valid.min, value),
      sliderMax: Math.max(valid.max, value),
      outsideRecommended,
    };
  }
  // No invariant-valid range available (older backend, or a cross-cutting param with no computed
  // range): fall back to the recommended range, extended by a little headroom ONLY when the current
  // value already sits outside it, so an out-of-recommended value stays draggable rather than pinned.
  const headroom = Math.max(step, (recMax - recMin) * 0.1);
  return {
    sliderMin: outsideRecommended ? Math.min(recMin, value - headroom) : recMin,
    sliderMax: outsideRecommended ? Math.max(recMax, value + headroom) : recMax,
    outsideRecommended,
  };
}
