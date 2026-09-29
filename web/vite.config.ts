import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Локальная разработка: API запускается отдельно (uvicorn api.main:app --port 8000),
// dev-сервер Vite проксирует на него /api и /media — как nginx в бою.
const API = process.env.API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": API,
      "/media": API,
    },
  },
  build: {
    sourcemap: false,
  },
  test: {
    environment: "node",
  },
});
