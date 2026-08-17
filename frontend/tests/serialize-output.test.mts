import assert from "node:assert/strict";
import { test } from "node:test";

import {
  serializeDocumentMarkdown,
  serializeItemMarkdown,
  serializePageJson,
  serializePageMarkdown,
  serializePageOutput,
} from "../lib/serialize-output.ts";
import {
  sampleCanonicalPresentation,
  samplePage,
  sampleResult,
} from "./fixtures.mts";

test("page Markdown preserves authoritative blocks and reading order", () => {
  const page = samplePage({
    items: [
      { id: "later", type: "text", reading_order: 2, value: "Fallback" },
      {
        id: "first",
        type: "heading",
        reading_order: 1,
        md: "  # Authoritative markdown  ",
        value: "Do not use this",
      },
      { id: "blank", type: "text", reading_order: 3, md: "   " },
    ],
  });

  assert.equal(
    serializePageMarkdown(page),
    "# Authoritative markdown\n\nFallback\n",
  );
  assert.deepEqual(serializePageOutput(page, "markdown"), {
    content: "# Authoritative markdown\n\nFallback\n",
    contentType: "text/markdown",
    extension: "md",
  });
});

test("page JSON contains only the selected page and preserves page identity", () => {
  const page = samplePage({
    page_index: 0,
    page_number: 1,
    page_label: "i",
    items: [
      { id: "page-one", type: "text", reading_order: 1, md: "Page one" },
    ],
  });

  const serialized = JSON.parse(serializePageJson(page));
  assert.equal(serialized.page_index, 0);
  assert.equal(serialized.page_number, 1);
  assert.equal(serialized.page_label, "i");
  assert.equal(serialized.items.length, 1);
  assert.equal("pages" in serialized, false);
  assert.equal("document" in serialized, false);

  const output = serializePageOutput(page, "json");
  assert.equal(output.contentType, "application/json");
  assert.equal(output.extension, "json");
  assert.deepEqual(JSON.parse(output.content), serialized);
});

test("stored canonical Markdown is returned byte-for-byte for document and page", () => {
  const canonical = sampleCanonicalPresentation();
  const result = sampleResult({ canonical_presentation: canonical });
  const page = result.pages[0];

  assert.equal(serializeDocumentMarkdown(result), canonical.full.markdown);
  assert.equal(
    serializePageMarkdown(page, result),
    canonical.pages[0].full.markdown,
  );
  assert.deepEqual(serializePageOutput(page, "markdown", result), {
    content: canonical.pages[0].full.markdown,
    contentType: "text/markdown",
    extension: "md",
  });
});

test("legacy additive item fallback remains md then scalar value", () => {
  assert.equal(
    serializeItemMarkdown({
      id: "unknown-md",
      type: "future_additive_item",
      reading_order: 1,
      md: "  authoritative additive markdown  ",
      value: 42,
    }),
    "authoritative additive markdown",
  );
  assert.equal(
    serializeItemMarkdown({
      id: "unknown-number",
      type: "future_additive_item",
      reading_order: 2,
      value: 42,
    }),
    "42",
  );
  assert.equal(
    serializeItemMarkdown({
      id: "unknown-boolean",
      type: "future_additive_item",
      reading_order: 3,
      value: false,
    }),
    "false",
  );
});
