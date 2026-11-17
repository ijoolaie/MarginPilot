import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxy keeps the browser on same-origin `/api/*` so production (Caddy)
// and development behave identically — no CORS games, no hardcoded URLs.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // P2-02: dev server MUST stay on port 3000 — it matches APP_BASE_URL and
    // CORS_ORIGINS in .env.example. strictPort: if 3000 is taken, Vite fails
    // loudly instead of silently switching to another port (which would break
    // the documented URLs and CORS origin).
    port: 3000,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
  },
});
