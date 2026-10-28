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

test("production landing offers the live studio instead of the former coming-soon product", async () => {
  const serverSource = await readFile(new URL("../dist/server/index.js", import.meta.url), "utf8");
  assert.ok(serverSource.includes("Prepare a document"));
  assert.ok(serverSource.includes("/studio"));
  assert.ok(serverSource.includes("No sign-up. No API key."));
  assert.doesNotMatch(serverSource, /Extract is still chasing its yarn|Coming soon/u);
});
