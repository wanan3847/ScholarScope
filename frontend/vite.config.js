import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  publicDir: false, // Shared brand assets are installed by scripts/build_frontend.mjs.
  base: command === "build" ? "/static/ui/" : "/",
  build: {
    outDir: "../src/web/static/ui",
    emptyOutDir: true,
    chunkSizeWarningLimit: 650,
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/static/brand": "http://127.0.0.1:8765",
      "/static/pdfjs": "http://127.0.0.1:8765",
      "^/static/scope-mark\\.svg$": "http://127.0.0.1:8765",
    },
  },
}));
