import type { DocumentContentItem } from "./types.ts";

function nonEmptyString(value: unknown): string {
  return typeof value === "string" && value.trim() ? value : "";
}

/**
 * Select text that a primary document view may expose.
 *
 * `value` and `md` are explicit P03-US02 primary representations. Raw OCR is
 * only a compatibility fallback, and an explicit false promotion decision is
 * a hard boundary on marked P03-US02 projections. Unmarked legacy responses
 * retain their established value/OCR/Markdown precedence.
 */
export function primaryItemText(item: DocumentContentItem): string {
  if (item.layout_visual_relationships_projected !== true) {
    if (typeof item.value === "string") return item.value;
    if (typeof item.ocr_text === "string") return item.ocr_text;
    if (typeof item.md === "string") return item.md;
    return "";
  }

  const value = nonEmptyString(item.value);
  if (value) return value;

  const markdown = nonEmptyString(item.md);
  if (markdown) return markdown;
  if (item.include_ocr_in_primary !== true) return "";
  return nonEmptyString(item.ocr_text);
}
