import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.LINESCOPE_FRONTEND_API_TARGET ?? "http://api:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: { environment: "jsdom", restoreMocks: true },
});
