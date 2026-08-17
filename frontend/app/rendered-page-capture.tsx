import { FileText } from "lucide-react";
import type { ReactNode } from "react";

import {
  findCanonicalPage,
  readCanonicalPresentation,
} from "@/lib/canonical-presentation";
import { readOutlineStructures } from "@/lib/outline-structure";
import { mapPhysicalPages } from "@/lib/page-results";
import { readRunningRegions } from "@/lib/running-regions";
import type { PagePresentationView, ParseResult } from "@/lib/types";
import {
  CanonicalRenderedPage,
  RenderedPage,
  canonicalPageBlocks,
} from "./clearleaf-workspace";

const EMPTY_OUTLINE_STRUCTURES = new Map();

export interface RenderedPageCaptureProps {
  result: ParseResult;
  pageNumber: number;
  pagePresentationView?: PagePresentationView;
}

function EmptyRenderedPage({
  canonical,
  pageNumber,
}: {
  canonical: boolean;
  pageNumber: number;
}) {
  return (
    <div className="result-empty-state">
      <div className="result-empty-icon">
        <FileText aria-hidden="true" size={30} />
      </div>
      <h3>
        {canonical
          ? "No canonical content is available for page "
          : "No extracted content is available for page "}
        {pageNumber}.
      </h3>
      <p>
        The document page remains available in the preview. The interface will
        not substitute{" "}
        {canonical ? "legacy or omitted content" : "content from another page"}.
      </p>
    </div>
  );
}

/**
 * Produce the exact rendered-result subtree used by TaffyBopWorkspace for a
 * successful parse. This is intentionally a React component, rather than a
 * Markdown-to-HTML helper, so table semantics, canonical custody, forms,
 * outlines, text runs, notes, and running-region validation remain identical
 * to the interactive UI.
 */
export function RenderedPageCapture({
  result,
  pageNumber,
  pagePresentationView = "body",
}: RenderedPageCaptureProps): ReactNode {
  if (!Number.isSafeInteger(pageNumber) || pageNumber < 1) {
    throw new Error("pageNumber must be a positive integer");
  }

  const sourcePage = mapPhysicalPages(result).byPageNumber.get(pageNumber);
  if (!sourcePage) {
    throw new Error(`No public parser page maps to physical page ${pageNumber}`);
  }

  const canonicalPresentation = readCanonicalPresentation(result);
  if (!canonicalPresentation) {
    return (
      <RenderedPage
        page={sourcePage}
        sourceSha256={result.document.sha256 ?? ""}
      />
    );
  }

  // TaffyBopWorkspace performs this validation even though the result is used
  // mainly by its Body/Full toggle and printed-page navigation. Captures must
  // therefore fail on the same inconsistent sidecars as the interactive UI.
  readRunningRegions(result, canonicalPresentation);

  const canonicalPage = findCanonicalPage(canonicalPresentation, sourcePage);
  const outlineStructures = Object.prototype.hasOwnProperty.call(
    result.processing,
    "outline_structure",
  )
    ? readOutlineStructures(result, canonicalPresentation)
    : EMPTY_OUTLINE_STRUCTURES;
  const blocks = canonicalPageBlocks(canonicalPage, pagePresentationView);
  if (!blocks.length) {
    return <EmptyRenderedPage canonical pageNumber={pageNumber} />;
  }

  return (
    <CanonicalRenderedPage
      page={canonicalPage}
      blocks={blocks}
      sourcePage={sourcePage}
      sourceSha256={result.document.sha256 ?? ""}
      outlineStructures={outlineStructures}
    />
  );
}
