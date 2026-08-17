import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  readOutlineStructures,
  renderValidatedOutlineStructure,
} from "../lib/outline-structure.ts";
import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import { serializePageMarkdown } from "../lib/serialize-output.ts";
import type {
  CanonicalBlock,
  CanonicalPage,
  CanonicalPresentation,
  CanonicalView,
  DocumentContentItem,
  OutlineConfidence,
  OutlineContinuation,
  OutlineGroup,
  OutlineItem,
  OutlineRelationship,
  PageResult,
  ParseResult,
} from "../lib/types.ts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);
const validatorSource = readFileSync(
  new URL("../lib/outline-structure.ts", import.meta.url),
  "utf8",
);

const digest = "a".repeat(64);
const confidence: OutlineConfidence = {
  scope: "evidence",
  score: null,
  unavailable_reason: "not_calibrated",
};

function canonicalView(blocks: CanonicalBlock[]): CanonicalView {
  const included = blocks.filter(
    (block) => (block.omission_reason ?? null) === null,
  );
  const render = (values: string[]) =>
    values.length ? `${values.join("\n\n")}\n` : "";
  return {
    block_ids: included.map((block) => block.id),
    markdown: render(included.map((block) => block.markdown)),
    text: render(included.map((block) => block.text)),
  };
}

function resultWith(
  page: PageResult,
  block: CanonicalBlock,
): { result: ParseResult; presentation: CanonicalPresentation } {
  const full = canonicalView([block]);
  const empty: CanonicalView = { block_ids: [], markdown: "", text: "" };
  const canonicalPage: CanonicalPage = {
    page_id: block.page_id,
    page_index: page.page_index,
    page_number: page.page_number,
    page_label: page.page_label,
    blocks: [block],
    full,
    body: full,
    header: empty,
    footer: empty,
  };
  const presentation: CanonicalPresentation = {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [canonicalPage],
    full,
    body: full,
    header: empty,
    footer: empty,
  };
  return {
    presentation,
    result: {
      schema_version: "1.0",
      document: {
        filename: "outline.pdf",
        mime_type: "application/pdf",
        sha256: digest,
        page_count: 1,
      },
      pages: [page],
      processing: {
        engine: "parser",
        ocr_engine: "none",
        ocr_languages: [],
        duration_ms: 1,
      },
      warnings: [],
      canonical_presentation: presentation,
    },
  };
}

function relationship(
  id: string,
  type: OutlineRelationship["type"],
  sourceId: string,
  targetId: string,
  extra: string[] = [],
): OutlineRelationship {
  const base = {
    id,
    type,
    source_id: sourceId,
    target_id: targetId,
    evidence_ids: [`evidence-${id}`],
    canonical_inert: true as const,
    outline_group_id: "group-1",
    outline_policy: "p03-outline-structure-v1" as const,
  };
  if (type === "outline_next") {
    return { ...base, type, intervening_element_ids: extra };
  }
  if (type === "outline_continuation_of") {
    return { ...base, type, interstitial_kind: "table" };
  }
  return { ...base, type };
}

function outlineItem(
  id: string,
  elementId: string,
  sourcePath: Array<string | number>,
  body: string,
  options: Partial<OutlineItem> = {},
): OutlineItem {
  const markerEvidenceId = `marker-evidence-${id}`;
  return {
    id,
    element_id: elementId,
    source_public_item_id: "public-anchor",
    source_public_path: sourcePath,
    source_bbox_id: `source-bbox-${id}`,
    source_evidence_ids: [`source-evidence-${id}`],
    source_object: {
      reader: "pdfplumber",
      page_index: 1,
      word_index: Number(sourcePath.at(-1)) + 10,
    },
    sequence_kind: "unordered",
    marker_style: "bullet",
    raw_marker: "•",
    marker_bbox: {
      x: 20,
      y: 20 + Number(sourcePath.at(-1)) * 20,
      width: 5,
      height: 12,
      unit: "pt",
    },
    marker_ownership: "separate",
    marker_separator: "",
    body_text: body,
    predecessor_value_sha256: digest,
    level: 0,
    ordinal: 1,
    parent_id: null,
    marker_bbox_id: `marker-bbox-${id}`,
    marker_evidence_id: markerEvidenceId,
    source_method: "native",
    confidence,
    concern_codes: [],
    relationship_ids: [],
    continuation_ids: [],
    ...options,
  };
}

function nestedFixture(): {
  result: ParseResult;
  presentation: CanonicalPresentation;
} {
  const relationships: OutlineRelationship[] = [
    relationship("rel-contains-root", "contains", "group-element", "element-root"),
    relationship("rel-contains-child", "contains", "group-element", "element-child"),
    relationship("rel-contains-second", "contains", "group-element", "element-second"),
    relationship("rel-parent", "outline_parent_of", "element-root", "element-child"),
    relationship("rel-next", "outline_next", "element-root", "element-second"),
  ];
  const items: OutlineItem[] = [
    outlineItem(
      "node-root",
      "element-root",
      ["pages", 0, "items", 0, "items", 0],
      "Root <unsafe>",
      {
        relationship_ids: ["rel-contains-root", "rel-parent", "rel-next"],
      },
    ),
    outlineItem(
      "node-child",
      "element-child",
      ["pages", 0, "items", 0, "items", 1],
      "Child & detail",
      {
        raw_marker: "◦",
        level: 1,
        parent_id: "node-root",
        relationship_ids: ["rel-contains-child", "rel-parent"],
      },
    ),
    outlineItem(
      "node-second",
      "element-second",
      ["pages", 0, "items", 0, "items", 2],
      "Second root",
      {
        ordinal: 2,
        relationship_ids: ["rel-contains-second", "rel-next"],
      },
    ),
  ];
  const block: CanonicalBlock = {
    id: "block-outline",
    page_id: "canonical-page-1",
    primary_element_id: "anchor-element",
    primary_element_type: "list",
    scope: "body",
    markdown: '<ul data-outline-group="group-1">safe</ul>',
    text: "• Root <unsafe>\n  ◦ Child & detail\n• Second root",
    contributing_element_ids: [
      "anchor-element",
      "element-root",
      "element-child",
      "element-second",
    ],
    relationship_ids: relationships.map((value) => value.id),
    excluded_contributions: [],
  };
  const group: OutlineGroup = {
    id: "group-1",
    element_id: "group-element",
    page_id: block.page_id,
    sequence_kind: "unordered",
    marker_style: "bullet",
    anchor_public_item_id: "public-anchor",
    anchor_element_id: block.primary_element_id,
    anchor_public_path: ["pages", 0, "items", 0],
    group_bbox: { x: 20, y: 20, width: 240, height: 70, unit: "pt" },
    member_item_ids: items.map((value) => value.id),
    member_element_ids: items.map((value) => value.element_id),
    continuation_ids: [],
    continuation_element_ids: [],
    relationship_ids: relationships.map((value) => value.id),
    relationship_cardinality: {
      contains: 3,
      outline_parent_of: 1,
      outline_next: 1,
      outline_continuation_of: 0,
    },
    canonical_block_id: block.id,
    canonical_primary_element_id: block.primary_element_id,
    canonical_contributor_element_ids: block.contributing_element_ids,
    canonical_relationship_ids: block.relationship_ids,
    canonical_markdown_sha256: digest,
    canonical_text_sha256: digest,
    source_method: "native",
    confidence,
    concern_codes: [],
  };
  const anchor: DocumentContentItem = {
    id: "public-anchor",
    type: "list",
    reading_order: 0,
    ordered: false,
    source: "native",
    bbox: { x: 20, y: 20, width: 240, height: 70, unit: "pt" },
    items: [
      {
        value: "Root <unsafe>",
        marker: "Root <unsafe>",
        level: 0,
        source: "native",
        bbox: { x: 20, y: 20, width: 120, height: 12, unit: "pt" },
      },
      {
        value: "Child & detail",
        marker: "Child & detail",
        level: 0,
        source: "native",
        bbox: { x: 40, y: 40, width: 120, height: 12, unit: "pt" },
      },
      {
        value: "Second root",
        marker: "Second root",
        level: 0,
        source: "native",
        bbox: { x: 20, y: 60, width: 120, height: 12, unit: "pt" },
      },
    ],
    layout_outline_structure_projected: true,
    outline_policy: "p03-outline-structure-v1",
    outline_group: group,
    outline_items: items,
    outline_continuations: [],
    relationships,
  };
  const page: PageResult = {
    page_index: 1,
    page_number: 1,
    page_label: "1",
    page_width: 612,
    page_height: 792,
    unit: "pt",
    success: true,
    items: [anchor],
    warnings: [],
  };
  return resultWith(page, block);
}

function legalFixture(): {
  result: ParseResult;
  presentation: CanonicalPresentation;
} {
  const relationships: OutlineRelationship[] = [
    relationship("rel-contains-a", "contains", "group-element", "element-a"),
    relationship("rel-contains-b", "contains", "group-element", "element-b"),
    relationship("rel-contains-c", "contains", "group-element", "element-c"),
    relationship("rel-next-a-b", "outline_next", "element-a", "element-b"),
    relationship(
      "rel-next-b-c",
      "outline_next",
      "element-b",
      "element-c",
      ["element-table"],
    ),
    relationship(
      "rel-continuation",
      "outline_continuation_of",
      "element-table",
      "element-b",
    ),
  ];
  const values = ["a. Alpha", "b. Beta", "c. Gamma"];
  const elements = ["element-a", "element-b", "element-c"];
  const nodes = ["node-a", "node-b", "node-c"];
  const itemIndexes = [0, 1, 3];
  const backlinks = [
    ["rel-contains-a", "rel-next-a-b"],
    [
      "rel-contains-b",
      "rel-next-a-b",
      "rel-next-b-c",
      "rel-continuation",
    ],
    ["rel-contains-c", "rel-next-b-c"],
  ];
  const items = values.map((value, index) =>
    outlineItem(
      nodes[index],
      elements[index],
      ["pages", 0, "items", itemIndexes[index]],
      value.slice(3),
      {
        source_public_item_id: `clause-${index + 1}`,
        sequence_kind: "legal",
        marker_style: "lower_alpha",
        raw_marker: `${String.fromCharCode(97 + index)}.`,
        marker_ownership: "value_prefix",
        marker_separator: " ",
        ordinal: index + 1,
        source_object: {
          reader: "pdfplumber",
          page_index: 1,
          word_index: 30 + index,
        },
        relationship_ids: backlinks[index],
        continuation_ids: index === 1 ? ["continuation-table"] : [],
      },
    ),
  );
  const continuation: OutlineContinuation = {
    id: "continuation-table",
    element_id: "element-table",
    source_public_item_id: "table",
    source_public_path: ["pages", 0, "items", 2],
    source_type: "table",
    bbox_id: "bbox-table",
    bbox: { x: 40, y: 100, width: 300, height: 80, unit: "pt" },
    source_evidence_ids: ["evidence-table"],
    target_node_id: "node-b",
    source_method: "native",
    confidence,
    concern_codes: [],
    relationship_ids: ["rel-continuation"],
  };
  const block: CanonicalBlock = {
    id: "block-legal",
    page_id: "canonical-page-1",
    primary_element_id: "element-a",
    primary_element_type: "text",
    scope: "body",
    markdown: '<ol data-outline-group="group-1" type="a" start="1">safe</ol>',
    text: "a. Alpha\nb. Beta\n  Header | Value\nc. Gamma",
    contributing_element_ids: [
      "element-a",
      "element-b",
      "element-table",
      "element-table-cell",
      "element-c",
    ],
    relationship_ids: relationships.map((value) => value.id),
    excluded_contributions: [],
  };
  const group: OutlineGroup = {
    id: "group-1",
    element_id: "group-element",
    page_id: block.page_id,
    sequence_kind: "legal",
    marker_style: "lower_alpha",
    anchor_public_item_id: "clause-1",
    anchor_element_id: "element-a",
    anchor_public_path: ["pages", 0, "items", 0],
    group_bbox: { x: 20, y: 20, width: 340, height: 220, unit: "pt" },
    member_item_ids: items.map((value) => value.id),
    member_element_ids: items.map((value) => value.element_id),
    continuation_ids: [continuation.id],
    continuation_element_ids: [continuation.element_id],
    relationship_ids: relationships.map((value) => value.id),
    relationship_cardinality: {
      contains: 3,
      outline_parent_of: 0,
      outline_next: 2,
      outline_continuation_of: 1,
    },
    canonical_block_id: block.id,
    canonical_primary_element_id: block.primary_element_id,
    canonical_contributor_element_ids: block.contributing_element_ids,
    canonical_relationship_ids: block.relationship_ids,
    canonical_markdown_sha256: digest,
    canonical_text_sha256: digest,
    source_method: "native",
    confidence,
    concern_codes: [],
  };
  const clauses: DocumentContentItem[] = values.map((value, index) => ({
    id: `clause-${index + 1}`,
    type: "text",
    reading_order: itemIndexes[index],
    value,
    md: value,
    source: "native",
    bbox: {
      x: 20,
      y: 20 + index * 90,
      width: 300,
      height: 30,
      unit: "pt",
    },
  }));
  const anchor = clauses[0];
  Object.assign(anchor, {
    layout_outline_structure_projected: true,
    outline_policy: "p03-outline-structure-v1",
    outline_group: group,
    outline_items: items,
    outline_continuations: [continuation],
    relationships,
  });
  const table: DocumentContentItem = {
    id: "table",
    type: "table",
    reading_order: 2,
    value: [["Header", "<script>alert(1)</script>"], ["Row", "5%"]],
    rows: [["Header", "<script>alert(1)</script>"], ["Row", "5%"]],
    source: "native",
    bbox: { x: 40, y: 100, width: 300, height: 80, unit: "pt" },
  };
  const page: PageResult = {
    page_index: 1,
    page_number: 1,
    page_label: "1",
    page_width: 612,
    page_height: 792,
    unit: "pt",
    success: true,
    items: [anchor, clauses[1], table, clauses[2]],
    warnings: [],
  };
  return resultWith(page, block);
}

test("whole-document validation accepts exact nested custody without client hashing", () => {
  const { result, presentation } = nestedFixture();
  const structures = readOutlineStructures(result, presentation);
  assert.ok(structures);
  assert.equal(structures.size, 1);
  const structure = structures.get("block-outline");
  assert.ok(structure);
  assert.equal(structure.items.length, 3);
  assert.equal(structure.items[1].parent_id, "node-root");
  assert.deepEqual(structure.group.relationship_cardinality, {
    contains: 3,
    outline_parent_of: 1,
    outline_next: 1,
    outline_continuation_of: 0,
  });
  assert.equal(
    structure.items[0].source_evidence_ids.includes(
      structure.items[0].marker_evidence_id,
    ),
    false,
  );
  assert.equal(structure.group.canonical_markdown_sha256, digest);
  assert.doesNotMatch(validatorSource, /subtle\.digest|node:crypto|createHash/);
});

test("UTF-8 marker/body limits are inclusive and value-prefix spacing is exact", () => {
  const exactMarker = nestedFixture();
  exactMarker.result.pages[0].items[0].outline_items![0].raw_marker =
    "é".repeat(32);
  assert.ok(
    readOutlineStructures(exactMarker.result, exactMarker.presentation),
  );

  const markerOverflow = nestedFixture();
  markerOverflow.result.pages[0].items[0].outline_items![0].raw_marker =
    "é".repeat(33);
  assert.equal(
    readOutlineStructures(markerOverflow.result, markerOverflow.presentation),
    null,
  );

  const exactBody = nestedFixture();
  const exactText = "x".repeat(16 * 1024);
  exactBody.result.pages[0].items[0].outline_items![0].body_text = exactText;
  exactBody.result.pages[0].items[0].items![0].value = exactText;
  assert.ok(readOutlineStructures(exactBody.result, exactBody.presentation));

  const bodyOverflow = nestedFixture();
  const overflowText = "x".repeat(16 * 1024 + 1);
  bodyOverflow.result.pages[0].items[0].outline_items![0].body_text =
    overflowText;
  bodyOverflow.result.pages[0].items[0].items![0].value = overflowText;
  assert.equal(
    readOutlineStructures(bodyOverflow.result, bodyOverflow.presentation),
    null,
  );

  const separator = legalFixture();
  separator.result.pages[0].items[0].outline_items![0].marker_separator = "  ";
  separator.result.pages[0].items[0].value = "a.  Alpha";
  assert.equal(
    readOutlineStructures(separator.result, separator.presentation),
    null,
  );
});

test("outline canonical custody stays disjoint from form-owned contributors", () => {
  const disjoint = nestedFixture();
  disjoint.result.pages[0].items.push({
    id: "form-source",
    type: "text",
    reading_order: 1,
    value: "Form source",
    form_group: {
      element_id: "form-semantic",
      anchor_element_id: "form-source-element",
      contributor_element_ids: ["form-source-element"],
    } as never,
  });
  assert.ok(readOutlineStructures(disjoint.result, disjoint.presentation));

  const overlap = nestedFixture();
  overlap.result.pages[0].items.push({
    id: "form-source",
    type: "text",
    reading_order: 1,
    value: "Form source",
    form_group: {
      element_id: "form-semantic",
      anchor_element_id: "form-source-element",
      contributor_element_ids: ["element-root"],
    } as never,
  });
  assert.equal(
    readOutlineStructures(overlap.result, overlap.presentation),
    null,
  );
});

test("safe semantic DOM nests lists and keeps a table inside its owning clause", () => {
  const nested = nestedFixture();
  const nestedStructures = readOutlineStructures(nested.result, nested.presentation);
  assert.ok(nestedStructures);
  const nestedHtml = renderToStaticMarkup(
    renderValidatedOutlineStructure(nestedStructures.get("block-outline")!),
  );
  assert.match(
    nestedHtml,
    /^<ul class="parsed-list outline-list outline-list-root" data-outline-group="group-1" data-outline-policy="p03-outline-structure-v1">/,
  );
  assert.match(nestedHtml, /Root &lt;unsafe&gt;<\/span><ul class="outline-list">/);
  assert.match(nestedHtml, /data-source-marker="◦"/);
  assert.doesNotMatch(nestedHtml, /<unsafe>/);

  const legal = legalFixture();
  const legalStructures = readOutlineStructures(legal.result, legal.presentation);
  assert.ok(legalStructures);
  const legalHtml = renderToStaticMarkup(
    renderValidatedOutlineStructure(legalStructures.get("block-legal")!),
  );
  assert.match(legalHtml, /^<ol [^>]*start="1"[^>]*type="a"/);
  assert.match(legalHtml, /data-source-marker="b\." value="2"><span[^>]*>Beta<\/span>/);
  assert.match(
    legalHtml,
    /data-outline-item="node-b"[\s\S]*?<table class="parsed-table">[\s\S]*?<\/table>[\s\S]*?<\/li>/,
  );
  assert.match(legalHtml, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(legalHtml, /<script>/);
});

test("unknown, partial, inconsistent, and canonically detached sidecars fail closed", () => {
  const mutations: Array<(result: ParseResult) => void> = [
    (result) => {
      (result.pages[0].items[0].outline_group as OutlineGroup & { extra?: boolean }).extra = true;
    },
    (result) => {
      result.pages[0].items[0].outline_items![1].parent_id = null;
    },
    (result) => {
      result.pages[0].items[0].outline_group!.canonical_contributor_element_ids.pop();
    },
    (result) => {
      result.pages[0].items[0].outline_items![0].source_public_path = [
        "pages",
        1,
        "items",
        0,
      ];
    },
    (result) => {
      result.pages[0].items[0].outline_group!.canonical_text_sha256 = digest.toUpperCase();
    },
    (result) => {
      result.pages[0].items[0].relationships!.pop();
    },
    (result) => {
      delete result.pages[0].items[0].outline_continuations;
    },
  ];
  for (const mutate of mutations) {
    const fixture = nestedFixture();
    mutate(fixture.result);
    assert.equal(
      readOutlineStructures(
        fixture.result,
        fixture.result.canonical_presentation!,
      ),
      null,
    );
  }

  const absent = nestedFixture();
  const anchor = absent.result.pages[0].items[0];
  delete anchor.layout_outline_structure_projected;
  delete anchor.outline_policy;
  delete anchor.outline_group;
  delete anchor.outline_items;
  delete anchor.outline_continuations;
  const empty = readOutlineStructures(absent.result, absent.presentation);
  assert.ok(empty);
  assert.equal(empty.size, 0);

  const unsafeTableMetadata = legalFixture();
  unsafeTableMetadata.result.pages[0].items[2].cells = {} as never;
  assert.equal(
    readOutlineStructures(
      unsafeTableMetadata.result,
      unsafeTableMetadata.presentation,
    ),
    null,
  );

  const legalWithDecimalMarkers = legalFixture();
  legalWithDecimalMarkers.result.pages[0].items[0].outline_group!.marker_style =
    "decimal";
  for (const item of legalWithDecimalMarkers.result.pages[0].items[0]
    .outline_items!) {
    item.marker_style = "decimal";
  }
  assert.equal(
    readOutlineStructures(
      legalWithDecimalMarkers.result,
      legalWithDecimalMarkers.presentation,
    ),
    null,
  );

  const orderedWithAlphaMarkers = legalFixture();
  orderedWithAlphaMarkers.result.pages[0].items[0].outline_group!.sequence_kind =
    "ordered";
  for (const item of orderedWithAlphaMarkers.result.pages[0].items[0]
    .outline_items!) {
    item.sequence_kind = "ordered";
  }
  assert.equal(
    readOutlineStructures(
      orderedWithAlphaMarkers.result,
      orderedWithAlphaMarkers.presentation,
    ),
    null,
  );

  const unclaimedCanonicalContributor = nestedFixture();
  unclaimedCanonicalContributor.result.pages[0].items[0].outline_group!
    .canonical_contributor_element_ids.push("unclaimed-element");
  unclaimedCanonicalContributor.result.canonical_presentation!.pages[0].blocks[0]
    .contributing_element_ids.push("unclaimed-element");
  assert.equal(
    readOutlineStructures(
      unclaimedCanonicalContributor.result,
      unclaimedCanonicalContributor.presentation,
    ),
    null,
  );
});

test("normalization preserves additive fields while copy/download serialization stays canonical", () => {
  const { result } = nestedFixture();
  const normalized = normalizeDocumentJson(result);
  const normalizedAnchor = normalized.items.pages[0].items[0];
  assert.equal(normalizedAnchor.layout_outline_structure_projected, true);
  assert.deepEqual(
    normalizedAnchor.outline_group,
    result.pages[0].items[0].outline_group,
  );
  assert.deepEqual(
    normalizedAnchor.outline_items,
    result.pages[0].items[0].outline_items,
  );
  assert.equal(
    serializePageMarkdown(result.pages[0], result),
    result.canonical_presentation!.pages[0].full.markdown,
  );
  assert.match(workspaceSource, /readOutlineStructures\(result, canonicalPresentation\)/);
  assert.match(
    workspaceSource,
    /hasOwnProperty\.call\([\s\S]*?result\.processing,[\s\S]*?"outline_structure"/,
  );
  assert.match(workspaceSource, /EMPTY_OUTLINE_STRUCTURES/);
  assert.match(workspaceSource, /renderValidatedOutlineStructure\(outlineStructure/);
  assert.match(workspaceSource, /if \(outlineStructures === null\) return canonicalFallback/);
  assert.match(workspaceSource, /renderContinuation: renderOutlineContinuation/);
  assert.doesNotMatch(workspaceSource, /dangerouslySetInnerHTML/);
});
