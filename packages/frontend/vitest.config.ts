import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Separate from vite.config.ts (the dev-server/build config) so the vitest-only `test` field never
// risks the working dev/build pipeline — vitest picks this file up automatically when it's present.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
});
