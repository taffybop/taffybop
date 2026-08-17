import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import { POST } from "../app/api/parse/route.ts";

const originalFetch = globalThis.fetch;
const originalParserUrl = process.env.PARSE_API_URL;

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalParserUrl === undefined) {
    delete process.env.PARSE_API_URL;
  } else {
    process.env.PARSE_API_URL = originalParserUrl;
  }
});

test("proxy forwards the upload and requested output format", async () => {
  process.env.PARSE_API_URL = "https://parser.example/";
  let requestUrl = "";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return new Response("# Parsed", {
      status: 201,
      statusText: "Created",
      headers: { "content-type": "text/markdown; charset=utf-8" },
    });
  };

  const request = new Request(
    "http://frontend.test/api/parse?output_format=markdown",
    {
      method: "POST",
      headers: {
        "content-type": "multipart/form-data; boundary=demo",
        accept: "text/markdown",
      },
      body: "--demo--",
    },
  );
  const response = await POST(request);

  assert.equal(response.status, 201);
  assert.match(response.headers.get("content-type") ?? "", /text\/markdown/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(await response.text(), "# Parsed");
  assert.equal(
    requestUrl,
    "https://parser.example/v1/parse?output_format=markdown",
  );
  assert.equal(requestInit?.method, "POST");
  assert.deepEqual(requestInit?.headers, {
    "content-type": "multipart/form-data; boundary=demo",
    accept: "text/markdown",
  });
  assert.ok(requestInit?.body instanceof ArrayBuffer);
});

test("proxy forwards an image multipart body without changing its contract", async () => {
  process.env.PARSE_API_URL = "https://parser.example";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (_input, init) => {
    requestInit = init;
    return new Response(
      JSON.stringify({
        schema_version: "1.0",
        document: { page_count: 1 },
        pages: [],
        processing: {},
      }),
      {
        status: 200,
        headers: { "content-type": "application/json" },
      },
    );
  };

  const form = new FormData();
  form.append(
    "file",
    new File(["png-payload"], "scan.png", { type: "image/png" }),
  );
  const response = await POST(
    new Request("http://frontend.test/api/parse?output_format=json", {
      method: "POST",
      headers: { accept: "application/json" },
      body: form,
    }),
  );

  assert.equal(response.status, 200);
  assert.ok(requestInit?.body instanceof ArrayBuffer);
  assert.match(
    String((requestInit?.headers as Record<string, string>)["content-type"]),
    /^multipart\/form-data;\s*boundary=/,
  );
  const forwardedBody = new TextDecoder().decode(
    requestInit?.body as ArrayBuffer,
  );
  assert.match(forwardedBody, /name="file"; filename="scan.png"/);
  assert.match(forwardedBody, /Content-Type: image\/png/i);
  assert.match(forwardedBody, /png-payload/);
});

test("proxy rejects uploads without content type before calling the parser", async () => {
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return new Response();
  };

  const response = await POST(
    new Request("http://frontend.test/api/parse", { method: "POST" }),
  );
  const body = await response.json();

  assert.equal(response.status, 400);
  assert.equal(body.error.code, "missing_content_type");
  assert.equal(called, false);
});
