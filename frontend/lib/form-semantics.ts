import { createElement, type ReactNode } from "react";

import type {
  CanonicalBlock,
  DocumentContentItem,
  FormBoundingBox,
  FormConfidenceDimension,
  FormControl,
  FormControlState,
  FormEvidenceMethod,
  FormField,
  FormGroup,
  FormKeyValuePair,
  FormLabel,
  FormRelationship,
  FormSemanticRecordBase,
  FormSourceObject,
  FormValueRegion,
  FormValueState,
  PageResult,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

const POLICY_ID = "p03-form-semantics-v1";
const MAX_ID_BYTES = 256;
const MAX_TEXT_BYTES = 16 * 1024;
const MAX_GROUP_BYTES = 256 * 1024;
const MAX_FIELDS = 128;
const MAX_LABELS = 256;
const MAX_VALUE_REGIONS = 128;
const MAX_CONTROLS = 256;
const MAX_KEY_VALUE_PAIRS = 32;
const MAX_CONCERNS = 13;
const MAX_RELATIONSHIPS = 32_768;

const COMMON_KEYS = [
  "id",
  "element_id",
  "page_index",
  "bbox",
  "evidence_methods",
  "source_objects",
  "confidence_dimensions",
  "concern_codes",
  "relationship_ids",
] as const;

const EVIDENCE_METHODS: FormEvidenceMethod[] = [
  "native",
  "vector",
  "embedded",
  "recovered",
  "derived",
];
const VALUE_STATES = new Set<FormValueState>([
  "empty",
  "present",
  "ambiguous",
  "not_applicable",
]);
const CONTROL_STATES = new Set<FormControlState>([
  "checked",
  "unchecked",
  "ambiguous",
  "not_applicable",
]);
const CONCERN_CODES = [
  "form_source_evidence_unavailable",
  "form_source_limit",
  "form_interactivity_unknown",
  "form_transform_unavailable",
  "form_candidate_limit",
  "form_relationship_limit",
  "form_geometry_ambiguous",
  "form_value_boundary_implicit",
  "form_value_state_ambiguous",
  "form_control_state_ambiguous",
  "form_table_ownership_ambiguous",
  "form_projection_failed_closed",
  "form_concerns_truncated",
] as const;
const RELATIONSHIP_TYPES = new Set<FormRelationship["type"]>([
  "contains",
  "label_of",
  "value_of",
  "control_of",
  "key_of",
  "form_overlay_of",
]);
const NEW_RELATIONSHIP_TYPES = new Set<FormRelationship["type"]>([
  "label_of",
  "value_of",
  "control_of",
  "key_of",
  "form_overlay_of",
]);
const UNAVAILABLE_REASONS = new Set([
  "not_calibrated",
  "not_applicable",
  "source_state_unavailable",
  "transcription_not_applicable",
]);
const SHA256 = /^[0-9a-f]{64}$/u;

class InvalidFormSemantics extends Error {}

function invalid(path: string, message: string): never {
  throw new InvalidFormSemantics(`${path} ${message}`);
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
  additional: readonly string[],
  path: string,
): void {
  const expected = new Set<string>([...COMMON_KEYS, ...additional]);
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

function exactObjectKeys(
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
  nonWhitespace = false,
): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    byteLength(value) > maximum ||
    (nonWhitespace && value.trim().length === 0)
  ) {
    invalid(path, `must be a bounded${nonWhitespace ? " non-whitespace" : ""} string`);
  }
  return value;
}

function integerAt(value: unknown, path: string, minimum = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < minimum) {
    invalid(path, `must be an integer at least ${minimum}`);
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
    invalid(path, `must contain ${minimum}–${maximum} entries`);
  }
  return value;
}

function uniqueStrings(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): string[] {
  const values = arrayAt(value, path, minimum, maximum).map((entry, index) =>
    boundedString(entry, `${path}[${index}]`),
  );
  if (new Set(values).size !== values.length) {
    invalid(path, "must not repeat IDs");
  }
  return values;
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

function validateBBox(
  value: unknown,
  page: PageResult,
  path: string,
): FormBoundingBox {
  const record = recordAt(value, path);
  exactObjectKeys(record, ["x", "y", "width", "height", "unit"], path);
  const x = finiteAt(record.x, `${path}.x`);
  const y = finiteAt(record.y, `${path}.y`);
  const width = finiteAt(record.width, `${path}.width`);
  const height = finiteAt(record.height, `${path}.height`);
  if (record.unit !== "pt" || x < 0 || y < 0 || width <= 0 || height <= 0) {
    invalid(path, "must be a positive top-left point bbox");
  }
  const pageWidth = finiteAt(page.page_width, "page.page_width");
  const pageHeight = finiteAt(page.page_height, "page.page_height");
  if (page.unit !== "pt" || pageWidth <= 0 || pageHeight <= 0) {
    invalid("page", "must use positive point dimensions for form geometry");
  }
  if (x + width > pageWidth + 0.001 || y + height > pageHeight + 0.001) {
    invalid(path, "must stay within its physical page");
  }
  return record as unknown as FormBoundingBox;
}

function validateSourceObject(value: unknown, path: string): FormSourceObject {
  const record = recordAt(value, path);
  if (record.kind === "character_range") {
    exactObjectKeys(record, ["kind", "start", "end"], path);
    const start = integerAt(record.start, `${path}.start`);
    const end = integerAt(record.end, `${path}.end`, 1);
    if (end <= start) invalid(path, "must contain a nonempty half-open range");
  } else if (record.kind === "line" || record.kind === "rect") {
    exactObjectKeys(record, ["kind", "index"], path);
    integerAt(record.index, `${path}.index`);
  } else if (
    record.kind === "field" ||
    record.kind === "widget" ||
    record.kind === "annotation"
  ) {
    exactObjectKeys(record, ["kind", "object_ref_digest"], path);
    const digest = boundedString(
      record.object_ref_digest,
      `${path}.object_ref_digest`,
      64,
    );
    if (!SHA256.test(digest)) invalid(path, "must use a lowercase SHA-256 digest");
  } else {
    invalid(`${path}.kind`, "is unsupported");
  }
  return record as unknown as FormSourceObject;
}

function validateConfidenceDimension(
  value: unknown,
  path: string,
): FormConfidenceDimension {
  const record = recordAt(value, path);
  if (Object.prototype.hasOwnProperty.call(record, "score")) {
    exactObjectKeys(record, ["score"], path);
    const score = finiteAt(record.score, `${path}.score`);
    if (score < 0 || score > 1) invalid(`${path}.score`, "must be in [0,1]");
  } else {
    exactObjectKeys(record, ["unavailable_reason"], path);
    if (!UNAVAILABLE_REASONS.has(record.unavailable_reason as string)) {
      invalid(`${path}.unavailable_reason`, "is unsupported");
    }
  }
  return record as unknown as FormConfidenceDimension;
}

function validateCommon(
  record: JsonRecord,
  additional: readonly string[],
  page: PageResult,
  path: string,
  relationshipMinimum: number,
  relationshipMaximum: number,
): void {
  exactKeys(record, additional, path);
  boundedString(record.id, `${path}.id`);
  boundedString(record.element_id, `${path}.element_id`);
  if (integerAt(record.page_index, `${path}.page_index`, 1) !== page.page_index) {
    invalid(`${path}.page_index`, "must match the physical result page");
  }
  validateBBox(record.bbox, page, `${path}.bbox`);

  const methods = uniqueStrings(
    record.evidence_methods,
    `${path}.evidence_methods`,
    1,
    EVIDENCE_METHODS.length,
  );
  const methodRanks = methods.map((method) =>
    EVIDENCE_METHODS.indexOf(method as FormEvidenceMethod),
  );
  if (
    methodRanks.some((rank) => rank < 0) ||
    methodRanks.some((rank, index) => index > 0 && rank <= methodRanks[index - 1])
  ) {
    invalid(`${path}.evidence_methods`, "must follow the closed canonical order");
  }

  const sourceObjects = arrayAt(
    record.source_objects,
    `${path}.source_objects`,
    1,
    64,
  );
  const sourceFingerprints = sourceObjects.map((entry, index) =>
    JSON.stringify(validateSourceObject(entry, `${path}.source_objects[${index}]`)),
  );
  if (new Set(sourceFingerprints).size !== sourceFingerprints.length) {
    invalid(`${path}.source_objects`, "must not repeat source references");
  }

  const dimensions = recordAt(
    record.confidence_dimensions,
    `${path}.confidence_dimensions`,
  );
  exactObjectKeys(
    dimensions,
    ["geometry", "role", "transcription", "state"],
    `${path}.confidence_dimensions`,
  );
  for (const key of ["geometry", "role", "transcription", "state"] as const) {
    validateConfidenceDimension(
      dimensions[key],
      `${path}.confidence_dimensions.${key}`,
    );
  }

  const concerns = uniqueStrings(
    record.concern_codes,
    `${path}.concern_codes`,
    0,
    MAX_CONCERNS,
  );
  const concernRanks = concerns.map((code) =>
    CONCERN_CODES.indexOf(code as (typeof CONCERN_CODES)[number]),
  );
  if (
    concernRanks.some((rank) => rank < 0) ||
    concernRanks.some((rank, index) => index > 0 && rank <= concernRanks[index - 1])
  ) {
    invalid(`${path}.concern_codes`, "must follow the concern-code order");
  }
  uniqueStrings(
    record.relationship_ids,
    `${path}.relationship_ids`,
    relationshipMinimum,
    relationshipMaximum,
  );
}

function validateValue(
  value: unknown,
  state: unknown,
  path: string,
  presentOnly = false,
): void {
  if (!VALUE_STATES.has(state as FormValueState)) {
    invalid(`${path}.value_state`, "is unsupported");
  }
  if (presentOnly && state !== "present") {
    invalid(`${path}.value_state`, "must equal present");
  }
  if (state === "present") {
    boundedString(value, `${path}.value`, MAX_TEXT_BYTES, true);
  } else if (value !== null) {
    invalid(`${path}.value`, "must be null for a non-present state");
  }
}

function validateGroup(
  value: unknown,
  page: PageResult,
  path: string,
): FormGroup {
  const record = recordAt(value, path);
  validateCommon(
    record,
    [
      "group_key",
      "status",
      "interactivity",
      "canonical_mode",
      "anchor_public_item_id",
      "anchor_element_id",
      "anchor_relationship_ids",
      "contributor_public_item_ids",
      "contributor_element_ids",
      "field_ids",
      "label_ids",
      "value_region_ids",
      "control_ids",
      "key_value_pair_ids",
    ],
    page,
    path,
    1,
    2_816,
  );
  boundedString(record.group_key, `${path}.group_key`);
  if (record.status !== "resolved" && record.status !== "unresolved") {
    invalid(`${path}.status`, "is unsupported");
  }
  if (
    !["none", "static", "interactive", "mixed", "unknown"].includes(
      record.interactivity as string,
    )
  ) {
    invalid(`${path}.interactivity`, "is unsupported");
  }
  if (record.canonical_mode !== "inert" && record.canonical_mode !== "replace") {
    invalid(`${path}.canonical_mode`, "is unsupported");
  }
  const anchorPublicId = boundedString(
    record.anchor_public_item_id,
    `${path}.anchor_public_item_id`,
  );
  const anchorElementId = boundedString(
    record.anchor_element_id,
    `${path}.anchor_element_id`,
  );
  uniqueStrings(record.anchor_relationship_ids, `${path}.anchor_relationship_ids`, 0, 1);
  const contributorPublicIds = uniqueStrings(
    record.contributor_public_item_ids,
    `${path}.contributor_public_item_ids`,
    1,
    64,
  );
  const contributorElementIds = uniqueStrings(
    record.contributor_element_ids,
    `${path}.contributor_element_ids`,
    1,
    64,
  );
  if (contributorPublicIds.length !== contributorElementIds.length) {
    invalid(path, "must pair public and internal contributors one-to-one");
  }
  const publicAnchorIndex = contributorPublicIds.indexOf(anchorPublicId);
  const elementAnchorIndex = contributorElementIds.indexOf(anchorElementId);
  if (publicAnchorIndex < 0 || publicAnchorIndex !== elementAnchorIndex) {
    invalid(path, "must pair the public and internal anchor at one source-order index");
  }
  if (contributorElementIds.includes(record.element_id as string)) {
    invalid(`${path}.element_id`, "must be disjoint from predecessor contributors");
  }
  const fieldIds = uniqueStrings(record.field_ids, `${path}.field_ids`, 0, MAX_FIELDS);
  uniqueStrings(record.label_ids, `${path}.label_ids`, 0, MAX_LABELS);
  uniqueStrings(
    record.value_region_ids,
    `${path}.value_region_ids`,
    0,
    MAX_VALUE_REGIONS,
  );
  const controlIds = uniqueStrings(
    record.control_ids,
    `${path}.control_ids`,
    0,
    MAX_CONTROLS,
  );
  const pairIds = uniqueStrings(
    record.key_value_pair_ids,
    `${path}.key_value_pair_ids`,
    0,
    MAX_KEY_VALUE_PAIRS,
  );
  if (!fieldIds.length && !controlIds.length && !pairIds.length) {
    invalid(path, "must own fields, controls, or key-value pairs");
  }
  if (pairIds.length && (fieldIds.length || controlIds.length)) {
    invalid(path, "must not mix key-value pairs with form fields or controls");
  }
  return record as unknown as FormGroup;
}

function validateField(value: unknown, page: PageResult, path: string): FormField {
  const record = recordAt(value, path);
  validateCommon(
    record,
    [
      "group_id",
      "field_key",
      "label_ids",
      "value_region_id",
      "control_ids",
      "value",
      "value_state",
    ],
    page,
    path,
    4,
    323,
  );
  boundedString(record.group_id, `${path}.group_id`);
  boundedString(record.field_key, `${path}.field_key`);
  uniqueStrings(record.label_ids, `${path}.label_ids`, 1, 64);
  boundedString(record.value_region_id, `${path}.value_region_id`);
  uniqueStrings(record.control_ids, `${path}.control_ids`, 0, MAX_CONTROLS);
  validateValue(record.value, record.value_state, path);
  return record as unknown as FormField;
}

function validateLabel(value: unknown, page: PageResult, path: string): FormLabel {
  const record = recordAt(value, path);
  validateCommon(
    record,
    ["group_id", "label_role", "text", "raw_text", "label_of_ids", "key_of_ids"],
    page,
    path,
    2,
    257,
  );
  boundedString(record.group_id, `${path}.group_id`);
  if (!["field", "group", "control", "key"].includes(record.label_role as string)) {
    invalid(`${path}.label_role`, "is unsupported");
  }
  const text = boundedString(record.text, `${path}.text`, MAX_TEXT_BYTES, true);
  const rawText = boundedString(record.raw_text, `${path}.raw_text`, MAX_TEXT_BYTES, true);
  const repairedRaw = new Map([
    ["PROJECT", "PRO- JECT"],
    ["WC STATUTORY LIMITS", "WC STATU- TORY LIMITS"],
    ["OTHER", "OTH- ER"],
  ]).get(text);
  if (rawText !== text && rawText !== repairedRaw) {
    invalid(`${path}.raw_text`, "is not an authorized source-preserving repair");
  }
  const role = record.label_role;
  const labelOf = uniqueStrings(
    record.label_of_ids,
    `${path}.label_of_ids`,
    role === "key" ? 0 : 1,
    role === "field" ? MAX_CONTROLS : role === "key" ? 0 : 1,
  );
  const keyOf = uniqueStrings(
    record.key_of_ids,
    `${path}.key_of_ids`,
    role === "key" ? 1 : 0,
    role === "key" ? 1 : 0,
  );
  if (role === "key" ? labelOf.length !== 0 : keyOf.length !== 0) {
    invalid(path, "has inconsistent label/key relationship arrays");
  }
  return record as unknown as FormLabel;
}

function validateValueRegion(
  value: unknown,
  page: PageResult,
  path: string,
): FormValueRegion {
  const record = recordAt(value, path);
  validateCommon(
    record,
    ["group_id", "owner_id", "excluded_label_ids", "value", "value_state"],
    page,
    path,
    2,
    2,
  );
  boundedString(record.group_id, `${path}.group_id`);
  boundedString(record.owner_id, `${path}.owner_id`);
  uniqueStrings(record.excluded_label_ids, `${path}.excluded_label_ids`, 0, 64);
  validateValue(record.value, record.value_state, path);
  return record as unknown as FormValueRegion;
}

function validateControl(
  value: unknown,
  page: PageResult,
  path: string,
): FormControl {
  const record = recordAt(value, path);
  validateCommon(
    record,
    ["group_id", "owner_field_id", "label_id", "control_type", "state", "origin"],
    page,
    path,
    2,
    3,
  );
  boundedString(record.group_id, `${path}.group_id`);
  if (record.owner_field_id !== null) {
    boundedString(record.owner_field_id, `${path}.owner_field_id`);
  }
  if (record.label_id !== null) boundedString(record.label_id, `${path}.label_id`);
  if (record.control_type !== "checkbox" && record.control_type !== "radio") {
    invalid(`${path}.control_type`, "is unsupported");
  }
  if (!CONTROL_STATES.has(record.state as FormControlState)) {
    invalid(`${path}.state`, "is unsupported");
  }
  if (record.origin !== "static_vector" && record.origin !== "interactive_widget") {
    invalid(`${path}.origin`, "is unsupported");
  }
  return record as unknown as FormControl;
}

function validatePair(
  value: unknown,
  page: PageResult,
  path: string,
): FormKeyValuePair {
  const record = recordAt(value, path);
  validateCommon(
    record,
    [
      "group_id",
      "pair_key",
      "key_label_id",
      "value_region_id",
      "key",
      "value",
      "value_state",
      "key_source_item_id",
      "value_source_item_id",
    ],
    page,
    path,
    5,
    5,
  );
  boundedString(record.group_id, `${path}.group_id`);
  boundedString(record.pair_key, `${path}.pair_key`);
  boundedString(record.key_label_id, `${path}.key_label_id`);
  boundedString(record.value_region_id, `${path}.value_region_id`);
  boundedString(record.key, `${path}.key`, MAX_TEXT_BYTES, true);
  validateValue(record.value, record.value_state, path, true);
  boundedString(record.key_source_item_id, `${path}.key_source_item_id`);
  boundedString(
    record.value_source_item_id,
    `${path}.value_source_item_id`,
  );
  return record as unknown as FormKeyValuePair;
}

function requiredArray<T>(
  value: unknown,
  path: string,
  expectedLength: number,
  maximum: number,
  parser: (entry: unknown, entryPath: string) => T,
): T[] {
  const entries = arrayAt(value, path, 1, maximum);
  if (entries.length !== expectedLength) {
    invalid(path, "must match the group ID-list cardinality");
  }
  return entries.map((entry, index) => parser(entry, `${path}[${index}]`));
}

function optionalClassArray<T>(
  item: DocumentContentItem,
  property: keyof DocumentContentItem,
  ids: readonly string[],
  maximum: number,
  parser: (entry: unknown, entryPath: string) => T,
): T[] {
  const value = item[property];
  if (!ids.length) {
    if (value !== undefined) invalid(`item.${String(property)}`, "must be omitted when empty");
    return [];
  }
  return requiredArray(
    value,
    `item.${String(property)}`,
    ids.length,
    maximum,
    parser,
  );
}

function indexById<T extends { id: string }>(values: readonly T[], path: string): Map<string, T> {
  const result = new Map<string, T>();
  for (const value of values) {
    if (result.has(value.id)) invalid(path, `repeats record ID ${JSON.stringify(value.id)}`);
    result.set(value.id, value);
  }
  return result;
}

function validateRelationship(value: unknown, path: string): FormRelationship {
  const record = recordAt(value, path);
  exactObjectKeys(
    record,
    ["id", "type", "source_id", "target_id", "evidence_ids", "canonical_inert"],
    path,
  );
  boundedString(record.id, `${path}.id`);
  if (!RELATIONSHIP_TYPES.has(record.type as FormRelationship["type"])) {
    invalid(`${path}.type`, "is unsupported");
  }
  boundedString(record.source_id, `${path}.source_id`);
  boundedString(record.target_id, `${path}.target_id`);
  if (record.source_id === record.target_id) invalid(path, "cannot be a self-edge");
  uniqueStrings(record.evidence_ids, `${path}.evidence_ids`, 0, 64);
  if (record.canonical_inert !== true) invalid(`${path}.canonical_inert`, "must be true");
  return record as unknown as FormRelationship;
}

interface ExpectedEdge {
  type: FormRelationship["type"];
  source: string;
  target: string;
}

function edgeKey(edge: ExpectedEdge): string {
  return `${edge.type}\u0000${edge.source}\u0000${edge.target}`;
}

function relationshipEdgeKey(relationship: FormRelationship): string {
  return edgeKey({
    type: relationship.type,
    source: relationship.source_id,
    target: relationship.target_id,
  });
}

export interface ValidatedFormSemantics {
  anchor: DocumentContentItem;
  group: FormGroup;
  fields: FormField[];
  labels: FormLabel[];
  valueRegions: FormValueRegion[];
  controls: FormControl[];
  keyValuePairs: FormKeyValuePair[];
  relationships: FormRelationship[];
}

function validateAnchor(
  anchor: DocumentContentItem,
  page: PageResult,
  block: CanonicalBlock,
): ValidatedFormSemantics {
  if (anchor.layout_forms_projected !== true || anchor.form_policy !== POLICY_ID) {
    invalid("item", "does not carry the exact form projection marker and policy");
  }
  const group = validateGroup(anchor.form_group, page, "item.form_group");
  if (
    group.anchor_public_item_id !== anchor.id ||
    group.anchor_element_id !== block.primary_element_id
  ) {
    invalid("item.form_group", "does not resolve to this public/canonical anchor");
  }
  const pageItemIds = new Set(page.items.map((item) => item.id));
  if (pageItemIds.size !== page.items.length) invalid("page.items", "must have unique IDs");
  if (group.contributor_public_item_ids.some((id) => !pageItemIds.has(id))) {
    invalid("item.form_group.contributor_public_item_ids", "does not resolve on this page");
  }
  const canonicalContributorElementIds = [
    group.anchor_element_id,
    ...group.contributor_element_ids.filter(
      (elementId) => elementId !== group.anchor_element_id,
    ),
  ];
  if (
    group.canonical_mode === "replace" &&
    !sameStrings(canonicalContributorElementIds, block.contributing_element_ids)
  ) {
    invalid(
      "item.form_group.contributor_element_ids",
      "does not match the anchor-first canonical claim",
    );
  }

  const fields = optionalClassArray(
    anchor,
    "form_fields",
    group.field_ids,
    MAX_FIELDS,
    (entry, path) => validateField(entry, page, path),
  );
  const labels = optionalClassArray(
    anchor,
    "form_labels",
    group.label_ids,
    MAX_LABELS,
    (entry, path) => validateLabel(entry, page, path),
  );
  const valueRegions = optionalClassArray(
    anchor,
    "form_value_regions",
    group.value_region_ids,
    MAX_VALUE_REGIONS,
    (entry, path) => validateValueRegion(entry, page, path),
  );
  const controls = optionalClassArray(
    anchor,
    "form_controls",
    group.control_ids,
    MAX_CONTROLS,
    (entry, path) => validateControl(entry, page, path),
  );
  const pairs = optionalClassArray(
    anchor,
    "form_key_value_pairs",
    group.key_value_pair_ids,
    MAX_KEY_VALUE_PAIRS,
    (entry, path) => validatePair(entry, page, path),
  );

  for (const [actual, expected, path] of [
    [fields.map((entry) => entry.id), group.field_ids, "form_fields"],
    [labels.map((entry) => entry.id), group.label_ids, "form_labels"],
    [valueRegions.map((entry) => entry.id), group.value_region_ids, "form_value_regions"],
    [controls.map((entry) => entry.id), group.control_ids, "form_controls"],
    [pairs.map((entry) => entry.id), group.key_value_pair_ids, "form_key_value_pairs"],
  ] as const) {
    if (!sameStrings(actual, expected)) invalid(`item.${path}`, "is not in group-declared order");
  }

  const allRecords: FormSemanticRecordBase[] = [
    group,
    ...fields,
    ...labels,
    ...valueRegions,
    ...controls,
    ...pairs,
  ];
  const recordById = indexById(allRecords, "item form records");
  const elementById = new Map<string, FormSemanticRecordBase>();
  const contributorElements = new Set(group.contributor_element_ids);
  for (const record of allRecords) {
    if (elementById.has(record.element_id)) invalid("item form records", "repeat an element ID");
    if (contributorElements.has(record.element_id)) {
      invalid("item form records", "reuse a predecessor element as a semantic node");
    }
    elementById.set(record.element_id, record);
  }

  const fieldById = indexById(fields, "item.form_fields");
  const labelById = indexById(labels, "item.form_labels");
  const regionById = indexById(valueRegions, "item.form_value_regions");
  const controlById = indexById(controls, "item.form_controls");
  const pairById = indexById(pairs, "item.form_key_value_pairs");
  const expectedEdges: ExpectedEdge[] = [];
  const expect = (type: FormRelationship["type"], source: string, target: string) => {
    expectedEdges.push({ type, source, target });
  };

  for (const field of fields) {
    if (field.group_id !== group.id) invalid(`field ${field.id}`, "has the wrong group");
    const region = regionById.get(field.value_region_id);
    if (!region || region.owner_id !== field.id) invalid(`field ${field.id}`, "has no exact value region");
    const linkedLabelIds = labels
      .filter(
        (label) =>
          label.label_role === "field" && label.label_of_ids.includes(field.id),
      )
      .map((label) => label.id);
    if (!sameStrings(field.label_ids, linkedLabelIds)) {
      invalid(`field ${field.id}`, "does not list exactly its field labels");
    }
    if (region.value !== field.value || region.value_state !== field.value_state) {
      invalid(`field ${field.id}`, "disagrees with its value region");
    }
    if (!sameStrings(region.excluded_label_ids, field.label_ids)) {
      invalid(`field ${field.id}`, "does not exclude exactly its owned labels");
    }
    if (
      !sameStrings(
        field.control_ids,
        controls.filter((entry) => entry.owner_field_id === field.id).map((entry) => entry.id),
      )
    ) {
      invalid(`field ${field.id}`, "does not list exactly its owned controls");
    }
    expect("contains", group.element_id, field.element_id);
    expect("contains", field.element_id, region.element_id);
  }

  for (const label of labels) {
    if (label.group_id !== group.id) invalid(`label ${label.id}`, "has the wrong group");
    if (label.label_role === "key") {
      const pair = pairById.get(label.key_of_ids[0]);
      if (!pair || pair.key_label_id !== label.id || pair.key !== label.text) {
        invalid(`label ${label.id}`, "does not resolve its exact key-value pair");
      }
      expect("key_of", label.element_id, pair.element_id);
    } else {
      expect("contains", group.element_id, label.element_id);
      for (const targetId of label.label_of_ids) {
        const target = recordById.get(targetId);
        const validTarget =
          (label.label_role === "group" && target === group) ||
          (label.label_role === "field" && fieldById.has(targetId)) ||
          (label.label_role === "control" && controlById.has(targetId));
        if (!target || !validTarget) invalid(`label ${label.id}`, "has a role-incompatible target");
        expect("label_of", label.element_id, target.element_id);
      }
    }
  }

  for (const region of valueRegions) {
    if (region.group_id !== group.id) invalid(`value region ${region.id}`, "has the wrong group");
    const owner = fieldById.get(region.owner_id) ?? pairById.get(region.owner_id);
    if (!owner) invalid(`value region ${region.id}`, "has no field or pair owner");
    if (pairById.has(region.owner_id)) {
      const pair = pairById.get(region.owner_id)!;
      if (
        region.excluded_label_ids.length ||
        region.value_state !== "present" ||
        region.value !== pair.value ||
        pair.value_region_id !== region.id
      ) {
        invalid(`value region ${region.id}`, "disagrees with its present pair value");
      }
    }
    expect("value_of", region.element_id, owner.element_id);
  }

  for (const control of controls) {
    if (control.group_id !== group.id) invalid(`control ${control.id}`, "has the wrong group");
    const owner = control.owner_field_id === null ? group : fieldById.get(control.owner_field_id);
    if (!owner) invalid(`control ${control.id}`, "has no valid owner");
    const linkedLabelIds = labels
      .filter(
        (label) =>
          label.label_role === "control" &&
          sameStrings(label.label_of_ids, [control.id]),
      )
      .map((label) => label.id);
    const declaredLabelIds = control.label_id === null ? [] : [control.label_id];
    if (!sameStrings(declaredLabelIds, linkedLabelIds)) {
      invalid(`control ${control.id}`, "does not resolve exactly its control label");
    }
    expect("contains", group.element_id, control.element_id);
    expect("control_of", control.element_id, owner.element_id);
  }

  for (const pair of pairs) {
    if (pair.group_id !== group.id) invalid(`pair ${pair.id}`, "has the wrong group");
    const label = labelById.get(pair.key_label_id);
    const region = regionById.get(pair.value_region_id);
    if (!label || label.label_role !== "key" || !region || region.owner_id !== pair.id) {
      invalid(`pair ${pair.id}`, "does not resolve its key label and value region");
    }
    if (
      !group.contributor_public_item_ids.includes(pair.key_source_item_id) ||
      !group.contributor_public_item_ids.includes(pair.value_source_item_id)
    ) {
      invalid(`pair ${pair.id}`, "uses source items outside canonical custody");
    }
    expect("contains", group.element_id, pair.element_id);
    expect("contains", pair.element_id, label.element_id);
    expect("contains", pair.element_id, region.element_id);
  }

  const rawRelationships = Array.isArray(anchor.relationships) ? anchor.relationships : [];
  const requiredRelationshipIds = new Set(
    allRecords.flatMap((record) => record.relationship_ids).concat(group.anchor_relationship_ids),
  );
  const relationships: FormRelationship[] = [];
  const seenRelationshipIds = new Set<string>();
  for (const [index, value] of rawRelationships.entries()) {
    if (!isRecord(value)) continue;
    const id = typeof value.id === "string" ? value.id : "";
    const type = typeof value.type === "string" ? value.type : "";
    const isUS06 =
      requiredRelationshipIds.has(id) ||
      NEW_RELATIONSHIP_TYPES.has(type as FormRelationship["type"]) ||
      (type === "contains" && value.canonical_inert === true);
    if (!isUS06) continue;
    const relationship = validateRelationship(value, `item.relationships[${index}]`);
    if (seenRelationshipIds.has(relationship.id)) invalid("item.relationships", "repeats an ID");
    seenRelationshipIds.add(relationship.id);
    relationships.push(relationship);
  }
  if (relationships.length > MAX_RELATIONSHIPS) invalid("item.relationships", "is oversized");
  if (
    requiredRelationshipIds.size !== relationships.length ||
    relationships.some((entry) => !requiredRelationshipIds.has(entry.id))
  ) {
    invalid("item.relationships", "does not match semantic backlinks exactly");
  }
  const expectedKeys = expectedEdges.map(edgeKey);
  if (group.anchor_relationship_ids.length) {
    expectedKeys.push(
      edgeKey({
        type: "form_overlay_of",
        source: group.element_id,
        target: group.anchor_element_id,
      }),
    );
  }
  const actualKeys = relationships.map(relationshipEdgeKey);
  if (
    new Set(expectedKeys).size !== expectedKeys.length ||
    !sameStrings(actualKeys.slice().sort(), expectedKeys.slice().sort())
  ) {
    invalid("item.relationships", "does not match the closed semantic graph");
  }
  for (const record of allRecords) {
    const incident = relationships
      .filter(
        (relationship) =>
          relationship.source_id === record.element_id ||
          relationship.target_id === record.element_id,
      )
      .map((relationship) => relationship.id);
    if (!sameStrings(record.relationship_ids, incident)) {
      invalid(`record ${record.id}.relationship_ids`, "does not match incident descriptors");
    }
  }
  const overlays = relationships.filter((entry) => entry.type === "form_overlay_of");
  if (
    !sameStrings(group.anchor_relationship_ids, overlays.map((entry) => entry.id)) ||
    overlays.some(
      (entry) => entry.source_id !== group.element_id || entry.target_id !== group.anchor_element_id,
    )
  ) {
    invalid("item.form_group.anchor_relationship_ids", "does not backlink its exact overlay");
  }

  const compactSidecar = JSON.stringify({
    layout_forms_projected: anchor.layout_forms_projected,
    form_policy: anchor.form_policy,
    form_group: group,
    ...(fields.length ? { form_fields: fields } : {}),
    ...(labels.length ? { form_labels: labels } : {}),
    ...(valueRegions.length ? { form_value_regions: valueRegions } : {}),
    ...(controls.length ? { form_controls: controls } : {}),
    ...(pairs.length ? { form_key_value_pairs: pairs } : {}),
    relationships,
  });
  if (byteLength(compactSidecar) > MAX_GROUP_BYTES) invalid("item", "has an oversized form sidecar");

  return {
    anchor,
    group,
    fields,
    labels,
    valueRegions,
    controls,
    keyValuePairs: pairs,
    relationships,
  };
}

/**
 * Resolve one complete form sidecar for a canonical block.
 *
 * Any duplicate, malformed, oversized, cross-page, or endpoint-inconsistent
 * candidate returns null so the caller can render authoritative canonical text.
 */
export function readFormSemanticsForCanonicalBlock(
  block: CanonicalBlock,
  page: PageResult,
): ValidatedFormSemantics | null {
  const candidates = page.items.filter(
    (item) =>
      isRecord(item.form_group) &&
      item.form_group.anchor_element_id === block.primary_element_id,
  );
  if (candidates.length !== 1) return null;
  try {
    return validateAnchor(candidates[0], page, block);
  } catch (error) {
    if (error instanceof InvalidFormSemantics) return null;
    return null;
  }
}

function sourceAttributes(record: FormSemanticRecordBase): Record<string, string | number> {
  return {
    "data-source-page-index": record.page_index,
    "data-source-bbox": [
      record.bbox.x,
      record.bbox.y,
      record.bbox.width,
      record.bbox.height,
    ].join(","),
  };
}

function fieldStateText(field: FormField): string {
  if (field.value_state === "present") return field.value ?? "";
  // A source-visible blank is state, not user content. Keep it on the node as
  // data-value-state without inserting synthetic words into the rendered UI.
  if (field.value_state === "empty") return "";
  if (field.value_state === "ambiguous") return "Value ambiguous; no value emitted";
  return "Not applicable in source";
}

const STATIC_PARTIES_BASE_LABELS = new Map([
  ["producer", "PRODUCER"],
  ["insured", "INSURED"],
  ["contact-name", "CONTACT NAME:"],
  ["phone", "PHONE (A/C, NO, EXT):"],
  ["fax", "FAX (A/C, NO):"],
  ["email-address", "E-MAIL ADDRESS:"],
]);
const STATIC_INSURER_FIELD = /^insurer-([a-z])-(name|naic)$/u;

function normalizedFormLabel(value: string): string {
  return value.replace(/\s+/gu, " ").trim().toUpperCase();
}

function bboxContains(outer: FormBoundingBox, inner: FormBoundingBox): boolean {
  const tolerance = 0.5;
  return (
    inner.x >= outer.x - tolerance &&
    inner.y >= outer.y - tolerance &&
    inner.x + inner.width <= outer.x + outer.width + tolerance &&
    inner.y + inner.height <= outer.y + outer.height + tolerance
  );
}

function sameMembers(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
}

interface StaticPartiesPresentation {
  fieldsByKey: Map<string, FormField>;
  labelsById: Map<string, FormLabel>;
  baseLabels: Map<string, FormLabel>;
  groupLabel: FormLabel;
  sharedLabel: FormLabel;
  insurerRows: string[];
}

/** Recheck the backend's source-complete replacement contract in the UI. */
function completeStaticPartiesPresentation(
  semantics: ValidatedFormSemantics,
): StaticPartiesPresentation | null {
  const { group, fields, labels, controls, keyValuePairs } = semantics;
  if (
    group.group_key !== "parties-and-insurers" ||
    group.status !== "resolved" ||
    group.interactivity !== "static" ||
    group.canonical_mode !== "replace" ||
    group.concern_codes.length !== 0 ||
    controls.length !== 0 ||
    keyValuePairs.length !== 0
  ) {
    return null;
  }

  const fieldsByKey = new Map(fields.map((field) => [field.field_key, field]));
  if (fieldsByKey.size !== fields.length) return null;
  const insurerRoles = new Map<string, Set<string>>();
  for (const field of fields) {
    if (STATIC_PARTIES_BASE_LABELS.has(field.field_key)) continue;
    const match = STATIC_INSURER_FIELD.exec(field.field_key);
    if (!match) return null;
    const roles = insurerRoles.get(match[1]) ?? new Set<string>();
    roles.add(match[2]);
    insurerRoles.set(match[1], roles);
  }
  const insurerRows = [...insurerRoles.keys()].sort();
  if (
    [...STATIC_PARTIES_BASE_LABELS.keys()].some((key) => !fieldsByKey.has(key)) ||
    insurerRows.length < 2 ||
    insurerRows.length > 26 ||
    [...insurerRoles.values()].some(
      (roles) => roles.size !== 2 || !roles.has("name") || !roles.has("naic"),
    ) ||
    fields.some(
      (field) =>
        field.value !== null ||
        field.value_state !== "empty" ||
        field.concern_codes.length !== 0 ||
        !field.evidence_methods.includes("vector") ||
        !bboxContains(group.bbox, field.bbox),
    )
  ) {
    return null;
  }

  const labelsById = new Map(labels.map((label) => [label.id, label]));
  if (
    labelsById.size !== labels.length ||
    labels.some(
      (label) =>
        label.concern_codes.length !== 0 ||
        !label.evidence_methods.includes("native") ||
        !bboxContains(group.bbox, label.bbox),
    )
  ) {
    return null;
  }

  const baseLabels = new Map<string, FormLabel>();
  const usedLabelIds = new Set<string>();
  for (const [fieldKey, expectedText] of STATIC_PARTIES_BASE_LABELS) {
    const field = fieldsByKey.get(fieldKey);
    if (!field || field.label_ids.length !== 1) return null;
    const label = labelsById.get(field.label_ids[0]);
    if (
      !label ||
      label.label_role !== "field" ||
      !sameStrings(label.label_of_ids, [field.id]) ||
      normalizedFormLabel(label.text) !== expectedText
    ) {
      return null;
    }
    baseLabels.set(fieldKey, label);
    usedLabelIds.add(label.id);
  }

  const groupLabels = labels.filter((label) => label.label_role === "group");
  const sharedLabels = labels.filter(
    (label) => normalizedFormLabel(label.text) === "NAIC #",
  );
  if (
    groupLabels.length !== 1 ||
    sharedLabels.length !== 1 ||
    !sameStrings(groupLabels[0].label_of_ids, [group.id]) ||
    normalizedFormLabel(groupLabels[0].text) !==
      "INSURER(S) AFFORDING COVERAGE"
  ) {
    return null;
  }
  const groupLabel = groupLabels[0];
  const sharedLabel = sharedLabels[0];
  usedLabelIds.add(groupLabel.id);
  usedLabelIds.add(sharedLabel.id);

  const expectedSharedTargets: string[] = [];
  let priorTop: number | null = null;
  for (const row of insurerRows) {
    const name = fieldsByKey.get(`insurer-${row}-name`);
    const naic = fieldsByKey.get(`insurer-${row}-naic`);
    if (!name || !naic) return null;
    const commonLabelIds = name.label_ids.filter((id) => naic.label_ids.includes(id));
    if (commonLabelIds.length !== 1 || !naic.label_ids.includes(sharedLabel.id)) {
      return null;
    }
    const rowLabel = labelsById.get(commonLabelIds[0]);
    if (
      !rowLabel ||
      rowLabel.label_role !== "field" ||
      !sameMembers(rowLabel.label_of_ids, [name.id, naic.id]) ||
      normalizedFormLabel(rowLabel.text) !== `INSURER ${row.toUpperCase()} :` ||
      !sameStrings(name.label_ids, [rowLabel.id]) ||
      !sameMembers(naic.label_ids, [rowLabel.id, sharedLabel.id]) ||
      Math.abs(name.bbox.y - naic.bbox.y) > 1 ||
      name.bbox.x >= naic.bbox.x ||
      (priorTop !== null && name.bbox.y <= priorTop)
    ) {
      return null;
    }
    priorTop = name.bbox.y;
    expectedSharedTargets.push(naic.id);
    usedLabelIds.add(rowLabel.id);
  }

  const producer = fieldsByKey.get("producer")!;
  const insured = fieldsByKey.get("insured")!;
  const contact = fieldsByKey.get("contact-name")!;
  const phone = fieldsByKey.get("phone")!;
  const fax = fieldsByKey.get("fax")!;
  const email = fieldsByKey.get("email-address")!;
  if (
    !sameMembers(sharedLabel.label_of_ids, expectedSharedTargets) ||
    usedLabelIds.size !== labelsById.size ||
    producer.bbox.x >= contact.bbox.x ||
    insured.bbox.x >= contact.bbox.x ||
    producer.bbox.y >= insured.bbox.y ||
    !(contact.bbox.y <= phone.bbox.y && phone.bbox.y <= email.bbox.y) ||
    Math.abs(phone.bbox.y - fax.bbox.y) > 1 ||
    phone.bbox.x >= fax.bbox.x ||
    groupLabel.bbox.y >= fieldsByKey.get(`insurer-${insurerRows[0]}-name`)!.bbox.y ||
    sharedLabel.bbox.y >= fieldsByKey.get(`insurer-${insurerRows[0]}-name`)!.bbox.y
  ) {
    return null;
  }

  return { fieldsByKey, labelsById, baseLabels, groupLabel, sharedLabel, insurerRows };
}

function renderCompleteStaticParties(
  semantics: ValidatedFormSemantics,
  options: { overlay?: boolean },
): ReactNode | null {
  const presentation = completeStaticPartiesPresentation(semantics);
  if (!presentation) return null;
  const { fieldsByKey, labelsById, baseLabels, groupLabel, sharedLabel, insurerRows } =
    presentation;
  const label = (key: string) => baseLabels.get(key)!.text;
  const blank = (key: string, attributes: Record<string, unknown> = {}) =>
    createElement("td", { key, "data-value-state": "empty", ...attributes });
  const rowLabel = (row: string): FormLabel => {
    const name = fieldsByKey.get(`insurer-${row}-name`)!;
    const naic = fieldsByKey.get(`insurer-${row}-naic`)!;
    return labelsById.get(name.label_ids.find((id) => naic.label_ids.includes(id))!)!;
  };

  const rows: ReactNode[] = [
    createElement(
      "tr",
      { key: "contact" },
      createElement("th", { rowSpan: 5, scope: "row" }, label("producer")),
      blank("producer-value", { rowSpan: 5 }),
      createElement("th", { scope: "row" }, label("contact-name")),
      blank("contact-value", { colSpan: 3 }),
    ),
    createElement(
      "tr",
      { key: "phone-fax" },
      createElement("th", { scope: "row" }, label("phone")),
      blank("phone-value"),
      createElement("th", { scope: "row" }, label("fax")),
      blank("fax-value"),
    ),
    createElement(
      "tr",
      { key: "email" },
      createElement("th", { scope: "row" }, label("email-address")),
      blank("email-value", { colSpan: 3 }),
    ),
    createElement(
      "tr",
      { key: "insurer-heading" },
      createElement("th", { colSpan: 2, scope: "col" }, groupLabel.text),
      createElement("th", { colSpan: 2, scope: "col" }, sharedLabel.text),
    ),
  ];
  insurerRows.forEach((row, index) => {
    const cells: ReactNode[] = [];
    if (index === 1) {
      cells.push(
        createElement(
          "th",
          { key: "insured-label", rowSpan: insurerRows.length - 1, scope: "row" },
          label("insured"),
        ),
        blank("insured-value", { rowSpan: insurerRows.length - 1 }),
      );
    }
    cells.push(
      createElement("th", { key: `${row}-label`, scope: "row" }, rowLabel(row).text),
      blank(`${row}-name-value`),
      blank(`${row}-naic-value`, { colSpan: 2 }),
    );
    rows.push(createElement("tr", { key: `insurer-${row}` }, ...cells));
  });

  return createElement(
    "aside",
    {
      className: `form-semantics-panel${options.overlay ? " form-semantics-overlay-panel" : ""}`,
      "data-form-canonical-mode": semantics.group.canonical_mode,
      "data-form-group-key": semantics.group.group_key,
      ...sourceAttributes(semantics.group),
    },
    createElement(
      "div",
      { className: "parsed-table-wrap form-parties-table-wrap" },
      createElement(
        "table",
        { className: "parsed-table form-parties-table", "aria-label": "Parties and insurers" },
        createElement("tbody", null, ...rows),
      ),
    ),
  );
}

function controlStateText(control: FormControl): string {
  if (control.control_type === "radio") {
    if (control.state === "checked") return "Selected";
    if (control.state === "unchecked") return "Unselected";
  }
  if (control.state === "checked") return "Checked";
  if (control.state === "unchecked") return "Unchecked";
  if (control.state === "ambiguous") return "State ambiguous";
  return "Not applicable";
}

/** Render a validated sidecar with semantic, read-only React nodes. */
export function renderValidatedFormSemantics(
  semantics: ValidatedFormSemantics,
  options: { overlay?: boolean } = {},
): ReactNode {
  const staticParties = renderCompleteStaticParties(semantics, options);
  if (staticParties) return staticParties;
  const labels = new Map(semantics.labels.map((label) => [label.id, label]));
  const sections: ReactNode[] = [];

  if (semantics.keyValuePairs.length) {
    sections.push(
      createElement(
        "section",
        { className: "form-semantics-section", key: "pairs", "aria-label": "Key-value details" },
        createElement("h3", { className: "form-semantics-heading" }, "Key-value details"),
        createElement(
          "dl",
          { className: "form-semantics-list form-key-value-list" },
          semantics.keyValuePairs.map((pair) =>
            createElement(
              "div",
              { className: "form-semantics-row", key: pair.id, ...sourceAttributes(pair) },
              createElement("dt", null, pair.key),
              createElement("dd", null, pair.value),
            ),
          ),
        ),
      ),
    );
  }

  if (semantics.fields.length) {
    sections.push(
      createElement(
        "section",
        { className: "form-semantics-section", key: "fields", "aria-label": "Form fields" },
        createElement("h3", { className: "form-semantics-heading" }, "Form fields"),
        createElement(
          "dl",
          { className: "form-semantics-list form-field-list" },
          semantics.fields.map((field) =>
            createElement(
              "div",
              { className: "form-semantics-row", key: field.id, ...sourceAttributes(field) },
              createElement(
                "dt",
                null,
                field.label_ids.map((id) => labels.get(id)?.text ?? "").join(" · "),
              ),
              createElement(
                "dd",
                { "data-value-state": field.value_state },
                fieldStateText(field),
              ),
            ),
          ),
        ),
      ),
    );
  }

  if (semantics.controls.length) {
    sections.push(
      createElement(
        "section",
        {
          className: "form-semantics-section form-controls-section",
          key: "controls",
          "aria-label": "Read-only form controls",
        },
        createElement(
          "div",
          { className: "form-semantics-heading-row" },
          createElement("h3", { className: "form-semantics-heading" }, "Form controls"),
          createElement("span", { className: "form-readonly-badge" }, "Read-only"),
        ),
        createElement(
          "ul",
          { className: "form-control-list" },
          semantics.controls.map((control) => {
            const label = control.label_id === null ? null : labels.get(control.label_id);
            const fallback =
              control.control_type === "radio" ? "Unlabeled radio" : "Unlabeled checkbox";
            return createElement(
              "li",
              {
                className: "form-control-row",
                key: control.id,
                "data-control-type": control.control_type,
                "data-control-state": control.state,
                ...sourceAttributes(control),
              },
              createElement("span", { className: "form-control-label" }, label?.text ?? fallback),
              createElement("span", { className: "form-control-state" }, controlStateText(control)),
            );
          }),
        ),
      ),
    );
  }

  return createElement(
    "aside",
    {
      className: `form-semantics-panel${options.overlay ? " form-semantics-overlay-panel" : ""}`,
      "data-form-canonical-mode": semantics.group.canonical_mode,
      "data-form-group-key": semantics.group.group_key,
      ...sourceAttributes(semantics.group),
    },
    sections,
  );
}
