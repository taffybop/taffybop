import assert from "node:assert/strict";
import { test } from "node:test";
import { assertStaticPublishReady, staticApiEndpoint, staticParserDefines } from "../tools/static-api-config.mjs";

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
