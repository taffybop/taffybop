import {
  serializeDocumentMarkdown,
  serializePageMarkdown,
} from "./serialize-output.ts";
import { readCanonicalPresentation } from "./canonical-presentation.ts";
import {
  initialPagePresentationView,
  readRunningRegions,
} from "./running-regions.ts";
import { primaryItemText } from "./primary-item-text.ts";
import type {
  CanonicalPresentation,
  DocumentContentItem,
  PageResult,
  ParseResult,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

export const DOCUMENT_JSON_FIELDS = [
  "text",
  "markdown",
  "items",
  "metadata",
  "images_content_metadata",
  "result_content_metadata",
  "markdown_full",
  "text_full",
] as const;

export type DocumentJsonField = (typeof DOCUMENT_JSON_FIELDS)[number];

export interface DocumentJsonSummaryRow {
  field: DocumentJsonField;
  data: string;
  type: "object" | "string";
}

export interface DocumentJsonMetrics {
  pageCount: number;
  extractedPageCount: number;
  itemCount: number;
  tableCount: number;
  imageCount: number;
  averageConfidence: number | null;
  generatedFileCount: number;
}

export interface NormalizedDocumentJson {
  result_content_metadata: JsonRecord;
  canonical_presentation?: CanonicalPresentation;
  text: {
    pages: Array<{
      page_number: number | string;
      text: string;
    }>;
  };
  markdown: {
    pages: Array<{
      page_number: number | string;
      markdown: string;
      success: boolean;
      footer: string | null;
      header: string | null;
    }>;
  };
  items: {
    pages: Array<PageResult>;
  };
  metadata: {
    schema_version: string;
    document: ParseResult["document"];
    processing: ParseResult["processing"];
    warnings: string[];
    pages: JsonRecord[];
    additional_top_level_fields: JsonRecord;
  };
  images_content_metadata: JsonRecord & {
    images: unknown[];
    total_count: number;
  };
  markdown_full: string;
  text_full: string;
}

const CORE_RESULT_FIELDS = new Set([
  "schema_version",
  "document",
  "pages",
  "processing",
  "warnings",
  "result_content_metadata",
  "images_content_metadata",
  "canonical_presentation",
]);

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function scalarText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function structuredText(value: unknown): string {
  const scalar = scalarText(value);
  if (scalar) return scalar;
  if (value === null || value === undefined) return "";

  try {
    return JSON.stringify(value);
  } catch {
    return "";
  }
}

function nestedItemText(value: unknown): string {
  if (!isRecord(value)) return structuredText(value);
  return (
    scalarText(value.value) ||
    scalarText(value.text) ||
    scalarText(value.ocr_text) ||
    scalarText(value.md)
  );
}

function itemText(item: DocumentContentItem): string {
  const itemType = item.type.toLowerCase();

  if (itemType === "table") {
    return (
      scalarText(item.html) ||
      scalarText(item.md) ||
      structuredText(item.value) ||
      structuredText(item.rows)
    );
  }

  if (
    item.layout_visual_relationships_projected === true &&
    (itemType === "image" ||
      itemType === "chart" ||
      itemType === "diagram")
  ) {
    return scalarText(primaryItemText(item));
  }

  if (itemType === "image") {
    return (
      scalarText(item.ocr_text) ||
      scalarText(item.value) ||
      scalarText(item.md)
    );
  }

  if (itemType === "header" || itemType === "footer") {
    const direct = scalarText(item.md) || scalarText(item.value);
    if (direct) return direct;

    return (item.items ?? [])
      .map(nestedItemText)
      .filter(Boolean)
      .join("\n");
  }

  return (
    scalarText(item.value) ||
    scalarText(item.md) ||
    scalarText(item.ocr_text) ||
    structuredText(item.value)
  );
}

function pageText(page: PageResult): string {
  return [...page.items]
    .sort((left, right) => left.reading_order - right.reading_order)
    .map(itemText)
    .map((block) => block.trim())
    .filter(Boolean)
    .join("\n\n");
}

function itemMarkdown(item: DocumentContentItem): string {
  return scalarText(item.md) || scalarText(item.value) || itemText(item);
}

function pageBoundaryContent(
  page: PageResult,
  itemType: "header" | "footer",
): string | null {
  const blocks = [...page.items]
    .sort((left, right) => left.reading_order - right.reading_order)
    .filter((item) => item.type.toLowerCase() === itemType)
    .map(itemMarkdown)
    .filter(Boolean);

  return blocks.length ? blocks.join("\n\n") : null;
}

function orderedPages(result: ParseResult): PageResult[] {
  return [...result.pages].sort(
    (left, right) => left.page_index - right.page_index,
  );
}

function preserveAdditivePagePayload(page: PageResult): PageResult {
  // Keep additive item sidecars (including validated or malformed form
  // metadata) byte-for-byte representable in JSON output. Rendering may fail
  // closed, but normalization is not allowed to redact source API fields.
  return {
    ...page,
    items: page.items.map((item) => ({ ...item })),
  };
}

function pageMetadata(page: PageResult): JsonRecord {
  const pageRecord = page as unknown as JsonRecord;
  const metadata: JsonRecord = {};

  for (const [key, value] of Object.entries(pageRecord)) {
    if (key !== "items" && key !== "detected_images") metadata[key] = value;
  }

  return metadata;
}

function additionalTopLevelFields(result: ParseResult): JsonRecord {
  const additional: JsonRecord = {};

  for (const [key, value] of Object.entries(result)) {
    if (!CORE_RESULT_FIELDS.has(key)) additional[key] = value;
  }

  return additional;
}

function imageFingerprint(image: unknown): string {
  if (!isRecord(image)) return JSON.stringify(image);

  const bbox = isRecord(image.bbox) ? image.bbox : {};
  return JSON.stringify({
    page_index: image.page_index ?? null,
    object_index: image.object_index ?? null,
    filename: image.filename ?? null,
    index: image.index ?? null,
    x: bbox.x ?? null,
    y: bbox.y ?? null,
    width: bbox.width ?? bbox.w ?? null,
    height: bbox.height ?? bbox.h ?? null,
    pixel_width: image.pixel_width ?? null,
    pixel_height: image.pixel_height ?? null,
    text: image.ocr_text ?? image.text ?? null,
  });
}

function collectImages(
  result: ParseResult,
  suppliedMetadata: JsonRecord,
): unknown[] {
  const images: unknown[] = [];
  const fingerprints = new Set<string>();

  const add = (image: unknown, context: JsonRecord = {}) => {
    const normalized = isRecord(image)
      ? {
          ...context,
          ...image,
        }
      : image;
    const fingerprint = imageFingerprint(normalized);
    if (fingerprints.has(fingerprint)) return;
    fingerprints.add(fingerprint);
    images.push(normalized);
  };

  if (Array.isArray(suppliedMetadata.images)) {
    suppliedMetadata.images.forEach((image) => add(image));
  }

  for (const page of orderedPages(result)) {
    for (const image of page.detected_images ?? []) {
      add(image, { page_index: page.page_index });
    }
    for (const item of page.items) {
      for (const image of item.embedded_images ?? []) {
        add(image, {
          page_index: page.page_index,
          source_item_id: item.id,
        });
      }
    }
  }

  return images;
}

function normalizeImageMetadata(result: ParseResult): JsonRecord & {
  images: unknown[];
  total_count: number;
} {
  const supplied = isRecord(result.images_content_metadata)
    ? result.images_content_metadata
    : {};
  const images = collectImages(result, supplied);
  const suppliedCount = finiteNumber(supplied.total_count);
  const declaredCount = finiteNumber(result.document.image_count);
  const totalCount = Math.max(
    images.length,
    Math.max(suppliedCount ?? 0, declaredCount ?? 0),
  );

  return {
    ...supplied,
    images,
    total_count: totalCount,
  };
}

function normalizedResultMetadata(result: ParseResult): JsonRecord {
  return isRecord(result.result_content_metadata)
    ? { ...result.result_content_metadata }
    : {};
}

export function normalizeDocumentJson(
  result: ParseResult,
): NormalizedDocumentJson {
  const canonical = readCanonicalPresentation(result);
  const pagePresentationView = initialPagePresentationView(
    canonical ? readRunningRegions(result, canonical) : null,
  );
  const canonicalPages = new Map(
    (canonical?.pages ?? []).map((page) => [page.page_index, page]),
  );
  const pages = orderedPages(result).map(preserveAdditivePagePayload);
  const textPages = pages.map((page) => {
    const canonicalPage = canonicalPages.get(page.page_index);
    return {
      page_number: page.page_number,
      text: canonicalPage?.[pagePresentationView].text ?? pageText(page),
    };
  });
  const markdownPages = pages.map((page) => {
    const canonicalPage = canonicalPages.get(page.page_index);
    return {
      page_number: page.page_number,
      markdown:
        canonicalPage?.[pagePresentationView].markdown ??
        serializePageMarkdown(page).trimEnd(),
      success: page.success,
      footer: canonicalPage
        ? canonicalPage.footer.block_ids.length
          ? canonicalPage.footer.markdown
          : null
        : pageBoundaryContent(page, "footer"),
      header: canonicalPage
        ? canonicalPage.header.block_ids.length
          ? canonicalPage.header.markdown
          : null
        : pageBoundaryContent(page, "header"),
    };
  });
  const textFull =
    canonical?.full.text ??
    textPages
      .map((page) => page.text.trim())
      .filter(Boolean)
      .join("\n\n");

  return {
    result_content_metadata: normalizedResultMetadata(result),
    ...(canonical ? { canonical_presentation: canonical } : {}),
    text: { pages: textPages },
    markdown: { pages: markdownPages },
    items: { pages },
    metadata: {
      schema_version: result.schema_version,
      document: result.document,
      processing: result.processing,
      warnings: result.warnings,
      pages: pages.map(pageMetadata),
      additional_top_level_fields: additionalTopLevelFields(result),
    },
    markdown_full: canonical?.full.markdown ?? serializeDocumentMarkdown(result),
    text_full: textFull,
    images_content_metadata: normalizeImageMetadata(result),
  };
}

export function serializeNormalizedDocumentJson(
  result: ParseResult,
  pretty = true,
): string {
  return JSON.stringify(
    normalizeDocumentJson(result),
    null,
    pretty ? 2 : undefined,
  );
}

function recordConfidence(record: unknown): number | null {
  if (!isRecord(record)) return null;
  const direct = finiteNumber(record.confidence);
  if (direct !== null) return direct;

  const boxes = Array.isArray(record.bbox)
    ? record.bbox
    : record.bbox === undefined || record.bbox === null
      ? []
      : [record.bbox];
  const boxConfidences = boxes
    .map((bbox) => (isRecord(bbox) ? finiteNumber(bbox.confidence) : null))
    .filter((value): value is number => value !== null);

  if (!boxConfidences.length) return null;
  return (
    boxConfidences.reduce((total, value) => total + value, 0) /
    boxConfidences.length
  );
}

function averageConfidence(document: NormalizedDocumentJson): number | null {
  const pageConfidences = document.metadata.pages
    .map(recordConfidence)
    .filter((value): value is number => value !== null);
  const fallbackConfidences = document.items.pages.flatMap((page) => [
    ...page.items
      .map(recordConfidence)
      .filter((value): value is number => value !== null),
    ...(page.detected_images ?? [])
      .map(recordConfidence)
      .filter((value): value is number => value !== null),
  ]);
  const values = pageConfidences.length
    ? pageConfidences
    : fallbackConfidences;

  if (!values.length) return null;
  return values.reduce((total, value) => total + value, 0) / values.length;
}

function generatedFileCount(metadata: JsonRecord): number {
  const explicitFiles = metadata.files;
  if (Array.isArray(explicitFiles)) {
    return explicitFiles.filter((file) => {
      if (!isRecord(file)) return true;
      return file.exists !== false;
    }).length;
  }

  return Object.values(metadata).filter((value) => {
    if (!isRecord(value) || value.exists === false) return false;
    return (
      value.exists === true ||
      typeof value.presigned_url === "string" ||
      typeof value.url === "string" ||
      typeof value.filename === "string"
    );
  }).length;
}

export function getDocumentJsonMetrics(
  document: NormalizedDocumentJson,
): DocumentJsonMetrics {
  const itemCount = document.items.pages.reduce(
    (total, page) => total + page.items.length,
    0,
  );
  const tableCount = document.items.pages.reduce(
    (total, page) =>
      total +
      page.items.filter((item) => item.type.toLowerCase() === "table").length,
    0,
  );
  const declaredPageCount = finiteNumber(document.metadata.document.page_count);

  return {
    pageCount: Math.max(
      declaredPageCount === null ? 0 : Math.trunc(declaredPageCount),
      document.items.pages.length,
    ),
    extractedPageCount: document.items.pages.length,
    itemCount,
    tableCount,
    imageCount: document.images_content_metadata.total_count,
    averageConfidence: averageConfidence(document),
    generatedFileCount: generatedFileCount(
      document.result_content_metadata,
    ),
  };
}

function plural(count: number, singular: string): string {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}

function characterSummary(value: string): string {
  return value ? plural(value.length, "character") : "empty";
}

export function summarizeDocumentJson(
  document: NormalizedDocumentJson,
): DocumentJsonSummaryRow[] {
  const metrics = getDocumentJsonMetrics(document);
  const confidence =
    metrics.averageConfidence === null
      ? "avg confidence unavailable"
      : `avg confidence ${Math.round(metrics.averageConfidence * 100)}%`;

  const data: Record<DocumentJsonField, string> = {
    result_content_metadata: metrics.generatedFileCount
      ? plural(metrics.generatedFileCount, "generated file")
      : "no generated files",
    text: plural(document.text.pages.length, "page"),
    markdown: plural(document.markdown.pages.length, "page"),
    items: `${plural(metrics.extractedPageCount, "page")} · ${plural(
      metrics.itemCount,
      "item",
    )} · ${plural(metrics.tableCount, "table")}`,
    metadata: `${plural(metrics.pageCount, "page")} · ${confidence}`,
    images_content_metadata: plural(metrics.imageCount, "image"),
    markdown_full: characterSummary(document.markdown_full),
    text_full: characterSummary(document.text_full),
  };

  const types: Record<DocumentJsonField, "object" | "string"> = {
    result_content_metadata: "object",
    text: "object",
    markdown: "object",
    items: "object",
    metadata: "object",
    images_content_metadata: "object",
    markdown_full: "string",
    text_full: "string",
  };

  return DOCUMENT_JSON_FIELDS.map((field) => ({
    field,
    data: data[field],
    type: types[field],
  }));
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Find the opening quote of a top-level field in two-space pretty-printed JSON.
 * Nested fields are ignored because they are indented by four or more spaces.
 */
export function findTopLevelFieldOffset(
  json: string,
  field: DocumentJsonField,
): number | null {
  const serializedField = JSON.stringify(field);
  const pattern = new RegExp(
    `(?:^|\\n)  ${escapeRegExp(serializedField)}\\s*:`,
  );
  const match = pattern.exec(json);
  if (!match) return null;

  const lineStart = match.index + (match[0].startsWith("\n") ? 1 : 0);
  return lineStart + 2;
}
