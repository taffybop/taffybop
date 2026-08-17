import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { resolveCanonicalNoteLink } from "../lib/layout-relationships.ts";
import { serializePageMarkdown } from "../lib/serialize-output.ts";
import type {
  CanonicalBlock,
  DocumentContentItem,
  LayoutRelationship,
} from "../lib/types.ts";
import { samplePage } from "./fixtures.mts";

const workspaceSource = readFileSync(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);
const stylesheetSource = readFileSync(
  new URL("../app/globals.css", import.meta.url),
  "utf8",
);

const sourceRelationship: LayoutRelationship = {
  id: "layout-rel-source-note",
  type: "source_note_of",
  source_id: "source-note-1",
  target_id: "chart-1",
};
const footnoteRelationship: LayoutRelationship = {
  id: "layout-rel-footnote",
  type: "footnote_of",
  source_id: "footnote-1",
  target_id: "chart-1",
};

const sourceNote: DocumentContentItem = {
  id: "source-note-1",
  type: "source_note",
  reading_order: 2,
  value: "Data: Aon Catastrophe Insight",
  md: "Data: Aon Catastrophe Insight",
  bbox: {
    x: 100,
    y: 586,
    width: 137,
    height: 9,
    unit: "pt",
  },
  source: "ocr",
  confidence: 0.98,
  source_note_of: "chart-1",
  relationship_id: sourceRelationship.id,
  relationship_type: "source_note_of",
  relationship_basis: "bounded_visual_band_and_geometry",
  links: [
    {
      kind: "pdf_annotation",
      target: "https://example.test/source",
    },
  ],
};

const footnote: DocumentContentItem = {
  id: "footnote-1",
  type: "footnote",
  reading_order: 3,
  value: "Values are rounded.",
  md: "Values are rounded.",
  bbox: {
    x: 100,
    y: 598,
    width: 80,
    height: 8,
    unit: "pt",
  },
  source: "native",
  confidence: null,
  footnote_of: "chart-1",
  relationship_id: footnoteRelationship.id,
  relationship_type: "footnote_of",
  relationship_basis: "graph_and_geometry",
};

const chart: DocumentContentItem = {
  id: "chart-1",
  type: "chart",
  reading_order: 1,
  value: "Authorized chart text",
  md: "Authorized chart text",
  bbox: {
    x: 100,
    y: 437,
    width: 445,
    height: 148,
    unit: "pt",
  },
  source: "ocr",
  confidence: 0.8,
  source_note_ids: [sourceNote.id],
  footnote_ids: [footnote.id],
  relationships: [sourceRelationship, footnoteRelationship],
  layout_source_notes_projected: true,
};

function noteBlock(
  note: DocumentContentItem,
  relationship: LayoutRelationship,
): CanonicalBlock {
  return {
    id: `canonical-${note.id}`,
    page_id: "canonical-page-1",
    primary_element_id: `internal-${note.id}`,
    primary_element_type: note.type,
    scope: "body",
    markdown: String(note.md),
    text: String(note.value),
    contributing_element_ids: [`internal-${note.id}`],
    relationship_ids: [relationship.id],
    excluded_contributions: [],
  };
}

const sourceBlock = noteBlock(sourceNote, sourceRelationship);
const footnoteBlock = noteBlock(footnote, footnoteRelationship);

function unresolvedCandidateOwner(
  overrides: Partial<DocumentContentItem> = {},
): DocumentContentItem {
  return {
    ...chart,
    id: "table-candidate-1",
    type: "table_candidate",
    rows: [
      ["Group", "Value"],
      ["A", "1"],
    ],
    row_count: 2,
    column_count: 2,
    table_candidate_gate: {
      outcome: "unresolved",
      owner_item_ids: [],
      feature_scores: { table_support: 0.75, cell_coverage: 1 },
    },
    table_candidate_gate_reasons: [
      "upstream_reconciliation_unresolved",
    ],
    table_candidate_gate_sources: [],
    ...overrides,
  };
}

test("canonical source-note and footnote relationships resolve through exact public links", () => {
  const page = samplePage({ items: [chart, sourceNote, footnote] });

  const sourceLink = resolveCanonicalNoteLink(sourceBlock, page);
  assert.ok(sourceLink);
  assert.equal(sourceLink.note, sourceNote);
  assert.equal(sourceLink.owner, chart);
  assert.equal(sourceLink.relationship, sourceRelationship);
  assert.equal(sourceLink.noteType, "source_note");
  assert.equal(sourceLink.relationshipType, "source_note_of");

  const footnoteLink = resolveCanonicalNoteLink(footnoteBlock, page);
  assert.ok(footnoteLink);
  assert.equal(footnoteLink.note, footnote);
  assert.equal(footnoteLink.owner, chart);
  assert.equal(footnoteLink.relationship, footnoteRelationship);
  assert.equal(footnoteLink.noteType, "footnote");
  assert.equal(footnoteLink.relationshipType, "footnote_of");
});

test("canonical notes resolve through an eligible unresolved table candidate without promotion", () => {
  const owner = unresolvedCandidateOwner();
  const relationship: LayoutRelationship = {
    ...sourceRelationship,
    target_id: owner.id,
  };
  const note: DocumentContentItem = {
    ...sourceNote,
    source_note_of: owner.id,
    relationship_id: relationship.id,
  };
  owner.source_note_ids = [note.id];
  owner.footnote_ids = [];
  owner.relationships = [relationship];
  const block = noteBlock(note, relationship);

  const link = resolveCanonicalNoteLink(
    block,
    samplePage({ items: [owner, note] }),
  );

  assert.ok(link);
  assert.equal(link.owner, owner);
  assert.equal(link.note, note);
  assert.equal(link.owner.type, "table_candidate");
});

test("canonical notes reject malformed or weak unresolved table candidates", () => {
  const invalidOwners = [
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "canonical_table",
        owner_item_ids: [],
        feature_scores: { table_support: 0.75, cell_coverage: 1 },
      },
    }),
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "unresolved",
        owner_item_ids: ["other-owner"],
        feature_scores: { table_support: 0.75, cell_coverage: 1 },
      },
    }),
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "unresolved",
        owner_item_ids: [],
        feature_scores: { table_support: 0.61, cell_coverage: 1 },
      },
    }),
    unresolvedCandidateOwner({
      table_candidate_gate_reasons: ["insufficient_table_support"],
    }),
    unresolvedCandidateOwner({
      table_candidate_gate_sources: [
        {
          owner_item_id: "forged-owner",
          owner_type: "image",
          bbox: { x: 0, y: 0, width: 1, height: 1, unit: "pt" },
          overlap: 1,
        },
      ],
    }),
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "unresolved",
        owner_item_ids: [],
        feature_scores: { table_support: 0.75, cell_coverage: 0.749999 },
      },
    }),
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "unresolved",
        owner_item_ids: [],
        feature_scores: { table_support: 0.75 },
      },
    }),
    unresolvedCandidateOwner({
      table_candidate_gate: {
        outcome: "unresolved",
        owner_item_ids: [],
        feature_scores: { table_support: 0.75, cell_coverage: Number.NaN },
      },
    }),
    unresolvedCandidateOwner({ rows: [["Group", "Value"], ["A"]] }),
    unresolvedCandidateOwner({ rows: [["Only one row", "1"]], row_count: 1 }),
  ];

  for (const owner of invalidOwners) {
    const relationship: LayoutRelationship = {
      ...sourceRelationship,
      target_id: owner.id,
    };
    const note: DocumentContentItem = {
      ...sourceNote,
      source_note_of: owner.id,
      relationship_id: relationship.id,
    };
    owner.source_note_ids = [note.id];
    owner.footnote_ids = [];
    owner.relationships = [relationship];
    assert.equal(
      resolveCanonicalNoteLink(
        noteBlock(note, relationship),
        samplePage({ items: [owner, note] }),
      ),
      null,
    );
  }
});

test("canonical note resolution rejects duplicate IDs anywhere on the page", () => {
  const duplicateItemPage = samplePage({
    items: [
      chart,
      sourceNote,
      footnote,
      {
        id: footnote.id,
        type: "text",
        reading_order: 4,
        value: "Conflicting item",
      },
    ],
  });
  assert.equal(
    resolveCanonicalNoteLink(sourceBlock, duplicateItemPage),
    null,
  );

  const duplicateRelationshipPage = samplePage({
    items: [
      chart,
      sourceNote,
      footnote,
      {
        id: "unrelated-image",
        type: "image",
        reading_order: 4,
        relationships: [
          {
            ...footnoteRelationship,
            source_id: "unrelated-note",
            target_id: "unrelated-image",
          },
        ],
      },
    ],
  });
  assert.equal(
    resolveCanonicalNoteLink(sourceBlock, duplicateRelationshipPage),
    null,
  );

  const duplicateRelationshipClaimPage = samplePage({
    items: [
      chart,
      sourceNote,
      {
        ...footnote,
        type: "source_note",
        source_note_of: chart.id,
        footnote_of: undefined,
        relationship_id: sourceRelationship.id,
        relationship_type: "source_note_of",
      },
    ],
  });
  assert.equal(
    resolveCanonicalNoteLink(sourceBlock, duplicateRelationshipClaimPage),
    null,
  );

  const nonNoteRelationshipClaimPage = samplePage({
    items: [
      chart,
      sourceNote,
      footnote,
      {
        id: "caption-with-conflicting-claim",
        type: "caption",
        reading_order: 4,
        value: "Conflicting caption",
        relationship_id: sourceRelationship.id,
        relationship_type: "caption_of",
      },
    ],
  });
  assert.equal(
    resolveCanonicalNoteLink(sourceBlock, nonNoteRelationshipClaimPage),
    null,
  );
});

test("canonical note resolution requires exact type, endpoints, marker, and one backlink", () => {
  const ownerWith = (
    overrides: Partial<DocumentContentItem>,
  ): DocumentContentItem => ({
    ...chart,
    ...overrides,
  });

  const invalidOwners: DocumentContentItem[] = [
    ownerWith({ layout_source_notes_projected: false }),
    ownerWith({ type: "text" }),
    ownerWith({ source_note_ids: [] }),
    ownerWith({ source_note_ids: [sourceNote.id, sourceNote.id] }),
    ownerWith({
      relationships: [
        {
          ...sourceRelationship,
          type: "footnote_of",
        },
        footnoteRelationship,
      ],
    }),
    ownerWith({
      relationships: [
        {
          ...sourceRelationship,
          source_id: footnote.id,
        },
        footnoteRelationship,
      ],
    }),
    ownerWith({
      relationships: [
        {
          ...sourceRelationship,
          target_id: "different-owner",
        },
        footnoteRelationship,
      ],
    }),
  ];

  for (const invalidOwner of invalidOwners) {
    assert.equal(
      resolveCanonicalNoteLink(
        sourceBlock,
        samplePage({ items: [invalidOwner, sourceNote, footnote] }),
      ),
      null,
    );
  }

  assert.equal(
    resolveCanonicalNoteLink(
      sourceBlock,
      samplePage({
        items: [
          chart,
          {
            ...sourceNote,
            footnote_of: chart.id,
          },
          footnote,
        ],
      }),
    ),
    null,
  );
  assert.equal(
    resolveCanonicalNoteLink(
      {
        ...sourceBlock,
        relationship_ids: [footnoteRelationship.id],
      },
      samplePage({ items: [chart, sourceNote, footnote] }),
    ),
    null,
  );

  const duplicateBacklinkOwner: DocumentContentItem = {
    id: "image-2",
    type: "image",
    reading_order: 4,
    source_note_ids: [sourceNote.id],
    layout_source_notes_projected: true,
  };
  assert.equal(
    resolveCanonicalNoteLink(
      sourceBlock,
      samplePage({
        items: [chart, sourceNote, footnote, duplicateBacklinkOwner],
      }),
    ),
    null,
  );

  assert.equal(
    resolveCanonicalNoteLink(
      sourceBlock,
      samplePage({
        items: [
          {
            ...chart,
            footnote_ids: [footnote.id, sourceNote.id],
          },
          sourceNote,
          footnote,
        ],
      }),
    ),
    null,
  );

  const descriptorOnWrongItem = samplePage({
    items: [
      {
        ...chart,
        relationships: [footnoteRelationship],
      },
      sourceNote,
      footnote,
      {
        id: "descriptor-host",
        type: "image",
        reading_order: 4,
        relationships: [sourceRelationship],
      },
    ],
  });
  assert.equal(
    resolveCanonicalNoteLink(sourceBlock, descriptorOnWrongItem),
    null,
  );
});

test("notes remain separate, ordered, and serialized exactly once", () => {
  const page = samplePage({ items: [footnote, sourceNote, chart] });
  const markdown = serializePageMarkdown(page);

  assert.equal(
    markdown,
    `${chart.md}\n\n${sourceNote.md}\n\n${footnote.md}\n`,
  );
  assert.equal(markdown.match(/Aon Catastrophe Insight/g)?.length, 1);
  assert.equal(String(chart.md).includes(String(sourceNote.value)), false);
  assert.equal(
    Number(sourceNote.bbox?.y) >
      Number(chart.bbox?.y) + Number(chart.bbox?.height),
    true,
  );
});

test("legacy and canonical renderers expose escaped note text without interactive targets", () => {
  const legacyRenderer = workspaceSource.slice(
    workspaceSource.indexOf("function ContentItemView"),
    workspaceSource.indexOf("function RenderedPage"),
  );
  const canonicalRenderer = workspaceSource.slice(
    workspaceSource.indexOf("function CanonicalRenderedPage"),
    workspaceSource.indexOf("function MarkdownSource"),
  );

  assert.match(
    legacyRenderer,
    /type === "source_note" \|\| type === "footnote"/,
  );
  assert.match(legacyRenderer, /parsed-note parsed-\$\{type\.replace/);
  assert.match(legacyRenderer, /data-note-id=\{item\.id\}/);
  assert.match(legacyRenderer, /data-note-kind=\{type\}/);
  assert.match(legacyRenderer, /data-note-of=/);

  assert.match(
    canonicalRenderer,
    /resolveCanonicalNoteLink\(block, sourcePage\)/,
  );
  assert.match(
    canonicalRenderer,
    /"parsed-note parsed-source-note"/,
  );
  assert.match(canonicalRenderer, /"parsed-note parsed-footnote"/);
  assert.match(canonicalRenderer, /data-note-id=\{noteLink\?\.note\.id\}/);
  assert.match(canonicalRenderer, /data-note-of=\{noteLink\?\.owner\.id\}/);
  assert.match(
    canonicalRenderer,
    /data-note-relationship-id=\{noteLink\?\.relationship\.id\}/,
  );
  assert.match(canonicalRenderer, /\{block\.text\}/);

  for (const renderer of [legacyRenderer, canonicalRenderer]) {
    assert.doesNotMatch(
      renderer,
      /dangerouslySetInnerHTML|<a\b|\bhref=|\.links\b|\.target\b|\.html\b/,
    );
  }
  assert.match(stylesheetSource, /\.parsed-note\s*\{/);
  assert.match(stylesheetSource, /\.parsed-source-note\s*\{/);
  assert.match(stylesheetSource, /\.parsed-footnote\s*\{/);
});
