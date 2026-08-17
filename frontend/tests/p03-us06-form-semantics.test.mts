import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  readFormSemanticsForCanonicalBlock,
  renderValidatedFormSemantics,
  type ValidatedFormSemantics,
} from "../lib/form-semantics.ts";
import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import type {
  CanonicalBlock,
  DocumentContentItem,
  FormRelationship,
  FormSemanticRecordBase,
  PageResult,
} from "../lib/types.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);

function common(
  id: string,
  elementId: string,
  relationshipIds: string[],
  bbox = { x: 20, y: 20, width: 80, height: 12, unit: "pt" as const },
): FormSemanticRecordBase {
  return {
    id,
    element_id: elementId,
    page_index: 1,
    bbox,
    evidence_methods: ["native"],
    source_objects: [{ kind: "character_range", start: 0, end: 1 }],
    confidence_dimensions: {
      geometry: { score: 1 },
      role: { unavailable_reason: "not_calibrated" },
      transcription: { score: 1 },
      state: { unavailable_reason: "not_calibrated" },
    },
    concern_codes: [],
    relationship_ids: relationshipIds,
  };
}

function relationship(
  id: string,
  type: FormRelationship["type"],
  sourceId: string,
  targetId: string,
): FormRelationship {
  return {
    id,
    type,
    source_id: sourceId,
    target_id: targetId,
    evidence_ids: [],
    canonical_inert: true,
  };
}

function canonicalBlock(
  anchorElementId: string,
  contributingElementIds: string[],
): CanonicalBlock {
  return {
    id: "canonical-form",
    page_id: "canonical-page-1",
    primary_element_id: anchorElementId,
    primary_element_type: "key_value",
    scope: "body",
    markdown: "- **PIN40:** <script>alert(1)</script>",
    text: "PIN40: <script>alert(1)</script>",
    contributing_element_ids: contributingElementIds,
    relationship_ids: [],
    excluded_contributions: [],
  };
}

function keyValueFixture(): {
  page: PageResult;
  anchor: DocumentContentItem;
  block: CanonicalBlock;
} {
  const edges = [
    relationship("rel-group-pair", "contains", "sem-group", "sem-pair"),
    relationship("rel-pair-label", "contains", "sem-pair", "sem-label"),
    relationship("rel-pair-value", "contains", "sem-pair", "sem-value"),
    relationship("rel-key", "key_of", "sem-label", "sem-pair"),
    relationship("rel-value", "value_of", "sem-value", "sem-pair"),
  ];
  const anchor: DocumentContentItem = {
    id: "p1-key",
    type: "text",
    reading_order: 0,
    value: "PIN40",
    md: "PIN40",
    bbox: { x: 20, y: 20, width: 40, height: 12, unit: "pt" },
    layout_forms_projected: true,
    form_policy: "p03-form-semantics-v1",
    form_group: {
      ...common("group", "sem-group", ["rel-group-pair"], {
        x: 20,
        y: 20,
        width: 180,
        height: 30,
        unit: "pt",
      }),
      group_key: "pins",
      status: "resolved",
      interactivity: "none",
      canonical_mode: "replace",
      anchor_public_item_id: "p1-key",
      anchor_element_id: "source-key",
      anchor_relationship_ids: [],
      contributor_public_item_ids: ["p1-key", "p1-value"],
      contributor_element_ids: ["source-key", "source-value"],
      field_ids: [],
      label_ids: ["key-label"],
      value_region_ids: ["value-region"],
      control_ids: [],
      key_value_pair_ids: ["pair"],
    },
    form_labels: [
      {
        ...common("key-label", "sem-label", ["rel-pair-label", "rel-key"]),
        group_id: "group",
        label_role: "key",
        text: "PIN40",
        raw_text: "PIN40",
        label_of_ids: [],
        key_of_ids: ["pair"],
      },
    ],
    form_value_regions: [
      {
        ...common(
          "value-region",
          "sem-value",
          ["rel-pair-value", "rel-value"],
          { x: 80, y: 20, width: 120, height: 12, unit: "pt" },
        ),
        group_id: "group",
        owner_id: "pair",
        excluded_label_ids: [],
        value: "<script>alert(1)</script>",
        value_state: "present",
      },
    ],
    form_key_value_pairs: [
      {
        ...common(
          "pair",
          "sem-pair",
          [
            "rel-group-pair",
            "rel-pair-label",
            "rel-pair-value",
            "rel-key",
            "rel-value",
          ],
          { x: 20, y: 20, width: 180, height: 12, unit: "pt" },
        ),
        group_id: "group",
        pair_key: "pins:pin40",
        key_label_id: "key-label",
        value_region_id: "value-region",
        key: "PIN40",
        value: "<script>alert(1)</script>",
        value_state: "present",
        key_source_item_id: "p1-key",
        value_source_item_id: "p1-value",
      },
    ],
    relationships: edges,
  };
  const valueItem: DocumentContentItem = {
    id: "p1-value",
    type: "text",
    reading_order: 1,
    value: "<script>alert(1)</script>",
    md: "<script>alert(1)</script>",
  };
  return {
    page: samplePage({
      page_index: 1,
      page_width: 612,
      page_height: 792,
      items: [anchor, valueItem],
    }),
    anchor,
    block: canonicalBlock("source-key", ["source-key", "source-value"]),
  };
}

function formOverlayFixture(): {
  page: PageResult;
  anchor: DocumentContentItem;
  block: CanonicalBlock;
} {
  const edges = [
    relationship("rel-group-field", "contains", "form-group", "form-field"),
    relationship("rel-group-field-label", "contains", "form-group", "field-label"),
    relationship("rel-group-control-label", "contains", "form-group", "control-label"),
    relationship("rel-group-control", "contains", "form-group", "control"),
    relationship("rel-field-value", "contains", "form-field", "field-value"),
    relationship("rel-label-field", "label_of", "field-label", "form-field"),
    relationship("rel-label-control", "label_of", "control-label", "control"),
    relationship("rel-value-field", "value_of", "field-value", "form-field"),
    relationship("rel-control-group", "control_of", "control", "form-group"),
    relationship("rel-overlay", "form_overlay_of", "form-group", "table-source"),
  ];
  const anchor: DocumentContentItem = {
    id: "coverage-table",
    type: "table",
    reading_order: 0,
    rows: [["Coverage", "Limit"]],
    md: "| Coverage | Limit |",
    layout_forms_projected: true,
    form_policy: "p03-form-semantics-v1",
    form_group: {
      ...common(
        "coverage-group",
        "form-group",
        [
          "rel-group-field",
          "rel-group-field-label",
          "rel-group-control-label",
          "rel-group-control",
          "rel-control-group",
          "rel-overlay",
        ],
        { x: 18, y: 240, width: 576, height: 324, unit: "pt" },
      ),
      concern_codes: ["form_table_ownership_ambiguous"],
      group_key: "coverages",
      status: "unresolved",
      interactivity: "static",
      canonical_mode: "inert",
      anchor_public_item_id: "coverage-table",
      anchor_element_id: "table-source",
      anchor_relationship_ids: ["rel-overlay"],
      contributor_public_item_ids: ["coverage-table"],
      contributor_element_ids: ["table-source"],
      field_ids: ["certificate-field"],
      label_ids: ["certificate-label", "checkbox-label"],
      value_region_ids: ["certificate-value"],
      control_ids: ["checkbox"],
      key_value_pair_ids: [],
    },
    form_fields: [
      {
        ...common(
          "certificate-field",
          "form-field",
          ["rel-group-field", "rel-field-value", "rel-label-field", "rel-value-field"],
        ),
        group_id: "coverage-group",
        field_key: "certificate-number",
        label_ids: ["certificate-label"],
        value_region_id: "certificate-value",
        control_ids: [],
        value: null,
        value_state: "empty",
      },
    ],
    form_labels: [
      {
        ...common(
          "certificate-label",
          "field-label",
          ["rel-group-field-label", "rel-label-field"],
        ),
        group_id: "coverage-group",
        label_role: "field",
        text: "<script>CERTIFICATE NUMBER</script>",
        raw_text: "<script>CERTIFICATE NUMBER</script>",
        label_of_ids: ["certificate-field"],
        key_of_ids: [],
      },
      {
        ...common(
          "checkbox-label",
          "control-label",
          ["rel-group-control-label", "rel-label-control"],
        ),
        group_id: "coverage-group",
        label_role: "control",
        text: "COMMERCIAL GENERAL LIABILITY",
        raw_text: "COMMERCIAL GENERAL LIABILITY",
        label_of_ids: ["checkbox"],
        key_of_ids: [],
      },
    ],
    form_value_regions: [
      {
        ...common(
          "certificate-value",
          "field-value",
          ["rel-field-value", "rel-value-field"],
        ),
        group_id: "coverage-group",
        owner_id: "certificate-field",
        excluded_label_ids: ["certificate-label"],
        value: null,
        value_state: "empty",
      },
    ],
    form_controls: [
      {
        ...common(
          "checkbox",
          "control",
          ["rel-group-control", "rel-label-control", "rel-control-group"],
          { x: 36, y: 312, width: 14.4, height: 12, unit: "pt" },
        ),
        group_id: "coverage-group",
        owner_field_id: null,
        label_id: "checkbox-label",
        control_type: "checkbox",
        state: "unchecked",
        origin: "static_vector",
      },
    ],
    relationships: edges,
  };
  return {
    page: samplePage({
      page_index: 1,
      page_width: 612,
      page_height: 792,
      items: [anchor],
    }),
    anchor,
    block: {
      ...canonicalBlock("table-source", ["table-source"]),
      primary_element_type: "table",
      markdown: "| Coverage | Limit |",
      text: "Coverage | Limit",
    },
  };
}

function completeStaticPartiesSemantics(): ValidatedFormSemantics {
  const groupId = "parties-group";
  const groupElementId = "parties-group-element";
  const fields: ValidatedFormSemantics["fields"] = [];
  const labels: ValidatedFormSemantics["labels"] = [];

  const addField = (
    fieldKey: string,
    text: string,
    bbox: { x: number; y: number; width: number; height: number; unit: "pt" },
    extraLabelIds: string[] = [],
  ) => {
    const fieldId = `field-${fieldKey}`;
    const labelId = `label-${fieldKey}`;
    fields.push({
      ...common(fieldId, `element-${fieldKey}`, [], bbox),
      evidence_methods: ["vector"],
      source_objects: [{ kind: "rect", index: fields.length }],
      group_id: groupId,
      field_key: fieldKey,
      label_ids: [labelId, ...extraLabelIds],
      value_region_id: `value-${fieldKey}`,
      control_ids: [],
      value: null,
      value_state: "empty",
    });
    labels.push({
      ...common(labelId, `label-element-${fieldKey}`, [] , {
        x: bbox.x + 1,
        y: bbox.y + 1,
        width: Math.min(bbox.width - 2, 100),
        height: Math.min(bbox.height - 2, 8),
        unit: "pt",
      }),
      group_id: groupId,
      label_role: "field",
      text,
      raw_text: text,
      label_of_ids: [fieldId],
      key_of_ids: [],
    });
  };

  addField("producer", "PRODUCER", {
    x: 18, y: 120, width: 288, height: 60, unit: "pt",
  });
  addField("contact-name", "CONTACT NAME:", {
    x: 306, y: 120, width: 288, height: 12, unit: "pt",
  });
  addField("phone", "PHONE (A/C, No, Ext):", {
    x: 306, y: 132, width: 176.4, height: 12, unit: "pt",
  });
  addField("fax", "FAX (A/C, No):", {
    x: 482.4, y: 132, width: 111.6, height: 12, unit: "pt",
  });
  addField("email-address", "E-MAIL ADDRESS:", {
    x: 306, y: 144, width: 288, height: 12, unit: "pt",
  });
  addField("insured", "INSURED", {
    x: 18, y: 180, width: 288, height: 60, unit: "pt",
  });

  const sharedLabelId = "label-naic";
  const naicFieldIds: string[] = [];
  for (const [index, row] of ["a", "b", "c", "d", "e", "f"].entries()) {
    const y = 168 + index * 12;
    const nameId = `field-insurer-${row}-name`;
    const naicId = `field-insurer-${row}-naic`;
    const rowLabelId = `label-insurer-${row}`;
    fields.push(
      {
        ...common(nameId, `element-insurer-${row}-name`, [], {
          x: 306, y, width: 234, height: 12, unit: "pt",
        }),
        evidence_methods: ["vector"],
        source_objects: [{ kind: "rect", index: 20 + index * 2 }],
        group_id: groupId,
        field_key: `insurer-${row}-name`,
        label_ids: [rowLabelId],
        value_region_id: `value-insurer-${row}-name`,
        control_ids: [],
        value: null,
        value_state: "empty",
      },
      {
        ...common(naicId, `element-insurer-${row}-naic`, [], {
          x: 540, y, width: 54, height: 12, unit: "pt",
        }),
        evidence_methods: ["vector"],
        source_objects: [{ kind: "rect", index: 21 + index * 2 }],
        group_id: groupId,
        field_key: `insurer-${row}-naic`,
        label_ids: [rowLabelId, sharedLabelId],
        value_region_id: `value-insurer-${row}-naic`,
        control_ids: [],
        value: null,
        value_state: "empty",
      },
    );
    labels.push({
      ...common(rowLabelId, `label-element-insurer-${row}`, [], {
        x: 309.6, y: y + 1, width: 40, height: 8, unit: "pt",
      }),
      group_id: groupId,
      label_role: "field",
      text: `INSURER ${row.toUpperCase()} :`,
      raw_text: `INSURER ${row.toUpperCase()} :`,
      label_of_ids: [nameId, naicId],
      key_of_ids: [],
    });
    naicFieldIds.push(naicId);
  }
  labels.push(
    {
      ...common("label-insurer-heading", "label-element-insurer-heading", [], {
        x: 309.6, y: 157, width: 120, height: 8, unit: "pt",
      }),
      group_id: groupId,
      label_role: "group",
      text: "INSURER(S) AFFORDING COVERAGE",
      raw_text: "INSURER(S) AFFORDING COVERAGE",
      label_of_ids: [groupId],
      key_of_ids: [],
    },
    {
      ...common(sharedLabelId, "label-element-naic", [], {
        x: 555, y: 157, width: 30, height: 8, unit: "pt",
      }),
      group_id: groupId,
      label_role: "field",
      text: "NAIC #",
      raw_text: "NAIC #",
      label_of_ids: naicFieldIds,
      key_of_ids: [],
    },
  );

  return {
    anchor: {
      id: "parties-anchor",
      type: "table_candidate",
      reading_order: 0,
      md: "source predecessor",
    },
    group: {
      ...common(groupId, groupElementId, [], {
        x: 18, y: 120, width: 576, height: 120, unit: "pt",
      }),
      evidence_methods: ["vector"],
      group_key: "parties-and-insurers",
      status: "resolved",
      interactivity: "static",
      canonical_mode: "replace",
      anchor_public_item_id: "parties-anchor",
      anchor_element_id: "source-parties",
      anchor_relationship_ids: [],
      contributor_public_item_ids: ["parties-anchor"],
      contributor_element_ids: ["source-parties"],
      field_ids: fields.map((field) => field.id),
      label_ids: labels.map((label) => label.id),
      value_region_ids: [],
      control_ids: [],
      key_value_pair_ids: [],
    },
    fields,
    labels,
    valueRegions: [],
    controls: [],
    keyValuePairs: [],
    relationships: [],
  };
}

test("strict key-value sidecars render as safe definition lists", () => {
  const { page, block } = keyValueFixture();
  const semantics = readFormSemanticsForCanonicalBlock(block, page);
  assert.ok(semantics);
  assert.equal(semantics.group.canonical_mode, "replace");

  const html = renderToStaticMarkup(renderValidatedFormSemantics(semantics));
  assert.match(html, /<dl class="form-semantics-list form-key-value-list">/);
  assert.match(html, /<dt>PIN40<\/dt>/);
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>|dangerouslySetInnerHTML|<input/i);
  assert.match(html, /data-source-page-index="1"/);
  assert.match(html, /data-source-bbox="20,20,180,12"/);
});

test("replace groups retain source-order custody when canonical contributors are anchor-first", () => {
  const { page, block } = keyValueFixture();
  const anchor = page.items[0];
  anchor.form_group!.contributor_public_item_ids = ["p1-value", "p1-key"];
  anchor.form_group!.contributor_element_ids = ["source-value", "source-key"];

  const semantics = readFormSemanticsForCanonicalBlock(block, page);

  assert.ok(semantics);
  assert.deepEqual(semantics.group.contributor_public_item_ids, [
    "p1-value",
    "p1-key",
  ]);
  assert.deepEqual(semantics.group.contributor_element_ids, [
    "source-value",
    "source-key",
  ]);
  assert.deepEqual(block.contributing_element_ids, [
    "source-key",
    "source-value",
  ]);
});

test("inert coverage semantics render fields and labeled read-only controls", () => {
  const { page, block } = formOverlayFixture();
  const semantics = readFormSemanticsForCanonicalBlock(block, page);
  assert.ok(semantics);
  assert.equal(semantics.group.canonical_mode, "inert");
  assert.equal(semantics.relationships.at(-1)?.type, "form_overlay_of");

  const html = renderToStaticMarkup(
    renderValidatedFormSemantics(semantics, { overlay: true }),
  );
  assert.match(html, /form-semantics-overlay-panel/);
  assert.match(html, /<dl class="form-semantics-list form-field-list">/);
  assert.match(html, /<dd data-value-state="empty"><\/dd>/);
  assert.doesNotMatch(html, /Empty source-visible field/);
  assert.match(html, /aria-label="Read-only form controls"/);
  assert.match(html, /COMMERCIAL GENERAL LIABILITY/);
  assert.match(html, /Unchecked/);
  assert.doesNotMatch(html, /<input|dangerouslySetInnerHTML/i);
});

test("complete blank parties and insurers render once in source visual order", () => {
  const semantics = completeStaticPartiesSemantics();
  const html = renderToStaticMarkup(
    renderValidatedFormSemantics(semantics, { overlay: true }),
  );

  assert.match(html, /<table class="parsed-table form-parties-table" aria-label="Parties and insurers">/);
  assert.match(html, /<th rowSpan="5" scope="row">PRODUCER<\/th>/);
  assert.match(html, /<th scope="row">CONTACT NAME:<\/th>/);
  assert.match(html, /<th colSpan="2" scope="col">INSURER\(S\) AFFORDING COVERAGE<\/th>/);
  assert.match(html, /<th rowSpan="5" scope="row">INSURED<\/th>/);
  assert.equal(html.match(/data-value-state="empty"/gu)?.length, 18);
  for (const label of semantics.labels) {
    assert.equal(html.split(label.text).length - 1, 1, label.text);
  }
  assert.doesNotMatch(html, /Empty source-visible field|<input|dangerouslySetInnerHTML/i);

  const entered = structuredClone(semantics);
  const contact = entered.fields.find((field) => field.field_key === "contact-name");
  assert.ok(contact);
  contact.value = "Alice Example";
  contact.value_state = "present";
  const genericHtml = renderToStaticMarkup(
    renderValidatedFormSemantics(entered, { overlay: true }),
  );
  assert.doesNotMatch(genericHtml, /aria-label="Parties and insurers"/);
  assert.match(genericHtml, /Alice Example/);
});

test("the closed thirteen-code concern set is accepted and max-plus-one fails closed", () => {
  const concernCodes = [
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
  ];
  const exact = formOverlayFixture();
  exact.page.items[0].form_group!.concern_codes = concernCodes;
  assert.ok(readFormSemanticsForCanonicalBlock(exact.block, exact.page));

  const overflow = formOverlayFixture();
  overflow.page.items[0].form_group!.concern_codes = [
    ...concernCodes,
    "form_source_limit",
  ];
  assert.equal(
    readFormSemanticsForCanonicalBlock(overflow.block, overflow.page),
    null,
  );
});

test("role-specific group max-plus-one ID lists fail closed", () => {
  const cases: Array<{
    property:
      | "field_ids"
      | "label_ids"
      | "value_region_ids"
      | "control_ids"
      | "key_value_pair_ids";
    count: number;
  }> = [
    { property: "field_ids", count: 129 },
    { property: "label_ids", count: 257 },
    { property: "value_region_ids", count: 129 },
    { property: "control_ids", count: 257 },
    { property: "key_value_pair_ids", count: 33 },
  ];

  for (const { property, count } of cases) {
    const fixture = formOverlayFixture();
    fixture.page.items[0].form_group![property] = Array.from(
      { length: count },
      (_, index) => `${property}:${index}`,
    );
    assert.equal(
      readFormSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
      `${property} max-plus-one must fail closed`,
    );
  }
});

test("duplicate, malformed, oversized, cross-page, and inconsistent sidecars fail closed", () => {
  const cases: Array<(page: PageResult, block: CanonicalBlock) => void> = [
    (page) => {
      page.items.push(structuredClone(page.items[0]));
    },
    (page) => {
      (page.items[0].form_group as unknown as Record<string, unknown>).extra = true;
    },
    (page) => {
      page.items[0].form_group!.concern_codes = Array.from(
        { length: 14 },
        (_, index) => `form-concern-${index}`,
      );
    },
    (page) => {
      page.items[0].form_key_value_pairs![0].bbox.x = 700;
    },
    (page) => {
      page.items[0].form_value_regions![0].value = null;
    },
    (page) => {
      page.items[0].form_key_value_pairs![0].relationship_ids.pop();
    },
    (page) => {
      const edge = page.items[0].relationships![0];
      edge.target_id = "wrong-semantic-node";
    },
    (_page, block) => {
      block.contributing_element_ids.reverse();
    },
  ];

  for (const mutate of cases) {
    const fixture = keyValueFixture();
    mutate(fixture.page, fixture.block);
    assert.equal(readFormSemanticsForCanonicalBlock(fixture.block, fixture.page), null);
  }
});

test("normalization preserves the complete additive sidecar without changing canonical copy", () => {
  const { page, anchor } = formOverlayFixture();
  const result = sampleResult({ pages: [page] });
  const before = structuredClone(anchor);
  const normalized = normalizeDocumentJson(result);

  assert.deepEqual(normalized.items.pages[0].items[0], before);
  assert.deepEqual(normalized.items.pages[0].items[0].form_group, before.form_group);
  assert.equal(normalized.markdown.pages[0].markdown, "| Coverage | Limit |");
  assert.deepEqual(anchor, before, "normalization must not mutate the API sidecar");
});

test("canonical rendering keeps fallback first for inert overlays and never creates form inputs", () => {
  const fallbackIndex = workspaceSource.indexOf("? canonicalFallback");
  const semanticIndex = workspaceSource.indexOf("{semanticView}", fallbackIndex);
  assert.ok(fallbackIndex >= 0 && semanticIndex > fallbackIndex);
  assert.match(workspaceSource, /readFormSemanticsForCanonicalBlock/);
  assert.match(workspaceSource, /formSemantics\.group\.canonical_mode === "inert"/);
  assert.doesNotMatch(workspaceSource, /dangerouslySetInnerHTML/);
});
