import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import {
  canonicalPageBlocks,
  canonicalPageView,
  initialPagePresentationView,
  pageDisplayLabel,
  readRunningRegions,
  RunningRegionValidationError,
} from "../lib/running-regions.ts";
import {
  serializePageMarkdown,
  serializePageOutput,
} from "../lib/serialize-output.ts";
import type {
  CanonicalBlock,
  CanonicalPage,
  CanonicalPresentation,
  CanonicalView,
  PageIdentity,
  ParseResult,
  RunningRegionDescriptor,
  RunningRegionsProcessingSummary,
} from "../lib/types.ts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);

const digest = "a".repeat(64);
const pageId = `page-${"1".repeat(20)}`;
const bodyBlockId = `pb-${"2".repeat(20)}`;
const footerBlockId = `pb-${"3".repeat(20)}`;
const bodyElementId = `el-${"4".repeat(20)}`;
const footerElementId = `el-${"5".repeat(20)}`;
const bidiPrintedLabel = "עמוד 46";

function view(blocks: CanonicalBlock[]): CanonicalView {
  const rendered = blocks.filter(
    (block) => (block.omission_reason ?? null) === null,
  );
  const render = (values: string[]) =>
    values.length ? `${values.join("\n\n")}\n` : "";
  return {
    block_ids: rendered.map((block) => block.id),
    markdown: render(rendered.map((block) => block.markdown)),
    text: render(rendered.map((block) => block.text)),
  };
}

function fixture(): {
  result: ParseResult;
  presentation: CanonicalPresentation;
  page: ParseResult["pages"][number];
} {
  const identity: PageIdentity = {
    schema_version: "1.0",
    policy_id: "p03-running-regions-page-identity-v1",
    page_id: pageId,
    physical_page_index: 1,
    embedded_label: null,
    detected_printed_label: null,
    visible_text: null,
    display_label: bidiPrintedLabel,
    display_source: "legacy_display_fallback",
    evidence_bbox: null,
    evidence_source: {
      method: "legacy_display_fallback",
      reader: "configured_predecessor",
      page_index: 1,
      public_item_id: null,
      public_path: [],
      element_id: null,
      bbox_id: null,
      evidence_ids: [],
      source_object_ids: [
        `configured-predecessor:${digest}:page:1:page_label`,
      ],
    },
    confidence: {
      scope: "unavailable",
      score: null,
      unavailable_reason: "page_identity_source_unavailable",
    },
    concern_codes: [],
  };
  const descriptor: RunningRegionDescriptor = {
    id: `running-region-${"6".repeat(20)}`,
    page_id: pageId,
    physical_page_index: 1,
    role: "footer",
    canonical_scope: "footer",
    source_public_item_id: "footer-item",
    source_public_path: ["pages", 0, "items", 1],
    source_element_id: footerElementId,
    predecessor_type: "footer",
    predecessor_item_sha256: "7".repeat(64),
    bbox_id: `box-${"8".repeat(20)}`,
    bbox: { x: 48, y: 740, width: 120, height: 12, unit: "pt" },
    evidence_ids: [`ev-${"9".repeat(20)}`],
    source_object_ids: [`pdfplumber:${digest}:page:1:word:20`],
    source_method: "trusted_layout_role",
    repetition_group_id: null,
    repetition_page_indexes: [],
    confidence: {
      scope: "deterministic_rule",
      score: 1,
      unavailable_reason: null,
    },
    concern_codes: [],
    canonical_block_id: footerBlockId,
  };
  const blocks: CanonicalBlock[] = [
    {
      id: bodyBlockId,
      page_id: pageId,
      primary_element_id: bodyElementId,
      primary_element_type: "text",
      scope: "body",
      markdown: "BODY",
      text: "Body",
      contributing_element_ids: [bodyElementId],
      relationship_ids: [],
      excluded_contributions: [],
    },
    {
      id: footerBlockId,
      page_id: pageId,
      primary_element_id: footerElementId,
      primary_element_type: "footer",
      scope: "footer",
      markdown: `FOOTER ${bidiPrintedLabel}`,
      text: `Footer ${bidiPrintedLabel}`,
      contributing_element_ids: [footerElementId],
      relationship_ids: [],
      excluded_contributions: [],
    },
  ];
  const body = view([blocks[0]]);
  const footer = view([blocks[1]]);
  const full = view(blocks);
  const empty = view([]);
  const canonicalPage: CanonicalPage = {
    page_id: pageId,
    page_index: 1,
    page_number: 1,
    page_label: bidiPrintedLabel,
    blocks,
    full,
    body,
    header: empty,
    footer,
    page_identity: structuredClone(identity),
  };
  const presentation: CanonicalPresentation = {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [canonicalPage],
    full,
    body,
    header: empty,
    footer,
  };
  const summary: RunningRegionsProcessingSummary = {
    policy_id: "p03-running-regions-page-identity-v1",
    status: "projected",
    reason: null,
    source_page_count: 1,
    identity_count: 1,
    detected_label_count: 0,
    embedded_label_count: 0,
    legacy_fallback_count: 1,
    candidate_count: 1,
    comparison_count: 0,
    running_region_count: 1,
    header_count: 0,
    footer_count: 1,
    top_navigation_count: 0,
    bottom_navigation_count: 0,
    concern_count: 0,
    extraction_ms: 1,
    projection_ms: 2,
    total_ms: 3,
  };
  const page: ParseResult["pages"][number] = {
    page_index: 1,
    page_number: 1,
    page_label: bidiPrintedLabel,
    page_width: 612,
    page_height: 792,
    unit: "pt",
    success: true,
    warnings: [],
    page_identity: identity,
    items: [
      {
        id: "body-item",
        type: "text",
        reading_order: 1,
        value: "Body",
        md: "BODY",
      },
      {
        id: "footer-item",
        type: "footer",
        reading_order: 2,
        value: `Footer ${bidiPrintedLabel}`,
        md: `FOOTER ${bidiPrintedLabel}`,
        bbox: { x: 48, y: 740, width: 120, height: 12, unit: "pt" },
        layout_running_region_projected: true,
        running_region_policy: "p03-running-regions-page-identity-v1",
        running_region: descriptor,
      },
    ],
  };
  const result: ParseResult = {
    schema_version: "1.0",
    document: {
      filename: "printed-label.pdf",
      mime_type: "application/pdf",
      sha256: digest,
      page_count: 1,
    },
    pages: [page],
    processing: {
      engine: "parser",
      ocr_engine: "none",
      ocr_languages: [],
      duration_ms: 3,
      running_regions: summary,
    },
    warnings: [],
    canonical_presentation: presentation,
  };
  return { result, presentation, page };
}

function assertInvalid(mutator: (result: ParseResult) => void): void {
  const { result, presentation } = fixture();
  mutator(result);
  assertRunningRegionsInvalid(result, presentation);
}

function assertRunningRegionsInvalid(
  result: ParseResult,
  presentation: CanonicalPresentation,
): void {
  assert.throws(
    () => readRunningRegions(result, presentation),
    (error: unknown) => {
      assert.ok(error instanceof RunningRegionValidationError);
      assert.equal(error.code, "invalid_running_regions");
      return true;
    },
  );
}

function makeValidExtracted(result: ParseResult): void {
  const syntheticItem = result.pages[0].items[1];
  const descriptor = syntheticItem.running_region!;
  descriptor.source_method = "extracted_source_contribution";
  descriptor.source_public_item_id = "body-item";
  descriptor.source_public_path = ["pages", 0, "items", 0];
  descriptor.predecessor_type = "text";
  syntheticItem.id = descriptor.id.replace(
    "running-region-",
    "running-region-item-",
  );
  syntheticItem.value = "Native footer source";
  syntheticItem.md = "Native footer source";
  syntheticItem.source = "native";
  syntheticItem.confidence = 1;
}

function setPrintedLabel(result: ParseResult, label: string): void {
  result.pages[0].page_label = label;
  result.pages[0].page_identity!.display_label = label;
  result.canonical_presentation!.pages[0].page_label = label;
  result.canonical_presentation!.pages[0].page_identity!.display_label = label;
}

function stripProjectedSidecars(result: ParseResult): void {
  delete result.pages[0].page_identity;
  delete result.canonical_presentation!.pages[0].page_identity;
  delete result.pages[0].items[1].layout_running_region_projected;
  delete result.pages[0].items[1].running_region_policy;
  delete result.pages[0].items[1].running_region;
}

function makeNonprojecting(
  status: "unavailable" | "not_applicable" | "failed_closed",
): ReturnType<typeof fixture> {
  const built = fixture();
  stripProjectedSidecars(built.result);
  const reason = {
    unavailable: "running_region_source_evidence_unavailable",
    not_applicable: "running_region_input_not_applicable",
    failed_closed: "running_region_projection_failed_closed",
  } as const;
  built.result.processing.running_regions = {
    policy_id: "p03-running-regions-page-identity-v1",
    status,
    reason: reason[status],
    source_page_count: 0,
    identity_count: 0,
    detected_label_count: 0,
    embedded_label_count: 0,
    legacy_fallback_count: 0,
    candidate_count: 0,
    comparison_count: 0,
    running_region_count: 0,
    header_count: 0,
    footer_count: 0,
    top_navigation_count: 0,
    bottom_navigation_count: 0,
    concern_count: 0,
    extraction_ms: 0,
    projection_ms: 0,
    total_ms: 0,
  };
  return built;
}

function addValidPageConcern(result: ParseResult): void {
  const code = "running_region_geometry_ambiguous";
  result.pages[0].items[1].running_region!.concern_codes = [code];
  result.processing.running_regions!.concern_count = 1;
  result.running_region_concerns = [
    {
      code,
      source_ref: "page:1",
      count: 1,
      cap: 64,
      exception_class: null,
    },
  ];
}

test("absence is an O(1) no-op that does not inspect pages or canonical data", () => {
  const result = {
    processing: {
      engine: "parser",
      ocr_engine: "none",
      ocr_languages: [],
      duration_ms: 1,
    },
    get pages(): never {
      throw new Error("absent running-region validation traversed pages");
    },
  } as unknown as ParseResult;
  const presentation = new Proxy({} as CanonicalPresentation, {
    get(): never {
      throw new Error("absent running-region validation traversed canonical data");
    },
  });

  assert.equal(readRunningRegions(result, presentation), null);
});

test("the closed validator accepts only a complete cross-surface projection", () => {
  const { result, presentation } = fixture();
  const validated = readRunningRegions(result, presentation);
  assert.ok(validated);
  assert.equal(pageDisplayLabel(validated, 1), bidiPrintedLabel);

  assertInvalid((candidate) => {
    delete candidate.pages[0].page_identity;
  });
  assertInvalid((candidate) => {
    (candidate.pages[0].page_identity as unknown as Record<string, unknown>)
      .unsupported = true;
  });
  assertInvalid((candidate) => {
    delete (candidate.pages[0].page_identity as unknown as Record<
      string,
      unknown
    >).evidence_source;
  });
  assertInvalid((candidate) => {
    candidate.canonical_presentation!.pages[0].page_identity!.display_label =
      "drifted";
  });
  assertInvalid((candidate) => {
    candidate.pages[0].items[1].running_region!.source_public_path = [
      "pages",
      0,
      "items",
      0,
    ];
  });
  assertInvalid((candidate) => {
    const summary = candidate.processing.running_regions! as unknown as Record<
      string,
      unknown
    >;
    summary.unsupported = true;
  });
  assertInvalid((candidate) => {
    delete (candidate.processing.running_regions! as unknown as Record<
      string,
      unknown
    >).identity_count;
  });
  assertInvalid((candidate) => {
    (candidate.pages[0].items[1].running_region as unknown as Record<
      string,
      unknown
    >).unsupported = true;
  });
  assertInvalid((candidate) => {
    delete (candidate.pages[0].items[1].running_region as unknown as Record<
      string,
      unknown
    >).canonical_block_id;
  });
});

test("public item bbox aliases must exactly match canonical dimensions", () => {
  const matchingAliases = fixture();
  Object.assign(matchingAliases.result.pages[0].items[1].bbox!, {
    w: 120,
    h: 12,
  });
  assert.ok(
    readRunningRegions(matchingAliases.result, matchingAliases.presentation),
  );

  assertInvalid((candidate) => {
    Object.assign(candidate.pages[0].items[1].bbox!, {
      w: 120.0005,
      h: 12,
    });
  });
  assertInvalid((candidate) => {
    Object.assign(
      candidate.pages[0].items[1].bbox as unknown as Record<string, unknown>,
      { w: "120", h: 12 },
    );
  });
  assertInvalid((candidate) => {
    Object.assign(
      candidate.pages[0].items[1].bbox as unknown as Record<string, unknown>,
      { w: 120, h: 12, depth: 1 },
    );
  });
  assertInvalid((candidate) => {
    Object.assign(
      candidate.pages[0].items[1].running_region!
        .bbox as unknown as Record<string, unknown>,
      { w: 120, h: 12 },
    );
  });
});

test("selected display source controls embedded, detected, and fallback counts", () => {
  const conflict = fixture();
  const conflictIdentity: PageIdentity = {
    ...structuredClone(conflict.result.pages[0].page_identity!),
    embedded_label: "7",
    detected_printed_label: "8",
    visible_text: "8",
    display_label: "7",
    display_source: "embedded_label",
    evidence_bbox: { x: 48, y: 740, width: 10, height: 12, unit: "pt" },
    evidence_source: {
      method: "native_printed_label",
      reader: "pdfplumber",
      page_index: 1,
      public_item_id: null,
      public_path: [],
      element_id: null,
      bbox_id: null,
      evidence_ids: [`ev-${"a".repeat(20)}`],
      source_object_ids: [`pdfplumber:${digest}:page:1:word:20`],
    },
    confidence: {
      scope: "source_metadata",
      score: 1,
      unavailable_reason: null,
    },
    concern_codes: ["page_identity_source_conflict"],
  };
  conflict.result.pages[0].page_identity = conflictIdentity;
  conflict.result.canonical_presentation!.pages[0].page_identity =
    structuredClone(conflictIdentity);
  conflict.result.processing.running_regions!.embedded_label_count = 1;
  conflict.result.processing.running_regions!.legacy_fallback_count = 0;
  conflict.result.processing.running_regions!.concern_count = 1;
  conflict.result.running_region_concerns = [
    {
      code: "page_identity_source_conflict",
      source_ref: "page:1",
      count: 1,
      cap: 64,
      exception_class: null,
    },
  ];
  assert.ok(readRunningRegions(conflict.result, conflict.presentation));

  const duplicateDetectedEvidence = structuredClone(conflict.result);
  duplicateDetectedEvidence.pages[0].page_identity!.evidence_source.evidence_ids.push(
    `ev-${"b".repeat(20)}`,
  );
  duplicateDetectedEvidence.canonical_presentation!.pages[0].page_identity =
    structuredClone(duplicateDetectedEvidence.pages[0].page_identity!);
  assertRunningRegionsInvalid(
    duplicateDetectedEvidence,
    duplicateDetectedEvidence.canonical_presentation!,
  );

  const attachedDetectedEvidence = structuredClone(conflict.result);
  const attachedIdentity = attachedDetectedEvidence.pages[0].page_identity!;
  attachedDetectedEvidence.pages[0].items[0].value = "8";
  attachedDetectedEvidence.pages[0].items[0].bbox = {
    x: 48,
    y: 740,
    width: 10,
    height: 12,
    w: 10,
    h: 12,
    unit: "pt",
  };
  attachedIdentity.evidence_source.public_item_id = "body-item";
  attachedIdentity.evidence_source.public_path = ["pages", 0, "items", 0];
  attachedIdentity.evidence_source.element_id = bodyElementId;
  attachedIdentity.evidence_source.bbox_id = `box-${"b".repeat(20)}`;
  attachedDetectedEvidence.canonical_presentation!.pages[0].page_identity =
    structuredClone(attachedIdentity);
  assert.ok(
    readRunningRegions(
      attachedDetectedEvidence,
      attachedDetectedEvidence.canonical_presentation!,
    ),
  );

  const detachedFromVisibleOwner = structuredClone(attachedDetectedEvidence);
  detachedFromVisibleOwner.pages[0].items[0].value = "9";
  assertRunningRegionsInvalid(
    detachedFromVisibleOwner,
    detachedFromVisibleOwner.canonical_presentation!,
  );

  const physical = fixture();
  physical.result.pages[0].page_label = "";
  physical.result.canonical_presentation!.pages[0].page_label = "";
  const physicalIdentity: PageIdentity = {
    ...structuredClone(physical.result.pages[0].page_identity!),
    display_label: "1",
    display_source: "physical",
    evidence_source: {
      method: "physical_page_index",
      reader: "configured_predecessor",
      page_index: 1,
      public_item_id: null,
      public_path: [],
      element_id: null,
      bbox_id: null,
      evidence_ids: [],
      source_object_ids: [],
    },
    confidence: {
      scope: "unavailable",
      score: null,
      unavailable_reason: "page_identity_display_fallback_physical",
    },
  };
  physical.result.pages[0].page_identity = physicalIdentity;
  physical.result.canonical_presentation!.pages[0].page_identity =
    structuredClone(physicalIdentity);
  assert.ok(readRunningRegions(physical.result, physical.presentation));

  const wrongLegacyDigest = fixture();
  wrongLegacyDigest.result.pages[0].page_identity!.evidence_source.source_object_ids = [
    `configured-predecessor:${"b".repeat(64)}:page:1:page_label`,
  ];
  wrongLegacyDigest.result.canonical_presentation!.pages[0].page_identity =
    structuredClone(wrongLegacyDigest.result.pages[0].page_identity!);
  assertRunningRegionsInvalid(
    wrongLegacyDigest.result,
    wrongLegacyDigest.result.canonical_presentation!,
  );

  const safeLegacyMustWin = structuredClone(physical.result);
  safeLegacyMustWin.pages[0].page_label = "Legacy 1";
  safeLegacyMustWin.canonical_presentation!.pages[0].page_label = "Legacy 1";
  assertRunningRegionsInvalid(
    safeLegacyMustWin,
    safeLegacyMustWin.canonical_presentation!,
  );

  const unsafePhysical = structuredClone(physical.result);
  unsafePhysical.pages[0].page_label = "<unsafe>";
  unsafePhysical.canonical_presentation!.pages[0].page_label = "<unsafe>";
  unsafePhysical.pages[0].page_identity!.concern_codes = [
    "page_identity_display_unsafe",
  ];
  unsafePhysical.canonical_presentation!.pages[0].page_identity =
    structuredClone(unsafePhysical.pages[0].page_identity!);
  unsafePhysical.processing.running_regions!.concern_count = 1;
  unsafePhysical.running_region_concerns = [
    {
      code: "page_identity_display_unsafe",
      source_ref: "page:1",
      count: 1,
      cap: 64,
      exception_class: null,
    },
  ];
  assert.ok(
    readRunningRegions(
      unsafePhysical,
      unsafePhysical.canonical_presentation!,
    ),
  );
});

test("confidence, method, repetition, evidence, and concern invariants fail closed", () => {
  assertInvalid((candidate) => {
    candidate.processing.running_regions!.extraction_ms = 2_000.001;
    candidate.processing.running_regions!.total_ms = 2_002.001;
  });
  assertInvalid((candidate) => {
    candidate.processing.running_regions!.projection_ms = 2_000.001;
    candidate.processing.running_regions!.total_ms = 2_001.001;
  });
  assertInvalid((candidate) => {
    candidate.pages[0].page_identity!.confidence = {
      scope: "deterministic_rule",
      score: 1,
      unavailable_reason: null,
    };
    candidate.canonical_presentation!.pages[0].page_identity =
      structuredClone(candidate.pages[0].page_identity!);
  });
  assertInvalid((candidate) => {
    candidate.pages[0].items[1].running_region!.confidence = {
      scope: "source_metadata",
      score: 1,
      unavailable_reason: null,
    };
  });
  assertInvalid((candidate) => {
    const descriptor = candidate.pages[0].items[1].running_region!;
    descriptor.role = "navigation_bottom";
    descriptor.source_method = "trusted_layout_role";
  });
  assertInvalid((candidate) => {
    const descriptor = candidate.pages[0].items[1].running_region!;
    descriptor.role = "footer";
    descriptor.source_method = "boundary_navigation";
  });
  assertInvalid((candidate) => {
    const descriptor = candidate.pages[0].items[1].running_region!;
    descriptor.role = "navigation_bottom";
    descriptor.source_method = "printed_label_boundary";
  });
  assertInvalid((candidate) => {
    const identity = candidate.pages[0].page_identity!;
    identity.detected_printed_label = "1";
    identity.visible_text = "1";
    identity.display_label = "1";
    identity.display_source = "detected_printed_label";
    identity.evidence_bbox = { x: 48, y: 740, width: 10, height: 12, unit: "pt" };
    identity.evidence_source = {
      method: "native_printed_label",
      reader: "pdfplumber",
      page_index: 1,
      public_item_id: null,
      public_path: [],
      element_id: null,
      bbox_id: null,
      evidence_ids: [`ev-${"a".repeat(20)}`],
      source_object_ids: [`pdfplumber:${digest}:page:1:word:20`],
    };
    identity.confidence = {
      scope: "deterministic_rule",
      score: 1,
      unavailable_reason: null,
    };
    identity.concern_codes = ["page_identity_detected_label_ambiguous"];
    candidate.canonical_presentation!.pages[0].page_identity =
      structuredClone(identity);
    candidate.processing.running_regions!.detected_label_count = 1;
    candidate.processing.running_regions!.legacy_fallback_count = 0;
    candidate.processing.running_regions!.concern_count = 1;
    candidate.running_region_concerns = [
      {
        code: "page_identity_detected_label_ambiguous",
        source_ref: "page:1",
        count: 1,
        cap: 64,
        exception_class: null,
      },
    ];
  });
  assertInvalid((candidate) => {
    const descriptor = candidate.pages[0].items[1].running_region!;
    descriptor.source_method = "cross_page_repetition";
  });
  assertInvalid((candidate) => {
    const descriptor = candidate.pages[0].items[1].running_region!;
    descriptor.source_method = "extracted_source_contribution";
    descriptor.source_public_item_id = "body-item";
    descriptor.source_public_path = ["pages", 0, "items", 0];
    descriptor.evidence_ids.push(`ev-${"b".repeat(20)}`);
  });
  assertInvalid((candidate) => {
    candidate.pages[0].items[1].running_region!.concern_codes = [
      "running_region_geometry_ambiguous",
    ];
  });
});

test("two descriptors cannot claim one element or canonical contribution", () => {
  assertInvalid((candidate) => {
    const page = candidate.pages[0];
    const duplicate = structuredClone(page.items[1]);
    duplicate.id = "footer-item-duplicate";
    duplicate.running_region!.id = `running-region-${"c".repeat(20)}`;
    duplicate.running_region!.source_public_item_id = duplicate.id;
    duplicate.running_region!.source_public_path = ["pages", 0, "items", 2];
    page.items.push(duplicate);
    candidate.processing.running_regions!.candidate_count = 2;
    candidate.processing.running_regions!.running_region_count = 2;
    candidate.processing.running_regions!.footer_count = 2;
  });
});

test("extracted synthetic items retain bounded public value and append custody", () => {
  const valid = fixture();
  makeValidExtracted(valid.result);
  assert.ok(readRunningRegions(valid.result, valid.presentation));

  for (const [mutationIndex, mutate] of [
    (item: ParseResult["pages"][number]["items"][number]) => {
      delete item.value;
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.md = "Different native text";
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.value = "x".repeat(4 * 1024 + 1);
      item.md = item.value as string;
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.value = "Cafe\u0301";
      item.md = item.value as string;
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.value = "hostile-\ud800";
      item.md = item.value as string;
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.value = "\u0085Native footer source";
      item.md = item.value as string;
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.id = "body-item";
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.id = "running-region-item-forged";
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.source = "ocr";
    },
    (item: ParseResult["pages"][number]["items"][number]) => {
      item.reading_order = 1;
    },
  ].entries()) {
    try {
      assertInvalid((candidate) => {
        makeValidExtracted(candidate);
        mutate(candidate.pages[0].items[1]);
      });
    } catch (error) {
      throw new Error(`extracted custody mutation ${mutationIndex} was accepted`, {
        cause: error,
      });
    }
  }

  assertInvalid((candidate) => {
    makeValidExtracted(candidate);
    const synthetic = candidate.pages[0].items[1];
    const laterOwner = structuredClone(candidate.pages[0].items[0]);
    laterOwner.id = "later-owner";
    laterOwner.reading_order = 3;
    candidate.pages[0].items.push(laterOwner);
    synthetic.running_region!.source_public_item_id = laterOwner.id;
    synthetic.running_region!.source_public_path = ["pages", 0, "items", 2];
  });

  assertInvalid((candidate) => {
    makeValidExtracted(candidate);
    const owner = candidate.pages[0].items[0];
    owner.layout_running_region_projected = true;
    owner.running_region_policy = "p03-running-regions-page-identity-v1";
    owner.running_region = structuredClone(
      candidate.pages[0].items[1].running_region,
    );
  });
});

test("concern records are exact, complete, and correlated to sidecars", () => {
  const valid = fixture();
  addValidPageConcern(valid.result);
  assert.ok(readRunningRegions(valid.result, valid.presentation));

  assertInvalid((candidate) => {
    addValidPageConcern(candidate);
    (
      candidate.running_region_concerns as unknown as Array<
        Record<string, unknown>
      >
    )[0].unsupported = true;
  });
  assertInvalid((candidate) => {
    addValidPageConcern(candidate);
    delete (
      candidate.running_region_concerns as unknown as Array<
        Record<string, unknown>
      >
    )[0].source_ref;
  });

  const lexical = fixture();
  addValidPageConcern(lexical.result);
  lexical.result.pages[0].items[1].running_region!.concern_codes = [
    "running_region_geometry_ambiguous",
    "running_region_ownership_conflict",
  ];
  lexical.result.processing.running_regions!.concern_count = 2;
  lexical.result.running_region_concerns!.push({
    code: "running_region_ownership_conflict",
    source_ref: "page:1",
    count: 1,
    cap: 64,
    exception_class: null,
  });
  assert.ok(readRunningRegions(lexical.result, lexical.presentation));
  lexical.result.pages[0].items[1].running_region!.concern_codes.reverse();
  assertRunningRegionsInvalid(lexical.result, lexical.presentation);
});

test("unsafe, controlled, and oversized labels fail while safe bidi text is inert", () => {
  const safe = fixture();
  const validated = readRunningRegions(safe.result, safe.presentation);
  assert.ok(validated);
  assert.equal(pageDisplayLabel(validated, 1), bidiPrintedLabel);
  const markup = renderToStaticMarkup(
    createElement("bdi", { dir: "auto" }, pageDisplayLabel(validated, 1)),
  );
  assert.equal(markup, `<bdi dir="auto">${bidiPrintedLabel}</bdi>`);

  for (const hostile of [
    "<img src=x onerror=alert(1)>",
    "[label](https://attacker.invalid)",
    "46%26script",
    "46&47",
    "46{47}",
    "46\\47",
    "46`47",
    " 46",
    "46 ",
    `e${String.fromCodePoint(0x0301)}`,
    "46\n47",
    "46\t47",
    `46${String.fromCharCode(0)}47`,
    `46${String.fromCodePoint(0x0085)}47`,
    `46${String.fromCodePoint(0x202e)}47`,
    `46${String.fromCodePoint(0x2066)}47`,
    `46${String.fromCodePoint(0x2028)}47`,
    `46${String.fromCodePoint(0xfdd0)}47`,
    `46${String.fromCharCode(0xd800)}47`,
    "x".repeat(257),
    "é".repeat(129),
  ]) {
    assertInvalid((candidate) => setPrintedLabel(candidate, hostile));
  }
});

test("Body and Full select exact canonical blocks and serializer bytes", () => {
  const { result, presentation, page } = fixture();
  const canonicalPage = presentation.pages[0];

  assert.deepEqual(canonicalPageView(canonicalPage, "body"), canonicalPage.body);
  assert.deepEqual(canonicalPageView(canonicalPage, "full"), canonicalPage.full);
  assert.deepEqual(
    canonicalPageBlocks(canonicalPage, "body").map((block) => block.id),
    [bodyBlockId],
  );
  assert.deepEqual(
    canonicalPageBlocks(canonicalPage, "full").map((block) => block.id),
    [bodyBlockId, footerBlockId],
  );

  assert.equal(serializePageMarkdown(page, result, "body"), "BODY\n");
  assert.equal(
    serializePageMarkdown(page, result, "full"),
    `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
  );
  assert.deepEqual(serializePageOutput(page, "markdown", result, "body"), {
    content: "BODY\n",
    contentType: "text/markdown",
    extension: "md",
  });
  assert.deepEqual(serializePageOutput(page, "markdown", result, "full"), {
    content: `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
    contentType: "text/markdown",
    extension: "md",
  });
  assert.equal(
    serializePageMarkdown(page, result),
    `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
    "the compatibility serializer must continue to default to Full",
  );
});

test("absence and nonprojecting summaries retain legacy Full selection", () => {
  const projected = fixture();
  assert.equal(
    initialPagePresentationView(
      readRunningRegions(projected.result, projected.presentation),
    ),
    "body",
  );

  const absent = fixture();
  stripProjectedSidecars(absent.result);
  delete absent.result.processing.running_regions;
  const absentContract = readRunningRegions(
    absent.result,
    absent.presentation,
  );
  assert.equal(absentContract, null);
  assert.equal(initialPagePresentationView(absentContract), "full");
  assert.equal(
    serializePageMarkdown(absent.page, absent.result),
    `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
  );

  for (const status of [
    "unavailable",
    "not_applicable",
    "failed_closed",
  ] as const) {
    const built = makeNonprojecting(status);
    const validated = readRunningRegions(built.result, built.presentation);
    assert.ok(validated);
    assert.equal(initialPagePresentationView(validated), "full");
    assert.equal(pageDisplayLabel(validated, 1), null);
    assert.equal(
      serializePageMarkdown(built.page, built.result),
      `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
    );
  }
});

test("nonprojecting rollback concerns use the closed code-only envelope", () => {
  const presentEmpty = makeNonprojecting("not_applicable");
  presentEmpty.result.running_region_concerns = [];
  assertRunningRegionsInvalid(presentEmpty.result, presentEmpty.presentation);

  for (const [status, code] of [
    ["unavailable", "running_region_source_evidence_unavailable"],
    ["failed_closed", "running_region_projection_failed_closed"],
  ] as const) {
    const valid = makeNonprojecting(status);
    valid.result.processing.running_regions!.concern_count = 1;
    valid.result.running_region_concerns = [{ code }] as never;
    assert.ok(readRunningRegions(valid.result, valid.presentation));

    const unknownField = makeNonprojecting(status);
    unknownField.result.processing.running_regions!.concern_count = 1;
    unknownField.result.running_region_concerns = [
      { code, source_ref: "document" },
    ] as never;
    assertRunningRegionsInvalid(
      unknownField.result,
      unknownField.presentation,
    );

    const wrongCount = makeNonprojecting(status);
    wrongCount.result.running_region_concerns = [{ code }] as never;
    assertRunningRegionsInvalid(wrongCount.result, wrongCount.presentation);
  }

  const notApplicable = makeNonprojecting("not_applicable");
  notApplicable.result.processing.running_regions!.concern_count = 1;
  notApplicable.result.running_region_concerns = [
    { code: "running_region_projection_failed_closed" },
  ] as never;
  assertRunningRegionsInvalid(notApplicable.result, notApplicable.presentation);
});

test("normalization uses Body for page rows and Full for the document", () => {
  const { result } = fixture();
  const normalized = normalizeDocumentJson(result);

  assert.equal(normalized.markdown.pages[0].markdown, "BODY\n");
  assert.equal(normalized.text.pages[0].text, "Body\n");
  assert.equal(normalized.markdown.pages[0].header, null);
  assert.equal(
    normalized.markdown.pages[0].footer,
    `FOOTER ${bidiPrintedLabel}\n`,
  );
  assert.equal(
    normalized.markdown_full,
    `BODY\n\nFOOTER ${bidiPrintedLabel}\n`,
  );
  assert.equal(normalized.text_full, `Body\n\nFooter ${bidiPrintedLabel}\n`);
});

test("printed labels are display-only: physical navigation remains page_index based", () => {
  const { result, presentation } = fixture();
  const validated = readRunningRegions(result, presentation);
  assert.ok(validated);
  assert.equal(pageDisplayLabel(validated, 1), bidiPrintedLabel);
  assert.equal(pageDisplayLabel(validated, 46), null);

  assert.match(
    workspaceSource,
    /physicalPages\s*=\s*useMemo[\s\S]*?mapPhysicalPages\(result\)\.byPageNumber/,
  );
  assert.match(workspaceSource, /physicalPageNumber\s*=\s*activePage \+ 1/);
  assert.match(
    workspaceSource,
    /currentPage\s*=\s*physicalPages\.get\(physicalPageNumber\)/,
  );
});

test("interactive results default to Full while one view selection drives render, source, copy, and download", () => {
  assert.match(
    workspaceSource,
    /<bdi\s+dir="auto">\s*\{[\s\S]*?displayLabel[\s\S]*?\}\s*<\/bdi>/,
  );
  assert.doesNotMatch(workspaceSource, /dangerouslySetInnerHTML/);
  assert.match(
    workspaceSource,
    /useState<PagePresentationView>\("full"\)/,
  );
  assert.match(
    workspaceSource,
    /if \(parsedPresentation\) \{\s*readRunningRegions\(parsed, parsedPresentation\);\s*\}\s*setPagePresentationView\("full"\);\s*setResult\(parsed\)/,
  );
  assert.doesNotMatch(
    workspaceSource,
    /setPagePresentationView\(initialPagePresentationView\(/,
  );
  assert.match(
    workspaceSource,
    /canonicalPageBlocks\(currentCanonicalPage,\s*pagePresentationView\)/,
  );
  assert.match(
    workspaceSource,
    /serializePageMarkdown\(currentPage,\s*result,\s*pagePresentationView\)/,
  );
  assert.match(
    workspaceSource,
    /navigator\.clipboard\.writeText\(visibleOutput\)/,
  );
  assert.match(
    workspaceSource,
    /new Blob\(\[visibleOutput\],\s*\{ type: mime \}\)/,
  );
  assert.match(workspaceSource, />\s*Body\s*</);
  assert.match(workspaceSource, />\s*Full\s*</);
});
