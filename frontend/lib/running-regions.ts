import type {
  CanonicalBlock,
  CanonicalPage,
  CanonicalPresentation,
  CanonicalView,
  DocumentContentItem,
  PageIdentity,
  PagePresentationView,
  PageResult,
  ParseResult,
  RunningRegionBoundingBox,
  RunningRegionConcern,
  RunningRegionConcernCode,
  RunningRegionDescriptor,
  RunningRegionsProcessingStatus,
  RunningRegionsProcessingSummary,
} from "./types.ts";
import { pythonStrip } from "./canonical-presentation.ts";

type JsonRecord = Record<string, unknown>;

const POLICY_ID = "p03-running-regions-page-identity-v1";
const MAX_PAGES = 100;
const MAX_ID_BYTES = 512;
const MAX_LABEL_BYTES = 256;
const MAX_VISIBLE_TEXT_BYTES = 512;
const MAX_EXTRACTED_CONTRIBUTION_BYTES = 4 * 1024;
const MAX_PATH_SEGMENTS = 16;
const MAX_REFERENCES = 64;
const MAX_REGIONS_PER_PAGE = 64;
const MAX_REGIONS_PER_DOCUMENT = 2_048;
const MAX_EXTRACTED_REGIONS_PER_PAGE = 8;
const MAX_EXTRACTED_REGIONS_PER_DOCUMENT = 64;
const MAX_REPETITION_GROUPS_PER_DOCUMENT = 2_048;
const MAX_CONCERNS_PER_PAGE = 64;
const MAX_CONCERNS_PER_DOCUMENT = 256;
const MAX_CANDIDATES_PER_DOCUMENT = 10_000;
const MAX_COMPARISONS_PER_DOCUMENT = 65_536;
const MAX_PAGE_IDENTITY_BYTES = 64 * 1_024;
const MAX_RUNNING_DESCRIPTOR_BYTES = 256 * 1_024;
const MAX_STAGE_DURATION_MS = 2_000;
const GEOMETRY_EPSILON = 0.001;

const SUMMARY_KEYS = [
  "policy_id",
  "status",
  "reason",
  "source_page_count",
  "identity_count",
  "detected_label_count",
  "embedded_label_count",
  "legacy_fallback_count",
  "candidate_count",
  "comparison_count",
  "running_region_count",
  "header_count",
  "footer_count",
  "top_navigation_count",
  "bottom_navigation_count",
  "concern_count",
  "extraction_ms",
  "projection_ms",
  "total_ms",
] as const;
const IDENTITY_KEYS = [
  "schema_version",
  "policy_id",
  "page_id",
  "physical_page_index",
  "embedded_label",
  "detected_printed_label",
  "visible_text",
  "display_label",
  "display_source",
  "evidence_bbox",
  "evidence_source",
  "confidence",
  "concern_codes",
] as const;
const EVIDENCE_SOURCE_KEYS = [
  "method",
  "reader",
  "page_index",
  "public_item_id",
  "public_path",
  "element_id",
  "bbox_id",
  "evidence_ids",
  "source_object_ids",
] as const;
const DESCRIPTOR_KEYS = [
  "id",
  "page_id",
  "physical_page_index",
  "role",
  "canonical_scope",
  "source_public_item_id",
  "source_public_path",
  "source_element_id",
  "predecessor_type",
  "predecessor_item_sha256",
  "bbox_id",
  "bbox",
  "evidence_ids",
  "source_object_ids",
  "source_method",
  "repetition_group_id",
  "repetition_page_indexes",
  "confidence",
  "concern_codes",
  "canonical_block_id",
] as const;
const BBOX_KEYS = ["x", "y", "width", "height", "unit"] as const;
const PUBLIC_ITEM_BBOX_KEYS = [...BBOX_KEYS, "w", "h"] as const;
const CONFIDENCE_KEYS = ["scope", "score", "unavailable_reason"] as const;
const PROJECTED_CONCERN_KEYS = [
  "code",
  "source_ref",
  "count",
  "cap",
  "exception_class",
] as const;
const NONPROJECTING_CONCERN_KEYS = ["code"] as const;

const STATUS_REASONS: Record<
  RunningRegionsProcessingStatus,
  ReadonlySet<string | null>
> = {
  projected: new Set([null]),
  unavailable: new Set([
    "running_region_source_evidence_unavailable",
    "running_region_source_limit",
  ]),
  not_applicable: new Set(["running_region_input_not_applicable"]),
  failed_closed: new Set(["running_region_projection_failed_closed"]),
};
const CONCERN_CODES = [
  "running_region_source_evidence_unavailable",
  "running_region_source_limit",
  "running_region_candidate_limit",
  "running_region_geometry_ambiguous",
  "running_region_repetition_ambiguous",
  "running_region_navigation_ambiguous",
  "running_region_ownership_conflict",
  "page_identity_embedded_label_invalid",
  "page_identity_detected_label_ambiguous",
  "page_identity_source_conflict",
  "page_identity_display_unsafe",
  "running_region_canonical_custody_invalid",
  "running_region_projection_failed_closed",
  "running_region_concerns_truncated",
] as const satisfies readonly RunningRegionConcernCode[];
const PAGE_IDENTITY_CONCERNS = new Set<RunningRegionConcernCode>([
  "running_region_source_evidence_unavailable",
  "running_region_source_limit",
  "running_region_candidate_limit",
  "running_region_geometry_ambiguous",
  "running_region_ownership_conflict",
  "page_identity_embedded_label_invalid",
  "page_identity_detected_label_ambiguous",
  "page_identity_source_conflict",
  "page_identity_display_unsafe",
  "running_region_projection_failed_closed",
  "running_region_concerns_truncated",
]);
const ROLES = {
  header: { type: "header", scope: "header" },
  footer: { type: "footer", scope: "footer" },
  navigation_top: { type: "header", scope: "header" },
  navigation_bottom: { type: "footer", scope: "footer" },
} as const;
const SOURCE_METHODS = new Set([
  "trusted_layout_role",
  "cross_page_repetition",
  "boundary_navigation",
  "printed_label_boundary",
  "effective_boundary_cluster",
  "extracted_source_contribution",
]);
const SHA256 = /^[0-9a-f]{64}$/u;
const EXCEPTION_CLASS = /^[A-Za-z_][A-Za-z0-9_.]{0,127}$/u;
const DETECTED_INTEGER = /^[1-9][0-9]{0,5}$/u;
const LEGACY_SOURCE_ID = /^configured-predecessor:[0-9a-f]{64}:page:([1-9][0-9]*):page_label$/u;

export class RunningRegionValidationError extends Error {
  readonly code = "invalid_running_regions";

  constructor(message: string) {
    super(`Invalid running regions: ${message}`);
    this.name = "RunningRegionValidationError";
  }
}

function invalid(path: string, message: string): never {
  throw new RunningRegionValidationError(`${path} ${message}`);
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

function enforceJsonByteCap(
  value: unknown,
  path: string,
  maximum: number,
): void {
  let serialized: string | undefined;
  try {
    serialized = JSON.stringify(value);
  } catch {
    invalid(path, "must be strict JSON");
  }
  if (serialized === undefined || byteLength(serialized) > maximum) {
    invalid(path, `exceeds its ${maximum}-byte JSON cap`);
  }
}

function boundedString(
  value: unknown,
  path: string,
  maximum = MAX_ID_BYTES,
): string {
  if (
    typeof value !== "string" ||
    value.length === 0 ||
    byteLength(value) > maximum
  ) {
    invalid(path, "must be a bounded nonempty string");
  }
  return value;
}

function safeSemanticString(
  value: unknown,
  path: string,
  maximum = MAX_LABEL_BYTES,
): string {
  const text = boundedString(value, path, maximum);
  if (text !== pythonStrip(text) || text.normalize("NFC") !== text) {
    invalid(path, "must be trimmed NFC text");
  }
  for (const character of text) {
    if (!/[\p{L}\p{N} ._\-:/|()]/u.test(character)) {
      invalid(path, "contains a forbidden character");
    }
    const point = character.codePointAt(0) ?? 0;
    if (
      (point >= 0xfdd0 && point <= 0xfdef) ||
      (point & 0xffff) === 0xfffe ||
      (point & 0xffff) === 0xffff
    ) {
      invalid(path, "contains a Unicode noncharacter");
    }
  }
  return text;
}

function boundedNfcText(
  value: unknown,
  path: string,
  maximum: number,
): string {
  const text = boundedString(value, path, maximum);
  if (text !== pythonStrip(text) || text.normalize("NFC") !== text) {
    invalid(path, "must be trimmed NFC text");
  }
  for (let index = 0; index < text.length; index += 1) {
    const codeUnit = text.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const next = text.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        invalid(path, "contains an unpaired surrogate");
      }
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      invalid(path, "contains an unpaired surrogate");
    }
  }
  return text;
}

function positiveInteger(
  value: unknown,
  path: string,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < 1 ||
    (value as number) > maximum
  ) {
    invalid(path, `must be an integer in [1, ${maximum}]`);
  }
  return value as number;
}

function countAt(
  value: unknown,
  path: string,
  maximum = Number.MAX_SAFE_INTEGER,
): number {
  if (
    !Number.isSafeInteger(value) ||
    (value as number) < 0 ||
    (value as number) > maximum
  ) {
    invalid(path, `must be an integer in [0, ${maximum}]`);
  }
  return value as number;
}

function durationAt(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    invalid(path, "must be a finite nonnegative duration");
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
  const values = arrayAt(value, path, minimum, maximum).map((entry, index) =>
    boundedString(entry, `${path}[${index}]`),
  );
  if (new Set(values).size !== values.length) {
    invalid(path, "must not repeat strings");
  }
  return values;
}

function strictPath(value: unknown, path: string): Array<string | number> {
  return arrayAt(value, path, 0, MAX_PATH_SEGMENTS).map((entry, index) => {
    if (typeof entry === "string") {
      return boundedString(entry, `${path}[${index}]`);
    }
    if (!Number.isSafeInteger(entry) || (entry as number) < 0) {
      invalid(`${path}[${index}]`, "must be a string or nonnegative integer");
    }
    return entry as number;
  });
}

function sameSequence<T>(left: readonly T[], right: readonly T[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function sameJson(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) && Array.isArray(right)) {
    return (
      left.length === right.length &&
      left.every((value, index) => sameJson(value, right[index]))
    );
  }
  if (isRecord(left) && isRecord(right)) {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return (
      sameSequence(leftKeys, rightKeys) &&
      leftKeys.every((key) => sameJson(left[key], right[key]))
    );
  }
  return false;
}

function resolvePublicPath(result: ParseResult, path: readonly (string | number)[]): unknown {
  let current: unknown = result;
  for (const part of path) {
    if (typeof part === "string") {
      if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, part)) {
        invalid("source_public_path", "does not resolve");
      }
      current = current[part];
    } else {
      if (!Array.isArray(current) || part >= current.length) {
        invalid("source_public_path", "does not resolve");
      }
      current = current[part];
    }
  }
  return current;
}

function validateBBox(
  value: unknown,
  page: PageResult,
  path: string,
): RunningRegionBoundingBox {
  const record = recordAt(value, path);
  exactKeys(record, BBOX_KEYS, path);
  const x = durationAt(record.x, `${path}.x`);
  const y = durationAt(record.y, `${path}.y`);
  const width = durationAt(record.width, `${path}.width`);
  const height = durationAt(record.height, `${path}.height`);
  if (
    record.unit !== "pt" ||
    page.unit !== "pt" ||
    width <= 0 ||
    height <= 0 ||
    !Number.isFinite(page.page_width) ||
    !Number.isFinite(page.page_height) ||
    page.page_width <= 0 ||
    page.page_height <= 0 ||
    x + width > page.page_width + GEOMETRY_EPSILON ||
    y + height > page.page_height + GEOMETRY_EPSILON
  ) {
    invalid(path, "must be a positive in-page point bbox");
  }
  return { x, y, width, height, unit: "pt" };
}

function validatePublicItemBBox(
  value: unknown,
  page: PageResult,
  path: string,
): RunningRegionBoundingBox {
  const record = recordAt(value, path);
  const allowed = new Set<string>(PUBLIC_ITEM_BBOX_KEYS);
  for (const key of BBOX_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(record, key)) {
      invalid(path, `is missing ${JSON.stringify(key)}`);
    }
  }
  for (const key of Object.keys(record)) {
    if (!allowed.has(key)) {
      invalid(path, `contains unsupported field ${JSON.stringify(key)}`);
    }
  }

  const bbox = validateBBox(
    {
      x: record.x,
      y: record.y,
      width: record.width,
      height: record.height,
      unit: record.unit,
    },
    page,
    path,
  );
  for (const [alias, canonical] of [
    ["w", "width"],
    ["h", "height"],
  ] as const) {
    if (!Object.prototype.hasOwnProperty.call(record, alias)) continue;
    const aliasValue = durationAt(record[alias], `${path}.${alias}`);
    if (aliasValue !== bbox[canonical]) {
      invalid(`${path}.${alias}`, `must exactly match ${canonical}`);
    }
  }
  return bbox;
}

function sameBBox(left: RunningRegionBoundingBox, right: RunningRegionBoundingBox): boolean {
  return (
    Math.abs(left.x - right.x) <= GEOMETRY_EPSILON &&
    Math.abs(left.y - right.y) <= GEOMETRY_EPSILON &&
    Math.abs(left.width - right.width) <= GEOMETRY_EPSILON &&
    Math.abs(left.height - right.height) <= GEOMETRY_EPSILON &&
    left.unit === right.unit
  );
}

function validateConfidence(value: unknown, path: string): JsonRecord {
  const record = recordAt(value, path);
  exactKeys(record, CONFIDENCE_KEYS, path);
  if (record.scope === "deterministic_rule" || record.scope === "source_metadata") {
    const score = durationAt(record.score, `${path}.score`);
    if (score > 1 || record.unavailable_reason !== null) {
      invalid(path, "has inconsistent scored confidence");
    }
  } else if (record.scope === "unavailable") {
    if (
      record.score !== null ||
      ![
        "page_identity_source_unavailable",
        "page_identity_display_fallback_physical",
      ].includes(record.unavailable_reason as string)
    ) {
      invalid(path, "has inconsistent unavailable confidence");
    }
  } else {
    invalid(`${path}.scope`, "is unsupported");
  }
  return record;
}

function validateConcernCodes(
  value: unknown,
  path: string,
  allowed: ReadonlySet<RunningRegionConcernCode> = new Set(CONCERN_CODES),
): RunningRegionConcernCode[] {
  const values = uniqueStrings(value, path, 0, MAX_CONCERNS_PER_PAGE);
  if (
    values.some(
      (entry) =>
        !CONCERN_CODES.includes(entry as RunningRegionConcernCode) ||
        !allowed.has(entry as RunningRegionConcernCode),
    ) ||
    !sameSequence(values, [...values].sort())
  ) {
    invalid(path, "must follow the closed concern order");
  }
  return values as RunningRegionConcernCode[];
}

function normalizeDetected(value: string, path: string): string {
  const compact = value.trim().replace(/\s+/gu, " ");
  let match = /^Page\s+([1-9][0-9]{0,5})\s+of\s+([1-9][0-9]{0,5})$/iu.exec(compact);
  if (match) {
    if (Number(match[1]) > Number(match[2])) invalid(path, "has an invalid total");
    return `${match[1]} of ${match[2]}`;
  }
  match = /^PAGE\s*\|\s*([1-9][0-9]{0,5})$/iu.exec(compact);
  if (match) return match[1];
  match = /^([1-9][0-9]{0,5})\s*\/\s*([1-9][0-9]{0,5})$/u.exec(compact);
  if (match) {
    if (Number(match[1]) > Number(match[2])) invalid(path, "has an invalid total");
    return `${match[1]}/${match[2]}`;
  }
  if (DETECTED_INTEGER.test(compact)) return compact;
  invalid(path, "does not use the printed-label grammar");
}

function validateEvidenceSource(
  value: unknown,
  identity: JsonRecord,
  page: PageResult,
  result: ParseResult,
  path: string,
): void {
  const record = recordAt(value, path);
  exactKeys(record, EVIDENCE_SOURCE_KEYS, path);
  if (positiveInteger(record.page_index, `${path}.page_index`, MAX_PAGES) !== page.page_index) {
    invalid(`${path}.page_index`, "must match the physical page");
  }
  const publicPath = strictPath(record.public_path, `${path}.public_path`);
  const evidenceIds = uniqueStrings(record.evidence_ids, `${path}.evidence_ids`, 0, MAX_REFERENCES);
  const sourceIds = uniqueStrings(record.source_object_ids, `${path}.source_object_ids`, 0, MAX_REFERENCES);
  const nullableIds = [record.public_item_id, record.element_id, record.bbox_id];
  const allNull = nullableIds.every((entry) => entry === null);
  const allStrings = nullableIds.every((entry) => typeof entry === "string" && entry.length > 0);
  const displaySource = identity.display_source;
  const hasDetectedEvidence = identity.detected_printed_label !== null;

  if (hasDetectedEvidence) {
    if (
      record.method !== "native_printed_label" ||
      record.reader !== "pdfplumber" ||
      evidenceIds.length !== 1 ||
      sourceIds.length === 0 ||
      (!allNull && !allStrings)
    ) {
      invalid(path, "has invalid detected-label custody");
    }
    if (allNull) {
      if (publicPath.length !== 0) invalid(path, "has a detached nonempty path");
    } else {
      for (const [index, key] of nullableIds.entries()) {
        boundedString(key, `${path}.${["public_item_id", "element_id", "bbox_id"][index]}`);
      }
      if (
        publicPath.length !== 4 ||
        publicPath[0] !== "pages" ||
        publicPath[1] !== page.page_index - 1 ||
        publicPath[2] !== "items" ||
        typeof publicPath[3] !== "number"
      ) {
        invalid(`${path}.public_path`, "is not the detected-label page item path");
      }
      const owner = resolvePublicPath(result, publicPath);
      if (!isRecord(owner) || owner.id !== record.public_item_id) {
        invalid(path, "does not resolve its public owner");
      }
      const ownerBBox = validatePublicItemBBox(
        owner.bbox,
        page,
        `${path}.public_owner.bbox`,
      );
      const evidenceBBox = validateBBox(identity.evidence_bbox, page, `${path}.identity_bbox`);
      if (!sameBBox(ownerBBox, evidenceBBox)) {
        invalid(path, "does not match its public owner's bbox");
      }
      const ownerText = owner.value === null || owner.value === undefined
        ? owner.md
        : owner.value;
      if (typeof ownerText !== "string" || ownerText !== identity.visible_text) {
        invalid(path, "does not match its public owner's visible text");
      }
    }
  } else {
    if (!allNull || publicPath.length !== 0) invalid(path, "fallback binding must be detached");
    if (displaySource === "embedded_label") {
      if (
        record.method !== "embedded_pdf_label" ||
        record.reader !== "pypdfium2" ||
        evidenceIds.length !== 1 ||
        sourceIds.length === 0
      ) {
        invalid(path, "has invalid embedded-label custody");
      }
    } else if (displaySource === "legacy_display_fallback") {
      if (
        record.method !== "legacy_display_fallback" ||
        record.reader !== "configured_predecessor" ||
        evidenceIds.length !== 0 ||
        sourceIds.length !== 1 ||
        !LEGACY_SOURCE_ID.test(sourceIds[0]) ||
        Number(LEGACY_SOURCE_ID.exec(sourceIds[0])?.[1]) !== page.page_index ||
        sourceIds[0] !==
          `configured-predecessor:${result.document.sha256}:page:${page.page_index}:page_label`
      ) {
        invalid(path, "has invalid legacy-label custody");
      }
    } else if (displaySource === "physical") {
      if (
        record.method !== "physical_page_index" ||
        record.reader !== "configured_predecessor" ||
        evidenceIds.length !== 0 ||
        sourceIds.length !== 0
      ) {
        invalid(path, "has invalid physical fallback custody");
      }
    } else {
      invalid(`${path}.method`, "does not match display_source");
    }
  }
}

function validatePageIdentity(
  value: unknown,
  page: PageResult,
  canonicalPage: CanonicalPage,
  result: ParseResult,
  path: string,
): PageIdentity {
  const record = recordAt(value, path);
  exactKeys(record, IDENTITY_KEYS, path);
  if (record.schema_version !== "1.0" || record.policy_id !== POLICY_ID) {
    invalid(path, "uses an unsupported identity contract");
  }
  const pageId = boundedString(record.page_id, `${path}.page_id`);
  if (
    pageId !== canonicalPage.page_id ||
    positiveInteger(record.physical_page_index, `${path}.physical_page_index`, MAX_PAGES) !== page.page_index
  ) {
    invalid(path, "does not match its public/canonical page");
  }
  const embedded = record.embedded_label === null
    ? null
    : safeSemanticString(record.embedded_label, `${path}.embedded_label`);
  const detected = record.detected_printed_label === null
    ? null
    : safeSemanticString(record.detected_printed_label, `${path}.detected_printed_label`);
  const visible = record.visible_text === null
    ? null
    : safeSemanticString(record.visible_text, `${path}.visible_text`, MAX_VISIBLE_TEXT_BYTES);
  if ((detected === null) !== (visible === null)) {
    invalid(path, "has inconsistent detected/visible nullability");
  }
  if (detected !== null && normalizeDetected(visible as string, `${path}.visible_text`) !== detected) {
    invalid(path, "has inconsistent detected-label normalization");
  }
  const display = safeSemanticString(record.display_label, `${path}.display_label`);
  const source = record.display_source;
  const concerns = validateConcernCodes(record.concern_codes, `${path}.concern_codes`, PAGE_IDENTITY_CONCERNS);
  const conflict = embedded !== null && detected !== null && embedded !== detected;
  if (conflict) {
    if (source !== "embedded_label" || display !== embedded || !concerns.includes("page_identity_source_conflict")) {
      invalid(path, "has invalid detected/embedded conflict selection");
    }
  } else if (detected !== null) {
    if (source !== "detected_printed_label" || display !== detected) invalid(path, "does not select detected identity");
    if (concerns.includes("page_identity_detected_label_ambiguous")) {
      invalid(path, "promotes an ambiguous detected label");
    }
  } else if (embedded !== null) {
    if (source !== "embedded_label" || display !== embedded) invalid(path, "does not select embedded identity");
  } else {
    if (typeof page.page_label !== "string") {
      invalid("page.page_label", "must be a string");
    }
    let safeLegacy: string | null = null;
    if (page.page_label.length > 0) {
      try {
        safeLegacy = safeSemanticString(page.page_label, "page.page_label");
      } catch (error) {
        if (!(error instanceof RunningRegionValidationError)) throw error;
      }
    }
    if (safeLegacy !== null) {
      if (source !== "legacy_display_fallback" || display !== safeLegacy) {
        invalid(path, "does not select the safe legacy label");
      }
    } else {
      if (source !== "physical" || display !== String(page.page_index)) {
        invalid(path, "does not select physical identity");
      }
      if (
        page.page_label.length > 0 &&
        !concerns.includes("page_identity_display_unsafe")
      ) {
        invalid(path, "uses an unsafe legacy fallback without its concern");
      }
    }
  }
  if (detected !== null) {
    validateBBox(record.evidence_bbox, page, `${path}.evidence_bbox`);
  } else if (record.evidence_bbox !== null) {
    invalid(`${path}.evidence_bbox`, "must be null without a detected label");
  }
  const confidence = validateConfidence(record.confidence, `${path}.confidence`);
  const expectedConfidenceScope =
    source === "embedded_label"
      ? "source_metadata"
      : source === "detected_printed_label"
        ? "deterministic_rule"
        : "unavailable";
  if (
    confidence.scope !== expectedConfidenceScope ||
    (expectedConfidenceScope === "unavailable"
      ? confidence.score !== null ||
        confidence.unavailable_reason !==
          (source === "physical"
            ? "page_identity_display_fallback_physical"
            : "page_identity_source_unavailable")
      : confidence.score !== 1 || confidence.unavailable_reason !== null)
  ) {
    invalid(`${path}.confidence`, "does not match the selected display source");
  }
  validateEvidenceSource(record.evidence_source, record, page, result, `${path}.evidence_source`);
  enforceJsonByteCap(record, path, MAX_PAGE_IDENTITY_BYTES);
  return record as unknown as PageIdentity;
}

function validateSummary(value: unknown): RunningRegionsProcessingSummary {
  const record = recordAt(value, "processing.running_regions");
  exactKeys(record, SUMMARY_KEYS, "processing.running_regions");
  if (record.policy_id !== POLICY_ID || !(record.status as string in STATUS_REASONS)) {
    invalid("processing.running_regions", "has an unsupported policy/status");
  }
  const status = record.status as RunningRegionsProcessingStatus;
  if (!STATUS_REASONS[status].has(record.reason as string | null)) {
    invalid("processing.running_regions.reason", "does not match status");
  }
  const maximums: Record<string, number> = {
    source_page_count: MAX_PAGES,
    identity_count: MAX_PAGES,
    detected_label_count: MAX_PAGES,
    embedded_label_count: MAX_PAGES,
    legacy_fallback_count: MAX_PAGES,
    candidate_count: MAX_CANDIDATES_PER_DOCUMENT,
    comparison_count: MAX_COMPARISONS_PER_DOCUMENT,
    running_region_count: MAX_REGIONS_PER_DOCUMENT,
    header_count: MAX_REGIONS_PER_DOCUMENT,
    footer_count: MAX_REGIONS_PER_DOCUMENT,
    top_navigation_count: MAX_REGIONS_PER_DOCUMENT,
    bottom_navigation_count: MAX_REGIONS_PER_DOCUMENT,
    concern_count: MAX_CONCERNS_PER_DOCUMENT,
  };
  const counts: Record<string, number> = {};
  for (const [key, maximum] of Object.entries(maximums)) {
    counts[key] = countAt(record[key], `processing.running_regions.${key}`, maximum);
  }
  if (status === "projected") {
    if (
      counts.source_page_count !== counts.identity_count ||
      counts.detected_label_count + counts.embedded_label_count + counts.legacy_fallback_count !== counts.identity_count ||
      counts.header_count + counts.footer_count + counts.top_navigation_count + counts.bottom_navigation_count !== counts.running_region_count
    ) {
      invalid("processing.running_regions", "has inconsistent projected counts");
    }
  } else if (
    Object.entries(counts).some(([key, value]) => key !== "concern_count" && value !== 0) ||
    counts.concern_count > 1
  ) {
    invalid("processing.running_regions", "has nonprojecting feature counts");
  }
  const extraction = durationAt(record.extraction_ms, "processing.running_regions.extraction_ms");
  const projection = durationAt(record.projection_ms, "processing.running_regions.projection_ms");
  const total = durationAt(record.total_ms, "processing.running_regions.total_ms");
  if (extraction > MAX_STAGE_DURATION_MS || projection > MAX_STAGE_DURATION_MS) {
    invalid("processing.running_regions", "exceeds a stage deadline");
  }
  if (total !== Math.round((extraction + projection) * 1_000) / 1_000) {
    invalid("processing.running_regions.total_ms", "does not equal extraction + projection");
  }
  return record as unknown as RunningRegionsProcessingSummary;
}

function validateProjectedConcerns(
  result: ParseResult,
  expectedCount: number,
  pageCount: number,
): RunningRegionConcern[] {
  const raw = Object.prototype.hasOwnProperty.call(result, "running_region_concerns")
    ? result.running_region_concerns
    : [];
  const values = arrayAt(raw, "running_region_concerns", expectedCount, expectedCount);
  const identities: string[] = [];
  const concerns = values.map((value, index) => {
    const path = `running_region_concerns[${index}]`;
    const record = recordAt(value, path);
    exactKeys(record, PROJECTED_CONCERN_KEYS, path);
    const code = boundedString(record.code, `${path}.code`) as RunningRegionConcernCode;
    if (!CONCERN_CODES.includes(code)) invalid(`${path}.code`, "is unsupported");
    const sourceRef = boundedString(record.source_ref, `${path}.source_ref`);
    if (sourceRef !== "document") {
      const match = /^page:([1-9][0-9]*)$/u.exec(sourceRef);
      if (!match || Number(match[1]) > pageCount) invalid(`${path}.source_ref`, "is outside the document");
    }
    const cap = positiveInteger(record.cap, `${path}.cap`);
    if (cap !== (sourceRef === "document" ? MAX_CONCERNS_PER_DOCUMENT : MAX_CONCERNS_PER_PAGE)) {
      invalid(`${path}.cap`, "does not match its concern scope");
    }
    const count = positiveInteger(record.count, `${path}.count`, cap);
    const exceptionClass = record.exception_class;
    if (exceptionClass !== null && (typeof exceptionClass !== "string" || !EXCEPTION_CLASS.test(exceptionClass))) {
      invalid(`${path}.exception_class`, "is invalid");
    }
    void count;
    identities.push(`${sourceRef}\u0000${code}`);
    return record as unknown as RunningRegionConcern;
  });
  if (
    new Set(identities).size !== identities.length ||
    identities.some((value, index) => index > 0 && value <= identities[index - 1])
  ) {
    invalid("running_region_concerns", "must be unique and sorted");
  }
  return concerns;
}

function validateNonprojectingConcern(result: ParseResult, summary: RunningRegionsProcessingSummary): void {
  const has = Object.prototype.hasOwnProperty.call(result, "running_region_concerns");
  if (!has) {
    if (summary.concern_count !== 0) {
      invalid("running_region_concerns", "is missing its nonprojecting concern");
    }
    return;
  }
  const values = arrayAt(result.running_region_concerns, "running_region_concerns", 1, 1);
  if (summary.concern_count !== 1) {
    invalid("running_region_concerns", "does not match the nonprojecting summary");
  }
  const record = recordAt(values[0], "running_region_concerns[0]");
  exactKeys(record, NONPROJECTING_CONCERN_KEYS, "running_region_concerns[0]");
  const allowed = summary.status === "unavailable"
    ? new Set([summary.reason])
    : summary.status === "failed_closed"
      ? new Set([
          "running_region_canonical_custody_invalid",
          "running_region_projection_failed_closed",
        ])
      : new Set<string | null>();
  if (!allowed.has(record.code as string)) invalid("running_region_concerns[0].code", "does not match status");
}

function hasRunningSidecar(value: unknown): boolean {
  if (Array.isArray(value)) return value.some(hasRunningSidecar);
  if (!isRecord(value)) return false;
  if (
    Object.prototype.hasOwnProperty.call(value, "page_identity") ||
    Object.prototype.hasOwnProperty.call(value, "layout_running_region_projected") ||
    Object.prototype.hasOwnProperty.call(value, "running_region_policy") ||
    Object.prototype.hasOwnProperty.call(value, "running_region")
  ) {
    return true;
  }
  return Object.values(value).some(hasRunningSidecar);
}

function validateDescriptor(
  value: unknown,
  item: DocumentContentItem,
  page: PageResult,
  canonicalPage: CanonicalPage,
  result: ParseResult,
  itemIndex: number,
  path: string,
): RunningRegionDescriptor {
  const record = recordAt(value, path);
  exactKeys(record, DESCRIPTOR_KEYS, path);
  const role = record.role as keyof typeof ROLES;
  const rolePolicy = ROLES[role];
  if (!rolePolicy || item.type !== rolePolicy.type || record.canonical_scope !== rolePolicy.scope) {
    invalid(path, "has inconsistent role/type/scope");
  }
  if (
    boundedString(record.page_id, `${path}.page_id`) !== canonicalPage.page_id ||
    positiveInteger(record.physical_page_index, `${path}.physical_page_index`, MAX_PAGES) !== page.page_index
  ) {
    invalid(path, "does not match its page");
  }
  const sourceMethod = boundedString(record.source_method, `${path}.source_method`);
  if (!SOURCE_METHODS.has(sourceMethod)) invalid(`${path}.source_method`, "is unsupported");
  const sourcePath = strictPath(record.source_public_path, `${path}.source_public_path`);
  if (
    sourcePath.length !== 4 ||
    sourcePath[0] !== "pages" ||
    sourcePath[1] !== page.page_index - 1 ||
    sourcePath[2] !== "items" ||
    typeof sourcePath[3] !== "number"
  ) {
    invalid(`${path}.source_public_path`, "is not a page item path");
  }
  const owner = resolvePublicPath(result, sourcePath);
  const sourcePublicItemId = boundedString(
    record.source_public_item_id,
    `${path}.source_public_item_id`,
  );
  if (!isRecord(owner) || owner.id !== sourcePublicItemId) {
    invalid(path, "does not resolve its declared source owner");
  }
  if (sourceMethod !== "extracted_source_contribution") {
    if (sourcePath[3] !== itemIndex || item.id !== record.source_public_item_id) {
      invalid(path, "direct region does not own its marked public item");
    }
  } else if (
    sourcePath[3] >= itemIndex ||
    item.id === record.source_public_item_id
  ) {
    invalid(path, "extracted region did not preserve an earlier distinct fused owner");
  }
  if (sourceMethod === "extracted_source_contribution") {
    const syntheticItemId = boundedString(item.id, `${path}.public_item.id`);
    const descriptorId = boundedString(record.id, `${path}.id`);
    const expectedItemId = descriptorId.replace(
      /^running-region-/u,
      "running-region-item-",
    );
    if (expectedItemId === descriptorId || syntheticItemId !== expectedItemId) {
      invalid(path, "extracted synthetic item ID differs from its descriptor");
    }
    if (syntheticItemId === sourcePublicItemId) {
      invalid(path, "extracted synthetic item aliases its fused owner");
    }
    if (
      Object.prototype.hasOwnProperty.call(owner, "layout_running_region_projected") ||
      Object.prototype.hasOwnProperty.call(owner, "running_region_policy") ||
      Object.prototype.hasOwnProperty.call(owner, "running_region")
    ) {
      invalid(path, "extracted synthetic item names another running region as owner");
    }
    const sourceText = boundedNfcText(
      item.value,
      `${path}.public_item.value`,
      MAX_EXTRACTED_CONTRIBUTION_BYTES,
    );
    const sourceMarkdown = boundedNfcText(
      item.md,
      `${path}.public_item.md`,
      MAX_EXTRACTED_CONTRIBUTION_BYTES,
    );
    if (sourceText !== sourceMarkdown) {
      invalid(path, "extracted synthetic public value and Markdown differ");
    }
    if (item.source !== "native" || item.confidence !== 1) {
      invalid(path, "extracted synthetic item does not retain native custody");
    }
  }
  const descriptorBBox = validateBBox(record.bbox, page, `${path}.bbox`);
  const itemBBox = validatePublicItemBBox(
    item.bbox,
    page,
    `${path}.public_item.bbox`,
  );
  if (!sameBBox(descriptorBBox, itemBBox)) {
    invalid(path, "does not match its marked item bbox");
  }
  if (
    sourceMethod === "extracted_source_contribution" &&
    owner.type !== record.predecessor_type
  ) {
    invalid(path, "does not match its extracted predecessor type");
  }
  boundedString(record.id, `${path}.id`);
  boundedString(record.source_element_id, `${path}.source_element_id`);
  boundedString(record.predecessor_type, `${path}.predecessor_type`);
  boundedString(record.bbox_id, `${path}.bbox_id`);
  boundedString(record.canonical_block_id, `${path}.canonical_block_id`);
  const digest = boundedString(record.predecessor_item_sha256, `${path}.predecessor_item_sha256`, 64);
  if (!SHA256.test(digest)) invalid(`${path}.predecessor_item_sha256`, "must be lowercase SHA-256");
  const evidenceIds = uniqueStrings(record.evidence_ids, `${path}.evidence_ids`, 1, MAX_REFERENCES);
  uniqueStrings(record.source_object_ids, `${path}.source_object_ids`, 1, MAX_REFERENCES);
  if (sourceMethod === "extracted_source_contribution" && evidenceIds.length !== 1) {
    invalid(`${path}.evidence_ids`, "must contain one extracted evidence record");
  }
  if (
    (sourceMethod === "trusted_layout_role" && !["header", "footer"].includes(role)) ||
    (sourceMethod === "boundary_navigation" && !["navigation_top", "navigation_bottom"].includes(role)) ||
    (sourceMethod === "printed_label_boundary" && !["header", "footer"].includes(role)) ||
    (sourceMethod === "effective_boundary_cluster" && role !== "footer")
  ) {
    invalid(`${path}.source_method`, "does not match the projected role");
  }
  const confidence = validateConfidence(record.confidence, `${path}.confidence`);
  if (
    confidence.scope !== "deterministic_rule" ||
    confidence.score !== 1 ||
    confidence.unavailable_reason !== null
  ) {
    invalid(`${path}.confidence`, "must be an exact deterministic rule");
  }
  validateConcernCodes(record.concern_codes, `${path}.concern_codes`);
  const repetitionPages = arrayAt(record.repetition_page_indexes, `${path}.repetition_page_indexes`, 0, MAX_PAGES)
    .map((entry, index) => positiveInteger(entry, `${path}.repetition_page_indexes[${index}]`, MAX_PAGES));
  if (record.repetition_group_id === null) {
    if (repetitionPages.length !== 0 || sourceMethod === "cross_page_repetition") {
      invalid(path, "has inconsistent repetition membership");
    }
  } else if (
    boundedString(record.repetition_group_id, `${path}.repetition_group_id`) &&
    (repetitionPages.length < 2 ||
      !sameSequence(repetitionPages, [...new Set(repetitionPages)].sort((a, b) => a - b)) ||
      !repetitionPages.includes(page.page_index))
  ) {
    invalid(path, "has inconsistent repetition membership");
  }
  const block = canonicalPage.blocks.find((candidate) => candidate.id === record.canonical_block_id);
  if (
    !block ||
    block.primary_element_id !== record.source_element_id ||
    block.scope !== record.canonical_scope
  ) {
    invalid(path, "does not bind its canonical block");
  }
  const expectedView = record.canonical_scope === "header" ? canonicalPage.header : canonicalPage.footer;
  if (
    canonicalPage.body.block_ids.includes(block.id) ||
    !canonicalPage.full.block_ids.includes(block.id) ||
    !expectedView.block_ids.includes(block.id) ||
    canonicalPage.full.block_ids.filter((id) => id === block.id).length !== 1 ||
    expectedView.block_ids.filter((id) => id === block.id).length !== 1
  ) {
    invalid(path, "has inconsistent Body/Full scope membership");
  }
  enforceJsonByteCap(record, path, MAX_RUNNING_DESCRIPTOR_BYTES);
  return record as unknown as RunningRegionDescriptor;
}

function validateCanonicalPageViews(page: CanonicalPage): void {
  const blockIds = page.blocks.map((block) => block.id);
  if (new Set(blockIds).size !== blockIds.length) invalid("canonical_page.blocks", "repeat IDs");
  for (const [name, expected] of [
    ["body", page.blocks.filter((block) => block.scope === "body")],
    ["header", page.blocks.filter((block) => block.scope === "header")],
    ["footer", page.blocks.filter((block) => block.scope === "footer")],
    ["full", page.blocks],
  ] as const) {
    const view = page[name];
    const included = expected.filter((block) => (block.omission_reason ?? null) === null);
    if (!sameSequence(view.block_ids, included.map((block) => block.id))) {
      invalid(`canonical_page.${name}.block_ids`, "does not match stored blocks");
    }
  }
}

export interface ValidatedRunningRegions {
  readonly status: RunningRegionsProcessingStatus;
  readonly summary: RunningRegionsProcessingSummary;
  readonly pageIdentities: ReadonlyMap<number, PageIdentity>;
  readonly canonicalPages: ReadonlyMap<number, CanonicalPage>;
}

export function readRunningRegions(
  result: ParseResult,
  presentation: CanonicalPresentation,
): ValidatedRunningRegions | null {
  const processing = result.processing as unknown as JsonRecord;
  if (!Object.prototype.hasOwnProperty.call(processing, "running_regions")) {
    return null;
  }
  const summary = validateSummary(processing.running_regions);
  const pages = result.pages;
  const canonicalPages = presentation.pages;
  if (!Array.isArray(pages) || !Array.isArray(canonicalPages)) {
    invalid("pages", "must be public/canonical arrays");
  }
  if (summary.status !== "projected") {
    if (hasRunningSidecar(pages) || hasRunningSidecar(canonicalPages)) {
      invalid("pages", "retain a US08 sidecar for a nonprojecting status");
    }
    validateNonprojectingConcern(result, summary);
    return {
      status: summary.status,
      summary,
      pageIdentities: new Map(),
      canonicalPages: new Map(),
    };
  }
  if (
    pages.length !== summary.identity_count ||
    pages.length !== canonicalPages.length ||
    pages.length !== result.document.page_count ||
    pages.length > MAX_PAGES
  ) {
    invalid("pages", "have inconsistent projected coverage");
  }
  const concerns = validateProjectedConcerns(result, summary.concern_count, pages.length);
  const identities = new Map<number, PageIdentity>();
  const canonicalByPage = new Map<number, CanonicalPage>();
  const descriptorIds = new Set<string>();
  const descriptorElementIds = new Set<string>();
  const descriptorCanonicalBlockIds = new Set<string>();
  const repetitionGroups = new Map<
    string,
    Array<{ pageIndex: number; declaredPages: readonly number[] }>
  >();
  const visibleConcernCounts = new Map<string, number>();
  const chargeVisibleConcerns = (
    pageIndex: number,
    codes: readonly RunningRegionConcernCode[],
  ) => {
    for (const code of codes) {
      const key = `page:${pageIndex}\u0000${code}`;
      visibleConcernCounts.set(key, (visibleConcernCounts.get(key) ?? 0) + 1);
    }
  };
  let regionCount = 0;
  let extractedRegionCount = 0;
  let detectedCount = 0;
  let embeddedCount = 0;
  let legacyCount = 0;
  const roleCounts = { header: 0, footer: 0, navigation_top: 0, navigation_bottom: 0 };

  pages.forEach((page, pageOffset) => {
    if (page.page_index !== pageOffset + 1) invalid("pages", "must use contiguous physical indexes");
    const canonicalPage = canonicalPages[pageOffset];
    if (
      !canonicalPage ||
      canonicalPage.page_index !== page.page_index ||
      canonicalPage.page_number !== page.page_number ||
      canonicalPage.page_label !== page.page_label
    ) {
      invalid("canonical_presentation.pages", "does not match public physical pages");
    }
    validateCanonicalPageViews(canonicalPage);
    if (!Object.prototype.hasOwnProperty.call(page, "page_identity") || !Object.prototype.hasOwnProperty.call(canonicalPage, "page_identity")) {
      invalid(`pages[${pageOffset}]`, "is missing projected page identity");
    }
    const identity = validatePageIdentity(page.page_identity, page, canonicalPage, result, `pages[${pageOffset}].page_identity`);
    if (!sameJson(identity, canonicalPage.page_identity)) invalid(`canonical_presentation.pages[${pageOffset}].page_identity`, "differs from public identity");
    identities.set(page.page_index, identity);
    canonicalByPage.set(page.page_index, canonicalPage);
    chargeVisibleConcerns(page.page_index, identity.concern_codes);
    if (identity.display_source === "detected_printed_label") detectedCount += 1;
    else if (identity.display_source === "embedded_label") embeddedCount += 1;
    else legacyCount += 1;

    let pageRegions = 0;
    let pageExtractedRegions = 0;
    let extractedSuffixStarted = false;
    let predecessorMaximumRank = -1;
    const extractedRanks: number[] = [];
    const extractedDescriptorIds: string[] = [];
    page.items.forEach((item, itemIndex) => {
      const markerKeys = [
        Object.prototype.hasOwnProperty.call(item, "layout_running_region_projected"),
        Object.prototype.hasOwnProperty.call(item, "running_region_policy"),
        Object.prototype.hasOwnProperty.call(item, "running_region"),
      ];
      if (markerKeys.every((present) => !present)) {
        if (extractedSuffixStarted) {
          invalid(`pages[${pageOffset}].items`, "has a non-region after its extracted suffix");
        }
        if (!Number.isSafeInteger(item.reading_order) || item.reading_order < 0) {
          invalid(`pages[${pageOffset}].items[${itemIndex}].reading_order`, "must be a nonnegative integer");
        }
        predecessorMaximumRank = Math.max(predecessorMaximumRank, item.reading_order);
        return;
      }
      if (!markerKeys.every(Boolean) || item.layout_running_region_projected !== true || item.running_region_policy !== POLICY_ID) {
        invalid(`pages[${pageOffset}].items[${itemIndex}]`, "has a partial or invalid running sidecar");
      }
      const descriptor = validateDescriptor(
        item.running_region,
        item,
        page,
        canonicalPage,
        result,
        itemIndex,
        `pages[${pageOffset}].items[${itemIndex}].running_region`,
      );
      if (descriptorIds.has(descriptor.id)) invalid("running_region.id", "repeats");
      if (descriptorElementIds.has(descriptor.source_element_id)) {
        invalid("running_region.source_element_id", "repeats");
      }
      if (descriptorCanonicalBlockIds.has(descriptor.canonical_block_id)) {
        invalid("running_region.canonical_block_id", "repeats");
      }
      descriptorIds.add(descriptor.id);
      descriptorElementIds.add(descriptor.source_element_id);
      descriptorCanonicalBlockIds.add(descriptor.canonical_block_id);
      chargeVisibleConcerns(page.page_index, descriptor.concern_codes);
      if (descriptor.source_method === "extracted_source_contribution") {
        extractedSuffixStarted = true;
        pageExtractedRegions += 1;
        extractedRegionCount += 1;
        if (!Number.isSafeInteger(item.reading_order) || item.reading_order < 0) {
          invalid(`pages[${pageOffset}].items[${itemIndex}].reading_order`, "must be a nonnegative integer");
        }
        extractedRanks.push(item.reading_order);
        extractedDescriptorIds.push(descriptor.id);
      } else if (extractedSuffixStarted) {
        invalid(`pages[${pageOffset}].items`, "has a direct region after its extracted suffix");
      } else {
        if (!Number.isSafeInteger(item.reading_order) || item.reading_order < 0) {
          invalid(`pages[${pageOffset}].items[${itemIndex}].reading_order`, "must be a nonnegative integer");
        }
        predecessorMaximumRank = Math.max(predecessorMaximumRank, item.reading_order);
      }
      if (descriptor.repetition_group_id !== null) {
        const members = repetitionGroups.get(descriptor.repetition_group_id) ?? [];
        members.push({
          pageIndex: descriptor.physical_page_index,
          declaredPages: descriptor.repetition_page_indexes,
        });
        repetitionGroups.set(descriptor.repetition_group_id, members);
      }
      roleCounts[descriptor.role] += 1;
      pageRegions += 1;
      regionCount += 1;
    });
    if (pageRegions > MAX_REGIONS_PER_PAGE) invalid(`pages[${pageOffset}]`, "exceeds its running-region cap");
    if (pageExtractedRegions > MAX_EXTRACTED_REGIONS_PER_PAGE) {
      invalid(`pages[${pageOffset}]`, "exceeds its extracted-region cap");
    }
    if (
      !sameSequence(
        extractedRanks,
        extractedRanks.map((_rank, index) => predecessorMaximumRank + index + 1),
      ) ||
      !sameSequence(extractedDescriptorIds, [...extractedDescriptorIds].sort())
    ) {
      invalid(
        `pages[${pageOffset}].items`,
        "does not append extracted items with stable IDs and contiguous ranks",
      );
    }
  });

  if (extractedRegionCount > MAX_EXTRACTED_REGIONS_PER_DOCUMENT) {
    invalid("pages", "exceed the document extracted-region cap");
  }
  if (repetitionGroups.size > MAX_REPETITION_GROUPS_PER_DOCUMENT) {
    invalid("pages", "exceed the document repetition-group cap");
  }
  for (const members of repetitionGroups.values()) {
    const actualPages = [...new Set(members.map((member) => member.pageIndex))]
      .sort((left, right) => left - right);
    if (
      members.length !== actualPages.length ||
      members.some(
        (member) => !sameSequence(member.declaredPages, actualPages),
      )
    ) {
      invalid("running_region.repetition_page_indexes", "do not match exact group membership");
    }
  }

  if (
    regionCount !== summary.running_region_count ||
    detectedCount !== summary.detected_label_count ||
    embeddedCount !== summary.embedded_label_count ||
    legacyCount !== summary.legacy_fallback_count ||
    roleCounts.header !== summary.header_count ||
    roleCounts.footer !== summary.footer_count ||
    roleCounts.navigation_top !== summary.top_navigation_count ||
    roleCounts.navigation_bottom !== summary.bottom_navigation_count ||
    concerns.length !== summary.concern_count
  ) {
    invalid("processing.running_regions", "does not match projected sidecars");
  }
  const projectedConcernByIdentity = new Map(
    concerns.map((concern) => [
      `${concern.source_ref}\u0000${concern.code}`,
      concern,
    ]),
  );
  for (const [identity, visibleCount] of visibleConcernCounts) {
    const projectedConcern = projectedConcernByIdentity.get(identity);
    if (!projectedConcern || projectedConcern.count < visibleCount) {
      invalid(
        "running_region_concerns",
        "does not charge every visible page-identity and descriptor concern",
      );
    }
  }
  return {
    status: summary.status,
    summary,
    pageIdentities: identities,
    canonicalPages: canonicalByPage,
  };
}

export function initialPagePresentationView(
  validated: ValidatedRunningRegions | null,
): PagePresentationView {
  return validated?.status === "projected" ? "body" : "full";
}

export function pageDisplayLabel(
  validated: ValidatedRunningRegions | null,
  physicalPageIndex: number,
): string | null {
  if (validated?.status !== "projected") return null;
  return validated.pageIdentities.get(physicalPageIndex)?.display_label ?? null;
}

export function canonicalPageView(
  page: CanonicalPage,
  view: PagePresentationView,
): CanonicalView {
  return view === "body" ? page.body : page.full;
}

export function canonicalPageBlocks(
  page: CanonicalPage,
  view: PagePresentationView,
): CanonicalBlock[] {
  const selected = canonicalPageView(page, view);
  const byId = new Map(page.blocks.map((block) => [block.id, block]));
  return selected.block_ids.map((id) => {
    const block = byId.get(id);
    if (!block) invalid("canonical_page", `view references missing block ${JSON.stringify(id)}`);
    return block;
  });
}
