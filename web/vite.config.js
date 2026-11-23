import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import tailwindcss from "@tailwindcss/vite";

// In development and `vite preview`, /api is proxied to the Flask API, so the
// browser sees one origin (no CORS) -- the same arrangement nginx gives in Docker.
const api = process.env.API_PROXY || "http://localhost:5000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { target: "esnext", outDir: "build" },
  server: { port: 3000, proxy: { "/api": api } },
  preview: { port: 3000, proxy: { "/api": api } },
});
