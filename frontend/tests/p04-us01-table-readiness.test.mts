import assert from "node:assert/strict";
import { test } from "node:test";

const readinessPlan = Object.freeze({
  status: "readiness-only",
  story: "P04-US01",
  featureFlag: "parser.tables.span_fidelity.enabled",
  defaultEnabled: false,
  implementationTestPath:
    "frontend/tests/p04-us01-table-span-fidelity.test.mts",
  requiredLayers: [
    "strict-sidecar-reader",
    "escaped-react-grid",
    "predecessor-fallback",
    "copy-download-parity",
    "responsive-layout",
  ],
  requiredFixtures: [
    "explicit-repeated-values",
    "supported-rowspan",
    "supported-colspan",
    "multiline-header",
    "explicit-blank-versus-covered",
    "inert-html-text",
    "malformed-sidecar-fallback",
    "flag-off-byte-identity",
  ],
  viewports: [
    { width: 320, height: 568 },
    { width: 768, height: 1024 },
    { width: 1440, height: 900 },
  ],
});

const inertCellValues = [
  "<script>alert(1)</script>",
  "<img src=x onerror=alert(1)>",
  "AT&T",
  'javascript:alert("x")',
];

test("P04-US01 frontend plan stays readiness-only while the story is Ready", () => {
  assert.equal(readinessPlan.status, "readiness-only");
  assert.equal(readinessPlan.defaultEnabled, false);
  assert.equal(readinessPlan.requiredLayers.length, 5);
  assert.equal(readinessPlan.requiredFixtures.length, 8);
  assert.deepEqual(
    readinessPlan.viewports.map(({ width }) => width),
    [320, 768, 1440],
  );
});

test("frontend fixture plan keeps hostile source text as data", () => {
  const encoded = JSON.stringify({ cells: inertCellValues });
  assert.deepEqual(JSON.parse(encoded).cells, inertCellValues);
  assert.equal(encoded.includes("<script>alert(1)</script>"), true);
  assert.equal(encoded.includes("onerror=alert(1)"), true);
});

test("frontend plan requires a separate production test before completion", () => {
  assert.equal(
    readinessPlan.implementationTestPath,
    "frontend/tests/p04-us01-table-span-fidelity.test.mts",
  );
  assert.equal(
    readinessPlan.requiredLayers.includes("escaped-react-grid"),
    true,
  );
  assert.equal(
    readinessPlan.requiredLayers.includes("predecessor-fallback"),
    true,
  );
});
