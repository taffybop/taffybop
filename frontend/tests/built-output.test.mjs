import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const clientRoot = new URL("../dist/client/", import.meta.url);

async function readManifest() {
  return JSON.parse(await readFile(new URL(".vite/manifest.json", clientRoot), "utf8"));
}

test("production bundle ships the knowledge preparation and review workspace", async () => {
  const manifest = await readManifest();
  const studio = Object.values(manifest).find((entry) =>
    entry.src?.endsWith("app/knowledge-studio.tsx"),
  );
  assert.ok(studio?.file, "Knowledge Studio client entry is present");
  const source = await readFile(new URL(studio.file, clientRoot), "utf8");

  for (const label of [
    "Knowledge Studio",
    "Browse files",
    "Review text",
    "Extracted page text",
    "Apply changes",
    "Search chunks",
    "Filter source",
    "Chunk size in words",
    "Save pack",
    "Open pack",
    "Markdown",
    "JSONL",
  ]) {
    assert.ok(source.includes(label), `built workspace includes ${label}`);
  }
  assert.ok(source.includes("/samples/customer-support-handbook.pdf"), "sample action loads the packaged PDF");
  assert.doesNotMatch(source, /Coming soon|parse_service_unreachable|\/api\/parse/u);
});

test("browser extraction and its PDF worker are packaged for local processing", async () => {
  const manifest = await readManifest();
  const sources = await Promise.all(Object.values(manifest)
    .filter((entry) => entry.file.endsWith(".js"))
    .map((entry) => readFile(new URL(entry.file, clientRoot), "utf8")));
  const clientSource = sources.join("\n");
  assert.ok(clientSource.includes("/pdf.worker.min.mjs"), "PDF.js references the same-origin worker");
  assert.ok(clientSource.includes("getTextContent"), "PDF selectable-text extraction is shipped");
  assert.ok(clientSource.includes("password protected"), "password-protected PDFs have an actionable error");
  assert.ok(clientSource.includes("Run OCR first"), "scanned PDFs have an honest unsupported-input explanation");

  const worker = await readFile(new URL("pdf.worker.min.mjs", clientRoot));
  const checkedInWorker = await readFile(new URL("../public/pdf.worker.min.mjs", import.meta.url));
  assert.ok(worker.byteLength > 100_000, "PDF worker is a real bundled asset");
  assert.deepEqual(worker, checkedInWorker, "production contains the complete PDF worker");
  const sample = await readFile(new URL("samples/customer-support-handbook.pdf", clientRoot));
  assert.equal(sample.subarray(0, 5).toString(), "%PDF-", "public sample is a PDF asset");
});

test("production home, studio and documents open the durable library; legacy remains separate", async () => {
  const serverSource = await readFile(new URL("../dist/server/index.js", import.meta.url), "utf8");
  for (const page of ["Home", "StudioPage", "DocumentsPage"]) {
    assert.match(
      serverSource,
      new RegExp(`function ${page}\\(\\) \\{[^}]*\\bDocumentsWorkspace\\b`, "u"),
      `${page} renders the persistent document workspace`,
    );
  }
  assert.ok(serverSource.includes("/studio"));
  assert.ok(serverSource.includes("/knowledge"));
  assert.match(serverSource, /function LegacyPage\(\) \{[^}]*\bLlamaParseWorkspace\b/u);
  assert.doesNotMatch(serverSource, /Extract is still chasing its yarn|Coming soon/u);
});

test("production product workspace ships saved records, simulation labels and owned artifact downloads", async () => {
  const manifest = await readManifest();
  const workspace = Object.values(manifest).find((entry) => entry.src?.endsWith("app/documents-workspace.tsx"));
  assert.ok(workspace?.file, "Persistent document workspace client entry is present");
  const source = await readFile(new URL(workspace.file, clientRoot), "utf8");
  for (const label of ["Upload document", "Saved parsing run", "Live parsing is unavailable", "Simulation — not a live parse", "Actual provider credits:", "Original raw JSON", "Result page occurrence", "Download original raw JSON"]) {
    assert.ok(source.includes(label), `Product workspace includes ${label}`);
  }
  assert.ok(source.includes("/v2/documents"), "Owned library API is bundled");
  assert.ok(source.includes("/v2/artifacts/"), "Original downloads use the authenticated artifact route");
  assert.ok(source.includes("SHA-256"), "Source preview verifies artifact integrity");
  assert.ok(source.includes("cancellation_requested_at"), "Cancellation request remains distinct from confirmation");
});


test("production bundle includes LlamaParse upload, output views, and exact API exports", async () => {
  const manifest = await readManifest();
  const studio = Object.values(manifest).find((entry) =>
    entry.src?.endsWith("app/llamaparse-workspace.tsx"),
  );
  assert.ok(studio?.file, "LlamaParse workspace client entry is present");
  const source = await readFile(new URL(studio.file, clientRoot), "utf8");
  for (const label of [
    "Powered by LlamaParse", "Choose a document", "Choose a parsing mode",
    "Parse document", "Source document", "Markdown", "Text", "Raw JSON",
    "Copy result", "Download result", "Original API response",
  ]) {
    assert.ok(source.includes(label), `LlamaParse workspace includes ${label}`);
  }
  assert.ok(source.includes("rawBytes"), "download uses captured response bytes");
  assert.ok(source.includes("rawText"), "copy and raw view use captured response text");
});
