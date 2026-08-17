import type {
  CanonicalBlock,
  CanonicalBlockScope,
  CanonicalExcludedContribution,
  CanonicalExclusionReason,
  CanonicalOmissionReason,
  CanonicalPage,
  CanonicalPresentation,
  CanonicalView,
  PageResult,
  ParseResult,
} from "./types.ts";

type JsonRecord = Record<string, unknown>;

const VISUAL_TYPES = new Set(["image", "chart", "diagram"]);
const EXCLUSION_REASONS = new Set<CanonicalExclusionReason>([
  "already_claimed",
  "alternate_representation",
  "caption_precedes_subordinate_ocr",
  "empty_contribution",
  "evidence_only_relationship",
  "overlapping_visual_table",
  "rejected_caption",
  "rejected_ocr",
  "unapproved_caption",
  "unapproved_ocr",
]);
const OMISSION_REASONS = new Set<CanonicalOmissionReason>([
  "alternate_representation",
  "consumed_by_relationship",
  "empty_content",
  "empty_visual",
  "overlapping_visual_table",
  "source_contradicted_primary_ocr",
  "unsupported_primary_ocr",
]);
const SOURCE_CONTRADICTED_PRIMARY_TYPES = new Set(["text", "heading"]);
const SCOPES = new Set<CanonicalBlockScope>(["body", "header", "footer"]);
const PYTHON_EDGE_WHITESPACE =
  /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;

export class CanonicalPresentationError extends Error {
  constructor(message: string) {
    super(`Invalid canonical_presentation: ${message}`);
    this.name = "CanonicalPresentationError";
  }
}

function invalid(path: string, message: string): never {
  throw new CanonicalPresentationError(`${path} ${message}`);
}

function isRecord(value: unknown): value is JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordAt(value: unknown, path: string): JsonRecord {
  if (!isRecord(value)) invalid(path, "must be an object");
  return value;
}

function requireExactKeys(
  record: JsonRecord,
  keys: readonly string[],
  path: string,
  optionalKeys: readonly string[] = [],
): void {
  const expected = new Set([...keys, ...optionalKeys]);
  for (const key of keys) {
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

function stringAt(value: unknown, path: string): string {
  if (typeof value !== "string") invalid(path, "must be a string");
  return value;
}

function integerAt(value: unknown, path: string, minimum?: number): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    invalid(path, "must be an integer");
  }
  if (minimum !== undefined && value < minimum) {
    invalid(path, `must be at least ${minimum}`);
  }
  return value;
}

function pageNumberAt(value: unknown, path: string): number | string {
  if (typeof value === "string") return value;
  return integerAt(value, path);
}

function arrayAt(value: unknown, path: string): unknown[] {
  if (!Array.isArray(value)) invalid(path, "must be an array");
  return value;
}

function uniqueStringsAt(value: unknown, path: string): string[] {
  const values = arrayAt(value, path).map((entry, index) =>
    stringAt(entry, `${path}[${index}]`),
  );
  if (new Set(values).size !== values.length) {
    invalid(path, "must not repeat values");
  }
  return values;
}

function requireUnique<Value extends string | number>(
  values: readonly Value[],
  path: string,
): void {
  if (new Set(values).size !== values.length) {
    invalid(path, "must not repeat values");
  }
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

export function pythonStrip(value: string): string {
  return value.replace(PYTHON_EDGE_WHITESPACE, "");
}

function renderValues(values: readonly string[]): string {
  const cleaned = values.map(pythonStrip).filter(Boolean);
  return cleaned.length ? `${cleaned.join("\n\n")}\n` : "";
}

function validateExcludedContribution(
  value: unknown,
  path: string,
  blockRelationshipIds: ReadonlySet<string>,
): CanonicalExcludedContribution {
  const record = recordAt(value, path);
  requireExactKeys(record, ["element_id", "reason", "relationship_ids"], path);
  stringAt(record.element_id, `${path}.element_id`);
  const reason = stringAt(record.reason, `${path}.reason`);
  if (!EXCLUSION_REASONS.has(reason as CanonicalExclusionReason)) {
    invalid(`${path}.reason`, "is unsupported");
  }
  const relationshipIds = uniqueStringsAt(
    record.relationship_ids,
    `${path}.relationship_ids`,
  );
  if (relationshipIds.some((id) => !blockRelationshipIds.has(id))) {
    invalid(
      `${path}.relationship_ids`,
      "must be recorded by the containing block",
    );
  }
  return record as unknown as CanonicalExcludedContribution;
}

function expectedScope(primaryElementType: string): CanonicalBlockScope {
  const type = primaryElementType.toLowerCase();
  if (type === "header") return "header";
  if (type === "footer") return "footer";
  return "body";
}

function validateBlock(value: unknown, path: string): CanonicalBlock {
  const record = recordAt(value, path);
  requireExactKeys(
    record,
    [
      "id",
      "page_id",
      "primary_element_id",
      "primary_element_type",
      "scope",
      "markdown",
      "text",
      "contributing_element_ids",
      "relationship_ids",
      "excluded_contributions",
    ],
    path,
    ["omission_reason", "suppressed_by_element_id"],
  );
  const id = stringAt(record.id, `${path}.id`);
  const pageId = stringAt(record.page_id, `${path}.page_id`);
  const primaryElementId = stringAt(
    record.primary_element_id,
    `${path}.primary_element_id`,
  );
  const primaryElementType = stringAt(
    record.primary_element_type,
    `${path}.primary_element_type`,
  );
  const scope = stringAt(record.scope, `${path}.scope`);
  if (!SCOPES.has(scope as CanonicalBlockScope)) {
    invalid(`${path}.scope`, "is unsupported");
  }
  if (scope !== expectedScope(primaryElementType)) {
    invalid(`${path}.scope`, "does not match primary_element_type");
  }
  const markdown = stringAt(record.markdown, `${path}.markdown`);
  const semanticText = stringAt(record.text, `${path}.text`);
  if (markdown !== pythonStrip(markdown)) {
    invalid(`${path}.markdown`, "must not have outer whitespace");
  }
  if (semanticText !== pythonStrip(semanticText)) {
    invalid(`${path}.text`, "must not have outer whitespace");
  }
  const contributingElementIds = uniqueStringsAt(
    record.contributing_element_ids,
    `${path}.contributing_element_ids`,
  );
  const relationshipIds = uniqueStringsAt(
    record.relationship_ids,
    `${path}.relationship_ids`,
  );
  const relationshipIdSet = new Set(relationshipIds);
  const exclusions = arrayAt(
    record.excluded_contributions,
    `${path}.excluded_contributions`,
  ).map((entry, index) =>
    validateExcludedContribution(
      entry,
      `${path}.excluded_contributions[${index}]`,
      relationshipIdSet,
    ),
  );
  const exclusionKeys = exclusions.map(
    (entry) => `${entry.element_id}\u0000${entry.reason}`,
  );
  requireUnique(exclusionKeys, `${path}.excluded_contributions`);

  const omissionReason =
    record.omission_reason === undefined || record.omission_reason === null
      ? null
      : stringAt(record.omission_reason, `${path}.omission_reason`);
  if (
    omissionReason !== null &&
    !OMISSION_REASONS.has(omissionReason as CanonicalOmissionReason)
  ) {
    invalid(`${path}.omission_reason`, "is unsupported");
  }
  const suppressor =
    record.suppressed_by_element_id === undefined ||
    record.suppressed_by_element_id === null
      ? null
      : stringAt(
          record.suppressed_by_element_id,
          `${path}.suppressed_by_element_id`,
        );

  if (omissionReason === null) {
    if (!contributingElementIds.length) {
      invalid(path, "included block must contribute at least one element");
    }
    if (contributingElementIds[0] !== primaryElementId) {
      invalid(path, "included block must contribute its primary element first");
    }
    if (!markdown && !semanticText) {
      invalid(path, "included block must contain Markdown or semantic text");
    }
    if (contributingElementIds.length > 1 && !relationshipIds.length) {
      invalid(path, "multi-element included block requires a relationship");
    }
    if (suppressor !== null) {
      invalid(path, "included block cannot declare a suppressor");
    }
  } else {
    if (markdown || semanticText || contributingElementIds.length) {
      invalid(path, "omitted block cannot present content");
    }
    if (suppressor === primaryElementId) {
      invalid(path, "omitted block cannot suppress itself");
    }
    const relationalOmission =
      omissionReason === "alternate_representation" ||
      omissionReason === "consumed_by_relationship" ||
      omissionReason === "overlapping_visual_table";
    if (relationalOmission && !suppressor) {
      invalid(path, "relationship or overlap omission requires a suppressor");
    }
    if (!relationalOmission && suppressor !== null) {
      invalid(path, "intrinsic omission cannot declare a suppressor");
    }
    if (
      omissionReason === "overlapping_visual_table" &&
      primaryElementType.toLowerCase() !== "table"
    ) {
      invalid(path, "overlap omission requires a table primary");
    }
    if (
      (omissionReason === "empty_visual" ||
        omissionReason === "unsupported_primary_ocr") &&
      !VISUAL_TYPES.has(primaryElementType.toLowerCase())
    ) {
      invalid(path, "visual omission requires a visual primary");
    }
    if (
      omissionReason === "empty_content" &&
      VISUAL_TYPES.has(primaryElementType.toLowerCase())
    ) {
      invalid(path, "visual primary cannot use empty_content");
    }
    if (omissionReason === "source_contradicted_primary_ocr") {
      if (
        !SOURCE_CONTRADICTED_PRIMARY_TYPES.has(
          primaryElementType.toLowerCase(),
        )
      ) {
        invalid(
          path,
          "source-contradicted OCR omission requires a text or heading primary",
        );
      }
      if (relationshipIds.length || exclusions.length) {
        invalid(
          path,
          "source-contradicted OCR omission cannot retain relationships or exclusions",
        );
      }
    }
  }

  void id;
  void pageId;
  return record as unknown as CanonicalBlock;
}

function validateViewShape(value: unknown, path: string): CanonicalView {
  const record = recordAt(value, path);
  requireExactKeys(record, ["block_ids", "markdown", "text"], path);
  const blockIds = uniqueStringsAt(record.block_ids, `${path}.block_ids`);
  const markdown = stringAt(record.markdown, `${path}.markdown`);
  const semanticText = stringAt(record.text, `${path}.text`);
  if (!blockIds.length && (markdown || semanticText)) {
    invalid(path, "empty view cannot contain content");
  }
  for (const [field, content] of [
    ["markdown", markdown],
    ["text", semanticText],
  ] as const) {
    if (
      blockIds.length &&
      content &&
      (!content.endsWith("\n") || content.endsWith("\n\n"))
    ) {
      invalid(`${path}.${field}`, "must end with exactly one newline");
    }
  }
  return record as unknown as CanonicalView;
}

function validateMatchingView(
  value: unknown,
  blocks: readonly CanonicalBlock[],
  path: string,
): CanonicalView {
  const view = validateViewShape(value, path);
  const included = blocks.filter(
    (block) => (block.omission_reason ?? null) === null,
  );
  const expectedIds = included.map((block) => block.id);
  if (!sameStrings(view.block_ids, expectedIds)) {
    invalid(`${path}.block_ids`, "does not match ordered included blocks");
  }
  if (view.markdown !== renderValues(included.map((block) => block.markdown))) {
    invalid(`${path}.markdown`, "does not match ordered included blocks");
  }
  if (view.text !== renderValues(included.map((block) => block.text))) {
    invalid(`${path}.text`, "does not match ordered included blocks");
  }
  return view;
}

function validatePage(value: unknown, path: string): CanonicalPage {
  const record = recordAt(value, path);
  requireExactKeys(
    record,
    [
      "page_id",
      "page_index",
      "page_number",
      "page_label",
      "blocks",
      "full",
      "body",
      "header",
      "footer",
    ],
    path,
    ["page_identity"],
  );
  const pageId = stringAt(record.page_id, `${path}.page_id`);
  integerAt(record.page_index, `${path}.page_index`, 1);
  pageNumberAt(record.page_number, `${path}.page_number`);
  stringAt(record.page_label, `${path}.page_label`);
  const blocks = arrayAt(record.blocks, `${path}.blocks`).map((entry, index) =>
    validateBlock(entry, `${path}.blocks[${index}]`),
  );
  requireUnique(
    blocks.map((block) => block.id),
    `${path}.blocks[].id`,
  );
  requireUnique(
    blocks.map((block) => block.primary_element_id),
    `${path}.blocks[].primary_element_id`,
  );
  if (blocks.some((block) => block.page_id !== pageId)) {
    invalid(`${path}.blocks`, "contains a block owned by another page");
  }

  const primaryRank = new Map(
    blocks.map((block, index) => [block.primary_element_id, index]),
  );
  const blocksByPrimary = new Map(
    blocks.map((block) => [block.primary_element_id, block]),
  );
  for (const block of blocks) {
    if (block.omission_reason !== "overlapping_visual_table") continue;
    const suppressor = blocksByPrimary.get(block.suppressed_by_element_id ?? "");
    if (
      !suppressor ||
      !VISUAL_TYPES.has(suppressor.primary_element_type.toLowerCase()) ||
      primaryRank.get(suppressor.primary_element_id)! >=
        primaryRank.get(block.primary_element_id)!
    ) {
      invalid(
        `${path}.blocks`,
        "overlap suppressor must be a preceding visual on the same page",
      );
    }
  }

  validateMatchingView(record.full, blocks, `${path}.full`);
  validateMatchingView(
    record.body,
    blocks.filter((block) => block.scope === "body"),
    `${path}.body`,
  );
  validateMatchingView(
    record.header,
    blocks.filter((block) => block.scope === "header"),
    `${path}.header`,
  );
  validateMatchingView(
    record.footer,
    blocks.filter((block) => block.scope === "footer"),
    `${path}.footer`,
  );
  return record as unknown as CanonicalPage;
}

function matchingSuppressorExclusions(
  block: CanonicalBlock,
): CanonicalExcludedContribution[] {
  const expectedReason =
    (block.omission_reason ?? null) === "alternate_representation"
      ? "alternate_representation"
      : "already_claimed";
  return block.excluded_contributions.filter(
    (entry) =>
      entry.element_id === block.suppressed_by_element_id &&
      entry.reason === expectedReason,
  );
}

function validateDocumentReferences(
  pages: readonly CanonicalPage[],
  path: string,
): void {
  const blocks = pages.flatMap((page) => page.blocks);
  requireUnique(
    blocks.map((block) => block.id),
    `${path}.pages[].blocks[].id`,
  );
  requireUnique(
    blocks.map((block) => block.primary_element_id),
    `${path}.pages[].blocks[].primary_element_id`,
  );
  const claimed = blocks.flatMap((block) =>
    (block.omission_reason ?? null) === null
      ? block.contributing_element_ids
      : [],
  );
  requireUnique(claimed, `${path}.presented_element_ids`);
  const presented = new Set(claimed);
  const blocksByPrimary = new Map(
    blocks.map((block) => [block.primary_element_id, block]),
  );
  const ownerByContribution = new Map<string, string>();
  for (const block of blocks) {
    if ((block.omission_reason ?? null) !== null) continue;
    for (const id of block.contributing_element_ids) {
      ownerByContribution.set(id, block.primary_element_id);
    }
  }

  for (const block of blocks) {
    for (const exclusion of block.excluded_contributions) {
      if (
        exclusion.reason === "already_claimed" &&
        !presented.has(exclusion.element_id)
      ) {
        invalid(path, "already_claimed exclusion does not resolve");
      }
    }
    if (
      (block.omission_reason ?? null) !== null &&
      block.omission_reason !== "consumed_by_relationship" &&
      presented.has(block.primary_element_id)
    ) {
      invalid(path, "omitted primary is also presented");
    }
    if (
      block.omission_reason !== "alternate_representation" &&
      block.omission_reason !== "consumed_by_relationship" &&
      block.omission_reason !== "overlapping_visual_table"
    ) {
      continue;
    }
    const suppressorId = block.suppressed_by_element_id!;
    if (block.omission_reason === "overlapping_visual_table") {
      const suppressor = blocksByPrimary.get(suppressorId);
      if (
        !suppressor ||
        !VISUAL_TYPES.has(suppressor.primary_element_type.toLowerCase())
      ) {
        invalid(path, "overlap suppressor does not resolve to a visual block");
      }
      continue;
    }
    if (!presented.has(suppressorId)) {
      invalid(path, "relationship suppressor does not resolve");
    }
    if (
      block.omission_reason === "consumed_by_relationship" &&
      ownerByContribution.get(block.primary_element_id) !== suppressorId
    ) {
      invalid(path, "consumed primary is not transferred to its owner");
    }
    const matchingExclusions = matchingSuppressorExclusions(block);
    if (
      !block.relationship_ids.length ||
      !matchingExclusions.length ||
      matchingExclusions.some((entry) => !entry.relationship_ids.length)
    ) {
      invalid(path, "relationship omission lacks asserting audit evidence");
    }
    if (block.omission_reason === "consumed_by_relationship") {
      const owner = blocksByPrimary.get(suppressorId);
      if (!owner) invalid(path, "consumption owner block does not resolve");
      const ownerRelationshipIds = new Set(owner.relationship_ids);
      if (
        matchingExclusions.some((entry) =>
          entry.relationship_ids.some((id) => !ownerRelationshipIds.has(id)),
        )
      ) {
        invalid(path, "consumption assertion is absent from its owner block");
      }
    }
  }
}

function validateLegacyPageReferences(
  presentation: CanonicalPresentation,
  result: ParseResult,
): void {
  if (presentation.pages.length !== result.pages.length) {
    invalid("$.pages", "does not cover every public result page");
  }
  const legacyByIndex = new Map<number, PageResult>();
  for (const [index, page] of result.pages.entries()) {
    if (
      typeof page.page_index !== "number" ||
      !Number.isInteger(page.page_index) ||
      legacyByIndex.has(page.page_index)
    ) {
      invalid(
        `result.pages[${index}].page_index`,
        "must uniquely identify a canonical page",
      );
    }
    legacyByIndex.set(page.page_index, page);
  }
  for (const [index, page] of presentation.pages.entries()) {
    const legacy = legacyByIndex.get(page.page_index);
    if (!legacy) {
      invalid(`$.pages[${index}]`, "does not resolve to a public result page");
    }
    if (
      legacy.page_number !== page.page_number ||
      legacy.page_label !== page.page_label
    ) {
      invalid(
        `$.pages[${index}]`,
        "page number or label differs from the public result page",
      );
    }
  }
}

function validateCanonicalPresentation(
  value: unknown,
  result: ParseResult,
): CanonicalPresentation {
  const record = recordAt(value, "$");
  requireExactKeys(
    record,
    [
      "schema_version",
      "source_ir_version",
      "policy_id",
      "pages",
      "full",
      "body",
      "header",
      "footer",
    ],
    "$",
  );
  if (record.schema_version !== "1.0") {
    invalid("$.schema_version", "must equal \"1.0\"");
  }
  if (record.source_ir_version !== "1.0") {
    invalid("$.source_ir_version", "must equal \"1.0\"");
  }
  if (record.policy_id !== "canonical-presentation-v1") {
    invalid(
      "$.policy_id",
      "must equal \"canonical-presentation-v1\"",
    );
  }
  const pages = arrayAt(record.pages, "$.pages").map((entry, index) =>
    validatePage(entry, `$.pages[${index}]`),
  );
  requireUnique(
    pages.map((page) => page.page_id),
    "$.pages[].page_id",
  );
  requireUnique(
    pages.map((page) => page.page_index),
    "$.pages[].page_index",
  );
  const pageIndexes = pages.map((page) => page.page_index);
  if (pageIndexes.some((value, index) => index > 0 && value < pageIndexes[index - 1])) {
    invalid("$.pages", "must be ordered by page_index");
  }
  validateDocumentReferences(pages, "$");
  const blocks = pages.flatMap((page) => page.blocks);
  validateMatchingView(record.full, blocks, "$.full");
  validateMatchingView(
    record.body,
    blocks.filter((block) => block.scope === "body"),
    "$.body",
  );
  validateMatchingView(
    record.header,
    blocks.filter((block) => block.scope === "header"),
    "$.header",
  );
  validateMatchingView(
    record.footer,
    blocks.filter((block) => block.scope === "footer"),
    "$.footer",
  );
  const presentation = record as unknown as CanonicalPresentation;
  validateLegacyPageReferences(presentation, result);
  return presentation;
}

/**
 * Return the stored canonical contract when present.
 *
 * Absence is the only condition that selects legacy serialization. A present
 * null, unsupported, partial, or internally inconsistent contract throws.
 */
export function readCanonicalPresentation(
  result: ParseResult,
): CanonicalPresentation | null {
  if (
    !Object.prototype.hasOwnProperty.call(result, "canonical_presentation")
  ) {
    return null;
  }
  return validateCanonicalPresentation(result.canonical_presentation, result);
}

export function findCanonicalPage(
  presentation: CanonicalPresentation,
  page: PageResult,
): CanonicalPage {
  const canonicalPage = presentation.pages.find(
    (candidate) => candidate.page_index === page.page_index,
  );
  if (
    !canonicalPage ||
    canonicalPage.page_number !== page.page_number ||
    canonicalPage.page_label !== page.page_label
  ) {
    invalid(
      "$.pages",
      `has no canonical entry for public page_index ${page.page_index}`,
    );
  }
  return canonicalPage;
}
