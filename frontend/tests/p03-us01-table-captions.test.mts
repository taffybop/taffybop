import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import {
  serializePageMarkdown,
} from "../lib/serialize-output.ts";
import { mapPhysicalPages } from "../lib/page-results.ts";
import { resolveCanonicalCaptionedTableLink } from "../lib/layout-relationships.ts";
import type {
  CanonicalBlock,
  CanonicalPage,
  CanonicalPresentation,
  CanonicalView,
  DocumentContentItem,
  LayoutRelationship,
  ParseResult,
} from "../lib/types.ts";
import { samplePage, sampleResult } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);

const relationship: LayoutRelationship = {
  id: "caption-rel",
  type: "caption_of",
  source_id: "caption-1",
  target_id: "table-1",
};

const caption: DocumentContentItem = {
  id: "caption-1",
  type: "caption",
  reading_order: 1,
  value: "EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025",
  md: "EXHIBIT 7: Top 5 Costliest Insured Loss Events in 1H 2025",
  bbox: {
    x: 100.7,
    y: 210.095,
    width: 250.22,
    height: 9.351,
    unit: "pt",
  },
  source: "native",
  confidence: null,
  caption_of: "table-1",
  relationship_id: relationship.id,
  relationship_type: relationship.type,
  relationship_basis: "graph_and_geometry",
};

const table: DocumentContentItem = {
  id: "table-1",
  type: "table",
  reading_order: 2,
  value: [["Date(s)", "Event"]],
  rows: [["Date(s)", "Event"]],
  md: "<table><tr><th>Date(s)</th><th>Event</th></tr></table>",
  html: "<table><tr><th>Date(s)</th><th>Event</th></tr></table>",
  caption_of: [caption.id],
  caption_ids: [caption.id],
  relationships: [relationship],
};

function view(blocks: CanonicalBlock[]): CanonicalView {
  return {
    block_ids: blocks.map((block) => block.id),
    markdown: `${blocks.map((block) => block.markdown).join("\n\n")}\n`,
    text: `${blocks.map((block) => block.text).join("\n\n")}\n`,
  };
}

function captionCanonicalPresentation(): CanonicalPresentation {
  const blocks: CanonicalBlock[] = [
    {
      id: "caption-block",
      page_id: "page-1",
      primary_element_id: caption.id,
      primary_element_type: "caption",
      scope: "body",
      markdown: String(caption.md),
      text: String(caption.value),
      contributing_element_ids: [caption.id],
      relationship_ids: [relationship.id],
      excluded_contributions: [],
    },
    {
      id: "table-block",
      page_id: "page-1",
      primary_element_id: table.id,
      primary_element_type: "table",
      scope: "body",
      markdown: String(table.md),
      text: "Date(s) Event",
      contributing_element_ids: [table.id],
      relationship_ids: [relationship.id],
      excluded_contributions: [],
    },
  ];
  const full = view(blocks);
  const empty = { block_ids: [], markdown: "", text: "" };
  return {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [
      {
        page_id: "page-1",
        page_index: 1,
        page_number: 7,
        page_label: "7",
        blocks,
        full,
        body: full,
        header: empty,
        footer: empty,
      },
    ],
    full,
    body: full,
    header: empty,
    footer: empty,
  };
}

function captionResult(): ParseResult {
  return sampleResult({
    document: {
      filename: "catastrophe-recap.pdf",
      mime_type: "application/pdf",
      sha256: "catastrophe",
      page_count: 1,
    },
    pages: [
      samplePage({
        page_index: 1,
        page_number: 7,
        page_label: "7",
        items: [caption, table],
      }),
    ],
    canonical_presentation: captionCanonicalPresentation(),
  });
}

test("caption and table stay separate, linked, and ordered in fallback Markdown", () => {
  const page = samplePage({ items: [table, caption] });
  const markdown = serializePageMarkdown(page);

  assert.equal(
    markdown.indexOf(String(caption.md)) <
      markdown.indexOf(String(table.md)),
    true,
  );
  assert.equal(markdown.match(/EXHIBIT 7:/g)?.length, 1);
  assert.equal(String(table.md).includes("EXHIBIT 7:"), false);
});

test("affected canonical page drives page mapping, source, copy, and download bytes", async () => {
  const result = captionResult();
  const page = mapPhysicalPages(result).byPageNumber.get(1);
  assert.ok(page);
  assert.equal(page.page_number, 7);
  assert.equal(page.page_label, "7");

  const markdownVisibleOutput = serializePageMarkdown(page, result);
  assert.equal(
    markdownVisibleOutput,
    `${caption.md}\n\n${table.md}\n`,
  );
  assert.equal(markdownVisibleOutput.match(/EXHIBIT 7:/g)?.length, 1);

  const normalized = normalizeDocumentJson(result);
  const normalizedItems = normalized.items.pages[0].items;
  assert.deepEqual(normalizedItems[0], caption);
  assert.deepEqual(normalizedItems[1], table);

  const jsonVisibleOutput = JSON.stringify(normalized, null, 2);
  let clipboardBytes = "";
  await {
    async writeText(value: string) {
      clipboardBytes = value;
    },
  }.writeText(jsonVisibleOutput);
  const downloadedBlob = new Blob(
    [jsonVisibleOutput],
    { type: "application/json" },
  );
  const downloaded = JSON.parse(await downloadedBlob.text());

  assert.equal(clipboardBytes, jsonVisibleOutput);
  assert.equal(downloadedBlob.type, "application/json");
  assert.equal(
    downloaded.items.pages[0].items[0].caption_of,
    "table-1",
  );
  assert.deepEqual(
    downloaded.items.pages[0].items[1].relationships,
    [relationship],
  );

  const visibleOutputSection = workspaceSource.slice(
    workspaceSource.indexOf("const visibleOutput = useMemo"),
    workspaceSource.indexOf("const resetPreviewScroll"),
  );
  const copyAndDownloadSection = workspaceSource.slice(
    workspaceSource.indexOf("const copyOutput = async"),
    workspaceSource.indexOf("const handleFormatKeyDown"),
  );
  assert.match(
    visibleOutputSection,
    /if \(format === "json"\) return documentJsonOutput/,
  );
  assert.match(
    visibleOutputSection,
    /serializePageMarkdown\(currentPage, result\)/,
  );
  assert.match(
    copyAndDownloadSection,
    /navigator\.clipboard\.writeText\(visibleOutput\)/,
  );
  assert.match(
    copyAndDownloadSection,
    /new Blob\(\[visibleOutput\], \{ type: mime \}\)/,
  );
});

test("flag-off affected page has no caption item or caption bytes", () => {
  const disabledTable = {
    ...table,
    caption_of: undefined,
    caption_ids: undefined,
    relationships: undefined,
  };
  const result = sampleResult({
    document: {
      filename: "catastrophe-recap.pdf",
      mime_type: "application/pdf",
      sha256: "catastrophe",
      page_count: 1,
    },
    pages: [
      samplePage({
        page_index: 1,
        page_number: 7,
        page_label: "7",
        items: [disabledTable],
      }),
    ],
  });

  const page = mapPhysicalPages(result).byPageNumber.get(1);
  assert.ok(page);
  assert.equal(serializePageMarkdown(page, result), `${table.md}\n`);
  assert.doesNotMatch(
    JSON.stringify(normalizeDocumentJson(result)),
    /EXHIBIT 7:|caption_of|caption_ids|caption-rel/,
  );
});

test("legacy item renderer has an explicit visible caption milestone", () => {
  assert.match(workspaceSource, /if \(type === "caption"\)/);
  assert.match(workspaceSource, /className="parsed-caption"/);
  assert.match(workspaceSource, /data-caption-of/);
});

function captionedCandidateResolverFixture(): {
  block: CanonicalBlock;
  canonicalPage: CanonicalPage;
  page: ReturnType<typeof samplePage>;
} {
  const publicRelationship: LayoutRelationship = {
    id: "public-captioned-candidate-rel",
    type: "caption_of",
    source_id: "public-candidate-caption",
    target_id: "public-candidate-owner",
  };
  const publicCaption: DocumentContentItem = {
    id: publicRelationship.source_id,
    type: "caption",
    reading_order: 0,
    value: "Table 1. Candidate caption.",
    md: "Table 1. Candidate caption.",
    caption_of: publicRelationship.target_id,
    relationship_id: publicRelationship.id,
    relationship_type: publicRelationship.type,
  };
  const publicOwner: DocumentContentItem = {
    id: publicRelationship.target_id,
    type: "table_candidate",
    reading_order: 1,
    value: [["A", "B"], ["1", "2"]],
    md: "| A | B |\n| - | - |\n| 1 | 2 |",
    rows: [["A", "B"], ["1", "2"]],
    row_count: 2,
    column_count: 2,
    table_candidate_gate: {
      outcome: "unresolved",
      owner_item_ids: [],
      feature_scores: { table_support: 0.9, cell_coverage: 1 },
    },
    table_candidate_gate_reasons: [
      "upstream_reconciliation_unresolved",
    ],
    table_candidate_gate_sources: [],
    caption_ids: [publicCaption.id],
    relationships: [publicRelationship],
  };
  const internalClaimedRelationshipId = "internal-caption-claim-rel";
  const internalEvidenceRelationshipId = "internal-caption-evidence-rel";
  const consumedCaptionBlock: CanonicalBlock = {
    id: "internal-consumed-caption-block",
    page_id: "canonical-candidate-page",
    primary_element_id: "internal-caption",
    primary_element_type: "caption",
    scope: "body",
    markdown: "",
    text: "",
    contributing_element_ids: [],
    relationship_ids: [
      internalEvidenceRelationshipId,
      internalClaimedRelationshipId,
    ],
    excluded_contributions: [
      {
        element_id: "internal-candidate-owner",
        reason: "already_claimed",
        relationship_ids: [internalClaimedRelationshipId],
      },
      {
        element_id: "internal-candidate-owner",
        reason: "evidence_only_relationship",
        relationship_ids: [internalEvidenceRelationshipId],
      },
    ],
    omission_reason: "consumed_by_relationship",
    suppressed_by_element_id: "internal-candidate-owner",
  };
  const block: CanonicalBlock = {
    id: "internal-candidate-owner-block",
    page_id: "canonical-candidate-page",
    primary_element_id: "internal-candidate-owner",
    primary_element_type: "table_candidate",
    scope: "body",
    markdown: "Table 1. Candidate caption.\n\n| A | B |\n| - | - |\n| 1 | 2 |",
    text: "Table 1. Candidate caption.\n\nA\tB\n1\t2",
    contributing_element_ids: [
      "internal-candidate-owner",
      consumedCaptionBlock.primary_element_id,
    ],
    relationship_ids: [
      internalClaimedRelationshipId,
      internalEvidenceRelationshipId,
    ],
    excluded_contributions: [],
  };
  const includedView = {
    block_ids: [block.id],
    markdown: `${block.markdown}\n`,
    text: `${block.text}\n`,
  };
  const emptyView = { block_ids: [], markdown: "", text: "" };
  const canonicalPage: CanonicalPage = {
    page_id: block.page_id,
    page_index: 1,
    page_number: 1,
    page_label: "1",
    blocks: [consumedCaptionBlock, block],
    full: includedView,
    body: includedView,
    header: emptyView,
    footer: emptyView,
  };
  return {
    block,
    canonicalPage,
    page: samplePage({ items: [publicCaption, publicOwner] }),
  };
}

test("caption-consumed table bridge rejects every ambiguous public or canonical claim", () => {
  const valid = captionedCandidateResolverFixture();
  const resolved = resolveCanonicalCaptionedTableLink(
    valid.block,
    valid.canonicalPage,
    valid.page,
  );
  assert.ok(resolved);
  assert.equal(resolved.caption.id, "public-candidate-caption");
  assert.equal(resolved.owner.id, "public-candidate-owner");
  assert.notEqual(valid.block.primary_element_id, resolved.owner.id);
  assert.equal(
    valid.canonicalPage.blocks[0].relationship_ids.includes(
      resolved.relationship.id,
    ),
    false,
  );
  assert.equal(
    valid.block.relationship_ids.includes(resolved.relationship.id),
    false,
  );

  const invalidFixtures = [
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.page.items[0].caption_of = "wrong-public-owner";
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.page.items[1].type = "table";
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.page.items.push({
        ...value.page.items[0],
        id: "competing-caption-claim",
        reading_order: 2,
      });
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.page.items.push({
        id: "competing-caption-descriptor",
        type: "text",
        reading_order: 2,
        value: "Unrelated",
        relationships: [value.page.items[1].relationships![0]],
      });
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.page.items.push({
        id: "competing-caption-backlink",
        type: "text",
        reading_order: 2,
        value: "Unrelated",
        caption_ids: ["public-candidate-caption"],
      });
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      value.canonicalPage.blocks.push({
        ...value.canonicalPage.blocks[0],
        id: "competing-consumed-caption-block",
        primary_element_id: "competing-internal-caption",
      });
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      const secondRelationshipId = "competing-caption-bridge";
      value.block.relationship_ids.push(secondRelationshipId);
      value.canonicalPage.blocks[0].relationship_ids.push(secondRelationshipId);
      value.canonicalPage.blocks[0].excluded_contributions[0].relationship_ids.push(
        secondRelationshipId,
      );
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      const caption = value.page.items[0];
      const owner = value.page.items[1];
      const relationship: LayoutRelationship = {
        id: "second-complete-public-caption-rel",
        type: "caption_of",
        source_id: "second-complete-public-caption",
        target_id: "second-complete-public-owner",
      };
      value.page.items.push(
        {
          ...caption,
          id: relationship.source_id,
          reading_order: 2,
          caption_of: relationship.target_id,
          relationship_id: relationship.id,
        },
        {
          ...owner,
          id: relationship.target_id,
          reading_order: 3,
          caption_ids: [relationship.source_id],
          relationships: [relationship],
        },
      );
      return value;
    })(),
    (() => {
      const value = structuredClone(captionedCandidateResolverFixture());
      const caption = value.page.items[0];
      const owner = value.page.items[1];
      const firstRelationship = owner.relationships![0];
      const secondRelationship: LayoutRelationship = {
        id: "split-public-caption-rel",
        type: "caption_of",
        source_id: "split-public-caption",
        target_id: "split-public-owner",
      };
      const secondCaption: DocumentContentItem = {
        ...caption,
        id: secondRelationship.source_id,
        reading_order: 2,
        caption_of: secondRelationship.target_id,
        relationship_id: secondRelationship.id,
      };
      const secondOwner: DocumentContentItem = {
        ...owner,
        id: secondRelationship.target_id,
        reading_order: 3,
        caption_ids: [secondCaption.id],
        relationships: [firstRelationship],
      };
      owner.relationships = [secondRelationship];
      value.page.items.push(secondCaption, secondOwner);
      return value;
    })(),
  ];

  for (const invalid of invalidFixtures) {
    assert.equal(
      resolveCanonicalCaptionedTableLink(
        invalid.block,
        invalid.canonicalPage,
        invalid.page,
      ),
      null,
    );
  }
});
