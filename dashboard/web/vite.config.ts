import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run dev` proxies the API to a locally running backend (uvicorn api.app:app --port 8080).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api/live": { target: "ws://localhost:8080", ws: true },
      "/api": { target: "http://localhost:8080" },
    },
  },
});
