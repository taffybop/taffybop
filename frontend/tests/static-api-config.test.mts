import assert from "node:assert/strict";
import { test } from "node:test";
import { assertStaticPublishReady, staticApiEndpoint, staticBuildMetadata, staticDeploymentMode, staticParserDefines } from "../tools/static-api-config.mjs";

test("static endpoint defaults to same origin and accepts only explicit public HTTPS API locations", () => {
  for (const value of [undefined, "", "  ", "/v1/parse"]) assert.equal(staticApiEndpoint(value), "/v1/parse");
  for (const value of ["https://api.example", "https://api.example/", "https://api.example/v1/parse", "https://api.example/v1/parse/"]) {
    assert.equal(staticApiEndpoint(value), "https://api.example/v1/parse");
  }
  const defines = staticParserDefines("https://api.example");
  assert.equal(defines["process.env.NEXT_PUBLIC_PARSE_API_URL"], '"https://api.example/v1/parse"');
  assert.equal(Object.keys(defines).length, 3);
});

test("static builds reject credentials, query tokens, insecure or malformed endpoints without printing secrets", () => {
  for (const value of [
    "http://api.example", "//api.example", "javascript:secret", "/other/path",
    "https://user:secret@api.example", "https://api.example?token=secret",
    "https://api.example/v1/parse?secret=1", "https://api.example/#secret",
    "https://api.example/private", "https://api.example\\private", "https://api.\nexample",
  ]) {
    assert.throws(() => staticApiEndpoint(value), error => {
      assert.ok(error instanceof Error);
      assert.match(error.message, /TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL/);
      assert.doesNotMatch(error.message, /secret/);
      return true;
    });
  }
});

test("static publication requires readiness and the exact endpoint embedded in the build", () => {
  const direct = { schemaVersion: 1, parseApiUrl: "https://api.example/v1/parse" };
  const env = { TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL: "https://api.example", TAFFYBOP_STATIC_API_GATEWAY_READY: "1" };
  assert.equal(assertStaticPublishReady(direct, env), direct.parseApiUrl);
  assert.throws(() => assertStaticPublishReady(direct, { ...env, TAFFYBOP_STATIC_API_GATEWAY_READY: "" }), /requires/);
  assert.throws(() => assertStaticPublishReady(direct, { ...env, TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL: "https://different.example" }), /differs/);
  assert.throws(() => assertStaticPublishReady(direct, { TAFFYBOP_STATIC_API_GATEWAY_READY: "1" }), /differs/);
  assert.throws(() => assertStaticPublishReady(null, env), /metadata/);
  const sameOrigin = { schemaVersion: 1, parseApiUrl: "/v1/parse" };
  assert.throws(() => assertStaticPublishReady(sameOrigin, {}), /requires/);
  assert.equal(assertStaticPublishReady(sameOrigin, { TAFFYBOP_STATIC_API_GATEWAY_READY: "1" }), "/v1/parse");
});

test("static mode is explicit and preview metadata cannot bind an API", () => {
  for (const value of [undefined, "", " ", "api"]) assert.equal(staticDeploymentMode(value), "api");
  assert.equal(staticDeploymentMode("preview"), "preview");
  assert.throws(() => staticDeploymentMode("unknown-secret-value"), error => {
    assert.ok(error instanceof Error);
    assert.match(error.message, /must be api or preview/);
    assert.doesNotMatch(error.message, /secret/);
    return true;
  });
  assert.deepEqual(staticBuildMetadata({}), { schemaVersion: 1, deploymentMode: "api", parseApiUrl: "/v1/parse" });
  assert.deepEqual(staticBuildMetadata({ TAFFYBOP_STATIC_MODE: "preview" }), { schemaVersion: 1, deploymentMode: "preview", parseApiUrl: null });
  for (const extra of [
    { TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL: "https://api.example" },
    { TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL: "/v1/parse" },
    { TAFFYBOP_STATIC_API_GATEWAY_READY: "1" },
  ]) {
    assert.throws(() => staticBuildMetadata({ TAFFYBOP_STATIC_MODE: "preview", ...extra }), /must not configure/);
  }
});

test("preview publication requires matching preview metadata and its own readiness", () => {
  const preview = { schemaVersion: 1, deploymentMode: "preview", parseApiUrl: null };
  const env = { TAFFYBOP_STATIC_MODE: "preview", TAFFYBOP_STATIC_PREVIEW_READY: "1" };
  assert.equal(assertStaticPublishReady(preview, env), null);
  assert.throws(() => assertStaticPublishReady(preview, { TAFFYBOP_STATIC_MODE: "preview" }), /PREVIEW_READY/);
  assert.throws(() => assertStaticPublishReady(preview, { TAFFYBOP_STATIC_PREVIEW_READY: "1" }), /mode differs/);
  assert.throws(() => assertStaticPublishReady(preview, { ...env, TAFFYBOP_STATIC_API_GATEWAY_READY: "1" }), /must not configure/);
  assert.throws(() => assertStaticPublishReady(preview, { ...env, TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL: "https://api.example" }), /must not configure/);
  assert.throws(() => assertStaticPublishReady({ ...preview, parseApiUrl: "/v1/parse" }, env), /must contain no API/);
  assert.throws(() => assertStaticPublishReady({ schemaVersion: 1, parseApiUrl: "/v1/parse" }, env), /mode differs/);
  assert.throws(() => assertStaticPublishReady({ ...preview, deploymentMode: "invalid" }, env), /metadata/);
});

test("preview readiness cannot authorize API publication", () => {
  const api = { schemaVersion: 1, deploymentMode: "api", parseApiUrl: "/v1/parse" };
  assert.throws(() => assertStaticPublishReady(api, { TAFFYBOP_STATIC_PREVIEW_READY: "1" }), /must not use preview/);
  assert.throws(() => assertStaticPublishReady(api, { TAFFYBOP_STATIC_API_GATEWAY_READY: "1", TAFFYBOP_STATIC_PREVIEW_READY: "1" }), /must not use preview/);
  assert.equal(assertStaticPublishReady(api, { TAFFYBOP_STATIC_API_GATEWAY_READY: "1" }), "/v1/parse");
});
