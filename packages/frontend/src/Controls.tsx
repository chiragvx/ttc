import { useState } from "react";
import type { ParamMutationRequest } from "./types";
import { RIB, SKIN } from "./types";

interface Bound {
  node: string;
  label: string;
  min: number;
  max: number;
  step: number;
  initial: number;
}

const BOUNDS: Bound[] = [
  { node: SKIN, label: "Skin thickness (mm)", min: 1, max: 5, step: 0.1, initial: 2 },
  { node: RIB, label: "Rib spacing (mm)", min: 10, max: 50, step: 1, initial: 20 },
];

interface Props {
  send: (req: ParamMutationRequest) => void;
  onSkin: (v: number) => void;
}

// Bounded sliders (physically clamped by the backend rules validator) + a HARD_LOCK toggle.
export function Controls({ send, onSkin }: Props) {
  const [values, setValues] = useState<Record<string, number>>(
    Object.fromEntries(BOUNDS.map((b) => [b.node, b.initial]))
  );
  const [locked, setLocked] = useState<Record<string, boolean>>({});

  const change = (b: Bound, v: number) => {
    setValues((prev) => ({ ...prev, [b.node]: v }));
    if (b.node === SKIN) onSkin(v);
    send({ target_node: b.node, requested_value: v });
  };

  const toggleLock = (b: Bound) => {
    const next = !locked[b.node];
    setLocked((prev) => ({ ...prev, [b.node]: next }));
    send({ target_node: b.node, requested_value: values[b.node], set_lock: next ? "HARD_LOCK" : "DYNAMIC" });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <h3 style={{ margin: "0 0 4px" }}>Parameters</h3>
      {BOUNDS.map((b) => (
        <div key={b.node}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
            <span>{b.label}</span>
            <span>
              <b>{values[b.node].toFixed(1)}</b>
              <button
                onClick={() => toggleLock(b)}
                title="Hard-lock"
                style={{ marginLeft: 8, background: "none", border: "none", cursor: "pointer", fontSize: 14 }}
              >
                {locked[b.node] ? "🔒" : "🔓"}
              </button>
            </span>
          </div>
          <input
            type="range"
            min={b.min}
            max={b.max}
            step={b.step}
            value={values[b.node]}
            disabled={locked[b.node]}
            onChange={(e) => change(b, parseFloat(e.target.value))}
            style={{ width: "100%" }}
          />
        </div>
      ))}
    </div>
  );
}
