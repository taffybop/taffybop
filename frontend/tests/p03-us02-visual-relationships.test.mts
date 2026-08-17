import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import { mapPhysicalPages } from "../lib/page-results.ts";
import { resolveCanonicalCaptionLink } from "../lib/layout-relationships.ts";
import { primaryItemText } from "../lib/primary-item-text.ts";
import { serializePageMarkdown } from "../lib/serialize-output.ts";
import type {
  CanonicalBlock,
  CanonicalPresentation,
  CanonicalView,
  ContainedVisualItem,
  DocumentContentItem,
  LayoutRelationship,
  ParseResult,
} from "../lib/types.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);

const captionRelationship: LayoutRelationship = {
  // Exact ID split produced by the backend P03-US02 synthetic graph: the
  // public compatibility ID and canonical internal element ID are distinct.
  id: "layout-rel-761207849f8d41bb0def",
  type: "caption_of",
  source_id: "layout-caption-fef79ebd66183c69620e",
  target_id: "p1-visual",
};

const containsRelationships: LayoutRelationship[] = [
  {
    id: "rel-contains-er-cas",
    type: "contains",
    source_id: "p1-visual",
    target_id: "visual-text-er-cas",
  },
  {
    id: "rel-contains-c",
    type: "contains",
    source_id: "p1-visual",
    target_id: "visual-text-c",
  },
];

const containedItems: ContainedVisualItem[] = [
  {
    id: "visual-text-er-cas",
    type: "visual_text",
    value: "er cas",
    bbox: {
      x: 134.25,
      y: 486.5,
      width: 31.5,
      height: 8,
      unit: "pt",
    },
    source: "ocr",
    confidence: 0.61,
    presentation_role: "subordinate",
    contained_by: "p1-visual",
    relationship_id: containsRelationships[0].id,
    relationship_type: "contains",
    relationship_basis: "graph_and_geometry",
  },
  {
    id: "visual-text-c",
    type: "visual_text",
    value: "C",
    bbox: {
      x: 310,
      y: 525,
      width: 6,
      height: 8,
      unit: "pt",
    },
    source: "ocr",
    confidence: 0.54,
    presentation_role: "subordinate",
    contained_by: "p1-visual",
    relationship_id: containsRelationships[1].id,
    relationship_type: "contains",
    relationship_basis: "graph_and_geometry",
  },
];

const caption: DocumentContentItem = {
  id: "layout-caption-fef79ebd66183c69620e",
  type: "caption",
  reading_order: 1,
  value: "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)",
  md: "EXHIBIT 8: 1H Insured Losses by Region (2025 $B)",
  bbox: {
    x: 100.25,
    y: 401.5,
    width: 216.51,
    height: 9.45,
    unit: "pt",
  },
  source: "native",
  confidence: null,
  caption_of: "p1-visual",
  relationship_id: captionRelationship.id,
  relationship_type: "caption_of",
  relationship_basis: "graph_and_geometry",
};

const chart: DocumentContentItem = {
  id: "p1-visual",
  type: "chart",
  reading_order: 2,
  value: "Authorized chart OCR",
  md: "Authorized chart OCR",
  bbox: {
    x: 99.27,
    y: 436.77,
    width: 445.04,
    height: 147.92,
    unit: "pt",
  },
  source: "ocr",
  confidence: 0.79,
  caption_ids: [caption.id],
  contains_ids: containedItems.map((item) => item.id),
  contained_items: containedItems,
  relationships: [
    captionRelationship,
    ...containsRelationships,
  ],
  include_ocr_in_primary: true,
  layout_visual_relationships_projected: true,
};

function view(blocks: CanonicalBlock[]): CanonicalView {
  return {
    block_ids: blocks.map((block) => block.id),
    markdown: `${blocks.map((block) => block.markdown).join("\n\n")}\n`,
    text: `${blocks.map((block) => block.text).join("\n\n")}\n`,
  };
}

function canonicalPresentation(): CanonicalPresentation {
  const blocks: CanonicalBlock[] = [
    {
      id: "canonical-caption-exhibit-8",
      page_id: "canonical-page-1",
      primary_element_id: "el-a98ba2136fefe0e21bdd",
      primary_element_type: "caption",
      scope: "body",
      markdown: String(caption.md),
      text: String(caption.value),
      contributing_element_ids: ["el-a98ba2136fefe0e21bdd"],
      relationship_ids: [captionRelationship.id],
      excluded_contributions: [],
    },
    {
      id: "canonical-chart-exhibit-8",
      page_id: "canonical-page-1",
      primary_element_id: "el-4a496fc78ad4b4398002",
      primary_element_type: "chart",
      scope: "body",
      markdown: String(chart.md),
      text: String(chart.value),
      contributing_element_ids: ["el-4a496fc78ad4b4398002"],
      relationship_ids: [
        captionRelationship.id,
        ...containsRelationships.map((relationship) => relationship.id),
      ],
      excluded_contributions: [],
    },
  ];
  const full = view(blocks);
  const empty = { block_ids: [], markdown: "", text: "" };

  return {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [
      {
        page_id: "canonical-page-1",
        page_index: 1,
        page_number: 7,
        page_label: "7",
        blocks,
        full,
        body: full,
        header: empty,
        footer: empty,
      },
    ],
    full,
    body: full,
    header: empty,
    footer: empty,
  };
}

function visualResult(withCanonical: boolean): ParseResult {
  return sampleResult({
    document: {
      filename: "catastrophe-recap.pdf",
      mime_type: "application/pdf",
      sha256: "catastrophe",
      page_count: 1,
    },
    pages: [
      samplePage({
        page_index: 1,
        page_number: 7,
        page_label: "7",
        items: [caption, chart],
      }),
    ],
    ...(withCanonical
      ? { canonical_presentation: canonicalPresentation() }
      : {}),
  });
}

test("legacy Markdown keeps the visual caption separate and contained text subordinate", () => {
  const page = visualResult(false).pages[0];
  const markdown = serializePageMarkdown(page);

  assert.equal(
    markdown,
    `${caption.md}\n\n${chart.md}\n`,
  );
  assert.equal(markdown.match(/EXHIBIT 8:/g)?.length, 1);
  assert.doesNotMatch(markdown, /er cas|(?:^|\s)C(?:\s|$)/);
  assert.equal(String(chart.value).includes(String(caption.value)), false);
  assert.equal(String(chart.md).includes("er cas"), false);
});

test("canonical output retains one linked caption block before the visual block", () => {
  const result = visualResult(true);
  const page = mapPhysicalPages(result).byPageNumber.get(1);
  assert.ok(page);

  const markdown = serializePageMarkdown(page, result);
  assert.equal(
    markdown,
    `${caption.md}\n\n${chart.md}\n`,
  );
  assert.equal(markdown.match(/EXHIBIT 8:/g)?.length, 1);
  assert.doesNotMatch(markdown, /er cas|(?:^|\s)C(?:\s|$)/);

  const blocks = result.canonical_presentation?.pages[0].blocks;
  assert.ok(blocks);
  assert.equal(blocks[0].primary_element_type, "caption");
  assert.equal(blocks[1].primary_element_type, "chart");
  assert.notEqual(blocks[0].primary_element_id, caption.id);
  assert.deepEqual(blocks[0].relationship_ids, [captionRelationship.id]);
  assert.equal(
    blocks[1].relationship_ids.includes(captionRelationship.id),
    true,
  );

  const link = resolveCanonicalCaptionLink(
    blocks[0],
    result.pages[0],
  );
  assert.ok(link);
  assert.equal(link.caption.id, caption.id);
  assert.equal(link.owner.id, chart.id);
  assert.deepEqual(link.relationship, captionRelationship);
});

test("non-canonical false image OCR stays subordinate in every primary output", async () => {
  const falseOcr = "SUBORDINATE PHOTO OCR";
  const containedText = "contained photo fragment";
  const safeFallback = "[Image detected; no reliable text extracted.]";
  const containedItem: ContainedVisualItem = {
    id: "visual-text-photo-fragment",
    type: "visual_text",
    value: containedText,
    bbox: {
      x: 25,
      y: 35,
      width: 20,
      height: 7,
      unit: "pt",
    },
    source: "ocr",
    confidence: 0.43,
    presentation_role: "subordinate",
    contained_by: "photo-1",
    relationship_id: "layout-rel-photo-contains",
    relationship_type: "contains",
    relationship_basis: "graph_and_geometry",
  };
  const photo: DocumentContentItem = {
    id: "photo-1",
    type: "image",
    reading_order: 1,
    value: "",
    md: safeFallback,
    ocr_text: falseOcr,
    include_ocr_in_primary: false,
    layout_visual_relationships_projected: true,
    contains_ids: [containedItem.id],
    contained_items: [containedItem],
    relationships: [
      {
        id: containedItem.relationship_id,
        type: "contains",
        source_id: "photo-1",
        target_id: containedItem.id,
      },
    ],
  };
  const result = sampleResult({
    pages: [samplePage({ items: [photo] })],
  });
  const page = result.pages[0];

  assert.equal(primaryItemText(photo), safeFallback);
  assert.equal(serializePageMarkdown(page), `${safeFallback}\n`);

  const normalized = normalizeDocumentJson(result);
  assert.equal(normalized.text.pages[0].text, safeFallback);
  assert.equal(normalized.text_full, safeFallback);
  assert.equal(
    normalized.markdown.pages[0].markdown,
    safeFallback,
  );
  assert.equal(normalized.markdown_full, `${safeFallback}\n`);
  for (const primaryOutput of [
    normalized.text.pages[0].text,
    normalized.text_full,
    normalized.markdown.pages[0].markdown,
    normalized.markdown_full,
  ]) {
    assert.doesNotMatch(primaryOutput, new RegExp(falseOcr));
    assert.doesNotMatch(primaryOutput, new RegExp(containedText));
  }
  assert.deepEqual(
    normalized.items.pages[0].items[0].contained_items,
    [containedItem],
  );

  const visibleOutput = serializePageMarkdown(page);
  let clipboardBytes = "";
  await {
    async writeText(value: string) {
      clipboardBytes = value;
    },
  }.writeText(visibleOutput);
  const downloadedBlob = new Blob(
    [visibleOutput],
    { type: "text/markdown;charset=utf-8" },
  );
  assert.equal(clipboardBytes, `${safeFallback}\n`);
  assert.equal(await downloadedBlob.text(), `${safeFallback}\n`);

  assert.equal(
    primaryItemText({
      ...photo,
      md: "",
    }),
    "",
  );

  const missingIncludeFlag: DocumentContentItem = {
    ...photo,
    md: "",
  };
  delete missingIncludeFlag.include_ocr_in_primary;
  assert.equal(primaryItemText(missingIncludeFlag), "");
  assert.equal(
    normalizeDocumentJson(
      sampleResult({
        pages: [samplePage({ items: [missingIncludeFlag] })],
      }),
    ).text_full,
    "",
  );
});

test("default-off legacy image keeps its retained OCR-first normalization", () => {
  const legacyPhoto: DocumentContentItem = {
    id: "legacy-photo",
    type: "image",
    reading_order: 0,
    value: "LEGACY IMAGE VALUE",
    md: "LEGACY IMAGE MARKDOWN",
    ocr_text: "LEGACY IMAGE OCR",
    include_ocr_in_primary: false,
  };
  const result = sampleResult({
    pages: [samplePage({ items: [legacyPhoto] })],
  });

  assert.equal(primaryItemText(legacyPhoto), "LEGACY IMAGE VALUE");
  assert.equal(normalizeDocumentJson(result).text_full, "LEGACY IMAGE OCR");
  assert.equal(
    serializePageMarkdown(result.pages[0]),
    "LEGACY IMAGE MARKDOWN\n",
  );
});

test("default-off UI keeps exact typed-string precedence including empties", () => {
  assert.equal(
    primaryItemText({
      id: "legacy-empty-value",
      type: "image",
      reading_order: 0,
      value: "",
      ocr_text: "AON",
      md: "fallback",
    }),
    "",
  );
  assert.equal(
    primaryItemText({
      id: "legacy-empty-ocr",
      type: "image",
      reading_order: 0,
      ocr_text: "",
      md: "fallback",
    }),
    "",
  );
  assert.equal(
    primaryItemText({
      id: "legacy-whitespace-markdown",
      type: "image",
      reading_order: 0,
      md: "  ",
    }),
    "  ",
  );
});

test("default-off chart and diagram keep generic value-Markdown-OCR order", () => {
  const legacyChart: DocumentContentItem = {
    id: "legacy-chart",
    type: "chart",
    reading_order: 0,
    value: "LEGACY CHART VALUE",
    md: "LEGACY CHART MARKDOWN",
    ocr_text: "LEGACY CHART OCR",
  };
  const legacyDiagram: DocumentContentItem = {
    id: "legacy-diagram",
    type: "diagram",
    reading_order: 1,
    value: "",
    md: "LEGACY DIAGRAM MARKDOWN",
    ocr_text: "LEGACY DIAGRAM OCR",
  };
  const result = sampleResult({
    pages: [samplePage({ items: [legacyChart, legacyDiagram] })],
  });

  assert.equal(
    normalizeDocumentJson(result).text_full,
    "LEGACY CHART VALUE\n\nLEGACY DIAGRAM MARKDOWN",
  );
});

test("normalized JSON, copy, and download preserve contained visual evidence", async () => {
  const result = visualResult(true);
  const normalized = normalizeDocumentJson(result);
  const normalizedChart = normalized.items.pages[0].items[1];

  assert.deepEqual(normalizedChart.contained_items, containedItems);
  assert.deepEqual(
    normalizedChart.contains_ids,
    containedItems.map((item) => item.id),
  );
  assert.deepEqual(normalizedChart.relationships, chart.relationships);

  const visibleJson = JSON.stringify(normalized, null, 2);
  let clipboardBytes = "";
  await {
    async writeText(value: string) {
      clipboardBytes = value;
    },
  }.writeText(visibleJson);
  const downloadedBlob = new Blob(
    [visibleJson],
    { type: "application/json" },
  );
  const downloaded = JSON.parse(await downloadedBlob.text());

  assert.equal(clipboardBytes, visibleJson);
  assert.deepEqual(
    downloaded.items.pages[0].items[1].contained_items,
    containedItems,
  );
  assert.equal(downloadedBlob.type, "application/json");
});

test("canonical and legacy captions share the escaped visible caption milestone", () => {
  const canonicalRenderer = workspaceSource.slice(
    workspaceSource.indexOf("function CanonicalRenderedPage"),
    workspaceSource.indexOf("function MarkdownSource"),
  );

  assert.match(workspaceSource, /if \(type === "caption"\)/);
  assert.match(workspaceSource, /className="parsed-caption"/);
  assert.match(
    canonicalRenderer,
    /block\.primary_element_type\.toLowerCase\(\) === "caption"/,
  );
  assert.match(canonicalRenderer, /\? "parsed-caption"/);
  assert.match(
    canonicalRenderer,
    /resolveCanonicalCaptionLink\(block, sourcePage\)/,
  );
  assert.match(
    canonicalRenderer,
    /data-caption-id=\{captionLink\?\.caption\.id\}/,
  );
  assert.match(
    canonicalRenderer,
    /data-caption-of=\{captionLink\?\.owner\.id\}/,
  );
  assert.match(
    canonicalRenderer,
    /data-relationship-id=\{captionLink\?\.relationship\.id\}/,
  );
  assert.match(canonicalRenderer, /\{block\.text\}/);
  assert.doesNotMatch(canonicalRenderer, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(workspaceSource, /contained_items/);
  assert.match(
    workspaceSource,
    /return primaryItemText\(item\)/,
  );
});

test("canonical caption links fail closed on inconsistent public endpoints", () => {
  const presentation = canonicalPresentation();
  const block = presentation.pages[0].blocks[0];
  const page = samplePage({
    items: [
      caption,
      {
        ...chart,
        relationships: [
          {
            ...captionRelationship,
            target_id: "different-owner",
          },
        ],
      },
    ],
  });

  assert.equal(resolveCanonicalCaptionLink(block, page), null);
});

test("canonical caption links require one exact owner caption backlink", () => {
  const block = canonicalPresentation().pages[0].blocks[0];
  for (const captionIds of [[], [caption.id, caption.id]]) {
    const page = samplePage({
      items: [
        caption,
        {
          ...chart,
          caption_ids: captionIds,
        },
      ],
    });

    assert.equal(resolveCanonicalCaptionLink(block, page), null);
  }
});

test("canonical caption links reject duplicate relationship IDs", () => {
  const block = canonicalPresentation().pages[0].blocks[0];
  const page = samplePage({
    items: [
      caption,
      {
        ...chart,
        relationships: [
          captionRelationship,
          {
            ...captionRelationship,
            target_id: "different-owner",
          },
        ],
      },
    ],
  });

  assert.equal(resolveCanonicalCaptionLink(block, page), null);
});

test("canonical caption links reject duplicate page item IDs", () => {
  const block = canonicalPresentation().pages[0].blocks[0];
  const page = samplePage({
    items: [
      caption,
      chart,
      {
        id: caption.id,
        type: "text",
        reading_order: 3,
        value: "conflicting item",
      },
    ],
  });

  assert.equal(resolveCanonicalCaptionLink(block, page), null);
});

test("canonical caption links reject relationship IDs reused page-wide", () => {
  const block = canonicalPresentation().pages[0].blocks[0];
  const page = samplePage({
    items: [
      caption,
      chart,
      {
        id: "other-owner",
        type: "chart",
        reading_order: 3,
        relationships: [
          {
            ...captionRelationship,
            target_id: "other-owner",
          },
        ],
      },
    ],
  });

  assert.equal(resolveCanonicalCaptionLink(block, page), null);
});

test("canonical caption links fail closed on malformed additive arrays", () => {
  const block = canonicalPresentation().pages[0].blocks[0];
  const malformedRelationships = samplePage({
    items: [
      caption,
      {
        ...chart,
        relationships: {} as LayoutRelationship[],
      },
    ],
  });
  const malformedCaptionIds = samplePage({
    items: [
      caption,
      {
        ...chart,
        caption_ids: "not-an-array" as unknown as string[],
      },
    ],
  });

  assert.equal(
    resolveCanonicalCaptionLink(block, malformedRelationships),
    null,
  );
  assert.equal(resolveCanonicalCaptionLink(block, malformedCaptionIds), null);
});
