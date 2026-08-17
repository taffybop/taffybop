"use client";

import {
  AlertTriangle,
  ArrowLeft,
  Braces,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Code2,
  Copy,
  Download,
  ExternalLink,
  Eye,
  FileText,
  Loader2,
  Maximize2,
  Plus,
  RefreshCw,
  RotateCcw,
  Scan,
  Upload,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import dynamic from "next/dynamic";
import Image from "next/image";
import Link from "next/link";
import {
  createElement,
  memo,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  DocumentApiError,
  getBrowserPreviewKind,
  getConfiguredMaxUploadBytes,
  getParseApiLabel,
  parseJson,
  stripSupportedDocumentExtension,
  SUPPORTED_DOCUMENT_ACCEPT,
  SUPPORTED_DOCUMENT_FORMATS,
  validateDocumentFile,
} from "@/lib/document-api";
import {
  findCanonicalPage,
  readCanonicalPresentation,
} from "@/lib/canonical-presentation";
import {
  serializePageMarkdown,
} from "@/lib/serialize-output";
import {
  normalizeDocumentJson,
  summarizeDocumentJson,
} from "@/lib/normalize-document-json";
import {
  getPhysicalPageCount,
  mapPhysicalPages,
} from "@/lib/page-results";
import { primaryItemText } from "@/lib/primary-item-text";
import { readTableSemantics } from "@/lib/table-semantics";
import {
  resolveCanonicalCaptionLink,
  resolveCanonicalCaptionedTableLink,
  resolveCanonicalNoteLink,
} from "@/lib/layout-relationships";
import {
  readTextRunSemantics,
  renderCanonicalTextRunOverlay,
  renderValidatedTextRunOverlay,
} from "@/lib/text-run-semantics";
import {
  readFormSemanticsForCanonicalBlock,
  renderValidatedFormSemantics,
} from "@/lib/form-semantics";
import {
  readDiagramSemanticsForCanonicalBlock,
  renderValidatedDiagramSemantics,
} from "@/lib/diagram-semantics";
import {
  pageDisplayLabel,
  readRunningRegions,
  RunningRegionValidationError,
  type ValidatedRunningRegions,
} from "@/lib/running-regions";
import {
  readOutlineStructures,
  renderValidatedOutlineStructure,
  type ValidatedOutlineContinuationSource,
  type ValidatedOutlineItemSource,
  type ValidatedOutlineStructure,
} from "@/lib/outline-structure";
import type {
  CanonicalBlock,
  CanonicalPage,
  DocumentContentItem,
  OutlineContinuation,
  OutlineItem,
  PageResult,
  PagePresentationView,
  ParseOutputFormat,
  ParseResult,
  TextRunTargetPath,
} from "@/lib/types";
import { DocumentJsonView } from "./json-document-view";
import { ImagePagePreview } from "./image-page-preview";
import type { PdfFitMode } from "./pdf-page-preview";

type RequestState = "idle" | "selected" | "submitting" | "success" | "error";
type MarkdownMode = "rendered" | "source";
type MobilePane = "document" | "results";

const PdfPagePreview = dynamic(
  () =>
    import("./pdf-page-preview").then((module) => module.PdfPagePreview),
  { ssr: false },
);

const EMPTY_OUTLINE_STRUCTURES: ReadonlyMap<string, ValidatedOutlineStructure> =
  new Map();

interface UiError {
  title: string;
  message: string;
  code?: string;
  status?: number | null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && value >= 1024; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value >= 10 ? value.toFixed(1) : value.toFixed(2)} ${unit}`;
}

function cleanBaseName(filename: string): string {
  const withoutExtension = stripSupportedDocumentExtension(filename);
  const safe = withoutExtension
    .normalize("NFKD")
    .replace(/[^\w.-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return safe || "document";
}

function itemText(item: DocumentContentItem): string {
  return primaryItemText(item);
}

function itemTableText(item: DocumentContentItem): string {
  if (!Array.isArray(item.rows)) return "";
  return item.rows
    .map((row) => row.join("\t").replace(/\t+$/u, ""))
    .join("\n")
    .trim();
}

function tableItemAuthority(
  item: DocumentContentItem,
): "canonical" | "candidate" | null {
  const type = item.type.toLowerCase();
  const gate =
    typeof item.table_candidate_gate === "object" &&
    item.table_candidate_gate !== null
      ? (item.table_candidate_gate as Record<string, unknown>)
      : null;
  if (
    type === "table" &&
    (Object.hasOwn(item, "table_evidence") ||
      gate?.outcome === "canonical_table")
  ) {
    return "canonical";
  }
  if (type !== "table_candidate" || gate?.outcome !== "unresolved") {
    return null;
  }
  const reasons = item.table_candidate_gate_reasons;
  const ownerIds = gate.owner_item_ids;
  const featureScores =
    typeof gate.feature_scores === "object" && gate.feature_scores !== null
      ? (gate.feature_scores as Record<string, unknown>)
      : null;
  const tableSupport = featureScores?.table_support;
  const rows = item.rows;
  const columnCount = item.column_count;
  if (
    !Array.isArray(reasons) ||
    reasons.length !== 1 ||
    reasons[0] !== "upstream_reconciliation_unresolved" ||
    !Array.isArray(ownerIds) ||
    ownerIds.length !== 0 ||
    typeof tableSupport !== "number" ||
    tableSupport < 0.62 ||
    !Array.isArray(rows) ||
    rows.length < 2 ||
    typeof columnCount !== "number" ||
    columnCount < 2 ||
    !rows.every((row) => row.length === columnCount)
  ) {
    return null;
  }
  return "candidate";
}

function errorForUi(error: unknown): UiError {
  if (error instanceof RunningRegionValidationError) {
    return {
      title: "Parser returned invalid page layout data",
      message:
        "The response could not be shown safely because its running-region projection was inconsistent.",
      code: error.code,
      status: null,
    };
  }

  if (error instanceof DocumentApiError) {
    if (error.kind === "timeout") {
      return {
        title: "Parsing timed out",
        message:
          "The document took longer than the configured limit. Your file is still selected, so you can retry.",
        code: error.code,
        status: error.status,
      };
    }
    if (error.kind === "network") {
      return {
        title: "Parser could not be reached",
        message:
          "Check that the parsing API is running and that the frontend API URL or proxy is configured correctly.",
        code: error.code,
        status: error.status,
      };
    }
    if (error.kind === "empty") {
      return {
        title: "No extractable content",
        message:
          "The parser returned no pages or content for this document. You can choose another file or retry.",
        code: error.code,
        status: error.status,
      };
    }
    if (error.code === "unsupported_document_type") {
      return {
        title: "Choose a supported document",
        message: `Supported formats are ${SUPPORTED_DOCUMENT_FORMATS}. The filename extension and file type must agree.`,
        code: error.code,
        status: error.status,
      };
    }
    if (error.code === "upload_too_large") {
      return {
        title: "Document is too large",
        message: `${error.message} The current frontend limit is ${formatBytes(
          getConfiguredMaxUploadBytes(),
        )}.`,
        code: error.code,
        status: error.status,
      };
    }
    if (error.code === "invalid_image") {
      return {
        title: "Image could not be read",
        message:
          "The image is empty, damaged, or does not match its declared format. Choose another image and retry.",
        code: error.code,
        status: error.status,
      };
    }
    if (error.code === "image_pixel_limit_exceeded") {
      return {
        title: "Image dimensions are too large",
        message:
          "The decoded image exceeds the parser's pixel limit. Resize the image or choose a smaller source.",
        code: error.code,
        status: error.status,
      };
    }
    if (error.code === "page_limit_exceeded") {
      return {
        title: "Document has too many pages",
        message:
          "This PDF or multi-frame TIFF exceeds the parser's configured page limit.",
        code: error.code,
        status: error.status,
      };
    }
    return {
      title:
        error.kind === "validation"
          ? "Document could not be accepted"
          : "Parsing failed",
      message: error.message,
      code: error.code,
      status: error.status,
    };
  }

  return {
    title: "Something went wrong",
    message: "The document could not be processed. Please retry.",
  };
}

function pageHasContent(page: PageResult): boolean {
  return page.items.some((item) => {
    if (item.type === "table") return Boolean(item.rows?.length);
    if (item.type === "list") return Boolean(item.items?.length);
    return Boolean(itemText(item).trim());
  });
}

function canonicalPageBlocks(
  page: CanonicalPage,
  view: PagePresentationView = "full",
): CanonicalBlock[] {
  const blocksById = new Map(
    page.blocks.map((block) => [block.id, block]),
  );
  const blockIds =
    view === "body" ? page.body.block_ids : page.full.block_ids;

  return blockIds
    .map((blockId) => blocksById.get(blockId))
    .filter(
      (block): block is CanonicalBlock =>
        block !== undefined && block.omission_reason == null,
    );
}

const ContentItemView = memo(function ContentItemView({
  item,
  sourcePage,
  sourceSha256,
}: {
  item: DocumentContentItem;
  sourcePage?: PageResult;
  sourceSha256?: string;
}) {
  const type = item.type.toLowerCase();
  const value = itemText(item);
  // A mounted parse-result graph is immutable. Parse completion atomically
  // replaces its item/page references; same-identity mutation is unsupported.
  // Object identity is therefore a safe validation-cache boundary for rerenders.
  const textRunSemantics = type === "table" ? null : readTextRunSemantics(item);
  const valueOverlay = textRunSemantics
    ? renderValidatedTextRunOverlay(textRunSemantics, ["value"], item.id)
    : null;

  if (type === "heading") {
    const level = Math.min(Math.max(Number(item.level) || 1, 1), 6);
    const visualLevel = Math.min(level + 1, 6);
    return createElement(
      `h${visualLevel}`,
      {
        className: `parsed-heading parsed-heading-${level}`,
        "data-item-type": type,
      },
      valueOverlay ?? value,
    );
  }

  if (type === "caption") {
    return value ? (
      <p
        className="parsed-caption"
        data-caption-of={
          typeof item.caption_of === "string"
            ? item.caption_of
            : undefined
        }
        data-item-type={type}
      >
        {valueOverlay ?? value}
      </p>
    ) : null;
  }

  if (type === "source_note" || type === "footnote") {
    const relationshipType =
      type === "source_note" ? "source_note_of" : "footnote_of";
    const noteOf =
      type === "source_note" ? item.source_note_of : item.footnote_of;
    const conflictingNoteOf =
      type === "source_note" ? item.footnote_of : item.source_note_of;
    const hasTypedRelationship =
      typeof noteOf === "string" &&
      noteOf.length > 0 &&
      conflictingNoteOf === undefined &&
      item.relationship_type === relationshipType &&
      typeof item.relationship_id === "string" &&
      item.relationship_id.length > 0;

    return value ? (
      <p
        className={`parsed-note parsed-${type.replace("_", "-")}`}
        data-item-type={type}
        data-note-id={item.id}
        data-note-kind={type}
        data-note-of={hasTypedRelationship ? noteOf : undefined}
        data-relationship-id={
          hasTypedRelationship ? item.relationship_id : undefined
        }
      >
        {valueOverlay ?? value}
      </p>
    ) : null;
  }

  const tableAuthority = tableItemAuthority(item);
  if (tableAuthority) {
    const tableContext =
      sourcePage && sourceSha256 && sourcePage.unit === "pt"
        ? {
            sourceSha256,
            pageIndex: sourcePage.page_index,
            pageWidth: sourcePage.page_width,
            pageHeight: sourcePage.page_height,
            unit: "pt" as const,
          }
        : undefined;
    const tableSemantics = readTableSemantics(item, tableContext);
    if (tableSemantics) {
      const renderSemanticCell = (
        cell: (typeof tableSemantics.cells)[number],
      ) => {
        const CellTag = cell.columnHeader || cell.rowHeader ? "th" : "td";
        const scope = cell.columnHeader
          ? "col"
          : cell.rowHeader
            ? "row"
            : undefined;
        return (
          <CellTag
            colSpan={cell.colSpan}
            data-cell-id={cell.id}
            data-source={cell.source}
            key={cell.id}
            rowSpan={cell.rowSpan}
            scope={scope}
            style={{ whiteSpace: "pre-wrap" }}
          >
            {cell.text}
          </CellTag>
        );
      };
      const headerRows = tableSemantics.rows.slice(
        0,
        tableSemantics.headerRowCount,
      );
      const bodyRows = tableSemantics.rows.slice(
        tableSemantics.headerRowCount,
      );
      return (
        <div
          className="parsed-table-wrap"
          data-item-type={type}
          data-table-authority={tableAuthority}
          data-table-policy={tableSemantics.policyId}
          data-table-id={tableSemantics.tableId}
        >
          <table className="parsed-table">
            {headerRows.length ? (
              <thead>
                {headerRows.map((row) => (
                  <tr key={`${tableSemantics.tableId}-row-${row.row}`}>
                    {row.cells.map(renderSemanticCell)}
                  </tr>
                ))}
              </thead>
            ) : null}
            {bodyRows.length ? (
              <tbody>
                {bodyRows.map((row) => (
                  <tr key={`${tableSemantics.tableId}-row-${row.row}`}>
                    {row.cells.map(renderSemanticCell)}
                  </tr>
                ))}
              </tbody>
            ) : null}
          </table>
        </div>
      );
    }

    const rows = item.rows ?? [];
    if (!rows.length) return null;
    const columnCount = Math.max(...rows.map((row) => row.length));
    const hasSpanningTitle =
      rows.length >= 3 &&
      columnCount >= 3 &&
      rows[0].length === columnCount &&
      rows[0][0]?.trim().length > 0 &&
      rows[0].slice(1).every((cell) => cell.trim().length === 0) &&
      rows[1].length === columnCount &&
      rows[1].every((cell) => cell.trim().length > 0);
    const bodyStart = hasSpanningTitle ? 2 : 1;
    return (
      <div
        className="parsed-table-wrap"
        data-item-type={type}
        data-table-authority={tableAuthority}
      >
        <table className="parsed-table">
          <thead>
            {hasSpanningTitle ? (
              <>
                <tr>
                  <th colSpan={columnCount}>{rows[0][0]}</th>
                </tr>
                <tr>
                  {rows[1].map((cell, index) => (
                    <th key={`${item.id}-header-${index}`}>{cell}</th>
                  ))}
                </tr>
              </>
            ) : (
              <tr>
                {rows[0].map((cell, index) => (
                  <th key={`${item.id}-header-${index}`}>
                    {(() => {
                      const matchingCellIndexes = (item.cells ?? [])
                        .map((candidate, candidateIndex) => ({
                          candidate,
                          candidateIndex,
                        }))
                        .filter(
                          ({ candidate }) =>
                            candidate.row === 0 &&
                            candidate.column === index &&
                            candidate.text === cell,
                        )
                        .map(({ candidateIndex }) => candidateIndex);
                      return textRunSemantics &&
                        matchingCellIndexes.length === 1
                        ? renderValidatedTextRunOverlay(
                            textRunSemantics,
                            ["cells", matchingCellIndexes[0], "text"],
                            item.id,
                          ) ?? cell
                        : cell;
                    })()}
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {rows.slice(bodyStart).map((row, rowIndex) => (
              <tr key={`${item.id}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${item.id}-${rowIndex}-${cellIndex}`}>
                    {(() => {
                      const physicalRow = rowIndex + bodyStart;
                      const matchingCellIndexes = (item.cells ?? [])
                        .map((candidate, candidateIndex) => ({
                          candidate,
                          candidateIndex,
                        }))
                        .filter(
                          ({ candidate }) =>
                            candidate.row === physicalRow &&
                            candidate.column === cellIndex &&
                            candidate.text === cell,
                        )
                        .map(({ candidateIndex }) => candidateIndex);
                      return textRunSemantics &&
                        matchingCellIndexes.length === 1
                        ? renderValidatedTextRunOverlay(
                            textRunSemantics,
                            ["cells", matchingCellIndexes[0], "text"],
                            item.id,
                          ) ?? cell
                        : cell;
                    })()}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (type === "list") {
    const entries = item.items ?? [];
    if (!entries.length) return null;
    const ListTag = item.ordered ? "ol" : "ul";
    return (
      <ListTag className="parsed-list" data-item-type={type}>
        {entries.map((entry, index) => {
          const entryValue =
            typeof entry.value === "string"
              ? entry.value
              : typeof entry.text === "string"
                ? entry.text
                : "";
          const entryTarget: TextRunTargetPath =
            typeof entry.value === "string"
              ? ["items", index, "value"]
              : ["items", index, "text"];
          const entryOverlay = textRunSemantics
            ? renderValidatedTextRunOverlay(
                textRunSemantics,
                entryTarget,
                item.id,
              )
            : null;
          return (
            <li
              key={`${item.id}-entry-${index}`}
              style={{ marginLeft: `${Math.max(Number(entry.level) || 0, 0) * 18}px` }}
            >
              {entryOverlay ?? entryValue}
            </li>
          );
        })}
      </ListTag>
    );
  }

  if (type === "image") {
    if (!value) return null;
    return (
      <figure className="parsed-image-text" data-item-type={type}>
        <figcaption>Text detected in image</figcaption>
        <p>{valueOverlay ?? value}</p>
      </figure>
    );
  }

  if (type === "code" || type === "formula") {
    return value ? (
      <pre className="parsed-code" data-item-type={type}>
        {valueOverlay ?? value}
      </pre>
    ) : null;
  }

  if (type === "header" || type === "footer") {
    const nested = (item.items ?? [])
      .map((entry) =>
        typeof entry.value === "string"
          ? entry.value
          : typeof entry.text === "string"
            ? entry.text
            : "",
      )
      .filter(Boolean);
    const content = nested.length ? nested.join(" · ") : value;
    const contentOverlay = nested.length ? null : valueOverlay;
    return content ? (
      <p className={`parsed-${type}`} data-item-type={type}>
        {contentOverlay ?? content}
      </p>
    ) : null;
  }

  return value ? (
    <p className="parsed-paragraph" data-item-type={type}>
      {valueOverlay ?? value}
    </p>
  ) : null;
});

function RenderedPage({
  page,
  sourceSha256,
}: {
  page: PageResult;
  sourceSha256: string;
}) {
  if (!pageHasContent(page)) {
    return (
      <div className="inline-empty">
        <FileText aria-hidden="true" size={22} />
        <p>No extractable content was found on this page.</p>
      </div>
    );
  }

  return (
    <article
      className="rendered-page"
      aria-label={`Extracted content for physical page ${page.page_index}`}
    >
      {page.items
        .slice()
        .sort((left, right) => left.reading_order - right.reading_order)
        .map((item) => (
          <ContentItemView
            key={item.id}
            item={item}
            sourcePage={page}
            sourceSha256={sourceSha256}
          />
        ))}
    </article>
  );
}

function renderOutlineItemTextRun(
  item: OutlineItem,
  source: ValidatedOutlineItemSource,
): ReactNode | null {
  if (/[\u0000-\u001f\u007f\u2028\u2029]/u.test(item.body_text)) {
    return null;
  }
  const semantics = readTextRunSemantics(source.sourceItem);
  if (!semantics) return null;
  const targetKey = JSON.stringify(source.targetPath);
  const target = semantics.targets.get(targetKey);
  if (!target || target.value !== source.value) return null;
  if (item.marker_ownership === "separate") {
    return renderValidatedTextRunOverlay(
      semantics,
      source.targetPath,
      `outline-${item.id}`,
    );
  }

  const prefixLength = Array.from(
    `${item.raw_marker}${item.marker_separator}`,
  ).length;
  const targetRuns = semantics.runs.filter(
    (run) => JSON.stringify(run.target_path) === targetKey,
  );
  if (
    targetRuns.some(
      (run) => run.start < prefixLength && run.end > prefixLength,
    )
  ) {
    return null;
  }
  const bodyRuns = targetRuns
    .filter((run) => run.start >= prefixLength)
    .map((run) => ({
      ...run,
      start: run.start - prefixLength,
      end: run.end - prefixLength,
    }));
  if (!bodyRuns.length) return null;
  const adjustedTargets = new Map(semantics.targets);
  adjustedTargets.set(targetKey, { ...target, value: item.body_text });
  return renderValidatedTextRunOverlay(
    {
      ...semantics,
      runs: [
        ...semantics.runs.filter(
          (run) => JSON.stringify(run.target_path) !== targetKey,
        ),
        ...bodyRuns,
      ],
      targets: adjustedTargets,
    },
    source.targetPath,
    `outline-${item.id}`,
  );
}

function renderOutlineContinuation(
  _continuation: OutlineContinuation,
  source: ValidatedOutlineContinuationSource,
): ReactNode {
  return <ContentItemView item={source.sourceItem} />;
}

function CanonicalRenderedPage({
  page,
  blocks,
  sourcePage,
  sourceSha256,
  outlineStructures,
}: {
  page: CanonicalPage;
  blocks: CanonicalBlock[];
  sourcePage: PageResult;
  sourceSha256: string;
  outlineStructures: ReadonlyMap<string, ValidatedOutlineStructure> | null;
}) {
  return (
    <article
      className="rendered-page"
      aria-label={`Canonical content for physical page ${page.page_index}`}
    >
      {blocks.map((block) => {
        const isCaption =
          block.primary_element_type.toLowerCase() === "caption";
        const primaryElementType =
          block.primary_element_type.toLowerCase();
        const isSourceNote = primaryElementType === "source_note";
        const isFootnote = primaryElementType === "footnote";
        const captionLink = resolveCanonicalCaptionLink(block, sourcePage);
        const captionedTableLink = resolveCanonicalCaptionedTableLink(
          block,
          page,
          sourcePage,
        );
        const noteLink = resolveCanonicalNoteLink(block, sourcePage);
        const textRunOverlay = renderCanonicalTextRunOverlay(
          block,
          sourcePage,
        );
        const headingSources =
          primaryElementType === "heading"
            ? sourcePage.items.filter(
                (item) =>
                  item.type.toLowerCase() === "heading" &&
                  ((item.text_runs ?? []).some(
                    (run) => run.element_id === block.primary_element_id,
                  ) ||
                    (itemText(item) === block.text &&
                      block.contributing_element_ids.length === 1 &&
                      block.contributing_element_ids[0] ===
                        block.primary_element_id)),
              )
            : [];
        const headingLevel =
          headingSources.length === 1
            ? Math.min(
                Math.max(Number(headingSources[0].level) || 1, 1),
                6,
              )
            : null;
        const canonicalContent =
          textRunOverlay !== null ? textRunOverlay : <>{block.text}</>;

        const formSemantics = readFormSemanticsForCanonicalBlock(
          block,
          sourcePage,
        );
        const diagramSemantics = readDiagramSemanticsForCanonicalBlock(
          block,
          sourcePage,
        );
        const outlineStructure = outlineStructures?.get(block.id) ?? null;
        const canonicalFallback =
          primaryElementType === "heading" && headingLevel !== null ? (
            createElement(
              `h${headingLevel}`,
              {
                className: `parsed-heading parsed-heading-${headingLevel}`,
                "data-item-type": primaryElementType,
                key: block.id,
                style: { whiteSpace: "pre-wrap" },
              },
              canonicalContent,
            )
          ) : (
          <p
            key={block.id}
            className={
              isCaption
                ? "parsed-caption"
                : isSourceNote
                  ? "parsed-note parsed-source-note"
                  : isFootnote
                    ? "parsed-note parsed-footnote"
                  : block.scope === "header"
                    ? "parsed-header"
                    : block.scope === "footer"
                      ? "parsed-footer"
                      : "parsed-paragraph"
            }
            data-caption-id={captionLink?.caption.id}
            data-caption-of={captionLink?.owner.id}
            data-item-type={primaryElementType}
            data-note-id={noteLink?.note.id}
            data-note-kind={noteLink?.noteType}
            data-note-of={noteLink?.owner.id}
            data-note-relationship-id={noteLink?.relationship.id}
            data-relationship-id={captionLink?.relationship.id}
            style={{ whiteSpace: "pre-wrap" }}
          >
            {canonicalContent}
          </p>
          );

        if (outlineStructure) {
          return (
            <div
              className="canonical-outline-block"
              data-item-type={primaryElementType}
              key={block.id}
            >
              {renderValidatedOutlineStructure(outlineStructure, {
                renderBody: renderOutlineItemTextRun,
                renderContinuation: renderOutlineContinuation,
              })}
            </div>
          );
        }

        if (outlineStructures === null) return canonicalFallback;

        if (diagramSemantics) {
          return (
            <div
              className="canonical-diagram-block"
              data-item-type={primaryElementType}
              key={block.id}
            >
              {renderValidatedDiagramSemantics(diagramSemantics)}
            </div>
          );
        }

        if (formSemantics) {
          const semanticView = renderValidatedFormSemantics(formSemantics, {
            overlay: formSemantics.relationships.some(
              (relationship) => relationship.type === "form_overlay_of",
            ),
          });
          return (
            <div
              className="canonical-form-block"
              data-item-type={primaryElementType}
              data-form-canonical-mode={formSemantics.group.canonical_mode}
              key={block.id}
            >
              {formSemantics.group.canonical_mode === "inert"
                ? canonicalFallback
                : null}
              {semanticView}
            </div>
          );
        }

        const captionedTableOwner = captionedTableLink?.owner ?? null;
        const matchingPrimaryItems = sourcePage.items.filter(
          (item) =>
            item === captionedTableOwner ||
            item.id === block.primary_element_id ||
            ((primaryElementType === "table" ||
              primaryElementType === "table_candidate") &&
              (item.type.toLowerCase() === "table" ||
                item.type.toLowerCase() === "table_candidate") &&
              itemTableText(item) === block.text),
        );
        if (matchingPrimaryItems.length !== 1) return canonicalFallback;
        const primaryItem = matchingPrimaryItems[0];
        if (!tableItemAuthority(primaryItem)) {
          return canonicalFallback;
        }
        if (primaryItem === captionedTableOwner && captionedTableLink) {
          return (
            <div
              className="captioned-table-block"
              data-item-type={primaryElementType}
              key={block.id}
            >
              {/* Render the exact public value bound above. A text-run overlay
                  cannot silently diverge from the canonical composite. */}
              <p
                className="parsed-caption"
                data-caption-of={primaryItem.id}
                data-item-type="caption"
                data-relationship-id={captionedTableLink.relationship.id}
              >
                {itemText(captionedTableLink.caption)}
              </p>
              <ContentItemView
                item={primaryItem}
                sourcePage={sourcePage}
                sourceSha256={sourceSha256}
              />
            </div>
          );
        }
        return (
          <ContentItemView
            key={block.id}
            item={primaryItem}
            sourcePage={sourcePage}
            sourceSha256={sourceSha256}
          />
        );
      })}
    </article>
  );
}

function MarkdownSource({ value }: { value: string }) {
  const lines = value.split("\n");

  return (
    <pre className="source-view markdown-source">
      <code>
        {lines.map((line, index) => {
          const heading = line.match(/^(\s{0,3}#{1,6})(\s+.*)$/);
          const list = line.match(/^(\s*)([-*+]|\d+\.)(\s+.*)$/);
          const quote = line.match(/^(\s*>)(\s+.*)$/);
          const fence = line.match(/^(\s*```.*)$/);
          let content: ReactNode = line;

          if (heading) {
            content = (
              <>
                <span className="syntax-marker">{heading[1]}</span>
                <span className="syntax-heading">{heading[2]}</span>
              </>
            );
          } else if (list) {
            content = (
              <>
                {list[1]}
                <span className="syntax-marker">{list[2]}</span>
                {list[3]}
              </>
            );
          } else if (quote) {
            content = (
              <>
                <span className="syntax-marker">{quote[1]}</span>
                <span className="syntax-quote">{quote[2]}</span>
              </>
            );
          } else if (fence) {
            content = <span className="syntax-code">{fence[1]}</span>;
          }

          return (
            <span className="syntax-line" key={index}>
              {content}
              {index < lines.length - 1 ? "\n" : null}
            </span>
          );
        })}
      </code>
    </pre>
  );
}

function PageNavigator({
  activePage,
  pageCount,
  displayLabel,
  onChange,
}: {
  activePage: number;
  pageCount: number;
  displayLabel: string | null;
  onChange: (page: number) => void;
}) {
  const hasPages = pageCount > 0;
  return (
    <nav className="page-navigator" aria-label="Document pages">
      <button
        className="icon-button"
        type="button"
        aria-label="Previous page"
        title="Previous page (Alt + Left)"
        disabled={!hasPages || activePage <= 0}
        onClick={() => onChange(activePage - 1)}
      >
        <ChevronLeft aria-hidden="true" size={17} />
      </button>
      <div className="page-readout" aria-live="polite">
        {hasPages ? (
          <input
            key={`${activePage}-${pageCount}`}
            type="number"
            min={1}
            max={pageCount}
            inputMode="numeric"
            defaultValue={activePage + 1}
            aria-label="Current page number"
            onFocus={(event) => event.currentTarget.select()}
            onBlur={(event) => {
              const requestedPage = Number.parseInt(event.currentTarget.value, 10);
              if (!Number.isFinite(requestedPage)) {
                event.currentTarget.value = String(activePage + 1);
                return;
              }
              onChange(Math.min(Math.max(requestedPage, 1), pageCount) - 1);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
              if (event.key === "Escape") {
                event.currentTarget.value = String(activePage + 1);
                event.currentTarget.blur();
              }
            }}
          />
        ) : (
          <strong>—</strong>
        )}
        <span>of {hasPages ? pageCount : "—"}</span>
      </div>
      <button
        className="icon-button"
        type="button"
        aria-label="Next page"
        title="Next page (Alt + Right)"
        disabled={!hasPages || activePage >= pageCount - 1}
        onClick={() => onChange(activePage + 1)}
      >
        <ChevronRight aria-hidden="true" size={17} />
      </button>
      {hasPages && displayLabel ? (
        <span className="printed-page-label">
          Printed <bdi dir="auto">{displayLabel}</bdi>
        </span>
      ) : null}
    </nav>
  );
}

export function TaffyBopWorkspace() {
  const [file, setFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [result, setResult] = useState<ParseResult | null>(null);
  const [error, setError] = useState<UiError | null>(null);
  const [activePage, setActivePage] = useState(0);
  const [format, setFormat] = useState<ParseOutputFormat>("markdown");
  const [markdownMode, setMarkdownMode] = useState<MarkdownMode>("rendered");
  const [pagePresentationView, setPagePresentationView] =
    useState<PagePresentationView>("full");
  const [wrapJson, setWrapJson] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [fitMode, setFitMode] = useState<PdfFitMode>("width");
  const [previewPageCount, setPreviewPageCount] = useState(0);
  const [split, setSplit] = useState(52);
  const [dragActive, setDragActive] = useState(false);
  const [mobilePane, setMobilePane] = useState<MobilePane>("document");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied">("idle");

  const inputRef = useRef<HTMLInputElement>(null);
  const objectUrlRef = useRef("");
  const abortRef = useRef<AbortController | null>(null);
  const errorRef = useRef<HTMLDivElement>(null);
  const resultsHeadingRef = useRef<HTMLHeadingElement>(null);
  const workspaceRef = useRef<HTMLDivElement>(null);
  const previewScrollRef = useRef<HTMLDivElement>(null);
  const resultScrollRef = useRef<HTMLDivElement>(null);

  const maxUploadBytes = getConfiguredMaxUploadBytes();
  const apiLabel = getParseApiLabel();
  const previewKind = file ? getBrowserPreviewKind(file) : null;
  const pageCount = getPhysicalPageCount(
    result,
    result && previewKind !== "pdf" ? 0 : previewPageCount,
  );
  const physicalPages = useMemo(
    () => (result ? mapPhysicalPages(result).byPageNumber : new Map<number, PageResult>()),
    [result],
  );
  const physicalPageNumber = activePage + 1;
  const currentPage = physicalPages.get(physicalPageNumber) ?? null;
  const canonicalPresentation = useMemo(
    () => (result ? readCanonicalPresentation(result) : null),
    [result],
  );
  const validatedRunningRegions = useMemo<ValidatedRunningRegions | null>(
    () =>
      result && canonicalPresentation
        ? readRunningRegions(result, canonicalPresentation)
        : null,
    [canonicalPresentation, result],
  );
  const hasRunningRegions =
    result !== null &&
    Object.prototype.hasOwnProperty.call(result.processing, "running_regions");
  const legacyDisplayLabel =
    currentPage?.page_label &&
    currentPage.page_label !== String(physicalPageNumber)
      ? currentPage.page_label
      : null;
  const displayLabel = hasRunningRegions
    ? pageDisplayLabel(validatedRunningRegions, physicalPageNumber)
    : legacyDisplayLabel;
  const outlineStructures = useMemo(
    () =>
      result && canonicalPresentation
        ? Object.prototype.hasOwnProperty.call(
            result.processing,
            "outline_structure",
          )
          ? readOutlineStructures(result, canonicalPresentation)
          : EMPTY_OUTLINE_STRUCTURES
        : null,
    [canonicalPresentation, result],
  );
  const currentCanonicalPage = useMemo(
    () =>
      canonicalPresentation && currentPage
        ? findCanonicalPage(canonicalPresentation, currentPage)
        : null,
    [canonicalPresentation, currentPage],
  );
  const currentCanonicalBlocks = useMemo(
    () =>
      currentCanonicalPage
        ? canonicalPageBlocks(currentCanonicalPage, pagePresentationView)
        : [],
    [currentCanonicalPage, pagePresentationView],
  );
  const isSubmitting = requestState === "submitting";
  const isSuccess = requestState === "success" && result !== null;
  const currentPageHasContent = canonicalPresentation
    ? currentCanonicalBlocks.length > 0
    : currentPage !== null && pageHasContent(currentPage);
  const previewControlsDisabled = previewKind === "tiff";
  const normalizedDocumentJson = useMemo(
    () => (result ? normalizeDocumentJson(result) : null),
    [result],
  );
  const documentJsonOutput = useMemo(
    () =>
      normalizedDocumentJson
        ? JSON.stringify(normalizedDocumentJson, null, 2)
        : "",
    [normalizedDocumentJson],
  );
  const documentJsonSummary = useMemo(
    () =>
      normalizedDocumentJson
        ? summarizeDocumentJson(normalizedDocumentJson)
        : [],
    [normalizedDocumentJson],
  );

  const visibleOutput = useMemo(() => {
    if (format === "json") return documentJsonOutput;
    if (!result || !currentPage || !currentPageHasContent) return "";
    return pagePresentationView === "full"
      ? serializePageMarkdown(currentPage, result)
      : serializePageMarkdown(currentPage, result, pagePresentationView);
  }, [
    currentPage,
    currentPageHasContent,
    documentJsonOutput,
    format,
    pagePresentationView,
    result,
  ]);

  const resetPreviewScroll = useCallback(() => {
    if (!previewScrollRef.current) return;
    previewScrollRef.current.scrollTop = 0;
    previewScrollRef.current.scrollLeft = 0;
  }, []);

  const resetResultScroll = useCallback(() => {
    if (!resultScrollRef.current) return;
    resultScrollRef.current.scrollTop = 0;
    resultScrollRef.current.scrollLeft = 0;
  }, []);

  const setPage = useCallback(
    (page: number) => {
      if (!pageCount) return;
      const nextPage = Math.min(Math.max(page, 0), pageCount - 1);
      const nextPhysicalPageNumber = nextPage + 1;
      const nextLegacyLabel =
        physicalPages.get(nextPhysicalPageNumber)?.page_label ?? null;
      const nextDisplayLabel = pageDisplayLabel(
        validatedRunningRegions,
        nextPhysicalPageNumber,
      ) ??
        (!hasRunningRegions &&
        nextLegacyLabel !== String(nextPhysicalPageNumber)
          ? nextLegacyLabel
          : null);
      setActivePage(nextPage);
      resetPreviewScroll();
      if (format === "markdown") resetResultScroll();
      setAnnouncement(
        `Physical page ${nextPhysicalPageNumber} of ${pageCount}${
          nextDisplayLabel ? `, printed label ${nextDisplayLabel}` : ""
        }`,
      );
    },
    [
      format,
      pageCount,
      hasRunningRegions,
      physicalPages,
      resetPreviewScroll,
      resetResultScroll,
      validatedRunningRegions,
    ],
  );

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    };
  }, []);

  useEffect(() => {
    if (!isSubmitting) return;
    const started = Date.now();
    const timer = window.setInterval(
      () => setElapsedSeconds(Math.floor((Date.now() - started) / 1000)),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [isSubmitting]);

  useEffect(() => {
    if (requestState === "error") errorRef.current?.focus();
    if (requestState === "success") resultsHeadingRef.current?.focus();
  }, [requestState]);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (
        target?.matches(
          "input, textarea, select, button, code, [role='region'], .json-code-line, [contenteditable='true'], pre",
        )
      ) {
        return;
      }
      if (event.altKey && event.key === "ArrowLeft") {
        event.preventDefault();
        setPage(activePage - 1);
      } else if (event.altKey && event.key === "ArrowRight") {
        event.preventDefault();
        setPage(activePage + 1);
      } else if (event.key === "Home" && pageCount) {
        event.preventDefault();
        setPage(0);
      } else if (event.key === "End" && pageCount) {
        event.preventDefault();
        setPage(pageCount - 1);
      } else if ((event.metaKey || event.ctrlKey) && event.key === "0") {
        event.preventDefault();
        setZoom(100);
        setFitMode("width");
        resetPreviewScroll();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [activePage, pageCount, resetPreviewScroll, setPage]);

  const clearResultState = ({
    preservePage = false,
  }: {
    preservePage?: boolean;
  } = {}) => {
    abortRef.current?.abort();
    abortRef.current = null;
    setResult(null);
    setError(null);
    if (!preservePage) setActivePage(0);
    setFormat("markdown");
    setMarkdownMode("rendered");
    setPagePresentationView("full");
    setElapsedSeconds(0);
    setAnnouncement("");
    resetResultScroll();
  };

  const selectFile = (nextFile: File) => {
    try {
      validateDocumentFile(nextFile);
    } catch (validationError) {
      setError(errorForUi(validationError));
      setRequestState("error");
      if (inputRef.current) inputRef.current.value = "";
      return;
    }

    clearResultState();
    setPreviewPageCount(
      getBrowserPreviewKind(nextFile) === "raster" ? 1 : 0,
    );
    setFitMode("width");
    setZoom(100);
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    const nextUrl = URL.createObjectURL(nextFile);
    objectUrlRef.current = nextUrl;
    setFile(nextFile);
    setFileUrl(nextUrl);
    setRequestState("selected");
    setMobilePane("document");
  };

  const resetWorkspace = () => {
    clearResultState();
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    objectUrlRef.current = "";
    setFile(null);
    setFileUrl("");
    setRequestState("idle");
    setPreviewPageCount(0);
    setZoom(100);
    setFitMode("width");
    setMobilePane("document");
    if (inputRef.current) inputRef.current.value = "";
  };

  const parseSelectedFile = async () => {
    if (!file || isSubmitting) return;
    clearResultState({ preservePage: true });
    const controller = new AbortController();
    abortRef.current = controller;
    setRequestState("submitting");
    setMobilePane("results");

    try {
      const parsed = await parseJson(file, { signal: controller.signal });
      const parsedPresentation = readCanonicalPresentation(parsed);
      const hasRunningRegions = Object.prototype.hasOwnProperty.call(
        parsed.processing,
        "running_regions",
      );
      if (hasRunningRegions && !parsedPresentation) {
        throw new RunningRegionValidationError(
          "canonical presentation is required when running-region processing is present",
        );
      }
      if (parsedPresentation) {
        readRunningRegions(parsed, parsedPresentation);
      }
      setPagePresentationView("full");
      setResult(parsed);
      setRequestState("success");
      setAnnouncement(
        `Parsing complete. ${parsed.pages.length} physical pages are available.`,
      );
    } catch (parseError) {
      if (
        parseError instanceof DocumentApiError &&
        parseError.kind === "cancelled"
      ) {
        setRequestState("selected");
        setAnnouncement("Parsing cancelled.");
      } else {
        setError(errorForUi(parseError));
        setRequestState("error");
      }
    } finally {
      abortRef.current = null;
    }
  };

  const cancelRequest = () => {
    abortRef.current?.abort();
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragActive(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped) selectFile(dropped);
  };

  const copyOutput = async () => {
    if (!visibleOutput) return;
    try {
      await navigator.clipboard.writeText(visibleOutput);
      setCopyState("copied");
      setAnnouncement(
        format === "json"
          ? "Complete document JSON copied."
          : `Markdown for page ${activePage + 1} copied.`,
      );
      window.setTimeout(() => setCopyState("idle"), 1800);
    } catch {
      setAnnouncement("Copy failed. Please use the source view and copy manually.");
    }
  };

  const downloadOutput = () => {
    if (!file || !visibleOutput) return;
    const extension = format === "json" ? "json" : "md";
    const mime =
      format === "json"
        ? "application/json"
        : "text/markdown;charset=utf-8";
    const pageSuffix =
      format === "json"
        ? ""
        : `.page-${String(activePage + 1).padStart(3, "0")}`;
    const name = `${cleanBaseName(file.name)}${pageSuffix}.parsed.${extension}`;
    const blobUrl = URL.createObjectURL(new Blob([visibleOutput], { type: mime }));
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = name;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(blobUrl), 0);
    setAnnouncement(`${name} downloaded.`);
  };

  const handleFormatKeyDown = (
    event: ReactKeyboardEvent<HTMLButtonElement>,
    selected: ParseOutputFormat,
  ) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const nextFormat = selected === "markdown" ? "json" : "markdown";
    selectFormat(nextFormat);
    document.getElementById(`format-tab-${nextFormat}`)?.focus();
  };

  const selectFormat = (nextFormat: ParseOutputFormat) => {
    setFormat(nextFormat);
    resetResultScroll();
  };

  const selectMarkdownMode = (nextMode: MarkdownMode) => {
    setMarkdownMode(nextMode);
    resetResultScroll();
  };

  const handlePreviewPageCountChange = useCallback(
    (nextPageCount: number) => {
      const safeCount = Math.max(Math.trunc(nextPageCount), 0);
      setPreviewPageCount(safeCount);
      if (safeCount > 0 && activePage >= safeCount) {
        setActivePage(safeCount - 1);
        resetPreviewScroll();
        if (format === "markdown") resetResultScroll();
      }
    },
    [activePage, format, resetPreviewScroll, resetResultScroll],
  );

  const beginResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const resize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
    const bounds = workspaceRef.current?.getBoundingClientRect();
    if (!bounds) return;
    const percentage = ((event.clientX - bounds.left) / bounds.width) * 100;
    setSplit(Math.min(Math.max(percentage, 34), 66));
  };

  const resizeWithKeyboard = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      setSplit((value) => Math.max(value - 2, 34));
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      setSplit((value) => Math.min(value + 2, 66));
    } else if (event.key === "Home") {
      event.preventDefault();
      setSplit(34);
    } else if (event.key === "End") {
      event.preventDefault();
      setSplit(66);
    }
  };

  return (
    <div className="clearleaf-app">
      <a className="skip-link" href="#workspace-main">
        Skip to workspace
      </a>

      <header className="app-header">
        <div className="brand-lockup">
          <Link href="/" aria-label="TaffyBop home">
            <Image src="/taffybop-logo.png" alt="TaffyBop" width={328} height={164} priority unoptimized />
          </Link>
          <span className="workspace-product">Parse</span>
        </div>

        <div className="header-file">
          {file ? (
            <>
              <FileText aria-hidden="true" size={17} />
              <span>{file.name}</span>
              <em>{formatBytes(file.size)}</em>
            </>
          ) : (
            <span>Documents in. Structured content out.</span>
          )}
        </div>

        <div className="header-actions">
          <Link className="button button-quiet home-link" href="/">
            <ArrowLeft aria-hidden="true" size={15} />
            Home
          </Link>
          <span
            className={`status-pill status-${requestState}`}
            title={`Transport: ${apiLabel}`}
          >
            {requestState === "submitting" ? (
              <Loader2 className="spin" aria-hidden="true" size={14} />
            ) : requestState === "success" ? (
              <CheckCircle2 aria-hidden="true" size={14} />
            ) : (
              <span className="status-dot" aria-hidden="true" />
            )}
            {requestState === "submitting"
              ? "Parsing"
              : requestState === "success"
                ? "Parsed"
                : "Ready"}
          </span>
          {file ? (
            <button className="button button-quiet" type="button" onClick={resetWorkspace}>
              <Plus aria-hidden="true" size={16} />
              New document
            </button>
          ) : null}
        </div>
      </header>

      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept={SUPPORTED_DOCUMENT_ACCEPT}
        onChange={(event) => {
          const selected = event.target.files?.[0];
          if (selected) selectFile(selected);
          event.currentTarget.value = "";
        }}
      />

      <main id="workspace-main" className="app-main">
        {!file ? (
          <section className="upload-stage" aria-labelledby="upload-title">
            <div className="upload-copy">
              <span className="eyebrow">TaffyBop Parse</span>
              <h1 id="upload-title">Drop it. We&apos;ll untangle it.</h1>
              <p>
                Bring a PDF or image and review the original beside clean,
                page-aligned Markdown or complete-document JSON.
              </p>
              <div className="trust-row" aria-label="Workspace capabilities">
                <span>
                  <Check aria-hidden="true" size={15} /> Document preview
                </span>
                <span>
                  <Check aria-hidden="true" size={15} /> Page-synced results
                </span>
                <span>
                  <Check aria-hidden="true" size={15} /> Copy or download
                </span>
              </div>
            </div>

            <div
              className={`upload-dropzone ${dragActive ? "is-dragging" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDragActive(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (event.currentTarget === event.target) setDragActive(false);
              }}
              onDrop={onDrop}
            >
              <div className="paper-stack" aria-hidden="true">
                <span />
                <span />
                <span>
                  <i />
                  <i />
                  <i />
                </span>
              </div>
              <h2>Drop a document here</h2>
              <p>or choose a document from your computer</p>
              <button
                className="button button-primary"
                type="button"
                onClick={() => inputRef.current?.click()}
              >
                <Upload aria-hidden="true" size={17} />
                Choose document
              </button>
              <small>
                PDF, PNG, JPEG, TIFF, or WebP · up to{" "}
                {formatBytes(maxUploadBytes)}
              </small>
              {requestState === "error" && error ? (
                <div
                  className="upload-error"
                  role="alert"
                  ref={errorRef}
                  tabIndex={-1}
                >
                  <AlertTriangle aria-hidden="true" size={18} />
                  <div>
                    <strong>{error.title}</strong>
                    <span>{error.message}</span>
                  </div>
                </div>
              ) : null}
            </div>
          </section>
        ) : (
          <div className="workspace-shell">
            <div className="mobile-view-tabs" role="tablist" aria-label="Workspace pane">
              <button
                type="button"
                role="tab"
                aria-selected={mobilePane === "document"}
                onClick={() => setMobilePane("document")}
              >
                Document
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mobilePane === "results"}
                onClick={() => setMobilePane("results")}
              >
                Results
              </button>
            </div>

            <div className="workspace-pagebar">
              <div className="page-mode-label">
                <strong>
                  {format === "json"
                    ? "Complete document JSON"
                    : "Page-by-page view"}
                </strong>
                <span>
                  {format === "json"
                    ? "The preview page changes; JSON remains document-wide"
                    : "Preview and Markdown stay synchronized"}
                </span>
              </div>
              <PageNavigator
                activePage={activePage}
                pageCount={pageCount}
                displayLabel={displayLabel}
                onChange={setPage}
              />
              <span className="page-output-status">
                {requestState === "success"
                  ? format === "json"
                    ? `${result?.pages.length ?? 0} pages · complete document JSON`
                    : currentPageHasContent
                      ? canonicalPresentation
                        ? `${currentCanonicalBlocks.length} canonical blocks`
                        : `${currentPage?.items.length ?? 0} extracted items`
                      : canonicalPresentation
                        ? `No canonical content for page ${physicalPageNumber}`
                        : `No extracted content for page ${physicalPageNumber}`
                  : requestState === "submitting"
                    ? "Parsing document"
                    : "Ready to parse"}
              </span>
            </div>

            <div
              ref={workspaceRef}
              className="workspace"
              style={{ "--workspace-split": `${split}%` } as CSSProperties}
            >
              <section
                className={`workspace-panel preview-panel ${
                  mobilePane === "document" ? "mobile-active" : ""
                }`}
                aria-labelledby="document-panel-title"
              >
                <div className="panel-toolbar">
                  <div className="panel-title">
                    <span className="panel-kicker">Original</span>
                    <h2 id="document-panel-title">Document</h2>
                  </div>
                  <div className="toolbar-actions">
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Zoom out"
                      title="Zoom out"
                      disabled={previewControlsDisabled || zoom <= 70}
                      onClick={() => {
                        setFitMode("custom");
                        setZoom((value) => Math.max(value - 10, 70));
                        resetPreviewScroll();
                      }}
                    >
                      <ZoomOut aria-hidden="true" size={16} />
                    </button>
                    <span className="zoom-readout">
                      {fitMode === "custom"
                        ? `${zoom}%`
                        : fitMode === "width"
                          ? "Width"
                          : "Page"}
                    </span>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Zoom in"
                      title="Zoom in"
                      disabled={previewControlsDisabled || zoom >= 150}
                      onClick={() => {
                        setFitMode("custom");
                        setZoom((value) => Math.min(value + 10, 150));
                        resetPreviewScroll();
                      }}
                    >
                      <ZoomIn aria-hidden="true" size={16} />
                    </button>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Fit page to width"
                      aria-pressed={fitMode === "width"}
                      title="Fit page to width"
                      disabled={previewControlsDisabled}
                      onClick={() => {
                        setFitMode("width");
                        setZoom(100);
                        resetPreviewScroll();
                      }}
                    >
                      <Maximize2 aria-hidden="true" size={16} />
                    </button>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Fit entire page"
                      aria-pressed={fitMode === "page"}
                      title="Fit entire page"
                      disabled={previewControlsDisabled}
                      onClick={() => {
                        setFitMode("page");
                        resetPreviewScroll();
                      }}
                    >
                      <Scan aria-hidden="true" size={16} />
                    </button>
                    <a
                      className="icon-button"
                      href={fileUrl}
                      target="_blank"
                      rel="noreferrer"
                      aria-label="Open original document"
                      title="Open original document"
                    >
                      <ExternalLink aria-hidden="true" size={16} />
                    </a>
                  </div>
                </div>

                <div ref={previewScrollRef} className="pdf-canvas">
                  {previewKind === "pdf" ? (
                    <PdfPagePreview
                      key={fileUrl}
                      file={file}
                      pageNumber={physicalPageNumber}
                      zoom={zoom}
                      fitMode={fitMode}
                      onPageCountChange={handlePreviewPageCountChange}
                    />
                  ) : previewKind ? (
                    <ImagePagePreview
                      key={fileUrl}
                      file={file}
                      fileUrl={fileUrl}
                      pageNumber={physicalPageNumber}
                      pageCount={pageCount}
                      previewKind={previewKind}
                      zoom={zoom}
                      fitMode={fitMode}
                    />
                  ) : null}
                </div>

                <div className="panel-footer preview-footer">
                  <div>
                    <FileText aria-hidden="true" size={16} />
                    <span>{file.name}</span>
                  </div>
                  <button
                    className="button-link"
                    type="button"
                    disabled={isSubmitting}
                    onClick={() => inputRef.current?.click()}
                  >
                    Choose another
                  </button>
                </div>
              </section>

              <div
                className="panel-divider"
                role="separator"
                aria-label="Resize document and results panes"
                aria-orientation="vertical"
                aria-valuemin={34}
                aria-valuemax={66}
                aria-valuenow={Math.round(split)}
                tabIndex={0}
                onDoubleClick={() => setSplit(52)}
                onPointerDown={beginResize}
                onPointerMove={resize}
                onKeyDown={resizeWithKeyboard}
              >
                <span />
              </div>

              <section
                className={`workspace-panel result-panel ${
                  mobilePane === "results" ? "mobile-active" : ""
                }`}
                aria-labelledby="result-panel-title"
                aria-busy={isSubmitting}
              >
                <div className="panel-toolbar result-toolbar">
                  <div className="panel-title">
                    <span className="panel-kicker">Structured</span>
                    <h2 id="result-panel-title" ref={resultsHeadingRef} tabIndex={-1}>
                      Results
                    </h2>
                  </div>

                  <div className="format-tabs" role="tablist" aria-label="Result format">
                    <button
                      id="format-tab-markdown"
                      type="button"
                      role="tab"
                      aria-selected={format === "markdown"}
                      aria-controls="result-tabpanel"
                      tabIndex={format === "markdown" ? 0 : -1}
                      onClick={() => selectFormat("markdown")}
                      onKeyDown={(event) => handleFormatKeyDown(event, "markdown")}
                    >
                      <Code2 aria-hidden="true" size={15} />
                      Markdown
                    </button>
                    <button
                      id="format-tab-json"
                      type="button"
                      role="tab"
                      aria-selected={format === "json"}
                      aria-controls="result-tabpanel"
                      tabIndex={format === "json" ? 0 : -1}
                      onClick={() => selectFormat("json")}
                      onKeyDown={(event) => handleFormatKeyDown(event, "json")}
                    >
                      <Braces aria-hidden="true" size={15} />
                      JSON
                    </button>
                  </div>

                  <div className="toolbar-actions result-actions">
                    <button
                      className="icon-button action-with-label"
                      type="button"
                      disabled={!visibleOutput}
                      onClick={copyOutput}
                      title={
                        format === "json"
                          ? "Copy complete document JSON"
                          : `Copy page ${physicalPageNumber} Markdown`
                      }
                    >
                      {copyState === "copied" ? (
                        <Check aria-hidden="true" size={16} />
                      ) : (
                        <Copy aria-hidden="true" size={16} />
                      )}
                      <span>{copyState === "copied" ? "Copied" : "Copy"}</span>
                    </button>
                    <button
                      className="icon-button action-with-label"
                      type="button"
                      disabled={!visibleOutput}
                      onClick={downloadOutput}
                      title={
                        format === "json"
                          ? "Download complete document JSON"
                          : `Download page ${physicalPageNumber} Markdown`
                      }
                    >
                      <Download aria-hidden="true" size={16} />
                      <span>Download</span>
                    </button>
                  </div>
                </div>

                {isSuccess ? (
                  <div className="result-subtoolbar">
                    {format === "markdown" ? (
                      <>
                        {validatedRunningRegions?.status === "projected" ? (
                          <div
                            className="view-toggle"
                            aria-label="Page content scope"
                          >
                            <button
                              type="button"
                              aria-pressed={pagePresentationView === "body"}
                              onClick={() => setPagePresentationView("body")}
                            >
                              Body
                            </button>
                            <button
                              type="button"
                              aria-pressed={pagePresentationView === "full"}
                              onClick={() => setPagePresentationView("full")}
                            >
                              Full
                            </button>
                          </div>
                        ) : null}
                        <div className="view-toggle" aria-label="Markdown view">
                          <button
                            type="button"
                            aria-pressed={markdownMode === "rendered"}
                            onClick={() => selectMarkdownMode("rendered")}
                          >
                            <Eye aria-hidden="true" size={14} /> Rendered
                          </button>
                          <button
                            type="button"
                            aria-pressed={markdownMode === "source"}
                            onClick={() => selectMarkdownMode("source")}
                          >
                            <Code2 aria-hidden="true" size={14} /> Source
                          </button>
                        </div>
                      </>
                    ) : (
                      <label className="wrap-toggle">
                        <input
                          type="checkbox"
                          checked={wrapJson}
                          onChange={(event) => setWrapJson(event.target.checked)}
                        />
                        Wrap lines
                      </label>
                    )}
                  </div>
                ) : null}

                <div
                  id="result-tabpanel"
                  className={`result-body ${format === "json" ? "json-mode" : ""}`}
                  role="tabpanel"
                  aria-labelledby={`format-tab-${format}`}
                  ref={resultScrollRef}
                >
                  {requestState === "selected" ? (
                    <div className="result-empty-state">
                      <div className="result-empty-icon">
                        <FileText aria-hidden="true" size={30} />
                      </div>
                      <span className="eyebrow">Ready when you are</span>
                      <h3>Parse this document</h3>
                      <p>
                        The document stays in the preview while the existing API extracts
                        its native text, tables, and image OCR.
                      </p>
                      <button
                        className="button button-primary"
                        type="button"
                        onClick={parseSelectedFile}
                      >
                        <RefreshCw aria-hidden="true" size={17} />
                        Parse document
                      </button>
                      <small>Sent through {apiLabel}</small>
                    </div>
                  ) : null}

                  {isSubmitting ? (
                    <div className="loading-state" role="status">
                      <div className="loading-orbit" aria-hidden="true">
                        <span />
                        <span />
                      </div>
                      <span className="eyebrow">Processing locally configured API</span>
                      <h3>Parsing {file.name}</h3>
                      <p>
                        Uploading and extracting document structure. Large or
                        image-heavy documents may take a few minutes.
                      </p>
                      <div className="loading-lines" aria-hidden="true">
                        <span />
                        <span />
                        <span />
                      </div>
                      <div className="loading-meta">
                        <span>{elapsedSeconds}s elapsed</span>
                        <button className="button-link danger-link" type="button" onClick={cancelRequest}>
                          Cancel request
                        </button>
                      </div>
                    </div>
                  ) : null}

                  {requestState === "error" && error ? (
                    <div className="error-state" role="alert" ref={errorRef} tabIndex={-1}>
                      <div className="error-icon">
                        <AlertTriangle aria-hidden="true" size={26} />
                      </div>
                      <span className="eyebrow">Request not completed</span>
                      <h3>{error.title}</h3>
                      <p>{error.message}</p>
                      <div className="error-actions">
                        {file ? (
                          <button
                            className="button button-primary"
                            type="button"
                            onClick={parseSelectedFile}
                          >
                            <RotateCcw aria-hidden="true" size={16} />
                            Retry
                          </button>
                        ) : null}
                        <button
                          className="button button-secondary"
                          type="button"
                          onClick={() => inputRef.current?.click()}
                        >
                          Choose another document
                        </button>
                      </div>
                      {error.code ? (
                        <details>
                          <summary>Technical details</summary>
                          <code>
                            {error.code}
                            {error.status ? ` · HTTP ${error.status}` : ""}
                          </code>
                        </details>
                      ) : null}
                    </div>
                  ) : null}

                  {isSuccess &&
                  format === "markdown" &&
                  !currentPageHasContent ? (
                    <div className="result-empty-state">
                      <div className="result-empty-icon">
                        <FileText aria-hidden="true" size={30} />
                      </div>
                      <h3>
                        {canonicalPresentation
                          ? "No canonical content is available for page "
                          : "No extracted content is available for page "}
                        {physicalPageNumber}.
                      </h3>
                      <p>
                        The document page remains available in the preview. The
                        interface will not substitute{" "}
                        {canonicalPresentation
                          ? "legacy or omitted content"
                          : "content from another page"}
                        .
                      </p>
                    </div>
                  ) : null}

                  {isSuccess && currentPageHasContent && format === "markdown" ? (
                    markdownMode === "source" ? (
                      <MarkdownSource value={visibleOutput} />
                    ) : currentCanonicalPage && currentPage ? (
                      <CanonicalRenderedPage
                        page={currentCanonicalPage}
                        blocks={currentCanonicalBlocks}
                        sourcePage={currentPage}
                        sourceSha256={result?.document.sha256 ?? ""}
                        outlineStructures={outlineStructures}
                      />
                    ) : currentPage ? (
                      <RenderedPage
                        page={currentPage}
                        sourceSha256={result?.document.sha256 ?? ""}
                      />
                    ) : null
                  ) : null}

                  {isSuccess &&
                  result &&
                  normalizedDocumentJson &&
                  format === "json" ? (
                    <DocumentJsonView
                      value={documentJsonOutput}
                      summary={documentJsonSummary}
                      wrap={wrapJson}
                    />
                  ) : null}
                </div>

                <div className="panel-footer result-footer">
                  {result ? (
                    format === "json" ? (
                      <>
                        <span>Complete document JSON</span>
                        <span>{result.pages.length} pages</span>
                        <span>
                          {result.pages.reduce(
                            (total, page) => total + page.items.length,
                            0,
                          )}{" "}
                          extracted items
                        </span>
                      </>
                    ) : (
                      <>
                        <span>
                          Physical page {physicalPageNumber}
                          {displayLabel ? (
                            <>
                              {" · printed "}
                              <bdi dir="auto">{displayLabel}</bdi>
                            </>
                          ) : null}
                        </span>
                        <span>
                          {currentCanonicalPage
                            ? `${currentCanonicalBlocks.length} canonical blocks`
                            : currentPage
                              ? `${currentPage.items.length} extracted items`
                            : "No matched page data"}
                        </span>
                        <span>
                          Processed in{" "}
                          {(result.processing.duration_ms / 1000).toFixed(1)}s
                        </span>
                      </>
                    )
                  ) : (
                    <span>
                      Markdown follows the selected page; JSON covers the complete
                      document.
                    </span>
                  )}
                </div>
              </section>
            </div>
          </div>
        )}
      </main>

      <div className="visually-hidden" aria-live="polite" aria-atomic="true">
        {announcement}
      </div>
    </div>
  );
}

// The fidelity harness renders these same components through React's static
// renderer. Keeping the export at the component boundary prevents benchmark
// captures from substituting a separate Markdown renderer for the UI users
// actually see.
export { CanonicalRenderedPage, RenderedPage, canonicalPageBlocks };
