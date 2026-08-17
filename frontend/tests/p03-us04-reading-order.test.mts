import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import {
  serializePageJson,
  serializePageMarkdown,
} from "../lib/serialize-output.ts";
import type {
  CanonicalBlock,
  CanonicalPresentation,
  CanonicalView,
  DocumentContentItem,
  LayoutRelationship,
  ParseResult,
} from "../lib/types.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);
const serializerSource = readFileSync(
  new URL("../lib/serialize-output.ts", import.meta.url),
  "utf8",
);
const normalizerSource = readFileSync(
  new URL("../lib/normalize-document-json.ts", import.meta.url),
  "utf8",
);

const TITLE = "Clean Energy Market Monitor - March 2024";
const OVERVIEW = "Overview";
const CLINICAL_OWNED =
  "Data Availability Statement: The data collected for this study involves " +
  "sensitive information obtained";
const REJECTED_TOKEN = "RESEARCHARTICLE";

const captionRelationship: LayoutRelationship = {
  id: "relationship-order-caption",
  type: "caption_of",
  source_id: "above-caption",
  target_id: "visual-owner",
};
const noteRelationship: LayoutRelationship = {
  id: "relationship-order-note",
  type: "source_note_of",
  source_id: "source-note",
  target_id: "visual-owner",
};

const orderedItems: DocumentContentItem[] = [
  {
    id: "clean-header",
    type: "header",
    reading_order: 0,
    value: `${TITLE}\n${OVERVIEW}`,
    md: `${TITLE}\n\n${OVERVIEW}`,
    bbox: {
      x: 56.64,
      y: 48.909,
      width: 723.129,
      height: 11.45,
      unit: "pt",
    },
    source: "native",
    confidence: 0.99,
    items: [
      {
        value: TITLE,
        md: TITLE,
        bbox: {
          x: 56.64,
          y: 52.803,
          width: 159.674,
          height: 7.556,
          unit: "pt",
        },
        source: "native",
      },
      {
        value: OVERVIEW,
        md: OVERVIEW,
        bbox: {
          x: 735.36,
          y: 48.909,
          width: 44.409,
          height: 9.36,
          unit: "pt",
        },
        source: "native",
      },
    ],
  },
  {
    id: "above-caption",
    type: "caption",
    reading_order: 1,
    value: "Reviewed caption",
    md: "Reviewed caption",
    bbox: {
      x: 90,
      y: 650,
      width: 220,
      height: 10,
      unit: "pt",
    },
    source: "native",
    confidence: 0.99,
    caption_of: "visual-owner",
    relationship_id: captionRelationship.id,
    relationship_type: captionRelationship.type,
    relationship_basis: "graph_and_geometry",
  },
  {
    id: "visual-owner",
    type: "chart",
    reading_order: 2,
    value: "Reviewed chart",
    md: "Reviewed chart",
    bbox: {
      x: 90,
      y: 420,
      width: 420,
      height: 140,
      unit: "pt",
    },
    source: "native",
    confidence: 0.99,
    caption_of: ["above-caption"],
    caption_ids: ["above-caption"],
    source_note_ids: ["source-note"],
    relationships: [captionRelationship, noteRelationship],
    layout_source_notes_projected: true,
  },
  {
    id: "source-note",
    type: "source_note",
    reading_order: 3,
    value: "Source: reviewed evidence",
    md: "Source: reviewed evidence",
    bbox: {
      x: 90,
      y: 580,
      width: 180,
      height: 9,
      unit: "pt",
    },
    source: "native",
    confidence: 0.99,
    source_note_of: "visual-owner",
    relationship_id: noteRelationship.id,
    relationship_type: noteRelationship.type,
    relationship_basis: "graph_and_geometry",
  },
  {
    id: "clinical-owned",
    type: "text",
    reading_order: 4,
    value: CLINICAL_OWNED,
    md: CLINICAL_OWNED,
    bbox: {
      x: 36.001,
      y: 692.642,
      width: 151.206,
      height: 17.698,
      unit: "pt",
    },
    source: "ocr",
    confidence: 0.99,
  },
];

const ORDERED_IDS = orderedItems.map((item) => item.id);
const EXPECTED_MARKDOWN = [
  `${TITLE}\n\n${OVERVIEW}`,
  "Reviewed caption",
  "Reviewed chart",
  "Source: reviewed evidence",
  CLINICAL_OWNED,
].join("\n\n") + "\n";
const EXPECTED_TEXT = [
  `${TITLE}\n${OVERVIEW}`,
  "Reviewed caption",
  "Reviewed chart",
  "Source: reviewed evidence",
  CLINICAL_OWNED,
].join("\n\n") + "\n";

function canonicalView(blocks: CanonicalBlock[]): CanonicalView {
  const render = (field: "markdown" | "text") => {
    const values = blocks
      .map((block) => block[field].trim())
      .filter(Boolean);
    return values.length ? `${values.join("\n\n")}\n` : "";
  };

  return {
    block_ids: blocks.map((block) => block.id),
    markdown: render("markdown"),
    text: render("text"),
  };
}

function relationshipOrderResult(): ParseResult {
  const page = samplePage({
    page_width: 841.92,
    page_height: 792,
    items: structuredClone(orderedItems),
  });
  const blocks: CanonicalBlock[] = page.items.map((item) => ({
    id: `canonical-${item.id}`,
    page_id: "canonical-page-1",
    primary_element_id: item.id,
    primary_element_type: item.type,
    scope: item.type === "header" ? "header" : "body",
    markdown: String(item.md ?? item.value ?? ""),
    text:
      item.id === "clean-header"
        ? `${TITLE}\n${OVERVIEW}`
        : String(item.value ?? ""),
    contributing_element_ids: [item.id],
    relationship_ids:
      item.id === "above-caption"
        ? [captionRelationship.id]
        : item.id === "visual-owner"
          ? [captionRelationship.id, noteRelationship.id]
          : item.id === "source-note"
            ? [noteRelationship.id]
            : [],
    excluded_contributions: [],
  }));
  const full = canonicalView(blocks);
  const body = canonicalView(
    blocks.filter((block) => block.scope === "body"),
  );
  const header = canonicalView(
    blocks.filter((block) => block.scope === "header"),
  );
  const footer = canonicalView([]);
  const canonical: CanonicalPresentation = {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [
      {
        page_id: "canonical-page-1",
        page_index: page.page_index,
        page_number: page.page_number,
        page_label: page.page_label,
        blocks,
        full,
        body,
        header,
        footer,
      },
    ],
    full,
    body,
    header,
    footer,
  };

  return sampleResult({
    document: {
      filename: "p03-us04-reading-order.pdf",
      mime_type: "application/pdf",
      sha256: "relationship-order",
      page_count: 1,
    },
    pages: [page],
    canonical_presentation: canonical,
  });
}

function sourceSection(
  source: string,
  start: string,
  end: string,
): string {
  const startIndex = source.indexOf(start);
  const endIndex = source.indexOf(end, startIndex);
  assert.notEqual(startIndex, -1, `Expected source to contain ${start}`);
  assert.notEqual(endIndex, -1, `Expected source to contain ${end}`);
  return source.slice(startIndex, endIndex);
}

async function assertCopyAndDownloadBytes(
  value: string,
  mime: string,
): Promise<void> {
  let clipboardBytes = "";
  await {
    async writeText(content: string) {
      clipboardBytes = content;
    },
  }.writeText(value);
  const downloaded = new Blob([value], { type: mime });

  assert.equal(clipboardBytes, value);
  assert.equal(downloaded.type, mime);
  assert.equal(await downloaded.text(), value);
}

test("backend order drives legacy, canonical, JSON, copy, and download bytes", async () => {
  const result = relationshipOrderResult();
  const before = structuredClone(result);
  const page = result.pages[0];
  const geometryY = page.items.map((item) => Number(item.bbox?.y));

  assert.deepEqual(page.items.map((item) => item.id), ORDERED_IDS);
  assert.deepEqual(
    page.items.map((item) => item.reading_order),
    [0, 1, 2, 3, 4],
  );
  assert.notDeepEqual(geometryY, [...geometryY].sort((left, right) => left - right));

  const legacyMarkdown = serializePageMarkdown(page);
  const canonicalMarkdown = serializePageMarkdown(page, result);
  assert.equal(legacyMarkdown, EXPECTED_MARKDOWN);
  assert.equal(canonicalMarkdown, EXPECTED_MARKDOWN);

  const normalized = normalizeDocumentJson(result);
  const normalizedPage = normalized.items.pages[0];
  assert.deepEqual(
    normalizedPage.items.map((item) => item.id),
    ORDERED_IDS,
  );
  assert.deepEqual(
    normalizedPage.items.map((item) => item.reading_order),
    [0, 1, 2, 3, 4],
  );
  assert.deepEqual(
    normalizedPage.items[0].items?.map((item) => item.value),
    [TITLE, OVERVIEW],
  );
  assert.equal(normalizedPage.items[0].value, `${TITLE}\n${OVERVIEW}`);
  assert.equal(normalizedPage.items[0].md, `${TITLE}\n\n${OVERVIEW}`);
  assert.equal(normalizedPage.items[4].value, CLINICAL_OWNED);
  assert.equal(normalizedPage.items[4].md, CLINICAL_OWNED);
  assert.equal(normalized.markdown.pages[0].markdown, EXPECTED_MARKDOWN);
  assert.equal(normalized.markdown_full, EXPECTED_MARKDOWN);
  assert.equal(normalized.text.pages[0].text, EXPECTED_TEXT);
  assert.equal(normalized.text_full, EXPECTED_TEXT);
  assert.equal(
    normalized.markdown.pages[0].header,
    `${TITLE}\n\n${OVERVIEW}\n`,
  );

  const serializedPage = JSON.parse(serializePageJson(page));
  assert.deepEqual(
    serializedPage.items.map((item: DocumentContentItem) => item.id),
    ORDERED_IDS,
  );
  assert.deepEqual(
    serializedPage.items[0].items.map(
      (item: { value?: unknown }) => item.value,
    ),
    [TITLE, OVERVIEW],
  );

  const visibleJson = JSON.stringify(normalized, null, 2);
  const downloadedJson = JSON.parse(visibleJson);
  assert.deepEqual(
    downloadedJson.items.pages[0].items.map(
      (item: DocumentContentItem) => item.id,
    ),
    ORDERED_IDS,
  );
  assert.deepEqual(
    downloadedJson.items.pages[0].items[0].items.map(
      (item: { value?: unknown }) => item.value,
    ),
    [TITLE, OVERVIEW],
  );

  for (const output of [
    legacyMarkdown,
    canonicalMarkdown,
    normalized.markdown_full,
    normalized.text_full,
    visibleJson,
  ]) {
    assert.doesNotMatch(output, new RegExp(REJECTED_TOKEN));
  }

  await assertCopyAndDownloadBytes(
    canonicalMarkdown,
    "text/markdown;charset=utf-8",
  );
  await assertCopyAndDownloadBytes(visibleJson, "application/json");
  assert.deepEqual(result, before);
});

test("render, source, normalization, copy, and download never geometry-sort", () => {
  const canonicalSelection = sourceSection(
    workspaceSource,
    "function canonicalPageBlocks",
    "function ContentItemView",
  );
  const itemRenderer = sourceSection(
    workspaceSource,
    "function ContentItemView",
    "function RenderedPage",
  );
  const legacyRenderer = sourceSection(
    workspaceSource,
    "function RenderedPage",
    "function CanonicalRenderedPage",
  );
  const canonicalRenderer = sourceSection(
    workspaceSource,
    "function CanonicalRenderedPage",
    "function MarkdownSource",
  );
  const visibleOutput = sourceSection(
    workspaceSource,
    "const visibleOutput = useMemo",
    "const resetPreviewScroll",
  );
  const copyAndDownload = sourceSection(
    workspaceSource,
    "const copyOutput = async",
    "const handleFormatKeyDown",
  );
  const pageSerializer = sourceSection(
    serializerSource,
    "export function serializePageMarkdown",
    "export function serializeDocumentMarkdown",
  );
  const pageText = sourceSection(
    normalizerSource,
    "function pageText",
    "function itemMarkdown",
  );
  const pageBoundary = sourceSection(
    normalizerSource,
    "function pageBoundaryContent",
    "function orderedPages",
  );
  const normalization = sourceSection(
    normalizerSource,
    "export function normalizeDocumentJson",
    "export function serializeNormalizedDocumentJson",
  );
  const geometryAccess =
    /\bbbox\b|page_(?:width|height)|\.(?:x|y)\b/;
  const readingOrderSort =
    /\.sort\(\(left, right\) => left\.reading_order - right\.reading_order\)/;

  assert.match(legacyRenderer, readingOrderSort);
  assert.match(pageSerializer, readingOrderSort);
  assert.match(pageText, readingOrderSort);
  assert.match(pageBoundary, readingOrderSort);
  for (const section of [
    legacyRenderer,
    pageSerializer,
    pageText,
    pageBoundary,
  ]) {
    assert.doesNotMatch(section, geometryAccess);
  }

  assert.match(canonicalSelection, /page\.full\.block_ids/);
  assert.match(
    canonicalSelection,
    /\.map\(\(blockId\) => blocksById\.get\(blockId\)\)/,
  );
  assert.doesNotMatch(canonicalSelection, /\.sort\(|reading_order/);
  assert.match(canonicalRenderer, /\{blocks\.map\(\(block\) =>/);
  assert.doesNotMatch(canonicalRenderer, /\.sort\(|reading_order/);
  assert.match(
    itemRenderer,
    /if \(type === "header" \|\| type === "footer"\)[\s\S]*?\(item\.items \?\? \[\]\)[\s\S]*?\.map/,
  );
  assert.doesNotMatch(itemRenderer, /\.sort\(/);
  const itemRendererWithoutTableValidationContext = itemRenderer.replace(
    /    const tableContext =[\s\S]*?    const tableSemantics = readTableSemantics\(item, tableContext\);/,
    "",
  );
  assert.match(
    itemRenderer,
    /pageIndex: sourcePage\.page_index[\s\S]*?pageWidth: sourcePage\.page_width[\s\S]*?pageHeight: sourcePage\.page_height/,
  );
  assert.match(
    itemRenderer,
    /readTableSemantics\(item, tableContext\)/,
  );
  for (const section of [
    canonicalSelection,
    canonicalRenderer,
    itemRendererWithoutTableValidationContext,
  ]) {
    assert.doesNotMatch(section, geometryAccess);
  }

  assert.match(normalization, /const pages = orderedPages\(result\)/);
  assert.match(normalization, /items: \{ pages \}/);
  assert.match(
    visibleOutput,
    /if \(format === "json"\) return documentJsonOutput/,
  );
  assert.match(
    visibleOutput,
    /serializePageMarkdown\(currentPage, result\)/,
  );
  assert.match(workspaceSource, /<MarkdownSource value=\{visibleOutput\} \/>/);
  assert.match(
    copyAndDownload,
    /navigator\.clipboard\.writeText\(visibleOutput\)/,
  );
  assert.match(
    copyAndDownload,
    /new Blob\(\[visibleOutput\], \{ type: mime \}\)/,
  );
});
