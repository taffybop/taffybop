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
  plugins: [react()],
  resolve: {
    alias: [
      { find: "next/link", replacement: resolve(frontendRoot, "static/link.tsx") },
      { find: "@", replacement: frontendRoot },
    ],
  },
  css: { postcss: frontendRoot },
  build: {
    outDir: resolve(frontendRoot, "dist-static"),
    emptyOutDir: true,
    sourcemap: false,
    target: "es2022",
  },
});
