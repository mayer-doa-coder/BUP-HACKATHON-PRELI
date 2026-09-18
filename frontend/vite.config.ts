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
// runs somewhere other than port 8000.
//
// The default target is 127.0.0.1, not "localhost", and that is deliberate. Node resolves
// "localhost" to ::1 (IPv6) before 127.0.0.1, while a dev server started with
// `uvicorn --host 127.0.0.1` listens on IPv4 only. If anything else is bound to the IPv6
// side of the port - a published Docker container is the usual culprit - the proxy silently
// forwards to *that* instead, and the UI shows errors coming from a service you are not
// editing. Pinning the literal IPv4 address removes the ambiguity.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const backendTarget = env.VITE_BACKEND_URL || "http://127.0.0.1:8000";

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
