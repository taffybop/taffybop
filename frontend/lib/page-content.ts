import { readChartResolution } from "./chart-resolution.ts";
import { primaryItemText } from "./primary-item-text.ts";
import type { PageResult } from "./types.ts";

/**
 * Decide whether a raw physical page has a renderable primary representation.
 * A terminal chart is content only after the same strict sidecar validation
 * used by its renderer succeeds.
 */
export function pageHasContent(
  page: PageResult,
  sourceSha256?: string,
  renderSourceSha256?: string,
): boolean {
  return page.items.some((item) => {
    if (
      item.type === "chart" &&
      readChartResolution(
        item,
        page,
        sourceSha256,
        renderSourceSha256,
      ) !== null
    ) {
      return true;
    }
    if (item.type === "table") return Boolean(item.rows?.length);
    if (item.type === "list") return Boolean(item.items?.length);
    return Boolean(primaryItemText(item).trim());
  });
}
