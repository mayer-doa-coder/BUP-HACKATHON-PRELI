import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// GridWise frontend — a standalone demo UI for the /health and /optimize-energy
// endpoints. This file never touches the backend; it only points the dev server
// at it.
//
// The backend does not (and, per this project's rules, should not on our side)
// send CORS headers, so calling it directly from a page served on a different
// origin would be blocked by the browser. The dev proxy below sidesteps that
// entirely: the browser only ever talks to the Vite origin, and Vite forwards
// `/api/*` to the real service server-side, where CORS does not apply.
//
// Override the target with VITE_BACKEND_URL (in .env.local) if the service
// runs somewhere other than localhost:8000.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget = env.VITE_BACKEND_URL || "http://localhost:8000";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: backendTarget,
          changeOrigin: true,
          rewrite: (path: string) => path.replace(/^\/api/, ""),
        },
      },
    },
  };
});
