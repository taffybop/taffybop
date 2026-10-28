import assert from "node:assert/strict";
import { test } from "node:test";
import { fieldText, inlineApiImage, previewTable, responseWarnings } from "../lib/backend-result-view.ts";

test("table preview preserves merged cells, API ordering, literal values, and explicit headers", () => {
  const table = {
    row_count: 3, column_count: 2,
    cells: [
      { row: 1, column: 1, text: "1,234.50 USD" },
      { row: 0, column: 0, col_span: 2, text: "Invoice", column_header: true },
      { row: 2, column: 1, text: "-0.00" },
      { row: 1, column: 0, row_span: 2, text: "00123" },
    ],
  };
  const before = structuredClone(table);
  const preview = previewTable(table);
  assert.equal(preview?.representation, "cells");
  assert.deepEqual(preview?.rows.map(row => row.map(cell => cell.text)), [["Invoice"], ["00123", "1,234.50 USD"], ["-0.00"]]);
  assert.equal(preview?.rows[0][0].colSpan, 2);
  assert.equal(preview?.rows[1][0].rowSpan, 2);
  assert.equal(preview?.rows[0][0].header, true);
  assert.equal(preview?.rows[1][0].header, false);
  assert.deepEqual(table, before);
});

test("invalid, overlapping, incomplete, or excessive cell coordinates fall back only to returned rows", () => {
  const rows = [["not automatically a header", "001"]];
  const badCells = [
    [{ row: 0, column: 0, col_span: 2 }, { row: 0, column: 1 }],
    [{ row: 0, column: 1 }],
    [{ row: 0, column: 0, row_span: 0 }],
    [{ row: 0, column: 0, col_span: 1_000_000 }],
    [{ row: 0.5, column: 0 }],
  ];
  for (const cells of badCells) {
    const preview = previewTable({ cells, rows });
    assert.equal(preview?.representation, "rows");
    assert.match(preview?.note ?? "", /Cell coordinates/);
    assert.deepEqual(preview?.rows[0].map(cell => cell.text), rows[0]);
    assert.equal(preview?.rows[0][0].header, false);
    assert.equal(previewTable({ cells }), null);
  }
  assert.equal(previewTable({ row_count: 2, cells: [{ row: 0, column: 0 }] }), null);
});

test("row preview does not pad or coerce source values and text is never interpreted as markup", () => {
  const preview = previewTable({ rows: [["<img src=x onerror=alert(1)>", "10 kg"], [null]] });
  assert.deepEqual(preview?.rows.map(row => row.map(cell => cell.text)), [["<img src=x onerror=alert(1)>", "10 kg"], ["null"]]);
  assert.equal(fieldText("**actual Markdown**"), "**actual Markdown**");
});

test("API image preview accepts inline raster assets only and never remote or active content", () => {
  const png = "data:image/png;base64,aGVsbG8=";
  assert.equal(inlineApiImage({ chart_resolution: { asset: { data_uri: png } } }), png);
  assert.equal(inlineApiImage({ asset: { data_uri: "data:image/jpeg;base64,aGVsbG8=" } }), "data:image/jpeg;base64,aGVsbG8=");
  for (const unsafe of ["https://example.com/tracker.png", "javascript:alert(1)", "data:image/svg+xml;base64,aGVsbG8=", "data:text/html;base64,aGVsbG8=", "data:image/png;base64,not valid", `data:image/png;base64,${"a".repeat(12_000_000)}`]) {
    assert.equal(inlineApiImage({ data_uri: unsafe }), null);
  }
});

test("warnings preserve original messages and identify actual failed API pages without manufacturing confidence", () => {
  assert.deepEqual(responseWarnings({ warnings: ["Original warning"], pages: [{ page_index: 7, success: false, warnings: ["OCR unavailable"] }, { page_index: 8, success: true }] }), ["Original warning", "Page 7: API reported unsuccessful processing.", "Page 7: OCR unavailable"]);
  assert.deepEqual(responseWarnings({ pages: [{ success: true }] }), []);
});

test("unresolved table candidate remains a candidate while its returned cells and concerns stay visible", () => {
  // Minimal fields from the real intake-table.png API response.
  const candidate = {
    id: "p1-i3", type: "table_candidate", row_count: 1, column_count: 2,
    rows: [["Complete after data entry for Route item is done", "Accepted"]],
    cells: [
      { row: 0, column: 0, row_span: 1, col_span: 1, text: "Complete after data entry for Route item is done", column_header: false, row_header: false },
      { row: 0, column: 1, row_span: 1, col_span: 1, text: "Accepted", column_header: false, row_header: false },
    ],
    parse_concerns: ["table_candidate_structure_invalid"],
  };
  assert.deepEqual(previewTable(candidate)?.rows[0].map(cell => cell.text), candidate.rows[0]);
  assert.equal(candidate.type, "table_candidate");
  assert.deepEqual(responseWarnings({ pages: [{ page_index: 1, items: [candidate], detected_images: [{ parse_concerns: ["image_description_unavailable"] }] }] }), [
    "Page 1 · p1-i3: table_candidate_structure_invalid",
    "Page 1 · detected_images[0]: image_description_unavailable",
  ]);
});
