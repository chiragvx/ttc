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
      "/manufacturing": "http://localhost:8001",
      "/files": "http://localhost:8001",
      "/telemetry": "http://localhost:8001",
      "/requirements": "http://localhost:8001",
      "/export": "http://localhost:8001",
      "/propose": "http://localhost:8001",
      "/chat": "http://localhost:8001",
      "/mesh": "http://localhost:8001",
      "/blueprint": "http://localhost:8001",
      "/validate": "http://localhost:8001",
      "/analyze": "http://localhost:8001",
      "/optimize": "http://localhost:8001",
      "/signoff": "http://localhost:8001",
    },
  },
});
