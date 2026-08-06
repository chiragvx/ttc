import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API + WebSocket to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8001", ws: true },
      "/ledger": "http://localhost:8001",
      "/params": "http://localhost:8001",
      "/subsystems": "http://localhost:8001",
      "/instances": "http://localhost:8001",
      "/feature_ops": "http://localhost:8001",
      "/instance_ops": "http://localhost:8001",
      // 2026-07-19 — connection_ops/coupling_ops (Engineering Graph Phases 1b/2b) and
      // /manufacturing/manifest (Phase 6) were added to the backend but never added here, so every
      // one of them silently 404'd in local dev (`npm run dev`) despite working fine under
      // docker-compose, which serves everything same-origin and needs no proxy at all — found live
      // testing a multi-part assembly whose battery-mount coupling came back
      // "coupling endpoint unavailable (HTTP 404)".
      "/connection_ops": "http://localhost:8001",
      "/coupling_ops": "http://localhost:8001",
      // 2026-08-04 — same silent-404 gap as the connection_ops/coupling_ops incident above, found live
      // while verifying the new region_ops feature: fit_ops and join_annotation_ops were already
      // missing here too (pre-existing, not new), region_ops was missing because it's brand new.
      "/fit_ops": "http://localhost:8001",
      "/join_annotation_ops": "http://localhost:8001",
      "/region_ops": "http://localhost:8001",
      "/manufacturing": "http://localhost:8001",
      // 2026-08-05 — same silent-404 gap as the connection_ops/coupling_ops and fit_ops/
      // join_annotation_ops/region_ops incidents above (this is the THIRD time): a new backend route
      // (/model_capabilities, vision-in-the-loop) shipped without being added here.
      "/model_capabilities": "http://localhost:8001",
      // 2026-08-06 — same silent-404 gap, FOURTH time: /envelope_ops and /envelope/status
      // (gearbox-housing-generation initiative, Phase 3) shipped without being added here — caught
      // live post-restart: GET /envelope_ops through the proxy returned 200 (the SPA index.html
      // fallback for an unmatched path), not the expected 405 Method Not Allowed a real proxied
      // POST-only route gives on GET, meaning the whole Phase 4/5 chat-UI wiring was unreachable in
      // local dev despite being fully correct server-side and in every test.
      "/envelope_ops": "http://localhost:8001",
      "/envelope": "http://localhost:8001",
      "/files": "http://localhost:8001",
      "/telemetry": "http://localhost:8001",
      "/requirements": "http://localhost:8001",
      "/export": "http://localhost:8001",
      "/propose": "http://localhost:8001",
      "/chat": "http://localhost:8001",
      "/mesh": "http://localhost:8001",
      "/blueprint": "http://localhost:8001",
      "/report": "http://localhost:8001",
      "/validate": "http://localhost:8001",
      "/analyze": "http://localhost:8001",
      "/optimize": "http://localhost:8001",
      "/signoff": "http://localhost:8001",
    },
  },
});
