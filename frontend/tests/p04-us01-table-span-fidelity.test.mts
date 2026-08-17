import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";
import { threadCpuUsage } from "node:process";
import { test } from "node:test";

import { createElement, memo } from "react";
import { flushSync } from "react-dom";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";

import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import {
  serializeDocumentJson,
  serializeDocumentMarkdown,
  serializePageMarkdown,
} from "../lib/serialize-output.ts";
import { readTableSemantics } from "../lib/table-semantics.ts";
import type {
  CanonicalPresentation,
  ParseResult,
} from "../lib/types.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

const sha256 = (value: string): string =>
  createHash("sha256").update(value, "utf8").digest("hex");

const CONTEXT = {
  sourceSha256: "ab".repeat(32),
  pageIndex: 1,
  pageWidth: 612,
  pageHeight: 792,
  unit: "pt" as const,
};

const orderedId = (value: number): string =>
  value.toString(16).padStart(64, "0");

function bbox(x: number, y: number, width: number, height: number) {
  return { x, y, width, height, unit: "pt" as const };
}

function float64Hex(value: number): string {
  const buffer = new ArrayBuffer(8);
  new DataView(buffer).setFloat64(0, Object.is(value, -0) ? 0 : value, false);
  return Buffer.from(buffer).toString("hex");
}

function canonicalCustodyJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (typeof value === "number") {
    assert.equal(Number.isFinite(value), true);
    return `{"$p04_f64":"${float64Hex(value)}"}`;
  }
  if (Array.isArray(value)) {
    return `[${value.map((entry) => canonicalCustodyJson(entry)).join(",")}]`;
  }
  assert.equal(typeof value, "object");
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${canonicalCustodyJson(record[key])}`)
    .join(",")}}`;
}

interface ProjectionCell {
  id: string;
  text: string;
  column_header: boolean;
  row_header: boolean;
  row_span: number;
  col_span: number;
}

interface ProjectionSlot {
  row: number;
  column: number;
  kind: "anchor" | "explicit_blank" | "covered";
  cell_id: string | null;
}

interface ProjectionFixture {
  row_count: number;
  column_count: number;
  rows: string[][];
  value: string[][];
  html: string;
  md: string;
  csv: string;
  cells: ProjectionCell[];
  table_evidence: {
    slots: ProjectionSlot[];
    representation_custody: {
      cells_sha256: string;
      rows_sha256: string;
      html_sha256: string;
      markdown_sha256: string;
      csv_sha256: string;
    };
  };
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#x27;")
    .replaceAll("\n", "<br>");
}

function csvField(value: string, singleEmptyField: boolean): string {
  return singleEmptyField || /[,"\r\n]/u.test(value)
    ? `"${value.replaceAll('"', '""')}"`
    : value;
}

function applyProjection<T extends ProjectionFixture>(table: T): T {
  const cellsById = new Map(table.cells.map((cell) => [cell.id, cell]));
  const rows: string[][] = [];
  const slotRows: ProjectionSlot[][] = [];
  let cursor = 0;
  for (let row = 0; row < table.row_count; row += 1) {
    const values: string[] = [];
    const slots: ProjectionSlot[] = [];
    for (let column = 0; column < table.column_count; column += 1) {
      const slot = table.table_evidence.slots[cursor];
      assert.ok(slot);
      cursor += 1;
      slots.push(slot);
      values.push(
        slot.kind === "covered"
          ? ""
          : (cellsById.get(assertString(slot.cell_id))?.text ?? ""),
      );
    }
    rows.push(values);
    slotRows.push(slots);
  }
  let headerRows = 0;
  for (const slots of slotRows) {
    const anchors = slots
      .filter((slot) => slot.kind !== "covered")
      .map((slot) => cellsById.get(assertString(slot.cell_id)));
    if (anchors.length > 0 && anchors.every((cell) => cell?.column_header)) {
      headerRows += 1;
    } else {
      break;
    }
  }
  const html = ["<table>"];
  for (let row = 0; row < table.row_count; row += 1) {
    if (row === 0 && headerRows > 0) html.push("  <thead>");
    if (row === headerRows) {
      if (headerRows > 0) html.push("  </thead>");
      html.push("  <tbody>");
    }
    html.push("    <tr>");
    for (const slot of slotRows[row] ?? []) {
      if (slot.kind === "covered") continue;
      const cell = cellsById.get(assertString(slot.cell_id));
      assert.ok(cell);
      let tag = "td";
      let attributes = "";
      if (cell.column_header) {
        tag = "th";
        attributes = ' scope="col"';
      } else if (cell.row_header) {
        tag = "th";
        attributes = ' scope="row"';
      }
      if (cell.row_span > 1) attributes += ` rowspan="${cell.row_span}"`;
      if (cell.col_span > 1) attributes += ` colspan="${cell.col_span}"`;
      html.push(`      <${tag}${attributes}>${escapeHtml(cell.text)}</${tag}>`);
    }
    html.push("    </tr>");
  }
  html.push(headerRows === table.row_count ? "  </thead>" : "  </tbody>");
  html.push("</table>");
  table.rows = rows;
  table.value = structuredClone(rows);
  table.html = html.join("\n");
  table.md = table.html;
  table.csv = rows
    .map((row) =>
      row
        .map((value) => csvField(value, row.length === 1 && value === ""))
        .join(","),
    )
    .join("\n");
  return table;
}

function assertString(value: string | null): string {
  assert.equal(typeof value, "string");
  return value as string;
}

function refreshCustody<T extends ProjectionFixture>(table: T): T {
  const custody = table.table_evidence.representation_custody;
  custody.cells_sha256 = sha256(canonicalCustodyJson(table.cells));
  custody.rows_sha256 = sha256(canonicalCustodyJson(table.rows));
  custody.html_sha256 = sha256(table.html);
  custody.markdown_sha256 = sha256(table.md);
  custody.csv_sha256 = sha256(table.csv);
  return table;
}

const read = (table: unknown) => readTableSemantics(table, CONTEXT);

type RecoveryRole = "header" | "body_control" | "bottom_row";

interface FixtureRecoveryWord {
  id: string;
  text: string;
  bbox: ReturnType<typeof bbox>;
  font_name: string;
  bold: boolean;
}

interface FixtureSourceObject {
  id: string;
  engine: string;
  object_type: string;
  page_index: number;
  raw_ref: string | null;
  content_sha256: string;
  role?: RecoveryRole;
  target_row?: number;
  target_column?: number;
  words?: FixtureRecoveryWord[];
}

interface FixtureCell extends ProjectionCell {
  row: number;
  column: number;
  row_section: boolean;
  bbox: ReturnType<typeof bbox> | null;
  source: string;
  page_index: number;
  evidence_ids: string[];
  source_object_ids: string[];
  span_decision_id: string | null;
  confidence_dimensions: {
    text: number | null;
    geometry: number | null;
    structure: number | null;
    header: number | null;
  };
}

interface FixtureEvidenceRecord {
  id: string;
  method: string;
  dimension: string;
  page_index: number;
  bbox: ReturnType<typeof bbox> | null;
  source_object_ids: string[];
  confidence: number;
  content_sha256: string;
}

interface ExactFixtureTable extends ProjectionFixture {
  bbox: ReturnType<typeof bbox>;
  engine: string;
  source: string;
  cells: FixtureCell[];
  table_evidence: ProjectionFixture["table_evidence"] & {
    table_id: string;
    candidate_id: string;
    page_index: number;
    grid: { row_count: number; column_count: number; cell_ids: string[] };
    slots: Array<ProjectionSlot & { id: string; covered_by_cell_id: string | null }>;
    source_objects: FixtureSourceObject[];
    evidence: FixtureEvidenceRecord[];
    span_decisions: Array<{
      id: string;
      cell_id: string;
      claimed_row_span: number;
      claimed_col_span: number;
      emitted_row_span: number;
      emitted_col_span: number;
      outcome: string;
      evidence_ids: string[];
      concern_codes: string[];
    }>;
    concerns: string[];
  };
}

function sealDoclingFixture<T extends ExactFixtureTable>(
  table: T,
  predecessorRows = table.row_count,
  canonicalizeBBox: (box: ReturnType<typeof bbox>) => string = canonicalWordBBox,
): T {
  const context = CONTEXT;
  const sidecar = table.table_evidence;
  const emittedRows = table.row_count;
  const columns = table.column_count;
  const tableReference = assertString(
    sidecar.source_objects.find((source) => source.object_type === "table_grid")
      ?.raw_ref ?? null,
  );
  const tableBox = canonicalizeBBox(table.bbox);
  const tableId = sha256(
    `["p04-table-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBox},${emittedRows},${columns}]`,
  );
  const candidateId = sha256(
    `["p04-candidate-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBox},${predecessorRows},${columns}]`,
  );
  const geometryContent = sha256(
    `["p04-geometry-source-content-v1",${tableBox},1]`,
  );
  const geometrySourceId = sha256(
    `["p04-geometry-source-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBox}]`,
  );
  const geometryEvidenceId = sha256(
    `["p04-geometry-evidence-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBox}]`,
  );
  const gridSourceId = sha256(
    `["p04-structure-source-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${predecessorRows},${columns}]`,
  );

  const oldSources = new Map(
    sidecar.source_objects.map((source) => [source.id, source]),
  );
  const cellFacts = table.cells.map((cell) => {
    const oldSource = oldSources.get(cell.source_object_ids[0] ?? "");
    assert.equal(oldSource?.object_type, "table_cell");
    const rawReference = assertString(oldSource?.raw_ref ?? null);
    const cellBox = cell.bbox === null ? "null" : canonicalizeBBox(cell.bbox);
    const identityTail = `[${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(rawReference)},${cellBox},${cell.row},${cell.column},${cell.row_span},${cell.col_span}]`;
    const cellId = sha256(`["p04-cell-id-v1",${identityTail}]`);
    const sourceId = sha256(`["p04-cell-source-id-v1",${identityTail}]`);
    const textEvidenceId = sha256(`["p04-text-evidence-id-v1",${identityTail}]`);
    const geometryId = sha256(
      `["p04-cell-geometry-evidence-id-v1",${identityTail}]`,
    );
    const decisionId = sha256(`["p04-span-decision-id-v1",${identityTail}]`);
    const content = sha256(
      `["p04-cell-content-v1",${JSON.stringify(rawReference)},${cellBox},${cell.row},${cell.column},${cell.row_span},${cell.col_span},${JSON.stringify(cell.text)},${cell.column_header ? "true" : "false"},${cell.row_header ? "true" : "false"},${cell.row_section ? "true" : "false"}]`,
    );
    return {
      cell,
      rawReference,
      cellBox,
      cellId,
      sourceId,
      textEvidenceId,
      geometryId,
      decisionId,
      content,
    };
  });
  const normalizedCells = cellFacts
    .filter(({ cell }) => cell.row < predecessorRows)
    .map(
      ({ cell, cellBox, rawReference }) =>
        `[${cell.row},${cell.column},${cell.row_span},${cell.col_span},${JSON.stringify(cell.text)},${cell.column_header ? "true" : "false"},${cell.row_header ? "true" : "false"},${cell.row_section ? "true" : "false"},${cellBox},${JSON.stringify(rawReference)}]`,
    );
  const gridContent = sha256(
    `["p04-structure-source-content-v1",${JSON.stringify(tableReference)},${predecessorRows},${columns},[${normalizedCells.join(",")}]]`,
  );
  const structureEvidenceId = sha256(
    `["p04-structure-evidence-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${emittedRows},${columns}]`,
  );
  const headerEvidenceId = sha256(
    `["p04-header-evidence-id-v1",${JSON.stringify(context.sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${emittedRows},${columns}]`,
  );
  const hasNativeHeader = table.cells.some(
    (cell) => cell.column_header || cell.row_header,
  );
  const sources: FixtureSourceObject[] = [
    ...cellFacts.map(({ rawReference, sourceId, content }) => ({
      id: sourceId,
      engine: "docling",
      object_type: "table_cell",
      page_index: 1,
      raw_ref: rawReference,
      content_sha256: content,
    })),
    {
      id: geometrySourceId,
      engine: "docling",
      object_type: "table_geometry",
      page_index: 1,
      raw_ref: tableReference,
      content_sha256: geometryContent,
    },
    {
      id: gridSourceId,
      engine: "docling",
      object_type: "table_grid",
      page_index: 1,
      raw_ref: tableReference,
      content_sha256: gridContent,
    },
  ];
  const evidence: FixtureEvidenceRecord[] = [
    ...cellFacts.flatMap(({ cell, sourceId, textEvidenceId, geometryId, content }) => {
      const records: FixtureEvidenceRecord[] = [
        {
          id: textEvidenceId,
          method: cell.source === "native" ? "native_text" : "ocr_text",
          dimension: "text",
          page_index: 1,
          bbox: cell.bbox,
          source_object_ids: [sourceId],
          confidence: 1,
          content_sha256: content,
        },
      ];
      if (cell.row_span > 1 || cell.col_span > 1) {
        records.push({
          id: geometryId,
          method: "embedded_grid",
          dimension: "geometry",
          page_index: 1,
          bbox: cell.bbox,
          source_object_ids: [sourceId],
          confidence: 1,
          content_sha256: content,
        });
      }
      return records;
    }),
    {
      id: geometryEvidenceId,
      method: "embedded_grid",
      dimension: "geometry",
      page_index: 1,
      bbox: table.bbox,
      source_object_ids: [geometrySourceId],
      confidence: 1,
      content_sha256: geometryContent,
    },
    {
      id: structureEvidenceId,
      method: "source_grid",
      dimension: "structure",
      page_index: 1,
      bbox: table.bbox,
      source_object_ids: [gridSourceId],
      confidence: 1,
      content_sha256: gridContent,
    },
  ];
  if (hasNativeHeader) {
    evidence.push({
      id: headerEvidenceId,
      method: "model_structure",
      dimension: "header",
      page_index: 1,
      bbox: table.bbox,
      source_object_ids: [gridSourceId],
      confidence: 1,
      content_sha256: gridContent,
    });
  }
  const decisions: ExactFixtureTable["table_evidence"]["span_decisions"] = [];
  for (const fact of cellFacts) {
    const { cell } = fact;
    const hasSpan = cell.row_span > 1 || cell.col_span > 1;
    const evidenceIds = [fact.textEvidenceId];
    if (hasSpan) evidenceIds.push(fact.geometryId, structureEvidenceId);
    if (cell.column_header || cell.row_header) evidenceIds.push(headerEvidenceId);
    cell.id = fact.cellId;
    cell.source_object_ids = [fact.sourceId];
    cell.evidence_ids = evidenceIds.sort();
    cell.span_decision_id = hasSpan ? fact.decisionId : null;
    if (hasSpan) {
      decisions.push({
        id: fact.decisionId,
        cell_id: fact.cellId,
        claimed_row_span: cell.row_span,
        claimed_col_span: cell.col_span,
        emitted_row_span: cell.row_span,
        emitted_col_span: cell.col_span,
        outcome: "supported",
        evidence_ids: [fact.geometryId, structureEvidenceId].sort(),
        concern_codes: [],
      });
    }
  }
  const slots: ExactFixtureTable["table_evidence"]["slots"] = [];
  for (let row = 0; row < emittedRows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const owner = table.cells.find(
        (cell) =>
          cell.row <= row &&
          row < cell.row + cell.row_span &&
          cell.column <= column &&
          column < cell.column + cell.col_span,
      );
      if (owner === undefined) continue;
      const anchor = owner.row === row && owner.column === column;
      slots.push({
        id: sha256(
          `["p04-slot-id-v1",${JSON.stringify(context.sourceSha256)},1,${JSON.stringify(tableId)},${JSON.stringify(candidateId)},${row},${column}]`,
        ),
        row,
        column,
        kind: anchor ? (owner.text === "" ? "explicit_blank" : "anchor") : "covered",
        cell_id: anchor ? owner.id : null,
        covered_by_cell_id: anchor ? null : owner.id,
      });
    }
  }
  sidecar.table_id = tableId;
  sidecar.candidate_id = candidateId;
  sidecar.grid = {
    row_count: emittedRows,
    column_count: columns,
    cell_ids: table.cells.map((cell) => cell.id),
  };
  sidecar.slots = slots;
  sidecar.source_objects = sources.sort((left, right) => left.id.localeCompare(right.id));
  sidecar.evidence = evidence.sort((left, right) => left.id.localeCompare(right.id));
  sidecar.span_decisions = decisions;
  return table;
}

function validTable(rightText = "Same") {
  const sourceIds = [10, 11, 12, 13, 14, 15].map(orderedId);
  const evidenceIds = [20, 21, 22, 23, 24, 25, 26, 27].map(orderedId);
  const cellIds = [30, 31, 32, 33].map(orderedId);
  const tableBox = bbox(10, 10, 300, 40);
  const hostileHeader = "<script>alert(1)</script>\nQuarterly result";
  const table = {
    id: "table-item",
    type: "table",
    engine: "docling",
    source: "native",
    bbox: tableBox,
    reading_order: 0,
    row_count: 2,
    column_count: 3,
    rows: [] as string[][],
    value: [] as string[][],
    html: "",
    md: "",
    csv: "",
    cells: [
      {
        id: cellIds[0], row: 0, column: 0, row_span: 1, col_span: 3,
        text: hostileHeader, column_header: true, row_header: false,
        row_section: false, bbox: bbox(10, 10, 300, 20), source: "native",
        page_index: 1, evidence_ids: [evidenceIds[0], evidenceIds[4], evidenceIds[5], evidenceIds[7]],
        source_object_ids: [sourceIds[0]], span_decision_id: orderedId(40),
        confidence_dimensions: { text: 1, geometry: 1, structure: 1, header: 1 },
      },
      {
        id: cellIds[1], row: 1, column: 0, row_span: 1, col_span: 1,
        text: "Same", column_header: false, row_header: true,
        row_section: false, bbox: bbox(10, 30, 100, 20), source: "native",
        page_index: 1, evidence_ids: [evidenceIds[1], evidenceIds[5]],
        source_object_ids: [sourceIds[1]], span_decision_id: null,
        confidence_dimensions: { text: 1, geometry: 1, structure: 1, header: 1 },
      },
      {
        id: cellIds[2], row: 1, column: 1, row_span: 1, col_span: 1,
        text: "", column_header: false, row_header: false,
        row_section: false, bbox: bbox(110, 30, 100, 20), source: "native",
        page_index: 1, evidence_ids: [evidenceIds[2]], source_object_ids: [sourceIds[2]],
        span_decision_id: null,
        confidence_dimensions: { text: 1, geometry: 1, structure: 1, header: null },
      },
      {
        id: cellIds[3], row: 1, column: 2, row_span: 1, col_span: 1,
        text: rightText, column_header: false, row_header: false,
        row_section: false, bbox: bbox(210, 30, 100, 20), source: "ocr",
        page_index: 1, evidence_ids: [evidenceIds[3]], source_object_ids: [sourceIds[3]],
        span_decision_id: null,
        confidence_dimensions: { text: 1, geometry: 1, structure: 1, header: null },
      },
    ],
    table_evidence: {
      policy_id: "p04-table-evidence-v1",
      version: "1.1",
      scope: ["P04-US01"],
      status: "valid",
      table_id: orderedId(1),
      candidate_id: orderedId(2),
      page_index: 1,
      grid: { row_count: 2, column_count: 3, cell_ids: cellIds },
      slots: [
        { id: orderedId(50), row: 0, column: 0, kind: "anchor" as const, cell_id: cellIds[0], covered_by_cell_id: null },
        { id: orderedId(51), row: 0, column: 1, kind: "covered" as const, cell_id: null, covered_by_cell_id: cellIds[0] },
        { id: orderedId(52), row: 0, column: 2, kind: "covered" as const, cell_id: null, covered_by_cell_id: cellIds[0] },
        { id: orderedId(53), row: 1, column: 0, kind: "anchor" as const, cell_id: cellIds[1], covered_by_cell_id: null },
        { id: orderedId(54), row: 1, column: 1, kind: "explicit_blank" as const, cell_id: cellIds[2], covered_by_cell_id: null },
        { id: orderedId(55), row: 1, column: 2, kind: "anchor" as const, cell_id: cellIds[3], covered_by_cell_id: null },
      ],
      source_objects: [
        { id: sourceIds[0], engine: "docling", object_type: "table_cell", page_index: 1, raw_ref: "#/tables/0/cells/0", content_sha256: orderedId(100) },
        { id: sourceIds[1], engine: "docling", object_type: "table_cell", page_index: 1, raw_ref: "#/tables/0/cells/1", content_sha256: orderedId(101) },
        { id: sourceIds[2], engine: "docling", object_type: "table_cell", page_index: 1, raw_ref: "#/tables/0/cells/2", content_sha256: orderedId(102) },
        { id: sourceIds[3], engine: "docling", object_type: "table_cell", page_index: 1, raw_ref: "#/tables/0/cells/3", content_sha256: orderedId(103) },
        { id: sourceIds[4], engine: "docling", object_type: "table_geometry", page_index: 1, raw_ref: "#/tables/0", content_sha256: orderedId(104) },
        { id: sourceIds[5], engine: "docling", object_type: "table_grid", page_index: 1, raw_ref: "#/tables/0", content_sha256: orderedId(105) },
      ] as FixtureSourceObject[],
      evidence: [
        { id: evidenceIds[0], method: "native_text", dimension: "text", page_index: 1, bbox: bbox(10, 10, 300, 20), source_object_ids: [sourceIds[0]], confidence: 1, content_sha256: orderedId(100) },
        { id: evidenceIds[1], method: "native_text", dimension: "text", page_index: 1, bbox: bbox(10, 30, 100, 20), source_object_ids: [sourceIds[1]], confidence: 1, content_sha256: orderedId(101) },
        { id: evidenceIds[2], method: "native_text", dimension: "text", page_index: 1, bbox: bbox(110, 30, 100, 20), source_object_ids: [sourceIds[2]], confidence: 1, content_sha256: orderedId(102) },
        { id: evidenceIds[3], method: "ocr_text", dimension: "text", page_index: 1, bbox: bbox(210, 30, 100, 20), source_object_ids: [sourceIds[3]], confidence: 1, content_sha256: orderedId(103) },
        { id: evidenceIds[4], method: "embedded_grid", dimension: "geometry", page_index: 1, bbox: bbox(10, 10, 300, 20), source_object_ids: [sourceIds[0]], confidence: 1, content_sha256: orderedId(100) },
        { id: evidenceIds[5], method: "model_structure", dimension: "header", page_index: 1, bbox: tableBox, source_object_ids: [sourceIds[5]], confidence: 1, content_sha256: orderedId(105) },
        { id: evidenceIds[6], method: "embedded_grid", dimension: "geometry", page_index: 1, bbox: tableBox, source_object_ids: [sourceIds[4]], confidence: 1, content_sha256: orderedId(104) },
        { id: evidenceIds[7], method: "source_grid", dimension: "structure", page_index: 1, bbox: tableBox, source_object_ids: [sourceIds[5]], confidence: 1, content_sha256: orderedId(105) },
      ],
      span_decisions: [
        {
          id: orderedId(40), cell_id: cellIds[0], claimed_row_span: 1,
          claimed_col_span: 3, emitted_row_span: 1, emitted_col_span: 3,
          outcome: "supported", evidence_ids: [evidenceIds[4], evidenceIds[7]],
          concern_codes: [] as string[],
        },
      ],
      representation_custody: {
        serializer_policy_id: "p04-table-grid-serializer-v1",
        grid_shape: [2, 3],
        cells_sha256: orderedId(200), rows_sha256: orderedId(201),
        html_sha256: orderedId(202), markdown_sha256: orderedId(203),
        csv_sha256: orderedId(204),
      },
      reconciliation: null,
      gate: null,
      continuation: null,
      concerns: [] as string[],
    },
  };
  return refreshCustody(applyProjection(sealDoclingFixture(table)));
}

test("cold and warm dense-table validation stay within the Node 24 CPU budget", (context) => {
  const dense = denseTable(32, 32);
  const measure = () => {
    const cpuStarted = threadCpuUsage();
    const wallStarted = performance.now();
    const semantics = read(dense);
    const wallMs = performance.now() - wallStarted;
    const cpu = threadCpuUsage(cpuStarted);
    return {
      semantics,
      wallMs,
      cpuMs: (cpu.user + cpu.system) / 1_000,
    };
  };
  const cold = measure();
  const warm = [measure(), measure(), measure()];
  assert.ok(cold.semantics);
  assert.equal(cold.semantics.cells.length, 1_024);
  assert.equal(cold.semantics.slots.length, 1_024);
  assert.ok(
    cold.cpuMs < 100,
    `cold dense validation used ${cold.cpuMs.toFixed(1)}ms CPU`,
  );
  const maximumWarmCpuMs = Math.max(...warm.map((sample) => sample.cpuMs));
  assert.ok(
    maximumWarmCpuMs < 70,
    `warm dense validation used ${maximumWarmCpuMs.toFixed(1)}ms CPU`,
  );
  assert.ok(warm.every((sample) => sample.semantics?.cells.length === 1_024));
  context.diagnostic(
    `dense 32x32 cold=${cold.cpuMs.toFixed(1)}ms CPU/${cold.wallMs.toFixed(1)}ms wall; warm CPU=${warm.map((sample) => sample.cpuMs.toFixed(1)).join(",")}ms; warm wall=${warm.map((sample) => sample.wallMs.toFixed(1)).join(",")}ms`,
  );
  const source = readFileSync(
    new URL("../lib/table-semantics.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /\.find\(/u);
});

test("v1.1 marked table preserves exact cells, spans, headers, blanks, and provenance", () => {
  const source = validTable();
  const before = structuredClone(source);
  const semantics = read(source);
  assert.ok(semantics);
  assert.equal(semantics.version, "1.1");
  assert.equal(semantics.headerRowCount, 1);
  assert.deepEqual(semantics.rows.map((row) => row.cells.length), [1, 3]);
  assert.equal(semantics.cells[0]?.colSpan, 3);
  assert.equal(semantics.cells[1]?.rowHeader, true);
  assert.deepEqual(semantics.cells.map((cell) => cell.text), [
    "<script>alert(1)</script>\nQuarterly result",
    "Same",
    "",
    "Same",
  ]);
  assert.equal(semantics.slots[1]?.kind, "covered");
  assert.equal(semantics.slots[4]?.kind, "explicit_blank");
  assert.deepEqual(source, before);
});

function pythonFloatJson(value: number): string {
  if (Object.is(value, -0)) return "-0.0";
  const negative = value < 0;
  const rendered = Math.abs(value).toString();
  let digits: string;
  let decimalExponent: number;
  const exponentIndex = rendered.indexOf("e");
  if (exponentIndex >= 0) {
    const coefficient = rendered.slice(0, exponentIndex);
    const decimalIndex = coefficient.indexOf(".");
    const wholeDigits = decimalIndex < 0 ? coefficient.length : decimalIndex;
    digits = coefficient.replace(".", "");
    decimalExponent =
      Number(rendered.slice(exponentIndex + 1)) + wholeDigits - 1;
  } else {
    const decimalIndex = rendered.indexOf(".");
    const wholeDigits = decimalIndex < 0 ? rendered.length : decimalIndex;
    const combined = rendered.replace(".", "");
    const firstNonzero = combined.search(/[1-9]/u);
    if (firstNonzero < 0) return negative ? "-0.0" : "0.0";
    digits = combined.slice(firstNonzero).replace(/0+$/u, "");
    decimalExponent = wholeDigits - firstNonzero - 1;
  }
  const sign = negative ? "-" : "";
  if (decimalExponent < -4 || decimalExponent >= 16) {
    const mantissa =
      digits.length === 1 ? digits : `${digits.charAt(0)}.${digits.slice(1)}`;
    return `${sign}${mantissa}e${decimalExponent >= 0 ? "+" : "-"}${Math.abs(decimalExponent)
      .toString()
      .padStart(2, "0")}`;
  }
  if (decimalExponent < 0) {
    return `${sign}0.${"0".repeat(-decimalExponent - 1)}${digits}`;
  }
  const wholeLength = decimalExponent + 1;
  if (digits.length <= wholeLength) {
    return `${sign}${digits}${"0".repeat(wholeLength - digits.length)}.0`;
  }
  return `${sign}${digits.slice(0, wholeLength)}.${digits.slice(wholeLength)}`;
}

function canonicalWordBBox(box: ReturnType<typeof bbox>): string {
  return `{"height":${pythonFloatJson(box.height)},"unit":"pt","width":${pythonFloatJson(box.width)},"x":${pythonFloatJson(box.x)},"y":${pythonFloatJson(box.y)}}`;
}

test("Python-derived float boundary vectors drive every identity preimage exactly", () => {
  const vectors = [
    {
      name: "subnormal and negative zero",
      box: bbox(-0, Number.MIN_VALUE, 1e-7, 1e-5),
      canonical:
        '{"height":1e-05,"unit":"pt","width":1e-07,"x":-0.0,"y":5e-324}',
      digest: "70671e27b58ed990d7d66e48b7e5f08bd444b8b8e960f7ad1463cac9de4b849c",
    },
    {
      name: "fixed and exponent thresholds",
      box: bbox(0.0001, 1e-6, 1e15, 1e16),
      canonical:
        '{"height":1e+16,"unit":"pt","width":1000000000000000.0,"x":0.0001,"y":1e-06}',
      digest: "ad61fcf3fa9cef0b8fef6ebcba7df2e5ce8d567c49eb4f48fd115c453ca32770",
    },
    {
      name: "maximum finite binary64",
      box: bbox(0, 0, Number.MAX_VALUE, 1),
      canonical:
        '{"height":1.0,"unit":"pt","width":1.7976931348623157e+308,"x":0.0,"y":0.0}',
      digest: "9b649fe1f74596db2b8db30da932741bf68cbe2b68a0a19c6b6b00d5f6a66474",
    },
    {
      name: "mixed integer and float source types",
      box: bbox(1, 2, 3, 4),
      canonical: '{"height":4.0,"unit":"pt","width":3,"x":1,"y":2.0}',
      digest: "99f91af0dc987c21be647220f9cd5ace4e6e19ba0154cd5a55207b873fc80368",
    },
  ] as const;

  for (const vector of vectors) {
    assert.equal(
      sha256(`["p04-float-boundary-vector-v1",${vector.canonical}]`),
      vector.digest,
      vector.name,
    );
    const table = denseTable(1, 1, false);
    table.bbox = vector.box;
    const cell = table.cells[0];
    assert.ok(cell);
    cell.bbox = vector.box;
    cell.confidence_dimensions.geometry = 1;
    table.table_evidence.concerns = [];
    sealDoclingFixture(table, 1, () => vector.canonical);
    refreshCustody(applyProjection(table));
    assert.ok(
      readTableSemantics(table, {
        ...CONTEXT,
        pageWidth: Number.MAX_VALUE,
        pageHeight: Number.MAX_VALUE,
      }),
      vector.name,
    );
  }
});

function recoveryWord(
  role: RecoveryRole,
  targetRow: number,
  targetColumn: number,
  text: string,
  box: ReturnType<typeof bbox>,
  fontName: string,
) {
  const id = sha256(
    `["p04-pdfplumber-word-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,${JSON.stringify(role)},${targetRow},${targetColumn},${canonicalWordBBox(box)}]`,
  );
  return {
    id,
    text,
    bbox: box,
    font_name: fontName,
    bold: fontName.toLowerCase().includes("bold"),
  };
}

function recoveryWordSet(
  role: RecoveryRole,
  targetRow: number,
  targetColumn: number,
  words: ReturnType<typeof recoveryWord>[],
) {
  const wordContent = words
    .map(
      (word) =>
        `[${JSON.stringify(word.id)},${JSON.stringify(word.text)},${canonicalWordBBox(word.bbox)},${JSON.stringify(word.font_name)},${word.bold ? "true" : "false"}]`,
    )
    .join(",");
  const content_sha256 = sha256(
    `["p04-pdfplumber-word-set-content-v1",${JSON.stringify(role)},${targetRow},${targetColumn},[${wordContent}]]`,
  );
  const id = sha256(
    `["p04-pdfplumber-word-set-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,${JSON.stringify(role)},${targetRow},${targetColumn},[${words.map((word) => JSON.stringify(word.id)).join(",")}]]`,
  );
  return {
    id,
    engine: "pdfplumber",
    object_type: "table_word_set",
    page_index: 1,
    raw_ref: null,
    role,
    target_row: targetRow,
    target_column: targetColumn,
    words,
    content_sha256,
  };
}

function canonicalIds(values: string[]): string {
  return `[${values.map((value) => JSON.stringify(value)).join(",")}]`;
}

function recoveredHeaderEvidence(
  column: number,
  targetBox: ReturnType<typeof bbox>,
  gridSourceId: string,
  headerSet: ReturnType<typeof recoveryWordSet>,
  bodySet: ReturnType<typeof recoveryWordSet>,
) {
  const sourceIds = [gridSourceId, headerSet.id, bodySet.id].sort();
  const canonicalBox = canonicalWordBBox(targetBox);
  const content_sha256 = sha256(
    `["p04-recovered-header-content-v1",0,${column},${JSON.stringify(gridSourceId)},${JSON.stringify(headerSet.content_sha256)},${JSON.stringify(bodySet.content_sha256)},${canonicalBox},[true,false]]`,
  );
  const id = sha256(
    `["p04-recovered-header-evidence-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,0,${column},${canonicalIds(sourceIds)},${canonicalBox},${JSON.stringify(content_sha256)}]`,
  );
  return {
    id,
    method: "recovered_structure",
    dimension: "header",
    page_index: 1,
    bbox: targetBox,
    source_object_ids: sourceIds,
    confidence: 1,
    content_sha256,
  };
}

function recoveredStructureEvidence(
  tableBox: ReturnType<typeof bbox>,
  gridSourceId: string,
  wordSets: ReturnType<typeof recoveryWordSet>[],
) {
  const sourceIds = [gridSourceId, ...wordSets.map((source) => source.id)].sort();
  const emittedCoordinates = `[${Array.from(
    { length: 3 },
    (_, column) => `[0,${column},"column_header"]`,
  ).join(",")}]`;
  const content_sha256 = sha256(
    `["p04-recovered-table-structure-content-v1","p04-table-recovery-rule-v1",${JSON.stringify(gridSourceId)},[2,3],null,null,null,[],${emittedCoordinates},${canonicalIds(sourceIds)}]`,
  );
  const id = sha256(
    `["p04-recovered-table-structure-evidence-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,${canonicalIds(sourceIds)},${JSON.stringify(content_sha256)}]`,
  );
  return {
    id,
    method: "recovered_structure",
    dimension: "structure",
    page_index: 1,
    bbox: tableBox,
    source_object_ids: sourceIds,
    confidence: 1,
    content_sha256,
  };
}

function recoveredBottomIdentity(
  tag:
    | "p04-recovered-cell-id-v1"
    | "p04-recovered-text-evidence-id-v1"
    | "p04-recovered-geometry-evidence-id-v1",
  sourceId: string,
  targetBox: ReturnType<typeof bbox>,
  column: number,
): string {
  return sha256(
    `[${JSON.stringify(tag)},[${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,${JSON.stringify(sourceId)},${canonicalWordBBox(targetBox)},2,${column}]]`,
  );
}

function recoveredBottomStructureEvidence(
  tableBox: ReturnType<typeof bbox>,
  gridSourceId: string,
  wordSets: ReturnType<typeof recoveryWordSet>[],
) {
  const sourceIds = [gridSourceId, ...wordSets.map((source) => source.id)].sort();
  const assignments = wordSets
    .flatMap((source) =>
      source.words.map((word) => ({ column: source.target_column, word })),
    )
    .sort((left, right) =>
      left.word.bbox.y - right.word.bbox.y ||
      left.word.bbox.x - right.word.bbox.x ||
      left.word.bbox.height - right.word.bbox.height ||
      left.word.bbox.width - right.word.bbox.width,
    )
    .map(
      ({ column, word }) =>
        `[${JSON.stringify(word.id)},${column},${canonicalWordBBox(word.bbox)}]`,
    );
  const emittedCoordinates = wordSets
    .sort((left, right) => left.target_column - right.target_column)
    .map((source) => {
      const targetBox = source.words[0]?.bbox;
      assert.ok(targetBox);
      return `[2,${source.target_column},${canonicalWordBBox(targetBox)},${JSON.stringify(source.words.map((word) => word.text).join(" "))}]`;
    });
  const content_sha256 = sha256(
    `["p04-recovered-table-structure-content-v1","p04-table-recovery-rule-v1",${JSON.stringify(gridSourceId)},[2,3],20.0,{"bottom":53.0,"tolerance":1.0,"top":45.0},[0.0,100.0,200.0],[${assignments.join(",")}],[${emittedCoordinates.join(",")}],${canonicalIds(sourceIds)}]`,
  );
  const id = sha256(
    `["p04-recovered-table-structure-evidence-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,"#/tables/0",2,3,${canonicalIds(sourceIds)},${JSON.stringify(content_sha256)}]`,
  );
  return {
    id,
    method: "recovered_structure",
    dimension: "structure",
    page_index: 1,
    bbox: tableBox,
    source_object_ids: sourceIds,
    confidence: 1,
    content_sha256,
  };
}

function recoveredHeaderTable(options: {
  firstRowHeader?: boolean;
  firstHeaderText?: string;
} = {}) {
  const table = denseTable(2, 3, false);
  const tableBox = bbox(0, 0, 300, 40);
  table.bbox = tableBox;
  for (let index = 0; index < table.cells.length; index += 1) {
    const cell = table.cells[index];
    assert.ok(cell);
    const row = Math.floor(index / 3);
    const column = index % 3;
    cell.text = row === 0 && column === 0
      ? (options.firstHeaderText ?? "H 0")
      : `${row === 0 ? "H" : "B"}${column}`;
    cell.bbox = bbox(column * 100, row * 20, 100, 20);
    cell.confidence_dimensions.geometry = 1;
  }
  if (options.firstRowHeader) {
    const firstCell = table.cells[0];
    assert.ok(firstCell);
    firstCell.row_header = true;
    firstCell.confidence_dimensions.header = 1;
  }
  sealDoclingFixture(table);
  const wordSets: ReturnType<typeof recoveryWordSet>[] = [];
  const headerSets: ReturnType<typeof recoveryWordSet>[] = [];
  const bodySets: ReturnType<typeof recoveryWordSet>[] = [];
  for (let column = 0; column < 3; column += 1) {
    const headerTexts = column === 0 ? ["H", "0"] : [`H${column}`];
    const headerSet = recoveryWordSet(
      "header",
      0,
      column,
      headerTexts.map((text, index) =>
        recoveryWord(
          "header",
          0,
          column,
          text,
          bbox(column * 100 + 10 + index * 25, 5, 20, 8),
          "Arial-Bold",
        ),
      ),
    );
    const bodySet = recoveryWordSet("body_control", 1, column, [
      recoveryWord(
        "body_control",
        1,
        column,
        `B${column}`,
        bbox(column * 100 + 10, 25, 20, 8),
        "Arial-Regular",
      ),
    ]);
    headerSets.push(headerSet);
    bodySets.push(bodySet);
    wordSets.push(headerSet, bodySet);
  }
  table.table_evidence.source_objects = [
    ...table.table_evidence.source_objects,
    ...wordSets,
  ].sort((left, right) => left.id.localeCompare(right.id));
  const gridSourceId = assertString(
    table.table_evidence.source_objects.find(
      (source) => source.object_type === "table_grid",
    )?.id ?? null,
  );
  const globalStructure = recoveredStructureEvidence(
    tableBox,
    gridSourceId,
    wordSets,
  );
  table.table_evidence.evidence = table.table_evidence.evidence.filter(
    (record) =>
      record.dimension !== "structure" && record.method !== "model_structure",
  );
  for (let column = 0; column < 3; column += 1) {
    const cell = table.cells[column];
    assert.ok(cell);
    const headerSet = headerSets[column];
    const bodySet = bodySets[column];
    assert.ok(headerSet);
    assert.ok(bodySet);
    assert.ok(cell.bbox);
    const headerEvidence = recoveredHeaderEvidence(
      column,
      cell.bbox,
      gridSourceId,
      headerSet,
      bodySet,
    );
    const textEvidenceId = table.table_evidence.evidence.find(
      (record) =>
        record.dimension === "text" &&
        record.source_object_ids.length === 1 &&
        record.source_object_ids[0] === cell.source_object_ids[0],
    )?.id;
    assert.ok(textEvidenceId);
    cell.column_header = true;
    cell.confidence_dimensions.header = 1;
    cell.evidence_ids = [
      textEvidenceId,
      globalStructure.id,
      headerEvidence.id,
    ].sort();
    table.table_evidence.evidence.push(headerEvidence);
  }
  table.table_evidence.evidence.push(globalStructure);
  table.table_evidence.evidence.sort((left, right) => left.id.localeCompare(right.id));
  return refreshCustody(applyProjection(table));
}

test("exact pdfplumber word sets validate physical order, typography, targets, content, and links", () => {
  const semantics = read(recoveredHeaderTable());
  assert.ok(semantics);
  const recoverySources = semantics.sourceObjects.filter(
    (source) => source.engine === "pdfplumber",
  );
  assert.equal(recoverySources.length, 6);
  assert.deepEqual(
    recoverySources.map((source) => source.objectType),
    Array.from({ length: 6 }, () => "table_word_set"),
  );
  assert.equal(semantics.cells[0]?.columnHeader, true);
});

test("recovered headers retain independent row ownership and replay text exactly", () => {
  const dualOwnership = read(recoveredHeaderTable({ firstRowHeader: true }));
  assert.ok(dualOwnership);
  assert.equal(dualOwnership.cells[0]?.columnHeader, true);
  assert.equal(dualOwnership.cells[0]?.rowHeader, true);
  assert.equal(dualOwnership.cells[0]?.text, "H 0");

  const whitespaceNormalizedAttack = recoveredHeaderTable({
    firstHeaderText: "H   0",
  });
  assert.equal(read(whitespaceNormalizedAttack), null);
});

test("word-set exact keys, bounds, physical order, typography, and content fail closed", () => {
  const extra = recoveredHeaderTable();
  const extraSource = extra.table_evidence.source_objects.find(
    (source) => source.object_type === "table_word_set",
  );
  assert.ok(extraSource);
  (extraSource as unknown as Record<string, unknown>).unexpected = true;
  assert.equal(read(extra), null);

  const wrongBold = recoveredHeaderTable();
  const wrongBoldSource = wrongBold.table_evidence.source_objects.find(
    (source) => source.object_type === "table_word_set" && source.role === "header",
  );
  assert.ok(wrongBoldSource?.words?.[0]);
  wrongBoldSource.words[0].bold = false;
  assert.equal(read(wrongBold), null);

  const wrongOrder = recoveredHeaderTable();
  const wrongOrderSource = wrongOrder.table_evidence.source_objects.find(
    (source) =>
      source.object_type === "table_word_set" &&
      source.role === "header" &&
      source.words?.length === 2,
  );
  assert.ok(wrongOrderSource?.words);
  wrongOrderSource.words.reverse();
  assert.equal(read(wrongOrder), null);

  const wrongContent = recoveredHeaderTable();
  const wrongContentSource = wrongContent.table_evidence.source_objects.find(
    (source) => source.object_type === "table_word_set",
  );
  assert.ok(wrongContentSource);
  wrongContentSource.content_sha256 = orderedId(999);
  assert.equal(read(wrongContent), null);

  const emptyWords = recoveredHeaderTable();
  const emptySource = emptyWords.table_evidence.source_objects.find(
    (source) => source.object_type === "table_word_set",
  );
  assert.ok(emptySource?.words);
  emptySource.words = [];
  assert.equal(read(emptyWords), null);
});

function denseTable(rowCount: number, columnCount: number, seal = true) {
  const cellCount = rowCount * columnCount;
  const sourceStart = 1_000;
  const evidenceStart = 100_000;
  const cellStart = 200_000;
  const slotStart = 300_000;
  const cells: FixtureCell[] = [];
  const slots = [];
  const sources: FixtureSourceObject[] = [];
  const evidence: FixtureEvidenceRecord[] = [];
  for (let index = 0; index < cellCount; index += 1) {
    const row = Math.floor(index / columnCount);
    const column = index % columnCount;
    const sourceId = orderedId(sourceStart + index);
    const evidenceId = orderedId(evidenceStart + index);
    const cellId = orderedId(cellStart + index);
    const contentHash = orderedId(500_000 + index);
    sources.push({
      id: sourceId, engine: "docling", object_type: "table_cell", page_index: 1,
      raw_ref: "#/tables/0", content_sha256: contentHash,
    });
    evidence.push({
      id: evidenceId, method: "native_text", dimension: "text", page_index: 1,
      bbox: null, source_object_ids: [sourceId], confidence: 1,
      content_sha256: contentHash,
    });
    cells.push({
      id: cellId, row, column, row_span: 1, col_span: 1, text: "x",
      column_header: false, row_header: false, row_section: false, bbox: null,
      source: "native", page_index: 1, evidence_ids: [evidenceId],
      source_object_ids: [sourceId], span_decision_id: null,
      confidence_dimensions: { text: 1, geometry: null, structure: 1, header: null },
    });
    slots.push({
      id: orderedId(slotStart + index), row, column, kind: "anchor" as const,
      cell_id: cellId, covered_by_cell_id: null,
    });
  }
  const geometrySourceId = orderedId(sourceStart + cellCount);
  const gridSourceId = orderedId(sourceStart + cellCount + 1);
  const rootGeometryId = orderedId(evidenceStart + cellCount);
  const rootStructureId = orderedId(evidenceStart + cellCount + 1);
  const tableBox = bbox(0, 0, columnCount * 4, rowCount * 4);
  sources.push(
    { id: geometrySourceId, engine: "docling", object_type: "table_geometry", page_index: 1, raw_ref: "#/tables/0", content_sha256: orderedId(700_000) },
    { id: gridSourceId, engine: "docling", object_type: "table_grid", page_index: 1, raw_ref: "#/tables/0", content_sha256: orderedId(700_001) },
  );
  evidence.push(
    { id: rootGeometryId, method: "embedded_grid", dimension: "geometry", page_index: 1, bbox: tableBox, source_object_ids: [geometrySourceId], confidence: 1, content_sha256: orderedId(700_000) },
    { id: rootStructureId, method: "source_grid", dimension: "structure", page_index: 1, bbox: tableBox, source_object_ids: [gridSourceId], confidence: 1, content_sha256: orderedId(700_001) },
  );
  const table = {
    id: "dense-table", type: "table", engine: "docling", source: "native",
    bbox: tableBox, row_count: rowCount, column_count: columnCount,
    rows: [] as string[][], value: [] as string[][], html: "", md: "", csv: "",
    cells,
    table_evidence: {
      policy_id: "p04-table-evidence-v1", version: "1.1", scope: ["P04-US01"],
      status: "valid", table_id: orderedId(800_000), candidate_id: orderedId(800_001),
      page_index: 1,
      grid: { row_count: rowCount, column_count: columnCount, cell_ids: cells.map((cell) => cell.id) },
      slots, source_objects: sources, evidence, span_decisions: [],
      representation_custody: {
        serializer_policy_id: "p04-table-grid-serializer-v1", grid_shape: [rowCount, columnCount],
        cells_sha256: orderedId(1), rows_sha256: orderedId(2), html_sha256: orderedId(3),
        markdown_sha256: orderedId(4), csv_sha256: orderedId(5),
      },
      reconciliation: null, gate: null, continuation: null,
      concerns: ["table_source_cell_bbox_unresolved"],
    },
  };
  return refreshCustody(
    applyProjection(seal ? sealDoclingFixture(table) : table),
  );
}

function recoveredBottomTable() {
  const table = denseTable(2, 3, false);
  const tableBox = bbox(0, 0, 300, 60);
  table.bbox = tableBox;
  table.row_count = 3;
  table.table_evidence.grid.row_count = 3;
  table.table_evidence.representation_custody.grid_shape = [3, 3];
  table.table_evidence.concerns = [];
  for (let index = 0; index < table.cells.length; index += 1) {
    const cell = table.cells[index];
    assert.ok(cell);
    const row = Math.floor(index / 3);
    const column = index % 3;
    const cellBox = bbox(column * 100, row * 20, 100, 20);
    cell.text = `P${row}${column}`;
    cell.bbox = cellBox;
    cell.confidence_dimensions.geometry = 1;
    const textEvidence = table.table_evidence.evidence.find(
      (record) => record.id === cell.evidence_ids[0],
    );
    assert.ok(textEvidence);
    textEvidence.bbox = cellBox;
  }
  sealDoclingFixture(table, 2);
  const bottomSets = Array.from({ length: 3 }, (_, column) =>
    recoveryWordSet("bottom_row", 2, column, [
      recoveryWord(
        "bottom_row",
        2,
        column,
        `Z${column}`,
        bbox(column * 100 + 10, 45, 20, 8),
        "Arial-Regular",
      ),
    ]),
  );
  table.table_evidence.source_objects = [
    ...table.table_evidence.source_objects,
    ...bottomSets,
  ].sort((left, right) => left.id.localeCompare(right.id));
  const gridSourceId = assertString(
    table.table_evidence.source_objects.find(
      (source) => source.object_type === "table_grid",
    )?.id ?? null,
  );
  const globalStructure = recoveredBottomStructureEvidence(
    tableBox,
    gridSourceId,
    bottomSets,
  );
  table.table_evidence.evidence = table.table_evidence.evidence.filter(
    (record) => record.dimension !== "structure",
  );
  for (let column = 0; column < 3; column += 1) {
    const source = bottomSets[column];
    const targetBox = source?.words[0]?.bbox;
    assert.ok(source);
    assert.ok(targetBox);
    const cellId = recoveredBottomIdentity(
      "p04-recovered-cell-id-v1",
      source.id,
      targetBox,
      column,
    );
    const textEvidenceId = recoveredBottomIdentity(
      "p04-recovered-text-evidence-id-v1",
      source.id,
      targetBox,
      column,
    );
    const geometryEvidenceId = recoveredBottomIdentity(
      "p04-recovered-geometry-evidence-id-v1",
      source.id,
      targetBox,
      column,
    );
    table.cells.push({
      id: cellId,
      row: 2,
      column,
      row_span: 1,
      col_span: 1,
      text: `Z${column}`,
      column_header: false,
      row_header: false,
      row_section: false,
      bbox: targetBox,
      source: "native",
      page_index: 1,
      evidence_ids: [textEvidenceId, geometryEvidenceId, globalStructure.id].sort(),
      source_object_ids: [source.id],
      span_decision_id: null,
      confidence_dimensions: {
        text: 1,
        geometry: 1,
        structure: 1,
        header: null,
      },
    });
    table.table_evidence.grid.cell_ids.push(cellId);
    table.table_evidence.slots.push({
      id: sha256(
        `["p04-slot-id-v1",${JSON.stringify(CONTEXT.sourceSha256)},1,${JSON.stringify(table.table_evidence.table_id)},${JSON.stringify(table.table_evidence.candidate_id)},2,${column}]`,
      ),
      row: 2,
      column,
      kind: "anchor" as const,
      cell_id: cellId,
      covered_by_cell_id: null,
    });
    table.table_evidence.evidence.push(
      {
        id: textEvidenceId,
        method: "native_text",
        dimension: "text",
        page_index: 1,
        bbox: targetBox,
        source_object_ids: [source.id],
        confidence: 1,
        content_sha256: source.content_sha256,
      },
      {
        id: geometryEvidenceId,
        method: "recovered_structure",
        dimension: "geometry",
        page_index: 1,
        bbox: targetBox,
        source_object_ids: [source.id],
        confidence: 1,
        content_sha256: source.content_sha256,
      },
    );
  }
  table.table_evidence.evidence.push(globalStructure);
  table.table_evidence.evidence.sort((left, right) => left.id.localeCompare(right.id));
  return refreshCustody(applyProjection(table));
}

test("bottom-row recovery validates exact global, cell, text, geometry, and grid commitments", () => {
  const table = recoveredBottomTable();
  const semantics = read(table);
  assert.ok(semantics);
  assert.deepEqual(semantics.cells.slice(-3).map((cell) => cell.text), [
    "Z0",
    "Z1",
    "Z2",
  ]);
  assert.equal(
    semantics.sourceObjects.some(
      (source) => source.engine === "docling" && source.objectType === "table_grid",
    ),
    true,
  );

  const alteredCell = recoveredBottomTable();
  const lastCell = alteredCell.cells.at(-1);
  assert.ok(lastCell);
  lastCell.id = orderedId(999_001);
  alteredCell.table_evidence.grid.cell_ids[alteredCell.cells.length - 1] = lastCell.id;
  alteredCell.table_evidence.slots.at(-1)!.cell_id = lastCell.id;
  refreshCustody(alteredCell);
  assert.equal(read(alteredCell), null);

  const missingGrid = recoveredBottomTable();
  missingGrid.table_evidence.source_objects =
    missingGrid.table_evidence.source_objects.filter(
      (source) => source.object_type !== "table_grid",
    );
  assert.equal(read(missingGrid), null);
});

test("hostile and multiline cell text stays inert and serializer escaping is exact", () => {
  const hostile = `A&B <tag> "double" 'single',value\nnext`;
  const table = validTable(hostile);
  const semantics = read(table);
  assert.ok(semantics);
  const markup = renderToStaticMarkup(createElement("td", null, semantics.cells[3]?.text));
  assert.doesNotMatch(markup, /<tag>/u);
  assert.match(markup, /A&amp;B &lt;tag&gt;/u);
  assert.match(table.html, /A&amp;B &lt;tag&gt; &quot;double&quot; &#x27;single&#x27;,value<br>next/u);
  assert.match(table.csv, /"A&B <tag> ""double"" 'single',value\nnext"$/u);
});

test("unmarked, non-valid, wrong-version, missing-context, and page mismatch fail closed", () => {
  const unmarked = validTable();
  delete (unmarked as Record<string, unknown>).table_evidence;
  assert.equal(read(unmarked), null);
  for (const status of ["unresolved", "structural_failure", "unknown"]) {
    const table = validTable();
    table.table_evidence.status = status;
    assert.equal(read(table), null);
  }
  const old = validTable();
  old.table_evidence.version = "1.0";
  assert.equal(read(old), null);
  assert.equal(readTableSemantics(validTable()), null);
  assert.equal(
    readTableSemantics(validTable(), { ...CONTEXT, pageIndex: 2 }),
    null,
  );
  assert.equal(
    readTableSemantics(validTable(), { ...CONTEXT, unit: "px" as "pt" }),
    null,
  );
});

test("v1.1 rejects vector/later-story ownership and continuation vocabulary", () => {
  for (const method of ["vector_rule", "derived_comparison"]) {
    const table = validTable();
    table.table_evidence.evidence[0].method = method;
    assert.equal(read(table), null);
  }
  for (const dimension of ["ownership", "continuation"]) {
    const table = validTable();
    table.table_evidence.evidence[0].dimension = dimension;
    assert.equal(read(table), null);
  }
  const vectorSource = validTable();
  vectorSource.table_evidence.source_objects[0].engine = "pdfplumber";
  vectorSource.table_evidence.source_objects[0].object_type = "vector_grid";
  assert.equal(read(vectorSource), null);
});

test("exact graph reachability rejects orphan sources and orphan evidence", () => {
  const orphanSource = validTable();
  orphanSource.table_evidence.source_objects.push({
    id: orderedId(16), engine: "docling", object_type: "table_cell", page_index: 1,
    raw_ref: "#/tables/0/cells/orphan", content_sha256: orderedId(106),
  });
  assert.equal(read(orphanSource), null);

  const orphanEvidence = validTable();
  orphanEvidence.table_evidence.evidence.push({
    id: orderedId(28), method: "native_text", dimension: "text", page_index: 1,
    bbox: orphanEvidence.cells[0].bbox,
    source_object_ids: [orphanEvidence.table_evidence.source_objects[0].id],
    confidence: 1,
    content_sha256: orphanEvidence.table_evidence.source_objects[0].content_sha256,
  });
  assert.equal(read(orphanEvidence), null);
});

test("coherently forged rows and representations fail even with every digest refreshed", () => {
  const forged = validTable();
  forged.rows[1][2] = "forged";
  forged.value[1][2] = "forged";
  forged.html = forged.html.replace("<td>Same</td>", "<td>forged</td>");
  forged.md = forged.html;
  forged.csv = "<script>alert(1)</script>\nQuarterly result,,\nSame,,forged";
  refreshCustody(forged);
  assert.equal(read(forged), null);

  const digestOnly = validTable();
  digestOnly.html += "\n";
  digestOnly.md = digestOnly.html;
  refreshCustody(digestOnly);
  assert.equal(read(digestOnly), null);
});

test("slot, span, source, evidence, header, and page geometry inconsistencies fail closed", () => {
  const badCover = validTable();
  badCover.table_evidence.slots[1].covered_by_cell_id = orderedId(999);
  assert.equal(read(badCover), null);

  const badSpan = validTable();
  badSpan.table_evidence.span_decisions[0].evidence_ids = [orderedId(20), orderedId(27)];
  assert.equal(read(badSpan), null);

  const missingHeader = validTable();
  missingHeader.cells[1].evidence_ids = [orderedId(21)];
  assert.equal(read(missingHeader), null);

  const wrongMethod = validTable();
  wrongMethod.table_evidence.evidence[3].method = "native_text";
  assert.equal(read(wrongMethod), null);

  const outsidePage = validTable();
  outsidePage.cells[3].bbox.x = 600;
  outsidePage.table_evidence.evidence[3].bbox.x = 600;
  refreshCustody(outsidePage);
  assert.equal(read(outsidePage), null);
});

test("valid tables accept only exact supported span decisions", () => {
  const refused = validTable();
  refused.table_evidence.span_decisions[0].outcome = "refused";
  refused.table_evidence.span_decisions[0].emitted_col_span = 1;
  refused.table_evidence.span_decisions[0].concern_codes = [
    "table_source_span_evidence_unresolved",
  ];
  assert.equal(read(refused), null);

  const emittedMismatch = validTable();
  emittedMismatch.table_evidence.span_decisions[0].emitted_col_span = 2;
  assert.equal(read(emittedMismatch), null);

  const wrongIdentity = validTable();
  const forgedDecisionId = orderedId(990_001);
  wrongIdentity.table_evidence.span_decisions[0].id = forgedDecisionId;
  wrongIdentity.cells[0].span_decision_id = forgedDecisionId;
  refreshCustody(wrongIdentity);
  assert.equal(read(wrongIdentity), null);

  const unitDecision = validTable();
  const unitCell = unitDecision.cells[3];
  assert.ok(unitCell);
  const unitDecisionId = orderedId(990_002);
  unitCell.span_decision_id = unitDecisionId;
  unitDecision.table_evidence.span_decisions.push({
    id: unitDecisionId,
    cell_id: unitCell.id,
    claimed_row_span: 1,
    claimed_col_span: 1,
    emitted_row_span: 1,
    emitted_col_span: 1,
    outcome: "supported",
    evidence_ids: [orderedId(24), orderedId(27)],
    concern_codes: [],
  });
  refreshCustody(unitDecision);
  assert.equal(read(unitDecision), null);
});

test("cell UTF-8 limits are exact and malformed Unicode fails closed", () => {
  const exact = validTable("é".repeat(8_192));
  assert.ok(read(exact));
  assert.equal(read(validTable(`${"é".repeat(8_192)}a`)), null);
  assert.ok(read(validTable("😀".repeat(4_096))));
  assert.equal(read(validTable(`${"😀".repeat(4_096)}a`)), null);
  assert.equal(read(validTable("safe\ud800unsafe")), null);
  assert.equal(read(validTable("safe\udc00unsafe")), null);
});

test("iterative marked-table byte/depth checks reject aggregate and cyclic payloads", () => {
  const aggregate = validTable();
  (aggregate as Record<string, unknown>).padding = Array.from(
    { length: 9 },
    () => "x".repeat(1_000_000),
  );
  const aggregateStarted = performance.now();
  assert.equal(read(aggregate), null);
  assert.ok(performance.now() - aggregateStarted < 1_000);

  const deep = validTable();
  const root: Record<string, unknown> = {};
  let cursor = root;
  for (let depth = 0; depth < 33; depth += 1) {
    const child: Record<string, unknown> = {};
    cursor.child = child;
    cursor = child;
  }
  (deep as Record<string, unknown>).deep = root;
  assert.equal(read(deep), null);

  const cyclic = validTable();
  const cycle: Record<string, unknown> = {};
  cycle.self = cycle;
  (cyclic as Record<string, unknown>).cycle = cycle;
  assert.equal(read(cyclic), null);
});

test("word count and table-wide recovery-set caps fail closed", () => {
  const tooManyWords = recoveredHeaderTable();
  const wordSource = tooManyWords.table_evidence.source_objects.find(
    (source) => source.object_type === "table_word_set" && source.role === "header",
  );
  assert.ok(wordSource?.words);
  wordSource.words = Array.from({ length: 65 }, (_, index) => ({
    id: orderedId(900_000 + index),
    text: "x",
    bbox: bbox(10 + index, 12, 0.5, 8),
    font_name: "Arial-Bold",
    bold: true,
  }));
  assert.equal(read(tooManyWords), null);

  const tooManySets = validTable();
  const additions: FixtureSourceObject[] = Array.from(
    { length: 49 },
    (_, index) => ({
    id: orderedId(910_000 + index),
    engine: "pdfplumber",
    object_type: "table_word_set",
    page_index: 1,
    raw_ref: null,
    role: "header" as const,
    target_row: 0,
    target_column: 0,
    words: [
      {
        id: orderedId(920_000 + index),
        text: "x",
        bbox: bbox(10 + index, 12, 0.5, 8),
        font_name: "Arial-Bold",
        bold: true,
      },
    ],
    content_sha256: orderedId(930_000 + index),
    }),
  );
  tooManySets.table_evidence.source_objects = [
    ...tooManySets.table_evidence.source_objects,
    ...additions,
  ].sort((left, right) => left.id.localeCompare(right.id));
  assert.equal(read(tooManySets), null);
});

test("reader keeps one sync export, no runtime imports, and bounded iterative accounting", () => {
  const source = readFileSync(
    new URL("../lib/table-semantics.ts", import.meta.url),
    "utf8",
  );
  assert.equal((source.match(/\bexport\b/gu) ?? []).length, 1);
  assert.match(
    source,
    /export function readTableSemantics\(\s*item: unknown,\s*context\?: TableSemanticsContext,\s*\): ValidatedTableSemantics \| null/u,
  );
  assert.doesNotMatch(source, /^\s*import\s/mu);
  assert.match(source, /MAX_TABLE_BYTES = 8_388_608/u);
  assert.match(source, /MAX_TABLE_NODES = 4_194_304/u);
  assert.match(source, /MAX_TABLE_DEPTH = 32/u);
  assert.match(source, /function markedTableFitsResourceBounds/u);
  assert.match(source, /function replayTableGrid/u);
});

test("workspace passes document/page context and renders only escaped authoritative cell text", () => {
  const source = readFileSync(
    new URL("../app/clearleaf-workspace.tsx", import.meta.url),
    "utf8",
  );
  const itemViewStart = source.indexOf("function ContentItemView");
  const itemViewEnd = source.indexOf("function RenderedPage", itemViewStart);
  const itemView = source.slice(itemViewStart, itemViewEnd);
  const tableStart = source.indexOf(
    "  const tableAuthority = tableItemAuthority(item);",
  );
  const tableEnd = source.indexOf('  if (type === "list") {', tableStart);
  const tableRenderer = source.slice(tableStart, tableEnd);
  const predecessorStart = tableRenderer.indexOf("    const rows = item.rows ?? [];");
  const semanticRenderer = tableRenderer.slice(0, predecessorStart);
  assert.notEqual(itemViewStart, -1);
  assert.notEqual(itemViewEnd, -1);
  assert.notEqual(tableStart, -1);
  assert.notEqual(tableEnd, -1);
  assert.match(source, /const ContentItemView = memo\(function ContentItemView/u);
  assert.match(itemView, /Object identity is therefore a safe validation-cache boundary/u);
  assert.match(itemView, /same-identity mutation is unsupported/u);
  assert.match(tableRenderer, /const tableContext =/u);
  assert.match(tableRenderer, /pageIndex: sourcePage\.page_index/u);
  assert.match(tableRenderer, /pageWidth: sourcePage\.page_width/u);
  assert.match(tableRenderer, /pageHeight: sourcePage\.page_height/u);
  assert.match(tableRenderer, /const tableSemantics = readTableSemantics\(item, tableContext\)/u);
  assert.match(semanticRenderer, /\{cell\.text\}/u);
  assert.doesNotMatch(semanticRenderer, /renderValidatedTextRunOverlay/u);
  assert.doesNotMatch(semanticRenderer, /dangerouslySetInnerHTML/u);
  assert.match(tableRenderer, /const rows = item\.rows \?\? \[\]/u);
  assert.match(source, /sourceSha256=\{result\?\.document\.sha256 \?\? ""\}/u);
  assert.match(source, /sourcePage=\{sourcePage\}/u);
});

class FakeDomDocument extends EventTarget {
  readonly nodeType = 9;
  readonly nodeName = "#document";
  activeElement: FakeDomElement | null = null;
  defaultView: Record<string, unknown> = {};
  documentElement: FakeDomElement;
  body: FakeDomElement;

  constructor() {
    super();
    this.documentElement = new FakeDomElement("html", this);
    this.body = new FakeDomElement("body", this);
    this.documentElement.appendChild(this.body);
    this.activeElement = this.body;
  }

  createElement(tagName: string): FakeDomElement {
    return new FakeDomElement(tagName, this);
  }

  createElementNS(_namespace: string, tagName: string): FakeDomElement {
    return this.createElement(tagName);
  }

  createTextNode(value: string): FakeDomText {
    return new FakeDomText(value, this);
  }

  createComment(value: string): FakeDomText {
    return new FakeDomText(value, this, 8);
  }
}

class FakeDomNode extends EventTarget {
  parentNode: FakeDomNode | null = null;
  readonly childNodes: FakeDomNode[] = [];
  readonly ownerDocument: FakeDomDocument;

  constructor(ownerDocument: FakeDomDocument) {
    super();
    this.ownerDocument = ownerDocument;
  }

  get firstChild(): FakeDomNode | null {
    return this.childNodes[0] ?? null;
  }

  get lastChild(): FakeDomNode | null {
    return this.childNodes.at(-1) ?? null;
  }

  get textContent(): string {
    return this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value: string) {
    void value;
  }

  appendChild<T extends FakeDomNode>(child: T): T {
    child.parentNode?.removeChild(child);
    this.childNodes.push(child);
    child.parentNode = this;
    return child;
  }

  insertBefore<T extends FakeDomNode>(child: T, before: FakeDomNode | null): T {
    if (before === null) return this.appendChild(child);
    const index = this.childNodes.indexOf(before);
    assert.notEqual(index, -1);
    child.parentNode?.removeChild(child);
    this.childNodes.splice(index, 0, child);
    child.parentNode = this;
    return child;
  }

  removeChild<T extends FakeDomNode>(child: T): T {
    const index = this.childNodes.indexOf(child);
    assert.notEqual(index, -1);
    this.childNodes.splice(index, 1);
    child.parentNode = null;
    return child;
  }
}

class FakeDomText extends FakeDomNode {
  readonly nodeName: string;
  readonly nodeType: number;
  private value: string;

  constructor(
    value: string,
    ownerDocument: FakeDomDocument,
    nodeType = 3,
  ) {
    super(ownerDocument);
    this.value = value;
    this.nodeType = nodeType;
    this.nodeName = nodeType === 8 ? "#comment" : "#text";
  }

  get nodeValue(): string {
    return this.value;
  }

  set nodeValue(value: string) {
    this.value = value;
  }

  get textContent(): string {
    return this.value;
  }

  set textContent(value: string) {
    this.value = value;
  }
}

class FakeDomElement extends FakeDomNode {
  readonly nodeType = 1;
  readonly namespaceURI = "http://www.w3.org/1999/xhtml";
  readonly style: Record<string, string> = {};
  readonly tagName: string;
  readonly nodeName: string;
  private readonly attributes = new Map<string, string>();
  private textValue = "";

  constructor(tagName: string, ownerDocument: FakeDomDocument) {
    super(ownerDocument);
    this.tagName = tagName.toUpperCase();
    this.nodeName = this.tagName;
  }

  override appendChild<T extends FakeDomNode>(child: T): T {
    this.textValue = "";
    return super.appendChild(child);
  }

  override insertBefore<T extends FakeDomNode>(
    child: T,
    before: FakeDomNode | null,
  ): T {
    this.textValue = "";
    return super.insertBefore(child, before);
  }

  setAttribute(name: string, value: string): void {
    this.attributes.set(name, value);
  }

  removeAttribute(name: string): void {
    this.attributes.delete(name);
  }

  get textContent(): string {
    return this.textValue || this.childNodes.map((child) => child.textContent).join("");
  }

  set textContent(value: string) {
    for (const child of this.childNodes) child.parentNode = null;
    this.childNodes.length = 0;
    this.textValue = value;
  }
}

test("committed rerenders honor the immutable atomic parse-result cache boundary", async () => {
  const dense = denseTable(24, 24);
  let validationCount = 0;
  const MemoizedTableChild = memo(function MemoizedTableChild({
    table,
    sourcePage,
    sourceSha256,
  }: {
    table: unknown;
    sourcePage: { pageIndex: number; pageWidth: number; pageHeight: number };
    sourceSha256: string;
  }) {
    validationCount += 1;
    const semantics = readTableSemantics(table, {
      sourceSha256,
      pageIndex: sourcePage.pageIndex,
      pageWidth: sourcePage.pageWidth,
      pageHeight: sourcePage.pageHeight,
      unit: "pt",
    });
    return createElement("output", null, semantics?.cells.length ?? "invalid");
  });
  const sourcePage = { pageIndex: 1, pageWidth: 612, pageHeight: 792 };
  const document = new FakeDomDocument();
  const container = document.createElement("main");
  const iframeClass = class FakeHtmlIFrameElement {};
  document.defaultView = {
    document,
    HTMLIFrameElement: iframeClass,
    HTMLElement: FakeDomElement,
    Node: FakeDomNode,
  };
  const globals = globalThis as unknown as Record<string, unknown>;
  const previousDescriptors = new Map(
    ["document", "window", "HTMLElement", "Node"].map((name) => [
      name,
      Object.getOwnPropertyDescriptor(globalThis, name),
    ]),
  );
  for (const [name, value] of Object.entries({
    document,
    window: document.defaultView,
    HTMLElement: FakeDomElement,
    Node: FakeDomNode,
  })) {
    Object.defineProperty(globals, name, {
      configurable: true,
      value,
      writable: true,
    });
  }

  const root = createRoot(container as never);
  const render = (table: unknown, page = sourcePage): void => {
    flushSync(() => {
      root.render(
        createElement(MemoizedTableChild, {
          table,
          sourcePage: page,
          sourceSha256: CONTEXT.sourceSha256,
        }),
      );
    });
  };
  try {
    render(dense);
    assert.equal(container.textContent, "576");
    assert.equal(validationCount, 1);
    for (let iteration = 0; iteration < 15; iteration += 1) render(dense);
    assert.equal(validationCount, 1);

    // Parsed result graphs are immutable while mounted. A new parse commits by
    // atomically replacing item/page references; same-identity mutation is not
    // supported and is deliberately not claimed by this cache contract.
    const replacedTable = structuredClone(dense);
    render(replacedTable);
    assert.equal(validationCount, 2);
    const replacedPage = { ...sourcePage };
    render(replacedTable, replacedPage);
    assert.equal(validationCount, 3);
    for (let iteration = 0; iteration < 5; iteration += 1) {
      render(replacedTable, replacedPage);
    }
    assert.equal(validationCount, 3);
  } finally {
    flushSync(() => root.unmount());
    await new Promise<void>((resolve) => setImmediate(resolve));
    await new Promise<void>((resolve) => setImmediate(resolve));
    for (const [name, descriptor] of previousDescriptors) {
      if (descriptor === undefined) delete globals[name];
      else Object.defineProperty(globals, name, descriptor);
    }
  }
});

test("recomputes exact Docling and recovery identities from the final backend-emitted header vector", () => {
  const sourceSha256 = "a".repeat(64);
  const tableReference = "#/tables/recovery";
  const tableBox = bbox(0, 0, 200, 100);
  const tableBoxJson = canonicalWordBBox(tableBox);
  const tableId = "1530ac16dcf9fa8e72ba0d4a32ca17cc47779ceb306c9452e25d52faedfa17e8";
  const candidateId = "8929729de0233c3230342d9cb9b595879c9c0b04b00b209fb5671e60a2f85e7e";
  const geometrySourceId = "90c2c01a54a06e6a733ba796f87d382a8e70c33cc8bd9f39c1505c63c2c0e5a5";
  const geometryContent = "41351da7e7c26bb6e34105ef419e6deb7f7e274fa6173234fc295550273312ce";
  const geometryEvidenceId = "d958f6ade6b59927153a69f0859d74e8332c3a759f7eaac27da24966a94a6ef6";
  const gridSourceId = "c0177fddf20fbe2b89b2c857ed63694433c77beb6afa80959ef1373ddebead90";
  assert.equal(
    sha256(
      `["p04-table-id-v1",${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBoxJson},2,2]`,
    ),
    tableId,
  );
  assert.equal(
    sha256(
      `["p04-candidate-id-v1",${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBoxJson},2,2]`,
    ),
    candidateId,
  );
  assert.equal(
    sha256(`["p04-geometry-source-content-v1",${tableBoxJson},1]`),
    geometryContent,
  );
  assert.equal(
    sha256(
      `["p04-geometry-source-id-v1",${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBoxJson}]`,
    ),
    geometrySourceId,
  );
  assert.equal(
    sha256(
      `["p04-geometry-evidence-id-v1",${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(tableReference)},${tableBoxJson}]`,
    ),
    geometryEvidenceId,
  );
  assert.equal(
    sha256(
      `["p04-structure-source-id-v1",${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(tableReference)},2,2]`,
    ),
    gridSourceId,
  );

  const canonicalIntegerBBox = (box: ReturnType<typeof bbox>): string =>
    `{"height":${box.height},"unit":"pt","width":${box.width},"x":${box.x},"y":${box.y}}`;
  const emittedCells = [
    {
      row: 0, column: 0, text: "Term", rawRef: "#/texts/0-0",
      box: bbox(0, 10, 100, 20),
      cellId: "d1a28067fa4701163eb1b9c07950aeae0baed9e4807642f287406fd34b0b897d",
      sourceId: "b6f8e6f41e9668129f793a8b018b03ff5b29871d6a7b6da29cf285f7dd24dedd",
      content: "2babec7ab6ea3e4dc0c628fe1f19d8d4e5bf9c33392f36bbb3bedeb3f37462c3",
      textEvidenceId: "daabab66ee1bc299a63d24d03d70a0259ed45e57c5dd88b7d9f94f496d9d7ca0",
    },
    {
      row: 0, column: 1, text: "Definition", rawRef: "#/texts/0-1",
      box: bbox(100, 10, 100, 20),
      cellId: "9c612e4f37695a326b40e05bdbdaffcac8f10cf37839ed91d23b6ffffc9be975",
      sourceId: "38e31fdf5491150fd78c75d43eaa9a76a71e83092e655efb437536a312742155",
      content: "c7218543f47eeeb18d5de98494af8e8116125038b50c930934a5c8a7d7cdea4e",
      textEvidenceId: "ffe5500c3fc8cb77f68e58c1a753336964f90a627e4b76f7d267cef0d63ab4bb",
    },
    {
      row: 1, column: 0, text: "FERS", rawRef: "#/texts/1-0",
      box: bbox(0, 30, 100, 20),
      cellId: "ebbdbe8dd6af774a3e07f454c35bb750bf3d76baec15e855dc61af1461a079e9",
      sourceId: "793806cafc0535d98151f5c0a6a4fa722ccc93bc85ac4701b9e17a4bfae58b4e",
      content: "d357149a422807e4eadfe9d7143eb21a693581d66e7ce5c6ffcb919d88e6f03b",
      textEvidenceId: "8e906518a13c09b1ca81eb8822995162501e12ef662bbf4fd51564f8cbdc73eb",
    },
    {
      row: 1, column: 1, text: "Federal Employees", rawRef: "#/texts/1-1",
      box: bbox(100, 30, 100, 20),
      cellId: "30fb0e7581b98a17a2103d245bbb5bf79d54c7fd034cb7f61af1ee203e9cdd71",
      sourceId: "f3d4c5d79aa514a2aa2b83ac2ffbab0ef95a920794c706a915f037257e076c19",
      content: "a4f914813bd0fe9dbe2925c6e2912e06a50915d605bbd3bfea7a7267988e546e",
      textEvidenceId: "c0eec8e93896720d7ba1d5a5b81e382ad6811d9a89cfc0f30bdfd649da7cd5d2",
    },
  ];
  const normalizedCells: string[] = [];
  for (const cell of emittedCells) {
    const cellBoxJson = canonicalIntegerBBox(cell.box);
    const identityTail = `[${JSON.stringify(sourceSha256)},1,"docling",${JSON.stringify(cell.rawRef)},${cellBoxJson},${cell.row},${cell.column},1,1]`;
    assert.equal(sha256(`["p04-cell-id-v1",${identityTail}]`), cell.cellId);
    assert.equal(sha256(`["p04-cell-source-id-v1",${identityTail}]`), cell.sourceId);
    assert.equal(
      sha256(`["p04-text-evidence-id-v1",${identityTail}]`),
      cell.textEvidenceId,
    );
    assert.equal(
      sha256(
        `["p04-cell-content-v1",${JSON.stringify(cell.rawRef)},${cellBoxJson},${cell.row},${cell.column},1,1,${JSON.stringify(cell.text)},false,false,false]`,
      ),
      cell.content,
    );
    normalizedCells.push(
      `[${cell.row},${cell.column},1,1,${JSON.stringify(cell.text)},false,false,false,${cellBoxJson},${JSON.stringify(cell.rawRef)}]`,
    );
  }
  const gridContent = sha256(
    `["p04-structure-source-content-v1",${JSON.stringify(tableReference)},2,2,[${normalizedCells.join(",")}]]`,
  );
  assert.equal(
    gridContent,
    "875fb9aed62e4ed03df5ccdd9db204f85504916808ff57849f6827e4b8d64648",
  );

  const backendWordSets = [
    {
      role: "header", row: 0, column: 0,
      id: "f16b8d544ec5d4eaa39d520fae879d24903b63ba193be8ee58457cb4f3177865",
      content: "79883eee4c7767ef6f68c67b133509ab119bd4164a748bd57b066c933314f3fd",
      words: [
        { text: "Term", box: bbox(10, 15, 40, 10), font: "Fixture-Bold", bold: true, id: "04f14769f196a5f2589f01d6653dfff9f291d0b474adc2637abc1f34c447239e" },
      ],
    },
    {
      role: "body_control", row: 1, column: 0,
      id: "90a7290a4453243b17d23323a6b96648b9f9889290c2e56854aa2102852136a5",
      content: "b407fc745c0e12d2f224b12450bf9f88854a1d8f857b3850882bbec20a5e6c94",
      words: [
        { text: "FERS", box: bbox(10, 35, 40, 10), font: "Fixture-Regular", bold: false, id: "d2871eb59e009db437babc3ce8f8e1cb4f39d21cb3aab98d26561ec6a18551d7" },
      ],
    },
    {
      role: "header", row: 0, column: 1,
      id: "4ec4995495d051404a11da656a5b9e235219915e004cdb269abc2a56557e96cc",
      content: "2b63569720cf84130adfd5ce2241e4ee931e76b2991a1f87a269395897708909",
      words: [
        { text: "Definition", box: bbox(110, 15, 70, 10), font: "Fixture-Bold", bold: true, id: "c598c0bcc839df59ecc9f7c2dfaf83ff70023b6dabf5908af2591df3f1f7d224" },
      ],
    },
    {
      role: "body_control", row: 1, column: 1,
      id: "07c467207f1829702d918c6ec667c40bd44b5f38f8f6f4cecc7d28113a578f9d",
      content: "251298f21f438d59dca9b6838d01be9f02f1d59fd8bf3b0695a45a550522a16b",
      words: [
        { text: "Federal", box: bbox(110, 35, 30, 10), font: "Fixture-Regular", bold: false, id: "801f6f61612b723aa4f8cb1b27c187402ab0c93631281b3dfc722b0e689459fe" },
        { text: "Employees", box: bbox(145, 35, 45, 10), font: "Fixture-Regular", bold: false, id: "501b29c83a6bd6f035a1023878be5578ff1e47299be7e88aaeec468822b0df59" },
      ],
    },
  ] as const;
  for (const source of backendWordSets) {
    for (const word of source.words) {
      assert.equal(
        sha256(
          `["p04-pdfplumber-word-id-v1",${JSON.stringify(sourceSha256)},1,${JSON.stringify(tableReference)},2,2,${JSON.stringify(source.role)},${source.row},${source.column},${canonicalWordBBox(word.box)}]`,
        ),
        word.id,
      );
    }
    const wordsJson = source.words.map(
      (word) =>
        `[${JSON.stringify(word.id)},${JSON.stringify(word.text)},${canonicalWordBBox(word.box)},${JSON.stringify(word.font)},${word.bold ? "true" : "false"}]`,
    );
    assert.equal(
      sha256(
        `["p04-pdfplumber-word-set-content-v1",${JSON.stringify(source.role)},${source.row},${source.column},[${wordsJson.join(",")}]]`,
      ),
      source.content,
    );
    assert.equal(
      sha256(
        `["p04-pdfplumber-word-set-id-v1",${JSON.stringify(sourceSha256)},1,${JSON.stringify(tableReference)},2,2,${JSON.stringify(source.role)},${source.row},${source.column},[${source.words.map((word) => JSON.stringify(word.id)).join(",")}]]`,
      ),
      source.id,
    );
  }

  const recoverySourceIds = [
    gridSourceId,
    ...backendWordSets.map((source) => source.id),
  ].sort();
  const recoveredStructureContent = sha256(
    `["p04-recovered-table-structure-content-v1","p04-table-recovery-rule-v1",${JSON.stringify(gridSourceId)},[2,2],null,null,null,[],[[0,0,"column_header"],[0,1,"column_header"]],${canonicalIds(recoverySourceIds)}]`,
  );
  assert.equal(
    recoveredStructureContent,
    "56d1624e9a37d4a87704454fd57eb65175b5ce25dc51d3fe16e294d514b23ac0",
  );
  assert.equal(
    sha256(
      `["p04-recovered-table-structure-evidence-id-v1",${JSON.stringify(sourceSha256)},1,${JSON.stringify(tableReference)},2,2,${canonicalIds(recoverySourceIds)},${JSON.stringify(recoveredStructureContent)}]`,
    ),
    "c2e87ce7d625c622be6802f3fbc0ad9d8a3a344620451372c91162a93432720f",
  );

  const emittedHeaderEvidence = [
    {
      column: 0,
      target: emittedCells[0]!,
      header: backendWordSets[0],
      body: backendWordSets[1],
      content: "b72f2602f9f84121ed10bc27b19ffe39a9b3b43c82143157844f1229fbc584f4",
      id: "fbeb2a6ae6927cc246776491c02231c97d3688cee4c4a6dc5e81bca0b527153f",
    },
    {
      column: 1,
      target: emittedCells[1]!,
      header: backendWordSets[2],
      body: backendWordSets[3],
      content: "cf7579a1f61a0131069d3d31203d88dea36f2e10137c0d84af5a8dddb5d42dfc",
      id: "6739a414e98536aa485f5b50c19ee3d8294e03d5c0e1841757aa53e4205425d6",
    },
  ];
  for (const evidence of emittedHeaderEvidence) {
    const targetBoxJson = canonicalIntegerBBox(evidence.target.box);
    const sourceIds = [gridSourceId, evidence.header.id, evidence.body.id].sort();
    const content = sha256(
      `["p04-recovered-header-content-v1",0,${evidence.column},${JSON.stringify(gridSourceId)},${JSON.stringify(evidence.header.content)},${JSON.stringify(evidence.body.content)},${targetBoxJson},[true,false]]`,
    );
    assert.equal(content, evidence.content);
    assert.equal(
      sha256(
        `["p04-recovered-header-evidence-id-v1",${JSON.stringify(sourceSha256)},1,${JSON.stringify(tableReference)},2,2,0,${evidence.column},${canonicalIds(sourceIds)},${targetBoxJson},${JSON.stringify(content)}]`,
      ),
      evidence.id,
    );
  }

  const emittedSlotIds = [
    "cd3b311c1a3c11e40edffe2f1360f574507eb01562547ac3027e5b51c0089b8f",
    "b360b70f2865208eec97d1fcddf78cd35e6d1dee7841244ec708337058a6e763",
    "43e3b2099f0abeca6ef8c24d1cd76aab26146555d3e210b94b5484a8fa61dc0b",
    "0e19d84e19b13783a59dac65a6d2ac7b7d44cd87afcaf7218d3de1b27bdee884",
  ];
  for (let index = 0; index < emittedSlotIds.length; index += 1) {
    assert.equal(
      sha256(
        `["p04-slot-id-v1",${JSON.stringify(sourceSha256)},1,${JSON.stringify(tableId)},${JSON.stringify(candidateId)},${Math.floor(index / 2)},${index % 2}]`,
      ),
      emittedSlotIds[index],
    );
  }

  assert.notEqual(
    sha256(
      `["p04-cell-id-v1",[${JSON.stringify(sourceSha256)},1,"docling","#/texts/tampered",${canonicalIntegerBBox(emittedCells[0]!.box)},0,0,1,1]]`,
    ),
    emittedCells[0]!.cellId,
  );
});

test("top-level opaque-group custody stays lossless and non-authoritative in every frontend table surface", () => {
  const canonicalJson = (value: unknown): string => {
    if (value === null || typeof value === "boolean" || typeof value === "string") {
      return JSON.stringify(value);
    }
    if (typeof value === "number") {
      assert.equal(Number.isSafeInteger(value), true);
      return JSON.stringify(value);
    }
    if (Array.isArray(value)) {
      return `[${value.map((entry) => canonicalJson(entry)).join(",")}]`;
    }
    assert.equal(typeof value, "object");
    const record = value as Record<string, unknown>;
    return `{${Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(record[key])}`)
      .join(",")}}`;
  };

  const groupRawRef = "#/groups/987654321";
  const counterpartRawRef = "#/tables/123456789";
  const groupElementId = `el-${sha256(groupRawRef).slice(0, 20)}`;
  const counterpartElementId = `el-${sha256(counterpartRawRef).slice(0, 20)}`;
  const relationshipField = "children";
  const relationshipType = "contains";
  const relationshipId = `rel-${sha256(
    canonicalJson([
      relationshipType,
      groupElementId,
      counterpartElementId,
      relationshipField,
    ]),
  ).slice(0, 20)}`;
  const memberContentDigest = sha256("custody-only-member-content");
  const counterpartContentDigest = sha256("custody-only-counterpart-content");
  const recordWithoutId = {
    record_order: 0,
    page_index: 1,
    edge_kind: "group_membership",
    owner_order: 0,
    owner_element_id: groupElementId,
    owner_raw_ref: groupRawRef,
    raw_slot_index: 0,
    raw_target_slot_index: null,
    member_element_id: counterpartElementId,
    member_raw_ref: counterpartRawRef,
    member_content_sha256: memberContentDigest,
    group_element_id: groupElementId,
    group_raw_ref: groupRawRef,
    group_type: "group",
    counterpart_element_id: counterpartElementId,
    counterpart_raw_ref: counterpartRawRef,
    counterpart_content_sha256: counterpartContentDigest,
    relationship_id: relationshipId,
    relationship_type: relationshipType,
    relationship_field: relationshipField,
    source_element_id: groupElementId,
    target_element_id: counterpartElementId,
    source_raw_ref: groupRawRef,
    target_raw_ref: counterpartRawRef,
  };
  const custodyRecord = {
    record_id: `custody-${sha256(
      canonicalJson({
        record: recordWithoutId,
        source_sha256: CONTEXT.sourceSha256,
      }),
    )}`,
    ...recordWithoutId,
  };
  const custody = {
    policy_id: "p04-opaque-raw-group-custody-v1",
    schema_version: "1.0",
    authority: "diagnostic_only",
    source_sha256: CONTEXT.sourceSha256,
    record_count: 1,
    records_sha256: sha256(canonicalJson([custodyRecord])),
    records: [custodyRecord],
  };

  const table = validTable("Visible custody-independent value");
  const canonicalBlock = {
    id: "canonical-table-block",
    page_id: "canonical-table-page",
    primary_element_id: table.id,
    primary_element_type: "table",
    scope: "body" as const,
    markdown: table.md,
    text: table.rows.map((row) => row.join("\t")).join("\n"),
    contributing_element_ids: [table.id],
    relationship_ids: [] as string[],
    excluded_contributions: [],
  };
  const canonicalBody = {
    block_ids: [canonicalBlock.id],
    markdown: `${canonicalBlock.markdown}\n`,
    text: `${canonicalBlock.text}\n`,
  };
  const canonicalEmpty = { block_ids: [] as string[], markdown: "", text: "" };
  const canonicalPresentation: CanonicalPresentation = {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [
      {
        page_id: "canonical-table-page",
        page_index: 1,
        page_number: 1,
        page_label: "1",
        blocks: [canonicalBlock],
        full: structuredClone(canonicalBody),
        body: structuredClone(canonicalBody),
        header: structuredClone(canonicalEmpty),
        footer: structuredClone(canonicalEmpty),
      },
    ],
    full: structuredClone(canonicalBody),
    body: structuredClone(canonicalBody),
    header: structuredClone(canonicalEmpty),
    footer: structuredClone(canonicalEmpty),
  };
  const predecessor = sampleResult({
    document: {
      filename: "custody-table.pdf",
      mime_type: "application/pdf",
      sha256: CONTEXT.sourceSha256,
      page_count: 1,
      image_count: 0,
    },
    pages: [
      samplePage({
        page_index: 1,
        page_number: 1,
        page_label: "1",
        page_width: CONTEXT.pageWidth,
        page_height: CONTEXT.pageHeight,
        unit: "pt",
        items: [table],
      }),
    ],
    canonical_presentation: canonicalPresentation,
  });
  const withCustody = {
    ...structuredClone(predecessor),
    canonical_source_custody: custody,
  } as ParseResult;

  const rawJson = serializeDocumentJson(withCustody, false);
  const rawRoundTrip = JSON.parse(rawJson) as Record<string, unknown>;
  assert.deepEqual(rawRoundTrip.canonical_source_custody, custody);
  assert.equal(rawRoundTrip.pages instanceof Array, true);
  assert.equal(
    (rawRoundTrip.pages as Array<Record<string, unknown>>)[0]?.items instanceof Array,
    true,
  );

  const normalized = normalizeDocumentJson(withCustody);
  assert.equal(
    normalized.metadata.additional_top_level_fields.canonical_source_custody,
    custody,
    "normalization must retain the exact additive top-level value by identity",
  );
  assert.deepEqual(
    normalized.metadata.additional_top_level_fields.canonical_source_custody,
    custody,
  );
  assert.equal(normalized.canonical_presentation, withCustody.canonical_presentation);
  assert.equal(
    Object.prototype.hasOwnProperty.call(normalized, "canonical_source_custody"),
    false,
  );

  const renderTableProjection = (result: ParseResult): string => {
    const page = result.pages[0];
    const item = page?.items[0];
    assert.ok(page);
    assert.ok(item);
    const semantics = readTableSemantics(item, {
      sourceSha256: result.document.sha256,
      pageIndex: page.page_index,
      pageWidth: page.page_width,
      pageHeight: page.page_height,
      unit: "pt",
    });
    assert.ok(semantics);
    const renderCell = (cell: (typeof semantics.cells)[number]) =>
      createElement(
        cell.columnHeader || cell.rowHeader ? "th" : "td",
        {
          colSpan: cell.colSpan,
          "data-cell-id": cell.id,
          "data-source": cell.source,
          key: cell.id,
          rowSpan: cell.rowSpan,
          scope: cell.columnHeader ? "col" : cell.rowHeader ? "row" : undefined,
          style: { whiteSpace: "pre-wrap" },
        },
        cell.text,
      );
    const renderRows = (rows: typeof semantics.rows) =>
      rows.map((row) =>
        createElement(
          "tr",
          { key: `${semantics.tableId}-row-${row.row}` },
          ...row.cells.map(renderCell),
        ),
      );
    const headerRows = semantics.rows.slice(0, semantics.headerRowCount);
    const bodyRows = semantics.rows.slice(semantics.headerRowCount);
    return renderToStaticMarkup(
      createElement(
        "div",
        {
          className: "parsed-table-wrap",
          "data-table-id": semantics.tableId,
          "data-table-policy": semantics.policyId,
        },
        createElement(
          "table",
          { className: "parsed-table" },
          headerRows.length
            ? createElement("thead", null, ...renderRows(headerRows))
            : null,
          bodyRows.length
            ? createElement("tbody", null, ...renderRows(bodyRows))
            : null,
        ),
      ),
    );
  };
  const authoritySurfaces = (result: ParseResult) => {
    const document = normalizeDocumentJson(result);
    const page = result.pages[0];
    assert.ok(page);
    return {
      canonical: JSON.stringify(document.canonical_presentation),
      documentMarkdown: serializeDocumentMarkdown(result),
      pageMarkdown: serializePageMarkdown(page, result),
      bodyMarkdown: serializePageMarkdown(page, result, "body"),
      normalizedMarkdown: document.markdown_full,
      normalizedPageMarkdown: document.markdown.pages[0]?.markdown,
      normalizedText: document.text_full,
      normalizedPageText: document.text.pages[0]?.text,
      tableProjection: renderTableProjection(result),
    };
  };

  const predecessorSurfaces = authoritySurfaces(predecessor);
  const custodySurfaces = authoritySurfaces(withCustody);
  assert.deepEqual(custodySurfaces, predecessorSurfaces);
  assert.equal(custodySurfaces.canonical, JSON.stringify(canonicalPresentation));
  const custodyOnlyValues = [
    groupRawRef,
    counterpartRawRef,
    memberContentDigest,
    counterpartContentDigest,
    custody.records_sha256,
    custodyRecord.record_id,
    relationshipId,
  ];
  for (const renderedOrCopyValue of Object.values(custodySurfaces)) {
    for (const custodyOnlyValue of custodyOnlyValues) {
      assert.doesNotMatch(renderedOrCopyValue ?? "", new RegExp(custodyOnlyValue, "u"));
    }
  }

  // Backend schema validation owns custody well-formedness. The frontend keeps
  // even malformed additive data representable in JSON, but never promotes it
  // into canonical, Markdown, text, copy, or table-render authority.
  const forgedAuthorityText = "CUSTODY_FORGED_RENDER_AUTHORITY";
  const malformedCustody = {
    ...structuredClone(custody),
    authority: "render_authority",
    records: [
      {
        ...structuredClone(custodyRecord),
        source_raw_ref: forgedAuthorityText,
        canonical_markdown: forgedAuthorityText,
        rows: [[forgedAuthorityText]],
      },
    ],
  };
  const withMalformedCustody = {
    ...structuredClone(predecessor),
    canonical_source_custody: malformedCustody,
  } as ParseResult;
  const malformedNormalized = normalizeDocumentJson(withMalformedCustody);
  assert.equal(
    malformedNormalized.metadata.additional_top_level_fields
      .canonical_source_custody,
    malformedCustody,
  );
  assert.deepEqual(authoritySurfaces(withMalformedCustody), predecessorSurfaces);
  assert.equal(
    JSON.stringify(authoritySurfaces(withMalformedCustody)).includes(
      forgedAuthorityText,
    ),
    false,
  );
});
