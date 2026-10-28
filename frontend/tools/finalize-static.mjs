import { mkdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const output = fileURLToPath(new URL("../dist-static/", import.meta.url));
const html = await readFile(resolve(output, "index.html"), "utf8");
for (const route of ["studio", "privacy", "knowledge"]) {
  await mkdir(resolve(output, route), { recursive: true });
  await writeFile(resolve(output, route, "index.html"), html);
}
for (const route of ["parse", "extract"]) {
  await mkdir(resolve(output, route), { recursive: true });
  await writeFile(resolve(output, route, "index.html"), '<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url=/studio"><title>Open Document Studio — TaffyBop</title></head><body><a href="/studio">Open Document Studio</a></body></html>\n');
}
await writeFile(resolve(output, "404.html"), html);
await writeFile(resolve(output, "_redirects"), "/parse /studio 301\n/extract /studio 301\n/* /index.html 200\n");
await writeFile(resolve(output, "robots.txt"), "User-agent: *\nAllow: /\n");
console.log("UI routes ready: /, /studio, /knowledge, /privacy, /parse, /extract. Serve alongside /v1/parse.");
