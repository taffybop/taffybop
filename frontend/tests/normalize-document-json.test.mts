import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DOCUMENT_JSON_FIELDS,
  findTopLevelFieldOffset,
  getDocumentJsonMetrics,
  normalizeDocumentJson,
  serializeNormalizedDocumentJson,
  summarizeDocumentJson,
} from "../lib/normalize-document-json.ts";
import {
  sampleCanonicalPresentation,
  samplePage,
  sampleResult,
} from "./fixtures.mts";

test("normalization is lossless while adding complete text and Markdown views", () => {
  const table = {
    id: "p1-table",
    type: "table",
    reading_order: 2,
    value: [["Revenue", "100"]],
    md: "| Revenue | 100 |",
    html: "<table><tr><td>Revenue</td><td>100</td></tr></table>",
    csv: "Revenue,100",
    rows: [["Revenue", "100"]],
    cells: [
      {
        row: 0,
        column: 0,
        text: "Revenue",
        column_header: true,
      },
    ],
    row_count: 1,
    column_count: 2,
    parse_concerns: ["review merged header"],
    bbox: {
      x: 10,
      y: 20,
      width: 200,
      height: 40,
      unit: "pt",
      rotation: 0,
    },
    confidence: 0.8,
    engine: "table-engine",
    custom_table_field: { preserved: true },
  };
  const pageOne = samplePage({
    page_index: 1,
    page_number: 1,
    page_label: "i",
    layout_model: "layout-v2",
    items: [
      {
        id: "title",
        type: "heading",
        reading_order: 1,
        value: "Statement",
        md: "# Statement",
        level: 1,
      },
      table,
      {
        id: "footer",
        type: "footer",
        reading_order: 3,
        md: "Footer one",
        items: [{ value: "Footer one", custom_child_field: "kept" }],
      },
    ],
  });
  const pageTwo = samplePage({
    page_index: 2,
    page_number: 2,
    page_label: "2",
    items: [
      {
        id: "paragraph",
        type: "text",
        reading_order: 1,
        value: "Second-page paragraph.",
        md: "Second-page paragraph.",
        custom_item_field: ["kept"],
      },
    ],
  });
  const result = sampleResult({
    document: {
      filename: "finance.pdf",
      mime_type: "application/pdf",
      sha256: "sha",
      page_count: 2,
      image_count: 0,
      custom_document_field: "kept",
    },
    pages: [pageTwo, pageOne],
    trace_id: "trace-123",
  });
  const before = structuredClone(result);

  const normalized = normalizeDocumentJson(result);

  assert.deepEqual(Object.keys(normalized), [
    "result_content_metadata",
    "text",
    "markdown",
    "items",
    "metadata",
    "markdown_full",
    "text_full",
    "images_content_metadata",
  ]);
  assert.deepEqual(
    normalized.items.pages.map((page) => page.page_index),
    [1, 2],
  );
  assert.deepEqual(normalized.items.pages[0].items[1], table);
  assert.equal(normalized.items.pages[0].layout_model, "layout-v2");
  assert.equal(
    normalized.metadata.document.custom_document_field,
    "kept",
  );
  assert.equal(
    normalized.metadata.additional_top_level_fields.trace_id,
    "trace-123",
  );
  assert.deepEqual(normalized.result_content_metadata, {});
  assert.deepEqual(normalized.images_content_metadata, {
    images: [],
    total_count: 0,
  });
  assert.equal(normalized.markdown.pages[0].footer, "Footer one");
  assert.equal(normalized.markdown.pages[0].header, null);
  assert.match(normalized.text.pages[0].text, /Statement/);
  assert.match(
    normalized.text.pages[0].text,
    /<table><tr><td>Revenue<\/td><td>100<\/td><\/tr><\/table>/,
  );
  assert.match(normalized.text_full, /Second-page paragraph\./);
  assert.match(normalized.markdown_full, /# Statement/);
  assert.match(normalized.markdown_full, /\| Revenue \| 100 \|/);
  assert.deepEqual(result, before, "normalization must not mutate the API result");
});

test("summary metrics use available values and do not fabricate files or confidence", () => {
  const result = sampleResult({
    document: {
      filename: "sample.pdf",
      mime_type: "application/pdf",
      sha256: "sha",
      page_count: 3,
      image_count: 0,
    },
    pages: [
      samplePage({
        page_index: 1,
        items: [
          {
            id: "table",
            type: "table",
            reading_order: 1,
            rows: [["A"]],
            md: "| A |",
          },
          {
            id: "text",
            type: "text",
            reading_order: 2,
            value: "Text",
          },
        ],
      }),
      samplePage({
        page_index: 2,
        page_number: 2,
        items: [
          {
            id: "more-text",
            type: "text",
            reading_order: 1,
            value: "More text",
          },
        ],
      }),
    ],
  });
  const normalized = normalizeDocumentJson(result);

  assert.deepEqual(getDocumentJsonMetrics(normalized), {
    pageCount: 3,
    extractedPageCount: 2,
    itemCount: 3,
    tableCount: 1,
    imageCount: 0,
    averageConfidence: null,
    generatedFileCount: 0,
  });

  const rows = summarizeDocumentJson(normalized);
  assert.equal(
    rows.find((row) => row.field === "items")?.data,
    "2 pages · 3 items · 1 table",
  );
  assert.equal(
    rows.find((row) => row.field === "metadata")?.data,
    "3 pages · avg confidence unavailable",
  );
  assert.equal(
    rows.find((row) => row.field === "images_content_metadata")?.data,
    "0 images",
  );
  assert.equal(
    rows.find((row) => row.field === "result_content_metadata")?.data,
    "no generated files",
  );
});

test("available confidence, images, generated files, and additive metadata are summarized", () => {
  const result = sampleResult({
    document: {
      filename: "sample.pdf",
      mime_type: "application/pdf",
      sha256: "sha",
      page_count: 1,
      image_count: 1,
    },
    pages: [
      samplePage({
        page_index: 1,
        confidence: 0.7,
        detected_images: [
          {
            object_index: 1,
            bbox: { x: 1, y: 2, width: 3, height: 4, unit: "pt" },
            ocr_text: "Chart",
            confidence: 0.9,
            custom_image_field: "kept",
          },
        ],
      }),
    ],
    result_content_metadata: {
      xlsx: {
        exists: true,
        filename: "sample.xlsx",
        size_bytes: 120,
      },
      absent: {
        exists: false,
        filename: "not-generated.jsonl",
      },
    },
    images_content_metadata: {
      image_format: "source-only",
    },
  });
  const normalized = normalizeDocumentJson(result);
  const metrics = getDocumentJsonMetrics(normalized);

  assert.equal(metrics.averageConfidence, 0.7);
  assert.equal(metrics.imageCount, 1);
  assert.equal(metrics.generatedFileCount, 1);
  assert.equal(normalized.images_content_metadata.image_format, "source-only");
  assert.equal(
    (normalized.images_content_metadata.images[0] as Record<string, unknown>)
      .custom_image_field,
    "kept",
  );
  assert.equal(
    summarizeDocumentJson(normalized).find(
      (row) => row.field === "metadata",
    )?.data,
    "1 page · avg confidence 70%",
  );
});

test("top-level field offsets ignore identically named nested fields", () => {
  const result = sampleResult({
    trace: {
      metadata: "nested value must not be selected",
      text_full: "nested text",
    },
  });
  const json = serializeNormalizedDocumentJson(result);

  for (const field of DOCUMENT_JSON_FIELDS) {
    const offset = findTopLevelFieldOffset(json, field);
    assert.notEqual(offset, null, `expected an offset for ${field}`);
    assert.equal(
      json.slice(offset!, offset! + JSON.stringify(field).length),
      JSON.stringify(field),
    );
    assert.equal(json.slice(0, offset!).split("\n").at(-1), "  ");
  }

  const textFullOffset = findTopLevelFieldOffset(json, "text_full");
  const nestedOffset = json.indexOf('"text_full": "nested text"');
  assert.ok(textFullOffset !== null && textFullOffset > nestedOffset);
  assert.equal(
    findTopLevelFieldOffset(JSON.stringify(normalizeDocumentJson(result)), "text"),
    null,
    "the locator intentionally requires two-space pretty JSON",
  );
});

test("normalization preserves canonical once and uses every stored view verbatim", () => {
  const canonical = sampleCanonicalPresentation();
  const result = sampleResult({
    canonical_presentation: canonical,
    trace_id: "canonical-trace",
  });
  const before = structuredClone(result);

  const normalized = normalizeDocumentJson(result);

  assert.equal(normalized.canonical_presentation, canonical);
  assert.equal(
    "canonical_presentation" in
      normalized.metadata.additional_top_level_fields,
    false,
  );
  assert.equal(normalized.markdown_full, canonical.full.markdown);
  assert.equal(normalized.text_full, canonical.full.text);
  assert.equal(
    normalized.markdown.pages[0].markdown,
    canonical.pages[0].full.markdown,
  );
  assert.equal(
    normalized.text.pages[0].text,
    canonical.pages[0].full.text,
  );
  assert.equal(
    normalized.markdown.pages[0].header,
    canonical.pages[0].header.markdown,
  );
  assert.equal(
    normalized.markdown.pages[0].footer,
    canonical.pages[0].footer.markdown,
  );
  assert.deepEqual(result, before);

  const serialized = JSON.parse(
    serializeNormalizedDocumentJson(result),
  ) as Record<string, unknown>;
  assert.deepEqual(serialized.canonical_presentation, canonical);
  assert.equal(
    Object.keys(serialized).filter(
      (key) => key === "canonical_presentation",
    ).length,
    1,
  );
  assert.equal(
    "canonical_presentation" in
      ((
        serialized.metadata as Record<string, unknown>
      ).additional_top_level_fields as Record<string, unknown>),
    false,
  );
});
