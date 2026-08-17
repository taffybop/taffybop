import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  readDiagramSemanticsForCanonicalBlock,
  renderValidatedDiagramSemantics,
} from "../lib/diagram-semantics.ts";
import type {
  CanonicalBlock,
  DocumentContentItem,
  PageResult,
} from "../lib/types.ts";
import { samplePage } from "./fixtures.mts";

type NodeSpec = {
  id: string;
  text: string;
  details?: string[];
  x?: number;
  y?: number;
};

type EdgeSpec = {
  id: string;
  source: string;
  target: string;
  label?: string;
};

type JsonRecord = Record<string, unknown>;

const compareIds = (left: string, right: string): number =>
  left < right ? -1 : left > right ? 1 : 0;
const PYTHON_EDGE_WHITESPACE =
  /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;
const pythonStripFixture = (value: string): string =>
  value.replace(PYTHON_EDGE_WHITESPACE, "");

const confidence = (geometry: number | null, direction: number | null) => ({
  geometry,
  calibration: null,
  category: null,
  series: null,
  value: null,
  direction,
});

const bbox = (
  x: number,
  y: number,
  width = 120,
  height = 36,
) => ({ x, y, width, height, unit: "pt" as const });

const rasterBbox = (
  x: number,
  y: number,
  width: number,
  height: number,
) => ({ x, y, width, height, unit: "px" as const });

function fixtureNodeBox(spec: NodeSpec, index: number) {
  return bbox(
    spec.x ?? 40,
    spec.y ?? 30 + index * 70,
    180,
    Math.max(36, 20 + (spec.details?.length ?? 0) * 10),
  );
}

function escapeDiagramMarkdown(value: string): string {
  return pythonStripFixture(
    value
    .replaceAll("\\", "\\\\")
    .replaceAll("|", "\\|")
    .replaceAll("\r\n", "<br>")
    .replaceAll("\r", "<br>")
    .replaceAll("\n", "<br>"),
  );
}

function expectedDiagramMarkdown(nodes: NodeSpec[], edges: EdgeSpec[]): string {
  const nodesById = new Map(nodes.map((node, index) => [node.id, { node, index }]));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, [] as EdgeSpec[]]));
  for (const edge of edges) {
    incoming.set(edge.target, (incoming.get(edge.target) ?? 0) + 1);
    outgoing.get(edge.source)?.push(edge);
  }
  const compareNodes = (leftId: string, rightId: string): number => {
    const left = nodesById.get(leftId)!;
    const right = nodesById.get(rightId)!;
    const leftBox = fixtureNodeBox(left.node, left.index);
    const rightBox = fixtureNodeBox(right.node, right.index);
    return (
      leftBox.y - rightBox.y ||
      leftBox.x - rightBox.x ||
      leftBox.width - rightBox.width ||
      leftBox.height - rightBox.height ||
      compareIds(leftId, rightId)
    );
  };
  for (const values of outgoing.values()) {
    values.sort(
      (left, right) =>
        compareNodes(left.target, right.target) || compareIds(left.id, right.id),
    );
  }
  const roots = nodes
    .filter((node) => incoming.get(node.id) === 0)
    .sort((left, right) => compareNodes(left.id, right.id));
  const seen = new Set<string>();
  const active = new Set<string>();
  const lines: string[] = [];
  const prefix = (edge: EdgeSpec | null): string =>
    edge?.label === undefined ? "" : `${escapeDiagramMarkdown(edge.label)}: `;
  const visit = (id: string, edge: EdgeSpec | null, depth: number): void => {
    const entry = nodesById.get(id)!;
    const indent = "  ".repeat(depth);
    lines.push(`${indent}- ${prefix(edge)}${escapeDiagramMarkdown(entry.node.text)}`);
    seen.add(id);
    active.add(id);
    for (const detail of entry.node.details ?? []) {
      lines.push(`${indent}  - ${escapeDiagramMarkdown(detail)}`);
    }
    for (const childEdge of outgoing.get(id) ?? []) {
      const childIndent = "  ".repeat(depth + 1);
      const child = nodesById.get(childEdge.target)!;
      if (active.has(childEdge.target)) {
        lines.push(
          `${childIndent}- ${prefix(childEdge)}Returns to: ${escapeDiagramMarkdown(child.node.text)}`,
        );
      } else if (seen.has(childEdge.target)) {
        lines.push(
          `${childIndent}- ${prefix(childEdge)}Continues at: ${escapeDiagramMarkdown(child.node.text)}`,
        );
      } else {
        visit(childEdge.target, childEdge, depth + 1);
      }
    }
    active.delete(id);
  };
  for (const root of roots) visit(root.id, null, 0);
  return lines.join("\n");
}

function graphFixture(
  nodes: NodeSpec[],
  edges: EdgeSpec[],
): {
  block: CanonicalBlock;
  owner: DocumentContentItem;
  page: PageResult;
} {
  const ownerId = "diagram-owner";
  const labels: JsonRecord[] = [];
  const evidence: JsonRecord[] = [
    {
      id: "ev-region",
      kind: "region",
      page_bbox: bbox(0, 0, 600, 700),
      chart_local_bbox: null,
      raster_pixel_bbox: null,
      transform_ids: [],
      provenance: {
        public_item_id: ownerId,
        page_index: 1,
        input_kind: "pdf",
        source_object_ids: ["source-region"],
        source_token_ids: [],
        extraction_method: "vector",
      },
    },
  ];
  let occurrenceIndex = 0;
  const diagramNodes = nodes.map((spec, index) => {
    const nodeBounds = fixtureNodeBox(spec, index);
    const mainLabelId = `label-${spec.id}`;
    const mainEvidenceId = `ev-label-${spec.id}`;
    labels.push({
      id: mainLabelId,
      text: spec.text,
      role: "node",
      page_bbox: bbox(nodeBounds.x + 4, nodeBounds.y + 4, 160, 8),
      raster_pixel_bbox: null,
      evidence_ids: [mainEvidenceId],
      occurrence_index: occurrenceIndex++,
    });
    evidence.push({
      id: mainEvidenceId,
      kind: "label",
      page_bbox: bbox(nodeBounds.x + 4, nodeBounds.y + 4, 160, 8),
      chart_local_bbox: null,
      raster_pixel_bbox: null,
      transform_ids: [],
      provenance: {
        public_item_id: ownerId,
        page_index: 1,
        input_kind: "pdf",
        source_object_ids: [`source-${mainEvidenceId}`],
        source_token_ids: [],
        extraction_method: "explicit_text",
      },
    });
    const detailLabelIds = (spec.details ?? []).map((text, detailIndex) => {
      const labelId = `detail-${spec.id}-${detailIndex}`;
      const evidenceId = `ev-${labelId}`;
      const detailBox = bbox(
        nodeBounds.x + 4,
        nodeBounds.y + 16 + detailIndex * 10,
        160,
        8,
      );
      labels.push({
        id: labelId,
        text,
        role: "node_detail",
        page_bbox: detailBox,
        raster_pixel_bbox: null,
        evidence_ids: [evidenceId],
        occurrence_index: occurrenceIndex++,
      });
      evidence.push({
        id: evidenceId,
        kind: "label",
        page_bbox: detailBox,
        chart_local_bbox: null,
        raster_pixel_bbox: null,
        transform_ids: [],
        provenance: {
          public_item_id: ownerId,
          page_index: 1,
          input_kind: "pdf",
          source_object_ids: [`source-${evidenceId}`],
          source_token_ids: [],
          extraction_method: "explicit_text",
        },
      });
      return labelId;
    });
    const nodeEvidenceId = `ev-node-${spec.id}`;
    evidence.push({
      id: nodeEvidenceId,
      kind: "node",
      page_bbox: nodeBounds,
      chart_local_bbox: null,
      raster_pixel_bbox: null,
      transform_ids: [],
      provenance: {
        public_item_id: ownerId,
        page_index: 1,
        input_kind: "pdf",
        source_object_ids: [`source-${nodeEvidenceId}`],
        source_token_ids: [],
        extraction_method: "vector",
      },
    });
    return {
      id: spec.id,
      shape: "rectangle",
      label_id: mainLabelId,
      detail_label_ids: detailLabelIds,
      page_bbox: nodeBounds,
      evidence_ids: [
        nodeEvidenceId,
        mainEvidenceId,
        ...detailLabelIds.map((id) => `ev-${id}`),
      ],
      confidence: confidence(1, null),
    };
  });
  const diagramConnectors = edges.map((spec, index) => {
    const labelId = spec.label === undefined ? null : `edge-label-${spec.id}`;
    const labelEvidenceId = `ev-edge-label-${spec.id}`;
    if (labelId !== null) {
      labels.push({
        id: labelId,
        text: spec.label,
        role: "connector",
        page_bbox: bbox(270, 30 + index * 15, 100, 8),
        raster_pixel_bbox: null,
        evidence_ids: [labelEvidenceId],
        occurrence_index: occurrenceIndex++,
      });
      evidence.push({
        id: labelEvidenceId,
        kind: "label",
        page_bbox: bbox(270, 30 + index * 15, 100, 8),
        chart_local_bbox: null,
        raster_pixel_bbox: null,
        transform_ids: [],
        provenance: {
          public_item_id: ownerId,
          page_index: 1,
          input_kind: "pdf",
          source_object_ids: [`source-${labelEvidenceId}`],
          source_token_ids: [],
          extraction_method: "explicit_text",
        },
      });
    }
    const connectorEvidence = [
      [`ev-path-${spec.id}`, "path"],
      [`ev-source-${spec.id}`, "point"],
      [`ev-target-${spec.id}`, "point"],
      [`ev-direction-${spec.id}`, "connector"],
    ] as const;
    for (const [id, kind] of connectorEvidence) {
      evidence.push({
        id,
        kind,
        page_bbox: bbox(200, 30 + index * 15, 40, 4),
        chart_local_bbox: null,
        raster_pixel_bbox: null,
        transform_ids: [],
        provenance: {
          public_item_id: ownerId,
          page_index: 1,
          input_kind: "pdf",
          source_object_ids: [`source-${id}`],
          source_token_ids: [],
          extraction_method: "vector",
        },
      });
    }
    return {
      id: spec.id,
      source_node_id: spec.source,
      target_node_id: spec.target,
      directed: true,
      label_id: labelId,
      path_evidence_id: `ev-path-${spec.id}`,
      endpoint_evidence_ids: [
        `ev-source-${spec.id}`,
        `ev-target-${spec.id}`,
      ],
      direction_evidence_id: `ev-direction-${spec.id}`,
      evidence_ids: [
        `ev-path-${spec.id}`,
        `ev-source-${spec.id}`,
        `ev-target-${spec.id}`,
        `ev-direction-${spec.id}`,
        ...(labelId === null ? [] : [labelEvidenceId]),
      ],
      confidence: confidence(1, 1),
    };
  });
  const markdown = expectedDiagramMarkdown(nodes, edges);
  const owner: DocumentContentItem = {
    id: ownerId,
    type: "diagram",
    reading_order: 0,
    value: markdown,
    md: markdown,
    bbox: { ...bbox(0, 0, 600, 700), w: 600, h: 700 },
    visual_structure: {
      schema_version: "1.0",
      region: {
        id: "diagram-region",
        kind: "diagram",
        page_bbox: bbox(0, 0, 600, 700),
        evidence_ids: ["ev-region"],
      },
      transforms: [],
      labels,
      axes: [],
      legends: [],
      panels: [],
      series: [],
      points: [],
      nodes: diagramNodes,
      connectors: diagramConnectors,
      evidence,
      vector_inventory: null,
      confidence: confidence(1, 1),
      concerns: [],
      fallback: {
        active: false,
        reason: "none",
        predecessor_concern: "diagram_relationships_not_structured",
      },
      serialization: {
        status: "diagram_topology",
        markdown,
        caption_occurrences: 0,
        row_count: edges.length,
      },
    } as unknown as NonNullable<DocumentContentItem["visual_structure"]>,
  };
  const block: CanonicalBlock = {
    id: "canonical-diagram",
    page_id: "canonical-page-1",
    primary_element_id: "diagram-element",
    primary_element_type: "diagram",
    scope: "body",
    markdown,
    text: markdown,
    contributing_element_ids: ["diagram-element"],
    relationship_ids: [],
    excluded_contributions: [],
  };
  const page = samplePage({ items: [owner] });
  return { block, owner, page };
}

function readFixture(nodes: NodeSpec[], edges: EdgeSpec[]) {
  const fixture = graphFixture(nodes, edges);
  const semantics = readDiagramSemanticsForCanonicalBlock(
    fixture.block,
    fixture.page,
  );
  assert.ok(semantics);
  return { ...fixture, semantics };
}

function mutableStructure(owner: DocumentContentItem): JsonRecord {
  return owner.visual_structure as unknown as JsonRecord;
}

function addRasterRegionGrounding(
  fixture: ReturnType<typeof graphFixture>,
): { evidenceId: string; transformId: string } {
  const structure = mutableStructure(fixture.owner);
  const region = structure.region as JsonRecord;
  const transformId = "raster-to-page";
  const evidenceId = "ev-raster-source-object";
  (structure.transforms as JsonRecord[]).push({
    id: transformId,
    source_space: "raster_pixel",
    target_space: "page",
    matrix: [0.5, 0, 0, 0.5, 0, 0],
    source_transform_ids: [],
  });
  (structure.evidence as JsonRecord[]).push({
    id: evidenceId,
    kind: "source_object",
    page_bbox: structuredClone(region.page_bbox),
    chart_local_bbox: null,
    raster_pixel_bbox: rasterBbox(0, 0, 1_200, 1_400),
    transform_ids: [transformId],
    provenance: {
      public_item_id: fixture.owner.id,
      page_index: fixture.page.page_index,
      input_kind: "pdf",
      source_object_ids: ["p1-image1"],
      source_token_ids: [],
      extraction_method: "raster",
    },
  });
  region.evidence_ids = [
    ...(region.evidence_ids as string[]),
    evidenceId,
  ];
  return { evidenceId, transformId };
}

function recordWithId(
  values: JsonRecord[],
  id: string,
): JsonRecord {
  const value = values.find((entry) => entry.id === id);
  assert.ok(value);
  return value;
}

function addRasterDetailGrounding(
  fixture: ReturnType<typeof graphFixture>,
  detailIndex = 0,
): { detailId: string; evidenceId: string; nodeId: string } {
  const structure = mutableStructure(fixture.owner);
  const nodes = structure.nodes as JsonRecord[];
  const node = nodes.find(
    (entry) =>
      Array.isArray(entry.detail_label_ids) &&
      (entry.detail_label_ids as string[]).length > detailIndex,
  );
  assert.ok(node);
  const detailId = (node.detail_label_ids as string[])[detailIndex]!;
  const label = recordWithId(structure.labels as JsonRecord[], detailId);
  const evidenceId = `ev-raster-detail-${detailIndex}`;
  const labelBox = label.page_bbox as ReturnType<typeof bbox>;
  const pageBox = bbox(
    (node.page_bbox as ReturnType<typeof bbox>).x + 2,
    labelBox.y,
    3,
    3,
  );
  (structure.evidence as JsonRecord[]).push({
    id: evidenceId,
    kind: "source_object",
    page_bbox: pageBox,
    chart_local_bbox: null,
    raster_pixel_bbox: rasterBbox(
      pageBox.x * 2,
      pageBox.y * 2,
      pageBox.width * 2,
      pageBox.height * 2,
    ),
    transform_ids: ["raster-to-page"],
    provenance: {
      public_item_id: fixture.owner.id,
      page_index: fixture.page.page_index,
      input_kind: "pdf",
      source_object_ids: [`raster-bullet-${detailIndex}`],
      source_token_ids: [`ocr-token-bullet-${detailIndex}`],
      extraction_method: "raster",
    },
  });
  label.evidence_ids = [...(label.evidence_ids as string[]), evidenceId];
  node.evidence_ids = [...(node.evidence_ids as string[]), evidenceId];
  return { detailId, evidenceId, nodeId: node.id as string };
}

function addOwnerCaption(
  fixture: ReturnType<typeof graphFixture>,
  caption: string,
): void {
  const structure = mutableStructure(fixture.owner);
  const serialization = structure.serialization as JsonRecord;
  const graphMarkdown = serialization.markdown as string;
  const markdown = `${escapeDiagramMarkdown(pythonStripFixture(caption))}\n\n${graphMarkdown}`;
  fixture.owner.caption = caption;
  fixture.owner.value = markdown;
  fixture.owner.md = markdown;
  fixture.block.text = markdown;
  fixture.block.markdown = markdown;
  serialization.markdown = markdown;
  serialization.caption_occurrences = 1;
}

function setCoordinateUnit(value: unknown, unit: "pt" | "px"): void {
  if (Array.isArray(value)) {
    value.forEach((entry) => setCoordinateUnit(entry, unit));
    return;
  }
  if (value === null || typeof value !== "object") return;
  const record = value as JsonRecord;
  if (
    Object.prototype.hasOwnProperty.call(record, "unit") &&
    (record.unit === "pt" || record.unit === "px")
  ) {
    record.unit = unit;
  }
  Object.values(record).forEach((entry) => setCoordinateUnit(entry, unit));
}

function stripNullFields(value: unknown): void {
  if (Array.isArray(value)) {
    value.forEach(stripNullFields);
    return;
  }
  if (value === null || typeof value !== "object") return;
  const record = value as JsonRecord;
  for (const [key, entry] of Object.entries(record)) {
    if (entry === null) {
      delete record[key];
    } else {
      stripNullFields(entry);
    }
  }
}

test("vertical and horizontal linear graphs project the same directed hierarchy", () => {
  const edges = [
    { id: "ab", source: "a", target: "b" },
    { id: "bc", source: "b", target: "c" },
  ];
  const vertical = readFixture(
    [
      { id: "a", text: "A", x: 20, y: 20 },
      { id: "b", text: "B", x: 20, y: 100 },
      { id: "c", text: "C", x: 20, y: 180 },
    ],
    edges,
  );
  const horizontal = readFixture(
    [
      { id: "a", text: "A", x: 20, y: 20 },
      { id: "b", text: "B", x: 220, y: 20 },
      { id: "c", text: "C", x: 420, y: 20 },
    ],
    edges,
  );
  const summarize = (entry: (typeof vertical.semantics.forest)[number]): unknown => ({
    node: entry.node.id,
    children: entry.children.map((child) =>
      child.kind === "reference"
        ? { reference: child.target.id, kind: child.referenceKind }
        : summarize(child),
    ),
  });
  assert.deepEqual(
    vertical.semantics.forest.map(summarize),
    horizontal.semantics.forest.map(summarize),
  );
  assert.deepEqual(vertical.semantics.forest.map(summarize), [
    { node: "a", children: [{ node: "b", children: [{ node: "c", children: [] }] }] },
  ]);
});

test("branches nest, merges reference the first occurrence, and rooted loops reference an ancestor", () => {
  const merged = readFixture(
    [
      { id: "a", text: "Start" },
      { id: "b", text: "Left" },
      { id: "c", text: "Right" },
      { id: "d", text: "Merged" },
    ],
    [
      { id: "ab", source: "a", target: "b" },
      { id: "ac", source: "a", target: "c" },
      { id: "bd", source: "b", target: "d" },
      { id: "cd", source: "c", target: "d", label: "again" },
    ],
  );
  const root = merged.semantics.forest[0];
  assert.equal(root?.node.id, "a");
  assert.deepEqual(root?.children.map((entry) => entry.kind), ["node", "node"]);
  const right = root?.children[1];
  assert.equal(right?.kind, "node");
  if (right?.kind === "node") {
    assert.deepEqual(
      right.children.map((entry) =>
        entry.kind === "reference"
          ? [entry.target.id, entry.referenceKind]
          : [entry.node.id, "node"],
      ),
      [["d", "merge"]],
    );
  }
  const mergedMarkup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(merged.semantics),
  );
  assert.match(mergedMarkup, /data-diagram-reference="merge"/u);
  assert.match(mergedMarkup, />again: <\/span>/u);
  assert.match(mergedMarkup, /Continues at: <\/span>/u);

  const cycle = readFixture(
    [
      { id: "root", text: "Root" },
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [
      { id: "ra", source: "root", target: "a" },
      { id: "ab", source: "a", target: "b" },
      { id: "ba", source: "b", target: "a", label: "retry" },
    ],
  );
  const a = cycle.semantics.forest[0]?.children[0];
  assert.equal(a?.kind, "node");
  if (a?.kind === "node") {
    const b = a.children[0];
    assert.equal(b?.kind, "node");
    if (b?.kind === "node") {
      const reference = b.children[0];
      assert.equal(reference?.kind, "reference");
      if (reference?.kind === "reference") {
        assert.equal(reference.referenceKind, "loop");
        assert.equal(reference.target.id, "a");
      }
    }
  }
  const cycleMarkup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(cycle.semantics),
  );
  assert.match(cycleMarkup, /data-diagram-reference="loop"/u);
  assert.match(cycleMarkup, />retry: <\/span>/u);
  assert.match(cycleMarkup, /Returns to: <\/span>/u);
});

test("duplicate node text is allowed until a merge or loop must name that target", () => {
  const ordinary = graphFixture(
    [
      { id: "root", text: "Root" },
      { id: "left", text: "Repeated" },
      { id: "right", text: "Repeated" },
    ],
    [
      { id: "root-left", source: "root", target: "left" },
      { id: "root-right", source: "root", target: "right" },
    ],
  );
  assert.ok(
    readDiagramSemanticsForCanonicalBlock(ordinary.block, ordinary.page),
  );

  const merge = graphFixture(
    [
      { id: "root", text: "Root" },
      { id: "left", text: "Left" },
      { id: "right", text: "Right" },
      { id: "target", text: "Repeated" },
      { id: "other", text: "Repeated" },
    ],
    [
      { id: "root-left", source: "root", target: "left" },
      { id: "root-right", source: "root", target: "right" },
      { id: "left-target", source: "left", target: "target" },
      { id: "right-target", source: "right", target: "target" },
    ],
  );
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(merge.block, merge.page),
    null,
  );

  const loop = graphFixture(
    [
      { id: "root", text: "Root" },
      { id: "a", text: "Repeated" },
      { id: "b", text: "B" },
      { id: "other", text: "Repeated" },
    ],
    [
      { id: "root-a", source: "root", target: "a" },
      { id: "a-b", source: "a", target: "b" },
      { id: "b-a", source: "b", target: "a" },
    ],
  );
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(loop.block, loop.page),
    null,
  );

  const escapedCollision = graphFixture(
    [
      { id: "root", text: "Root" },
      { id: "left", text: "Left" },
      { id: "right", text: "Right" },
      { id: "target", text: "Repeated\nlabel" },
      { id: "other", text: "Repeated<br>label" },
    ],
    [
      { id: "root-left", source: "root", target: "left" },
      { id: "root-right", source: "root", target: "right" },
      { id: "left-target", source: "left", target: "target" },
      { id: "right-target", source: "right", target: "target" },
    ],
  );
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(
      escapedCollision.block,
      escapedCollision.page,
    ),
    null,
  );
});

test("roots and outgoing siblings use grounded geometry before input order", () => {
  const fixture = readFixture(
    [
      { id: "right-root", text: "Right root", x: 300, y: 20 },
      { id: "later", text: "Later child", x: 20, y: 200 },
      { id: "left-root", text: "Left root", x: 20, y: 20 },
      { id: "earlier", text: "Earlier child", x: 300, y: 100 },
    ],
    [
      { id: "to-later", source: "left-root", target: "later" },
      { id: "to-earlier", source: "left-root", target: "earlier" },
    ],
  );
  assert.deepEqual(
    fixture.semantics.forest.map((entry) => entry.node.id),
    ["left-root", "right-root"],
  );
  assert.deepEqual(
    fixture.semantics.forest[0]?.children.map((entry) =>
      entry.kind === "node" ? entry.node.id : entry.target.id,
    ),
    ["earlier", "later"],
  );
});

test("disconnected starts remain peers and Clinical-like node details stay grouped", () => {
  const disconnected = readFixture(
    [
      { id: "a", text: "First start" },
      { id: "b", text: "First end" },
      { id: "x", text: "Second start" },
      { id: "y", text: "Second end" },
    ],
    [
      { id: "ab", source: "a", target: "b" },
      { id: "xy", source: "x", target: "y" },
    ],
  );
  assert.deepEqual(
    disconnected.semantics.forest.map((entry) => entry.node.id),
    ["a", "x"],
  );

  const clinical = readFixture(
    [
      { id: "assessed", text: "Assessed for eligibility (n = 826)" },
      {
        id: "excluded",
        text: "Excluded (n = 230)",
        details: [
          "Acute suicidality (n = 83)",
          "Low symptoms (n = 73)",
          "Age < 18 (n = 73)",
          "Duplicate account (n = 1)",
        ],
      },
      { id: "included", text: "Included (n = 596)" },
      { id: "baseline", text: "baseline non-completion (n = 58)" },
      { id: "randomized", text: "Randomized (n = 538)" },
      { id: "sbs", text: "Allocated to SbS + CAU (n = 266)" },
      { id: "cau", text: "Allocated to CAU (n = 272)" },
    ],
    [
      { id: "ae", source: "assessed", target: "excluded" },
      { id: "ai", source: "assessed", target: "included" },
      { id: "ib", source: "included", target: "baseline" },
      { id: "ir", source: "included", target: "randomized" },
      { id: "rs", source: "randomized", target: "sbs" },
      { id: "rc", source: "randomized", target: "cau" },
    ],
  );
  const excluded = clinical.semantics.nodes.find((node) => node.id === "excluded");
  assert.deepEqual(
    excluded?.details.map((detail) => detail.text),
    [
      "Acute suicidality (n = 83)",
      "Low symptoms (n = 73)",
      "Age < 18 (n = 73)",
      "Duplicate account (n = 1)",
    ],
  );
  const markup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(clinical.semantics),
  );
  assert.match(markup, /class="diagram-node-details"/u);
  assert.match(markup, /baseline non-completion \(n = 58\)/u);
  assert.equal((markup.match(/class="diagram-branch-list"/gu) ?? []).length >= 3, true);
});

test("connector labels and hostile Markdown/HTML remain escaped inert text", () => {
  const hostile = readFixture(
    [
      {
        id: "a",
        text: "<script>alert(1)</script> **not bold**",
        details: ["[not a link](javascript:alert(2)) | literal"],
      },
      { id: "b", text: "AT&T" },
    ],
    [
      {
        id: "ab",
        source: "a",
        target: "b",
        label: "<img src=x onerror=alert(3)> **Yes**",
      },
    ],
  );
  const markup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(hostile.semantics),
  );
  assert.doesNotMatch(markup, /<(?:script|img|a)\b|onerror="/u);
  assert.match(markup, /&lt;script&gt;alert\(1\)&lt;\/script&gt; \*\*not bold\*\*/u);
  assert.match(markup, /\[not a link\]\(javascript:alert\(2\)\) \| literal/u);
  assert.match(markup, /&lt;img src=x onerror=alert\(3\)&gt; \*\*Yes\*\*/u);
  assert.match(markup, /AT&amp;T/u);
});

test("point and pixel pages require exact owner-region coordinate custody", () => {
  const pointFixture = graphFixture(
    [
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [{ id: "ab", source: "a", target: "b" }],
  );
  assert.ok(
    readDiagramSemanticsForCanonicalBlock(
      pointFixture.block,
      pointFixture.page,
    ),
  );

  const pixelFixture = structuredClone(pointFixture);
  pixelFixture.page.unit = "px";
  setCoordinateUnit(pixelFixture.owner, "px");
  assert.ok(
    readDiagramSemanticsForCanonicalBlock(
      pixelFixture.block,
      pixelFixture.page,
    ),
  );

  const unitMismatch = structuredClone(pointFixture);
  unitMismatch.page.unit = "px";
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(
      unitMismatch.block,
      unitMismatch.page,
    ),
    null,
  );

  const bboxMismatch = structuredClone(pointFixture);
  bboxMismatch.owner.bbox!.width = 599;
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(
      bboxMismatch.block,
      bboxMismatch.page,
    ),
    null,
  );

  const aliasMismatch = structuredClone(pointFixture);
  aliasMismatch.owner.bbox!.w = 599;
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(
      aliasMismatch.block,
      aliasMismatch.page,
    ),
    null,
  );
});

test("the decoder accepts the backend exclude-none public projection", () => {
  const fixture = graphFixture(
    [
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [{ id: "ab", source: "a", target: "b" }],
  );
  stripNullFields(fixture.owner.visual_structure);
  assert.ok(
    readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
  );
});

test("an exact owner caption renders once before the semantic list", () => {
  const fixture = graphFixture(
    [
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [{ id: "ab", source: "a", target: "b" }],
  );
  addOwnerCaption(fixture, "Approval | flow");
  const semantics = readDiagramSemanticsForCanonicalBlock(
    fixture.block,
    fixture.page,
  );
  assert.ok(semantics);
  const markup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(semantics),
  );
  assert.equal((markup.match(/Approval \| flow/gu) ?? []).length, 1);
  assert.equal((markup.match(/diagram-owner-caption/gu) ?? []).length, 1);
  assert.equal(
    markup.indexOf("diagram-owner-caption") < markup.indexOf("diagram-root-list"),
    true,
  );
  assert.match(markup, /data-caption-of="diagram-owner"/u);

  const badCount = structuredClone(fixture);
  const serialization = mutableStructure(badCount.owner)
    .serialization as JsonRecord;
  serialization.caption_occurrences = 0;
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(badCount.block, badCount.page),
    null,
  );
});

test("a layout-externalized caption keeps a raster diagram on the semantic-list path", () => {
  const fixture = graphFixture(
    [
      { id: "eligibility", text: "Assessed for eligibility (n = 826)" },
      { id: "included", text: "Included (n = 596)" },
    ],
    [{ id: "eligibility-included", source: "eligibility", target: "included" }],
  );
  const structure = mutableStructure(fixture.owner);
  addRasterRegionGrounding(fixture);

  const captionId = "layout-caption-flowchart";
  const relationshipId = "layout-rel-caption-flowchart";
  const caption = {
    id: captionId,
    type: "caption",
    reading_order: 1,
    value: "Fig 1. Flowchart.",
    md: "Fig 1. Flowchart.",
    caption_of: fixture.owner.id,
    relationship_id: relationshipId,
    relationship_type: "caption_of",
  } satisfies DocumentContentItem;
  fixture.owner.caption_ids = [captionId];
  fixture.owner.caption_of = [captionId];
  fixture.owner.relationships = [
    {
      id: relationshipId,
      type: "caption_of",
      source_id: captionId,
      target_id: fixture.owner.id,
    },
  ];
  fixture.page.items.push(caption);

  const serialization = structure.serialization as JsonRecord;
  assert.equal(fixture.owner.caption, undefined);
  assert.equal(serialization.caption_occurrences, 0);
  assert.equal(serialization.markdown, fixture.block.markdown);
  assert.doesNotMatch(fixture.block.markdown, /Fig 1\. Flowchart\./u);

  const semantics = readDiagramSemanticsForCanonicalBlock(
    fixture.block,
    fixture.page,
  );
  assert.ok(semantics);
  const markup = renderToStaticMarkup(
    renderValidatedDiagramSemantics(semantics),
  );
  assert.match(markup, /data-diagram-rendering="semantic-list"/u);
  assert.doesNotMatch(markup, /diagram-owner-caption|Fig 1\. Flowchart\./u);
});

test("raster region evidence remains supplemental, exact, and fully grounded", () => {
  const fixtureWithRasterRegion = () => {
    const fixture = graphFixture(
      [
        { id: "a", text: "A" },
        { id: "b", text: "B" },
      ],
      [{ id: "ab", source: "a", target: "b" }],
    );
    const ids = addRasterRegionGrounding(fixture);
    return { ...fixture, ...ids };
  };

  assert.ok((() => {
    const fixture = fixtureWithRasterRegion();
    return readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page);
  })());

  const mutations: Array<(
    structure: JsonRecord,
    rasterEvidence: JsonRecord,
    transform: JsonRecord,
    evidenceId: string,
  ) => void> = [
    (structure, _rasterEvidence, _transform, evidenceId) => {
      (structure.region as JsonRecord).evidence_ids = [evidenceId];
    },
    (_structure, rasterEvidence) => {
      (rasterEvidence.page_bbox as JsonRecord).x = 1;
    },
    (_structure, rasterEvidence) => {
      (rasterEvidence.provenance as JsonRecord).extraction_method = "vector";
    },
    (_structure, rasterEvidence) => {
      rasterEvidence.raster_pixel_bbox = null;
    },
    (_structure, rasterEvidence) => {
      (rasterEvidence.provenance as JsonRecord).source_object_ids = [];
    },
    (_structure, rasterEvidence) => {
      rasterEvidence.kind = "label";
    },
    (_structure, rasterEvidence) => {
      rasterEvidence.transform_ids = [];
    },
    (_structure, _rasterEvidence, transform) => {
      transform.source_space = "chart_local";
    },
    (_structure, _rasterEvidence, transform) => {
      transform.matrix = [0.25, 0, 0, 0.5, 0, 0];
    },
  ];

  for (const mutate of mutations) {
    const fixture = fixtureWithRasterRegion();
    const structure = mutableStructure(fixture.owner);
    const rasterEvidence = recordWithId(
      structure.evidence as JsonRecord[],
      fixture.evidenceId,
    );
    const transform = recordWithId(
      structure.transforms as JsonRecord[],
      fixture.transformId,
    );
    mutate(structure, rasterEvidence, transform, fixture.evidenceId);
    assert.equal(
      readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
    );
  }
});

test("raster detail source objects supplement one grounded label in one owning node", () => {
  const fixtureWithRasterDetail = () => {
    const fixture = graphFixture(
      [
        { id: "a", text: "A", details: ["first detail", "second detail"] },
        { id: "b", text: "B" },
      ],
      [{ id: "ab", source: "a", target: "b" }],
    );
    addRasterRegionGrounding(fixture);
    const ids = addRasterDetailGrounding(fixture);
    return { ...fixture, ...ids };
  };

  assert.ok((() => {
    const fixture = fixtureWithRasterDetail();
    return readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page);
  })());

  const mutations: Array<(
    fixture: ReturnType<typeof fixtureWithRasterDetail>,
    structure: JsonRecord,
    detail: JsonRecord,
    rasterEvidence: JsonRecord,
    ownerNode: JsonRecord,
  ) => void> = [
    (fixture, _structure, detail) => {
      detail.evidence_ids = [fixture.evidenceId];
    },
    (_fixture, _structure, _detail, rasterEvidence) => {
      rasterEvidence.page_bbox = bbox(300, 300, 3, 3);
      rasterEvidence.raster_pixel_bbox = rasterBbox(600, 600, 6, 6);
    },
    (fixture, _structure, _detail, _rasterEvidence, ownerNode) => {
      ownerNode.evidence_ids = (ownerNode.evidence_ids as string[]).filter(
        (id) => id !== fixture.evidenceId,
      );
    },
    (fixture, structure) => {
      const secondDetailId = (
        recordWithId(structure.nodes as JsonRecord[], fixture.nodeId)
          .detail_label_ids as string[]
      )[1]!;
      const secondDetail = recordWithId(
        structure.labels as JsonRecord[],
        secondDetailId,
      );
      secondDetail.evidence_ids = [
        ...(secondDetail.evidence_ids as string[]),
        fixture.evidenceId,
      ];
    },
    (fixture, structure) => {
      const otherNode = (structure.nodes as JsonRecord[]).find(
        (node) => node.id !== fixture.nodeId,
      );
      assert.ok(otherNode);
      otherNode.evidence_ids = [
        ...(otherNode.evidence_ids as string[]),
        fixture.evidenceId,
      ];
    },
    (_fixture, _structure, _detail, rasterEvidence) => {
      (rasterEvidence.provenance as JsonRecord).public_item_id = "wrong-owner";
    },
    (_fixture, _structure, _detail, rasterEvidence) => {
      (rasterEvidence.provenance as JsonRecord).page_index = 2;
    },
  ];

  for (const mutate of mutations) {
    const fixture = fixtureWithRasterDetail();
    const structure = mutableStructure(fixture.owner);
    const detail = recordWithId(
      structure.labels as JsonRecord[],
      fixture.detailId,
    );
    const rasterEvidence = recordWithId(
      structure.evidence as JsonRecord[],
      fixture.evidenceId,
    );
    const ownerNode = recordWithId(
      structure.nodes as JsonRecord[],
      fixture.nodeId,
    );
    mutate(fixture, structure, detail, rasterEvidence, ownerNode);
    assert.equal(
      readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
    );
  }
});

test("labels admit 1024 Unicode codepoints but reject overflow and bidi controls", () => {
  for (const label of ["é".repeat(1_024), "😀".repeat(1_024)]) {
    const fixture = graphFixture(
      [
        { id: "a", text: label },
        { id: "b", text: "B" },
      ],
      [{ id: "ab", source: "a", target: "b" }],
    );
    assert.ok(
      readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
    );
  }

  for (const label of ["a".repeat(1_025), "safe\u202eevil", "safe\u2066evil"]) {
    const fixture = graphFixture(
      [
        { id: "a", text: label },
        { id: "b", text: "B" },
      ],
      [{ id: "ab", source: "a", target: "b" }],
    );
    assert.equal(
      readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
    );
  }
});

test("authoritative diagrams allow unrelated concerns but reject the stale relationship fallback concern", () => {
  const unrelated = graphFixture(
    [
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [{ id: "ab", source: "a", target: "b" }],
  );
  unrelated.owner.parse_concerns = ["unrelated_concern"];
  assert.ok(
    readDiagramSemanticsForCanonicalBlock(unrelated.block, unrelated.page),
  );

  const stale = graphFixture(
    [
      { id: "a", text: "A" },
      { id: "b", text: "B" },
    ],
    [{ id: "ab", source: "a", target: "b" }],
  );
  stale.owner.parse_concerns = [
    "unrelated_concern",
    "diagram_relationships_not_structured",
  ];
  assert.equal(
    readDiagramSemanticsForCanonicalBlock(stale.block, stale.page),
    null,
  );
});

test("canonical and owner mismatches, fallback, malformed graphs, and tampering fail closed", () => {
  const mutations: Array<(
    block: CanonicalBlock,
    owner: DocumentContentItem,
    page: PageResult,
  ) => void> = [
    (block) => { block.text += " tampered"; },
    (block) => { block.markdown += " tampered"; },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      (structure.fallback as JsonRecord).active = true;
      (structure.fallback as JsonRecord).reason = "unresolved";
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      (structure.serialization as JsonRecord).status = "fallback";
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      (structure.serialization as JsonRecord).row_count = 99;
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const connectors = structure.connectors as JsonRecord[];
      connectors[0]!.target_node_id = "unknown";
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const nodes = structure.nodes as JsonRecord[];
      nodes[1]!.id = nodes[0]!.id;
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const labels = structure.labels as JsonRecord[];
      const detail = labels.find((label) => label.role === "node_detail");
      assert.ok(detail);
      detail.role = "node";
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const labels = structure.labels as JsonRecord[];
      const connector = labels.find((label) => label.role === "connector");
      assert.ok(connector);
      connector.role = "node";
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const evidence = structure.evidence as JsonRecord[];
      const provenance = evidence[0]!.provenance as JsonRecord;
      provenance.public_item_id = "different-owner";
    },
    (block, owner) => {
      const structure = mutableStructure(owner);
      const serialization = structure.serialization as JsonRecord;
      serialization.markdown = "forged but consistently resealed";
      owner.value = serialization.markdown;
      owner.md = serialization.markdown as string;
      block.text = serialization.markdown as string;
      block.markdown = serialization.markdown as string;
    },
    (_block, owner) => {
      const structure = mutableStructure(owner);
      const nodes = structure.nodes as JsonRecord[];
      const connectors = structure.connectors as JsonRecord[];
      nodes.push({
        ...structuredClone(nodes[0]),
        id: "cycle-only-a",
        label_id: null,
        detail_label_ids: [],
      });
      nodes.push({
        ...structuredClone(nodes[0]),
        id: "cycle-only-b",
        label_id: null,
        detail_label_ids: [],
      });
      connectors.push({
        ...structuredClone(connectors[0]),
        id: "cycle-only-ab",
        source_node_id: "cycle-only-a",
        target_node_id: "cycle-only-b",
        label_id: null,
      });
      connectors.push({
        ...structuredClone(connectors[0]),
        id: "cycle-only-ba",
        source_node_id: "cycle-only-b",
        target_node_id: "cycle-only-a",
        label_id: null,
      });
      (structure.serialization as JsonRecord).row_count = connectors.length;
    },
    (_block, owner, page) => {
      page.items.push(structuredClone(owner));
    },
  ];
  for (const mutate of mutations) {
    const fixture = graphFixture(
      [
        { id: "a", text: "A", details: ["detail"] },
        { id: "b", text: "B" },
      ],
      [{ id: "ab", source: "a", target: "b", label: "yes" }],
    );
    mutate(fixture.block, fixture.owner, fixture.page);
    assert.equal(
      readDiagramSemanticsForCanonicalBlock(fixture.block, fixture.page),
      null,
    );
  }
});

test("workspace uses only the strict canonical diagram resolver and keeps paragraph fallback", () => {
  const source = readFileSync(
    new URL("../app/clearleaf-workspace.tsx", import.meta.url),
    "utf8",
  );
  const canonicalStart = source.indexOf("function CanonicalRenderedPage");
  const canonicalEnd = source.indexOf("function MarkdownSource", canonicalStart);
  const renderer = source.slice(canonicalStart, canonicalEnd);
  assert.match(
    source,
    /import \{[\s\S]*readDiagramSemanticsForCanonicalBlock,[\s\S]*renderValidatedDiagramSemantics[\s\S]*\} from "@\/lib\/diagram-semantics";/u,
  );
  assert.match(
    renderer,
    /readDiagramSemanticsForCanonicalBlock\(\s*block,\s*sourcePage,?\s*\)/u,
  );
  assert.match(renderer, /renderValidatedDiagramSemantics\(diagramSemantics\)/u);
  assert.match(renderer, /const canonicalFallback =/u);
  assert.doesNotMatch(renderer, /mermaid|dangerouslySetInnerHTML/u);
});
