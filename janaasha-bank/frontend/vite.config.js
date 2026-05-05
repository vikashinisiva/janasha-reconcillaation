import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Flask serves the production bundle from /static/dist/, so production needs
// that base path. In dev (`npm run dev`), we want the root path and a proxy
// to Flask for /api/* calls.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/dist/" : "/",
  build: {
    outDir: "../static/dist",
    emptyOutDir: true,
    assetsDir: "assets",
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:5000",
    },
  },
}));
