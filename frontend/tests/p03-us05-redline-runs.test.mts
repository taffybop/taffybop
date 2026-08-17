import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  readTextRunSemantics,
  renderCanonicalTextRunOverlay,
  renderItemTextRunOverlay,
} from "../lib/text-run-semantics.ts";
import type {
  CanonicalBlock,
  DocumentContentItem,
  PageResult,
  TextRule,
  TextRun,
} from "../lib/types.ts";
import { samplePage } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);
const serializerSource = readFileSync(
  new URL("../lib/serialize-output.ts", import.meta.url),
  "utf8",
);
const targetPathOrderFixture = JSON.parse(
  readFileSync(
    new URL(
      "../../tests/fixtures/p03_us05_target_path_order.json",
      import.meta.url,
    ),
    "utf8",
  ),
) as {
  policy_id: string;
  ordered_paths: TextRun["target_path"][];
};

function rule(
  id: string,
  y: number,
  color: "red" | "blue" = "red",
): TextRule {
  return {
    id,
    bbox: { x: 10, y, width: 40, height: 0.6, unit: "pt" },
    source_object_kind: "rect",
    source_object_index: y,
    color:
      color === "red"
        ? { space: "rgb", components: [1, 0, 0] }
        : { space: "rgb", components: [0, 0, 1] },
    width: 40,
    thickness: 0.6,
    evidence_method: "vector",
    extraction_policy_id: "p03-text-run-extraction-v1",
  };
}

function run(
  id: string,
  elementId: string,
  text: string,
  start: number,
  end: number,
  options: Partial<TextRun> = {},
): TextRun {
  return {
    id,
    element_id: elementId,
    target_path: ["value"],
    text,
    source_text: text,
    start,
    end,
    bbox: { x: 10 + start, y: 20, width: end - start, height: 10, unit: "pt" },
    font_name: "Helvetica",
    font_size: 11,
    bold: false,
    italic: false,
    color: { space: "rgb", components: [0, 0, 0] },
    change_state: "unchanged",
    decorations: [],
    placeholder: false,
    rule_ids: [],
    evidence_method: "native",
    semantic_derivation: "source_style",
    extraction_policy_id: "p03-text-run-extraction-v1",
    association_policy_id: "p03-text-run-association-v1",
    ...options,
  };
}

function scalarItem(): DocumentContentItem {
  const value = "😀 <script> old new";
  const underline = run("run-underline", "ir-element-1", "<script>", 2, 10, {
    change_group_id: "change-underline",
    color: { space: "rgb", components: [0, 0, 1] },
    decorations: ["underline"],
    rule_ids: ["rule-blue"],
    evidence_method: "vector",
    semantic_derivation: "same_color_underline_rule",
  });
  const deleted = run("run-deleted", "ir-element-1", "old", 11, 14, {
    change_group_id: "change-1",
    color: { space: "rgb", components: [1, 0, 0] },
    change_state: "deleted",
    decorations: ["strikethrough"],
    rule_ids: ["rule-red"],
    evidence_method: "vector",
    semantic_derivation: "same_color_midline_rule",
  });
  return {
    id: "public-item-1",
    type: "text",
    reading_order: 0,
    value,
    md: "😀 <u>&lt;script&gt;</u> ~~old~~ new",
    bbox: { x: 0, y: 0, width: 100, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [underline, deleted],
    text_rules: [rule("rule-blue", 5, "blue"), rule("rule-red", 20)],
    redline_markdown: "😀 <u>&lt;script&gt;</u> ~~old~~ new",
    active_text: "😀 <script>  new",
    active_text_omitted_run_ids: ["run-deleted"],
    active_text_policy: "omit-proven-deletions-v1",
  };
}

function canonicalBlock(overrides: Partial<CanonicalBlock> = {}): CanonicalBlock {
  return {
    id: "canonical-1",
    page_id: "canonical-page-1",
    primary_element_id: "ir-element-1",
    primary_element_type: "text",
    scope: "body",
    markdown: "😀 <u>&lt;script&gt;</u> ~~old~~ new",
    text: "😀 <script> old new",
    contributing_element_ids: ["ir-element-1"],
    relationship_ids: [],
    excluded_contributions: [],
    ...overrides,
  };
}

function emphasisItem(): DocumentContentItem {
  const value = "Bold and italic";
  return {
    id: "public-emphasis-1",
    type: "text",
    reading_order: 0,
    value,
    md: "**Bold** and *italic*",
    bbox: { x: 0, y: 0, width: 100, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run("run-bold", "ir-emphasis-1", "Bold", 0, 4, { bold: true }),
      run("run-italic", "ir-emphasis-1", "italic", 9, 15, {
        italic: true,
      }),
    ],
    text_rules: [],
    redline_markdown: "**Bold** and *italic*",
    active_text: value,
    active_text_omitted_run_ids: [],
    active_text_policy: "omit-proven-deletions-v1",
  };
}

test("strict scalar overlay uses code-point offsets and safe React nodes", () => {
  const item = scalarItem();
  const semantics = readTextRunSemantics(item);
  assert.ok(semantics);
  assert.equal(semantics.elementId, "ir-element-1");

  const rendered = renderItemTextRunOverlay(item, ["value"]);
  assert.ok(rendered);
  const html = renderToStaticMarkup(rendered);
  assert.match(
    html,
    /^<span>😀 <\/span><u data-text-run-id="run-underline"><span /,
  );
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(
    html,
    /<del data-text-run-id="run-deleted"><span data-change-state="deleted">old<\/span><\/del>/,
  );
  assert.match(html, /<span> new<\/span>$/);
  assert.equal(item.value, "😀 <script> old new");
  assert.equal(item.active_text, "😀 <script>  new");
});

test("strict scalar projection preserves source bold and italic in Markdown", () => {
  const item = emphasisItem();
  const semantics = readTextRunSemantics(item);
  assert.ok(semantics);

  const rendered = renderItemTextRunOverlay(item, ["value"]);
  assert.ok(rendered);
  const html = renderToStaticMarkup(rendered);
  assert.match(
    html,
    /<span data-change-state="unchanged"><strong>Bold<\/strong><\/span>/,
  );
  assert.match(
    html,
    /<span data-change-state="unchanged"><em>italic<\/em><\/span>/,
  );

  const malformed = structuredClone(item);
  malformed.redline_markdown = "Bold and italic";
  malformed.md = malformed.redline_markdown;
  assert.equal(readTextRunSemantics(malformed), null);
});

test("malformed, unsorted, overlapping, and partial overlays fail closed", () => {
  const mutations: Array<(item: DocumentContentItem) => void> = [
    (item) => {
      item.text_runs![0].start = 3;
    },
    (item) => {
      (item.text_runs![0] as TextRun & { injected?: boolean }).injected = true;
    },
    (item) => {
      item.text_runs![0].rule_ids = ["missing-rule"];
    },
    (item) => {
      item.text_runs!.reverse();
    },
    (item) => {
      item.text_runs![1].start = 9;
      item.text_runs![1].text = "> old";
    },
    (item) => {
      item.text_rules!.push(rule("unlinked-rule", 30));
    },
    (item) => {
      item.text_rules!.reverse();
    },
    (item) => {
      item.text_rules![0].width += 0.01;
    },
    (item) => {
      item.text_rules![0].thickness += 0.01;
    },
    (item) => {
      item.active_text_omitted_run_ids = [];
    },
  ];

  for (const mutate of mutations) {
    const item = structuredClone(scalarItem());
    mutate(item);
    assert.equal(readTextRunSemantics(item), null);
    assert.equal(renderItemTextRunOverlay(item, ["value"]), null);
  }
});

test("run state, derivation, decoration, evidence, and links are coherent", () => {
  const mutations: Array<(item: DocumentContentItem) => void> = [
    (item) => {
      item.text_runs![1].change_state = "unchanged";
    },
    (item) => {
      item.text_runs![1].decorations = [];
    },
    (item) => {
      item.text_runs![1].evidence_method = "native";
    },
    (item) => {
      item.text_runs![1].semantic_derivation =
        "same_color_underline_rule";
    },
    (item) => {
      delete item.text_runs![1].change_group_id;
    },
    (item) => {
      item.text_runs![0].change_group_id =
        item.text_runs![1].change_group_id;
    },
    (item) => {
      item.text_runs![0].placeholder = true;
      item.text_runs![0].change_state = "unknown";
      item.text_runs![0].semantic_derivation =
        "same_color_underlined_placeholder";
    },
    (item) => {
      item.text_runs![0].color = {
        space: "rgb",
        components: [0, 1, 0],
      };
    },
    (item) => {
      item.text_runs![0].rule_ids = Array.from(
        { length: 65 },
        (_, index) => `rule-${index}`,
      );
    },
  ];

  for (const mutate of mutations) {
    const item = structuredClone(scalarItem());
    mutate(item);
    assert.equal(readTextRunSemantics(item), null);
  }

  const deletedAndUnderlined = structuredClone(scalarItem());
  deletedAndUnderlined.text_runs![1].decorations = [
    "strikethrough",
    "underline",
  ];
  assert.equal(readTextRunSemantics(deletedAndUnderlined), null);

  const nativeTrackedItem: DocumentContentItem = {
    id: "public-native-change",
    type: "code",
    reading_order: 0,
    value: "old",
    md: "```\nold\n```",
    bbox: { x: 0, y: 0, width: 40, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run("run-native-change", "ir-native-change", "old", 0, 3, {
        change_state: "deleted",
        decorations: ["strikethrough", "underline"],
        semantic_derivation: "native_tracked_change",
      }),
    ],
    text_rules: [],
  };
  assert.ok(readTextRunSemantics(nativeTrackedItem));

  const placeholderItem: DocumentContentItem = {
    id: "public-placeholder",
    type: "table",
    reading_order: 0,
    value: "_______",
    md: "| _______ |",
    bbox: { x: 0, y: 0, width: 100, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run("run-placeholder", "ir-placeholder", "_______", 0, 7, {
        change_group_id: "change-placeholder",
        color: { space: "rgb", components: [0, 0, 1] },
        change_state: "unknown",
        decorations: ["underline"],
        placeholder: true,
        rule_ids: ["rule-placeholder"],
        evidence_method: "vector",
        semantic_derivation: "same_color_underlined_placeholder",
      }),
    ],
    text_rules: [rule("rule-placeholder", 5, "blue")],
  };
  assert.ok(readTextRunSemantics(placeholderItem));

  for (const invalidText of ["__", "_".repeat(129), "___x"]) {
    const item = structuredClone(placeholderItem);
    item.value = invalidText;
    item.text_runs![0].text = invalidText;
    item.text_runs![0].source_text = invalidText;
    item.text_runs![0].end = Array.from(invalidText).length;
    assert.equal(readTextRunSemantics(item), null);
  }
});

test("rule-link limits accept exactly 64 and reject 65", () => {
  const linkedRulesItem = (count: number): DocumentContentItem => {
    const linkedRules = Array.from(
      { length: count },
      (_, index) => rule(`rule-link-${index}`, index, "blue"),
    );
    return {
      id: "public-rule-links",
      type: "code",
      reading_order: 0,
      value: "underlined",
      md: "```\nunderlined\n```",
      bbox: { x: 0, y: 0, width: 100, height: 12, unit: "pt" },
      text_run_policy: "p03-text-run-semantics-v1",
      text_runs: [
        run("run-rule-links", "ir-rule-links", "underlined", 0, 10, {
          change_group_id: "change-rule-links",
          color: { space: "rgb", components: [0, 0, 1] },
          decorations: ["underline"],
          rule_ids: linkedRules.map((linkedRule) => linkedRule.id),
          evidence_method: "vector",
          semantic_derivation: "same_color_underline_rule",
        }),
      ],
      text_rules: linkedRules,
    };
  };
  assert.ok(readTextRunSemantics(linkedRulesItem(64)));
  assert.equal(readTextRunSemantics(linkedRulesItem(65)), null);

  const sharedRuleItem = (count: number): DocumentContentItem => {
    const value = "x".repeat(count);
    return {
      id: "public-shared-rule",
      type: "code",
      reading_order: 0,
      value,
      md: `\`\`\`\n${value}\n\`\`\``,
      bbox: { x: 0, y: 0, width: 100, height: 12, unit: "pt" },
      text_run_policy: "p03-text-run-semantics-v1",
      text_runs: Array.from({ length: count }, (_, index) =>
        run(
          `run-shared-${index}`,
          "ir-shared-rule",
          "x",
          index,
          index + 1,
          {
            change_group_id: "change-shared-rule",
            color: { space: "rgb", components: [0, 0, 1] },
            decorations: ["underline"],
            rule_ids: ["rule-shared"],
            evidence_method: "vector",
            semantic_derivation: "same_color_underline_rule",
          },
        ),
      ),
      text_rules: [rule("rule-shared", 5, "blue")],
    };
  };
  assert.ok(readTextRunSemantics(sharedRuleItem(64)));
  assert.equal(readTextRunSemantics(sharedRuleItem(65)), null);
});

test("a non-isolatable scalar keeps normative JSON without a partial projection", () => {
  const item: DocumentContentItem = {
    id: "public-code",
    type: "code",
    reading_order: 0,
    value: "const answer = 42;",
    md: "```ts\nconst answer = 42;\n```",
    bbox: { x: 0, y: 0, width: 120, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run(
        "run-code",
        "ir-code",
        "answer",
        6,
        12,
        { bold: true },
      ),
    ],
    text_rules: [],
  };
  assert.ok(readTextRunSemantics(item));

  const inclusiveNearBlack = structuredClone(item);
  inclusiveNearBlack.text_runs![0].color = {
    space: "rgb",
    components: [1 / 255, 0, 0],
  };
  assert.ok(readTextRunSemantics(inclusiveNearBlack));

  const aboveNearBlack = structuredClone(inclusiveNearBlack);
  aboveNearBlack.text_runs![0].color.components[0] += 1e-6;
  assert.equal(readTextRunSemantics(aboveNearBlack), null);

  const unavailableColor = structuredClone(item);
  unavailableColor.text_runs![0].color = {
    space: "unknown",
    components: [],
  };
  assert.ok(readTextRunSemantics(unavailableColor));
  unavailableColor.text_runs![0].change_state = "unknown";
  assert.equal(readTextRunSemantics(unavailableColor), null);

  for (const field of [
    "redline_markdown",
    "active_text",
    "active_text_omitted_run_ids",
    "active_text_policy",
  ] as const) {
    const partial = structuredClone(item);
    if (field === "redline_markdown") partial[field] = partial.md ?? "";
    if (field === "active_text") partial[field] = String(partial.value);
    if (field === "active_text_omitted_run_ids") partial[field] = [];
    if (field === "active_text_policy") {
      partial[field] = "omit-proven-deletions-v1";
    }
    assert.equal(readTextRunSemantics(partial), null);
  }

  const forbiddenCompleteProjection = structuredClone(item);
  forbiddenCompleteProjection.redline_markdown =
    forbiddenCompleteProjection.md ?? "";
  forbiddenCompleteProjection.active_text = String(
    forbiddenCompleteProjection.value,
  );
  forbiddenCompleteProjection.active_text_omitted_run_ids = [];
  forbiddenCompleteProjection.active_text_policy =
    "omit-proven-deletions-v1";
  assert.equal(readTextRunSemantics(forbiddenCompleteProjection), null);

  const supportedEnvelopeMismatch: DocumentContentItem = {
    id: "public-envelope-mismatch",
    type: "text",
    reading_order: 0,
    value: "x",
    md: "**x**",
    bbox: { x: 0, y: 0, width: 20, height: 12, unit: "pt" },
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run("run-envelope-mismatch", "ir-envelope-mismatch", "x", 0, 1, {
        bold: true,
      }),
    ],
    text_rules: [],
    redline_markdown: "**x**",
    active_text: "x",
    active_text_omitted_run_ids: [],
    active_text_policy: "omit-proven-deletions-v1",
  };
  assert.ok(readTextRunSemantics(supportedEnvelopeMismatch));

  const supportedIsolatable = structuredClone(supportedEnvelopeMismatch);
  supportedIsolatable.md = "x";
  supportedIsolatable.redline_markdown = "x";
  assert.equal(readTextRunSemantics(supportedIsolatable), null);

  const isolatable = structuredClone(item);
  isolatable.type = "text";
  isolatable.md = String(isolatable.value);
  assert.equal(readTextRunSemantics(isolatable), null);
});

test("frontend target-path order interoperates with the backend ordering fixture", () => {
  assert.equal(
    targetPathOrderFixture.policy_id,
    "p03-text-run-semantics-v1",
  );
  const cells = Array.from({ length: 3 }, (_, index) => ({
    row: 0,
    column: index,
    text: `cell-${index}`,
  }));
  const items = Array.from({ length: 3 }, (_, index) => ({
    text: `item-text-${index}`,
    value: `item-value-${index}`,
  }));
  const owner: DocumentContentItem = {
    id: "public-order",
    type: "table",
    reading_order: 0,
    value: "owner-value",
    md: "| owner-value |",
    cells,
    items,
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: targetPathOrderFixture.ordered_paths.map((targetPath, index) => {
      const target =
        targetPath[0] === "value"
          ? "owner-value"
          : targetPath[0] === "cells"
            ? cells[targetPath[1]].text
            : items[targetPath[1]][targetPath[2]];
      return run(
        `run-order-${index}`,
        "ir-order",
        target,
        0,
        Array.from(target).length,
        {
          target_path: targetPath,
          italic: true,
        },
      );
    }),
    text_rules: [],
  };
  assert.ok(readTextRunSemantics(owner));

  const legacyValueFirst = structuredClone(owner);
  legacyValueFirst.text_runs = [
    legacyValueFirst.text_runs!.at(-1)!,
    ...legacyValueFirst.text_runs!.slice(0, -1),
  ];
  assert.equal(readTextRunSemantics(legacyValueFirst), null);
});

test("nested target paths are independently validated and rendered", () => {
  const table: DocumentContentItem = {
    id: "public-table",
    type: "table",
    reading_order: 0,
    cells: [{ row: 0, column: 0, text: "CARES Act" }],
    text_run_policy: "p03-text-run-semantics-v1",
    text_runs: [
      run("run-cell", "ir-table", "CARES Act", 0, 9, {
        target_path: ["cells", 0, "text"],
        italic: true,
      }),
    ],
    text_rules: [],
  };
  const semantics = readTextRunSemantics(table);
  assert.ok(semantics);
  const html = renderToStaticMarkup(
    renderItemTextRunOverlay(table, ["cells", 0, "text"]),
  );
  assert.match(html, /<em>CARES Act<\/em>/);
  assert.equal(renderItemTextRunOverlay(table, ["value"]), null);
});

test("canonical overlay requires one byte-identical contributor and item", () => {
  const item = scalarItem();
  const page = samplePage({ items: [item] });
  const rendered = renderCanonicalTextRunOverlay(canonicalBlock(), page);
  assert.ok(rendered);
  assert.match(renderToStaticMarkup(rendered), /<del data-text-run-id/);

  assert.equal(
    renderCanonicalTextRunOverlay(
      canonicalBlock({
        contributing_element_ids: ["ir-element-1", "ir-element-2"],
      }),
      page,
    ),
    null,
  );
  assert.equal(
    renderCanonicalTextRunOverlay(
      canonicalBlock({ text: "😀 <script> old new\n" }),
      page,
    ),
    null,
  );
  const duplicatePage: PageResult = samplePage({
    items: [item, { ...structuredClone(item), id: "public-item-duplicate" }],
  });
  assert.equal(
    renderCanonicalTextRunOverlay(canonicalBlock(), duplicatePage),
    null,
  );
});

test("workspace integrates safe overlays without changing output authority", () => {
  assert.match(
    workspaceSource,
    /readTextRunSemantics\(item\)/,
  );
  assert.match(
    workspaceSource,
    /renderCanonicalTextRunOverlay\(\s*block,\s*sourcePage,\s*\)/,
  );
  assert.match(
    workspaceSource,
    /textRunOverlay !== null \? textRunOverlay : <>\{block\.text\}<\/>/,
  );
  assert.doesNotMatch(workspaceSource, /dangerouslySetInnerHTML/);
  assert.match(
    workspaceSource,
    /navigator\.clipboard\.writeText\(visibleOutput\)/,
  );
  assert.match(
    workspaceSource,
    /new Blob\(\[visibleOutput\], \{ type: mime \}\)/,
  );
  assert.doesNotMatch(serializerSource, /text-run-semantics|active_text/);
});
