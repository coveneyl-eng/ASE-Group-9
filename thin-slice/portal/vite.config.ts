import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, proxy API + WebSocket calls to the NGINX gateway.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "https://localhost:8444", secure: false },
      "/ws": { target: "wss://localhost:8444", ws: true, secure: false },
    },
  },
});
