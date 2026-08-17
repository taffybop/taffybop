import { createElement, type ReactNode } from "react";

import { pythonStrip } from "./canonical-presentation.ts";
import type {
  CanonicalBlock,
  DiagramNode,
  DocumentContentItem,
  PageResult,
  VisualBoundingBox,
  VisualConfidenceDimensions,
  VisualLabelRole,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

const ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const CONCERN_CODE = /^[a-z][a-z0-9_]{2,95}$/u;
const MAX_SIDE_CAR_BYTES = 4 * 1024 * 1024;
const MAX_SIDE_CAR_VALUES = 65_536;
const MAX_SIDE_CAR_DEPTH = 32;
const MAX_REFERENCES = 64;
const MAX_EVIDENCE = 2_048;
const MAX_LABELS = 512;
const MAX_NODES = 512;
const MAX_CONNECTORS = 1_024;
const MAX_TEXT_BYTES = 1_024;
const MAX_LABEL_CODEPOINTS = 1_024;
const MAX_LABEL_BYTES = 4_096;
const MAX_MARKDOWN_BYTES = 262_144;
const CONTROL_TEXT = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u2028-\u202e\u2066-\u2069]/u;
const CONFIDENCE_KEYS = [
  "geometry",
  "calibration",
  "category",
  "series",
  "value",
  "direction",
] as const;
const LABEL_ROLES = new Set<VisualLabelRole>([
  "title",
  "caption",
  "axis_title",
  "tick",
  "category",
  "unit",
  "legend",
  "node",
  "node_detail",
  "connector",
  "other",
]);
const EVIDENCE_KINDS = new Set([
  "region",
  "label",
  "axis",
  "tick",
  "legend",
  "swatch",
  "panel",
  "mark",
  "path",
  "point",
  "baseline",
  "node",
  "connector",
  "source_object",
  "ocr_token",
]);
const INPUT_KINDS = new Set(["pdf", "image", "unknown"]);
const EXTRACTION_METHODS = new Set([
  "layout",
  "ocr",
  "vector",
  "raster",
  "explicit_text",
]);
const SPACES = new Set(["page", "chart_local", "raster_pixel"]);
const SHAPES = new Set<DiagramNode["shape"]>([
  "rectangle",
  "rounded_rectangle",
  "ellipse",
  "diamond",
]);

class InvalidDiagramSemantics extends Error {}

function invalid(path: string, message: string): never {
  throw new InvalidDiagramSemantics(`${path} ${message}`);
}

function isRecord(value: unknown): value is JsonRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function recordAt(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) invalid(path, "must be a plain object");
  return value;
}

function exactKeys(
  record: JsonRecord,
  required: readonly string[],
  path: string,
  optional: readonly string[] = [],
): void {
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(record, key)) {
      invalid(path, `is missing ${JSON.stringify(key)}`);
    }
  }
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) {
      invalid(path, `contains unsupported field ${JSON.stringify(key)}`);
    }
  }
}

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function boundedText(
  value: unknown,
  path: string,
  maximum = MAX_TEXT_BYTES,
): string {
  if (
    typeof value !== "string" ||
    pythonStrip(value).length === 0 ||
    utf8Length(value) > maximum ||
    CONTROL_TEXT.test(value)
  ) {
    invalid(path, "must be bounded non-whitespace text without control characters");
  }
  return value;
}

function isWellFormedUnicode(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const trailing = value.charCodeAt(index + 1);
      if (!(trailing >= 0xdc00 && trailing <= 0xdfff)) return false;
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function boundedLabelText(value: unknown, path: string): string {
  if (
    typeof value !== "string" ||
    pythonStrip(value).length === 0 ||
    !isWellFormedUnicode(value) ||
    Array.from(value).length > MAX_LABEL_CODEPOINTS ||
    utf8Length(value) > MAX_LABEL_BYTES ||
    CONTROL_TEXT.test(value)
  ) {
    invalid(path, "must be bounded, well-formed label text without control characters");
  }
  return value;
}

function identifier(value: unknown, path: string): string {
  if (typeof value !== "string" || !ID.test(value)) {
    invalid(path, "must be a bounded identifier");
  }
  return value;
}

function finiteNumber(value: unknown, path: string, minimum?: number): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    (minimum !== undefined && value < minimum)
  ) {
    invalid(path, "must be a finite number in range");
  }
  return value;
}

function integer(value: unknown, path: string, minimum: number, maximum: number): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < minimum ||
    (value as number) > maximum
  ) {
    invalid(path, `must be an integer from ${minimum} through ${maximum}`);
  }
  return value as number;
}

function arrayAt(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): unknown[] {
  if (!Array.isArray(value) || value.length < minimum || value.length > maximum) {
    invalid(path, `must contain ${minimum} through ${maximum} entries`);
  }
  return value;
}

function stringIds(
  value: unknown,
  path: string,
  minimum = 0,
  maximum = MAX_REFERENCES,
): string[] {
  const values = arrayAt(value, path, minimum, maximum).map((entry, index) =>
    identifier(entry, `${path}[${index}]`),
  );
  if (new Set(values).size !== values.length) {
    invalid(path, "must not repeat identifiers");
  }
  return values;
}

function compareUnicode(left: string, right: string): number {
  const leftPoints = Array.from(left, (value) => value.codePointAt(0)!);
  const rightPoints = Array.from(right, (value) => value.codePointAt(0)!);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    if (leftPoints[index] !== rightPoints[index]) {
      return leftPoints[index]! - rightPoints[index]!;
    }
  }
  return leftPoints.length - rightPoints.length;
}

function sourceReferences(value: unknown, path: string): string[] {
  const values = arrayAt(value, path, 0, MAX_REFERENCES).map((entry, index) => {
    if (
      typeof entry !== "string" ||
      entry.length === 0 ||
      !isWellFormedUnicode(entry)
    ) {
      invalid(`${path}[${index}]`, "must be a nonempty source identifier");
    }
    return entry;
  });
  const sorted = [...values].sort(compareUnicode);
  if (
    new Set(values).size !== values.length ||
    values.some((entry, index) => entry !== sorted[index])
  ) {
    invalid(path, "must contain unique source identifiers in source order");
  }
  return values;
}

function nullableRecord(value: unknown, path: string): JsonRecord | null {
  return value === null ? null : recordAt(value, path);
}

function sidecarFitsResourceBounds(value: unknown): boolean {
  const pending: Array<{ value: unknown; depth: number }> = [
    { value, depth: 0 },
  ];
  const seen = new WeakSet<object>();
  let values = 0;
  let bytes = 0;
  while (pending.length) {
    const next = pending.pop();
    if (!next || next.depth > MAX_SIDE_CAR_DEPTH) return false;
    values += 1;
    if (values > MAX_SIDE_CAR_VALUES) return false;
    const current = next.value;
    if (typeof current === "string") {
      bytes += utf8Length(current);
    } else if (typeof current === "number") {
      if (!Number.isFinite(current)) return false;
      bytes += 8;
    } else if (current !== null && typeof current === "object") {
      // Repeated object identity is harmless in an in-memory caller and a
      // cycle must not make bounded accounting loop forever. Public JSON has
      // neither identity sharing nor cycles, so count either object once.
      if (seen.has(current)) continue;
      seen.add(current);
      if (!Array.isArray(current) && !isRecord(current)) return false;
      for (const [key, child] of Object.entries(current)) {
        bytes += utf8Length(key);
        pending.push({ value: child, depth: next.depth + 1 });
      }
    } else {
      bytes += 4;
    }
    if (bytes > MAX_SIDE_CAR_BYTES) return false;
  }
  return true;
}

function boundingBox(value: unknown, path: string): VisualBoundingBox {
  const record = recordAt(value, path);
  exactKeys(record, ["x", "y", "width", "height", "unit"], path);
  const unit = record.unit;
  if (unit !== "pt" && unit !== "px") invalid(`${path}.unit`, "must be pt or px");
  return {
    x: finiteNumber(record.x, `${path}.x`, 0),
    y: finiteNumber(record.y, `${path}.y`, 0),
    width: finiteNumber(record.width, `${path}.width`, 0),
    height: finiteNumber(record.height, `${path}.height`, 0),
    unit,
  };
}

function sameBox(left: VisualBoundingBox, right: VisualBoundingBox): boolean {
  return (
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height &&
    left.unit === right.unit
  );
}

function containsBox(outer: VisualBoundingBox, inner: VisualBoundingBox): boolean {
  const epsilon = 1e-6;
  return (
    outer.unit === inner.unit &&
    inner.x >= outer.x - epsilon &&
    inner.y >= outer.y - epsilon &&
    inner.x + inner.width <= outer.x + outer.width + epsilon &&
    inner.y + inner.height <= outer.y + outer.height + epsilon
  );
}

function confidenceAt(value: unknown, path: string): VisualConfidenceDimensions {
  const record = recordAt(value, path);
  exactKeys(record, [], path, CONFIDENCE_KEYS);
  const output = {} as Record<(typeof CONFIDENCE_KEYS)[number], number | null>;
  for (const key of CONFIDENCE_KEYS) {
    const raw = record[key];
    if (raw === null || raw === undefined) {
      output[key] = null;
    } else {
      const score = finiteNumber(raw, `${path}.${key}`, 0);
      if (score > 1) invalid(`${path}.${key}`, "must not exceed one");
      output[key] = score;
    }
  }
  return output as VisualConfidenceDimensions;
}

interface ValidatedTransform {
  id: string;
  sourceSpace: string;
  targetSpace: string;
  matrix: [number, number, number, number, number, number];
  sourceTransformIds: string[];
}

function transformAt(value: unknown, path: string): ValidatedTransform {
  const record = recordAt(value, path);
  exactKeys(
    record,
    ["id", "source_space", "target_space", "matrix", "source_transform_ids"],
    path,
  );
  const sourceSpace = boundedText(record.source_space, `${path}.source_space`, 32);
  const targetSpace = boundedText(record.target_space, `${path}.target_space`, 32);
  if (!SPACES.has(sourceSpace) || !SPACES.has(targetSpace)) {
    invalid(path, "has an unsupported coordinate space");
  }
  const matrix = arrayAt(record.matrix, `${path}.matrix`, 6, 6).map(
    (entry, index) => finiteNumber(entry, `${path}.matrix[${index}]`),
  );
  const [a, b, c, d, e, f] = matrix;
  if (sourceSpace === targetSpace) {
    if (a !== 1 || b !== 0 || c !== 0 || d !== 1 || e !== 0 || f !== 0) {
      invalid(`${path}.matrix`, "must be identity for an unchanged space");
    }
  } else if (Math.abs(a! * d! - b! * c!) < 1e-12) {
    invalid(`${path}.matrix`, "must be invertible");
  }
  return {
    id: identifier(record.id, `${path}.id`),
    sourceSpace,
    targetSpace,
    matrix: matrix as [number, number, number, number, number, number],
    sourceTransformIds: stringIds(
      record.source_transform_ids,
      `${path}.source_transform_ids`,
      0,
      8,
    ),
  };
}

interface ValidatedEvidence {
  id: string;
  kind: string;
  pageBox: VisualBoundingBox | null;
  chartBox: VisualBoundingBox | null;
  rasterBox: VisualBoundingBox | null;
  transformIds: string[];
  extractionMethod: string;
  sourceObjectIds: string[];
  sourceTokenIds: string[];
}

function evidenceAt(
  value: unknown,
  ownerId: string,
  pageIndex: number,
  path: string,
): ValidatedEvidence {
  const record = recordAt(value, path);
  exactKeys(
    record,
    [
      "id",
      "kind",
      "transform_ids",
      "provenance",
    ],
    path,
    ["page_bbox", "chart_local_bbox", "raster_pixel_bbox"],
  );
  const kind = boundedText(record.kind, `${path}.kind`, 32);
  if (!EVIDENCE_KINDS.has(kind)) invalid(`${path}.kind`, "is unsupported");
  const pageRecord = record.page_bbox === undefined
    ? null
    : nullableRecord(record.page_bbox, `${path}.page_bbox`);
  const chartRecord = record.chart_local_bbox === undefined
    ? null
    : nullableRecord(record.chart_local_bbox, `${path}.chart_local_bbox`);
  const rasterRecord = record.raster_pixel_bbox === undefined
    ? null
    : nullableRecord(record.raster_pixel_bbox, `${path}.raster_pixel_bbox`);
  const pageBox = pageRecord ? boundingBox(pageRecord, `${path}.page_bbox`) : null;
  const chartBox = chartRecord
    ? boundingBox(chartRecord, `${path}.chart_local_bbox`)
    : null;
  const rasterBox = rasterRecord
    ? boundingBox(rasterRecord, `${path}.raster_pixel_bbox`)
    : null;
  const transformIds = stringIds(record.transform_ids, `${path}.transform_ids`, 0, 8);
  const provenance = recordAt(record.provenance, `${path}.provenance`);
  exactKeys(
    provenance,
    [
      "public_item_id",
      "page_index",
      "input_kind",
      "source_object_ids",
      "source_token_ids",
      "extraction_method",
    ],
    `${path}.provenance`,
  );
  if (provenance.public_item_id !== ownerId || provenance.page_index !== pageIndex) {
    invalid(`${path}.provenance`, "does not identify the exact public owner and page");
  }
  const inputKind = boundedText(
    provenance.input_kind,
    `${path}.provenance.input_kind`,
    16,
  );
  const extractionMethod = boundedText(
    provenance.extraction_method,
    `${path}.provenance.extraction_method`,
    32,
  );
  if (!INPUT_KINDS.has(inputKind) || !EXTRACTION_METHODS.has(extractionMethod)) {
    invalid(`${path}.provenance`, "has an unsupported source method");
  }
  const sourceObjectIds = sourceReferences(
    provenance.source_object_ids,
    `${path}.provenance.source_object_ids`,
  );
  const sourceTokenIds = sourceReferences(
    provenance.source_token_ids,
    `${path}.provenance.source_token_ids`,
  );
  if (!pageBox && !chartBox && !rasterBox && !sourceObjectIds.length && !sourceTokenIds.length) {
    invalid(path, "has no source grounding");
  }
  return {
    id: identifier(record.id, `${path}.id`),
    kind,
    pageBox,
    chartBox,
    rasterBox,
    transformIds,
    extractionMethod,
    sourceObjectIds,
    sourceTokenIds,
  };
}

function boxesClose(
  left: VisualBoundingBox,
  right: VisualBoundingBox,
): boolean {
  if (left.unit !== right.unit) return false;
  return (["x", "y", "width", "height"] as const).every((key) => {
    const absoluteDifference = Math.abs(left[key] - right[key]);
    const tolerance = Math.max(
      1e-6,
      1e-9 * Math.max(Math.abs(left[key]), Math.abs(right[key])),
    );
    return absoluteDifference <= tolerance;
  });
}

function transformedBox(
  box: VisualBoundingBox,
  matrix: ValidatedTransform["matrix"],
  unit: VisualBoundingBox["unit"],
): VisualBoundingBox {
  const [a, b, c, d, e, f] = matrix;
  const corners = [
    [box.x, box.y],
    [box.x + box.width, box.y],
    [box.x, box.y + box.height],
    [box.x + box.width, box.y + box.height],
  ] as const;
  const mapped = corners.map(([x, y]) => [
    a * x + c * y + e,
    b * x + d * y + f,
  ] as const);
  const xs = mapped.map(([x]) => x);
  const ys = mapped.map(([, y]) => y);
  return {
    x: Math.min(...xs),
    y: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
    unit,
  };
}

function requireRasterSourceObjectCustody(
  record: ValidatedEvidence,
  transformsById: ReadonlyMap<string, ValidatedTransform>,
  path: string,
): void {
  if (
    record.kind !== "source_object" ||
    !record.pageBox ||
    record.pageBox.width <= 0 ||
    record.pageBox.height <= 0 ||
    record.chartBox !== null ||
    !record.rasterBox ||
    record.rasterBox.unit !== "px" ||
    record.rasterBox.width <= 0 ||
    record.rasterBox.height <= 0 ||
    record.extractionMethod !== "raster" ||
    record.sourceObjectIds.length === 0 ||
    record.transformIds.length !== 1
  ) {
    invalid(path, "has incomplete raster source-object custody");
  }
  const transform = transformsById.get(record.transformIds[0]!);
  if (
    !transform ||
    transform.sourceSpace !== "raster_pixel" ||
    transform.targetSpace !== "page" ||
    transform.sourceTransformIds.length !== 0
  ) {
    invalid(path, "has an unsupported raster-to-page transform");
  }
  const [a, b, c, d] = transform.matrix;
  if (a <= 0 || b !== 0 || c !== 0 || d <= 0) {
    invalid(path, "has a non-axis-aligned raster-to-page transform");
  }
  if (
    !boxesClose(
      transformedBox(record.rasterBox, transform.matrix, record.pageBox.unit),
      record.pageBox,
    )
  ) {
    invalid(path, "has inconsistent page and raster geometry");
  }
}

interface ValidatedLabel {
  id: string;
  text: string;
  role: VisualLabelRole;
  pageBox: VisualBoundingBox | null;
  evidenceIds: string[];
  occurrenceIndex: number;
}

function labelAt(value: unknown, path: string): ValidatedLabel {
  const record = recordAt(value, path);
  exactKeys(
    record,
    [
      "id",
      "text",
      "role",
      "evidence_ids",
      "occurrence_index",
    ],
    path,
    ["page_bbox", "raster_pixel_bbox"],
  );
  const role = boundedText(record.role, `${path}.role`, 32) as VisualLabelRole;
  if (!LABEL_ROLES.has(role)) invalid(`${path}.role`, "is unsupported");
  const pageRecord = record.page_bbox === undefined
    ? null
    : nullableRecord(record.page_bbox, `${path}.page_bbox`);
  const rasterRecord = record.raster_pixel_bbox === undefined
    ? null
    : nullableRecord(record.raster_pixel_bbox, `${path}.raster_pixel_bbox`);
  if (rasterRecord) boundingBox(rasterRecord, `${path}.raster_pixel_bbox`);
  return {
    id: identifier(record.id, `${path}.id`),
    text: boundedLabelText(record.text, `${path}.text`),
    role,
    pageBox: pageRecord ? boundingBox(pageRecord, `${path}.page_bbox`) : null,
    evidenceIds: stringIds(record.evidence_ids, `${path}.evidence_ids`, 1),
    occurrenceIndex: integer(record.occurrence_index, `${path}.occurrence_index`, 0, MAX_LABELS),
  };
}

interface StagedNode {
  id: string;
  shape: DiagramNode["shape"];
  labelId: string | null;
  detailLabelIds: string[];
  pageBox: VisualBoundingBox;
  evidenceIds: string[];
  confidence: VisualConfidenceDimensions;
}

function nodeAt(value: unknown, path: string): StagedNode {
  const record = recordAt(value, path);
  exactKeys(
    record,
    ["id", "shape", "page_bbox", "evidence_ids", "confidence"],
    path,
    ["label_id", "detail_label_ids"],
  );
  const shape = boundedText(record.shape, `${path}.shape`, 32) as DiagramNode["shape"];
  if (!SHAPES.has(shape)) invalid(`${path}.shape`, "is unsupported");
  const labelId =
    record.label_id === undefined || record.label_id === null
      ? null
      : identifier(record.label_id, `${path}.label_id`);
  const detailLabelIds = Object.prototype.hasOwnProperty.call(
    record,
    "detail_label_ids",
  )
    ? stringIds(record.detail_label_ids, `${path}.detail_label_ids`)
    : [];
  if (labelId !== null && detailLabelIds.includes(labelId)) {
    invalid(path, "uses its main label as detail text");
  }
  const pageBox = boundingBox(record.page_bbox, `${path}.page_bbox`);
  if (pageBox.width <= 0 || pageBox.height <= 0) {
    invalid(`${path}.page_bbox`, "must have positive area");
  }
  const confidence = confidenceAt(record.confidence, `${path}.confidence`);
  if (confidence.geometry === null) invalid(`${path}.confidence.geometry`, "is required");
  return {
    id: identifier(record.id, `${path}.id`),
    shape,
    labelId,
    detailLabelIds,
    pageBox,
    evidenceIds: stringIds(record.evidence_ids, `${path}.evidence_ids`, 1),
    confidence,
  };
}

interface StagedConnector {
  id: string;
  sourceNodeId: string;
  targetNodeId: string;
  labelId: string | null;
  pathEvidenceId: string;
  endpointEvidenceIds: [string, string];
  directionEvidenceId: string;
  evidenceIds: string[];
  confidence: VisualConfidenceDimensions;
}

function connectorAt(value: unknown, path: string): StagedConnector {
  const record = recordAt(value, path);
  exactKeys(
    record,
    [
      "id",
      "source_node_id",
      "target_node_id",
      "directed",
      "path_evidence_id",
      "endpoint_evidence_ids",
      "direction_evidence_id",
      "evidence_ids",
      "confidence",
    ],
    path,
    ["label_id"],
  );
  if (record.directed !== true) invalid(`${path}.directed`, "must be true");
  const endpointEvidenceIds = stringIds(
    record.endpoint_evidence_ids,
    `${path}.endpoint_evidence_ids`,
    2,
    2,
  ) as [string, string];
  const confidence = confidenceAt(record.confidence, `${path}.confidence`);
  if (confidence.geometry === null || confidence.direction === null) {
    invalid(`${path}.confidence`, "requires geometry and direction scores");
  }
  return {
    id: identifier(record.id, `${path}.id`),
    sourceNodeId: identifier(record.source_node_id, `${path}.source_node_id`),
    targetNodeId: identifier(record.target_node_id, `${path}.target_node_id`),
    labelId:
      !Object.prototype.hasOwnProperty.call(record, "label_id") ||
      record.label_id === null
        ? null
        : identifier(record.label_id, `${path}.label_id`),
    pathEvidenceId: identifier(record.path_evidence_id, `${path}.path_evidence_id`),
    endpointEvidenceIds,
    directionEvidenceId: identifier(
      record.direction_evidence_id,
      `${path}.direction_evidence_id`,
    ),
    evidenceIds: stringIds(record.evidence_ids, `${path}.evidence_ids`, 1),
    confidence,
  };
}

export interface ValidatedDiagramLabel {
  id: string;
  text: string;
}

export interface ValidatedDiagramNode {
  id: string;
  shape: DiagramNode["shape"];
  label: ValidatedDiagramLabel;
  details: ValidatedDiagramLabel[];
  pageBox: VisualBoundingBox;
}

export interface ValidatedDiagramConnector {
  id: string;
  source: ValidatedDiagramNode;
  target: ValidatedDiagramNode;
  label: ValidatedDiagramLabel | null;
}

export interface DiagramNodeListEntry {
  kind: "node";
  node: ValidatedDiagramNode;
  connector: ValidatedDiagramConnector | null;
  children: DiagramListEntry[];
}

export interface DiagramReferenceListEntry {
  kind: "reference";
  referenceKind: "merge" | "loop";
  target: ValidatedDiagramNode;
  connector: ValidatedDiagramConnector;
}

export type DiagramListEntry = DiagramNodeListEntry | DiagramReferenceListEntry;

export interface ValidatedDiagramSemantics {
  owner: DocumentContentItem;
  caption: string;
  markdown: string;
  nodes: ValidatedDiagramNode[];
  connectors: ValidatedDiagramConnector[];
  forest: DiagramNodeListEntry[];
}

function uniqueById<T extends { id: string }>(values: T[], path: string): Map<string, T> {
  const output = new Map<string, T>();
  for (const value of values) {
    if (output.has(value.id)) invalid(path, `repeats identifier ${JSON.stringify(value.id)}`);
    output.set(value.id, value);
  }
  return output;
}

function requireEvidence(
  evidenceById: ReadonlyMap<string, ValidatedEvidence>,
  id: string,
  kind: string,
  path: string,
): ValidatedEvidence {
  const record = evidenceById.get(id);
  if (!record || record.kind !== kind) invalid(path, `must resolve ${kind} evidence`);
  return record;
}

function compareIdentifiers(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function compareNodeGeometry(
  left: ValidatedDiagramNode,
  right: ValidatedDiagramNode,
): number {
  return (
    left.pageBox.y - right.pageBox.y ||
    left.pageBox.x - right.pageBox.x ||
    left.pageBox.width - right.pageBox.width ||
    left.pageBox.height - right.pageBox.height ||
    compareIdentifiers(left.id, right.id)
  );
}

function compareConnectors(
  left: ValidatedDiagramConnector,
  right: ValidatedDiagramConnector,
): number {
  return compareNodeGeometry(left.target, right.target) || compareIdentifiers(left.id, right.id);
}

function buildForest(
  nodes: ValidatedDiagramNode[],
  connectors: ValidatedDiagramConnector[],
): DiagramNodeListEntry[] {
  const labelCounts = new Map<string, number>();
  for (const node of nodes) {
    const serializedLabel = escapeMarkdown(node.label.text);
    labelCounts.set(serializedLabel, (labelCounts.get(serializedLabel) ?? 0) + 1);
  }
  const incomingCount = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as ValidatedDiagramConnector[]]));
  for (const connector of connectors) {
    incomingCount.set(connector.target.id, (incomingCount.get(connector.target.id) ?? 0) + 1);
    outgoing.get(connector.source.id)!.push(connector);
  }
  for (const values of outgoing.values()) values.sort(compareConnectors);
  const roots = nodes
    .filter((node) => incomingCount.get(node.id) === 0)
    .sort(compareNodeGeometry);
  const seen = new Set<string>();
  const active = new Set<string>();

  const visit = (
    node: ValidatedDiagramNode,
    connector: ValidatedDiagramConnector | null,
  ): DiagramNodeListEntry => {
    seen.add(node.id);
    active.add(node.id);
    const children: DiagramListEntry[] = [];
    for (const edge of outgoing.get(node.id) ?? []) {
      if (active.has(edge.target.id)) {
        if (labelCounts.get(escapeMarkdown(edge.target.label.text)) !== 1) {
          invalid(
            `visual_structure.connectors.${edge.id}`,
            "has an ambiguous loop-reference target label",
          );
        }
        children.push({
          kind: "reference",
          referenceKind: "loop",
          target: edge.target,
          connector: edge,
        });
      } else if (seen.has(edge.target.id)) {
        if (labelCounts.get(escapeMarkdown(edge.target.label.text)) !== 1) {
          invalid(
            `visual_structure.connectors.${edge.id}`,
            "has an ambiguous merge-reference target label",
          );
        }
        children.push({
          kind: "reference",
          referenceKind: "merge",
          target: edge.target,
          connector: edge,
        });
      } else {
        children.push(visit(edge.target, edge));
      }
    }
    active.delete(node.id);
    return { kind: "node", node, connector, children };
  };

  const forest = roots.map((root) => visit(root, null));
  if (seen.size !== nodes.length) {
    invalid("visual_structure.connectors", "contains a rootless non-isolated cycle");
  }
  return forest;
}

// This is intentionally a closed serializer, not a Markdown parser. Keep it
// byte-identical to the backend diagram-list serializer.
function escapeMarkdown(value: string): string {
  const escaped = value
    .replaceAll("\\", "\\\\")
    .replaceAll("|", "\\|")
    .replaceAll("\r\n", "<br>")
    .replaceAll("\r", "<br>")
    .replaceAll("\n", "<br>");
  return pythonStrip(escaped);
}

function edgePrefix(connector: ValidatedDiagramConnector | null): string {
  return connector?.label ? `${escapeMarkdown(connector.label.text)}: ` : "";
}

function replayMarkdown(
  forest: readonly DiagramNodeListEntry[],
  caption: string,
): string {
  const lines: string[] = [];
  const append = (entry: DiagramListEntry, depth: number): void => {
    const indent = "  ".repeat(depth);
    if (entry.kind === "reference") {
      const phrase = entry.referenceKind === "loop" ? "Returns to" : "Continues at";
      lines.push(
        `${indent}- ${edgePrefix(entry.connector)}${phrase}: ${escapeMarkdown(entry.target.label.text)}`,
      );
      return;
    }
    lines.push(
      `${indent}- ${edgePrefix(entry.connector)}${escapeMarkdown(entry.node.label.text)}`,
    );
    for (const detail of entry.node.details) {
      lines.push(`${indent}  - ${escapeMarkdown(detail.text)}`);
    }
    for (const child of entry.children) append(child, depth + 1);
  };
  for (const root of forest) append(root, 0);
  const graph = lines.join("\n");
  return caption ? `${escapeMarkdown(caption)}\n\n${graph}` : graph;
}

function itemCaption(item: DocumentContentItem): string {
  const raw = item.caption;
  if (raw === undefined || raw === null) return "";
  if (
    typeof raw !== "string" ||
    !isWellFormedUnicode(raw) ||
    utf8Length(raw) > MAX_MARKDOWN_BYTES ||
    CONTROL_TEXT.test(raw)
  ) {
    invalid("owner.caption", "must be bounded text");
  }
  return pythonStrip(raw);
}

function decodeOwner(
  owner: DocumentContentItem,
  page: PageResult,
): ValidatedDiagramSemantics {
  if (
    owner.type !== "diagram" ||
    !ID.test(owner.id) ||
    (page.unit !== "pt" && page.unit !== "px") ||
    !Number.isSafeInteger(page.page_index) ||
    page.page_index < 1 ||
    !Number.isFinite(page.page_width) ||
    page.page_width <= 0 ||
    !Number.isFinite(page.page_height) ||
    page.page_height <= 0
  ) {
    invalid("owner", "is not an exact diagram owner on a supported coordinate page");
  }
  const raw = owner.visual_structure;
  const rawParseConcerns = owner.parse_concerns;
  if (rawParseConcerns !== undefined) {
    const parseConcerns = arrayAt(
      rawParseConcerns,
      "owner.parse_concerns",
      0,
      256,
    );
    if (
      parseConcerns.some(
        (value) =>
          typeof value !== "string" ||
          value.length === 0 ||
          utf8Length(value) > 256 ||
          CONTROL_TEXT.test(value),
      ) ||
      parseConcerns.includes("diagram_relationships_not_structured")
    ) {
      invalid("owner.parse_concerns", "contradicts authoritative diagram state");
    }
  }
  if (!sidecarFitsResourceBounds(raw)) invalid("visual_structure", "exceeds resource bounds");
  const structure = recordAt(raw, "visual_structure");
  exactKeys(
    structure,
    [
      "schema_version",
      "region",
      "transforms",
      "labels",
      "axes",
      "legends",
      "panels",
      "series",
      "points",
      "nodes",
      "connectors",
      "evidence",
      "confidence",
      "concerns",
      "fallback",
      "serialization",
    ],
    "visual_structure",
    ["vector_inventory"],
  );
  if (structure.schema_version !== "1.0") invalid("visual_structure.schema_version", "is unsupported");
  for (const key of ["axes", "legends", "panels", "series", "points"] as const) {
    if (arrayAt(structure[key], `visual_structure.${key}`, 0, 0).length) {
      invalid(`visual_structure.${key}`, "must be empty for a diagram");
    }
  }
  if (
    structure.vector_inventory !== undefined &&
    structure.vector_inventory !== null
  ) {
    invalid("visual_structure.vector_inventory", "must be null for a diagram");
  }
  confidenceAt(structure.confidence, "visual_structure.confidence");

  const transforms = arrayAt(structure.transforms, "visual_structure.transforms", 0, 16).map(
    (value, index) => transformAt(value, `visual_structure.transforms[${index}]`),
  );
  const transformsById = uniqueById(transforms, "visual_structure.transforms");
  for (const transform of transforms) {
    if (
      transform.sourceTransformIds.includes(transform.id) ||
      transform.sourceTransformIds.some((id) => !transformsById.has(id))
    ) {
      invalid(`visual_structure.transforms.${transform.id}`, "has an unknown or self reference");
    }
  }

  const evidence = arrayAt(
    structure.evidence,
    "visual_structure.evidence",
    1,
    MAX_EVIDENCE,
  ).map((value, index) =>
    evidenceAt(value, owner.id, page.page_index, `visual_structure.evidence[${index}]`),
  );
  const evidenceById = uniqueById(evidence, "visual_structure.evidence");
  for (const record of evidence) {
    if (record.transformIds.some((id) => !transformsById.has(id))) {
      invalid(`visual_structure.evidence.${record.id}`, "uses an unknown transform");
    }
  }

  const region = recordAt(structure.region, "visual_structure.region");
  exactKeys(region, ["id", "kind", "page_bbox", "evidence_ids"], "visual_structure.region");
  identifier(region.id, "visual_structure.region.id");
  if (region.kind !== "diagram") invalid("visual_structure.region.kind", "must be diagram");
  const regionBox = boundingBox(region.page_bbox, "visual_structure.region.page_bbox");
  if (
    regionBox.unit !== page.unit ||
    regionBox.x + regionBox.width > page.page_width + 1e-6 ||
    regionBox.y + regionBox.height > page.page_height + 1e-6
  ) {
    invalid("visual_structure.region.page_bbox", "leaves its public page");
  }
  const ownerBoxRecord = recordAt(owner.bbox, "owner.bbox");
  exactKeys(
    ownerBoxRecord,
    ["x", "y", "width", "height", "unit"],
    "owner.bbox",
    ["w", "h"],
  );
  const ownerBox = boundingBox(
    {
      x: ownerBoxRecord.x,
      y: ownerBoxRecord.y,
      width: ownerBoxRecord.width,
      height: ownerBoxRecord.height,
      unit: ownerBoxRecord.unit,
    },
    "owner.bbox",
  );
  if (
    !sameBox(ownerBox, regionBox) ||
    (ownerBoxRecord.w !== undefined && ownerBoxRecord.w !== ownerBox.width) ||
    (ownerBoxRecord.h !== undefined && ownerBoxRecord.h !== ownerBox.height)
  ) {
    invalid("owner.bbox", "does not exactly reproduce the visual region");
  }
  let exactRegionEvidence = 0;
  for (const id of stringIds(region.evidence_ids, "visual_structure.region.evidence_ids", 1)) {
    const record = evidenceById.get(id);
    if (!record) {
      invalid("visual_structure.region.evidence_ids", "uses unknown evidence");
    }
    if (!record.pageBox || !sameBox(record.pageBox, regionBox)) {
      invalid("visual_structure.region.evidence_ids", "does not reproduce region geometry");
    }
    if (record.kind === "region") {
      exactRegionEvidence += 1;
      continue;
    }
    if (record.kind !== "source_object") {
      invalid(
        "visual_structure.region.evidence_ids",
        "contains evidence other than a region or raster source object",
      );
    }
    requireRasterSourceObjectCustody(
      record,
      transformsById,
      `visual_structure.evidence.${record.id}`,
    );
    if (
      record.rasterBox!.x !== 0 ||
      record.rasterBox!.y !== 0 ||
      !Number.isSafeInteger(record.rasterBox!.width) ||
      !Number.isSafeInteger(record.rasterBox!.height)
    ) {
      invalid(
        `visual_structure.evidence.${record.id}.raster_pixel_bbox`,
        "must identify the complete raster owner",
      );
    }
  }
  if (exactRegionEvidence === 0) {
    invalid("visual_structure.region.evidence_ids", "lacks exact region evidence");
  }

  const labels = arrayAt(structure.labels, "visual_structure.labels", 0, MAX_LABELS).map(
    (value, index) => labelAt(value, `visual_structure.labels[${index}]`),
  );
  const labelsById = uniqueById(labels, "visual_structure.labels");
  labels.forEach((label, index) => {
    if (label.occurrenceIndex !== index) invalid("visual_structure.labels", "has noncontiguous occurrence order");
    let exactTextEvidence = 0;
    for (const id of label.evidenceIds) {
      const record = evidenceById.get(id);
      if (!record) {
        invalid(`visual_structure.labels.${label.id}`, "uses unknown evidence");
      }
      if (record.kind === "label" || record.kind === "ocr_token") {
        exactTextEvidence += 1;
        continue;
      }
      if (label.role === "node_detail" && record.kind === "source_object") {
        requireRasterSourceObjectCustody(
          record,
          transformsById,
          `visual_structure.evidence.${record.id}`,
        );
        continue;
      }
      if (record.kind !== "label" && record.kind !== "ocr_token") {
        invalid(`visual_structure.labels.${label.id}`, "has non-label evidence");
      }
    }
    if (exactTextEvidence === 0) {
      invalid(`visual_structure.labels.${label.id}`, "lacks label or OCR text evidence");
    }
  });

  const stagedNodes = arrayAt(structure.nodes, "visual_structure.nodes", 1, MAX_NODES).map(
    (value, index) => nodeAt(value, `visual_structure.nodes[${index}]`),
  );
  uniqueById(stagedNodes, "visual_structure.nodes");
  const nodeEvidenceClaims = new Map<string, number>();
  for (const node of stagedNodes) {
    for (const evidenceId of node.evidenceIds) {
      nodeEvidenceClaims.set(
        evidenceId,
        (nodeEvidenceClaims.get(evidenceId) ?? 0) + 1,
      );
    }
  }
  const semanticIds = [region.id, ...labels.map((label) => label.id), ...stagedNodes.map((node) => node.id)];
  if (new Set(semanticIds).size !== semanticIds.length) {
    invalid("visual_structure", "reuses semantic identifiers");
  }
  const ownedDetailLabels = new Set<string>();
  const ownedMainLabels = new Set<string>();
  const ownedDetailSourceEvidence = new Set<string>();
  const nodes: ValidatedDiagramNode[] = stagedNodes.map((node, index) => {
    if (!containsBox(regionBox, node.pageBox)) {
      invalid(`visual_structure.nodes.${node.id}`, "leaves the diagram region");
    }
    const geometryRecords = node.evidenceIds
      .map((id) => evidenceById.get(id))
      .filter((entry): entry is ValidatedEvidence => entry?.kind === "node");
    if (!geometryRecords.some((entry) => entry.pageBox && sameBox(entry.pageBox, node.pageBox))) {
      invalid(`visual_structure.nodes.${node.id}`, "lacks matching node geometry evidence");
    }
    for (const evidenceId of node.evidenceIds) {
      if (!evidenceById.has(evidenceId)) {
        invalid(`visual_structure.nodes.${node.id}`, "uses unknown evidence");
      }
    }
    let label: ValidatedLabel | null = null;
    if (node.labelId !== null) {
      label = labelsById.get(node.labelId) ?? null;
      if (
        !label ||
        label.role !== "node" ||
        !label.pageBox ||
        !containsBox(node.pageBox, label.pageBox) ||
        label.evidenceIds.some((id) => !node.evidenceIds.includes(id)) ||
        ownedMainLabels.has(label.id)
      ) {
        invalid(`visual_structure.nodes.${node.id}.label_id`, "is not unique grounded node text");
      }
      ownedMainLabels.add(label.id);
    }
    const details = node.detailLabelIds.map((id) => {
      const detail = labelsById.get(id);
      if (
        !detail ||
        detail.role !== "node_detail" ||
        !detail.pageBox ||
        !containsBox(node.pageBox, detail.pageBox) ||
        detail.evidenceIds.some((evidenceId) => !node.evidenceIds.includes(evidenceId)) ||
        ownedDetailLabels.has(detail.id)
      ) {
        invalid(`visual_structure.nodes.${node.id}.detail_label_ids`, "has invalid detail ownership");
      }
      for (const evidenceId of detail.evidenceIds) {
        const record = evidenceById.get(evidenceId)!;
        if (record.kind !== "source_object") continue;
        if (
          !record.pageBox ||
          !containsBox(node.pageBox, record.pageBox) ||
          nodeEvidenceClaims.get(evidenceId) !== 1 ||
          ownedDetailSourceEvidence.has(evidenceId)
        ) {
          invalid(
            `visual_structure.nodes.${node.id}.detail_label_ids`,
            "has reused or out-of-bounds raster detail evidence",
          );
        }
        ownedDetailSourceEvidence.add(evidenceId);
      }
      ownedDetailLabels.add(detail.id);
      return { id: detail.id, text: detail.text };
    });
    return {
      id: node.id,
      shape: node.shape,
      label: label
        ? { id: label.id, text: label.text }
        : { id: `synthetic:${node.id}`, text: `Node ${index + 1}` },
      details,
      pageBox: node.pageBox,
    };
  });
  if (
    labels.some(
      (label) =>
        (label.role === "node_detail" && !ownedDetailLabels.has(label.id)) ||
        (label.role === "connector" && label.pageBox === null),
    )
  ) {
    invalid("visual_structure.labels", "has unowned detail or ungrounded connector text");
  }
  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  const stagedConnectors = arrayAt(
    structure.connectors,
    "visual_structure.connectors",
    1,
    MAX_CONNECTORS,
  ).map((value, index) => connectorAt(value, `visual_structure.connectors[${index}]`));
  uniqueById(stagedConnectors, "visual_structure.connectors");
  const allSemanticIds = [...semanticIds, ...stagedConnectors.map((edge) => edge.id)];
  if (new Set(allSemanticIds).size !== allSemanticIds.length) {
    invalid("visual_structure", "reuses connector identifiers");
  }
  const directedPairs = new Set<string>();
  const ownedConnectorLabels = new Set<string>();
  const connectors: ValidatedDiagramConnector[] = stagedConnectors.map((connector) => {
    const source = nodesById.get(connector.sourceNodeId);
    const target = nodesById.get(connector.targetNodeId);
    if (!source || !target || source === target) {
      invalid(`visual_structure.connectors.${connector.id}`, "has unknown or identical endpoints");
    }
    const pair = `${source.id}\u0000${target.id}`;
    if (directedPairs.has(pair)) {
      invalid("visual_structure.connectors", "repeats a directed edge");
    }
    directedPairs.add(pair);
    requireEvidence(
      evidenceById,
      connector.pathEvidenceId,
      "path",
      `visual_structure.connectors.${connector.id}.path_evidence_id`,
    );
    for (const id of connector.endpointEvidenceIds) {
      requireEvidence(
        evidenceById,
        id,
        "point",
        `visual_structure.connectors.${connector.id}.endpoint_evidence_ids`,
      );
    }
    requireEvidence(
      evidenceById,
      connector.directionEvidenceId,
      "connector",
      `visual_structure.connectors.${connector.id}.direction_evidence_id`,
    );
    const requiredEvidence = new Set([
      connector.pathEvidenceId,
      ...connector.endpointEvidenceIds,
      connector.directionEvidenceId,
    ]);
    if (
      [...requiredEvidence].some((id) => !connector.evidenceIds.includes(id)) ||
      connector.evidenceIds.some((id) => !evidenceById.has(id))
    ) {
      invalid(`visual_structure.connectors.${connector.id}.evidence_ids`, "is incomplete");
    }
    let label: ValidatedLabel | null = null;
    if (connector.labelId !== null) {
      label = labelsById.get(connector.labelId) ?? null;
      if (
        !label ||
        label.role !== "connector" ||
        label.evidenceIds.some((id) => !connector.evidenceIds.includes(id)) ||
        ownedConnectorLabels.has(label.id)
      ) {
        invalid(`visual_structure.connectors.${connector.id}.label_id`, "has invalid label ownership");
      }
      ownedConnectorLabels.add(label.id);
    }
    return {
      id: connector.id,
      source,
      target,
      label: label ? { id: label.id, text: label.text } : null,
    };
  });
  if (labels.some((label) => label.role === "connector" && !ownedConnectorLabels.has(label.id))) {
    invalid("visual_structure.labels", "has an unowned connector label");
  }

  const concernRecords = arrayAt(structure.concerns, "visual_structure.concerns", 0, 256);
  concernRecords.forEach((value, index) => {
    const path = `visual_structure.concerns[${index}]`;
    const record = recordAt(value, path);
    exactKeys(record, ["code", "severity", "stage", "evidence_ids"], path);
    if (typeof record.code !== "string" || !CONCERN_CODE.test(record.code)) {
      invalid(`${path}.code`, "is malformed");
    }
    if (!new Set(["info", "warning", "error"]).has(record.severity as string)) {
      invalid(`${path}.severity`, "is unsupported");
    }
    boundedText(record.stage, `${path}.stage`, 64);
    for (const id of stringIds(record.evidence_ids, `${path}.evidence_ids`)) {
      if (!evidenceById.has(id)) invalid(`${path}.evidence_ids`, "uses unknown evidence");
    }
  });

  const fallback = recordAt(structure.fallback, "visual_structure.fallback");
  exactKeys(fallback, ["active", "reason", "predecessor_concern"], "visual_structure.fallback");
  if (
    fallback.active !== false ||
    fallback.reason !== "none" ||
    fallback.predecessor_concern !== "diagram_relationships_not_structured"
  ) {
    invalid("visual_structure.fallback", "is not authoritative");
  }
  const serialization = recordAt(structure.serialization, "visual_structure.serialization");
  exactKeys(
    serialization,
    ["status", "markdown", "caption_occurrences", "row_count"],
    "visual_structure.serialization",
  );
  if (serialization.status !== "diagram_topology") {
    invalid("visual_structure.serialization.status", "is not diagram topology");
  }
  const markdown = boundedText(
    serialization.markdown,
    "visual_structure.serialization.markdown",
    MAX_MARKDOWN_BYTES,
  );
  const captionOccurrences = integer(
    serialization.caption_occurrences,
    "visual_structure.serialization.caption_occurrences",
    0,
    1,
  );
  if (
    integer(
      serialization.row_count,
      "visual_structure.serialization.row_count",
      0,
      MAX_CONNECTORS,
    ) !== connectors.length
  ) {
    invalid("visual_structure.serialization.row_count", "differs from connector authority");
  }
  const caption = itemCaption(owner);
  if (captionOccurrences !== (caption ? 1 : 0)) {
    invalid("visual_structure.serialization.caption_occurrences", "differs from owner caption");
  }
  const forest = buildForest(nodes, connectors);
  if (replayMarkdown(forest, caption) !== markdown) {
    invalid("visual_structure.serialization.markdown", "does not replay from the graph");
  }
  if (owner.value !== markdown || owner.md !== markdown) {
    invalid("owner", "does not publish the exact graph serialization");
  }
  return { owner, caption, markdown, nodes, connectors, forest };
}

/**
 * Resolve one uniquely owned, graph-replayable diagram for a canonical block.
 * Any absent, duplicate, malformed, fallback, or byte-mismatched authority
 * returns null so the caller preserves the existing canonical paragraph.
 */
export function readDiagramSemanticsForCanonicalBlock(
  block: CanonicalBlock,
  page: PageResult,
): ValidatedDiagramSemantics | null {
  if (
    block.primary_element_type !== "diagram" ||
    block.scope !== "body" ||
    (block.omission_reason ?? null) !== null ||
    block.text !== block.markdown ||
    pythonStrip(block.text).length === 0
  ) {
    return null;
  }
  const itemIds = page.items.map((item) => item.id);
  if (
    itemIds.some((id) => typeof id !== "string" || !ID.test(id)) ||
    new Set(itemIds).size !== itemIds.length
  ) {
    return null;
  }
  const candidates: ValidatedDiagramSemantics[] = [];
  for (const item of page.items) {
    if (item.type !== "diagram" || item.visual_structure === undefined) continue;
    try {
      const decoded = decodeOwner(item, page);
      if (
        decoded.markdown === block.text &&
        decoded.markdown === block.markdown
      ) {
        candidates.push(decoded);
      }
    } catch (error) {
      if (
        !(error instanceof InvalidDiagramSemantics) ||
        (item.value === block.text && item.md === block.markdown)
      ) {
        return null;
      }
    }
  }
  return candidates.length === 1 ? candidates[0] : null;
}

function renderConnectorLabel(connector: ValidatedDiagramConnector | null): ReactNode {
  return connector?.label
    ? createElement(
        "span",
        { className: "diagram-connector-label", "data-connector-label-id": connector.label.id },
        connector.label.text,
        ": ",
      )
    : null;
}

function renderEntry(entry: DiagramListEntry): ReactNode {
  if (entry.kind === "reference") {
    const phrase = entry.referenceKind === "loop" ? "Returns to: " : "Continues at: ";
    return createElement(
      "li",
      {
        className: "diagram-reference-entry",
        "data-connector-id": entry.connector.id,
        "data-diagram-reference": entry.referenceKind,
        "data-reference-node-id": entry.target.id,
        key: entry.connector.id,
      },
      renderConnectorLabel(entry.connector),
      createElement("span", { className: "diagram-reference-prefix" }, phrase),
      createElement(
        "span",
        { className: "diagram-node-label", "data-node-label-id": entry.target.label.id },
        entry.target.label.text,
      ),
    );
  }
  return createElement(
    "li",
    {
      className: "diagram-node-entry",
      "data-connector-id": entry.connector?.id,
      "data-diagram-node-id": entry.node.id,
      "data-node-shape": entry.node.shape,
      key: entry.connector?.id ?? `root:${entry.node.id}`,
    },
    renderConnectorLabel(entry.connector),
    createElement(
      "span",
      { className: "diagram-node-label", "data-node-label-id": entry.node.label.id },
      entry.node.label.text,
    ),
    entry.node.details.length
      ? createElement(
          "ul",
          { className: "diagram-node-details" },
          ...entry.node.details.map((detail) =>
            createElement(
              "li",
              { "data-detail-label-id": detail.id, key: detail.id },
              detail.text,
            ),
          ),
        )
      : null,
    entry.children.length
      ? createElement(
          "ul",
          { className: "diagram-branch-list" },
          ...entry.children.map(renderEntry),
        )
      : null,
  );
}

/** Render only already validated graph data; React keeps all source text inert. */
export function renderValidatedDiagramSemantics(
  semantics: ValidatedDiagramSemantics,
): ReactNode {
  return createElement(
    "div",
    {
      className: "parsed-diagram-semantics",
      "data-diagram-owner-id": semantics.owner.id,
      "data-diagram-rendering": "semantic-list",
    },
    semantics.caption
      ? createElement(
          "p",
          {
            className: "parsed-caption diagram-owner-caption",
            "data-caption-of": semantics.owner.id,
            "data-item-type": "caption",
          },
          semantics.caption,
        )
      : null,
    createElement(
      "ul",
      { className: "diagram-root-list" },
      ...semantics.forest.map(renderEntry),
    ),
  );
}
