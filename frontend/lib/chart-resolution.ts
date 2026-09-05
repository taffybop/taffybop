import { createElement, type ReactNode } from "react";

import type {
  CanonicalBlock,
  CanonicalPage,
  ChartComplexityClassification,
  ChartConfidence,
  ChartFamilyClassification,
  ChartResolution,
  ChartSemanticAnalysis,
  ChartSemanticFeature,
  ChartSourceAsset,
  ChartTranscript,
  DocumentContentItem,
  PageResult,
  VisualBoundingBox,
} from "./types.ts";

const PNG_PREFIX = "data:image/png;base64,";
const MAX_ASSET_BYTES = 8 * 1024 * 1024;
const MAX_ASSET_PIXELS = 16_000_000;
const MAX_DATA_URI_LENGTH =
  PNG_PREFIX.length + 4 * Math.ceil(MAX_ASSET_BYTES / 3);
const MAX_TRANSCRIPT_CHARACTERS = 65_536;
const SHA256 = /^[0-9a-f]{64}$/u;
const ASSET_ID = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/u;
const PYTHON_EDGE_WHITESPACE =
  /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;

const STATUS = [
  "structured_primary",
  "image_primary_unsupported",
  "image_primary_incomplete",
  "asset_unavailable",
] as const;
const ASSET_STATUS = ["retained", "unavailable"] as const;
const OWNER_GEOMETRY_PROOF_KIND = [
  "detected_image",
  "docling_picture",
  "detected_image_and_docling_picture",
] as const;
const PRIMARY_REPRESENTATION = [
  "structured_chart",
  "source_image",
  "grounded_predecessor",
] as const;
const PRIMARY_REASON = [
  "semantic_completeness_passed",
  "semantic_family_not_supported",
  "semantic_analysis_incomplete",
  "source_asset_unavailable",
] as const;
const TERMINAL_STATE = {
  structured_primary: [
    "retained",
    "structured_chart",
    "semantic_completeness_passed",
    "completed",
    "passed",
  ],
  image_primary_unsupported: [
    "retained",
    "source_image",
    "semantic_family_not_supported",
    "not_run_no_approved_analyzer",
    "not_run",
  ],
  image_primary_incomplete: [
    "retained",
    "source_image",
    "semantic_analysis_incomplete",
    null,
    "failed",
  ],
  asset_unavailable: [
    "unavailable",
    "grounded_predecessor",
    "source_asset_unavailable",
    "not_run_asset_unavailable",
    "not_run",
  ],
} as const;
const ASSET_UNAVAILABLE_REASON = [
  "source_bytes_unavailable",
  "source_kind_unsupported",
  "owner_geometry_invalid",
  "owner_outside_page",
  "page_unavailable",
  "render_failed",
  "render_timeout",
  "crop_dimension_limit",
  "crop_pixel_limit",
  "asset_byte_limit",
  "document_asset_count_limit",
  "document_asset_byte_limit",
  "response_byte_limit",
  "document_render_timeout",
  "mime_validation_failed",
  "source_integrity_mismatch",
  "crop_legibility_limit",
] as const;
const CONCERN_CODE = [
  "chart_family_undetermined",
  "chart_complexity_undetermined",
  "chart_semantics_unsupported",
  "chart_semantics_incomplete",
  "chart_source_asset_unavailable",
] as const;
const CONFIDENCE_REASON = [
  "not_calibrated",
  "source_confidence_unavailable",
  "asset_unavailable",
] as const;
const TRANSCRIPT_SOURCE = ["native", "ocr", "mixed", "source_labels"] as const;
const VISUAL_LABEL_ROLE = [
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
] as const;
const VISUAL_EVIDENCE_KIND = [
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
] as const;
const VISUAL_EXTRACTION_METHOD = [
  "layout",
  "ocr",
  "vector",
  "raster",
  "explicit_text",
] as const;
const NATIVE_TRANSCRIPT_METHOD = [
  "pdf_text_layer_inside_visual_bbox",
  "pdf_source_line_owned_by_visual_child",
] as const;
const FAMILY_STATUS = ["classified", "undetermined", "not_run"] as const;
const FAMILY = [
  "bar",
  "line",
  "pie",
  "area",
  "scatter",
  "bubble",
  "mixed",
  "multi_panel",
  "other",
  "undetermined",
] as const;
const FAMILY_REASON = [
  "declared_classifier_family",
  "native_office_family",
  "multiple_family_signals",
  "insufficient_source_features",
  "asset_unavailable",
] as const;
const COMPLEXITY_STATUS = ["regular", "complex", "undetermined", "not_run"] as const;
const COMPLEXITY_REASON = [
  "single_supported_family",
  "multi_panel_geometry",
  "multiple_axes",
  "multiple_legends",
  "multiple_mark_types",
  "dense_source_labels",
  "multi_encoding_family",
  "insufficient_source_features",
  "asset_unavailable",
] as const;
const COMPLEX_REASONS = new Set<string>([
  "multi_panel_geometry",
  "multiple_axes",
  "multiple_legends",
  "multiple_mark_types",
  "dense_source_labels",
  "multi_encoding_family",
]);
const SEMANTIC_FEATURE = [
  "region",
  "source_evidence",
  "family",
  "panels",
  "axes",
  "categories",
  "legends",
  "series",
  "points",
  "ownership",
  "ambiguity_closure",
  "serialization",
] as const;
const ATTEMPT_STATUS = [
  "not_run_asset_unavailable",
  "not_run_no_approved_analyzer",
  "completed",
  "failed",
  "timed_out",
  "resource_refused",
] as const;
const GATE_STATUS = ["not_run", "passed", "failed"] as const;
const FAILURE_REASON = [
  "unresolved",
  "unsupported",
  "malformed_input",
  "validation_failed",
  "resource_limit",
  "timeout",
  "low_quality",
  "incomplete",
  "asset_unavailable",
] as const;

const RESOLUTION_KEYS = [
  "schema_version",
  "policy_id",
  "owner_item_id",
  "page_index",
  "source_order",
  "source_bbox",
  "status",
  "asset_status",
  "asset_unavailable_reason",
  "asset",
  "family_classification",
  "complexity_classification",
  "semantic_analysis",
  "primary_representation",
  "primary_reason",
  "transcript",
  "confidence_dimensions",
  "concern_codes",
] as const;
const ASSET_KEYS = [
  "asset_id",
  "source_document_sha256",
  "render_source_sha256",
  "owner_item_id",
  "physical_page",
  "source_bbox",
  "owner_geometry_proof_kind",
  "owner_geometry_evidence_ids",
  "owner_geometry_evidence_sha256",
  "rendered_bbox",
  "coordinate_system",
  "pixel_to_page_transform",
  "page_device_dimensions",
  "crop_device_margins",
  "renderer",
  "renderer_version",
  "render_policy",
  "source_kind",
  "render_scale",
  "effective_dpi",
  "width",
  "height",
  "mime_type",
  "encoding",
  "byte_length",
  "sha256",
  "data_uri",
  "color_space",
  "alpha_policy",
  "antialiasing_policy",
  "interpolation_policy",
  "bbox_rounding",
  "padding",
] as const;
const BBOX_KEYS = ["x", "y", "width", "height", "unit"] as const;
const CONFIDENCE_KEYS = ["value", "unavailable_reason"] as const;
const CONFIDENCE_DIMENSION_KEYS = [
  "ownership",
  "transcription",
  "family",
  "complexity",
] as const;
const TRANSCRIPT_KEYS = [
  "status",
  "source",
  "text",
  "text_sha256",
  "evidence_ids",
  "confidence",
] as const;
const FAMILY_KEYS = [
  "status",
  "family",
  "classifier_version",
  "reason_codes",
  "evidence_ids",
  "confidence",
] as const;
const COMPLEXITY_KEYS = [
  "status",
  "classifier_version",
  "reason_codes",
  "evidence_ids",
  "confidence",
] as const;
const SEMANTIC_KEYS = [
  "capability_matrix_version",
  "attempt_status",
  "analyzer_ids",
  "configuration_sha256",
  "completeness_gate_status",
  "required_features",
  "observed_features",
  "missing_features",
  "ambiguous_evidence_ids",
  "failure_reason",
] as const;
const VISUAL_SERIALIZATION_KEYS = [
  "status",
  "markdown",
  "caption_occurrences",
  "row_count",
] as const;

const UTF8_ENCODER = new TextEncoder();
const SHA256_CONSTANTS = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5,
  0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
  0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc,
  0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
  0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
  0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3,
  0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5,
  0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
  0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);
const SHA256_WORDS = new Uint32Array(64);

export class ChartResolutionValidationError extends Error {
  readonly code = "invalid_chart_resolution";
  readonly path: string;

  constructor(path: string, detail: string) {
    super(`Invalid chart resolution at ${path}: ${detail}`);
    this.name = "ChartResolutionValidationError";
    this.path = path;
  }
}

export interface ValidatedChartResolution {
  owner: DocumentContentItem;
  resolution: ChartResolution;
  asset: ChartSourceAsset | null;
  caption: string;
  imageMarkdown: string | null;
  structuredMarkdown: string | null;
  structuredCaptionOccurrences: 0 | 1;
  primaryText: string | null;
}

export interface ChartCaptionPresentation {
  text: string;
  itemId: string;
  relationshipId: string;
  placement: "before" | "after";
}

function invalid(path: string, detail: string): never {
  throw new ChartResolutionValidationError(path, detail);
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function exactRecord(
  value: unknown,
  path: string,
  expectedKeys: readonly string[],
): Record<string, unknown> {
  if (!isPlainRecord(value)) invalid(path, "must be an exact object");
  const keys = Object.keys(value).sort();
  const expected = [...expectedKeys].sort();
  if (
    keys.length !== expected.length ||
    keys.some((key, index) => key !== expected[index])
  ) {
    invalid(path, "has missing or additional keys");
  }
  return value;
}

function looseRecord(value: unknown, path: string): Record<string, unknown> {
  if (!isPlainRecord(value)) invalid(path, "must be an exact object");
  return value;
}

function exactArray(value: unknown, path: string, maximum: number): unknown[] {
  if (
    !Array.isArray(value) ||
    value.length > maximum ||
    Object.keys(value).length !== value.length ||
    Object.keys(value).some((key, index) => key !== String(index))
  ) {
    invalid(path, `must be a dense array with at most ${maximum} entries`);
  }
  return value;
}

function oneOf<T extends string>(
  value: unknown,
  choices: readonly T[],
  path: string,
): T {
  if (typeof value !== "string" || !choices.includes(value as T)) {
    invalid(path, "has an unsupported value");
  }
  return value as T;
}

function boundedString(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): string {
  if (typeof value !== "string") {
    invalid(path, `must contain ${minimum}..${maximum} characters`);
  }
  let length = 0;
  const characters = value[Symbol.iterator]();
  while (!characters.next().done) {
    length += 1;
    if (length > maximum) {
      invalid(path, `must contain ${minimum}..${maximum} characters`);
    }
  }
  if (length < minimum) {
    invalid(path, `must contain ${minimum}..${maximum} characters`);
  }
  return value;
}

function finiteNumber(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): number {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    value < minimum ||
    value > maximum
  ) {
    invalid(path, `must be finite and in ${minimum}..${maximum}`);
  }
  return value;
}

function integer(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
): number {
  const parsed = finiteNumber(value, path, minimum, maximum);
  if (!Number.isInteger(parsed)) invalid(path, "must be an integer");
  return parsed;
}

function sha256(value: unknown, path: string): string {
  if (typeof value !== "string" || !SHA256.test(value)) {
    invalid(path, "must be a lowercase SHA-256 digest");
  }
  return value;
}

function stringArray<T extends string = string>(
  value: unknown,
  path: string,
  minimum: number,
  maximum: number,
  choices?: readonly T[],
): T[] {
  const values = exactArray(value, path, maximum);
  if (values.length < minimum) invalid(path, `requires at least ${minimum} entries`);
  const parsed = values.map((entry, index) => {
    if (choices !== undefined) return oneOf(entry, choices, `${path}.${index}`);
    if (typeof entry !== "string") invalid(`${path}.${index}`, "must be a string");
    return entry as T;
  });
  if (new Set(parsed).size !== parsed.length) invalid(path, "must not repeat entries");
  return parsed;
}

function sameStrings(left: readonly string[], right: readonly string[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function sameStringSet(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
}

function parseBoundingBox(
  value: unknown,
  path: string,
  requireArea = false,
): VisualBoundingBox {
  const record = exactRecord(value, path, BBOX_KEYS);
  const width = finiteNumber(record.width, `${path}.width`, 0, Number.MAX_VALUE);
  const height = finiteNumber(record.height, `${path}.height`, 0, Number.MAX_VALUE);
  if (requireArea && (width === 0 || height === 0)) {
    invalid(path, "must have positive area");
  }
  return {
    x: finiteNumber(record.x, `${path}.x`, 0, Number.MAX_VALUE),
    y: finiteNumber(record.y, `${path}.y`, 0, Number.MAX_VALUE),
    width,
    height,
    unit: oneOf(record.unit, ["pt", "px"] as const, `${path}.unit`),
  };
}

function sameBoundingBox(left: VisualBoundingBox, right: VisualBoundingBox): boolean {
  return (
    left.x === right.x &&
    left.y === right.y &&
    left.width === right.width &&
    left.height === right.height &&
    left.unit === right.unit
  );
}

function pythonStrip(value: string): string {
  return value.replace(PYTHON_EDGE_WHITESPACE, "");
}

function parseConfidence(value: unknown, path: string): ChartConfidence {
  const record = exactRecord(value, path, CONFIDENCE_KEYS);
  const confidence =
    record.value === null
      ? null
      : finiteNumber(record.value, `${path}.value`, 0, 1);
  const reason =
    record.unavailable_reason === null
      ? null
      : oneOf(
          record.unavailable_reason,
          CONFIDENCE_REASON,
          `${path}.unavailable_reason`,
        );
  if ((confidence === null) === (reason === null)) {
    invalid(path, "requires exactly one confidence value or unavailable reason");
  }
  return { value: confidence, unavailable_reason: reason };
}

function sameConfidence(left: ChartConfidence, right: ChartConfidence): boolean {
  return (
    left.value === right.value &&
    left.unavailable_reason === right.unavailable_reason
  );
}

function validUtf8Bytes(value: string): Uint8Array | null {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const trailing = value.charCodeAt(index + 1);
      if (!(trailing >= 0xdc00 && trailing <= 0xdfff)) return null;
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return null;
    }
  }
  return UTF8_ENCODER.encode(value);
}

function sha256Hex(bytes: Uint8Array): string {
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const bitLength = bytes.length * 8;
  const view = new DataView(padded.buffer);
  view.setUint32(
    paddedLength - 8,
    Math.floor(bitLength / 0x1_0000_0000),
    false,
  );
  view.setUint32(paddedLength - 4, bitLength >>> 0, false);
  let hash0 = 0x6a09e667;
  let hash1 = 0xbb67ae85;
  let hash2 = 0x3c6ef372;
  let hash3 = 0xa54ff53a;
  let hash4 = 0x510e527f;
  let hash5 = 0x9b05688c;
  let hash6 = 0x1f83d9ab;
  let hash7 = 0x5be0cd19;
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) {
      SHA256_WORDS[index] = view.getUint32(offset + index * 4, false);
    }
    for (let index = 16; index < 64; index += 1) {
      const before15 = SHA256_WORDS[index - 15] ?? 0;
      const before2 = SHA256_WORDS[index - 2] ?? 0;
      const sigma0 =
        ((before15 >>> 7) | (before15 << 25)) ^
        ((before15 >>> 18) | (before15 << 14)) ^
        (before15 >>> 3);
      const sigma1 =
        ((before2 >>> 17) | (before2 << 15)) ^
        ((before2 >>> 19) | (before2 << 13)) ^
        (before2 >>> 10);
      SHA256_WORDS[index] =
        ((SHA256_WORDS[index - 16] ?? 0) +
          sigma0 +
          (SHA256_WORDS[index - 7] ?? 0) +
          sigma1) >>>
        0;
    }
    let a = hash0;
    let b = hash1;
    let c = hash2;
    let d = hash3;
    let e = hash4;
    let f = hash5;
    let g = hash6;
    let h = hash7;
    for (let index = 0; index < 64; index += 1) {
      const upper1 =
        ((e >>> 6) | (e << 26)) ^
        ((e >>> 11) | (e << 21)) ^
        ((e >>> 25) | (e << 7));
      const choice = (e & f) ^ (~e & g);
      const temporary1 =
        (h +
          upper1 +
          choice +
          (SHA256_CONSTANTS[index] ?? 0) +
          (SHA256_WORDS[index] ?? 0)) >>>
        0;
      const upper0 =
        ((a >>> 2) | (a << 30)) ^
        ((a >>> 13) | (a << 19)) ^
        ((a >>> 22) | (a << 10));
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temporary2 = (upper0 + majority) >>> 0;
      h = g;
      g = f;
      f = e;
      e = (d + temporary1) >>> 0;
      d = c;
      c = b;
      b = a;
      a = (temporary1 + temporary2) >>> 0;
    }
    hash0 = (hash0 + a) >>> 0;
    hash1 = (hash1 + b) >>> 0;
    hash2 = (hash2 + c) >>> 0;
    hash3 = (hash3 + d) >>> 0;
    hash4 = (hash4 + e) >>> 0;
    hash5 = (hash5 + f) >>> 0;
    hash6 = (hash6 + g) >>> 0;
    hash7 = (hash7 + h) >>> 0;
  }
  return [hash0, hash1, hash2, hash3, hash4, hash5, hash6, hash7]
    .map((value) => value.toString(16).padStart(8, "0"))
    .join("");
}

/** Match CPython's ensure_ascii JSON string encoding for the custody tuple. */
function pythonAsciiJsonString(value: string): string {
  let encoded = '"';
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit === 0x22) encoded += '\\"';
    else if (codeUnit === 0x5c) encoded += "\\\\";
    else if (codeUnit === 0x08) encoded += "\\b";
    else if (codeUnit === 0x09) encoded += "\\t";
    else if (codeUnit === 0x0a) encoded += "\\n";
    else if (codeUnit === 0x0c) encoded += "\\f";
    else if (codeUnit === 0x0d) encoded += "\\r";
    else if (codeUnit < 0x20 || codeUnit >= 0x7f) {
      encoded += `\\u${codeUnit.toString(16).padStart(4, "0")}`;
    } else {
      encoded += value[index];
    }
  }
  return `${encoded}"`;
}

/**
 * Match CPython's finite float repr used by json.dumps.
 *
 * Both runtimes choose the shortest round-tripping decimal digits; their
 * differences are presentation-only: CPython switches to scientific notation
 * outside [-4, 15], retains `.0` for integral decimal floats, and pads a
 * one-digit exponent. The asset contract has already rejected non-finite
 * values before this helper runs.
 */
function pythonJsonFloat(value: number): string {
  if (!Number.isFinite(value)) {
    throw new TypeError("chart asset identity requires a finite float");
  }
  if (Object.is(value, -0)) return "-0.0";
  if (value === 0) return "0.0";

  const sign = value < 0 ? "-" : "";
  const raw = Math.abs(value).toString().toLowerCase();
  let digits: string;
  let decimalExponent: number;
  const exponentMarker = raw.indexOf("e");
  if (exponentMarker >= 0) {
    const mantissa = raw.slice(0, exponentMarker);
    decimalExponent = Number.parseInt(raw.slice(exponentMarker + 1), 10);
    digits = mantissa.replace(".", "");
  } else {
    const decimalPoint = raw.indexOf(".");
    if (decimalPoint < 0) {
      digits = raw;
      decimalExponent = raw.length - 1;
    } else {
      const integerPart = raw.slice(0, decimalPoint);
      const fractionalPart = raw.slice(decimalPoint + 1);
      if (integerPart !== "0") {
        digits = `${integerPart}${fractionalPart}`;
        decimalExponent = integerPart.length - 1;
      } else {
        const firstSignificant = fractionalPart.search(/[1-9]/u);
        digits = fractionalPart.slice(firstSignificant);
        decimalExponent = -(firstSignificant + 1);
      }
    }
  }
  digits = digits.replace(/0+$/u, "");

  if (decimalExponent < -4 || decimalExponent >= 16) {
    const fraction = digits.length > 1 ? `.${digits.slice(1)}` : "";
    const exponentSign = decimalExponent < 0 ? "-" : "+";
    const exponent = Math.abs(decimalExponent).toString().padStart(2, "0");
    return `${sign}${digits[0]}${fraction}e${exponentSign}${exponent}`;
  }
  if (decimalExponent < 0) {
    return `${sign}0.${"0".repeat(-decimalExponent - 1)}${digits}`;
  }
  const integerDigits = decimalExponent + 1;
  if (digits.length <= integerDigits) {
    return `${sign}${digits}${"0".repeat(integerDigits - digits.length)}.0`;
  }
  return `${sign}${digits.slice(0, integerDigits)}.${digits.slice(integerDigits)}`;
}

function pythonBoundingBoxJson(bbox: VisualBoundingBox): string {
  // json.dumps(sort_keys=True) recursively sorts this closed object's keys.
  return (
    `{"height":${pythonJsonFloat(bbox.height)},` +
    `"unit":${pythonAsciiJsonString(bbox.unit)},` +
    `"width":${pythonJsonFloat(bbox.width)},` +
    `"x":${pythonJsonFloat(bbox.x)},` +
    `"y":${pythonJsonFloat(bbox.y)}}`
  );
}

function pythonIntegerArrayJson(values: readonly number[] | null): string {
  return values === null ? "null" : `[${values.join(",")}]`;
}

/** Replay the backend `_stable_id("chart-asset", ...)` custody identity. */
export function replayChartSourceAssetId(asset: ChartSourceAsset): string {
  const evidenceIds = `[${asset.owner_geometry_evidence_ids
    .map(pythonAsciiJsonString)
    .join(",")}]`;
  const parts = [
    pythonAsciiJsonString(asset.source_document_sha256),
    pythonAsciiJsonString(asset.render_source_sha256),
    pythonAsciiJsonString(asset.owner_item_id),
    String(asset.physical_page),
    pythonBoundingBoxJson(asset.source_bbox),
    pythonAsciiJsonString(asset.owner_geometry_proof_kind),
    evidenceIds,
    pythonAsciiJsonString(asset.owner_geometry_evidence_sha256),
    pythonBoundingBoxJson(asset.rendered_bbox),
    pythonIntegerArrayJson(asset.page_device_dimensions),
    pythonIntegerArrayJson(asset.crop_device_margins),
    pythonAsciiJsonString(asset.render_policy),
    pythonAsciiJsonString(asset.sha256),
  ];
  const payload = `[${parts.join(",")}]`;
  return `chart-asset-${sha256Hex(UTF8_ENCODER.encode(payload)).slice(0, 24)}`;
}

function base64Value(code: number): number {
  if (code >= 0x41 && code <= 0x5a) return code - 0x41;
  if (code >= 0x61 && code <= 0x7a) return code - 0x61 + 26;
  if (code >= 0x30 && code <= 0x39) return code - 0x30 + 52;
  if (code === 0x2b) return 62;
  if (code === 0x2f) return 63;
  return -1;
}

function decodeBase64(value: string, path: string): Uint8Array {
  if (value.length < 4 || value.length % 4 !== 0) {
    invalid(path, "is not padded base64");
  }
  let padding = 0;
  if (value.endsWith("==")) padding = 2;
  else if (value.endsWith("=")) padding = 1;
  const decodedLength = (value.length / 4) * 3 - padding;
  if (decodedLength < 1 || decodedLength > MAX_ASSET_BYTES) {
    invalid(path, "exceeds the decoded-byte limit");
  }
  const bytes = new Uint8Array(decodedLength);
  let cursor = 0;
  for (let index = 0; index < value.length; index += 4) {
    const final = index + 4 === value.length;
    const character0 = value.charCodeAt(index);
    const character1 = value.charCodeAt(index + 1);
    const character2 = value.charCodeAt(index + 2);
    const character3 = value.charCodeAt(index + 3);
    const value0 = base64Value(character0);
    const value1 = base64Value(character1);
    const value2 = character2 === 0x3d ? 0 : base64Value(character2);
    const value3 = character3 === 0x3d ? 0 : base64Value(character3);
    if (
      value0 < 0 ||
      value1 < 0 ||
      value2 < 0 ||
      value3 < 0 ||
      (!final && (character2 === 0x3d || character3 === 0x3d)) ||
      (character2 === 0x3d && character3 !== 0x3d)
    ) {
      invalid(path, "contains malformed base64");
    }
    if (final && character2 === 0x3d && (value1 & 0x0f) !== 0) {
      invalid(path, "contains non-canonical padding bits");
    }
    if (
      final &&
      character2 !== 0x3d &&
      character3 === 0x3d &&
      (value2 & 0x03) !== 0
    ) {
      invalid(path, "contains non-canonical padding bits");
    }
    const word = (value0 << 18) | (value1 << 12) | (value2 << 6) | value3;
    if (cursor < decodedLength) bytes[cursor++] = (word >>> 16) & 0xff;
    if (cursor < decodedLength) bytes[cursor++] = (word >>> 8) & 0xff;
    if (cursor < decodedLength) bytes[cursor++] = word & 0xff;
  }
  if (cursor !== decodedLength) invalid(path, "has inconsistent padding");
  return bytes;
}

function pngDimensions(
  bytes: Uint8Array,
  path: string,
): { width: number; height: number } {
  const signature = [137, 80, 78, 71, 13, 10, 26, 10];
  if (
    bytes.length < 33 ||
    signature.some((value, index) => bytes[index] !== value) ||
    bytes[8] !== 0 ||
    bytes[9] !== 0 ||
    bytes[10] !== 0 ||
    bytes[11] !== 13 ||
    bytes[12] !== 73 ||
    bytes[13] !== 72 ||
    bytes[14] !== 68 ||
    bytes[15] !== 82
  ) {
    invalid(path, "does not start with a PNG signature and 13-byte IHDR");
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const width = view.getUint32(16, false);
  const height = view.getUint32(20, false);
  if (width === 0 || height === 0) invalid(path, "has zero IHDR dimensions");
  return { width, height };
}

function parseTranscript(value: unknown, path: string): ChartTranscript {
  const record = exactRecord(value, path, TRANSCRIPT_KEYS);
  const status = oneOf(record.status, ["available", "unavailable"] as const, `${path}.status`);
  const source =
    record.source === null
      ? null
      : oneOf(record.source, TRANSCRIPT_SOURCE, `${path}.source`);
  const text =
    record.text === null
      ? null
      : boundedString(record.text, `${path}.text`, 0, MAX_TRANSCRIPT_CHARACTERS);
  const textDigest =
    record.text_sha256 === null
      ? null
      : sha256(record.text_sha256, `${path}.text_sha256`);
  const evidenceIds = stringArray(record.evidence_ids, `${path}.evidence_ids`, 0, 64);
  const confidence = parseConfidence(record.confidence, `${path}.confidence`);
  if (status === "available") {
    if (source === null || text === null || text.length === 0 || textDigest === null) {
      invalid(path, "has an incomplete available transcript");
    }
    const bytes = validUtf8Bytes(text);
    if (bytes === null || sha256Hex(bytes) !== textDigest) {
      invalid(`${path}.text_sha256`, "differs from the UTF-8 transcript");
    }
  } else if (source !== null || text !== null || textDigest !== null) {
    invalid(path, "carries content for an unavailable transcript");
  }
  return {
    status,
    source,
    text,
    text_sha256: textDigest,
    evidence_ids: evidenceIds,
    confidence,
  };
}

interface TranscriptLabelView {
  text: string;
  role: (typeof VISUAL_LABEL_ROLE)[number];
  evidenceIds: string[];
}

interface TranscriptEvidenceView {
  kind: (typeof VISUAL_EVIDENCE_KIND)[number];
  extractionMethod: (typeof VISUAL_EXTRACTION_METHOD)[number];
  sourceTokenIds: string[];
}

function boundedOptionalTranscriptText(value: unknown): string | null {
  if (typeof value !== "string" || value.length === 0) return null;
  let length = 0;
  const characters = value[Symbol.iterator]();
  while (!characters.next().done) {
    length += 1;
    if (length > MAX_TRANSCRIPT_CHARACTERS) return null;
  }
  return validUtf8Bytes(value) === null ? null : value;
}

function readTranscriptEvidenceGraph(structure: Record<string, unknown>): {
  labels: TranscriptLabelView[];
  evidenceById: Map<string, TranscriptEvidenceView>;
} {
  const rawLabels = exactArray(
    structure.labels,
    "owner.visual_structure.labels",
    512,
  );
  const labels = rawLabels.map((value, index): TranscriptLabelView => {
    const record = looseRecord(
      value,
      `owner.visual_structure.labels.${index}`,
    );
    const text = boundedString(
      record.text,
      `owner.visual_structure.labels.${index}.text`,
      1,
      1_024,
    );
    if (validUtf8Bytes(text) === null) {
      invalid(
        `owner.visual_structure.labels.${index}.text`,
        "is not valid UTF-8",
      );
    }
    const occurrenceIndex = integer(
      record.occurrence_index,
      `owner.visual_structure.labels.${index}.occurrence_index`,
      0,
      512,
    );
    if (occurrenceIndex !== index) {
      invalid(
        "owner.visual_structure.labels",
        "has inconsistent occurrence order",
      );
    }
    return {
      text,
      role: oneOf(
        record.role,
        VISUAL_LABEL_ROLE,
        `owner.visual_structure.labels.${index}.role`,
      ),
      evidenceIds: stringArray(
        record.evidence_ids,
        `owner.visual_structure.labels.${index}.evidence_ids`,
        1,
        64,
      ),
    };
  });

  const rawEvidence = exactArray(
    structure.evidence,
    "owner.visual_structure.evidence",
    2_048,
  );
  const evidenceById = new Map<string, TranscriptEvidenceView>();
  rawEvidence.forEach((value, index) => {
    const record = looseRecord(
      value,
      `owner.visual_structure.evidence.${index}`,
    );
    const id = boundedString(
      record.id,
      `owner.visual_structure.evidence.${index}.id`,
      1,
      128,
    );
    if (!ASSET_ID.test(id) || evidenceById.has(id)) {
      invalid(
        `owner.visual_structure.evidence.${index}.id`,
        "is invalid or repeats",
      );
    }
    const provenance = looseRecord(
      record.provenance,
      `owner.visual_structure.evidence.${index}.provenance`,
    );
    evidenceById.set(id, {
      kind: oneOf(
        record.kind,
        VISUAL_EVIDENCE_KIND,
        `owner.visual_structure.evidence.${index}.kind`,
      ),
      extractionMethod: oneOf(
        provenance.extraction_method,
        VISUAL_EXTRACTION_METHOD,
        `owner.visual_structure.evidence.${index}.provenance.extraction_method`,
      ),
      sourceTokenIds: stringArray(
        provenance.source_token_ids,
        `owner.visual_structure.evidence.${index}.provenance.source_token_ids`,
        0,
        64,
      ),
    });
  });
  return { labels, evidenceById };
}

function transcriptEvidenceIds(
  labels: readonly TranscriptLabelView[],
  evidenceById: ReadonlyMap<string, TranscriptEvidenceView>,
  options: {
    extractionMethod?: TranscriptEvidenceView["extractionMethod"];
    omitGeneratedCaption?: boolean;
  } = {},
): string[] {
  const output: string[] = [];
  const seen = new Set<string>();
  for (const label of labels) {
    if (options.omitGeneratedCaption === true && label.role === "caption") {
      continue;
    }
    for (const evidenceId of label.evidenceIds) {
      const evidence = evidenceById.get(evidenceId);
      if (
        evidence === undefined ||
        evidence.kind !== "label" ||
        (options.extractionMethod !== undefined &&
          evidence.extractionMethod !== options.extractionMethod)
      ) {
        continue;
      }
      if (!seen.has(evidenceId)) {
        seen.add(evidenceId);
        output.push(evidenceId);
        if (output.length > 64) return [];
      }
    }
  }
  return output;
}

function sourceConfidenceUnavailable(): ChartConfidence {
  return {
    value: null,
    unavailable_reason: "source_confidence_unavailable",
  };
}

function availableTranscript(
  source: "native" | "ocr" | "source_labels",
  text: string,
  evidenceIds: string[],
  confidence: ChartConfidence,
): ChartTranscript {
  const encoded = validUtf8Bytes(text);
  if (encoded === null) {
    invalid("owner chart transcript", "contains invalid UTF-8");
  }
  return {
    status: "available",
    source,
    text,
    text_sha256: sha256Hex(encoded),
    evidence_ids: evidenceIds,
    confidence,
  };
}

function replayNativeTranscript(
  item: DocumentContentItem,
  text: string,
  labels: readonly TranscriptLabelView[],
  evidenceById: ReadonlyMap<string, TranscriptEvidenceView>,
): ChartTranscript | null {
  if (!isPlainRecord(item.meta)) return null;
  const sourceMeta = item.meta.phase05_visual_source_text;
  if (!isPlainRecord(sourceMeta)) return null;
  if (
    typeof sourceMeta.method !== "string" ||
    !NATIVE_TRANSCRIPT_METHOD.includes(
      sourceMeta.method as (typeof NATIVE_TRANSCRIPT_METHOD)[number],
    )
  ) {
    return null;
  }
  const encoded = validUtf8Bytes(text);
  if (
    encoded === null ||
    sourceMeta.text_sha256 !== sha256Hex(encoded) ||
    !Array.isArray(item.visual_source_text_occurrences) ||
    !Array.isArray(item.visual_source_text_lines)
  ) {
    return null;
  }
  const occurrences = item.visual_source_text_occurrences;
  const lines = item.visual_source_text_lines;
  if (
    occurrences.length < 1 ||
    occurrences.length > 64 ||
    lines.length < 1 ||
    lines.length > 64 ||
    Object.keys(occurrences).length !== occurrences.length ||
    Object.keys(lines).length !== lines.length ||
    typeof sourceMeta.occurrence_count !== "number" ||
    !Number.isInteger(sourceMeta.occurrence_count) ||
    sourceMeta.occurrence_count !== occurrences.length
  ) {
    return null;
  }
  const occurrenceIds: string[] = [];
  for (const value of occurrences) {
    if (!isPlainRecord(value)) return null;
    const occurrenceId = Object.hasOwn(value, "occurrence_id")
      ? value.occurrence_id
      : value.id;
    if (typeof occurrenceId !== "string") return null;
    let length = 0;
    const characters = occurrenceId[Symbol.iterator]();
    while (!characters.next().done) {
      length += 1;
      if (length > 128) return null;
    }
    if (length < 1) return null;
    occurrenceIds.push(occurrenceId);
  }
  if (new Set(occurrenceIds).size !== occurrenceIds.length) return null;

  const lineTexts: string[] = [];
  for (const value of lines) {
    if (!isPlainRecord(value) || typeof value.text !== "string" || !value.text) {
      return null;
    }
    lineTexts.push(value.text);
  }
  if (pythonStrip(lineTexts.join("\n")) !== text) return null;

  const evidenceIds = transcriptEvidenceIds(labels, evidenceById, {
    extractionMethod: "explicit_text",
  });
  if (evidenceIds.length === 0) return null;
  const evidenceOccurrenceIds: string[] = [];
  for (const evidenceId of evidenceIds) {
    const sourceTokenIds = evidenceById.get(evidenceId)?.sourceTokenIds;
    if (sourceTokenIds?.length !== 1) return null;
    evidenceOccurrenceIds.push(sourceTokenIds[0]!);
  }
  if (!sameStrings(evidenceOccurrenceIds, occurrenceIds)) return null;
  return availableTranscript(
    "native",
    text,
    evidenceIds,
    sourceConfidenceUnavailable(),
  );
}

function replayOwnerTranscript(
  item: DocumentContentItem,
  structure: Record<string, unknown>,
): ChartTranscript {
  const { labels, evidenceById } = readTranscriptEvidenceGraph(structure);
  const nativeText = boundedOptionalTranscriptText(item.visual_source_text);
  if (nativeText !== null) {
    const native = replayNativeTranscript(
      item,
      nativeText,
      labels,
      evidenceById,
    );
    if (native !== null) return native;
  }

  const ocrText = boundedOptionalTranscriptText(item.ocr_text);
  if (ocrText !== null) {
    const evidenceIds = transcriptEvidenceIds(labels, evidenceById, {
      extractionMethod: "ocr",
    });
    if (evidenceIds.length > 0) {
      const sourceConfidence = item.confidence;
      const confidence =
        typeof sourceConfidence === "number" &&
        Number.isFinite(sourceConfidence) &&
        sourceConfidence >= 0 &&
        sourceConfidence <= 1
          ? { value: sourceConfidence, unavailable_reason: null }
          : sourceConfidenceUnavailable();
      return availableTranscript("ocr", ocrText, evidenceIds, confidence);
    }
  }

  const omitGeneratedCaption = item.caption_generated === true;
  const sourceLabels = labels.filter(
    (label) => !(omitGeneratedCaption && label.role === "caption"),
  );
  const labelText = boundedOptionalTranscriptText(
    sourceLabels.map((label) => label.text).join("\n"),
  );
  if (labelText !== null) {
    const evidenceIds = transcriptEvidenceIds(labels, evidenceById, {
      omitGeneratedCaption,
    });
    if (evidenceIds.length > 0) {
      return availableTranscript(
        "source_labels",
        labelText,
        evidenceIds,
        sourceConfidenceUnavailable(),
      );
    }
  }
  return {
    status: "unavailable",
    source: null,
    text: null,
    text_sha256: null,
    evidence_ids: [],
    confidence: sourceConfidenceUnavailable(),
  };
}

function sameTranscript(
  actual: ChartTranscript,
  expected: ChartTranscript,
): boolean {
  return (
    actual.status === expected.status &&
    actual.source === expected.source &&
    actual.text === expected.text &&
    actual.text_sha256 === expected.text_sha256 &&
    sameStrings(actual.evidence_ids, expected.evidence_ids) &&
    sameConfidence(actual.confidence, expected.confidence)
  );
}

function parseFamily(
  value: unknown,
  path: string,
): ChartFamilyClassification {
  const record = exactRecord(value, path, FAMILY_KEYS);
  const status = oneOf(record.status, FAMILY_STATUS, `${path}.status`);
  const family = oneOf(record.family, FAMILY, `${path}.family`);
  if (record.classifier_version !== "chart-family-source-evidence-v1") {
    invalid(`${path}.classifier_version`, "has an unsupported policy");
  }
  const reasons = stringArray(
    record.reason_codes,
    `${path}.reason_codes`,
    1,
    8,
    FAMILY_REASON,
  );
  const evidenceIds = stringArray(record.evidence_ids, `${path}.evidence_ids`, 0, 64);
  const confidence = parseConfidence(record.confidence, `${path}.confidence`);
  if (
    (status === "classified" && family === "undetermined") ||
    (status !== "classified" && family !== "undetermined")
  ) {
    invalid(path, "has inconsistent classification and family states");
  }
  if (
    status === "not_run" &&
    (!sameStrings(reasons, ["asset_unavailable"]) ||
      evidenceIds.length !== 0 ||
      confidence.value !== null ||
      confidence.unavailable_reason !== "asset_unavailable")
  ) {
    invalid(path, "has inconsistent not-run evidence");
  }
  if (
    status === "undetermined" &&
    !sameStrings(reasons, ["insufficient_source_features"]) &&
    !sameStrings(reasons, ["multiple_family_signals"])
  ) {
    invalid(path, "has inconsistent undetermined reasons");
  }
  return {
    status,
    family,
    classifier_version: "chart-family-source-evidence-v1",
    reason_codes: reasons,
    evidence_ids: evidenceIds,
    confidence,
  };
}

function parseComplexity(
  value: unknown,
  path: string,
): ChartComplexityClassification {
  const record = exactRecord(value, path, COMPLEXITY_KEYS);
  const status = oneOf(record.status, COMPLEXITY_STATUS, `${path}.status`);
  if (record.classifier_version !== "chart-complexity-source-evidence-v1") {
    invalid(`${path}.classifier_version`, "has an unsupported policy");
  }
  const reasons = stringArray(
    record.reason_codes,
    `${path}.reason_codes`,
    1,
    8,
    COMPLEXITY_REASON,
  );
  const evidenceIds = stringArray(record.evidence_ids, `${path}.evidence_ids`, 0, 64);
  const confidence = parseConfidence(record.confidence, `${path}.confidence`);
  if (status === "complex" && !reasons.some((reason) => COMPLEX_REASONS.has(reason))) {
    invalid(path, "lacks a complex source feature");
  }
  if (status === "regular" && !sameStrings(reasons, ["single_supported_family"])) {
    invalid(path, "has inconsistent regular reasons");
  }
  if (
    status === "undetermined" &&
    !sameStrings(reasons, ["insufficient_source_features"])
  ) {
    invalid(path, "has inconsistent undetermined reasons");
  }
  if (
    status === "not_run" &&
    (!sameStrings(reasons, ["asset_unavailable"]) ||
      evidenceIds.length !== 0 ||
      confidence.value !== null ||
      confidence.unavailable_reason !== "asset_unavailable")
  ) {
    invalid(path, "has inconsistent not-run evidence");
  }
  return {
    status,
    classifier_version: "chart-complexity-source-evidence-v1",
    reason_codes: reasons,
    evidence_ids: evidenceIds,
    confidence,
  };
}

function parseSemanticAnalysis(
  value: unknown,
  path: string,
): ChartSemanticAnalysis {
  const record = exactRecord(value, path, SEMANTIC_KEYS);
  if (record.capability_matrix_version !== "chart-semantic-capabilities-v1") {
    invalid(`${path}.capability_matrix_version`, "has an unsupported policy");
  }
  const attempt = oneOf(record.attempt_status, ATTEMPT_STATUS, `${path}.attempt_status`);
  const analyzers = stringArray(record.analyzer_ids, `${path}.analyzer_ids`, 0, 16);
  const configurationDigest = sha256(
    record.configuration_sha256,
    `${path}.configuration_sha256`,
  );
  const gate = oneOf(
    record.completeness_gate_status,
    GATE_STATUS,
    `${path}.completeness_gate_status`,
  );
  const required = stringArray<ChartSemanticFeature>(
    record.required_features,
    `${path}.required_features`,
    0,
    16,
    SEMANTIC_FEATURE,
  );
  const observed = stringArray<ChartSemanticFeature>(
    record.observed_features,
    `${path}.observed_features`,
    0,
    16,
    SEMANTIC_FEATURE,
  );
  const missing = stringArray<ChartSemanticFeature>(
    record.missing_features,
    `${path}.missing_features`,
    0,
    16,
    SEMANTIC_FEATURE,
  );
  const ambiguous = stringArray(
    record.ambiguous_evidence_ids,
    `${path}.ambiguous_evidence_ids`,
    0,
    64,
  );
  const failure =
    record.failure_reason === null
      ? null
      : oneOf(record.failure_reason, FAILURE_REASON, `${path}.failure_reason`);
  const expectedMissing = required.filter((feature) => !observed.includes(feature));
  if (!sameStringSet(missing, expectedMissing)) {
    invalid(`${path}.missing_features`, "differs from required minus observed");
  }
  const notRun = attempt.startsWith("not_run_");
  if (
    notRun &&
    (analyzers.length !== 0 ||
      gate !== "not_run" ||
      required.length !== 0 ||
      observed.length !== 0 ||
      missing.length !== 0 ||
      ambiguous.length !== 0 ||
      (failure !== "unsupported" && failure !== "asset_unavailable"))
  ) {
    invalid(path, "has inconsistent not-run semantic evidence");
  }
  if (!notRun && (analyzers.length === 0 || required.length === 0)) {
    invalid(path, "has no capability evidence for an attempted analysis");
  }
  if (
    gate === "passed" &&
    (attempt !== "completed" || missing.length !== 0 || failure !== null)
  ) {
    invalid(path, "has inconsistent passed-gate state");
  }
  if (gate === "failed" && (missing.length === 0 || failure === null)) {
    invalid(path, "has inconsistent failed-gate state");
  }
  return {
    capability_matrix_version: "chart-semantic-capabilities-v1",
    attempt_status: attempt,
    analyzer_ids: analyzers,
    configuration_sha256: configurationDigest,
    completeness_gate_status: gate,
    required_features: required,
    observed_features: observed,
    missing_features: missing,
    ambiguous_evidence_ids: ambiguous,
    failure_reason: failure,
  };
}

function parseAsset(
  value: unknown,
  path: string,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ChartSourceAsset {
  const record = exactRecord(value, path, ASSET_KEYS);
  const assetId = boundedString(record.asset_id, `${path}.asset_id`, 1, 128);
  if (!ASSET_ID.test(assetId)) invalid(`${path}.asset_id`, "has an invalid identity");
  const sourceDigest = sha256(
    record.source_document_sha256,
    `${path}.source_document_sha256`,
  );
  const renderDigest = sha256(
    record.render_source_sha256,
    `${path}.render_source_sha256`,
  );
  if (sourceSha256 !== undefined && sourceDigest !== sourceSha256) {
    invalid(path, "does not belong to the active source document");
  }
  if (renderSourceSha256 !== undefined && renderDigest !== renderSourceSha256) {
    invalid(path, "does not belong to the active render source");
  }
  const ownerItemId = boundedString(record.owner_item_id, `${path}.owner_item_id`, 1, 512);
  const physicalPage = integer(record.physical_page, `${path}.physical_page`, 1, 1_000_000);
  const sourceBBox = parseBoundingBox(record.source_bbox, `${path}.source_bbox`, true);
  const ownerGeometryProofKind = oneOf(
    record.owner_geometry_proof_kind,
    OWNER_GEOMETRY_PROOF_KIND,
    `${path}.owner_geometry_proof_kind`,
  );
  const ownerGeometryEvidenceIds = stringArray(
    record.owner_geometry_evidence_ids,
    `${path}.owner_geometry_evidence_ids`,
    1,
    2,
  );
  const expectedOwnerGeometryEvidenceCount =
    ownerGeometryProofKind === "detected_image_and_docling_picture" ? 2 : 1;
  if (ownerGeometryEvidenceIds.length !== expectedOwnerGeometryEvidenceCount) {
    invalid(
      `${path}.owner_geometry_evidence_ids`,
      "differs from the declared proof kind",
    );
  }
  const ownerGeometryEvidenceSha256 = sha256(
    record.owner_geometry_evidence_sha256,
    `${path}.owner_geometry_evidence_sha256`,
  );
  const renderedBBox = parseBoundingBox(record.rendered_bbox, `${path}.rendered_bbox`, true);
  if (renderedBBox.unit !== sourceBBox.unit) {
    invalid(`${path}.rendered_bbox.unit`, "differs from source geometry");
  }
  if (record.coordinate_system !== "page_top_left") {
    invalid(`${path}.coordinate_system`, "has an unsupported coordinate system");
  }
  const transformValues = exactArray(
    record.pixel_to_page_transform,
    `${path}.pixel_to_page_transform`,
    6,
  );
  if (transformValues.length !== 6) {
    invalid(`${path}.pixel_to_page_transform`, "must have six values");
  }
  const transform = transformValues.map((entry, index) =>
    finiteNumber(entry, `${path}.pixel_to_page_transform.${index}`, -Number.MAX_VALUE, Number.MAX_VALUE),
  ) as [number, number, number, number, number, number];
  const deviceDimensionsRaw =
    record.page_device_dimensions === null
      ? null
      : exactArray(record.page_device_dimensions, `${path}.page_device_dimensions`, 2);
  if (deviceDimensionsRaw !== null && deviceDimensionsRaw.length !== 2) {
    invalid(`${path}.page_device_dimensions`, "must have two values");
  }
  const pageDeviceDimensions =
    deviceDimensionsRaw === null
      ? null
      : (deviceDimensionsRaw.map((entry, index) =>
          integer(
            entry,
            `${path}.page_device_dimensions.${index}`,
            0,
            Number.MAX_SAFE_INTEGER,
          ),
        ) as [number, number]);
  const cropMarginsRaw =
    record.crop_device_margins === null
      ? null
      : exactArray(record.crop_device_margins, `${path}.crop_device_margins`, 4);
  if (cropMarginsRaw !== null && cropMarginsRaw.length !== 4) {
    invalid(`${path}.crop_device_margins`, "must have four values");
  }
  const cropDeviceMargins =
    cropMarginsRaw === null
      ? null
      : (cropMarginsRaw.map((entry, index) =>
          integer(
            entry,
            `${path}.crop_device_margins.${index}`,
            0,
            Number.MAX_SAFE_INTEGER,
          ),
        ) as [number, number, number, number]);
  const renderer = oneOf(record.renderer, ["pypdfium2", "pillow"] as const, `${path}.renderer`);
  const rendererVersion = boundedString(record.renderer_version, `${path}.renderer_version`, 1, 64);
  if (record.render_policy !== "chart-source-inline-png-v1") {
    invalid(`${path}.render_policy`, "has an unsupported policy");
  }
  const sourceKind = oneOf(record.source_kind, ["pdf", "image"] as const, `${path}.source_kind`);
  const renderScale = finiteNumber(record.render_scale, `${path}.render_scale`, Number.MIN_VALUE, 16);
  const effectiveDpi =
    record.effective_dpi === null
      ? null
      : finiteNumber(record.effective_dpi, `${path}.effective_dpi`, Number.MIN_VALUE, 1_152);
  const width = integer(record.width, `${path}.width`, 1, 8_192);
  const height = integer(record.height, `${path}.height`, 1, 8_192);
  if (width * height > MAX_ASSET_PIXELS) invalid(path, "exceeds the pixel cap");
  if (record.mime_type !== "image/png" || record.encoding !== "data_uri_base64") {
    invalid(path, "does not declare an inline PNG");
  }
  const byteLength = integer(record.byte_length, `${path}.byte_length`, 1, MAX_ASSET_BYTES);
  const digest = sha256(record.sha256, `${path}.sha256`);
  const dataUri = boundedString(
    record.data_uri,
    `${path}.data_uri`,
    PNG_PREFIX.length + 4,
    MAX_DATA_URI_LENGTH,
  );
  if (!dataUri.startsWith(PNG_PREFIX)) invalid(`${path}.data_uri`, "is not an inline PNG");
  const bytes = decodeBase64(dataUri.slice(PNG_PREFIX.length), `${path}.data_uri`);
  if (bytes.length !== byteLength) invalid(`${path}.byte_length`, "differs from decoded data");
  if (sha256Hex(bytes) !== digest) invalid(`${path}.sha256`, "differs from decoded data");
  const dimensions = pngDimensions(bytes, `${path}.data_uri`);
  if (dimensions.width !== width || dimensions.height !== height) {
    invalid(`${path}.data_uri`, "IHDR dimensions differ from declared dimensions");
  }
  if (
    record.color_space !== "srgb" ||
    record.alpha_policy !== "flatten_white" ||
    record.antialiasing_policy !== "renderer_default" ||
    record.interpolation_policy !== "none" ||
    record.padding !== 0
  ) {
    invalid(path, "has unsupported pixel policy metadata");
  }
  const bboxRounding = oneOf(
    record.bbox_rounding,
    ["outward_device_pixels", "exact_integer"] as const,
    `${path}.bbox_rounding`,
  );
  const expectedTransform = [
    renderedBBox.width / width,
    0,
    0,
    renderedBBox.height / height,
    renderedBBox.x,
    renderedBBox.y,
  ];
  if (
    transform.some(
      (entry, index) => Math.abs(entry - (expectedTransform[index] ?? Number.NaN)) > 1e-9,
    )
  ) {
    invalid(`${path}.pixel_to_page_transform`, "differs from the page mapping");
  }
  if (
    sourceKind === "pdf" &&
    (renderer !== "pypdfium2" ||
      bboxRounding !== "outward_device_pixels" ||
      sourceBBox.unit !== "pt" ||
      effectiveDpi === null ||
      pageDeviceDimensions === null ||
      cropDeviceMargins === null ||
      Math.abs(effectiveDpi - renderScale * 72) > 1e-9)
  ) {
    invalid(path, "has inconsistent PDF render metadata");
  }
  if (sourceKind === "pdf") {
    if (pageDeviceDimensions === null || cropDeviceMargins === null) {
      invalid(path, "lacks PDF device crop metadata");
    }
    const [pageDeviceWidth, pageDeviceHeight] = pageDeviceDimensions;
    const [left, bottom, right, top] = cropDeviceMargins;
    if (
      pageDeviceWidth < 1 ||
      pageDeviceHeight < 1 ||
      width !== pageDeviceWidth - left - right ||
      height !== pageDeviceHeight - bottom - top
    ) {
      invalid(path, "has inconsistent PDF device crop dimensions");
    }
    const pixelSize = 1 / renderScale;
    if (
      renderedBBox.x > sourceBBox.x ||
      renderedBBox.y > sourceBBox.y ||
      renderedBBox.x + renderedBBox.width < sourceBBox.x + sourceBBox.width ||
      renderedBBox.y + renderedBBox.height < sourceBBox.y + sourceBBox.height ||
      sourceBBox.x - renderedBBox.x >= pixelSize + 1e-9 ||
      sourceBBox.y - renderedBBox.y >= pixelSize + 1e-9 ||
      renderedBBox.x + renderedBBox.width - sourceBBox.x - sourceBBox.width >=
        pixelSize + 1e-9 ||
      renderedBBox.y + renderedBBox.height - sourceBBox.y - sourceBBox.height >=
        pixelSize + 1e-9
    ) {
      invalid(`${path}.rendered_bbox`, "does not tightly cover source geometry");
    }
  }
  if (
    sourceKind === "image" &&
    (renderer !== "pillow" ||
      bboxRounding !== "exact_integer" ||
      sourceBBox.unit !== "px" ||
      effectiveDpi !== null ||
      pageDeviceDimensions !== null ||
      cropDeviceMargins !== null ||
      !sameBoundingBox(renderedBBox, sourceBBox) ||
      renderScale !== 1)
  ) {
    invalid(path, "has inconsistent image render metadata");
  }
  const parsedAsset: ChartSourceAsset = {
    asset_id: assetId,
    source_document_sha256: sourceDigest,
    render_source_sha256: renderDigest,
    owner_item_id: ownerItemId,
    physical_page: physicalPage,
    source_bbox: sourceBBox,
    owner_geometry_proof_kind: ownerGeometryProofKind,
    owner_geometry_evidence_ids: ownerGeometryEvidenceIds,
    owner_geometry_evidence_sha256: ownerGeometryEvidenceSha256,
    rendered_bbox: renderedBBox,
    coordinate_system: "page_top_left",
    pixel_to_page_transform: transform,
    page_device_dimensions: pageDeviceDimensions,
    crop_device_margins: cropDeviceMargins,
    renderer,
    renderer_version: rendererVersion,
    render_policy: "chart-source-inline-png-v1",
    source_kind: sourceKind,
    render_scale: renderScale,
    effective_dpi: effectiveDpi,
    width,
    height,
    mime_type: "image/png",
    encoding: "data_uri_base64",
    byte_length: byteLength,
    sha256: digest,
    data_uri: dataUri,
    color_space: "srgb",
    alpha_policy: "flatten_white",
    antialiasing_policy: "renderer_default",
    interpolation_policy: "none",
    bbox_rounding: bboxRounding,
    padding: 0,
  };
  if (assetId !== replayChartSourceAssetId(parsedAsset)) {
    invalid(`${path}.asset_id`, "differs from the public custody tuple");
  }
  return parsedAsset;
}

function captionFor(item: DocumentContentItem): string {
  const caption = item.caption;
  if (caption === undefined || caption === null) return "";
  if (typeof caption !== "string") invalid("owner.caption", "must be a source string");
  return pythonStrip(caption);
}

function groundedPredecessorText(item: DocumentContentItem): string | null {
  for (const key of ["value", "text", "md"] as const) {
    const value = item[key];
    if (value === undefined || value === null || value === "") continue;
    if (typeof value !== "string") return null;
    const cleaned = pythonStrip(value);
    if (cleaned) return cleaned;
  }
  const caption = item.caption;
  if (caption === undefined || caption === null || caption === "") return "";
  return typeof caption === "string" ? pythonStrip(caption) : null;
}

/** Reproduce the backend's one permitted source-image Markdown reference. */
export function replayChartResolutionMarkdown(
  resolution: ChartResolution,
  caption: string | null | undefined,
): string | null {
  if (resolution.primary_representation !== "source_image" || resolution.asset === null) {
    return null;
  }
  const alt = (caption ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("[", "\\[")
    .replaceAll("]", "\\]")
    .replaceAll("\r", " ")
    .replaceAll("\n", " ");
  return `![${alt}](${resolution.asset.data_uri})`;
}

function parseResolution(
  value: unknown,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ChartResolution {
  const record = exactRecord(value, "chart_resolution", RESOLUTION_KEYS);
  if (record.schema_version !== "1.0" || record.policy_id !== "ffd-015-chart-source-asset-v1") {
    invalid("chart_resolution", "has an unsupported schema or policy");
  }
  const ownerItemId = boundedString(record.owner_item_id, "chart_resolution.owner_item_id", 1, 512);
  const pageIndex = integer(record.page_index, "chart_resolution.page_index", 1, 1_000_000);
  const sourceOrder = integer(record.source_order, "chart_resolution.source_order", 0, 1_000_000);
  const sourceBBox = parseBoundingBox(record.source_bbox, "chart_resolution.source_bbox");
  const status = oneOf(record.status, STATUS, "chart_resolution.status");
  const assetStatus = oneOf(record.asset_status, ASSET_STATUS, "chart_resolution.asset_status");
  const unavailableReason =
    record.asset_unavailable_reason === null
      ? null
      : oneOf(
          record.asset_unavailable_reason,
          ASSET_UNAVAILABLE_REASON,
          "chart_resolution.asset_unavailable_reason",
        );
  const asset =
    record.asset === null
      ? null
      : parseAsset(
          record.asset,
          "chart_resolution.asset",
          sourceSha256,
          renderSourceSha256,
        );
  const family = parseFamily(
    record.family_classification,
    "chart_resolution.family_classification",
  );
  const complexity = parseComplexity(
    record.complexity_classification,
    "chart_resolution.complexity_classification",
  );
  const semantic = parseSemanticAnalysis(
    record.semantic_analysis,
    "chart_resolution.semantic_analysis",
  );
  const primaryRepresentation = oneOf(
    record.primary_representation,
    PRIMARY_REPRESENTATION,
    "chart_resolution.primary_representation",
  );
  const primaryReason = oneOf(
    record.primary_reason,
    PRIMARY_REASON,
    "chart_resolution.primary_reason",
  );
  const transcript = parseTranscript(record.transcript, "chart_resolution.transcript");
  const confidenceRecord = exactRecord(
    record.confidence_dimensions,
    "chart_resolution.confidence_dimensions",
    CONFIDENCE_DIMENSION_KEYS,
  );
  const confidenceDimensions = {
    ownership: parseConfidence(
      confidenceRecord.ownership,
      "chart_resolution.confidence_dimensions.ownership",
    ),
    transcription: parseConfidence(
      confidenceRecord.transcription,
      "chart_resolution.confidence_dimensions.transcription",
    ),
    family: parseConfidence(
      confidenceRecord.family,
      "chart_resolution.confidence_dimensions.family",
    ),
    complexity: parseConfidence(
      confidenceRecord.complexity,
      "chart_resolution.confidence_dimensions.complexity",
    ),
  };
  if (
    !sameConfidence(confidenceDimensions.transcription, transcript.confidence) ||
    !sameConfidence(confidenceDimensions.family, family.confidence) ||
    !sameConfidence(confidenceDimensions.complexity, complexity.confidence)
  ) {
    invalid("chart_resolution.confidence_dimensions", "differs from its source records");
  }
  const concerns = stringArray(
    record.concern_codes,
    "chart_resolution.concern_codes",
    0,
    8,
    CONCERN_CODE,
  );
  if (assetStatus === "retained") {
    if (
      asset === null ||
      unavailableReason !== null ||
      asset.owner_item_id !== ownerItemId ||
      asset.physical_page !== pageIndex ||
      !sameBoundingBox(asset.source_bbox, sourceBBox)
    ) {
      invalid("chart_resolution.asset", "has inconsistent retained ownership");
    }
  } else if (asset !== null || unavailableReason === null) {
    invalid("chart_resolution.asset", "has inconsistent unavailable state");
  }
  const expected = TERMINAL_STATE[status];
  if (
    assetStatus !== expected[0] ||
    primaryRepresentation !== expected[1] ||
    primaryReason !== expected[2] ||
    (expected[3] !== null && semantic.attempt_status !== expected[3]) ||
    semantic.completeness_gate_status !== expected[4]
  ) {
    invalid("chart_resolution", "has inconsistent terminal authority");
  }
  if (
    status === "image_primary_incomplete" &&
    !(["completed", "failed", "timed_out", "resource_refused"] as const).includes(
      semantic.attempt_status as "completed",
    )
  ) {
    invalid("chart_resolution.semantic_analysis.attempt_status", "is not an incomplete attempt");
  }
  if (
    semantic.attempt_status === "not_run_no_approved_analyzer" &&
    semantic.failure_reason !== "unsupported"
  ) {
    invalid("chart_resolution.semantic_analysis.failure_reason", "must record unsupported analysis");
  }
  if (
    semantic.attempt_status === "not_run_asset_unavailable" &&
    semantic.failure_reason !== "asset_unavailable"
  ) {
    invalid("chart_resolution.semantic_analysis.failure_reason", "must record unavailable asset");
  }
  const classificationsNotRun =
    family.status === "not_run" || complexity.status === "not_run";
  if (classificationsNotRun !== (status === "asset_unavailable")) {
    invalid("chart_resolution", "has inconsistent classification dispatch");
  }
  if (
    status === "asset_unavailable" &&
    (confidenceDimensions.ownership.value !== null ||
      confidenceDimensions.ownership.unavailable_reason !== "asset_unavailable")
  ) {
    invalid("chart_resolution.confidence_dimensions.ownership", "must record asset unavailability");
  }
  const expectedConcerns: string[] = [];
  if (family.status === "undetermined") expectedConcerns.push("chart_family_undetermined");
  if (complexity.status === "undetermined") {
    expectedConcerns.push("chart_complexity_undetermined");
  }
  if (status === "image_primary_unsupported") {
    expectedConcerns.push("chart_semantics_unsupported");
  } else if (status === "image_primary_incomplete") {
    expectedConcerns.push("chart_semantics_incomplete");
  } else if (status === "asset_unavailable") {
    expectedConcerns.push("chart_source_asset_unavailable");
  }
  if (!sameStrings(concerns, expectedConcerns)) {
    invalid("chart_resolution.concern_codes", "differs from terminal uncertainty");
  }
  return {
    schema_version: "1.0",
    policy_id: "ffd-015-chart-source-asset-v1",
    owner_item_id: ownerItemId,
    page_index: pageIndex,
    source_order: sourceOrder,
    source_bbox: sourceBBox,
    status,
    asset_status: assetStatus,
    asset_unavailable_reason: unavailableReason,
    asset,
    family_classification: family,
    complexity_classification: complexity,
    semantic_analysis: semantic,
    primary_representation: primaryRepresentation,
    primary_reason: primaryReason,
    transcript,
    confidence_dimensions: confidenceDimensions,
    concern_codes: concerns,
  };
}

function itemBoundingBox(item: DocumentContentItem): VisualBoundingBox {
  const raw = looseRecord(item.bbox, "owner.bbox");
  return {
    x: finiteNumber(raw.x, "owner.bbox.x", 0, Number.MAX_VALUE),
    y: finiteNumber(raw.y, "owner.bbox.y", 0, Number.MAX_VALUE),
    width: finiteNumber(raw.width, "owner.bbox.width", 0, Number.MAX_VALUE),
    height: finiteNumber(raw.height, "owner.bbox.height", 0, Number.MAX_VALUE),
    unit: oneOf(raw.unit, ["pt", "px"] as const, "owner.bbox.unit"),
  };
}

function validateOwnerBinding(
  item: DocumentContentItem,
  page: PageResult,
  resolution: ChartResolution,
): { markdown: string | null; captionOccurrences: 0 | 1 } {
  if (item.type !== "chart" || typeof item.id !== "string" || !item.id) {
    invalid("owner", "must be a chart item with an identity");
  }
  if (
    resolution.owner_item_id !== item.id ||
    !Number.isInteger(item.reading_order)
  ) {
    invalid("owner", "identity or final reading order is invalid");
  }
  if (
    !Number.isInteger(page.page_index) ||
    resolution.page_index !== page.page_index ||
    !Number.isFinite(page.page_width) ||
    !Number.isFinite(page.page_height) ||
    page.page_width <= 0 ||
    page.page_height <= 0 ||
    page.unit !== resolution.source_bbox.unit ||
    resolution.source_bbox.x + resolution.source_bbox.width > page.page_width ||
    resolution.source_bbox.y + resolution.source_bbox.height > page.page_height
  ) {
    invalid("owner", "does not bind to the active physical page");
  }
  const ownerBox = itemBoundingBox(item);
  if (!sameBoundingBox(ownerBox, resolution.source_bbox)) {
    invalid("owner.bbox", "differs from chart resolution geometry");
  }
  const structure = looseRecord(item.visual_structure, "owner.visual_structure");
  const region = looseRecord(structure.region, "owner.visual_structure.region");
  if (region.kind !== "chart") invalid("owner.visual_structure.region.kind", "must be chart");
  const regionBox = parseBoundingBox(
    region.page_bbox,
    "owner.visual_structure.region.page_bbox",
  );
  if (!sameBoundingBox(regionBox, resolution.source_bbox)) {
    invalid("owner.visual_structure.region.page_bbox", "differs from chart resolution geometry");
  }
  const expectedTranscript = replayOwnerTranscript(item, structure);
  if (!sameTranscript(resolution.transcript, expectedTranscript)) {
    invalid(
      "chart_resolution.transcript",
      "differs from its source-grounded owner replay",
    );
  }
  const fallback = looseRecord(structure.fallback, "owner.visual_structure.fallback");
  if (typeof fallback.active !== "boolean") {
    invalid("owner.visual_structure.fallback.active", "must be boolean");
  }
  const serialization = structure.serialization;
  const structured =
    fallback.active === false &&
    isPlainRecord(serialization) &&
    serialization.status === "structured_chart";
  if (resolution.status === "structured_primary" && !structured) {
    invalid("owner.visual_structure", "does not prove complete structured authority");
  }
  if (resolution.status === "asset_unavailable" && fallback.active !== true) {
    invalid("owner.visual_structure.fallback", "is not active for predecessor authority");
  }
  if (resolution.status !== "structured_primary") {
    return { markdown: null, captionOccurrences: 0 };
  }

  const serialized = exactRecord(
    serialization,
    "owner.visual_structure.serialization",
    VISUAL_SERIALIZATION_KEYS,
  );
  if (serialized.status !== "structured_chart") {
    invalid(
      "owner.visual_structure.serialization.status",
      "must select structured chart authority",
    );
  }
  const markdown = boundedString(
    serialized.markdown,
    "owner.visual_structure.serialization.markdown",
    1,
    262_144,
  );
  const captionOccurrences = integer(
    serialized.caption_occurrences,
    "owner.visual_structure.serialization.caption_occurrences",
    0,
    1,
  ) as 0 | 1;
  const rowCount = integer(
    serialized.row_count,
    "owner.visual_structure.serialization.row_count",
    1,
    1_024,
  );
  const points = exactArray(
    structure.points,
    "owner.visual_structure.points",
    1_024,
  );
  if (points.length !== rowCount) {
    invalid(
      "owner.visual_structure.serialization.row_count",
      "differs from structured point authority",
    );
  }
  const ownerCaption = captionFor(item);
  if (ownerCaption && captionOccurrences !== 1) {
    invalid(
      "owner.visual_structure.serialization.caption_occurrences",
      "does not retain the owner caption exactly once",
    );
  }
  if (ownerCaption) {
    const escapedCaption = ownerCaption
      .replaceAll("\\", "\\\\")
      .replaceAll("|", "\\|")
      .replaceAll("\r\n", "<br>")
      .replaceAll("\r", "<br>")
      .replaceAll("\n", "<br>")
      .trim();
    if (!markdown.startsWith(`${escapedCaption}\n\n`)) {
      invalid(
        "owner.visual_structure.serialization.markdown",
        "does not replay its declared caption",
      );
    }
  }
  return { markdown, captionOccurrences };
}

/**
 * Strictly validate and bind one additive chart-resolution sidecar.
 *
 * The source document digest is optional only because raw component tests and
 * older callers may not own document context. When supplied it is mandatory,
 * well-formed, and must match both asset custody digests.
 */
export function validateChartResolution(
  item: DocumentContentItem,
  page: PageResult,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ValidatedChartResolution {
  let sourceDigest: string | undefined;
  if (sourceSha256 !== undefined && sourceSha256 !== "") {
    sourceDigest = sha256(sourceSha256, "sourceSha256");
  }
  let renderSourceDigest = sourceDigest;
  if (renderSourceSha256 !== undefined && renderSourceSha256 !== "") {
    renderSourceDigest = sha256(renderSourceSha256, "renderSourceSha256");
  }
  if (!Object.hasOwn(item, "chart_resolution") || item.chart_resolution == null) {
    invalid("chart_resolution", "is absent");
  }
  const resolution = parseResolution(
    item.chart_resolution,
    sourceDigest,
    renderSourceDigest,
  );
  const structured = validateOwnerBinding(item, page, resolution);
  const caption = captionFor(item);
  const imageMarkdown = replayChartResolutionMarkdown(resolution, caption);
  const predecessorText = groundedPredecessorText(item);
  const primaryText =
    resolution.primary_representation === "structured_chart"
      ? structured.markdown
      : resolution.primary_representation === "source_image" &&
          resolution.transcript.status === "available"
        ? resolution.transcript.text
        : predecessorText;
  return {
    owner: item,
    resolution,
    asset: resolution.asset,
    caption,
    imageMarkdown,
    structuredMarkdown: structured.markdown,
    structuredCaptionOccurrences: structured.captionOccurrences,
    primaryText,
  };
}

const READ_CACHE = new WeakMap<
  DocumentContentItem,
  WeakMap<PageResult, Map<string, ValidatedChartResolution | null>>
>();

/** Fail-closed wrapper around the strict chart-resolution validator. */
export function readChartResolution(
  item: DocumentContentItem,
  page: PageResult,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ValidatedChartResolution | null {
  let pageCache = READ_CACHE.get(item);
  if (pageCache === undefined) {
    pageCache = new WeakMap();
    READ_CACHE.set(item, pageCache);
  }
  let contextCache = pageCache.get(page);
  if (contextCache === undefined) {
    contextCache = new Map();
    pageCache.set(page, contextCache);
  }
  const key = `${sourceSha256 ?? "\u0000"}\u0001${
    renderSourceSha256 ?? "\u0000"
  }`;
  if (contextCache.has(key)) return contextCache.get(key) ?? null;
  try {
    const validated = validateChartResolution(
      item,
      page,
      sourceSha256,
      renderSourceSha256,
    );
    const ownerMatches = page.items.filter(
      (entry) => entry.type === "chart" && entry.id === validated.owner.id,
    );
    const sourceSlotMatches = page.items.filter((entry) => {
      if (entry.type !== "chart" || !isPlainRecord(entry.chart_resolution)) {
        return false;
      }
      return (
        entry.chart_resolution.page_index === validated.resolution.page_index &&
        entry.chart_resolution.source_order === validated.resolution.source_order
      );
    });
    if (ownerMatches.length !== 1 || sourceSlotMatches.length !== 1) {
      invalid("owner", "identity or immutable source slot is not unique");
    }
    contextCache.set(key, validated);
    return validated;
  } catch (error) {
    if (!(error instanceof ChartResolutionValidationError)) throw error;
    contextCache.set(key, null);
    return null;
  }
}

/** Resolve only an image-primary state; structured/unavailable states stay on predecessor UI. */
export function readChartImageResolution(
  item: DocumentContentItem,
  page: PageResult,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ValidatedChartResolution | null {
  const validated = readChartResolution(
    item,
    page,
    sourceSha256,
    renderSourceSha256,
  );
  if (
    validated?.resolution.primary_representation !== "source_image" ||
    validated.asset === null ||
    validated.imageMarkdown === null
  ) {
    return null;
  }
  const ownerMatches = page.items.filter(
    (entry) => entry.type === "chart" && entry.id === validated.owner.id,
  );
  const sourceSlotMatches = page.items.filter((entry) => {
    if (entry.type !== "chart" || !isPlainRecord(entry.chart_resolution)) {
      return false;
    }
    return (
      entry.chart_resolution.page_index === validated.resolution.page_index &&
      entry.chart_resolution.source_order === validated.resolution.source_order
    );
  });
  return ownerMatches.length === 1 && sourceSlotMatches.length === 1
    ? validated
    : null;
}

function chartDomId(
  chart: ValidatedChartResolution,
  kind: "caption" | "content",
  discriminator: string,
): string {
  return `chart-${kind}-${sha256Hex(
    UTF8_ENCODER.encode(
      [
        chart.resolution.policy_id,
        chart.resolution.owner_item_id,
        chart.resolution.page_index,
        chart.resolution.source_order,
        chart.resolution.status,
        discriminator,
      ].join("\u0000"),
    ),
  ).slice(0, 24)}`;
}

/** Render exactly one already-validated terminal chart representation. */
export function renderValidatedChartResolution(
  chart: ValidatedChartResolution,
  linkedCaption: ChartCaptionPresentation | null = null,
): ReactNode {
  const asset = chart.asset;
  const linkedCaptionValid =
    linkedCaption !== null &&
    typeof linkedCaption.text === "string" &&
    pythonStrip(linkedCaption.text).length > 0 &&
    typeof linkedCaption.itemId === "string" &&
    linkedCaption.itemId.length > 0 &&
    linkedCaption.itemId.length <= 512 &&
    typeof linkedCaption.relationshipId === "string" &&
    /^layout-rel-[0-9a-f]{20}$/u.test(linkedCaption.relationshipId) &&
    (linkedCaption.placement === "before" ||
      linkedCaption.placement === "after");
  const caption = linkedCaptionValid
    ? pythonStrip(linkedCaption.text)
    : chart.caption;
  const serializationOwnsCaption =
    chart.resolution.primary_representation === "structured_chart" &&
    chart.structuredCaptionOccurrences === 1;
  const renderedCaption = serializationOwnsCaption ? "" : caption;
  const captionId = renderedCaption
    ? chartDomId(
        chart,
        "caption",
        linkedCaptionValid
          ? `${linkedCaption.relationshipId}\u0000${linkedCaption.itemId}`
          : renderedCaption,
      )
    : null;
  const accessibilityDisposition = serializationOwnsCaption
    ? "caption_in_serialization"
    : captionId === null
      ? chart.resolution.primary_representation === "source_image"
        ? "empty_alt"
        : "unlabelled"
      : "caption_labelledby";
  const contentDiscriminator =
    asset?.sha256 ?? chart.structuredMarkdown ?? chart.primaryText ?? "empty";
  const contentId = chartDomId(chart, "content", contentDiscriminator);
  const commonProperties = {
    "aria-describedby": serializationOwnsCaption ? contentId : undefined,
    "aria-labelledby":
      chart.resolution.primary_representation !== "source_image"
        ? captionId ?? undefined
        : undefined,
    className:
      chart.resolution.primary_representation === "source_image"
        ? "parsed-chart-image"
        : chart.resolution.primary_representation === "structured_chart"
          ? "parsed-chart-structure"
          : "parsed-chart-unavailable",
    "data-chart-accessibility-disposition": accessibilityDisposition,
    "data-chart-asset-id": asset?.asset_id,
    "data-chart-asset-sha256": asset?.sha256,
    "data-chart-caption-item-id": linkedCaptionValid
      ? linkedCaption.itemId
      : undefined,
    "data-chart-caption-relationship-id": linkedCaptionValid
      ? linkedCaption.relationshipId
      : undefined,
    "data-chart-owner-id": chart.owner.id,
    "data-chart-primary-representation":
      chart.resolution.primary_representation,
    "data-chart-resolution": chart.resolution.status,
    "data-chart-source-order": chart.resolution.source_order,
    "data-item-type": "chart",
  } as const;

  let primary: ReactNode;
  if (chart.resolution.primary_representation === "source_image") {
    if (asset === null || chart.imageMarkdown === null) return null;
    primary = createElement("img", {
      alt: "",
      "aria-labelledby": captionId ?? undefined,
      decoding: "async",
      height: asset.height,
      id: contentId,
      loading: "lazy",
      src: asset.data_uri,
      width: asset.width,
    });
  } else if (chart.resolution.primary_representation === "structured_chart") {
    if (chart.structuredMarkdown === null) return null;
    primary = createElement(
      "pre",
      {
        className: "parsed-chart-structure-content",
        id: contentId,
      },
      chart.structuredMarkdown,
    );
  } else {
    primary =
      chart.primaryText && chart.primaryText !== renderedCaption
        ? createElement("p", { id: contentId }, chart.primaryText)
        : null;
  }
  return createElement(
    "figure",
    commonProperties,
    captionId !== null && linkedCaption?.placement === "before"
      ? createElement("figcaption", { id: captionId }, renderedCaption)
      : null,
    primary,
    captionId !== null && linkedCaption?.placement !== "before"
      ? createElement("figcaption", { id: captionId }, renderedCaption)
      : null,
  );
}

function rawItemCouldClaimBlock(
  item: DocumentContentItem,
  block: CanonicalBlock,
): boolean {
  if (item.id === block.primary_element_id) return true;
  const raw = isPlainRecord(item.chart_resolution) ? item.chart_resolution : null;
  const transcript = raw && isPlainRecord(raw.transcript) ? raw.transcript : null;
  if (typeof transcript?.text === "string" && transcript.text === block.text) return true;
  const predecessor = groundedPredecessorText(item);
  if (predecessor !== null && predecessor === block.text) return true;
  const structure = isPlainRecord(item.visual_structure)
    ? item.visual_structure
    : null;
  const serialization =
    structure && isPlainRecord(structure.serialization)
      ? structure.serialization
      : null;
  if (
    typeof serialization?.markdown === "string" &&
    (serialization.markdown === block.markdown ||
      serialization.markdown === block.text)
  ) {
    return true;
  }
  const asset = raw && isPlainRecord(raw.asset) ? raw.asset : null;
  return (
    typeof asset?.data_uri === "string" &&
    block.markdown.includes(asset.data_uri)
  );
}

/**
 * Bind a canonical chart block to exactly one terminal chart sidecar.
 *
 * The image bytes alone are insufficient: both canonical projections must be
 * exact validator replays, and a non-identical IR/public identity may use the
 * text bridge only when that bridge is unique on the physical page.
 */
export function readChartResolutionForCanonicalBlock(
  block: CanonicalBlock,
  canonicalPage: CanonicalPage,
  sourcePage: PageResult,
  sourceSha256?: string,
  renderSourceSha256?: string,
): ValidatedChartResolution | null {
  if (
    block.primary_element_type !== "chart" ||
    block.scope !== "body" ||
    (block.omission_reason ?? null) !== null ||
    block.page_id !== canonicalPage.page_id ||
    canonicalPage.page_index !== sourcePage.page_index ||
    canonicalPage.blocks.filter((candidate) => candidate.id === block.id).length !== 1
  ) {
    return null;
  }
  const chartItems = sourcePage.items.filter((item) => item.type === "chart");
  if (
    new Set(chartItems.map((item) => item.id)).size !== chartItems.length ||
    chartItems.some((item) => typeof item.id !== "string" || !item.id)
  ) {
    return null;
  }
  const candidates: ValidatedChartResolution[] = [];
  for (const item of chartItems) {
    if (!Object.hasOwn(item, "chart_resolution")) continue;
    const validated = readChartResolution(
      item,
      sourcePage,
      sourceSha256,
      renderSourceSha256,
    );
    if (validated === null) {
      if (rawItemCouldClaimBlock(item, block)) return null;
      continue;
    }
    candidates.push(validated);
  }
  const exactCandidates = candidates.filter(
    (candidate) => {
      const expectedMarkdown =
        candidate.resolution.primary_representation === "source_image"
          ? candidate.imageMarkdown
          : candidate.resolution.primary_representation === "structured_chart"
            ? candidate.structuredMarkdown
            : candidate.primaryText;
      return (
        expectedMarkdown !== null &&
        expectedMarkdown === block.markdown &&
        candidate.primaryText !== null &&
        candidate.primaryText === block.text
      );
    },
  );
  if (exactCandidates.length !== 1) return null;
  const candidate = exactCandidates[0];
  if (candidate === undefined) return null;
  if (candidate.owner.id === block.primary_element_id) return candidate;
  const textMatches = candidates.filter(
    (entry) => entry.primaryText !== null && entry.primaryText === block.text,
  );
  return textMatches.length === 1 ? candidate : null;
}
