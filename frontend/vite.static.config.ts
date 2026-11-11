import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { staticBuildMetadata, staticParserDefines } from "./tools/static-api-config.mjs";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const metadata = staticBuildMetadata(process.env);
const preview = metadata.deploymentMode === "preview";

export default defineConfig({
  root: resolve(frontendRoot, "static"),
  base: "/",
  publicDir: resolve(frontendRoot, "public"),
  envDir: resolve(frontendRoot, "static"),
  // Only the validated endpoint below is public. Never expose a general
  // environment prefix or build-process environment to browser code.
  envPrefix: [],
  define: preview ? {} : staticParserDefines(process.env.TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL),
  plugins: [react(), {
    name: "static-api-build-metadata",
    transformIndexHtml: {
      order: "pre",
      handler(html) {
        if (!preview) return html;
        const title = "TaffyBop — Workspace preview";
        const description = "Preview the TaffyBop document workspace. Uploads, saved history and parsing are disabled in this preview.";
        return html.replace('src="/main.tsx"', 'src="/preview.tsx"')
          .replace(/<title>[^<]*<\/title>/u, `<title>${title}</title>`)
          .replace(/<meta name="description" content="[^"]*"\s*\/>/u, `<meta name="description" content="${description}" />`)
          .replace(/<meta property="og:title" content="[^"]*"\s*\/>/u, `<meta property="og:title" content="${title}" />`)
          .replace(/<meta property="og:description" content="[^"]*"\s*\/>/u, `<meta property="og:description" content="${description}" />`);
      },
    },
    generateBundle() {
      this.emitFile({
        type: "asset",
        fileName: "static-api-config.json",
        source: JSON.stringify(metadata) + "\n",
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
    proxy: preview ? undefined : {
      "/v1": { target: "http://127.0.0.1:8042", timeout: 330_000, proxyTimeout: 330_000 },
      "/v2": { target: "http://127.0.0.1:8042", timeout: 90_000, proxyTimeout: 90_000 },
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
