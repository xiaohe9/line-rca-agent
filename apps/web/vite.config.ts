import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API is proxied rather than called cross-origin: it keeps the browser on one origin
// and removes CORS from the list of things that can silently break the SSE stream.
const API_TARGET = process.env["LRC_API_TARGET"] ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // The default 5s assumes an idle machine. These tests routinely take under 200ms, but
    // module import on a loaded Windows box (Docker Desktop plus a browser) has been
    // measured at 60s+ for a cold run, which turns a healthy suite into a red one.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
