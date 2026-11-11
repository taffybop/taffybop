import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  createLlamaParseJob, getLlamaParseConfig, getLlamaParseJob, getLlamaParseJobError,
  getLlamaParsePages, getLlamaParseStatus, LlamaParseApiError, pollLlamaParseJob,
  validateLlamaParseFile,
} from "../lib/llamaparse-api.ts";
import type { LlamaParseConfig } from "../lib/llamaparse-api.ts";

// Contract fixtures only: no provider calls, API credentials or accuracy claims.
const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
const config: LlamaParseConfig = {
  configured: true, default_mode: "cost_effective", max_upload_bytes: 1024, max_pages: 20,
  modes: [
    { id: "cost_effective", label: "Cost Effective", description: "Simple documents", credits_per_page: 3 },
    { id: "agentic", label: "Agentic", description: "Complex layouts", credits_per_page: 10 },
    { id: "agentic_plus", label: "Agentic Plus", description: "Most detailed", credits_per_page: 45 },
  ],
};
const pdf = () => new File(["%PDF-1.7 source"], "sample.pdf", { type: "application/pdf" });
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });
const receipt = { job_id: "job-1", mode: "cost_effective", status: "PENDING", page_count: 2, estimated_credits: 6 };

test("config uses the same-origin endpoint and retains server-owned choices and limits", async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/v1/llamaparse/config");
    assert.equal(init?.method, "GET");
    assert.equal(init?.cache, "no-store");
    return json({ ...config, max_pages: 11, default_mode: "agentic" });
  };
  const actual = await getLlamaParseConfig();
  assert.equal(actual.max_pages, 11);
  assert.equal(actual.default_mode, "agentic");
  assert.deepEqual(actual.modes, config.modes);
});

test("missing server key is a valid setup state, not a reason to ask for a browser key", async () => {
  globalThis.fetch = async () => json({ ...config, configured: false });
  const actual = await getLlamaParseConfig();
  assert.equal(actual.configured, false);
  globalThis.fetch = async () => { assert.fail("No POST may occur without configured server credentials"); };
  await assert.rejects(createLlamaParseJob(pdf(), "cost_effective", actual), /LlamaCloud key not configured on the server/);
});

test("disabled submission is separate from server credential configuration", async () => {
  globalThis.fetch = async () => json({ ...config, submission_enabled: false });
  const actual = await getLlamaParseConfig();
  assert.equal(actual.configured, true);
  assert.equal(actual.submission_enabled, false);
  globalThis.fetch = async () => { assert.fail("No POST may occur while submission is disabled"); };
  await assert.rejects(createLlamaParseJob(pdf(), "cost_effective", actual),
    (error: unknown) => error instanceof LlamaParseApiError && error.code === "submission_unavailable"
      && error.message === "Parsing is unavailable in this session");
});

test("config rejects unknown default, duplicate mode IDs, empty modes and malformed credit declarations", async () => {
  for (const invalid of [
    { ...config, default_mode: "not-offered" },
    { ...config, modes: [config.modes[0], config.modes[0]] },
    { ...config, modes: [] },
    { ...config, modes: [{ ...config.modes[0], credits_per_page: -3 }] },
    { ...config, max_upload_bytes: 0 },
    { ...config, submission_enabled: "false" },
  ]) {
    globalThis.fetch = async () => json(invalid);
    await assert.rejects(getLlamaParseConfig(), (error: unknown) => error instanceof LlamaParseApiError && error.code === "invalid_config");
  }
});

test("submission sends only the original file and selected mode, without browser credentials", async () => {
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls += 1;
    assert.equal(url, "/v1/llamaparse/jobs");
    assert.equal(init?.method, "POST");
    assert.deepEqual(init?.headers, { accept: "application/json" });
    assert.ok(init.body instanceof FormData);
    assert.deepEqual([...init.body.keys()].sort(), ["file", "mode"]);
    assert.equal(init.body.get("mode"), "cost_effective");
    const file = init.body.get("file") as File;
    assert.equal(file.name, "sample.pdf");
    assert.equal(await file.text(), "%PDF-1.7 source");
    return json(receipt, 202);
  };
  assert.deepEqual(await createLlamaParseJob(pdf(), "cost_effective", config), receipt);
  assert.equal(calls, 1);
});

test("submission rejects nonaccepted or mismatched receipts and keeps absent estimates distinct from zero", async () => {
  for (const [body, status] of [[receipt, 200], [{ ...receipt, mode: "agentic" }, 202], [{ ...receipt, estimated_credits: undefined }, 202]] as const) {
    globalThis.fetch = async () => json(body, status);
    await assert.rejects(createLlamaParseJob(pdf(), "cost_effective", config), (error: unknown) => error instanceof LlamaParseApiError && error.code === "invalid_job");
  }
  globalThis.fetch = async () => json({ ...receipt, page_count: null, estimated_credits: null }, 202);
  assert.equal((await createLlamaParseJob(pdf(), "cost_effective", config)).estimated_credits, null);
});

test("validation accepts PDF/PNG/JPEG and rejects mismatches, empty files, unsupported images and over-limit uploads", () => {
  assert.doesNotThrow(() => validateLlamaParseFile(pdf(), 1024));
  assert.doesNotThrow(() => validateLlamaParseFile(new File(["png"], "source.PNG", { type: "image/png" }), 3));
  assert.doesNotThrow(() => validateLlamaParseFile(new File(["jpg"], "source.jpeg", { type: "image/jpeg" }), 3));
  for (const file of [
    new File(["x"], "image.webp", { type: "image/webp" }),
    new File(["x"], "image.png", { type: "image/jpeg" }),
    new File([], "empty.pdf", { type: "application/pdf" }),
    new File(["1234"], "large.pdf", { type: "application/pdf" }),
  ]) assert.throws(() => validateLlamaParseFile(file, 3), LlamaParseApiError);
});

test("unsupported mode fails before any upload", async () => {
  globalThis.fetch = async () => { assert.fail("No upload for an unsupported mode"); };
  await assert.rejects(createLlamaParseJob(pdf(), "invented", config), /offered by this server/);
});

test("raw provider response preserves byte order, BOM, whitespace, UTF-8, large integer spelling and unknown fields", async () => {
  const raw = '\uFEFF {\n "job":{"status":"COMPLETED"}, "future":{"id":9007199254740993,"amount":1.2300,"note":"café ₹"},"markdown":{"pages":[{"page_number":1,"markdown":"# Heading\\n"}]}\n}\n';
  const bytes = new TextEncoder().encode(raw);
  globalThis.fetch = async () => new Response(new ReadableStream<Uint8Array>({
    start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close(); },
  }), { headers: { "content-type": "application/json; charset=utf-8" } });
  const result = await getLlamaParseJob("job-1");
  assert.equal(result.rawText, raw);
  assert.deepEqual(result.rawBytes, bytes);
  assert.equal(result.contentType, "application/json; charset=utf-8");
  assert.notEqual(JSON.stringify(result.data), raw);
  assert.ok(result.data.future);
});

test("job IDs are path encoded and GET carries no uploaded file", async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(url, "/v1/llamaparse/jobs/a%2Fb%3Fmode%3Dother");
    assert.equal(init?.method, "GET");
    assert.equal(init?.body, undefined);
    return json({ job: { status: "RUNNING" } });
  };
  await getLlamaParseJob("a/b?mode=other");
});

test("status is read exclusively from job.status, with unsupported declarations rejected", () => {
  assert.equal(getLlamaParseStatus({ status: "FAILED", job: { status: "COMPLETED" } }), "COMPLETED");
  assert.throws(() => getLlamaParseStatus({ status: "COMPLETED" }), /unsupported job status/);
  assert.throws(() => getLlamaParseStatus({ job: { status: "SUCCESS" } }), /unsupported job status/);
  assert.equal(getLlamaParseJobError({ job: { status: "FAILED", error_message: "Provider quota exhausted" } }), "Provider quota exhausted");
});

test("format pages preserve provider order, whitespace, empty values and repeated page numbers without synthesizing another format", () => {
  const data = { markdown: { pages: [
    { page_number: 3, markdown: "  # Heading\r\n\r\n| x | 2 |\n" },
    { page_number: 1, markdown: "" },
    { page_number: 1, markdown: "Repeated page\n" },
  ] }, items: { pages: [{ text: "Not a text response" }] } };
  assert.deepEqual(getLlamaParsePages(data, "markdown"), { kind: "available", pages: [
    { pageNumber: 3, content: "  # Heading\r\n\r\n| x | 2 |\n" },
    { pageNumber: 1, content: "" },
    { pageNumber: 1, content: "Repeated page\n" },
  ] });
  assert.deepEqual(getLlamaParsePages(data, "text"), { kind: "not_returned", pages: [] });
});

test("partially malformed format does not silently omit pages or coerce values", () => {
  for (const output of [{ pages: [{ page_number: 1, text: "ok" }, { page_number: 2 }] }, { pages: [{ page_number: 1, text: 42 }] }, { pages: "unexpected" }]) {
    assert.deepEqual(getLlamaParsePages({ text: output }, "text"), { kind: "unsupported", pages: [] });
  }
  assert.deepEqual(getLlamaParsePages({ text: { pages: [] } }, "text"), { kind: "empty", pages: [] });
});

test("polling advances through provider statuses using GET only and preserves the terminal raw response", async () => {
  const statuses = ["PENDING", "RUNNING", "COMPLETED"];
  let calls = 0;
  const seen: string[] = [];
  globalThis.fetch = async (_url, init) => {
    assert.equal(init?.method, "GET");
    return json({ job: { status: statuses[calls++] }, text: { pages: [{ page_number: 1, text: "Provider text\n" }] } });
  };
  const result = await pollLlamaParseJob("job-1", { intervalMs: 0, onResponse: (value) => seen.push(getLlamaParseStatus(value.data)) });
  assert.deepEqual(seen, statuses);
  assert.equal(calls, 3);
  assert.equal(getLlamaParseStatus(result.data), "COMPLETED");
});

test("provider failure and cancellation are terminal and still return the raw response", async () => {
  for (const status of ["FAILED", "CANCELLED"]) {
    let calls = 0;
    globalThis.fetch = async () => { calls += 1; return json({ job: { status, error_message: "Stopped by provider" } }); };
    const result = await pollLlamaParseJob("job-1", { intervalMs: 0 });
    assert.equal(getLlamaParseStatus(result.data), status);
    assert.equal(calls, 1);
  }
});

test("network or quota failure stops polling; checking again uses the same job and never repeats POST", async () => {
  const methods: string[] = [];
  globalThis.fetch = async (url, init) => {
    methods.push(init?.method ?? "");
    assert.equal(url, "/v1/llamaparse/jobs/job-1");
    throw new TypeError("Network offline");
  };
  await assert.rejects(pollLlamaParseJob("job-1"), (error: unknown) => error instanceof LlamaParseApiError && error.code === "network_error");
  globalThis.fetch = async (url, init) => {
    methods.push(init?.method ?? "");
    assert.equal(url, "/v1/llamaparse/jobs/job-1");
    return json({ error: { code: "quota_exceeded", message: "LlamaCloud quota exceeded" } }, 429);
  };
  await assert.rejects(pollLlamaParseJob("job-1"), (error: unknown) => error instanceof LlamaParseApiError && error.code === "quota_exceeded" && error.status === 429 && error.message === "LlamaCloud quota exceeded");
  assert.deepEqual(methods, ["GET", "GET"]);
});

test("stopping locally aborts the wait without requesting provider cancellation or more polls", async () => {
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = async (_url, init) => { calls += 1; assert.equal(init?.method, "GET"); return json({ job: { status: "RUNNING" } }); };
  await assert.rejects(pollLlamaParseJob("job-1", { signal: controller.signal, onResponse: () => controller.abort() }), (error: unknown) => error instanceof Error && error.name === "AbortError");
  assert.equal(calls, 1);
});

test("unknown provider status reaches raw-response callback before polling fails", async () => {
  let raw = "";
  globalThis.fetch = async () => new Response(' {"job":{"status":"NEW_STATE"},"extra":1}\n');
  await assert.rejects(pollLlamaParseJob("job-1", { onResponse: (response) => { raw = response.rawText; } }), /unsupported job status/);
  assert.equal(raw, ' {"job":{"status":"NEW_STATE"},"extra":1}\n');
});

test("streamed response cap cancels reading and surfaces a typed error", async () => {
  let cancelled = false;
  globalThis.fetch = async () => new Response(new ReadableStream<Uint8Array>({
    pull(controller) { controller.enqueue(new Uint8Array(10)); },
    cancel() { cancelled = true; },
  }));
  await assert.rejects(getLlamaParseJob("job-1", { maxResponseBytes: 12 }), (error: unknown) => error instanceof LlamaParseApiError && error.code === "response_too_large");
  assert.equal(cancelled, true);
});

test("invalid JSON and invalid UTF-8 do not produce invented output", async () => {
  for (const body of ["<html>Server unavailable</html>", new Uint8Array([0xff, 0xfe])]) {
    globalThis.fetch = async () => new Response(body);
    await assert.rejects(getLlamaParseJob("job-1"), (error: unknown) => error instanceof LlamaParseApiError && error.code === "invalid_response");
  }
});
