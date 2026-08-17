import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { promisify } from "node:util";
import test from "node:test";

import {
  sampleCanonicalPresentation,
  sampleResult,
} from "./fixtures.mts";

const execFileAsync = promisify(execFile);
const captureTool = new URL(
  "../tools/capture-rendered-ui.mjs",
  import.meta.url,
);

test("repository-native capture renders the canonical React UI contract deterministically", async () => {
  const runDir = await mkdtemp(join(tmpdir(), "clearleaf-rendered-capture-"));
  const caseDir = join(runDir, "canonical-case");
  await mkdir(caseDir, { recursive: true });

  const result = sampleResult({
    canonical_presentation: sampleCanonicalPresentation(),
  });
  await writeFile(
    join(caseDir, "response.json"),
    `${JSON.stringify(result, null, 2)}\n`,
    "utf8",
  );

  const runCapture = () =>
    execFileAsync(
      process.execPath,
      [captureTool.pathname, "--run-dir", runDir],
      { cwd: new URL("..", import.meta.url).pathname },
    );

  const first = await runCapture();
  assert.match(first.stdout, /Captured 1 page across 1 case/);
  const capturePath = join(
    caseDir,
    "pages",
    "page-1",
    "rendered-dom.json",
  );
  const firstBytes = await readFile(capturePath, "utf8");
  const payload = JSON.parse(firstBytes);
  assert.deepEqual(Object.keys(payload), ["page_number", "html", "text"]);
  assert.equal(payload.page_number, 1);
  assert.match(payload.html, /^<article class="rendered-page"/);
  assert.match(payload.html, /Canonical body semantic text/);
  assert.doesNotMatch(payload.html, /Canonical header semantic text/);
  assert.doesNotMatch(payload.html, /Canonical footer semantic text/);
  assert.doesNotMatch(payload.html, /Fallback paragraph/);
  assert.equal(payload.text, "Canonical body semantic text");

  await runCapture();
  assert.equal(await readFile(capturePath, "utf8"), firstBytes);

  const manifest = JSON.parse(
    await readFile(join(caseDir, "rendered-capture.json"), "utf8"),
  );
  assert.equal(manifest.schema_version, "clearleaf-rendered-ui-capture-v1");
  assert.equal(manifest.presentation_view, "body");
  assert.equal(manifest.page_count, 1);
  assert.equal(manifest.pages.length, 1);
});

test("canonical capture preserves a uniquely sourced heading level as semantic DOM", async () => {
  const canonical = sampleCanonicalPresentation();
  const canonicalPage = canonical.pages[0];
  const bodyBlock = canonicalPage.blocks.find(
    (block) => block.id === "canonical-body-block",
  );
  assert.ok(bodyBlock);
  bodyBlock.primary_element_type = "heading";
  bodyBlock.markdown = "## Background";
  bodyBlock.text = "Background";
  canonicalPage.body.markdown = "## Background\n";
  canonicalPage.body.text = "Background\n";
  canonical.body.markdown = canonicalPage.body.markdown;
  canonical.body.text = canonicalPage.body.text;
  canonicalPage.full.markdown =
    "CANONICAL HEADER\n\n## Background\n\nCANONICAL FOOTER\n";
  canonicalPage.full.text =
    "Canonical header semantic text\n\nBackground\n\nCanonical footer semantic text\n";
  canonical.full.markdown = canonicalPage.full.markdown;
  canonical.full.text = canonicalPage.full.text;

  const result = sampleResult({
    canonical_presentation: canonical,
    pages: [
      {
        ...sampleResult().pages[0],
        items: [
          {
            id: "public-background-heading",
            type: "heading",
            reading_order: 0,
            level: 2,
            value: "Background",
            md: "## Background",
          },
        ],
      },
    ],
  });
  const runDir = await mkdtemp(join(tmpdir(), "clearleaf-heading-capture-"));
  const caseDir = join(runDir, "source-heading-case");
  await mkdir(caseDir, { recursive: true });
  await writeFile(
    join(caseDir, "response.json"),
    `${JSON.stringify(result, null, 2)}\n`,
    "utf8",
  );
  await execFileAsync(
    process.execPath,
    [captureTool.pathname, "--run-dir", runDir, "--view", "body"],
    { cwd: new URL("..", import.meta.url).pathname },
  );
  const rendered = JSON.parse(
    await readFile(
      join(caseDir, "pages", "page-1", "rendered-dom.json"),
      "utf8",
    ),
  );
  const html = rendered.html;

  assert.match(
    html,
    /<h2 class="parsed-heading parsed-heading-2" data-item-type="heading"[^>]*>Background<\/h2>/,
  );
  assert.doesNotMatch(html, /<p[^>]*>Background<\/p>/);
});

test("canonical capture renders a strong unresolved source grid as a candidate table", async () => {
  const canonical = sampleCanonicalPresentation();
  const canonicalPage = canonical.pages[0];
  const bodyBlock = canonicalPage.blocks.find(
    (block) => block.id === "canonical-body-block",
  );
  assert.ok(bodyBlock);
  bodyBlock.primary_element_id = "source-grid";
  bodyBlock.primary_element_type = "table_candidate";
  bodyBlock.contributing_element_ids = ["source-grid"];
  bodyBlock.markdown =
    '<table><thead><tr><th colspan="3">Weekdays</th></tr>' +
    "<tr><th>Notes</th><th>A</th><th>B</th></tr></thead>" +
    "<tbody><tr><td>Mon</td><td>1:00</td><td>1:05</td></tr></tbody></table>";
  bodyBlock.text = "Weekdays\nNotes\tA\tB\nMon\t1:00\t1:05";
  canonicalPage.body = {
    block_ids: [bodyBlock.id],
    markdown: `${bodyBlock.markdown}\n`,
    text: `${bodyBlock.text}\n`,
  };
  canonical.body = canonicalPage.body;
  canonicalPage.full = {
    block_ids: canonicalPage.blocks.map((block) => block.id),
    markdown: `${canonicalPage.blocks
      .map((block) => block.markdown.trim())
      .join("\n\n")}\n`,
    text: `${canonicalPage.blocks
      .map((block) => block.text.trim())
      .join("\n\n")}\n`,
  };
  canonical.full = canonicalPage.full;

  const result = sampleResult({
    canonical_presentation: canonical,
    pages: [
      {
        ...sampleResult().pages[0],
        items: [
          {
            id: "public-source-grid",
            type: "table_candidate",
            reading_order: 0,
            value: [
              ["Weekdays", "", ""],
              ["Notes", "A", "B"],
              ["Mon", "1:00", "1:05"],
            ],
            rows: [
              ["Weekdays", "", ""],
              ["Notes", "A", "B"],
              ["Mon", "1:00", "1:05"],
            ],
            cells: [],
            row_count: 3,
            column_count: 3,
            table_candidate_gate: {
              outcome: "unresolved",
              owner_item_ids: [],
              feature_scores: { table_support: 0.9 },
            },
            table_candidate_gate_reasons: [
              "upstream_reconciliation_unresolved",
            ],
            table_reconciliation: { outcome: "unresolved" },
          },
        ],
      },
    ],
  });
  const runDir = await mkdtemp(join(tmpdir(), "clearleaf-grid-capture-"));
  const caseDir = join(runDir, "source-grid-case");
  await mkdir(caseDir, { recursive: true });
  await writeFile(
    join(caseDir, "response.json"),
    `${JSON.stringify(result, null, 2)}\n`,
    "utf8",
  );
  await execFileAsync(
    process.execPath,
    [captureTool.pathname, "--run-dir", runDir, "--view", "body"],
    { cwd: new URL("..", import.meta.url).pathname },
  );
  const rendered = JSON.parse(
    await readFile(
      join(caseDir, "pages", "page-1", "rendered-dom.json"),
      "utf8",
    ),
  );

  assert.match(rendered.html, /<table class="parsed-table">/);
  assert.match(rendered.html, /data-table-authority="candidate"/);
  assert.match(rendered.html, /<th colSpan="3">Weekdays<\/th>/);
  assert.match(rendered.html, /<th>Notes<\/th><th>A<\/th><th>B<\/th>/);
  assert.match(
    rendered.html,
    /<td>Mon<\/td><td>1:00<\/td><td>1:05<\/td>/,
  );
  assert.doesNotMatch(rendered.html, /class="parsed-paragraph"/);
});

test("canonical capture renders a relationship-consumed caption with its candidate table", async () => {
  const captionText = "Table 1. Demographic and baseline characteristics.";
  const tableRows = [
    ["Group", "CAU", "SbS+CAU"],
    ["Age M(SD)", "33.98 (10.54)", "33.29 (11.20)"],
    ["Female %(n)", "69.1% (188)", "65.4% (174)"],
  ];
  const tableText = tableRows.map((row) => row.join("\t")).join("\n");
  const candidateText = `${captionText}\n\n${tableText}`;
  const tableMarkdown = '<table><tr><th>Group</th><th>CAU</th><th>SbS+CAU</th></tr><tr><td>Age M(SD)</td><td>33.98 (10.54)</td><td>33.29 (11.20)</td></tr><tr><td>Female %(n)</td><td>69.1% (188)</td><td>65.4% (174)</td></tr></table>';
  const candidateMarkdown = `${captionText}\n\n${tableMarkdown}`;
  const captionRelationship = {
    id: "caption-of-candidate",
    type: "caption_of",
    source_id: "public-caption",
    target_id: "public-candidate",
  };
  const internalCaptionClaimRelationshipId = "internal-caption-claim";
  const internalCaptionEvidenceRelationshipId = "internal-caption-evidence";
  const noteRelationships = [
    {
      id: "footnote-one-of-candidate",
      type: "footnote_of",
      source_id: "public-note-one",
      target_id: "public-candidate",
    },
    {
      id: "footnote-two-of-candidate",
      type: "footnote_of",
      source_id: "public-note-two",
      target_id: "public-candidate",
    },
  ];
  const notes = [
    {
      id: "public-note-one",
      type: "footnote",
      reading_order: 2,
      value: "1 At least 4 out of 5 sessions completed.",
      footnote_of: "public-candidate",
      relationship_id: noteRelationships[0].id,
      relationship_type: "footnote_of",
    },
    {
      id: "public-note-two",
      type: "footnote",
      reading_order: 3,
      value: "2 Less than 4 sessions completed.",
      footnote_of: "public-candidate",
      relationship_id: noteRelationships[1].id,
      relationship_type: "footnote_of",
    },
  ];
  const candidate = {
    id: "public-candidate",
    type: "table_candidate",
    reading_order: 1,
    value: tableRows,
    md: tableMarkdown,
    html: tableMarkdown,
    rows: tableRows,
    cells: [],
    row_count: tableRows.length,
    column_count: tableRows[0].length,
    caption_ids: ["public-caption"],
    footnote_ids: notes.map((note) => note.id),
    source_note_ids: [],
    relationships: [captionRelationship, ...noteRelationships],
    layout_source_notes_projected: true,
    table_candidate_gate: {
      outcome: "unresolved",
      owner_item_ids: [],
      feature_scores: { table_support: 0.9, cell_coverage: 1 },
    },
    table_candidate_gate_reasons: [
      "upstream_reconciliation_unresolved",
    ],
    table_candidate_gate_sources: [],
    table_reconciliation: { outcome: "unresolved" },
  };
  const caption = {
    id: "public-caption",
    type: "caption",
    reading_order: 0,
    value: captionText,
    md: captionText,
    caption_of: candidate.id,
    relationship_id: captionRelationship.id,
    relationship_type: "caption_of",
  };

  const canonical = sampleCanonicalPresentation();
  const canonicalPage = canonical.pages[0];
  const originalBodyBlockIndex = canonicalPage.blocks.findIndex(
    (block) => block.id === "canonical-body-block",
  );
  assert.notEqual(originalBodyBlockIndex, -1);
  const pageId = canonicalPage.page_id;
  const captionBlock = {
    id: "internal-caption-block",
    page_id: pageId,
    primary_element_id: "internal-caption",
    primary_element_type: "caption",
    scope: "body" as const,
    markdown: "",
    text: "",
    contributing_element_ids: [],
    relationship_ids: [
      internalCaptionEvidenceRelationshipId,
      internalCaptionClaimRelationshipId,
    ],
    excluded_contributions: [
      {
        element_id: "internal-candidate",
        reason: "already_claimed" as const,
        relationship_ids: [internalCaptionClaimRelationshipId],
      },
      {
        element_id: "internal-candidate",
        reason: "evidence_only_relationship" as const,
        relationship_ids: [internalCaptionEvidenceRelationshipId],
      },
    ],
    omission_reason: "consumed_by_relationship" as const,
    suppressed_by_element_id: "internal-candidate",
  };
  const candidateBlock = {
    id: "internal-candidate-block",
    page_id: pageId,
    primary_element_id: "internal-candidate",
    primary_element_type: "table_candidate",
    scope: "body" as const,
    markdown: candidateMarkdown,
    text: candidateText,
    contributing_element_ids: ["internal-candidate", "internal-caption"],
    relationship_ids: [
      internalCaptionClaimRelationshipId,
      internalCaptionEvidenceRelationshipId,
    ],
    excluded_contributions: [],
  };
  const noteBlocks = notes.map((note, index) => ({
    id: `internal-note-block-${index + 1}`,
    page_id: pageId,
    primary_element_id: `internal-note-${index + 1}`,
    primary_element_type: "footnote",
    scope: "body" as const,
    markdown: String(note.value),
    text: String(note.value),
    contributing_element_ids: [`internal-note-${index + 1}`],
    relationship_ids: [noteRelationships[index].id],
    excluded_contributions: [],
  }));
  canonicalPage.blocks.splice(
    originalBodyBlockIndex,
    1,
    captionBlock,
    candidateBlock,
    ...noteBlocks,
  );
  const includedBodyBlocks = [candidateBlock, ...noteBlocks];
  canonicalPage.body = {
    block_ids: includedBodyBlocks.map((block) => block.id),
    markdown: `${includedBodyBlocks.map((block) => block.markdown).join("\n\n")}\n`,
    text: `${includedBodyBlocks.map((block) => block.text).join("\n\n")}\n`,
  };
  canonical.body = canonicalPage.body;
  const includedFullBlocks = canonicalPage.blocks.filter(
    (block) => block.omission_reason == null,
  );
  canonicalPage.full = {
    block_ids: includedFullBlocks.map((block) => block.id),
    markdown: `${includedFullBlocks.map((block) => block.markdown).join("\n\n")}\n`,
    text: `${includedFullBlocks.map((block) => block.text).join("\n\n")}\n`,
  };
  canonical.full = canonicalPage.full;

  const result = sampleResult({
    canonical_presentation: canonical,
    pages: [
      {
        ...sampleResult().pages[0],
        items: [caption, candidate, ...notes],
      },
    ],
  });
  const runDir = await mkdtemp(join(tmpdir(), "clearleaf-captioned-grid-capture-"));
  const caseDir = join(runDir, "captioned-grid-case");
  await mkdir(caseDir, { recursive: true });
  await writeFile(
    join(caseDir, "response.json"),
    `${JSON.stringify(result, null, 2)}\n`,
    "utf8",
  );
  await execFileAsync(
    process.execPath,
    [captureTool.pathname, "--run-dir", runDir, "--view", "body"],
    { cwd: new URL("..", import.meta.url).pathname },
  );
  const rendered = JSON.parse(
    await readFile(
      join(caseDir, "pages", "page-1", "rendered-dom.json"),
      "utf8",
    ),
  );

  assert.notEqual(candidateBlock.primary_element_id, candidate.id);
  assert.match(rendered.html, /class="parsed-caption"/);
  assert.match(rendered.html, /data-caption-of="public-candidate"/);
  assert.match(rendered.html, /data-table-authority="candidate"/);
  assert.match(rendered.html, /<table class="parsed-table">/);
  assert.doesNotMatch(
    rendered.html,
    /class="parsed-paragraph" data-item-type="table_candidate"/,
  );
  for (const uniqueVisibleValue of [
    captionText,
    "33.98 (10.54)",
    "69.1% (188)",
    String(notes[0].value),
    String(notes[1].value),
  ]) {
    assert.equal(rendered.html.split(uniqueVisibleValue).length - 1, 1);
  }
  const captionIndex = rendered.html.indexOf(captionText);
  const tableIndex = rendered.html.indexOf('<table class="parsed-table">');
  const noteOneIndex = rendered.html.indexOf(String(notes[0].value));
  const noteTwoIndex = rendered.html.indexOf(String(notes[1].value));
  assert.equal(
    captionIndex >= 0 &&
      captionIndex < tableIndex &&
      tableIndex < noteOneIndex &&
      noteOneIndex < noteTwoIndex,
    true,
  );

  const ambiguousResults = new Map([
    [
      "ambiguous-claim",
      (() => {
        const value = structuredClone(result);
        value.pages[0].items.push({
          ...caption,
          id: "competing-public-caption",
          reading_order: 4,
        });
        return value;
      })(),
    ],
    [
      "ambiguous-backlink",
      (() => {
        const value = structuredClone(result);
        value.pages[0].items.push({
          id: "competing-caption-backlink",
          type: "text",
          reading_order: 4,
          value: "Unrelated public item",
          caption_ids: [caption.id],
        });
        return value;
      })(),
    ],
    [
      "ambiguous-descriptor",
      (() => {
        const value = structuredClone(result);
        value.pages[0].items.push({
          id: "competing-caption-descriptor",
          type: "text",
          reading_order: 4,
          value: "Unrelated public item",
          relationships: [captionRelationship],
        });
        return value;
      })(),
    ],
    [
      "tampered-composite",
      (() => {
        const value = structuredClone(result);
        const presentation = value.canonical_presentation!;
        const tamperedCandidateText = `${captionText}\n${tableText}`;
        const renderedCandidateBlock = presentation.pages[0].blocks.find(
          (block) => block.id === candidateBlock.id,
        );
        assert.ok(renderedCandidateBlock);
        renderedCandidateBlock.text = tamperedCandidateText;
        for (const view of new Set([
          presentation.pages[0].body,
          presentation.pages[0].full,
          presentation.body,
          presentation.full,
        ])) {
          view.text = view.text.replace(candidateText, tamperedCandidateText);
        }
        return value;
      })(),
    ],
    [
      "tampered-markdown",
      (() => {
        const value = structuredClone(result);
        const presentation = value.canonical_presentation!;
        const tamperedCandidateMarkdown = `${candidateMarkdown}\n<!-- tampered -->`;
        const renderedCandidateBlock = presentation.pages[0].blocks.find(
          (block) => block.id === candidateBlock.id,
        );
        assert.ok(renderedCandidateBlock);
        renderedCandidateBlock.markdown = tamperedCandidateMarkdown;
        for (const view of new Set([
          presentation.pages[0].body,
          presentation.pages[0].full,
          presentation.body,
          presentation.full,
        ])) {
          view.markdown = view.markdown.replace(
            candidateMarkdown,
            tamperedCandidateMarkdown,
          );
        }
        return value;
      })(),
    ],
    [
      "weak-candidate-coverage",
      (() => {
        const value = structuredClone(result);
        const owner = value.pages[0].items.find(
          (item) => item.id === candidate.id,
        )!;
        const gate = owner.table_candidate_gate as {
          feature_scores: { cell_coverage: number };
        };
        gate.feature_scores.cell_coverage = 0.749999;
        return value;
      })(),
    ],
    [
      "candidate-owner-source",
      (() => {
        const value = structuredClone(result);
        const owner = value.pages[0].items.find(
          (item) => item.id === candidate.id,
        )!;
        owner.table_candidate_gate_sources = [
          { owner_item_id: "untrusted-owner" },
        ];
        return value;
      })(),
    ],
    [
      "candidate-row-count-mismatch",
      (() => {
        const value = structuredClone(result);
        const owner = value.pages[0].items.find(
          (item) => item.id === candidate.id,
        )!;
        owner.row_count = tableRows.length + 1;
        return value;
      })(),
    ],
  ]);
  for (const [caseId, ambiguousResult] of ambiguousResults) {
    const ambiguousCaseDir = join(runDir, caseId);
    await mkdir(ambiguousCaseDir, { recursive: true });
    await writeFile(
      join(ambiguousCaseDir, "response.json"),
      `${JSON.stringify(ambiguousResult, null, 2)}\n`,
      "utf8",
    );
  }
  await execFileAsync(
    process.execPath,
    [
      captureTool.pathname,
      "--run-dir",
      runDir,
      ...[...ambiguousResults.keys()].flatMap((caseId) => ["--case", caseId]),
      "--view",
      "body",
    ],
    { cwd: new URL("..", import.meta.url).pathname },
  );
  for (const caseId of ambiguousResults.keys()) {
    const ambiguousRendered = JSON.parse(
      await readFile(
        join(runDir, caseId, "pages", "page-1", "rendered-dom.json"),
        "utf8",
      ),
    );
    assert.doesNotMatch(ambiguousRendered.html, /data-table-authority=/);
    assert.match(
      ambiguousRendered.html,
      /class="parsed-paragraph" data-item-type="table_candidate"/,
    );
  }
});

test("canonical table custody presents a covered row exactly once", async () => {
  const runDir = await mkdtemp(join(tmpdir(), "clearleaf-table-custody-capture-"));
  const tableRows = [
    ["Token", "Description"],
    ["NX-17", "Network Exchange"],
    ["RV-4", "Routing Vector"],
  ];
  const tableText = tableRows.map((row) => row.join("\t")).join("\n");
  const tableMarkdown = [
    "| Token | Description |",
    "| --- | --- |",
    "| NX-17 | Network Exchange |",
    "| RV-4 | Routing Vector |",
  ].join("\n");
  const coveredRowText = "NX-17 Network Exchange";

  const resultWithCustody = (includeDetachedBlock: boolean) => {
    const canonical = sampleCanonicalPresentation();
    const canonicalPage = canonical.pages[0];
    const bodyBlock = canonicalPage.blocks.find(
      (block) => block.id === "canonical-body-block",
    );
    assert.ok(bodyBlock);
    bodyBlock.primary_element_id = "owned-source-table";
    bodyBlock.primary_element_type = "table";
    bodyBlock.contributing_element_ids = ["owned-source-table"];
    bodyBlock.markdown = tableMarkdown;
    bodyBlock.text = tableText;

    const detachedBlock = {
      ...bodyBlock,
      id: "detached-copy-block",
      primary_element_id: "detached-source-text",
      primary_element_type: "text",
      contributing_element_ids: ["detached-source-text"],
      markdown: coveredRowText,
      text: coveredRowText,
    };
    if (includeDetachedBlock) {
      const footerIndex = canonicalPage.blocks.findIndex(
        (block) => block.scope === "footer",
      );
      canonicalPage.blocks.splice(footerIndex, 0, detachedBlock);
    }

    const bodyBlocks = includeDetachedBlock
      ? [bodyBlock, detachedBlock]
      : [bodyBlock];
    const renderView = (blocks: typeof bodyBlocks) => ({
      block_ids: blocks.map((block) => block.id),
      markdown: `${blocks.map((block) => block.markdown).join("\n\n")}\n`,
      text: `${blocks.map((block) => block.text).join("\n\n")}\n`,
    });
    canonicalPage.body = renderView(bodyBlocks);
    canonical.body = canonicalPage.body;
    canonicalPage.full = renderView(canonicalPage.blocks);
    canonical.full = canonicalPage.full;

    const items = [
      {
        id: "owned-source-table",
        type: "table",
        reading_order: 0,
        value: tableRows,
        rows: tableRows,
        cells: [],
        row_count: tableRows.length,
        column_count: tableRows[0].length,
        table_candidate_gate: { outcome: "canonical_table" },
      },
      ...(includeDetachedBlock
        ? [
            {
              id: "detached-source-text",
              type: "text",
              reading_order: 1,
              value: coveredRowText,
            },
          ]
        : []),
    ];
    return sampleResult({
      canonical_presentation: canonical,
      pages: [
        {
          ...sampleResult().pages[0],
          items,
        },
      ],
    });
  };

  for (const [caseId, includeDetachedBlock] of [
    ["table-owned", false],
    ["table-plus-detached", true],
  ] as const) {
    const caseDir = join(runDir, caseId);
    await mkdir(caseDir, { recursive: true });
    await writeFile(
      join(caseDir, "response.json"),
      `${JSON.stringify(resultWithCustody(includeDetachedBlock), null, 2)}\n`,
      "utf8",
    );
  }

  const capture = await execFileAsync(
    process.execPath,
    [captureTool.pathname, "--run-dir", runDir, "--view", "body"],
    { cwd: new URL("..", import.meta.url).pathname },
  );
  assert.match(capture.stdout, /Captured 2 pages across 2 cases/);

  const readRendered = async (caseId: string) =>
    JSON.parse(
      await readFile(
        join(runDir, caseId, "pages", "page-1", "rendered-dom.json"),
        "utf8",
      ),
    );
  const owned = await readRendered("table-owned");
  assert.match(
    owned.html,
    /<div class="parsed-table-wrap" data-item-type="table" data-table-authority="canonical">/,
  );
  assert.match(
    owned.html,
    /<tbody><tr><td>NX-17<\/td><td>Network Exchange<\/td><\/tr><tr><td>RV-4<\/td><td>Routing Vector<\/td><\/tr><\/tbody>/,
  );
  assert.equal((owned.html.match(/NX-17/gu) ?? []).length, 1);
  assert.equal((owned.html.match(/Network Exchange/gu) ?? []).length, 1);
  assert.doesNotMatch(owned.html, /class="parsed-paragraph"/);
  assert.equal(
    owned.text,
    "Token\tDescription\nNX-17\tNetwork Exchange\nRV-4\tRouting Vector",
  );

  const detached = await readRendered("table-plus-detached");
  assert.match(
    detached.html,
    /<p class="parsed-paragraph" data-item-type="text"[^>]*>NX-17 Network Exchange<\/p>/,
  );
  assert.equal((detached.html.match(/NX-17/gu) ?? []).length, 2);
  assert.equal((detached.html.match(/Network Exchange/gu) ?? []).length, 2);
});

test("canonical capture keeps typed-owner and weak alternatives out of table UI", async () => {
  for (const [name, gate] of [
    [
      "visual-owner",
      {
        outcome: "visual",
        owner_item_ids: ["chart-owner"],
        feature_scores: { table_support: 0.99 },
      },
    ],
    [
      "weak-unresolved",
      {
        outcome: "unresolved",
        owner_item_ids: [],
        feature_scores: { table_support: 0.609 },
      },
    ],
  ] as const) {
    const canonical = sampleCanonicalPresentation();
    const canonicalPage = canonical.pages[0];
    const bodyBlock = canonicalPage.blocks.find(
      (block) => block.id === "canonical-body-block",
    );
    assert.ok(bodyBlock);
    bodyBlock.primary_element_id = `${name}-private`;
    bodyBlock.primary_element_type = "table_candidate";
    bodyBlock.contributing_element_ids = [`${name}-private`];
    bodyBlock.markdown = "A B C D";
    bodyBlock.text = "A\tB\nC\tD";
    canonicalPage.body = {
      block_ids: [bodyBlock.id],
      markdown: `${bodyBlock.markdown}\n`,
      text: `${bodyBlock.text}\n`,
    };
    canonical.body = canonicalPage.body;
    canonicalPage.full = {
      block_ids: canonicalPage.blocks.map((block) => block.id),
      markdown: `${canonicalPage.blocks
        .map((block) => block.markdown.trim())
        .join("\n\n")}\n`,
      text: `${canonicalPage.blocks
        .map((block) => block.text.trim())
        .join("\n\n")}\n`,
    };
    canonical.full = canonicalPage.full;

    const result = sampleResult({
      canonical_presentation: canonical,
      pages: [
        {
          ...sampleResult().pages[0],
          items: [
            {
              id: `${name}-public`,
              type: "table_candidate",
              reading_order: 0,
              value: [
                ["A", "B"],
                ["C", "D"],
              ],
              rows: [
                ["A", "B"],
                ["C", "D"],
              ],
              cells: [],
              row_count: 2,
              column_count: 2,
              table_candidate_gate: gate,
              table_candidate_gate_reasons:
                gate.outcome === "unresolved"
                  ? ["upstream_reconciliation_unresolved"]
                  : ["typed_visual_owns_region"],
            },
          ],
        },
      ],
    });
    const runDir = await mkdtemp(join(tmpdir(), `clearleaf-${name}-capture-`));
    const caseDir = join(runDir, name);
    await mkdir(caseDir, { recursive: true });
    await writeFile(
      join(caseDir, "response.json"),
      `${JSON.stringify(result, null, 2)}\n`,
      "utf8",
    );
    await execFileAsync(
      process.execPath,
      [captureTool.pathname, "--run-dir", runDir, "--view", "body"],
      { cwd: new URL("..", import.meta.url).pathname },
    );
    const rendered = JSON.parse(
      await readFile(
        join(caseDir, "pages", "page-1", "rendered-dom.json"),
        "utf8",
      ),
    );

    assert.doesNotMatch(rendered.html, /<table class="parsed-table">/);
    assert.doesNotMatch(rendered.html, /data-table-authority=/);
    assert.match(
      rendered.html,
      /class="parsed-paragraph" data-item-type="table_candidate"/,
    );
  }
});
