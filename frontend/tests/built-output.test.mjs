import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

test("production bundle contains the TaffyBop upload workspace", async () => {
  const manifest = JSON.parse(
    await readFile(
      new URL("../dist/client/.vite/manifest.json", import.meta.url),
      "utf8",
    ),
  );
  const workspace = Object.values(manifest).find((entry) =>
    entry.src?.endsWith("app/clearleaf-workspace.tsx"),
  );

  assert.ok(workspace?.file, "workspace client entry is present");
  const bundledSource = await readFile(
    new URL(`../dist/client/${workspace.file}`, import.meta.url),
    "utf8",
  );

  assert.match(bundledSource, /TaffyBop/);
  assert.match(bundledSource, /Choose document/);
  assert.match(bundledSource, /\.png/);
  assert.match(bundledSource, /\.jpe?g/);
  assert.match(bundledSource, /\.tiff/);
  assert.match(bundledSource, /\.webp/);
  assert.match(bundledSource, /TIFF preview is unavailable/);
  assert.match(bundledSource, /Markdown/);
  assert.match(bundledSource, /JSON/);
  assert.match(bundledSource, /Document pages/);
  assert.match(bundledSource, /Previous page/);
  assert.match(bundledSource, /Next page/);
  assert.match(bundledSource, /Document JSON structure/);
  assert.match(bundledSource, /Raw JSON/);
  assert.match(bundledSource, /Collapse sections/);
  assert.match(bundledSource, /Complete document JSON/);
  assert.match(bundledSource, /markdown_full/);
  assert.match(bundledSource, /text_full/);

  // Page navigation remains shared by the preview and page-specific Markdown.
  // JSON is document-wide without adding a second Page/Document scope control.
  assert.doesNotMatch(bundledSource, /Result scope/);
  assert.doesNotMatch(bundledSource, /document-page-section/);
  assert.doesNotMatch(bundledSource, /LlamaParse/);
});
