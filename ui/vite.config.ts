import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const api = "http://127.0.0.1:8000";

// Dev server proxies the API; production build is served by FastAPI from ui/dist.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/events": api, "/state": api, "/stream": api } },
});
