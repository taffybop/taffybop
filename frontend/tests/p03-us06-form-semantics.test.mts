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
  FormControl,
  FormGrid,
  FormGridCell,
  FormGridContentFragment,
  FormGroup,
  FormLabel,
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

const ACORD_GRID_ROWS = [
  288, 300, 312, 324, 336, 348, 360, 372, 384, 396, 408, 420, 432,
  444, 456, 468, 480, 492, 504, 516, 528, 564,
];
const ACORD_GRID_COLUMNS = [
  18, 36, 176.4, 194.4, 212.4, 331.2, 378, 424.8, 514.8, 594,
];

function realisticAcordGridFixture(): {
  page: PageResult;
  anchor: DocumentContentItem;
  block: CanonicalBlock;
} {
  const bboxFor = (
    row: number,
    column: number,
    rowSpan: number,
    columnSpan: number,
  ) => ({
    x: ACORD_GRID_COLUMNS[column]!,
    y: ACORD_GRID_ROWS[row]!,
    width:
      ACORD_GRID_COLUMNS[column + columnSpan]! - ACORD_GRID_COLUMNS[column]!,
    height: ACORD_GRID_ROWS[row + rowSpan]! - ACORD_GRID_ROWS[row]!,
    unit: "pt" as const,
  });
  const confidence = (state = 1) => ({
    geometry: { score: 1 },
    role: { score: 1 },
    transcription: { score: 1 },
    state: { score: state },
  });
  const cells: FormGridCell[] = [];
  let sourceOffset = 1_000;
  const appendCell = ({
    row,
    column,
    rowSpan = 1,
    columnSpan = 1,
    cellRole,
    staticKind,
    text,
    valueState,
    controlIds = [],
    fragments,
    stateConfidence = 1,
  }: {
    row: number;
    column: number;
    rowSpan?: number;
    columnSpan?: number;
    cellRole: FormGridCell["cell_role"];
    staticKind: FormGridCell["static_kind"];
    text: string | null;
    valueState: FormGridCell["value_state"];
    controlIds?: string[];
    fragments?: FormGridContentFragment[];
    stateConfidence?: number;
  }) => {
    const bbox = bboxFor(row, column, rowSpan, columnSpan);
    const readingOrder = cells.length;
    const contentFragments =
      fragments ??
      (text === null
        ? []
        : [
            {
              source_order: 0,
              kind: "text" as const,
              bbox: {
                x: bbox.x + 1,
                y: bbox.y + 1,
                width: Math.max(1, bbox.width - 2),
                height: Math.min(8, bbox.height - 2),
                unit: "pt" as const,
              },
              text,
              control_id: null,
              source_objects: [
                {
                  kind: "character_range" as const,
                  start: sourceOffset,
                  end: sourceOffset + 1,
                },
              ],
            },
          ]);
    sourceOffset += 2;
    const sourceObjects = [
      { kind: "line" as const, index: readingOrder },
      ...contentFragments.flatMap((fragment) => fragment.source_objects),
    ];
    cells.push({
      reading_order: readingOrder,
      row,
      column,
      row_span: rowSpan,
      column_span: columnSpan,
      bbox,
      cell_role: cellRole,
      static_kind: staticKind,
      text,
      text_state: text === null ? "empty" : "present",
      value: null,
      value_state: valueState,
      control_ids: controlIds,
      content_fragments: contentFragments,
      header_cell_orders: [],
      section_cell_orders: [],
      label_cell_orders: [],
      source_objects: sourceObjects,
      confidence_dimensions: confidence(stateConfidence),
      concern_codes:
        valueState === "ambiguous" ? ["form_value_state_ambiguous"] : [],
    });
  };

  const columnHeaders = [
    "INSR LTR",
    "TYPE OF INSURANCE",
    "ADDL INSR",
    "SUBR WVD",
    "POLICY NUMBER",
    "POLICY EFF (MM/DD/YYYY)",
    "POLICY EXP (MM/DD/YYYY)",
  ];
  columnHeaders.forEach((text, column) =>
    appendCell({
      row: 0,
      column,
      cellRole: "static",
      staticKind: "column_header",
      text,
      valueState: "not_applicable",
    }),
  );
  appendCell({
    row: 0,
    column: 7,
    columnSpan: 2,
    cellRole: "static",
    staticKind: "column_header",
    text: "LIMITS",
    valueState: "not_applicable",
  });

  const sectionSpecs = [
    { row: 1, span: 7, title: "GENERAL LIABILITY", controlId: "control-cgl" },
    { row: 8, span: 5, title: "AUTOMOBILE LIABILITY", controlId: "control-auto" },
    { row: 13, span: 3, title: "UMBRELLA LIABILITY", controlId: null },
    { row: 16, span: 4, title: "WORKERS COMPENSATION", controlId: null },
  ];
  for (const section of sectionSpecs) {
    appendCell({
      row: section.row,
      column: 0,
      rowSpan: section.span,
      cellRole: "value",
      staticKind: null,
      text: null,
      valueState: "empty",
    });
    const sectionBox = bboxFor(section.row, 1, section.span, 1);
    const sectionFragments: FormGridContentFragment[] = [
      {
        source_order: 0,
        kind: "text",
        bbox: {
          x: sectionBox.x + 3,
          y: sectionBox.y + 3,
          width: sectionBox.width - 6,
          height: 7,
          unit: "pt",
        },
        text: section.title,
        control_id: null,
        source_objects: [
          { kind: "character_range", start: sourceOffset, end: sourceOffset + 1 },
        ],
      },
    ];
    sourceOffset += 2;
    if (section.controlId !== null) {
      sectionFragments.push(
        {
          source_order: 1,
          kind: "control",
          bbox: {
            x: sectionBox.x + 3,
            y: sectionBox.y + 14,
            width: 10,
            height: 10,
            unit: "pt",
          },
          text: null,
          control_id: section.controlId,
          source_objects: [{ kind: "rect", index: 200 + section.row }],
        },
        {
          source_order: 2,
          kind: "text",
          bbox: {
            x: sectionBox.x + 18,
            y: sectionBox.y + 15,
            width: sectionBox.width - 21,
            height: 8,
            unit: "pt",
          },
          text:
            section.controlId === "control-cgl"
              ? "COMMERCIAL GENERAL LIABILITY"
              : "ANY AUTO",
          control_id: null,
          source_objects: [
            { kind: "character_range", start: sourceOffset, end: sourceOffset + 1 },
          ],
        },
      );
      sourceOffset += 2;
    }
    appendCell({
      row: section.row,
      column: 1,
      rowSpan: section.span,
      cellRole: "static",
      staticKind: "section_header",
      text: sectionFragments
        .flatMap((fragment) => (fragment.kind === "text" ? [fragment.text!] : []))
        .join("\n"),
      valueState: "not_applicable",
      controlIds: section.controlId === null ? [] : [section.controlId],
      fragments: sectionFragments,
    });
    for (let column = 2; column <= 6; column += 1) {
      appendCell({
        row: section.row,
        column,
        rowSpan: section.span,
        cellRole: "value",
        staticKind: null,
        text: null,
        valueState: "empty",
      });
    }
    for (let row = section.row; row < section.row + section.span; row += 1) {
      appendCell({
        row,
        column: 7,
        cellRole: "static",
        staticKind: "row_header",
        text: `LIMIT ${row}`,
        valueState: "not_applicable",
      });
      appendCell({
        row,
        column: 8,
        cellRole: "value",
        staticKind: null,
        text: null,
        valueState: row === 1 ? "ambiguous" : "empty",
        stateConfidence: row === 1 ? 0.62 : 1,
      });
    }
  }
  appendCell({
    row: 20,
    column: 0,
    columnSpan: 9,
    cellRole: "static",
    staticKind: "qualifier",
    text: "DESCRIPTION OF OPERATIONS / LOCATIONS / VEHICLES",
    valueState: "not_applicable",
  });

  cells.sort((left, right) => left.row - right.row || left.column - right.column);
  cells.forEach((cell, index) => {
    cell.reading_order = index;
  });
  const headers = cells.filter((cell) => cell.static_kind === "column_header");
  const sections = cells.filter((cell) => cell.static_kind === "section_header");
  const rowLabels = cells.filter((cell) => cell.static_kind === "row_header");
  for (const cell of cells) {
    cell.header_cell_orders = headers
      .filter(
        (header) =>
          cell.static_kind !== "column_header" &&
          Math.max(header.column, cell.column) <
            Math.min(
              header.column + header.column_span,
              cell.column + cell.column_span,
            ),
      )
      .map((header) => header.reading_order);
    cell.section_cell_orders = sections
      .filter(
        (section) =>
          cell.cell_role === "value" &&
          section.row <= cell.row &&
          cell.row < section.row + section.row_span,
      )
      .map((section) => section.reading_order);
    cell.label_cell_orders = rowLabels
      .filter(
        (label) =>
          cell.cell_role === "value" &&
          cell.row_span === 1 &&
          label.row === cell.row &&
          label.column + label.column_span === cell.column,
      )
      .map((label) => label.reading_order);
  }

  const grid: FormGrid = {
    bbox: { x: 18, y: 288, width: 576, height: 276, unit: "pt" },
    row_boundaries: [...ACORD_GRID_ROWS],
    column_boundaries: [...ACORD_GRID_COLUMNS],
    cells,
  };
  const group = {
    ...common("coverage-grid-group", "coverage-grid-element", [], grid.bbox),
    evidence_methods: ["vector"] as const,
    source_objects: [{ kind: "rect" as const, index: 900 }],
    group_key: "coverages",
    status: "resolved" as const,
    interactivity: "static" as const,
    canonical_mode: "replace" as const,
    anchor_public_item_id: "coverage-grid-anchor",
    anchor_element_id: "coverage-grid-source",
    anchor_relationship_ids: ["rel-grid-overlay"],
    contributor_public_item_ids: ["coverage-grid-anchor"],
    contributor_element_ids: ["coverage-grid-source"],
    field_ids: [],
    label_ids: ["label-cgl", "label-auto"],
    value_region_ids: [],
    control_ids: ["control-cgl", "control-auto"],
    key_value_pair_ids: [],
    form_grid: grid,
  } satisfies FormGroup;
  const labels: FormLabel[] = [
    {
      ...common("label-cgl", "label-cgl-element", []),
      group_id: group.id,
      label_role: "control",
      text: "COMMERCIAL GENERAL LIABILITY",
      raw_text: "COMMERCIAL GENERAL LIABILITY",
      label_of_ids: ["control-cgl"],
      key_of_ids: [],
    },
    {
      ...common("label-auto", "label-auto-element", []),
      group_id: group.id,
      label_role: "control",
      text: "ANY AUTO",
      raw_text: "ANY AUTO",
      label_of_ids: ["control-auto"],
      key_of_ids: [],
    },
  ];
  const controls: FormControl[] = [
    {
      ...common("control-cgl", "control-cgl-element", [], {
        x: 39,
        y: 314,
        width: 8,
        height: 8,
        unit: "pt",
      }),
      evidence_methods: ["vector"],
      source_objects: [{ kind: "rect", index: 201 }],
      group_id: group.id,
      owner_field_id: null,
      label_id: "label-cgl",
      control_type: "checkbox",
      state: "unchecked",
      origin: "static_vector",
    },
    {
      ...common("control-auto", "control-auto-element", [], {
        x: 39,
        y: 398,
        width: 8,
        height: 8,
        unit: "pt",
      }),
      evidence_methods: ["vector"],
      source_objects: [{ kind: "rect", index: 208 }],
      confidence_dimensions: {
        geometry: { score: 1 },
        role: { score: 0.9 },
        transcription: { unavailable_reason: "transcription_not_applicable" },
        state: { score: 0.44 },
      },
      concern_codes: ["form_control_state_ambiguous"],
      group_id: group.id,
      owner_field_id: null,
      label_id: "label-auto",
      control_type: "checkbox",
      state: "ambiguous",
      origin: "static_vector",
    },
  ];
  const edges: FormRelationship[] = [
    relationship("rel-grid-label-cgl", "contains", group.element_id, labels[0]!.element_id),
    relationship("rel-grid-label-auto", "contains", group.element_id, labels[1]!.element_id),
    relationship("rel-grid-control-cgl", "contains", group.element_id, controls[0]!.element_id),
    relationship("rel-grid-control-auto", "contains", group.element_id, controls[1]!.element_id),
    relationship("rel-grid-label-of-cgl", "label_of", labels[0]!.element_id, controls[0]!.element_id),
    relationship("rel-grid-label-of-auto", "label_of", labels[1]!.element_id, controls[1]!.element_id),
    relationship("rel-grid-control-of-cgl", "control_of", controls[0]!.element_id, group.element_id),
    relationship("rel-grid-control-of-auto", "control_of", controls[1]!.element_id, group.element_id),
    relationship("rel-grid-overlay", "form_overlay_of", group.element_id, group.anchor_element_id),
  ];
  for (const record of [group, ...labels, ...controls]) {
    record.relationship_ids = edges
      .filter(
        (edge) =>
          edge.source_id === record.element_id || edge.target_id === record.element_id,
      )
      .map((edge) => edge.id);
  }
  const anchor: DocumentContentItem = {
    id: group.anchor_public_item_id,
    type: "table_candidate",
    reading_order: 14,
    value: "flattened fallback must not render",
    md: "flattened fallback must not render",
    bbox: { ...grid.bbox },
    layout_forms_projected: true,
    form_policy: "p03-form-semantics-v1",
    form_group: group,
    form_labels: labels,
    form_controls: controls,
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
      ...canonicalBlock(group.anchor_element_id, [group.anchor_element_id]),
      primary_element_type: "table_candidate",
      markdown: "<table data-form-grid=\"true\">",
      text: "flattened fallback must not render",
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

test("a realistic 21x9 ACORD coverage grid renders as one accessible source-ordered table", () => {
  const { page, block } = realisticAcordGridFixture();
  const semantics = readFormSemanticsForCanonicalBlock(block, page);
  assert.ok(semantics);
  assert.equal(semantics.group.form_grid?.row_boundaries.length, 22);
  assert.equal(semantics.group.form_grid?.column_boundaries.length, 10);

  const html = renderToStaticMarkup(
    renderValidatedFormSemantics(semantics, { overlay: true }),
  );
  assert.match(
    html,
    /<table class="parsed-table form-grid-table" aria-label="coverages form grid" data-form-grid="true">/,
  );
  assert.equal(html.match(/<tr /gu)?.length, 21);
  assert.match(html, /<thead>/);
  assert.match(html, /<tbody>/);
  assert.match(html, /rowSpan="7"/);
  assert.match(html, /colSpan="2"/);
  assert.match(html, /scope="col"/);
  assert.match(html, /scope="row"/);
  assert.doesNotMatch(html, /scope="rowgroup"/);
  assert.match(
    html,
    /<th[^>]*headers="[^"]+"[^>]*data-static-kind="section_header"/,
  );
  assert.match(html, /headers="form-grid-[^"]+-cell-7/);
  assert.match(html, /role="checkbox" aria-checked="false"/);
  assert.match(html, /role="checkbox" aria-checked="mixed"/);
  assert.match(html, /COMMERCIAL GENERAL LIABILITY: Unchecked/);
  assert.match(html, /ANY AUTO: State ambiguous/);
  assert.match(
    html,
    /data-control-id="control-auto"[^>]*data-concern-codes="form_control_state_ambiguous"/,
  );
  assert.match(
    html,
    /data-control-id="control-auto"[^>]*data-confidence-role="0.9"[^>]*data-confidence-transcription="unavailable:transcription_not_applicable"[^>]*data-confidence-state="0.44"/,
  );
  assert.match(
    html,
    /aria-describedby="[^"]+-control-confidence-control-auto-[0-9a-f]{8}"/,
  );
  assert.match(html, /data-value-state="ambiguous"/);
  assert.match(html, />Uncertain value</);
  assert.match(html, />Confidence 62%<\/span>/);
  assert.match(html, /data-confidence-state="0.62"/);
  assert.match(html, /data-confidence-geometry="1"/);
  assert.match(html, /left:[^;]+%;top:[^;]+%;width:[^;]+%;height:[^;]+%/);
  assert.match(html, /aspect-ratio:[^;]+\//);
  assert.doesNotMatch(html, /flattened fallback must not render/);
  assert.doesNotMatch(html, /<input|dangerouslySetInnerHTML/i);

  const generalIndex = html.indexOf(">GENERAL LIABILITY<");
  const checkboxIndex = html.indexOf('data-control-id="control-cgl"');
  const commercialIndex = html.indexOf(">COMMERCIAL GENERAL LIABILITY<");
  assert.ok(
    generalIndex >= 0 &&
      generalIndex < checkboxIndex &&
      checkboxIndex < commercialIndex,
    "positioned fragments must preserve source order in the DOM",
  );
});

test("ACORD form-grid topology and custody failures fall back closed", () => {
  const cases: Array<{
    name: string;
    mutate: (anchor: DocumentContentItem) => void;
  }> = [
    {
      name: "unknown group member",
      mutate: (anchor) => {
        (anchor.form_group as unknown as Record<string, unknown>).unexpected = true;
      },
    },
    {
      name: "non-canonical reading order",
      mutate: (anchor) => {
        anchor.form_group!.form_grid!.cells[1]!.reading_order = 9;
      },
    },
    {
      name: "overlapping logical cell",
      mutate: (anchor) => {
        const cells = anchor.form_group!.form_grid!.cells;
        cells[1]!.column = cells[0]!.column;
        cells[1]!.bbox = structuredClone(cells[0]!.bbox);
      },
    },
    {
      name: "uncovered logical slot",
      mutate: (anchor) => {
        anchor.form_group!.form_grid!.cells.pop();
      },
    },
    {
      name: "cell bbox disagrees with its span",
      mutate: (anchor) => {
        anchor.form_group!.form_grid!.cells[0]!.bbox.width += 1;
      },
    },
    {
      name: "fragment order is not contiguous",
      mutate: (anchor) => {
        const section = anchor.form_group!.form_grid!.cells.find(
          (cell) => cell.content_fragments.length > 1,
        )!;
        section.content_fragments[1]!.source_order = 8;
      },
    },
    {
      name: "semantic header reference is incomplete",
      mutate: (anchor) => {
        const value = anchor.form_group!.form_grid!.cells.find(
          (cell) => cell.row > 0 && cell.cell_role === "value",
        )!;
        value.header_cell_orders = [];
      },
    },
    {
      name: "grid control is not declared by the group",
      mutate: (anchor) => {
        anchor.form_group!.control_ids.pop();
        anchor.form_controls!.pop();
      },
    },
    {
      name: "ambiguous value lacks an uncertainty concern",
      mutate: (anchor) => {
        const ambiguous = anchor.form_group!.form_grid!.cells.find(
          (cell) => cell.value_state === "ambiguous",
        )!;
        ambiguous.concern_codes = [];
      },
    },
  ];

  for (const testCase of cases) {
    const fixture = realisticAcordGridFixture();
    testCase.mutate(fixture.anchor);
    assert.equal(
      readFormSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
      testCase.name,
    );
  }
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
