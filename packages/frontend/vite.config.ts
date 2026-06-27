import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies the API + WebSocket to the FastAPI backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
      "/ledger": "http://localhost:8000",
      "/export": "http://localhost:8000",
    },
  },
});
