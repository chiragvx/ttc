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
