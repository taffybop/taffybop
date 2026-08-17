import { createElement, type ReactNode } from "react";

import type {
  CanonicalBlock,
  CanonicalPage,
  CanonicalPresentation,
  DocumentContentItem,
  OutlineBoundingBox,
  OutlineConcernCode,
  OutlineConfidence,
  OutlineContinuation,
  OutlineGroup,
  OutlineItem,
  OutlineMarkerStyle,
  OutlinePublicPath,
  OutlineRelationship,
  OutlineSequenceKind,
  PageResult,
  ParseResult,
  TextRunTargetPath,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

const POLICY_ID = "p03-outline-structure-v1";
const MAX_ID_BYTES = 256;
const MAX_MARKER_BYTES = 64;
const MAX_BODY_BYTES = 16 * 1024;
const MAX_GROUP_BYTES = 512 * 1024;
const MAX_DEPTH = 8;
const MAX_NODES_PER_GROUP = 256;
const MAX_GROUPS_PER_PAGE = 256;
const MAX_GROUPS_PER_DOCUMENT = 2_048;
const MAX_NODES_PER_PAGE = 4_096;
const MAX_NODES_PER_DOCUMENT = 32_768;
const MAX_CONTINUATIONS_PER_GROUP = 64;
const MAX_RELATIONSHIPS_PER_PAGE = 16_384;
const MAX_RELATIONSHIPS_PER_DOCUMENT = 65_536;
const MAX_CONCERNS_PER_PAGE = 64;
const MAX_PATH_SEGMENTS = 16;
const MAX_EVIDENCE_IDS = 64;
const GEOMETRY_EPSILON = 0.001;

const GROUP_KEYS = [
  "id",
  "element_id",
  "page_id",
  "sequence_kind",
  "marker_style",
  "anchor_public_item_id",
  "anchor_element_id",
  "anchor_public_path",
  "group_bbox",
  "member_item_ids",
  "member_element_ids",
  "continuation_ids",
  "continuation_element_ids",
  "relationship_ids",
  "relationship_cardinality",
  "canonical_block_id",
  "canonical_primary_element_id",
  "canonical_contributor_element_ids",
  "canonical_relationship_ids",
  "canonical_markdown_sha256",
  "canonical_text_sha256",
  "source_method",
  "confidence",
  "concern_codes",
] as const;
const ITEM_KEYS = [
  "id",
  "element_id",
  "source_public_item_id",
  "source_public_path",
  "source_bbox_id",
  "source_evidence_ids",
  "source_object",
  "sequence_kind",
  "marker_style",
  "raw_marker",
  "marker_bbox",
  "marker_ownership",
  "marker_separator",
  "body_text",
  "predecessor_value_sha256",
  "level",
  "ordinal",
  "parent_id",
  "marker_bbox_id",
  "marker_evidence_id",
  "source_method",
  "confidence",
  "concern_codes",
  "relationship_ids",
  "continuation_ids",
] as const;
const CONTINUATION_KEYS = [
  "id",
  "element_id",
  "source_public_item_id",
  "source_public_path",
  "source_type",
  "bbox_id",
  "bbox",
  "source_evidence_ids",
  "target_node_id",
  "source_method",
  "confidence",
  "concern_codes",
  "relationship_ids",
] as const;
const RELATIONSHIP_BASE_KEYS = [
  "id",
  "type",
  "source_id",
  "target_id",
  "evidence_ids",
  "canonical_inert",
  "outline_group_id",
  "outline_policy",
] as const;
const OUTLINE_ANCHOR_KEYS = [
  "layout_outline_structure_projected",
  "outline_policy",
  "outline_group",
  "outline_items",
  "outline_continuations",
] as const;
const BBOX_KEYS = ["x", "y", "width", "height", "unit"] as const;
const CONFIDENCE_KEYS = ["scope", "score", "unavailable_reason"] as const;
const SOURCE_OBJECT_KEYS = ["reader", "page_index", "word_index"] as const;
const CARDINALITY_KEYS = [
  "contains",
  "outline_parent_of",
  "outline_next",
  "outline_continuation_of",
] as const;

const SEQUENCE_KINDS = new Set<OutlineSequenceKind>([
  "unordered",
  "ordered",
  "legal",
]);
const MARKER_STYLES = new Set<OutlineMarkerStyle>([
  "bullet",
  "decimal",
  "lower_alpha",
]);
const RELATIONSHIP_TYPES = new Set<OutlineRelationship["type"]>([
  "contains",
  "outline_parent_of",
  "outline_next",
  "outline_continuation_of",
]);
const CONCERN_CODES = [
  "outline_source_evidence_unavailable",
  "outline_source_limit",
  "outline_candidate_limit",
  "outline_geometry_ambiguous",
  "outline_marker_ambiguous",
  "outline_sequence_invalid",
  "outline_interstitial_ambiguous",
  "outline_relationship_limit",
  "outline_canonical_custody_invalid",
  "outline_projection_failed_closed",
  "outline_concerns_truncated",
] as const satisfies readonly OutlineConcernCode[];
const SHA256 = /^[0-9a-f]{64}$/u;

class InvalidOutlineStructure extends Error {}

function invalid(path: string, message: string): never {
  throw new InvalidOutlineStructure(`${path} ${message}`);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordAt(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) invalid(path, "must be an object");
  return value;
}

function exactKeys(
  record: JsonRecord,
  expectedKeys: readonly string[],
  path: string,
): void {
  const expected = new Set(expectedKeys);
  for (const key of expected) {
    if (!Object.prototype.hasOwnProperty.call(record, key)) {
      invalid(path, `is missing ${JSON.stringify(key)}`);
    }
  }
  for (const key of Object.keys(record)) {
    if (!expected.has(key)) {
      invalid(path, `contains unsupported field ${JSON.stringify(key)}`);
    }
  }
}

function byteLength(value: string): number {
  return new TextEncoder().encode(value).byteLength;
}

function boundedString(
  value: unknown,
  path: string,
  maximum = MAX_ID_BYTES,
  options: { allowEmpty?: boolean; nonWhitespace?: boolean } = {},
): string {
  const allowEmpty = options.allowEmpty ?? false;
  if (
    typeof value !== "string" ||
    (!allowEmpty && value.length === 0) ||
    byteLength(value) > maximum ||
    (options.nonWhitespace === true && value.trim().length === 0)
  ) {
    invalid(path, "must be a bounded string");
  }
  return value;
}

function integerAt(
  value: unknown,
  path: string,
  minimum = 0,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < minimum ||
    (value as number) > maximum
  ) {
    invalid(path, `must be an integer in [${minimum},${maximum}]`);
  }
  return value as number;
}

function finiteAt(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    invalid(path, "must be a finite number");
  }
  return value;
}

function arrayAt(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): unknown[] {
  if (
    !Array.isArray(value) ||
    value.length < minimum ||
    value.length > maximum
  ) {
    invalid(path, `must contain ${minimum}-${maximum} entries`);
  }
  return value;
}

function uniqueStrings(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): string[] {
  const result = arrayAt(value, path, minimum, maximum).map((entry, index) =>
    boundedString(entry, `${path}[${index}]`),
  );
  if (new Set(result).size !== result.length) {
    invalid(path, "must not repeat IDs");
  }
  return result;
}

function sameStrings(
  actual: readonly string[],
  expected: readonly string[],
): boolean {
  return (
    actual.length === expected.length &&
    actual.every((value, index) => value === expected[index])
  );
}

function pathKey(path: readonly (string | number)[]): string {
  return JSON.stringify(path);
}

function validateBBox(
  value: unknown,
  page: PageResult,
  path: string,
  exact = true,
): OutlineBoundingBox {
  const record = recordAt(value, path);
  if (exact) exactKeys(record, BBOX_KEYS, path);
  const x = finiteAt(record.x, `${path}.x`);
  const y = finiteAt(record.y, `${path}.y`);
  const width = finiteAt(record.width, `${path}.width`);
  const height = finiteAt(record.height, `${path}.height`);
  const pageWidth = finiteAt(page.page_width, "page.page_width");
  const pageHeight = finiteAt(page.page_height, "page.page_height");
  if (
    record.unit !== "pt" ||
    page.unit !== "pt" ||
    pageWidth <= 0 ||
    pageHeight <= 0 ||
    x < 0 ||
    y < 0 ||
    width <= 0 ||
    height <= 0 ||
    x + width > pageWidth + GEOMETRY_EPSILON ||
    y + height > pageHeight + GEOMETRY_EPSILON
  ) {
    invalid(path, "must be a finite positive in-page top-left point bbox");
  }
  return { x, y, width, height, unit: "pt" };
}

function sameBBox(left: OutlineBoundingBox, right: OutlineBoundingBox): boolean {
  return (
    left.unit === right.unit &&
    Math.abs(left.x - right.x) <= GEOMETRY_EPSILON &&
    Math.abs(left.y - right.y) <= GEOMETRY_EPSILON &&
    Math.abs(left.width - right.width) <= GEOMETRY_EPSILON &&
    Math.abs(left.height - right.height) <= GEOMETRY_EPSILON
  );
}

function validateConfidence(value: unknown, path: string): OutlineConfidence {
  const record = recordAt(value, path);
  exactKeys(record, CONFIDENCE_KEYS, path);
  if (record.scope !== "evidence") {
    invalid(`${path}.scope`, "must equal evidence");
  }
  if (
    record.score !== null ||
    (record.unavailable_reason !== "not_calibrated" &&
      record.unavailable_reason !== "source_state_unavailable")
  ) {
    invalid(path, "must carry the closed unavailable-confidence shape");
  }
  return record as unknown as OutlineConfidence;
}

function validateConcerns(value: unknown, path: string): OutlineConcernCode[] {
  const concerns = uniqueStrings(value, path, 0, MAX_CONCERNS_PER_PAGE);
  const ranks = concerns.map((code) =>
    CONCERN_CODES.indexOf(code as OutlineConcernCode),
  );
  if (
    ranks.some((rank) => rank < 0) ||
    ranks.some((rank, index) => index > 0 && rank <= ranks[index - 1])
  ) {
    invalid(path, "must follow the closed concern-code order");
  }
  return concerns as OutlineConcernCode[];
}

function validateSequenceAndStyle(
  sequence: unknown,
  style: unknown,
  path: string,
): { sequence: OutlineSequenceKind; style: OutlineMarkerStyle } {
  if (!SEQUENCE_KINDS.has(sequence as OutlineSequenceKind)) {
    invalid(`${path}.sequence_kind`, "is unsupported");
  }
  if (!MARKER_STYLES.has(style as OutlineMarkerStyle)) {
    invalid(`${path}.marker_style`, "is unsupported");
  }
  const expectedStyle =
    sequence === "unordered"
      ? "bullet"
      : sequence === "ordered"
        ? "decimal"
        : "lower_alpha";
  if (style !== expectedStyle) {
    invalid(path, "has an incompatible sequence kind and marker style");
  }
  return {
    sequence: sequence as OutlineSequenceKind,
    style: style as OutlineMarkerStyle,
  };
}

function validatePublicPath(value: unknown, path: string): OutlinePublicPath {
  const entries = arrayAt(value, path, 4, MAX_PATH_SEGMENTS);
  return entries.map((entry, index) => {
    if (typeof entry === "string") {
      return boundedString(entry, `${path}[${index}]`, MAX_ID_BYTES, {
        nonWhitespace: true,
      });
    }
    return integerAt(entry, `${path}[${index}]`);
  });
}

function validateGroup(
  value: unknown,
  page: PageResult,
  path: string,
): OutlineGroup {
  const record = recordAt(value, path);
  exactKeys(record, GROUP_KEYS, path);
  boundedString(record.id, `${path}.id`);
  boundedString(record.element_id, `${path}.element_id`);
  boundedString(record.page_id, `${path}.page_id`);
  validateSequenceAndStyle(record.sequence_kind, record.marker_style, path);
  boundedString(record.anchor_public_item_id, `${path}.anchor_public_item_id`);
  boundedString(record.anchor_element_id, `${path}.anchor_element_id`);
  validatePublicPath(record.anchor_public_path, `${path}.anchor_public_path`);
  validateBBox(record.group_bbox, page, `${path}.group_bbox`);
  uniqueStrings(
    record.member_item_ids,
    `${path}.member_item_ids`,
    2,
    MAX_NODES_PER_GROUP,
  );
  uniqueStrings(
    record.member_element_ids,
    `${path}.member_element_ids`,
    2,
    MAX_NODES_PER_GROUP,
  );
  uniqueStrings(
    record.continuation_ids,
    `${path}.continuation_ids`,
    0,
    MAX_CONTINUATIONS_PER_GROUP,
  );
  uniqueStrings(
    record.continuation_element_ids,
    `${path}.continuation_element_ids`,
    0,
    MAX_CONTINUATIONS_PER_GROUP,
  );
  uniqueStrings(
    record.relationship_ids,
    `${path}.relationship_ids`,
    3,
    MAX_RELATIONSHIPS_PER_PAGE,
  );
  const cardinality = recordAt(
    record.relationship_cardinality,
    `${path}.relationship_cardinality`,
  );
  exactKeys(cardinality, CARDINALITY_KEYS, `${path}.relationship_cardinality`);
  for (const key of CARDINALITY_KEYS) {
    integerAt(
      cardinality[key],
      `${path}.relationship_cardinality.${key}`,
      0,
      MAX_RELATIONSHIPS_PER_PAGE,
    );
  }
  boundedString(record.canonical_block_id, `${path}.canonical_block_id`);
  boundedString(
    record.canonical_primary_element_id,
    `${path}.canonical_primary_element_id`,
  );
  uniqueStrings(
    record.canonical_contributor_element_ids,
    `${path}.canonical_contributor_element_ids`,
    1,
    MAX_NODES_PER_DOCUMENT,
  );
  uniqueStrings(
    record.canonical_relationship_ids,
    `${path}.canonical_relationship_ids`,
    0,
    MAX_RELATIONSHIPS_PER_DOCUMENT,
  );
  for (const key of ["canonical_markdown_sha256", "canonical_text_sha256"] as const) {
    const digest = boundedString(record[key], `${path}.${key}`, 64);
    if (!SHA256.test(digest)) {
      invalid(`${path}.${key}`, "must be a lowercase SHA-256 field");
    }
  }
  if (record.source_method !== "native") {
    invalid(`${path}.source_method`, "must equal native");
  }
  validateConfidence(record.confidence, `${path}.confidence`);
  validateConcerns(record.concern_codes, `${path}.concern_codes`);
  return record as unknown as OutlineGroup;
}

function validateItem(
  value: unknown,
  page: PageResult,
  path: string,
): OutlineItem {
  const record = recordAt(value, path);
  exactKeys(record, ITEM_KEYS, path);
  boundedString(record.id, `${path}.id`);
  boundedString(record.element_id, `${path}.element_id`);
  boundedString(record.source_public_item_id, `${path}.source_public_item_id`);
  validatePublicPath(record.source_public_path, `${path}.source_public_path`);
  boundedString(record.source_bbox_id, `${path}.source_bbox_id`);
  uniqueStrings(
    record.source_evidence_ids,
    `${path}.source_evidence_ids`,
    1,
    MAX_EVIDENCE_IDS,
  );
  const sourceObject = recordAt(record.source_object, `${path}.source_object`);
  exactKeys(sourceObject, SOURCE_OBJECT_KEYS, `${path}.source_object`);
  if (sourceObject.reader !== "pdfplumber") {
    invalid(`${path}.source_object.reader`, "must equal pdfplumber");
  }
  if (
    integerAt(sourceObject.page_index, `${path}.source_object.page_index`, 1) !==
    page.page_index
  ) {
    invalid(`${path}.source_object.page_index`, "must match the public page");
  }
  integerAt(sourceObject.word_index, `${path}.source_object.word_index`);
  validateSequenceAndStyle(record.sequence_kind, record.marker_style, path);
  boundedString(record.raw_marker, `${path}.raw_marker`, MAX_MARKER_BYTES);
  validateBBox(record.marker_bbox, page, `${path}.marker_bbox`);
  if (record.marker_ownership !== "separate" && record.marker_ownership !== "value_prefix") {
    invalid(`${path}.marker_ownership`, "is unsupported");
  }
  const separator = boundedString(
    record.marker_separator,
    `${path}.marker_separator`,
    MAX_MARKER_BYTES,
    { allowEmpty: true },
  );
  if (record.marker_ownership === "separate" && separator !== "") {
    invalid(`${path}.marker_separator`, "must be empty for separate ownership");
  } else if (record.marker_ownership === "value_prefix" && separator !== " ") {
    invalid(`${path}.marker_separator`, "must be one ASCII space for value-prefix ownership");
  }
  boundedString(record.body_text, `${path}.body_text`, MAX_BODY_BYTES, {
    nonWhitespace: true,
  });
  const predecessorDigest = boundedString(
    record.predecessor_value_sha256,
    `${path}.predecessor_value_sha256`,
    64,
  );
  if (!SHA256.test(predecessorDigest)) {
    invalid(`${path}.predecessor_value_sha256`, "must be a lowercase SHA-256 field");
  }
  integerAt(record.level, `${path}.level`, 0, MAX_DEPTH - 1);
  integerAt(record.ordinal, `${path}.ordinal`, 1, MAX_NODES_PER_GROUP);
  if (record.parent_id !== null) {
    boundedString(record.parent_id, `${path}.parent_id`);
  }
  boundedString(record.marker_bbox_id, `${path}.marker_bbox_id`);
  boundedString(
    record.marker_evidence_id,
    `${path}.marker_evidence_id`,
  );
  if (record.source_method !== "native") {
    invalid(`${path}.source_method`, "must equal native");
  }
  validateConfidence(record.confidence, `${path}.confidence`);
  validateConcerns(record.concern_codes, `${path}.concern_codes`);
  uniqueStrings(
    record.relationship_ids,
    `${path}.relationship_ids`,
    1,
    323,
  );
  uniqueStrings(
    record.continuation_ids,
    `${path}.continuation_ids`,
    0,
    MAX_CONTINUATIONS_PER_GROUP,
  );
  return record as unknown as OutlineItem;
}

function validateContinuation(
  value: unknown,
  page: PageResult,
  path: string,
): OutlineContinuation {
  const record = recordAt(value, path);
  exactKeys(record, CONTINUATION_KEYS, path);
  boundedString(record.id, `${path}.id`);
  boundedString(record.element_id, `${path}.element_id`);
  boundedString(record.source_public_item_id, `${path}.source_public_item_id`);
  validatePublicPath(record.source_public_path, `${path}.source_public_path`);
  if (record.source_type !== "table") {
    invalid(`${path}.source_type`, "must equal table");
  }
  boundedString(record.bbox_id, `${path}.bbox_id`);
  validateBBox(record.bbox, page, `${path}.bbox`);
  uniqueStrings(
    record.source_evidence_ids,
    `${path}.source_evidence_ids`,
    1,
    MAX_EVIDENCE_IDS,
  );
  boundedString(record.target_node_id, `${path}.target_node_id`);
  if (record.source_method !== "native") {
    invalid(`${path}.source_method`, "must equal native");
  }
  validateConfidence(record.confidence, `${path}.confidence`);
  validateConcerns(record.concern_codes, `${path}.concern_codes`);
  uniqueStrings(record.relationship_ids, `${path}.relationship_ids`, 1, 1);
  return record as unknown as OutlineContinuation;
}

function validateRelationship(
  value: unknown,
  groupId: string,
  path: string,
): OutlineRelationship {
  const record = recordAt(value, path);
  if (!RELATIONSHIP_TYPES.has(record.type as OutlineRelationship["type"])) {
    invalid(`${path}.type`, "is unsupported");
  }
  const extra =
    record.type === "outline_next"
      ? ["intervening_element_ids"]
      : record.type === "outline_continuation_of"
        ? ["interstitial_kind"]
        : [];
  exactKeys(record, [...RELATIONSHIP_BASE_KEYS, ...extra], path);
  boundedString(record.id, `${path}.id`);
  const sourceId = boundedString(record.source_id, `${path}.source_id`);
  const targetId = boundedString(record.target_id, `${path}.target_id`);
  if (sourceId === targetId) invalid(path, "cannot be a self-edge");
  uniqueStrings(record.evidence_ids, `${path}.evidence_ids`, 1, MAX_EVIDENCE_IDS);
  if (record.canonical_inert !== true) {
    invalid(`${path}.canonical_inert`, "must be true");
  }
  if (record.outline_group_id !== groupId || record.outline_policy !== POLICY_ID) {
    invalid(path, "does not carry the exact group and policy identity");
  }
  if (record.type === "outline_next") {
    uniqueStrings(
      record.intervening_element_ids,
      `${path}.intervening_element_ids`,
      0,
      MAX_CONTINUATIONS_PER_GROUP,
    );
  } else if (
    record.type === "outline_continuation_of" &&
    record.interstitial_kind !== "table"
  ) {
    invalid(`${path}.interstitial_kind`, "must equal table");
  }
  return record as unknown as OutlineRelationship;
}

export interface ValidatedOutlineItemSource {
  sourceItem: DocumentContentItem;
  sourceRecord: JsonRecord;
  targetPath: TextRunTargetPath;
  value: string;
  bbox: OutlineBoundingBox;
}

export interface ValidatedOutlineContinuationSource {
  sourceItem: DocumentContentItem;
  rows: string[][];
}

export interface ValidatedOutlineStructure {
  anchor: DocumentContentItem;
  page: PageResult;
  canonicalPage: CanonicalPage;
  block: CanonicalBlock;
  group: OutlineGroup;
  items: OutlineItem[];
  continuations: OutlineContinuation[];
  relationships: OutlineRelationship[];
  itemSources: ReadonlyMap<string, ValidatedOutlineItemSource>;
  continuationSources: ReadonlyMap<
    string,
    ValidatedOutlineContinuationSource
  >;
}

function resolveSourcePath(
  result: ParseResult,
  pageArrayIndex: number,
  pathValue: unknown,
  path: string,
  requireStringValue = true,
): ValidatedOutlineItemSource {
  const publicPath = validatePublicPath(pathValue, path);
  if (
    publicPath[0] !== "pages" ||
    publicPath[1] !== pageArrayIndex ||
    publicPath[2] !== "items" ||
    typeof publicPath[3] !== "number" ||
    (publicPath.length !== 4 &&
      !(
        publicPath.length === 6 &&
        publicPath[4] === "items" &&
        typeof publicPath[5] === "number"
      ))
  ) {
    invalid(path, "must use the frozen same-page public-item path grammar");
  }
  const page = result.pages[pageArrayIndex];
  const sourceItem = page?.items[publicPath[3]];
  if (!sourceItem || !isRecord(sourceItem)) {
    invalid(path, "does not resolve to one top-level public item");
  }
  let sourceRecord: JsonRecord = sourceItem as unknown as JsonRecord;
  let targetPath: TextRunTargetPath = ["value"];
  if (publicPath.length === 6) {
    const nestedIndex = publicPath[5] as number;
    const nested = sourceItem.items?.[nestedIndex];
    if (!nested || !isRecord(nested)) {
      invalid(path, "does not resolve to one nested public item");
    }
    sourceRecord = nested;
    targetPath = ["items", nestedIndex, "value"];
  }
  const value = requireStringValue
    ? boundedString(
        sourceRecord.value,
        `${path}.value`,
        MAX_BODY_BYTES + MAX_MARKER_BYTES,
        { nonWhitespace: true },
      )
    : typeof sourceRecord.value === "string"
      ? sourceRecord.value
      : "";
  if (sourceRecord.source !== "native") {
    invalid(path, "must resolve to native source content");
  }
  return {
    sourceItem,
    sourceRecord,
    targetPath,
    value,
    bbox: validateBBox(sourceRecord.bbox, page, `${path}.bbox`, false),
  };
}

function validateTableRows(item: DocumentContentItem, path: string): string[][] {
  if (!Array.isArray(item.rows) || item.rows.length === 0) {
    invalid(`${path}.rows`, "must contain source table rows");
  }
  const rawRows = item.rows;
  const rows = rawRows.map((row, rowIndex) => {
    if (!Array.isArray(row) || row.length === 0) {
      invalid(`${path}.rows[${rowIndex}]`, "must contain source table cells");
    }
    return row.map((cell, cellIndex) => {
      if (typeof cell !== "string") {
        invalid(`${path}.rows[${rowIndex}][${cellIndex}]`, "must be text");
      }
      return cell;
    });
  });

  // The shared table renderer optionally consults cell metadata for text-run
  // overlays. Validate the small surface it reads so an otherwise valid
  // outline sidecar cannot route malformed source data into that renderer.
  if (item.cells !== undefined && item.cells !== null) {
    if (!Array.isArray(item.cells)) {
      invalid(`${path}.cells`, "must be an array when present");
    }
    item.cells.forEach((cell, cellIndex) => {
      if (
        !isRecord(cell) ||
        !Number.isSafeInteger(cell.row) ||
        (cell.row as number) < 0 ||
        !Number.isSafeInteger(cell.column) ||
        (cell.column as number) < 0 ||
        (cell.text !== undefined && typeof cell.text !== "string")
      ) {
        invalid(
          `${path}.cells[${cellIndex}]`,
          "must contain safe row, column, and optional text values",
        );
      }
    });
  }
  return rows;
}

function itemHasOutlineFields(record: JsonRecord): boolean {
  return OUTLINE_ANCHOR_KEYS.some((key) =>
    Object.prototype.hasOwnProperty.call(record, key),
  );
}

function itemHasFormFields(record: JsonRecord): boolean {
  return [
    "layout_forms_projected",
    "form_policy",
    "form_group",
    "form_fields",
    "form_labels",
    "form_value_regions",
    "form_controls",
    "form_key_value_pairs",
  ].some((key) => Object.prototype.hasOwnProperty.call(record, key));
}

function collectFormOwnedElementIds(result: ParseResult): Set<string> {
  const resultIds = new Set<string>();
  for (const page of result.pages) {
    for (const item of page.items) {
      if (!isRecord(item.form_group)) continue;
      for (const key of [
        "element_id",
        "anchor_element_id",
      ] as const) {
        if (typeof item.form_group[key] === "string") {
          resultIds.add(item.form_group[key] as string);
        }
      }
      if (Array.isArray(item.form_group.contributor_element_ids)) {
        for (const id of item.form_group.contributor_element_ids) {
          if (typeof id === "string") resultIds.add(id);
        }
      }
      for (const property of [
        "form_fields",
        "form_labels",
        "form_value_regions",
        "form_controls",
        "form_key_value_pairs",
      ] as const) {
        const values = item[property];
        if (!Array.isArray(values)) continue;
        for (const value of values) {
          if (isRecord(value) && typeof value.element_id === "string") {
            resultIds.add(value.element_id);
          }
        }
      }
    }
  }
  return resultIds;
}

function relationshipEdgeKey(relationship: OutlineRelationship): string {
  const extra =
    relationship.type === "outline_next"
      ? relationship.intervening_element_ids.join("\u0001")
      : relationship.type === "outline_continuation_of"
        ? relationship.interstitial_kind
        : "";
  return [
    relationship.type,
    relationship.source_id,
    relationship.target_id,
    extra,
  ].join("\u0000");
}

interface ExpectedEdge {
  type: OutlineRelationship["type"];
  source: string;
  target: string;
  extra?: string;
}

function expectedEdgeKey(edge: ExpectedEdge): string {
  return [edge.type, edge.source, edge.target, edge.extra ?? ""].join("\u0000");
}

function validateAnchor(
  result: ParseResult,
  pageArrayIndex: number,
  page: PageResult,
  canonicalPage: CanonicalPage,
  blockById: ReadonlyMap<string, CanonicalBlock>,
  anchor: DocumentContentItem,
  formOwnedElementIds: ReadonlySet<string>,
): ValidatedOutlineStructure {
  const anchorRecord = anchor as unknown as JsonRecord;
  if (
    anchor.layout_outline_structure_projected !== true ||
    anchor.outline_policy !== POLICY_ID ||
    !OUTLINE_ANCHOR_KEYS.every((key) =>
      Object.prototype.hasOwnProperty.call(anchorRecord, key),
    )
  ) {
    invalid("anchor", "does not carry the complete outline marker and policy");
  }
  if (itemHasFormFields(anchorRecord)) {
    invalid("anchor", "must not carry form semantic ownership");
  }

  const group = validateGroup(anchor.outline_group, page, "anchor.outline_group");
  const block = blockById.get(group.canonical_block_id);
  if (!block || !canonicalPage.blocks.some((entry) => entry.id === block.id)) {
    invalid("anchor.outline_group.canonical_block_id", "does not resolve on this page");
  }
  if (
    (block.omission_reason ?? null) !== null ||
    block.scope !== "body" ||
    group.page_id !== canonicalPage.page_id ||
    group.anchor_public_item_id !== anchor.id ||
    group.anchor_element_id !== block.primary_element_id ||
    group.canonical_primary_element_id !== block.primary_element_id ||
    !sameStrings(
      group.canonical_contributor_element_ids,
      block.contributing_element_ids,
    ) ||
    !sameStrings(group.canonical_relationship_ids, block.relationship_ids)
  ) {
    invalid("anchor.outline_group", "does not bind the exact included canonical block");
  }
  if (
    block.contributing_element_ids[0] !== group.anchor_element_id ||
    block.contributing_element_ids.includes(group.element_id) ||
    block.contributing_element_ids.some((id) => formOwnedElementIds.has(id))
  ) {
    invalid("anchor.outline_group", "has invalid canonical content custody");
  }

  const anchorPath = validatePublicPath(
    group.anchor_public_path,
    "anchor.outline_group.anchor_public_path",
  );
  const expectedAnchorIndex = page.items.indexOf(anchor);
  if (
    anchorPath.length !== 4 ||
    anchorPath[0] !== "pages" ||
    anchorPath[1] !== pageArrayIndex ||
    anchorPath[2] !== "items" ||
    anchorPath[3] !== expectedAnchorIndex
  ) {
    invalid("anchor.outline_group.anchor_public_path", "does not resolve to the anchor");
  }

  const rawItems = arrayAt(
    anchor.outline_items,
    "anchor.outline_items",
    2,
    MAX_NODES_PER_GROUP,
  );
  if (rawItems.length !== group.member_item_ids.length) {
    invalid("anchor.outline_items", "does not match group member cardinality");
  }
  const items = rawItems.map((value, index) =>
    validateItem(value, page, `anchor.outline_items[${index}]`),
  );
  const rawContinuations = arrayAt(
    anchor.outline_continuations,
    "anchor.outline_continuations",
    0,
    MAX_CONTINUATIONS_PER_GROUP,
  );
  if (rawContinuations.length !== group.continuation_ids.length) {
    invalid("anchor.outline_continuations", "does not match group continuation cardinality");
  }
  const continuations = rawContinuations.map((value, index) =>
    validateContinuation(value, page, `anchor.outline_continuations[${index}]`),
  );

  if (
    !sameStrings(items.map((item) => item.id), group.member_item_ids) ||
    !sameStrings(items.map((item) => item.element_id), group.member_element_ids) ||
    !sameStrings(continuations.map((item) => item.id), group.continuation_ids) ||
    !sameStrings(
      continuations.map((item) => item.element_id),
      group.continuation_element_ids,
    )
  ) {
    invalid("anchor.outline_group", "does not name sidecar records in exact order");
  }
  const itemIds = new Set(items.map((item) => item.id));
  const itemElementIds = new Set(items.map((item) => item.element_id));
  const continuationIds = new Set(continuations.map((item) => item.id));
  const continuationElementIds = new Set(
    continuations.map((item) => item.element_id),
  );
  if (
    itemIds.size !== items.length ||
    itemElementIds.size !== items.length ||
    continuationIds.size !== continuations.length ||
    continuationElementIds.size !== continuations.length ||
    itemIds.has(group.id) ||
    itemElementIds.has(group.element_id) ||
    [...itemIds].some((id) => continuationIds.has(id)) ||
    [...itemElementIds].some((id) => continuationElementIds.has(id)) ||
    group.member_element_ids.some(
      (id) => !block.contributing_element_ids.includes(id),
    ) ||
    group.continuation_element_ids.some(
      (id) => !block.contributing_element_ids.includes(id),
    )
  ) {
    invalid("anchor outline records", "repeat, overlap, or escape canonical custody");
  }
  if (
    continuations.length === 0 &&
    !sameStrings(block.contributing_element_ids, [
      group.anchor_element_id,
      ...group.member_element_ids,
    ])
  ) {
    invalid(
      "anchor.outline_group.canonical_contributor_element_ids",
      "contains unclaimed non-continuation content",
    );
  }

  const itemById = new Map(items.map((item) => [item.id, item]));
  const stack: OutlineItem[] = [];
  const siblingsByParent = new Map<string | null, OutlineItem[]>();
  for (const [index, item] of items.entries()) {
    if (
      item.sequence_kind !== group.sequence_kind ||
      item.marker_style !== group.marker_style
    ) {
      invalid(`anchor.outline_items[${index}]`, "differs from its group sequence contract");
    }
    if (index === 0 && item.level !== 0) {
      invalid("anchor.outline_items[0].level", "must begin at zero");
    }
    if (index > 0 && item.level > items[index - 1].level + 1) {
      invalid(`anchor.outline_items[${index}].level`, "skips a hierarchy level");
    }
    const expectedParent = item.level === 0 ? null : (stack[item.level - 1]?.id ?? null);
    if (item.parent_id !== expectedParent) {
      invalid(`anchor.outline_items[${index}].parent_id`, "is not the nearest direct parent");
    }
    if (item.parent_id !== null) {
      const parent = itemById.get(item.parent_id);
      if (!parent || parent.level + 1 !== item.level) {
        invalid(`anchor.outline_items[${index}].parent_id`, "does not resolve one level above");
      }
    }
    stack[item.level] = item;
    stack.length = item.level + 1;
    const siblings = siblingsByParent.get(item.parent_id) ?? [];
    siblings.push(item);
    siblingsByParent.set(item.parent_id, siblings);
  }
  const roots = siblingsByParent.get(null) ?? [];
  if (roots.length < 2 || (group.sequence_kind === "legal" && roots.length < 3)) {
    invalid("anchor.outline_items", "does not contain enough root siblings");
  }
  if (group.sequence_kind === "legal" && items.some((item) => item.level !== 0)) {
    invalid("anchor.outline_items", "legal v1 must remain a level-zero outline");
  }
  for (const [parentId, siblings] of siblingsByParent) {
    if (
      siblings.some((item, index) => item.ordinal !== index + 1) ||
      (parentId !== null && !itemById.has(parentId))
    ) {
      invalid("anchor.outline_items", "contains a non-contiguous sibling sequence");
    }
  }

  const itemSources = new Map<string, ValidatedOutlineItemSource>();
  const sourcePathKeys = new Set<string>();
  const sourceObjectKeys = new Set<string>();
  for (const [index, item] of items.entries()) {
    const source = resolveSourcePath(
      result,
      pageArrayIndex,
      item.source_public_path,
      `anchor.outline_items[${index}].source_public_path`,
    );
    if (source.sourceItem.id !== item.source_public_item_id) {
      invalid(`anchor.outline_items[${index}].source_public_item_id`, "does not own its path");
    }
    if (source.sourceRecord !== anchorRecord && itemHasOutlineFields(source.sourceRecord)) {
      invalid(`anchor.outline_items[${index}]`, "mutates a non-anchor source record");
    }
    if (itemHasFormFields(source.sourceRecord)) {
      invalid(`anchor.outline_items[${index}]`, "overlaps form-owned source content");
    }
    const expectedValue =
      item.marker_ownership === "separate"
        ? item.body_text
        : `${item.raw_marker}${item.marker_separator}${item.body_text}`;
    if (source.value !== expectedValue) {
      invalid(`anchor.outline_items[${index}]`, "does not recompose the predecessor value");
    }
    const sourcePathKey = pathKey(item.source_public_path);
    const sourceObjectKey = `${item.source_object.page_index}:${item.source_object.word_index}`;
    if (sourcePathKeys.has(sourcePathKey) || sourceObjectKeys.has(sourceObjectKey)) {
      invalid(`anchor.outline_items[${index}]`, "repeats source custody");
    }
    sourcePathKeys.add(sourcePathKey);
    sourceObjectKeys.add(sourceObjectKey);
    itemSources.set(item.id, source);
  }

  const continuationSources = new Map<
    string,
    ValidatedOutlineContinuationSource
  >();
  for (const [index, continuation] of continuations.entries()) {
    const source = resolveSourcePath(
      result,
      pageArrayIndex,
      continuation.source_public_path,
      `anchor.outline_continuations[${index}].source_public_path`,
      false,
    );
    if (
      source.targetPath[0] !== "value" ||
      source.sourceItem.id !== continuation.source_public_item_id ||
      source.sourceItem.type.toLowerCase() !== "table" ||
      !sameBBox(source.bbox, continuation.bbox) ||
      itemHasOutlineFields(source.sourceRecord) ||
      itemHasFormFields(source.sourceRecord) ||
      sourcePathKeys.has(pathKey(continuation.source_public_path))
    ) {
      invalid(`anchor.outline_continuations[${index}]`, "does not resolve one unowned source table");
    }
    sourcePathKeys.add(pathKey(continuation.source_public_path));
    continuationSources.set(continuation.id, {
      sourceItem: source.sourceItem,
      rows: validateTableRows(
        source.sourceItem,
        `anchor.outline_continuations[${index}].source_table`,
      ),
    });
  }

  if (!Array.isArray(anchor.relationships)) {
    invalid("anchor.relationships", "must contain the story relationship slice");
  }
  const declaredRelationshipIds = new Set(group.relationship_ids);
  const rawStoryRelationships = anchor.relationships.filter((value) => {
    if (!isRecord(value)) return false;
    const id = typeof value.id === "string" ? value.id : "";
    const type = typeof value.type === "string" ? value.type : "";
    return (
      declaredRelationshipIds.has(id) ||
      value.outline_policy === POLICY_ID ||
      value.outline_group_id === group.id ||
      type.startsWith("outline_")
    );
  });
  if (rawStoryRelationships.length !== group.relationship_ids.length) {
    invalid("anchor.relationships", "does not contain the exact story relationship slice");
  }
  const relationships = rawStoryRelationships.map((value, index) =>
    validateRelationship(value, group.id, `anchor.relationships[story:${index}]`),
  );
  if (!sameStrings(relationships.map((value) => value.id), group.relationship_ids)) {
    invalid("anchor.relationships", "does not follow group relationship order");
  }

  const continuationsByTarget = new Map<string, OutlineContinuation[]>();
  for (const continuation of continuations) {
    if (!itemById.has(continuation.target_node_id)) {
      invalid(`continuation ${continuation.id}`, "has no target node");
    }
    const values = continuationsByTarget.get(continuation.target_node_id) ?? [];
    values.push(continuation);
    continuationsByTarget.set(continuation.target_node_id, values);
  }
  const expectedEdges: ExpectedEdge[] = [];
  for (const item of items) {
    expectedEdges.push({
      type: "contains",
      source: group.element_id,
      target: item.element_id,
    });
    if (item.parent_id !== null) {
      expectedEdges.push({
        type: "outline_parent_of",
        source: itemById.get(item.parent_id)!.element_id,
        target: item.element_id,
      });
    }
  }
  for (const siblings of siblingsByParent.values()) {
    for (let index = 0; index < siblings.length - 1; index += 1) {
      const previous = siblings[index];
      const next = siblings[index + 1];
      const intervening = (continuationsByTarget.get(previous.id) ?? []).map(
        (continuation) => continuation.element_id,
      );
      expectedEdges.push({
        type: "outline_next",
        source: previous.element_id,
        target: next.element_id,
        extra: intervening.join("\u0001"),
      });
    }
    const terminal = siblings.at(-1);
    if (terminal && continuationsByTarget.has(terminal.id)) {
      invalid(`item ${terminal.id}`, "owns an interstitial without a next sibling");
    }
  }
  for (const continuation of continuations) {
    expectedEdges.push({
      type: "outline_continuation_of",
      source: continuation.element_id,
      target: itemById.get(continuation.target_node_id)!.element_id,
      extra: "table",
    });
  }
  const expectedEdgeKeys = expectedEdges.map(expectedEdgeKey).sort();
  const actualEdgeKeys = relationships.map(relationshipEdgeKey).sort();
  if (
    new Set(expectedEdgeKeys).size !== expectedEdgeKeys.length ||
    !sameStrings(expectedEdgeKeys, actualEdgeKeys)
  ) {
    invalid("anchor.relationships", "does not match the complete outline graph");
  }

  for (const item of items) {
    const incident = relationships
      .filter(
        (relationship) =>
          relationship.source_id === item.element_id ||
          relationship.target_id === item.element_id,
      )
      .map((relationship) => relationship.id);
    const ownedContinuations = (continuationsByTarget.get(item.id) ?? []).map(
      (continuation) => continuation.id,
    );
    if (
      !sameStrings(item.relationship_ids, incident) ||
      !sameStrings(item.continuation_ids, ownedContinuations)
    ) {
      invalid(`item ${item.id}`, "does not backlink its exact relationships");
    }
  }
  for (const continuation of continuations) {
    const incident = relationships
      .filter(
        (relationship) =>
          relationship.source_id === continuation.element_id ||
          relationship.target_id === continuation.element_id,
      )
      .map((relationship) => relationship.id);
    if (!sameStrings(continuation.relationship_ids, incident)) {
      invalid(`continuation ${continuation.id}`, "does not backlink its exact relationship");
    }
  }
  const cardinality = {
    contains: relationships.filter((value) => value.type === "contains").length,
    outline_parent_of: relationships.filter(
      (value) => value.type === "outline_parent_of",
    ).length,
    outline_next: relationships.filter((value) => value.type === "outline_next").length,
    outline_continuation_of: relationships.filter(
      (value) => value.type === "outline_continuation_of",
    ).length,
  };
  if (
    CARDINALITY_KEYS.some(
      (key) => group.relationship_cardinality[key] !== cardinality[key],
    ) ||
    cardinality.contains !== items.length ||
    cardinality.outline_parent_of !== items.filter((item) => item.parent_id !== null).length ||
    cardinality.outline_next !==
      [...siblingsByParent.values()].reduce(
        (total, siblings) => total + Math.max(siblings.length - 1, 0),
        0,
      ) ||
    cardinality.outline_continuation_of !== continuations.length
  ) {
    invalid("anchor.outline_group.relationship_cardinality", "does not match the graph");
  }
  if (
    group.relationship_ids.some((id) => !block.relationship_ids.includes(id))
  ) {
    invalid("anchor.outline_group.relationship_ids", "escapes canonical relationship custody");
  }

  let serializedSidecar: string;
  try {
    serializedSidecar = JSON.stringify({
      layout_outline_structure_projected: anchor.layout_outline_structure_projected,
      outline_policy: anchor.outline_policy,
      outline_group: group,
      outline_items: items,
      outline_continuations: continuations,
      relationships,
    });
  } catch {
    invalid("anchor", "cannot be measured as strict JSON");
  }
  if (byteLength(serializedSidecar!) > MAX_GROUP_BYTES) {
    invalid("anchor", "exceeds the complete public-group byte cap");
  }

  return {
    anchor,
    page,
    canonicalPage,
    block,
    group,
    items,
    continuations,
    relationships,
    itemSources,
    continuationSources,
  };
}

function assertUnique(values: readonly string[], path: string): void {
  if (new Set(values).size !== values.length) {
    invalid(path, "must be unique across the document");
  }
}

/**
 * Validate every P03-US07 anchor as one bounded document graph.
 *
 * No sidecars returns an empty map. Any partial, duplicate, excessive, or
 * canonically inconsistent sidecar returns null, allowing the UI to retain the
 * authoritative canonical block-text path without inferring hierarchy.
 */
export function readOutlineStructures(
  result: ParseResult,
  presentation: CanonicalPresentation,
): ReadonlyMap<string, ValidatedOutlineStructure> | null {
  try {
    const canonicalPageByIndex = new Map(
      presentation.pages.map((page) => [page.page_index, page]),
    );
    const blockById = new Map(
      presentation.pages.flatMap((page) =>
        page.blocks.map((block) => [block.id, block] as const),
      ),
    );
    const formOwnedElementIds = collectFormOwnedElementIds(result);
    const structures: ValidatedOutlineStructure[] = [];
    let totalNodes = 0;
    let totalRelationships = 0;

    for (const [pageArrayIndex, page] of result.pages.entries()) {
      const canonicalPage = canonicalPageByIndex.get(page.page_index);
      if (!canonicalPage) invalid(`result.pages[${pageArrayIndex}]`, "has no canonical page");
      assertUnique(
        page.items.map((item) => item.id),
        `result.pages[${pageArrayIndex}].items[].id`,
      );
      const anchors = page.items.filter((item) =>
        itemHasOutlineFields(item as unknown as JsonRecord),
      );
      if (anchors.length > MAX_GROUPS_PER_PAGE) {
        invalid(`result.pages[${pageArrayIndex}]`, "exceeds the group cap");
      }
      let pageNodes = 0;
      let pageRelationships = 0;
      for (const anchor of anchors) {
        const structure = validateAnchor(
          result,
          pageArrayIndex,
          page,
          canonicalPage,
          blockById,
          anchor,
          formOwnedElementIds,
        );
        structures.push(structure);
        pageNodes += structure.items.length;
        pageRelationships += structure.relationships.length;
      }
      if (
        pageNodes > MAX_NODES_PER_PAGE ||
        pageRelationships > MAX_RELATIONSHIPS_PER_PAGE
      ) {
        invalid(`result.pages[${pageArrayIndex}]`, "exceeds a page outline cap");
      }
      totalNodes += pageNodes;
      totalRelationships += pageRelationships;
    }
    if (
      structures.length > MAX_GROUPS_PER_DOCUMENT ||
      totalNodes > MAX_NODES_PER_DOCUMENT ||
      totalRelationships > MAX_RELATIONSHIPS_PER_DOCUMENT
    ) {
      invalid("result", "exceeds a document outline cap");
    }

    assertUnique(structures.map((value) => value.group.id), "outline group IDs");
    assertUnique(
      structures.map((value) => value.group.element_id),
      "outline group element IDs",
    );
    assertUnique(
      structures.flatMap((value) => value.items.map((item) => item.id)),
      "outline item IDs",
    );
    assertUnique(
      structures.flatMap((value) => value.items.map((item) => item.element_id)),
      "outline item element IDs",
    );
    assertUnique(
      structures.flatMap((value) => value.continuations.map((item) => item.id)),
      "outline continuation IDs",
    );
    assertUnique(
      structures.flatMap((value) =>
        value.continuations.map((item) => item.element_id),
      ),
      "outline continuation element IDs",
    );
    assertUnique(
      structures.flatMap((value) =>
        value.relationships.map((relationship) => relationship.id),
      ),
      "outline relationship IDs",
    );
    assertUnique(
      structures.flatMap((value) =>
        [
          ...value.items.map((item) => pathKey(item.source_public_path)),
          ...value.continuations.map((continuation) =>
            pathKey(continuation.source_public_path),
          ),
        ],
      ),
      "outline source paths",
    );
    assertUnique(
      structures.flatMap((value) => [
        value.group.id,
        ...value.items.map((item) => item.id),
        ...value.continuations.map((continuation) => continuation.id),
        ...value.relationships.map((relationship) => relationship.id),
      ]),
      "outline record IDs",
    );
    assertUnique(
      structures.flatMap((value) => [
        value.group.element_id,
        ...value.items.map((item) => item.element_id),
        ...value.continuations.map((continuation) => continuation.element_id),
      ]),
      "outline semantic element IDs",
    );
    assertUnique(
      structures.map((value) => value.block.id),
      "outline canonical block claims",
    );

    return new Map(structures.map((value) => [value.block.id, value]));
  } catch (error) {
    if (error instanceof InvalidOutlineStructure) return null;
    return null;
  }
}

function safePlainText(value: string): string {
  return Array.from(value)
    .map((character) => {
      const codePoint = character.codePointAt(0) ?? 0;
      return codePoint >= 0x20 &&
        codePoint !== 0x7f &&
        codePoint !== 0x2028 &&
        codePoint !== 0x2029
        ? character
        : "�";
    })
    .join("");
}

function defaultContinuationView(
  continuation: OutlineContinuation,
  source: ValidatedOutlineContinuationSource,
): ReactNode {
  const [header, ...body] = source.rows;
  return createElement(
    "div",
    { className: "parsed-table-wrap", "data-outline-continuation": continuation.id },
    createElement(
      "table",
      { className: "parsed-table" },
      createElement(
        "thead",
        null,
        createElement(
          "tr",
          null,
          header.map((cell, index) => createElement("th", { key: `h-${index}` }, cell)),
        ),
      ),
      createElement(
        "tbody",
        null,
        body.map((row, rowIndex) =>
          createElement(
            "tr",
            { key: `r-${rowIndex}` },
            row.map((cell, cellIndex) =>
              createElement("td", { key: `c-${rowIndex}-${cellIndex}` }, cell),
            ),
          ),
        ),
      ),
    ),
  );
}

export interface OutlineRenderOptions {
  renderBody?: (
    item: OutlineItem,
    source: ValidatedOutlineItemSource,
  ) => ReactNode | null;
  renderContinuation?: (
    continuation: OutlineContinuation,
    source: ValidatedOutlineContinuationSource,
  ) => ReactNode | null;
}

/** Render one validated graph through semantic React lists and safe text nodes. */
export function renderValidatedOutlineStructure(
  structure: ValidatedOutlineStructure,
  options: OutlineRenderOptions = {},
): ReactNode {
  const childrenByParent = new Map<string | null, OutlineItem[]>();
  for (const item of structure.items) {
    const children = childrenByParent.get(item.parent_id) ?? [];
    children.push(item);
    childrenByParent.set(item.parent_id, children);
  }
  const continuationsByTarget = new Map<string, OutlineContinuation[]>();
  for (const continuation of structure.continuations) {
    const values = continuationsByTarget.get(continuation.target_node_id) ?? [];
    values.push(continuation);
    continuationsByTarget.set(continuation.target_node_id, values);
  }
  const tag = structure.group.sequence_kind === "unordered" ? "ul" : "ol";
  const orderedType =
    structure.group.marker_style === "lower_alpha" ? "a" : undefined;

  const renderLevel = (parentId: string | null, root: boolean): ReactNode => {
    const listProperties: Record<string, unknown> = {
      className: root ? "parsed-list outline-list outline-list-root" : "outline-list",
    };
    if (root) {
      listProperties["data-outline-group"] = structure.group.id;
      listProperties["data-outline-policy"] = POLICY_ID;
    }
    if (tag === "ol") {
      listProperties.start = 1;
      if (orderedType) listProperties.type = orderedType;
    }
    return createElement(
      tag,
      listProperties,
      (childrenByParent.get(parentId) ?? []).map((item) => {
        const source = structure.itemSources.get(item.id)!;
        const customBody = options.renderBody?.(item, source) ?? null;
        const children = childrenByParent.has(item.id)
          ? renderLevel(item.id, false)
          : null;
        const continuations = (continuationsByTarget.get(item.id) ?? []).map(
          (continuation) => {
            const continuationSource = structure.continuationSources.get(
              continuation.id,
            )!;
            const custom =
              options.renderContinuation?.(continuation, continuationSource) ??
              null;
            return createElement(
              "div",
              {
                className: "outline-continuation",
                key: continuation.id,
                "data-outline-continuation": continuation.id,
              },
              custom ?? defaultContinuationView(continuation, continuationSource),
            );
          },
        );
        const properties: Record<string, unknown> = {
          key: item.id,
          "data-outline-item": item.id,
          "data-source-marker": item.raw_marker,
        };
        if (tag === "ol") properties.value = item.ordinal;
        return createElement(
          "li",
          properties,
          createElement(
            "span",
            { className: "outline-item-body" },
            customBody ?? safePlainText(item.body_text),
          ),
          children,
          continuations,
        );
      }),
    );
  };

  return renderLevel(null, true);
}
