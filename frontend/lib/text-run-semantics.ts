import {
  createElement,
  Fragment,
  type ReactNode,
} from "react";

import type {
  CanonicalBlock,
  DocumentContentItem,
  PageResult,
  TextRule,
  TextRun,
  TextRunBoundingBox,
  TextRunColor,
  TextRunTargetPath,
} from "./types.ts";

const TEXT_RUN_POLICY = "p03-text-run-semantics-v1";
const EXTRACTION_POLICY = "p03-text-run-extraction-v1";
const ASSOCIATION_POLICY = "p03-text-run-association-v1";
const ACTIVE_TEXT_POLICY = "omit-proven-deletions-v1";
const MAX_RUN_TEXT_BYTES = 16 * 1024;
const MAX_FONT_NAME_BYTES = 256;
const MAX_RULES_PER_RUN = 64;
const MAX_RUNS_PER_RULE = 64;
const MIN_PLACEHOLDER_LENGTH = 3;
const MAX_PLACEHOLDER_LENGTH = 128;
const MAX_COLOR_COMPONENT_DELTA = 1 / 255;
const RULE_GEOMETRY_EPSILON = 1e-9;

const RUN_KEYS = [
  "association_policy_id",
  "bbox",
  "bold",
  "change_state",
  "color",
  "decorations",
  "element_id",
  "end",
  "evidence_method",
  "extraction_policy_id",
  "font_name",
  "font_size",
  "id",
  "italic",
  "placeholder",
  "rule_ids",
  "semantic_derivation",
  "source_text",
  "start",
  "target_path",
  "text",
] as const;
const OPTIONAL_RUN_KEYS = ["change_group_id"] as const;
const RULE_KEYS = [
  "bbox",
  "color",
  "evidence_method",
  "extraction_policy_id",
  "id",
  "source_object_index",
  "source_object_kind",
  "thickness",
  "width",
] as const;
const BBOX_KEYS = ["height", "unit", "width", "x", "y"] as const;
const COLOR_KEYS = ["components", "space"] as const;

const CHANGE_STATES = new Set([
  "deleted",
  "inserted",
  "replacement",
  "unknown",
  "unchanged",
]);
const EVIDENCE_METHODS = new Set([
  "native",
  "ocr",
  "vector",
  "embedded",
  "recovered",
  "derived",
]);
const SEMANTIC_DERIVATIONS = new Set([
  "source_style",
  "same_color_midline_rule",
  "same_color_underline_rule",
  "same_color_underlined_placeholder",
  "native_tracked_change",
]);
const COLOR_ARITY: Record<string, number> = {
  gray: 1,
  rgb: 3,
  cmyk: 4,
  unknown: 0,
};
const DECORATION_ORDER = ["strikethrough", "underline"] as const;

interface TargetResolution {
  path: TextRunTargetPath;
  value: string;
}

export interface ValidatedTextRunSemantics {
  elementId: string;
  runs: TextRun[];
  rules: TextRule[];
  targets: Map<string, TargetResolution>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function hasExactKeys(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  const actual = Object.keys(value).sort();
  const allowed = new Set([...required, ...optional]);
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    actual.every((key) => allowed.has(key)) &&
    actual.length >= required.length
  );
}

function utf8Length(value: string): number {
  return new TextEncoder().encode(value).length;
}

function isStringArray(value: unknown): value is string[] {
  return (
    Array.isArray(value) &&
    value.every((entry) => isNonEmptyString(entry))
  );
}

function hasUniqueValues(values: readonly string[]): boolean {
  return new Set(values).size === values.length;
}

function validateDecorations(
  value: unknown,
): value is ("strikethrough" | "underline")[] {
  if (
    !Array.isArray(value) ||
    value.some(
      (decoration) =>
        decoration !== "strikethrough" && decoration !== "underline",
    )
  ) {
    return false;
  }
  return value.every(
    (decoration, index) =>
      index === 0 ||
      DECORATION_ORDER.indexOf(value[index - 1]) <
        DECORATION_ORDER.indexOf(decoration),
  );
}

function validateBBox(value: unknown): value is TextRunBoundingBox {
  if (!isRecord(value) || !hasExactKeys(value, BBOX_KEYS)) return false;
  return (
    isFiniteNumber(value.x) &&
    isFiniteNumber(value.y) &&
    isFiniteNumber(value.width) &&
    value.width > 0 &&
    isFiniteNumber(value.height) &&
    value.height > 0 &&
    value.unit === "pt"
  );
}

function validateColor(value: unknown): value is TextRunColor {
  if (!isRecord(value) || !hasExactKeys(value, COLOR_KEYS)) return false;
  if (
    typeof value.space !== "string" ||
    !Object.hasOwn(COLOR_ARITY, value.space) ||
    !Array.isArray(value.components) ||
    value.components.length !== COLOR_ARITY[value.space]
  ) {
    return false;
  }
  return value.components.every(
    (component) =>
      isFiniteNumber(component) && component >= 0 && component <= 1,
  );
}

function validateTargetPath(value: unknown): value is TextRunTargetPath {
  if (!Array.isArray(value)) return false;
  if (value.length === 1) return value[0] === "value";
  return (
    value.length === 3 &&
    (value[0] === "cells" || value[0] === "items") &&
    Number.isInteger(value[1]) &&
    (value[1] as number) >= 0 &&
    (value[0] === "cells"
      ? value[2] === "text"
      : value[2] === "value" || value[2] === "text")
  );
}

function isBlack(color: TextRunColor): boolean {
  if (color.space === "gray") {
    return Math.abs(color.components[0]) <= MAX_COLOR_COMPONENT_DELTA;
  }
  if (color.space === "rgb") {
    return color.components.every(
      (component) => Math.abs(component) <= MAX_COLOR_COMPONENT_DELTA,
    );
  }
  if (color.space === "cmyk") {
    return (
      Math.abs(color.components[0]) <= MAX_COLOR_COMPONENT_DELTA &&
      Math.abs(color.components[1]) <= MAX_COLOR_COMPONENT_DELTA &&
      Math.abs(color.components[2]) <= MAX_COLOR_COMPONENT_DELTA &&
      Math.abs(1 - color.components[3]) <= MAX_COLOR_COMPONENT_DELTA
    );
  }
  return false;
}

function colorsMatch(left: TextRunColor, right: TextRunColor): boolean {
  return (
    left.space !== "unknown" &&
    left.space === right.space &&
    left.components.length === right.components.length &&
    left.components.every(
      (component, index) =>
        Math.abs(component - right.components[index]) <=
        MAX_COLOR_COMPONENT_DELTA,
    )
  );
}

function resolveTarget(
  item: DocumentContentItem,
  path: TextRunTargetPath,
): string | null {
  if (path[0] === "value") {
    return typeof item.value === "string" ? item.value : null;
  }
  if (path[0] === "cells") {
    const cell = item.cells?.[path[1]];
    return cell && typeof cell.text === "string" ? cell.text : null;
  }
  const nested = item.items?.[path[1]];
  if (!nested) return null;
  const value = nested[path[2]];
  return typeof value === "string" ? value : null;
}

function pathKey(path: TextRunTargetPath): string {
  return JSON.stringify(path);
}

function compareTargetPath(
  left: TextRunTargetPath,
  right: TextRunTargetPath,
): number {
  const leftHead = left[0];
  const rightHead = right[0];
  if (leftHead !== rightHead) return leftHead < rightHead ? -1 : 1;
  if (leftHead === "value" || rightHead === "value") return 0;
  if (left[1] !== right[1]) return left[1] - right[1];
  if (left[2] === right[2]) return 0;
  return left[2] < right[2] ? -1 : 1;
}

function compareRuns(left: TextRun, right: TextRun): number {
  return (
    compareTargetPath(left.target_path, right.target_path) ||
    left.start - right.start ||
    left.end - right.end ||
    (left.id === right.id ? 0 : left.id < right.id ? -1 : 1)
  );
}

function compareRules(left: TextRule, right: TextRule): number {
  return (
    left.bbox.y - right.bbox.y ||
    left.bbox.x - right.bbox.x ||
    left.bbox.width - right.bbox.width ||
    left.bbox.height - right.bbox.height ||
    (left.id === right.id ? 0 : left.id < right.id ? -1 : 1)
  );
}

function validateSemanticCoherence(run: TextRun): boolean {
  const hasRules = run.rule_ids.length > 0;
  const isOnlyDecoration = (
    decoration: "strikethrough" | "underline",
  ): boolean =>
    run.decorations.length === 1 && run.decorations[0] === decoration;

  switch (run.semantic_derivation) {
    case "source_style":
      return (
        run.evidence_method === "native" &&
        !hasRules &&
        run.decorations.length === 0 &&
        !run.placeholder &&
        run.change_group_id === undefined &&
        run.change_state ===
          (run.color.space === "unknown" || isBlack(run.color)
            ? "unchanged"
            : "unknown")
      );
    case "same_color_midline_rule":
      return (
        run.evidence_method === "vector" &&
        hasRules &&
        isOnlyDecoration("strikethrough") &&
        run.change_state === "deleted" &&
        !run.placeholder &&
        run.change_group_id !== undefined
      );
    case "same_color_underline_rule":
      return (
        run.evidence_method === "vector" &&
        hasRules &&
        isOnlyDecoration("underline") &&
        run.change_state === "unchanged" &&
        !run.placeholder &&
        run.change_group_id !== undefined
      );
    case "same_color_underlined_placeholder":
      return (
        run.evidence_method === "vector" &&
        hasRules &&
        isOnlyDecoration("underline") &&
        run.change_state === "unknown" &&
        run.placeholder &&
        run.text === run.source_text &&
        run.text.length >= MIN_PLACEHOLDER_LENGTH &&
        run.text.length <= MAX_PLACEHOLDER_LENGTH &&
        /^_+$/.test(run.text) &&
        run.change_group_id !== undefined
      );
    case "native_tracked_change":
      return (
        run.evidence_method === "native" &&
        !hasRules &&
        !run.placeholder &&
        run.change_group_id === undefined &&
        (run.change_state === "deleted" ||
          run.change_state === "inserted" ||
          run.change_state === "replacement")
      );
    default:
      return false;
  }
}

function validateRun(value: unknown): value is TextRun {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RUN_KEYS, OPTIONAL_RUN_KEYS) ||
    !isNonEmptyString(value.id) ||
    !isNonEmptyString(value.element_id) ||
    !validateTargetPath(value.target_path) ||
    typeof value.text !== "string" ||
    value.text.length === 0 ||
    utf8Length(value.text) > MAX_RUN_TEXT_BYTES ||
    typeof value.source_text !== "string" ||
    value.source_text.length === 0 ||
    utf8Length(value.source_text) > MAX_RUN_TEXT_BYTES ||
    !Number.isInteger(value.start) ||
    (value.start as number) < 0 ||
    !Number.isInteger(value.end) ||
    (value.end as number) <= (value.start as number) ||
    !validateBBox(value.bbox) ||
    !isNonEmptyString(value.font_name) ||
    utf8Length(value.font_name) > MAX_FONT_NAME_BYTES ||
    !isFiniteNumber(value.font_size) ||
    value.font_size <= 0 ||
    typeof value.bold !== "boolean" ||
    typeof value.italic !== "boolean" ||
    !validateColor(value.color) ||
    typeof value.change_state !== "string" ||
    !CHANGE_STATES.has(value.change_state) ||
    !validateDecorations(value.decorations) ||
    typeof value.placeholder !== "boolean" ||
    !isStringArray(value.rule_ids) ||
    !hasUniqueValues(value.rule_ids) ||
    value.rule_ids.length > MAX_RULES_PER_RUN ||
    typeof value.evidence_method !== "string" ||
    !EVIDENCE_METHODS.has(value.evidence_method) ||
    typeof value.semantic_derivation !== "string" ||
    !SEMANTIC_DERIVATIONS.has(value.semantic_derivation) ||
    value.extraction_policy_id !== EXTRACTION_POLICY ||
    value.association_policy_id !== ASSOCIATION_POLICY
  ) {
    return false;
  }
  const run = value as unknown as TextRun;
  return (
    value.change_group_id === undefined ||
    isNonEmptyString(value.change_group_id)
  ) && validateSemanticCoherence(run);
}

function validateRule(value: unknown): value is TextRule {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RULE_KEYS) ||
    !isNonEmptyString(value.id) ||
    !validateBBox(value.bbox) ||
    (value.source_object_kind !== "line" &&
      value.source_object_kind !== "rect") ||
    !Number.isInteger(value.source_object_index) ||
    (value.source_object_index as number) < 0 ||
    !validateColor(value.color) ||
    !isFiniteNumber(value.width) ||
    value.width <= 0 ||
    !isFiniteNumber(value.thickness) ||
    value.thickness <= 0 ||
    value.width < 2 ||
    value.thickness > 1.5 ||
    value.width / value.thickness < 3 ||
    Math.abs(value.width - value.bbox.width) >
      RULE_GEOMETRY_EPSILON ||
    Math.abs(value.thickness - value.bbox.height) >
      RULE_GEOMETRY_EPSILON ||
    value.evidence_method !== "vector" ||
    value.extraction_policy_id !== EXTRACTION_POLICY
  ) {
    return false;
  }
  return true;
}

function hasCanonicalOrder<T>(
  values: readonly T[],
  compare: (left: T, right: T) => number,
): boolean {
  return values.every(
    (value, index) => index === 0 || compare(values[index - 1], value) <= 0,
  );
}

function hasCoherentChangeGroups(runs: readonly TextRun[]): boolean {
  const groups = new Map<string, TextRun[]>();
  for (const run of runs) {
    if (run.change_group_id === undefined) continue;
    const members = groups.get(run.change_group_id) ?? [];
    members.push(run);
    groups.set(run.change_group_id, members);
  }

  for (const members of groups.values()) {
    const first = members[0];
    for (let index = 0; index < members.length; index += 1) {
      const member = members[index];
      if (
        member.element_id !== first.element_id ||
        pathKey(member.target_path) !== pathKey(first.target_path) ||
        member.change_state !== first.change_state ||
        member.decorations.length !== first.decorations.length ||
        member.decorations.some(
          (decoration, decorationIndex) =>
            decoration !== first.decorations[decorationIndex],
        ) ||
        member.placeholder !== first.placeholder ||
        member.semantic_derivation !== first.semantic_derivation ||
        member.evidence_method !== first.evidence_method ||
        (index > 0 && members[index - 1].end !== member.start)
      ) {
        return false;
      }
    }
  }
  return true;
}

function expectedActiveProjection(
  target: string,
  runs: readonly TextRun[],
): { text: string; omittedIds: string[] } {
  const characters = Array.from(target);
  const omitted = runs.filter((run) => run.change_state === "deleted");
  let cursor = 0;
  let text = "";
  for (const run of omitted) {
    text += characters.slice(cursor, run.start).join("");
    cursor = run.end;
  }
  text += characters.slice(cursor).join("");
  return {
    text,
    omittedIds: omitted.map((run) => run.id),
  };
}

function markdownEscape(value: string, htmlContext = false): string {
  let escaped = value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
  if (htmlContext) return escaped;
  escaped = escaped.replace(/[\\`*_[\]|~]/g, "\\$&");
  escaped = escaped.replace(
    /^([ \t]{0,3})([#>+\-])(?=\s)/gm,
    (_match, prefix: string, marker: string) => `${prefix}\\${marker}`,
  );
  escaped = escaped.replace(
    /^([ \t]{0,3})(-)(?=-*[ \t]*$)/gm,
    (_match, prefix: string, marker: string) => `${prefix}\\${marker}`,
  );
  escaped = escaped.replace(
    /^([ \t]{0,3})(=)(?==*[ \t]*$)/gm,
    (_match, prefix: string, marker: string) => `${prefix}\\${marker}`,
  );
  return escaped.replace(
    /^([ \t]{0,3})(\d+)([.)])(?=\s)/gm,
    (
      _match,
      prefix: string,
      digits: string,
      marker: string,
    ) => `${prefix}${digits}\\${marker}`,
  );
}

function renderScalarRedlineBody(
  target: string,
  runs: readonly TextRun[],
  includeEmphasis = true,
): string | null {
  const characters = Array.from(target);
  const decorated: Array<{
    end: number;
    kind: "bold" | "bold_italic" | "deleted" | "italic" | "underline";
    start: number;
  }> = [];
  const deletedGroups = new Map<string, TextRun[]>();
  for (const run of runs) {
    if (run.change_state !== "deleted") continue;
    const groupId = run.change_group_id ?? run.id;
    const members = deletedGroups.get(groupId) ?? [];
    members.push(run);
    deletedGroups.set(groupId, members);
  }
  for (const members of deletedGroups.values()) {
    decorated.push({
      end: Math.max(...members.map((run) => run.end)),
      kind: "deleted",
      start: Math.min(...members.map((run) => run.start)),
    });
  }
  for (const run of runs) {
    if (
      run.change_state !== "deleted" &&
      run.decorations.includes("underline")
    ) {
      decorated.push({
        end: run.end,
        kind: "underline",
        start: run.start,
      });
    }
  }
  if (includeEmphasis) {
    const protectedRanges = decorated.map(({ start, end }) => ({ start, end }));
    for (const run of runs) {
      if (
        run.change_state === "deleted" ||
        (!run.bold && !run.italic) ||
        protectedRanges.some(
          (range) => run.start < range.end && range.start < run.end,
        )
      ) {
        continue;
      }
      decorated.push({
        end: run.end,
        kind:
          run.bold && run.italic
            ? "bold_italic"
            : run.bold
              ? "bold"
              : "italic",
        start: run.start,
      });
    }
  }
  decorated.sort(
    (left, right) =>
      left.start - right.start ||
      left.end - right.end ||
      (left.kind === right.kind ? 0 : left.kind < right.kind ? -1 : 1),
  );

  let cursor = 0;
  let output = "";
  for (const decoration of decorated) {
    if (decoration.start < cursor) return null;
    output += markdownEscape(
      characters.slice(cursor, decoration.start).join(""),
    );
    const content = characters
      .slice(decoration.start, decoration.end)
      .join("");
    if (decoration.kind === "deleted") {
      output += `~~${markdownEscape(content)}~~`;
    } else if (decoration.kind === "underline") {
      const escapedContent =
        content.length > 0 && /^_+$/.test(content)
          ? markdownEscape(content, true)
          : markdownEscape(content);
      output += `<u>${escapedContent}</u>`;
    } else if (decoration.kind === "bold") {
      output += `**${markdownEscape(content)}**`;
    } else if (decoration.kind === "italic") {
      output += `*${markdownEscape(content)}*`;
    } else {
      output += `***${markdownEscape(content)}***`;
    }
    cursor = decoration.end;
  }
  output += markdownEscape(characters.slice(cursor).join(""));
  return output;
}

function expectedScalarRedline(
  item: DocumentContentItem,
  target: string,
  runs: readonly TextRun[],
): string | null {
  const type = item.type.toLocaleLowerCase("en-US");
  const body = renderScalarRedlineBody(target, runs, type !== "heading");
  if (body === null) return null;
  if (type === "text" || type === "header" || type === "footer") {
    return body;
  }
  if (type !== "heading" || typeof item.redline_markdown !== "string") {
    return null;
  }
  const match = /^(#{1,6} )/.exec(item.redline_markdown);
  return match === null ? null : `${match[1]}${body}`;
}

function hasCompleteScalarProjection(
  item: DocumentContentItem,
  expectedRedline: string | null,
): boolean {
  return (
    expectedRedline !== null &&
    typeof item.redline_markdown === "string" &&
    item.redline_markdown === expectedRedline &&
    item.redline_markdown === item.md &&
    typeof item.active_text === "string" &&
    item.active_text_policy === ACTIVE_TEXT_POLICY &&
    isStringArray(item.active_text_omitted_run_ids) &&
    hasUniqueValues(item.active_text_omitted_run_ids)
  );
}

function scalarProjectionFieldCount(item: DocumentContentItem): number {
  return [
    "redline_markdown",
    "active_text",
    "active_text_omitted_run_ids",
    "active_text_policy",
  ].filter((key) => Object.hasOwn(item, key)).length;
}

function hasLosslesslyIsolatableScalarEnvelope(
  item: DocumentContentItem,
): boolean {
  if (typeof item.value !== "string" || typeof item.md !== "string") {
    return false;
  }
  const type = item.type.toLocaleLowerCase("en-US");
  if (type === "text" || type === "header" || type === "footer") {
    return item.md === item.value;
  }
  if (type !== "heading") return false;
  const match = /^(#{1,6} )([\s\S]*)$/.exec(item.md);
  return match !== null && match[2] === item.value;
}

function supportsScalarProjectionEnvelope(
  item: DocumentContentItem,
): boolean {
  const type = item.type.toLocaleLowerCase("en-US");
  return (
    type === "heading" ||
    type === "text" ||
    type === "header" ||
    type === "footer"
  );
}

/**
 * Validate one complete public item overlay.
 *
 * A malformed run, unresolved target, duplicate ID, bad ordering, or partial
 * rule inventory invalidates the entire overlay. The caller then displays the
 * authoritative predecessor text.
 */
export function readTextRunSemantics(
  item: DocumentContentItem,
): ValidatedTextRunSemantics | null {
  if (item.text_run_policy !== TEXT_RUN_POLICY) return null;
  if (!Array.isArray(item.text_runs) || !Array.isArray(item.text_rules)) {
    return null;
  }
  if (
    item.text_runs.length === 0 ||
    item.text_runs.length > 10_000 ||
    item.text_rules.length > 10_000 ||
    !item.text_runs.every(validateRun) ||
    !item.text_rules.every(validateRule)
  ) {
    return null;
  }

  const runs = item.text_runs;
  const rules = item.text_rules;
  if (
    !hasCanonicalOrder(runs, compareRuns) ||
    !hasCanonicalOrder(rules, compareRules)
  ) {
    return null;
  }

  const runIds = runs.map((run) => run.id);
  const ruleIds = rules.map((rule) => rule.id);
  if (!hasUniqueValues(runIds) || !hasUniqueValues(ruleIds)) return null;
  const ruleIdSet = new Set(ruleIds);
  const rulesById = new Map(rules.map((rule) => [rule.id, rule]));
  const ruleOrder = new Map(
    ruleIds.map((ruleId, index) => [ruleId, index]),
  );
  const runCountByRule = new Map<string, number>();
  const linkedRuleIds = new Set<string>();
  const elementIds = new Set<string>();
  const targets = new Map<string, TargetResolution>();
  const previousEndByTarget = new Map<string, number>();

  for (const run of runs) {
    elementIds.add(run.element_id);
    if (!run.rule_ids.every((ruleId) => ruleIdSet.has(ruleId))) return null;
    if (
      run.rule_ids.some(
        (ruleId, index) =>
          index > 0 &&
          ruleOrder.get(run.rule_ids[index - 1])! >= ruleOrder.get(ruleId)!,
      )
    ) {
      return null;
    }
    for (const ruleId of run.rule_ids) {
      const linkedRule = rulesById.get(ruleId);
      if (!linkedRule || !colorsMatch(run.color, linkedRule.color)) {
        return null;
      }
      linkedRuleIds.add(ruleId);
      const nextCount = (runCountByRule.get(ruleId) ?? 0) + 1;
      if (nextCount > MAX_RUNS_PER_RULE) return null;
      runCountByRule.set(ruleId, nextCount);
    }

    const targetValue = resolveTarget(item, run.target_path);
    if (targetValue === null) return null;
    const targetCharacters = Array.from(targetValue);
    if (
      run.end > targetCharacters.length ||
      targetCharacters.slice(run.start, run.end).join("") !== run.text
    ) {
      return null;
    }

    const key = pathKey(run.target_path);
    const previousEnd = previousEndByTarget.get(key);
    if (previousEnd !== undefined && previousEnd > run.start) return null;
    previousEndByTarget.set(key, run.end);
    targets.set(key, { path: run.target_path, value: targetValue });
  }

  if (
    elementIds.size !== 1 ||
    linkedRuleIds.size !== ruleIdSet.size ||
    [...linkedRuleIds].some((ruleId) => !ruleIdSet.has(ruleId)) ||
    !hasCoherentChangeGroups(runs)
  ) {
    return null;
  }

  const scalarRuns = runs.filter((run) => run.target_path[0] === "value");
  const scalarProjectionFields = scalarProjectionFieldCount(item);
  if (scalarRuns.length > 0) {
    const scalarTarget = targets.get(pathKey(["value"]));
    if (!scalarTarget) {
      return null;
    }
    if (!supportsScalarProjectionEnvelope(item)) {
      if (scalarProjectionFields !== 0) return null;
    } else if (scalarProjectionFields === 0) {
      if (hasLosslesslyIsolatableScalarEnvelope(item)) return null;
    } else if (
      scalarProjectionFields !== 4 ||
      !hasCompleteScalarProjection(
        item,
        expectedScalarRedline(item, scalarTarget.value, scalarRuns),
      )
    ) {
      return null;
    } else {
      const active = expectedActiveProjection(scalarTarget.value, scalarRuns);
      if (
        item.active_text !== active.text ||
        item.active_text_omitted_run_ids!.length !==
          active.omittedIds.length ||
        item.active_text_omitted_run_ids!.some(
          (id, index) => id !== active.omittedIds[index],
        )
      ) {
        return null;
      }
    }
  } else if (scalarProjectionFields !== 0) {
    return null;
  }

  return {
    elementId: runs[0].element_id,
    runs,
    rules,
    targets,
  };
}

function renderTarget(
  target: string,
  runs: readonly TextRun[],
  keyPrefix: string,
): ReactNode {
  const characters = Array.from(target);
  const output: ReactNode[] = [];
  let cursor = 0;

  for (const run of runs) {
    if (cursor < run.start) {
      output.push(
        createElement(
          "span",
          { key: `${keyPrefix}-plain-${cursor}` },
          characters.slice(cursor, run.start).join(""),
        ),
      );
    }

    const text = characters.slice(run.start, run.end).join("");
    const italicContent = run.italic
      ? createElement("em", null, text)
      : text;
    const emphasizedContent = run.bold
      ? createElement("strong", null, italicContent)
      : italicContent;
    const span = createElement(
      "span",
      {
        "data-change-state": run.change_state,
        "data-placeholder": run.placeholder ? "true" : undefined,
        key: `${keyPrefix}-run-${run.id}`,
      },
      emphasizedContent,
    );
    const wrapped =
      run.change_state === "deleted"
        ? createElement(
            "del",
            { "data-text-run-id": run.id, key: `${keyPrefix}-del-${run.id}` },
            span,
          )
        : run.decorations.includes("underline")
          ? createElement(
              "u",
              { "data-text-run-id": run.id, key: `${keyPrefix}-u-${run.id}` },
              span,
            )
          : span;
    output.push(wrapped);
    cursor = run.end;
  }

  if (cursor < characters.length) {
    output.push(
      createElement(
        "span",
        { key: `${keyPrefix}-plain-${cursor}` },
        characters.slice(cursor).join(""),
      ),
    );
  }
  return createElement(Fragment, null, ...output);
}

/**
 * Render a validated target through React text nodes. Invalid or absent
 * semantics return null so callers can preserve their existing text path.
 */
export function renderItemTextRunOverlay(
  item: DocumentContentItem,
  targetPath: TextRunTargetPath,
): ReactNode | null {
  const semantics = readTextRunSemantics(item);
  if (!semantics) return null;
  return renderValidatedTextRunOverlay(semantics, targetPath, item.id);
}

export function renderValidatedTextRunOverlay(
  semantics: ValidatedTextRunSemantics,
  targetPath: TextRunTargetPath,
  keyPrefix = semantics.elementId,
): ReactNode | null {
  const key = pathKey(targetPath);
  const target = semantics.targets.get(key);
  if (!target) return null;
  const runs = semantics.runs.filter(
    (run) => pathKey(run.target_path) === key,
  );
  return renderTarget(target.value, runs, `${keyPrefix}-${key}`);
}

/**
 * Overlay canonical text only across the policy's exact one-contributor
 * bridge. Combined or transformed canonical blocks retain block.text.
 */
export function renderCanonicalTextRunOverlay(
  block: CanonicalBlock,
  sourcePage: PageResult,
): ReactNode | null {
  if (
    block.contributing_element_ids.length !== 1 ||
    typeof block.text !== "string"
  ) {
    return null;
  }
  const [elementId] = block.contributing_element_ids;
  const candidates = sourcePage.items.filter((item) => {
    const semantics = readTextRunSemantics(item);
    return (
      semantics !== null &&
      semantics.elementId === elementId &&
      semantics.runs.every((run) => run.target_path[0] === "value") &&
      typeof item.value === "string" &&
      item.value === block.text
    );
  });
  return candidates.length === 1
    ? renderItemTextRunOverlay(candidates[0], ["value"])
    : null;
}
