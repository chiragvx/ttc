# packages/frontend — Vite + React + react-three-fiber

The three-zone UI (controls sidebar / 3D viewport / telemetry floor rail) over the Tier-0 WebSocket.

Hard rules:
- **Read-only viewport** — geometry is driven only by parameters; no direct vertex/mesh editing
  (protects the script integrity). Sliders are **physically bounded**; the backend rules validator
  clamps out-of-bounds and NACKs HARD_LOCK/forbidden nodes — the UI must surface the NACK, never
  silently drop it.
- Wire types in `src/types.ts` mirror `packages/transport/protocol.py` — keep them in sync.
- Tier 0 only: this talks to the analytic-telemetry WS. Kernel regen / solver results arrive on their
  own (future) message channels — do not block the UI on them.
- `npm run dev` proxies `/ws`, `/ledger`, `/export` to the FastAPI backend on :8000 (run
  `uvicorn packages.transport.app:create_app --factory` to serve it).
