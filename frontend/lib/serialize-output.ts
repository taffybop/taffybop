import type {
  DocumentContentItem,
  PagePresentationView,
  PageResult,
  ParseOutputFormat,
  ParseResult,
  SerializedOutput,
} from "@/lib/types";
import {
  findCanonicalPage,
  readCanonicalPresentation,
} from "./canonical-presentation.ts";

function scalarText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (
    typeof value === "boolean" ||
    (typeof value === "number" && Number.isFinite(value))
  ) {
    return String(value);
  }
  return "";
}

export function serializeItemMarkdown(item: DocumentContentItem): string {
  // The frontend is a renderer, not a second document parser. The normalized
  // backend item is authoritative; only a scalar value is used as a defensive
  // fallback for additive/older schemas that omit `md`.
  return scalarText(item.md) || scalarText(item.value);
}

export function serializePageMarkdown(
  page: PageResult,
  result?: ParseResult,
  view: PagePresentationView = "full",
): string {
  if (result) {
    const canonical = readCanonicalPresentation(result);
    if (canonical) return findCanonicalPage(canonical, page)[view].markdown;
  }

  const blocks = [...page.items]
    .sort((left, right) => left.reading_order - right.reading_order)
    .map(serializeItemMarkdown)
    .map((block) => block.trim())
    .filter(Boolean);

  return blocks.length ? `${blocks.join("\n\n")}\n` : "";
}

export function serializeDocumentMarkdown(result: ParseResult): string {
  const canonical = readCanonicalPresentation(result);
  if (canonical) return canonical.full.markdown;

  const markdown = [...result.pages]
    .sort((left, right) => left.page_index - right.page_index)
    .map((page) => serializePageMarkdown(page))
    .map((page) => page.trim())
    .filter(Boolean)
    .join("\n\n");

  return markdown ? `${markdown}\n` : "";
}

export function serializePageJson(page: PageResult, pretty = true): string {
  return JSON.stringify(page, null, pretty ? 2 : undefined);
}

export function serializeDocumentJson(
  result: ParseResult,
  pretty = true,
): string {
  return JSON.stringify(result, null, pretty ? 2 : undefined);
}

export function serializePageOutput(
  page: PageResult,
  outputFormat: ParseOutputFormat,
  result?: ParseResult,
  view: PagePresentationView = "full",
): SerializedOutput {
  if (outputFormat === "markdown") {
    return {
      content: serializePageMarkdown(page, result, view),
      contentType: "text/markdown",
      extension: "md",
    };
  }

  return {
    content: serializePageJson(page),
    contentType: "application/json",
    extension: "json",
  };
}

export function serializeDocumentOutput(
  result: ParseResult,
  outputFormat: ParseOutputFormat,
): SerializedOutput {
  if (outputFormat === "markdown") {
    return {
      content: serializeDocumentMarkdown(result),
      contentType: "text/markdown",
      extension: "md",
    };
  }

  return {
    content: serializeDocumentJson(result),
    contentType: "application/json",
    extension: "json",
  };
}
