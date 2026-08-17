import assert from "node:assert/strict";
import { test } from "node:test";

import {
  getPhysicalPageCount,
  mapPhysicalPages,
} from "../lib/page-results.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

test("one-based parser pages map by physical index, not array position", () => {
  const result = sampleResult({
    document: {
      filename: "sparse.pdf",
      mime_type: "application/pdf",
      sha256: "sparse",
      page_count: 3,
    },
    pages: [
      samplePage({ page_index: 3, page_number: 3, page_label: "3" }),
      samplePage({ page_index: 1, page_number: 1, page_label: "cover" }),
      samplePage({ page_index: 8, page_number: 8, page_label: "8" }),
    ],
  });

  const mapped = mapPhysicalPages(result);

  assert.equal(mapped.usesZeroBasedIndexes, false);
  assert.equal(mapped.byPageNumber.get(1)?.page_label, "cover");
  assert.equal(mapped.byPageNumber.has(2), false);
  assert.equal(mapped.byPageNumber.get(3)?.page_label, "3");
  assert.equal(mapped.byPageNumber.has(8), false);
});

test("zero-based adapter pages normalize to one-based physical navigation", () => {
  const result = sampleResult({
    document: {
      filename: "zero-based.pdf",
      mime_type: "application/pdf",
      sha256: "zero",
      page_count: 2,
    },
    pages: [
      samplePage({ page_index: 0, page_number: 1, page_label: "i" }),
      samplePage({ page_index: 1, page_number: 2, page_label: "1" }),
    ],
  });

  const mapped = mapPhysicalPages(result);

  assert.equal(mapped.usesZeroBasedIndexes, true);
  assert.equal(mapped.byPageNumber.get(1)?.page_index, 0);
  assert.equal(mapped.byPageNumber.get(2)?.page_index, 1);
});

test("local preview count is preferred, with API metadata as a fallback", () => {
  const result = sampleResult({
    document: {
      filename: "count.pdf",
      mime_type: "application/pdf",
      sha256: "count",
      page_count: 17,
    },
  });

  assert.equal(getPhysicalPageCount(result, 19), 19);
  assert.equal(getPhysicalPageCount(result, 0), 17);
  assert.equal(getPhysicalPageCount(null, 0), 0);
});

test("multi-frame TIFF navigation can use the parsed document page count", () => {
  const result = sampleResult({
    document: {
      filename: "frames.tiff",
      mime_type: "image/tiff",
      sha256: "frames",
      page_count: 3,
    },
    pages: [
      samplePage({ page_index: 1, page_number: 1, page_label: "1" }),
      samplePage({ page_index: 2, page_number: 2, page_label: "2" }),
      samplePage({ page_index: 3, page_number: 3, page_label: "3" }),
    ],
  });

  assert.equal(getPhysicalPageCount(result, 0), 3);
  assert.deepEqual([...mapPhysicalPages(result).byPageNumber.keys()], [1, 2, 3]);
});
