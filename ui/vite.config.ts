/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: api, ws: true },
      "/health": { target: api },
    },
  },
  test: { environment: "node" },
});
