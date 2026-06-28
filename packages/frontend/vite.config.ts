import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API + WebSocket to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8001", ws: true },
      "/ledger": "http://localhost:8001",
      "/export": "http://localhost:8001",
      "/propose": "http://localhost:8001",
      "/mesh": "http://localhost:8001",
    },
  },
});
