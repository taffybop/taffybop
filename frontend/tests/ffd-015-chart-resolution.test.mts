import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { renderToStaticMarkup } from "react-dom/server";

import {
  readChartImageResolution,
  readChartResolution,
  readChartResolutionForCanonicalBlock,
  renderValidatedChartResolution,
  replayChartResolutionMarkdown,
  replayChartSourceAssetId,
  validateChartResolution,
} from "../lib/chart-resolution.ts";
import { resolveChartCaptionLink } from "../lib/layout-relationships.ts";
import { pageHasContent } from "../lib/page-content.ts";
import type {
  CanonicalBlock,
  CanonicalPage,
  ChartResolution,
  DocumentContentItem,
  PageResult,
} from "../lib/types.ts";

const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR42mP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC";
const PNG_BYTES = Buffer.from(PNG_BASE64, "base64");
const SOURCE_SHA256 = "a".repeat(64);
const NORMALIZED_SOURCE_SHA256 = "c".repeat(64);
const CONFIGURATION_SHA256 = "b".repeat(64);
const BOX = { x: 10, y: 20, width: 1, height: 1, unit: "pt" as const };

const digest = (value: string | Uint8Array): string =>
  createHash("sha256").update(value).digest("hex");

const confidence = (value: number) => ({
  value,
  unavailable_reason: null,
});
const unavailableConfidence = (reason: "asset_unavailable") => ({
  value: null,
  unavailable_reason: reason,
});
const sourceConfidenceUnavailable = () => ({
  value: null,
  unavailable_reason: "source_confidence_unavailable" as const,
});

function transcriptEvidence(
  ownerId: string,
  id: string,
  extractionMethod: "layout" | "ocr" | "explicit_text",
  sourceTokenIds: string[] = [],
) {
  return {
    id,
    kind: "label",
    page_bbox: BOX,
    chart_local_bbox: null,
    raster_pixel_bbox: null,
    transform_ids: [],
    provenance: {
      public_item_id: ownerId,
      page_index: 1,
      input_kind: "pdf",
      source_object_ids: [],
      source_token_ids: sourceTokenIds,
      extraction_method: extractionMethod,
    },
  };
}

function unsupportedResolution(ownerId: string): ChartResolution {
  const transcriptText = "2024 12\n2025 15";
  const resolution: ChartResolution = {
    schema_version: "1.0",
    policy_id: "ffd-015-chart-source-asset-v1",
    owner_item_id: ownerId,
    page_index: 1,
    source_order: 4,
    source_bbox: BOX,
    status: "image_primary_unsupported",
    asset_status: "retained",
    asset_unavailable_reason: null,
    asset: {
      asset_id: "chart-asset-pending-custody-replay",
      source_document_sha256: SOURCE_SHA256,
      render_source_sha256: SOURCE_SHA256,
      owner_item_id: ownerId,
      physical_page: 1,
      source_bbox: BOX,
      owner_geometry_proof_kind: "detected_image",
      owner_geometry_evidence_ids: ["detected-image-0"],
      owner_geometry_evidence_sha256: "d".repeat(64),
      rendered_bbox: BOX,
      coordinate_system: "page_top_left",
      pixel_to_page_transform: [1, 0, 0, 1, 10, 20],
      page_device_dimensions: [1, 1],
      crop_device_margins: [0, 0, 0, 0],
      renderer: "pypdfium2",
      renderer_version: "1.0",
      render_policy: "chart-source-inline-png-v1",
      source_kind: "pdf",
      render_scale: 1,
      effective_dpi: 72,
      width: 1,
      height: 1,
      mime_type: "image/png",
      encoding: "data_uri_base64",
      byte_length: PNG_BYTES.length,
      sha256: digest(PNG_BYTES),
      data_uri: `data:image/png;base64,${PNG_BASE64}`,
      color_space: "srgb",
      alpha_policy: "flatten_white",
      antialiasing_policy: "renderer_default",
      interpolation_policy: "none",
      bbox_rounding: "outward_device_pixels",
      padding: 0,
    },
    family_classification: {
      status: "classified",
      family: "bar",
      classifier_version: "chart-family-source-evidence-v1",
      reason_codes: ["declared_classifier_family"],
      evidence_ids: ["family-evidence"],
      confidence: confidence(0.9),
    },
    complexity_classification: {
      status: "regular",
      classifier_version: "chart-complexity-source-evidence-v1",
      reason_codes: ["single_supported_family"],
      evidence_ids: ["complexity-evidence"],
      confidence: confidence(0.85),
    },
    semantic_analysis: {
      capability_matrix_version: "chart-semantic-capabilities-v1",
      attempt_status: "not_run_no_approved_analyzer",
      analyzer_ids: [],
      configuration_sha256: CONFIGURATION_SHA256,
      completeness_gate_status: "not_run",
      required_features: [],
      observed_features: [],
      missing_features: [],
      ambiguous_evidence_ids: [],
      failure_reason: "unsupported",
    },
    primary_representation: "source_image",
    primary_reason: "semantic_family_not_supported",
    transcript: {
      status: "available",
      source: "source_labels",
      text: transcriptText,
      text_sha256: digest(transcriptText),
      evidence_ids: ["transcript-evidence-0", "transcript-evidence-1"],
      confidence: sourceConfidenceUnavailable(),
    },
    confidence_dimensions: {
      ownership: confidence(0.95),
      transcription: sourceConfidenceUnavailable(),
      family: confidence(0.9),
      complexity: confidence(0.85),
    },
    concern_codes: ["chart_semantics_unsupported"],
  };
  resolution.asset!.asset_id = replayChartSourceAssetId(resolution.asset!);
  return resolution;
}

function chartItem(ownerId = "chart-owner"): DocumentContentItem {
  return {
    id: ownerId,
    type: "chart",
    // Final relationship ordering may move this independently of source_order.
    reading_order: 99,
    bbox: BOX,
    caption: "Revenue [source]\n2025",
    value: "Grounded predecessor",
    visual_structure: {
      schema_version: "1.0",
      region: {
        id: `region-${ownerId}`,
        kind: "chart",
        page_bbox: BOX,
        evidence_ids: ["region-evidence"],
      },
      transforms: [],
      labels: [
        {
          id: `transcript-label-${ownerId}-0`,
          text: "2024 12",
          role: "other",
          evidence_ids: ["transcript-evidence-0"],
          occurrence_index: 0,
        },
        {
          id: `transcript-label-${ownerId}-1`,
          text: "2025 15",
          role: "other",
          evidence_ids: ["transcript-evidence-1"],
          occurrence_index: 1,
        },
      ],
      axes: [],
      legends: [],
      panels: [],
      series: [],
      points: [],
      nodes: [],
      connectors: [],
      evidence: [
        transcriptEvidence(ownerId, "transcript-evidence-0", "layout"),
        transcriptEvidence(ownerId, "transcript-evidence-1", "layout"),
      ],
      vector_inventory: null,
      confidence: {},
      concerns: [],
      // The terminal sidecar may supersede this older structured state.
      fallback: {
        active: false,
        reason: "structured",
        predecessor_concern: "legacy",
      },
      serialization: {
        status: "structured_chart",
        markdown: "legacy structure",
        caption_occurrences: 0,
        row_count: 1,
      },
    },
    chart_resolution: unsupportedResolution(ownerId),
  };
}

function useNativeTranscript(item: DocumentContentItem): void {
  const text = "2024 12\n2025 15";
  const evidenceIds = ["native-transcript-evidence-0", "native-transcript-evidence-1"];
  const occurrenceIds = ["native-occurrence-0", "native-occurrence-1"];
  item.visual_structure!.labels = [
    {
      id: `native-label-${item.id}-0`,
      text: "2024 12",
      role: "other",
      evidence_ids: [evidenceIds[0]!],
      occurrence_index: 0,
    },
    {
      id: `native-label-${item.id}-1`,
      text: "2025 15",
      role: "other",
      evidence_ids: [evidenceIds[1]!],
      occurrence_index: 1,
    },
  ];
  item.visual_structure!.evidence = evidenceIds.map((id, index) =>
    transcriptEvidence(
      item.id,
      id,
      "explicit_text",
      [occurrenceIds[index]!],
    ),
  );
  item.visual_source_text = text;
  item.visual_source_text_occurrences = occurrenceIds.map((occurrenceId) => ({
    occurrence_id: occurrenceId,
  }));
  item.visual_source_text_lines = [{ text: "2024 12" }, { text: "2025 15" }];
  item.meta = {
    phase05_visual_source_text: {
      method: "pdf_text_layer_inside_visual_bbox",
      text_sha256: digest(text),
      occurrence_count: occurrenceIds.length,
    },
  };
  item.chart_resolution!.transcript = {
    status: "available",
    source: "native",
    text,
    text_sha256: digest(text),
    evidence_ids: evidenceIds,
    confidence: sourceConfidenceUnavailable(),
  };
  item.chart_resolution!.confidence_dimensions.transcription =
    sourceConfidenceUnavailable();
}

function useOcrTranscript(item: DocumentContentItem): void {
  const text = "OCR 2024 12\nOCR 2025 15";
  const evidenceIds = ["ocr-transcript-evidence-0", "ocr-transcript-evidence-1"];
  item.visual_structure!.labels = [
    {
      id: `ocr-label-${item.id}-0`,
      text: "OCR 2024 12",
      role: "other",
      evidence_ids: [evidenceIds[0]!],
      occurrence_index: 0,
    },
    {
      id: `ocr-label-${item.id}-1`,
      text: "OCR 2025 15",
      role: "other",
      evidence_ids: [evidenceIds[1]!],
      occurrence_index: 1,
    },
  ];
  item.visual_structure!.evidence = evidenceIds.map((id) =>
    transcriptEvidence(item.id, id, "ocr", [`token-${id}`]),
  );
  item.ocr_text = text;
  item.confidence = 0.73;
  item.chart_resolution!.transcript = {
    status: "available",
    source: "ocr",
    text,
    text_sha256: digest(text),
    evidence_ids: evidenceIds,
    confidence: confidence(0.73),
  };
  item.chart_resolution!.confidence_dimensions.transcription = confidence(0.73);
}

function pageWith(...items: DocumentContentItem[]): PageResult {
  return {
    page_index: 1,
    page_number: 1,
    page_label: "1",
    page_width: 612,
    page_height: 792,
    unit: "pt",
    success: true,
    items,
    warnings: [],
  };
}

function canonicalFor(
  item: DocumentContentItem,
  primaryElementId = "ir-chart-element",
): { block: CanonicalBlock; page: CanonicalPage } {
  const markdown = replayChartResolutionMarkdown(
    item.chart_resolution!,
    item.caption as string,
  )!;
  const block: CanonicalBlock = {
    id: "chart-block",
    page_id: "canonical-page-1",
    primary_element_id: primaryElementId,
    primary_element_type: "chart",
    scope: "body",
    markdown,
    text: item.chart_resolution!.transcript.text!,
    contributing_element_ids: [primaryElementId],
    relationship_ids: [],
    excluded_contributions: [],
  };
  const view = { block_ids: [block.id], markdown: `${markdown}\n`, text: `${block.text}\n` };
  return {
    block,
    page: {
      page_id: "canonical-page-1",
      page_index: 1,
      page_number: 1,
      page_label: "1",
      blocks: [block],
      full: view,
      body: view,
      header: { block_ids: [], markdown: "", text: "" },
      footer: { block_ids: [], markdown: "", text: "" },
    },
  };
}

function assertSingleAccessibleCaption(
  markup: string,
  expectedCaption: string,
  image = true,
): string {
  const captionId = markup.match(
    /<figcaption id="(chart-caption-[0-9a-f]{24})">/u,
  )?.[1];
  assert.ok(captionId);
  assert.equal(markup.match(/<figcaption\b/gu)?.length, 1);
  assert.equal(markup.split(expectedCaption).length - 1, 1);
  assert.ok(
    markup.includes(
      `<figcaption id="${captionId}">${expectedCaption}</figcaption>`,
    ),
  );
  if (image) {
    assert.match(markup, /<img alt=""/u);
  }
  assert.ok(markup.includes(`aria-labelledby="${captionId}"`));
  return captionId;
}

test("source-image chart validation binds bytes, custody, geometry, and immutable source order", () => {
  const item = chartItem();
  const page = pageWith(item);
  const validated = validateChartResolution(item, page, SOURCE_SHA256);
  assert.equal(validated.resolution.source_order, 4);
  assert.equal(validated.owner.reading_order, 99);
  assert.equal(validated.primaryText, "2024 12\n2025 15");
  assert.ok(
    validated.imageMarkdown!.startsWith(
      "![Revenue \\[source\\] 2025](data:image/png;base64,",
    ),
  );

  const markup = renderToStaticMarkup(renderValidatedChartResolution(validated));
  assert.match(markup, /^<figure class="parsed-chart-image"/u);
  assert.match(markup, /data-chart-resolution="image_primary_unsupported"/u);
  assert.match(markup, /src="data:image\/png;base64,/u);
  assertSingleAccessibleCaption(markup, "Revenue [source]\n2025");
  assert.doesNotMatch(markup, /2024 12/u);
});

test("native, OCR, source-label, and unavailable chart transcripts replay from the owner", () => {
  const sourceLabels = chartItem("source-label-transcript-owner");
  assert.equal(
    validateChartResolution(
      sourceLabels,
      pageWith(sourceLabels),
      SOURCE_SHA256,
    ).resolution.transcript.source,
    "source_labels",
  );

  const native = chartItem("native-transcript-owner");
  useNativeTranscript(native);
  const nativeValidated = validateChartResolution(
    native,
    pageWith(native),
    SOURCE_SHA256,
  );
  assert.equal(nativeValidated.resolution.transcript.source, "native");
  assert.equal(nativeValidated.primaryText, native.visual_source_text);

  const ocr = chartItem("ocr-transcript-owner");
  useOcrTranscript(ocr);
  const ocrValidated = validateChartResolution(
    ocr,
    pageWith(ocr),
    SOURCE_SHA256,
  );
  assert.equal(ocrValidated.resolution.transcript.source, "ocr");
  assert.equal(ocrValidated.resolution.transcript.confidence.value, 0.73);
  assert.equal(ocrValidated.primaryText, ocr.ocr_text);

  const unavailable = chartItem("unavailable-transcript-owner");
  unavailable.visual_structure!.labels = [];
  unavailable.visual_structure!.evidence = [];
  unavailable.chart_resolution!.transcript = {
    status: "unavailable",
    source: null,
    text: null,
    text_sha256: null,
    evidence_ids: [],
    confidence: sourceConfidenceUnavailable(),
  };
  unavailable.chart_resolution!.confidence_dimensions.transcription =
    sourceConfidenceUnavailable();
  assert.equal(
    validateChartResolution(
      unavailable,
      pageWith(unavailable),
      SOURCE_SHA256,
    ).resolution.transcript.status,
    "unavailable",
  );
});

test("forged chart transcript text, source, evidence, and mirrored confidence fail closed", () => {
  const mutations: Array<(item: DocumentContentItem) => void> = [
    (item) => {
      const forgedText = "FORGED OCR DECISION TEXT";
      item.chart_resolution!.transcript.text = forgedText;
      item.chart_resolution!.transcript.text_sha256 = digest(forgedText);
    },
    (item) => {
      item.chart_resolution!.transcript.source = "ocr";
    },
    (item) => {
      item.chart_resolution!.transcript.evidence_ids = [
        ...item.chart_resolution!.transcript.evidence_ids,
      ].reverse();
    },
    (item) => {
      const forgedConfidence = confidence(0.99);
      item.chart_resolution!.transcript.confidence = forgedConfidence;
      item.chart_resolution!.confidence_dimensions.transcription =
        forgedConfidence;
    },
  ];
  for (const [index, mutate] of mutations.entries()) {
    const item = chartItem(`forged-transcript-owner-${index}`);
    mutate(item);
    const page = pageWith(item);
    assert.equal(
      readChartResolution(item, page, SOURCE_SHA256),
      null,
      `forgery ${index} must fail closed`,
    );
    assert.throws(
      () => validateChartResolution(item, page, SOURCE_SHA256),
      /chart_resolution\.transcript/u,
    );
  }
});

test("raw content detection retains a validated image-only chart page", () => {
  const item = chartItem("image-only-owner");
  delete item.caption;
  delete item.value;
  delete item.md;
  item.visual_structure!.labels = [];
  item.visual_structure!.evidence = [];
  item.chart_resolution!.transcript = {
    status: "unavailable",
    source: null,
    text: null,
    text_sha256: null,
    evidence_ids: [],
    confidence: {
      value: null,
      unavailable_reason: "source_confidence_unavailable",
    },
  };
  item.chart_resolution!.confidence_dimensions.transcription = {
    value: null,
    unavailable_reason: "source_confidence_unavailable",
  };
  const page = pageWith(item);

  assert.equal(
    pageHasContent(page, SOURCE_SHA256, SOURCE_SHA256),
    true,
  );
  assert.equal(
    pageHasContent(page, NORMALIZED_SOURCE_SHA256, SOURCE_SHA256),
    false,
  );
  const validated = readChartImageResolution(
    item,
    page,
    SOURCE_SHA256,
    SOURCE_SHA256,
  );
  assert.ok(validated);
  const markup = renderToStaticMarkup(
    renderValidatedChartResolution(validated),
  );
  assert.match(markup, /<img alt=""/u);
  assert.match(
    markup,
    /data-chart-accessibility-disposition="empty_alt"/u,
  );
  assert.doesNotMatch(markup, /aria-labelledby|figcaption/u);
});

test("normalized raster assets bind original and render-source digests independently", () => {
  const item = chartItem("normalized-image-owner");
  const pixelBox = { ...BOX, unit: "px" as const };
  item.bbox = pixelBox;
  item.visual_structure!.region.page_bbox = pixelBox;
  const resolution = item.chart_resolution!;
  resolution.source_bbox = pixelBox;
  const asset = resolution.asset!;
  asset.source_bbox = pixelBox;
  asset.rendered_bbox = pixelBox;
  asset.render_source_sha256 = NORMALIZED_SOURCE_SHA256;
  asset.renderer = "pillow";
  asset.source_kind = "image";
  asset.render_scale = 1;
  asset.effective_dpi = null;
  asset.page_device_dimensions = null;
  asset.crop_device_margins = null;
  asset.bbox_rounding = "exact_integer";
  asset.asset_id = replayChartSourceAssetId(asset);
  const page = { ...pageWith(item), unit: "px" };
  assert.ok(
    readChartImageResolution(
      item,
      page,
      SOURCE_SHA256,
      NORMALIZED_SOURCE_SHA256,
    ),
  );
  assert.equal(
    readChartImageResolution(item, page, SOURCE_SHA256),
    null,
  );
});

test("undetermined family accepts conflicting source signals without discarding the image", () => {
  const item = chartItem("ambiguous-family-owner");
  item.chart_resolution!.family_classification = {
    status: "undetermined",
    family: "undetermined",
    classifier_version: "chart-family-source-evidence-v1",
    reason_codes: ["multiple_family_signals"],
    evidence_ids: ["bar-signal", "line-signal"],
    confidence: confidence(0.55),
  };
  item.chart_resolution!.confidence_dimensions.family = confidence(0.55);
  item.chart_resolution!.concern_codes = [
    "chart_family_undetermined",
    "chart_semantics_unsupported",
  ];

  assert.ok(
    readChartImageResolution(item, pageWith(item), SOURCE_SHA256),
  );
});

test("chart asset identity exactly replays Python canonical JSON custody", () => {
  const ordinary = unsupportedResolution("chart-owner").asset!;
  assert.equal(
    replayChartSourceAssetId(ordinary),
    "chart-asset-40fa607216a820589d6ef391",
  );

  const exponentAndUnicode = structuredClone(ordinary);
  const edgeBox = {
    x: 1e-5,
    y: 1e16,
    width: 1.2345678901234567e-7,
    height: 0.0001,
    unit: "pt" as const,
  };
  exponentAndUnicode.render_source_sha256 = NORMALIZED_SOURCE_SHA256;
  exponentAndUnicode.owner_item_id = "unicode-é-😀";
  exponentAndUnicode.physical_page = 7;
  exponentAndUnicode.source_bbox = edgeBox;
  exponentAndUnicode.owner_geometry_evidence_ids = ["ev-é"];
  exponentAndUnicode.rendered_bbox = edgeBox;
  exponentAndUnicode.page_device_dimensions = null;
  exponentAndUnicode.crop_device_margins = null;
  assert.equal(
    replayChartSourceAssetId(exponentAndUnicode),
    "chart-asset-e14080ee0a6901d02b9a0f27",
  );
});

test("malformed chart bytes, metadata, terminal state, and document custody fail closed", () => {
  const original = chartItem();
  const mutations: Array<(item: DocumentContentItem) => void> = [
    (item) => {
      (item.chart_resolution as unknown as Record<string, unknown>).extra = true;
    },
    (item) => {
      item.chart_resolution!.owner_item_id = "another-owner";
    },
    (item) => {
      item.chart_resolution!.asset!.byte_length += 1;
    },
    (item) => {
      item.chart_resolution!.asset!.asset_id =
        "chart-asset-000000000000000000000000";
    },
    (item) => {
      item.chart_resolution!.asset!.owner_geometry_proof_kind =
        "detected_image_and_docling_picture";
    },
    (item) => {
      item.chart_resolution!.asset!.owner_geometry_evidence_sha256 = "D".repeat(64);
    },
    (item) => {
      delete (item.chart_resolution!.asset as unknown as Record<string, unknown>)
        .owner_geometry_proof_kind;
    },
    (item) => {
      item.chart_resolution!.primary_reason = "semantic_analysis_incomplete";
    },
    (item) => {
      item.chart_resolution!.source_bbox = { ...BOX, x: 11 };
    },
    (item) => {
      item.chart_resolution!.asset!.rendered_bbox = { ...BOX, x: 9.4 };
    },
    (item) => {
      item.chart_resolution!.asset!.page_device_dimensions = [2, 1];
    },
    (item) => {
      const bytes = Buffer.from(PNG_BYTES);
      bytes.writeUInt32BE(2, 16);
      item.chart_resolution!.asset!.data_uri =
        `data:image/png;base64,${bytes.toString("base64")}`;
      item.chart_resolution!.asset!.sha256 = digest(bytes);
    },
  ];
  for (const mutate of mutations) {
    const item = structuredClone(original);
    mutate(item);
    assert.equal(readChartImageResolution(item, pageWith(item), SOURCE_SHA256), null);
  }
  assert.equal(
    readChartImageResolution(original, pageWith(original), "c".repeat(64)),
    null,
  );
  const repeatedSourceSlot = chartItem("same-source-slot-owner");
  assert.equal(
    readChartResolution(
      original,
      pageWith(original, repeatedSourceSlot),
      SOURCE_SHA256,
    ),
    null,
  );
});

test("structured and unavailable terminal states render their one declared primary", () => {
  const structured = chartItem("structured-owner");
  const structuredResolution = structured.chart_resolution!;
  structuredResolution.status = "structured_primary";
  structuredResolution.primary_representation = "structured_chart";
  structuredResolution.primary_reason = "semantic_completeness_passed";
  structuredResolution.semantic_analysis = {
    capability_matrix_version: "chart-semantic-capabilities-v1",
    attempt_status: "completed",
    analyzer_ids: ["approved-analyzer"],
    configuration_sha256: CONFIGURATION_SHA256,
    completeness_gate_status: "passed",
    required_features: ["region"],
    observed_features: ["region"],
    missing_features: [],
    ambiguous_evidence_ids: [],
    failure_reason: null,
  };
  structuredResolution.concern_codes = [];
  const structuredMarkdown =
    "Revenue [source]<br>2025\n\n| Category | Series | Value |\n| --- | --- | ---: |\n| A | Revenue | 12 |\n";
  structured.visual_structure!.points = [{}];
  structured.visual_structure!.serialization = {
    status: "structured_chart",
    markdown: structuredMarkdown,
    caption_occurrences: 1,
    row_count: 1,
  };
  const structuredPage = pageWith(structured);
  const validatedStructured = readChartResolution(
    structured,
    structuredPage,
    SOURCE_SHA256,
  );
  assert.ok(validatedStructured);
  assert.equal(
    readChartImageResolution(structured, structuredPage, SOURCE_SHA256),
    null,
  );
  const structuredMarkup = renderToStaticMarkup(
    renderValidatedChartResolution(validatedStructured),
  );
  assert.match(structuredMarkup, /^<figure[^>]*class="parsed-chart-structure"/u);
  assert.match(structuredMarkup, /data-chart-resolution="structured_primary"/u);
  assert.match(structuredMarkup, /data-chart-source-order="4"/u);
  assert.match(
    structuredMarkup,
    /data-chart-accessibility-disposition="caption_in_serialization"/u,
  );
  assert.ok(structuredMarkup.includes("| Category | Series | Value |"));
  assert.equal(structuredMarkup.split("Revenue [source]").length - 1, 1);
  assert.doesNotMatch(structuredMarkup, /Grounded predecessor|<img|data:image/u);

  const structuredCanonical = canonicalFor(structured);
  structuredCanonical.block.markdown = structuredMarkdown;
  structuredCanonical.block.text = structuredMarkdown;
  structuredCanonical.page.blocks = [structuredCanonical.block];
  const canonicalStructured = readChartResolutionForCanonicalBlock(
    structuredCanonical.block,
    structuredCanonical.page,
    structuredPage,
    SOURCE_SHA256,
  );
  assert.ok(canonicalStructured);
  assert.equal(
    renderToStaticMarkup(renderValidatedChartResolution(canonicalStructured)),
    structuredMarkup,
  );
  for (const mutate of [
    (item: DocumentContentItem) => {
      item.visual_structure!.serialization!.row_count = 2;
    },
    (item: DocumentContentItem) => {
      item.visual_structure!.serialization!.caption_occurrences = 0;
    },
    (item: DocumentContentItem) => {
      (item.visual_structure!.serialization as unknown as Record<string, unknown>)
        .unexpected = true;
    },
    (item: DocumentContentItem) => {
      item.visual_structure!.serialization!.markdown =
        "Different caption\n\n| Category | Series | Value |\n";
    },
  ]) {
    const malformed = structuredClone(structured);
    mutate(malformed);
    assert.equal(
      readChartResolution(malformed, pageWith(malformed), SOURCE_SHA256),
      null,
    );
  }

  const unavailable = chartItem("unavailable-owner");
  const unavailableResolution = unavailable.chart_resolution!;
  unavailableResolution.status = "asset_unavailable";
  unavailableResolution.asset_status = "unavailable";
  unavailableResolution.asset_unavailable_reason = "render_failed";
  unavailableResolution.asset = null;
  unavailableResolution.primary_representation = "grounded_predecessor";
  unavailableResolution.primary_reason = "source_asset_unavailable";
  unavailableResolution.family_classification = {
    status: "not_run",
    family: "undetermined",
    classifier_version: "chart-family-source-evidence-v1",
    reason_codes: ["asset_unavailable"],
    evidence_ids: [],
    confidence: unavailableConfidence("asset_unavailable"),
  };
  unavailableResolution.complexity_classification = {
    status: "not_run",
    classifier_version: "chart-complexity-source-evidence-v1",
    reason_codes: ["asset_unavailable"],
    evidence_ids: [],
    confidence: unavailableConfidence("asset_unavailable"),
  };
  unavailableResolution.semantic_analysis = {
    capability_matrix_version: "chart-semantic-capabilities-v1",
    attempt_status: "not_run_asset_unavailable",
    analyzer_ids: [],
    configuration_sha256: CONFIGURATION_SHA256,
    completeness_gate_status: "not_run",
    required_features: [],
    observed_features: [],
    missing_features: [],
    ambiguous_evidence_ids: [],
    failure_reason: "asset_unavailable",
  };
  unavailableResolution.confidence_dimensions.ownership =
    unavailableConfidence("asset_unavailable");
  unavailableResolution.confidence_dimensions.family =
    unavailableConfidence("asset_unavailable");
  unavailableResolution.confidence_dimensions.complexity =
    unavailableConfidence("asset_unavailable");
  unavailableResolution.concern_codes = ["chart_source_asset_unavailable"];
  unavailable.visual_structure!.fallback.active = true;
  unavailable.visual_structure!.serialization = null;
  const unavailablePage = pageWith(unavailable);
  const validatedUnavailable = readChartResolution(
    unavailable,
    unavailablePage,
    SOURCE_SHA256,
  );
  assert.ok(validatedUnavailable);
  assert.equal(
    readChartImageResolution(unavailable, unavailablePage, SOURCE_SHA256),
    null,
  );
  const unavailableMarkup = renderToStaticMarkup(
    renderValidatedChartResolution(validatedUnavailable),
  );
  assert.match(unavailableMarkup, /^<figure[^>]*class="parsed-chart-unavailable"/u);
  assert.match(unavailableMarkup, /data-chart-resolution="asset_unavailable"/u);
  assert.match(unavailableMarkup, />Grounded predecessor<\/p>/u);
  assertSingleAccessibleCaption(
    unavailableMarkup,
    "Revenue [source]\n2025",
    false,
  );
  assert.doesNotMatch(unavailableMarkup, /<img|parsed-chart-structure-content|data:image/u);

  const unavailableCanonical = canonicalFor(unavailable);
  unavailableCanonical.block.markdown = "Grounded predecessor";
  unavailableCanonical.block.text = "Grounded predecessor";
  unavailableCanonical.page.blocks = [unavailableCanonical.block];
  const canonicalUnavailable = readChartResolutionForCanonicalBlock(
    unavailableCanonical.block,
    unavailableCanonical.page,
    unavailablePage,
    SOURCE_SHA256,
  );
  assert.ok(canonicalUnavailable);
  assert.equal(
    renderToStaticMarkup(renderValidatedChartResolution(canonicalUnavailable)),
    unavailableMarkup,
  );
  for (const reason of [
    "response_byte_limit",
    "document_render_timeout",
  ] as const) {
    unavailableResolution.asset_unavailable_reason = reason;
    assert.ok(
      readChartResolution(unavailable, pageWith(unavailable), SOURCE_SHA256),
    );
  }
});

test("canonical image rendering requires exact replay and a unique identity or text bridge", () => {
  const item = chartItem();
  const sourcePage = pageWith(item);
  const canonical = canonicalFor(item);
  assert.equal(
    readChartResolutionForCanonicalBlock(
      canonical.block,
      canonical.page,
      sourcePage,
      SOURCE_SHA256,
    )?.owner.id,
    item.id,
  );

  const badMarkdown = structuredClone(canonical.block);
  badMarkdown.markdown += " ";
  assert.equal(
    readChartResolutionForCanonicalBlock(
      badMarkdown,
      { ...canonical.page, blocks: [badMarkdown] },
      sourcePage,
      SOURCE_SHA256,
    ),
    null,
  );
  const badText = structuredClone(canonical.block);
  badText.text += " estimated";
  assert.equal(
    readChartResolutionForCanonicalBlock(
      badText,
      { ...canonical.page, blocks: [badText] },
      sourcePage,
      SOURCE_SHA256,
    ),
    null,
  );

  const duplicate = chartItem("chart-owner-2");
  assert.equal(
    readChartResolutionForCanonicalBlock(
      canonical.block,
      canonical.page,
      pageWith(item, duplicate),
      SOURCE_SHA256,
    ),
    null,
  );
});

test("raw and canonical image paths expose one deterministic safe caption label", () => {
  const item = chartItem("chart owner/unsafe:<id>");
  const sourcePage = pageWith(item);
  const raw = readChartImageResolution(
    item,
    sourcePage,
    SOURCE_SHA256,
    SOURCE_SHA256,
  );
  assert.ok(raw);
  const canonicalContract = canonicalFor(item);
  const canonical = readChartResolutionForCanonicalBlock(
    canonicalContract.block,
    canonicalContract.page,
    sourcePage,
    SOURCE_SHA256,
    SOURCE_SHA256,
  );
  assert.ok(canonical);

  const rawId = assertSingleAccessibleCaption(
    renderToStaticMarkup(renderValidatedChartResolution(raw)),
    "Revenue [source]\n2025",
  );
  const canonicalId = assertSingleAccessibleCaption(
    renderToStaticMarkup(renderValidatedChartResolution(canonical)),
    "Revenue [source]\n2025",
  );
  assert.equal(canonicalId, rawId);
  assert.doesNotMatch(rawId, /chart owner|unsafe|[<>:/\s]/u);
});

test("one strict same-page chart caption relationship moves into the figure once", () => {
  const owner = chartItem("linked-chart-owner");
  delete owner.caption;
  owner.layout_visual_relationships_projected = true;
  const relationshipId = `layout-rel-${"1".repeat(20)}`;
  const caption: DocumentContentItem = {
    id: "linked-chart-caption",
    type: "caption",
    reading_order: 3,
    value: "Source-visible chart caption",
    caption_of: owner.id,
    relationship_id: relationshipId,
    relationship_type: "caption_of",
    relationship_basis: "graph_and_geometry",
  };
  owner.caption_ids = [caption.id];
  owner.caption_of = [caption.id];
  owner.relationships = [
    {
      id: relationshipId,
      type: "caption_of",
      source_id: caption.id,
      target_id: owner.id,
    },
  ];
  const page = pageWith(caption, owner);
  const link = resolveChartCaptionLink(owner, page);
  assert.ok(link);
  const chart = readChartResolution(owner, page, SOURCE_SHA256);
  assert.ok(chart);
  const markup = renderToStaticMarkup(
    renderValidatedChartResolution(chart, {
      itemId: link.caption.id,
      placement: "before",
      relationshipId: link.relationship.id,
      text: String(link.caption.value),
    }),
  );
  assertSingleAccessibleCaption(markup, "Source-visible chart caption");
  assert.equal(markup.split("Source-visible chart caption").length - 1, 1);
  assert.ok(markup.indexOf("<figcaption") < markup.indexOf("<img"));
  assert.match(markup, /data-chart-caption-item-id="linked-chart-caption"/u);
  assert.ok(
    markup.includes(`data-chart-caption-relationship-id="${relationshipId}"`),
  );

  const wrongEndpoint = structuredClone(page);
  wrongEndpoint.items[1]!.relationships![0]!.target_id = "another-owner";
  assert.equal(resolveChartCaptionLink(wrongEndpoint.items[1]!, wrongEndpoint), null);
  const duplicateCaption = structuredClone(caption);
  duplicateCaption.id = "duplicate-caption";
  duplicateCaption.relationship_id = `layout-rel-${"2".repeat(20)}`;
  duplicateCaption.reading_order = 4;
  assert.equal(
    resolveChartCaptionLink(owner, pageWith(caption, duplicateCaption, owner)),
    null,
  );
});

test("raw and canonical workspace paths invoke terminal validation and once-only caption custody", () => {
  const workspace = readFileSync(
    new URL("../app/clearleaf-workspace.tsx", import.meta.url),
    "utf8",
  );
  assert.match(
    workspace,
    /type === "chart" && sourcePage[\s\S]*?readChartResolution\(\s*item,\s*sourcePage,\s*sourceSha256,\s*renderSourceSha256/u,
  );
  assert.match(
    workspace,
    /readChartResolutionForCanonicalBlock\(\s*block,\s*page,\s*sourcePage,\s*sourceSha256,\s*renderSourceSha256/u,
  );
  assert.match(workspace, /renderValidatedChartResolution\(\s*chart,/u);
  assert.match(workspace, /resolveChartCaptionLink\(item, page\)/u);
  assert.match(workspace, /consumedCaptionIds\.has\(item\.id\)/u);
  assert.match(workspace, /consumedCaptionBlockIds\.has\(block\.id\)/u);
  assert.match(
    workspace,
    /block\.relationship_ids\.filter\(\(id\) => id === link\.relationship\.id\)[\s\S]*?\.length === 1/u,
  );
  assert.match(
    workspace,
    /captionBlockIds\.length !== 1/u,
  );
});
