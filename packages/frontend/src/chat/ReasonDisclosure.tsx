import { useState } from "react";

// "Decision visible, reasoning one click away" (2026-07-04 widget redesign) — a hover-only title
// tooltip is easy to miss, especially on touch. This promotes it to an explicit toggle so scanning a
// changeset stays fast (read the status, skip the why) but the why is never more than one click off.
export function ReasonDisclosure({ reason }: { reason?: string | null }) {
  const [open, setOpen] = useState(false);
  if (!reason) return null;
  return (
    <>
      <button onClick={() => setOpen((v) => !v)} title="Why" style={btn}>
        {open ? "▾" : "ⓘ"}
      </button>
      {open && <div style={text}>{reason}</div>}
    </>
  );
}

const btn: React.CSSProperties = {
  background: "none", border: "none", color: "#6e7681", cursor: "pointer", fontSize: 11, padding: "0 2px",
};
const text: React.CSSProperties = {
  flexBasis: "100%", fontSize: 11, color: "#8b949e", padding: "2px 0 2px 20px", fontStyle: "italic",
};

// A REJECTED/CONFLICT outcome's reason is always shown, never hidden behind a click — a wall of red
// badges with hidden reasons (the ⓘ pattern above) is exactly what made a real "why did every
// add_instance in this turn fail" incident undiagnosable without opening dev tools. Reasoning is
// only worth a click-to-reveal when it's optional context (why an APPLIED change happened); a
// failure reason is the answer to "did this work," which nobody should have to click to see.
export function FailureReason({ reason }: { reason?: string | null }) {
  if (!reason) return null;
  return <div style={failText}>{reason}</div>;
}

const failText: React.CSSProperties = {
  flexBasis: "100%", fontSize: 11, color: "#f85149", padding: "2px 0 2px 20px",
};
