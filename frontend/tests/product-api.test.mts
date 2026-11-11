import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  cancelProductJob, getProductConfig, getProductDocument, getProductHistory, getProductJob,
  getProductRawPreview, getProductResult, getProductSource, isTerminalProductJob,
  listProductDocuments, ProductApiError, productArtifactUrl, uploadProductDocument,
} from "../lib/product-api.ts";
import type { ProductArtifact, ProductJob } from "../lib/product-api.ts";

// Authored protocol fixtures only; none are provider outputs or accuracy evidence.
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const docId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const jobId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const resultId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const artifactId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const sourceId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const source: ProductArtifact = { id: sourceId, sha256: "0".repeat(64), size_bytes: 9, media_type: "application/pdf" };
const doc = { schema_version: "2.0", id: docId, display_name: "Authored.pdf", page_count: 2, state: "active", source, created_at: "2026-11-11T00:00:00Z", expires_at: null };
const settings = { provider: "llamaparse", adapter_version: "llamaparse-v2/1", mode: "cost_effective", requested_version: "2026-09-28", max_pages: 10 };
const usage = { estimated_credits: "3", estimate_price_version: "authored", actual_credits: null, reconciliation: "pending" };
const job = { schema_version: "2.0", id: jobId, document_id: docId, status: "queued", settings, created_at: "2026-11-11T00:00:00Z", updated_at: "2026-11-11T00:00:00Z", result_id: null, raw_response: null, cancellation_requested_at: null, cancellation_confirmed: false, usage, error: null };
const config = { schema_version: "2.0", enabled: true, identity_mode: "local_development", uploads_enabled: true, parse_enabled: false, disabled_reason: "Live parsing unavailable", default_mode: "cost_effective", modes: [{ id: "cost_effective", label: "Cost-effective" }] };
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
const invalidResponse = (failure: unknown) => failure instanceof ProductApiError && failure.code === "invalid_response";

test("product config requires explicit local identity and disabled live parsing", async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/v2/config"); assert.equal(init?.cache, "no-store"); assert.equal(init?.credentials, "same-origin");
    return json(config);
  };
  assert.equal((await getProductConfig()).parse_enabled, false);
  for (const invalid of [{ ...config, identity_mode: "anonymous" }, { ...config, parse_enabled: true }, { ...config, schema_version: "1.0" }, { ...config, modes: [config.modes[0], config.modes[0]] }]) {
    globalThis.fetch = async () => json(invalid); await assert.rejects(getProductConfig(), invalidResponse);
  }
});

test("owned library forwards only bounded-list cursor and preserves server order", async () => {
  globalThis.fetch = async (url) => {
    assert.equal(url, "/v2/documents?limit=25&cursor=opaque%2B%2F%3D");
    return json({ schema_version: "2.0", documents: [doc], next_cursor: "next" });
  };
  assert.deepEqual((await listProductDocuments("opaque+/=")).documents, [doc]);
});

test("upload persists one multipart file without owner, mode or provider credentials", async () => {
  const file = new File(["%PDF-data"], "Authored.pdf", { type: "application/pdf" });
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/v2/documents"); assert.equal(init?.method, "POST");
    assert.ok(init?.body instanceof FormData); assert.deepEqual([...init.body.keys()], ["file"]);
    assert.equal((init.body.get("file") as File).name, file.name);
    return json(doc, 201);
  };
  assert.equal((await uploadProductDocument(file)).id, docId);
});

test("resource URLs reject path input before fetch and canonicalize UUIDs", async () => {
  globalThis.fetch = async (url) => { assert.equal(url, `/v2/documents/${docId}`); return json(doc); };
  assert.equal((await getProductDocument(docId.toUpperCase())).id, docId);
  globalThis.fetch = async () => { assert.fail("Invalid IDs must never issue a request"); };
  await assert.rejects(getProductDocument("../other-owner"), (failure: unknown) => failure instanceof ProductApiError && failure.code === "invalid_id");
  assert.throws(() => productArtifactUrl("//example.com/private"));
  assert.equal(productArtifactUrl(artifactId, true), `/v2/artifacts/${artifactId}/content?download=1`);
});

test("resource response identity and history document identity must match the selection", async () => {
  globalThis.fetch = async () => json({ ...doc, id: sourceId });
  await assert.rejects(getProductDocument(docId), invalidResponse);
  globalThis.fetch = async () => json({ schema_version: "2.0", jobs: [{ job: { ...job, document_id: sourceId }, evidence_kind: "simulation" }] });
  await assert.rejects(getProductHistory(docId), invalidResponse);
});

test("history provenance is explicit; unknown evidence cannot become a live success claim", async () => {
  for (const kind of ["simulation", "unverified"]) {
    globalThis.fetch = async () => json({ schema_version: "2.0", jobs: [{ job, evidence_kind: kind }] });
    assert.equal((await getProductHistory(docId)).jobs[0].evidence_kind, kind);
  }
  globalThis.fetch = async () => json({ schema_version: "2.0", jobs: [{ job, evidence_kind: "live" }] });
  await assert.rejects(getProductHistory(docId), invalidResponse);
});

test("unknown usage remains null and finite Decimal exponent strings survive without rounding", async () => {
  globalThis.fetch = async () => json({ ...job, usage: { ...usage, estimated_credits: "1E+2" } });
  const unknown = await getProductJob(jobId); assert.equal(unknown.usage.actual_credits, null); assert.equal(unknown.usage.estimated_credits, "1E+2");
  globalThis.fetch = async () => json({ ...job, usage: { ...usage, actual_credits: "1E-7", reconciliation: "observed" } });
  assert.equal((await getProductJob(jobId)).usage.actual_credits, "1E-7");
});

test("job cancellation request and terminal confirmation remain independent", async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, `/v2/jobs/${jobId}/cancel`); assert.equal(init?.method, "POST");
    return json({ ...job, status: "submission_unknown", cancellation_requested_at: "2026-11-11T00:01:00Z" }, 202);
  };
  const requested = await cancelProductJob(jobId);
  assert.equal(requested.status, "submission_unknown"); assert.ok(requested.cancellation_requested_at);
  assert.equal(requested.cancellation_confirmed, false); assert.equal(isTerminalProductJob(requested), false);
  for (const status of ["succeeded", "failed", "cancelled"]) assert.equal(isTerminalProductJob({ ...requested, status } as ProductJob), true);
});

test("unknown job states and success without a persisted result are rejected", async () => {
  for (const invalid of [{ ...job, status: "complete" }, { ...job, status: "succeeded" }, { ...job, usage: { ...usage, actual_credits: "0" } }]) {
    globalThis.fetch = async () => json(invalid); await assert.rejects(getProductJob(jobId), invalidResponse);
  }
});

test("normalized formats preserve separate order, repeated page IDs and exact empty/whitespace strings", async () => {
  const markdown = { state: "available", pages: [{ page_number: 2, content: "  second\n" }, { page_number: 1, content: "\tfirst " }, { page_number: 2, content: "" }] };
  const text = { state: "available", pages: [{ page_number: 1, content: "different\n" }] };
  globalThis.fetch = async () => json({ schema_version: "2.0", id: resultId, document_id: docId, job_id: jobId, settings, provider_version: null, raw: { ...source, id: artifactId, media_type: "application/json" }, markdown, text, warnings: ["Authored simulation"], usage });
  const result = await getProductResult(resultId); assert.deepEqual(result.markdown, markdown); assert.deepEqual(result.text, text);
  assert.equal(result.provider_version, null);
});

test("raw preview preserves original whitespace, property order, BOM and newline", async () => {
  const raw = '\uFEFF{ "z": 1, "a": [2, 1] }\n\n';
  globalThis.fetch = async () => new Response(new TextEncoder().encode(raw));
  assert.equal(await getProductRawPreview(artifactId), raw);
});

test("large raw previews are bounded while original-download URL remains available", async () => {
  globalThis.fetch = async () => new Response("{}", { headers: { "content-length": String(1024 * 1024 + 1) } });
  await assert.rejects(getProductRawPreview(artifactId), (failure: unknown) => failure instanceof ProductApiError && failure.code === "response_too_large");
  assert.ok(productArtifactUrl(artifactId, true).endsWith("?download=1"));
});

test("source preview verifies exact size and SHA256 before exposing a Blob", async () => {
  const bytes = new TextEncoder().encode("%PDF-data");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const sha256 = Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  globalThis.fetch = async () => new Response(bytes);
  const blob = await getProductSource({ ...source, sha256 }); assert.equal(blob.type, source.media_type);
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes);
  await assert.rejects(getProductSource({ ...source, sha256: "f".repeat(64) }), invalidResponse);
  await assert.rejects(getProductSource({ ...source, size_bytes: 8, sha256 }), invalidResponse);
});

test("sanitized server errors are preserved and HTML fallback does not masquerade as success", async () => {
  globalThis.fetch = async () => json({ error: { code: "not_found", message: "Resource not found." } }, 404);
  await assert.rejects(getProductJob(jobId), (failure: unknown) => failure instanceof ProductApiError && failure.status === 404 && failure.message === "Resource not found.");
  globalThis.fetch = async () => new Response("<!doctype html>SPA fallback");
  await assert.rejects(getProductConfig(), invalidResponse);
});

test("an aborted selection never starts a fetch or receives a network-error replacement", async () => {
  const controller = new AbortController(); controller.abort();
  globalThis.fetch = async () => { assert.fail("No fetch is allowed after selection abort"); };
  await assert.rejects(getProductJob(jobId, { signal: controller.signal }), (failure: unknown) => failure instanceof DOMException && failure.name === "AbortError");
});
