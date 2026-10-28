import assert from "node:assert/strict";
import { test } from "node:test";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { build } from "vite";
import staticConfig from "../vite.static.config.ts";

async function browserApi(defines: Record<string, string>) {
  const built = await build({
    configFile: false,
    logLevel: "silent",
    define: defines,
    build: {
      write: false,
      minify: true,
      lib: { entry: fileURLToPath(new URL("../lib/document-api.ts", import.meta.url)), formats: ["iife"], name: "ParserApi" },
    },
  });
  const bundle = Array.isArray(built) ? built[0] : built;
  assert.ok("output" in bundle);
  const chunk = bundle.output.find(output => output.type === "chunk");
  assert.ok(chunk?.type === "chunk");
  const requests: string[] = [];
  const timeouts: number[] = [];
  const context = {
    AbortController, DOMException, File, FormData, TextDecoder, Uint8Array,
    setTimeout: (_callback: () => void, milliseconds: number) => { timeouts.push(milliseconds); return 1; },
    clearTimeout: () => {},
    fetch: async (url: string) => {
      requests.push(url);
      return new Response('{"schema_version":"1.0","document":{},"pages":[],"processing":{}}');
    },
  };
  assert.equal(vm.runInNewContext("typeof process", context), "undefined");
  const api = vm.runInNewContext(`${chunk.code}; ParserApi`, context) as {
    getConfiguredMaxUploadBytes(): number;
    parseJsonResponse(file: File, options?: { apiBaseUrl?: string }): Promise<unknown>;
  };
  return { api, requests, timeouts };
}

test("inlined Next public parser settings work in a browser without process", async () => {
  const { api, requests, timeouts } = await browserApi({
    "process.env.NEXT_PUBLIC_PARSE_API_URL": JSON.stringify("https://configured-parser.example"),
    "process.env.NEXT_PUBLIC_PARSE_API_TIMEOUT_MS": JSON.stringify("12345"),
    "process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES": JSON.stringify("98765"),
  });
  assert.equal(api.getConfiguredMaxUploadBytes(), 98_765);
  await api.parseJsonResponse(new File(["%PDF-1.7"], "test.pdf", { type: "application/pdf" }));
  assert.deepEqual(requests, ["https://configured-parser.example/v1/parse?output_format=json"]);
  assert.deepEqual(timeouts, [12_345]);
});

test("static build defines only its three parser settings and uses the explicit same-origin endpoint", async () => {
  assert.ok(typeof staticConfig === "object" && staticConfig.define);
  assert.deepEqual(Object.keys(staticConfig.define).sort(), [
    "process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES",
    "process.env.NEXT_PUBLIC_PARSE_API_TIMEOUT_MS",
    "process.env.NEXT_PUBLIC_PARSE_API_URL",
  ]);
  const { api, requests, timeouts } = await browserApi(staticConfig.define as Record<string, string>);
  assert.equal(api.getConfiguredMaxUploadBytes(), 20 * 1024 * 1024);
  await api.parseJsonResponse(new File(["%PDF-1.7"], "test.pdf", { type: "application/pdf" }), { apiBaseUrl: "/v1/parse" });
  assert.deepEqual(requests, ["/v1/parse?output_format=json"]);
  assert.deepEqual(timeouts, [330_000]);
});
