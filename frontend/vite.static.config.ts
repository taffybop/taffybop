import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  root: resolve(frontendRoot, "static"),
  base: "/",
  publicDir: resolve(frontendRoot, "public"),
  envDir: resolve(frontendRoot, "static"),
  envPrefix: "TAFFYBOP_STATIC_PUBLIC_",
  // Static deployments use the explicit same-origin endpoint. Define only
  // these client settings; never expose the build process environment.
  define: {
    "process.env.NEXT_PUBLIC_PARSE_API_URL": "undefined",
    "process.env.NEXT_PUBLIC_PARSE_API_TIMEOUT_MS": "undefined",
    "process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES": "undefined",
  },
  plugins: [react()],
  resolve: {
    alias: [
      { find: "next/link", replacement: resolve(frontendRoot, "static/link.tsx") },
      { find: "@", replacement: frontendRoot },
    ],
  },
  css: { postcss: frontendRoot },
  server: {
    host: "127.0.0.1",
    port: 3019,
    strictPort: true,
    proxy: {
      "/v1": { target: "http://127.0.0.1:8042", timeout: 330_000, proxyTimeout: 330_000 },
      "/healthz": { target: "http://127.0.0.1:8042" },
    },
  },
  build: {
    outDir: resolve(frontendRoot, "dist-static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
});
