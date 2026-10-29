import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { staticApiEndpoint, staticParserDefines } from "./tools/static-api-config.mjs";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const publicApiUrl = staticApiEndpoint(process.env.TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL);

export default defineConfig({
  root: resolve(frontendRoot, "static"),
  base: "/",
  publicDir: resolve(frontendRoot, "public"),
  envDir: resolve(frontendRoot, "static"),
  // Only the validated endpoint below is public. Never expose a general
  // environment prefix or build-process environment to browser code.
  envPrefix: [],
  define: staticParserDefines(process.env.TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL),
  plugins: [react(), {
    name: "static-api-build-metadata",
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "static-api-config.json",
        source: JSON.stringify({ schemaVersion: 1, parseApiUrl: publicApiUrl }) + "\n",
      });
    },
  }],
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
