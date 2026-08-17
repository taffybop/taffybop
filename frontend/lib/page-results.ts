import type { PageResult, ParseResult } from "@/lib/types";

export interface PhysicalPageMap {
  byPageNumber: Map<number, PageResult>;
  usesZeroBasedIndexes: boolean;
}

/**
 * Maps parser pages to one-based physical document pages or image frames.
 *
 * The current API contract is one-based. The zero-based branch is a defensive
 * compatibility path for gateways or older adapters that may preserve a
 * zero-based `page_index`. Printed `page_number` and `page_label` are never
 * used for physical navigation.
 */
export function mapPhysicalPages(result: ParseResult): PhysicalPageMap {
  const usesZeroBasedIndexes = result.pages.some(
    (page) => Number(page.page_index) === 0,
  );
  const byPageNumber = new Map<number, PageResult>();
  const physicalPageCount = Math.max(
    Math.trunc(Number(result.document.page_count)) || 0,
    0,
  );

  for (const page of result.pages) {
    const rawIndex = Number(page.page_index);
    if (!Number.isInteger(rawIndex)) continue;

    const physicalPageNumber = usesZeroBasedIndexes
      ? rawIndex + 1
      : rawIndex;
    if (
      physicalPageNumber < 1 ||
      (physicalPageCount > 0 && physicalPageNumber > physicalPageCount) ||
      byPageNumber.has(physicalPageNumber)
    ) {
      continue;
    }

    byPageNumber.set(physicalPageNumber, page);
  }

  return { byPageNumber, usesZeroBasedIndexes };
}

export function getPhysicalPageCount(
  result: ParseResult | null,
  previewPageCount: number,
): number {
  if (previewPageCount > 0) return Math.trunc(previewPageCount);
  if (!result) return 0;

  const metadataCount = Math.trunc(Number(result.document.page_count)) || 0;
  if (metadataCount > 0) return metadataCount;

  const { byPageNumber } = mapPhysicalPages(result);
  return Math.max(0, ...byPageNumber.keys());
}
