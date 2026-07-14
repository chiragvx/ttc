# packages/frontend — Vite + React + react-three-fiber

The three-zone UI (controls sidebar / 3D viewport / telemetry floor rail) over the Tier-0 WebSocket.

Hard rules:
- **Read-only viewport** — geometry is driven only by parameters; no direct vertex/mesh editing
  (protects the script integrity). Slider bounds are **advisory**, not a hard clamp (2026-07-04 —
  see `packages/ledger/parameter.py`/`apply.py`: a value outside the recommended range still applies,
  as `APPLIED_ADVISORY`, on copilot judgment — a user asking for 14 legs on a table gets 14, not
  "clamped to 12"). The backend rules validator still NACKs HARD_LOCK/forbidden nodes and CONFLICTs
  on a broken physical invariant (edge-distance, min-wall, cut depth/fit) — the UI must surface an
  APPLIED_ADVISORY (soft-bound heads-up) and a REJECTED/CONFLICT (hard stop) distinctly, and never
  silently drop either.
- Wire types in `src/types.ts` mirror `packages/transport/protocol.py` — keep them in sync.
- Tier 0 only: this talks to the analytic-telemetry WS. Kernel regen / solver results arrive on their
  own (future) message channels — do not block the UI on them.
- `npm run dev` proxies `/ws`, `/ledger`, `/export` to the FastAPI backend on :8000 (run
  `uvicorn packages.transport.app:create_app --factory` to serve it).
