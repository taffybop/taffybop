import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CanonicalPresentationError,
  readCanonicalPresentation,
} from "../lib/canonical-presentation.ts";
import { normalizeDocumentJson } from "../lib/normalize-document-json.ts";
import { serializeDocumentMarkdown } from "../lib/serialize-output.ts";
import type {
  CanonicalPresentation,
  ParseResult,
} from "../lib/types.ts";
import {
  sampleCanonicalPresentation,
  sampleResult,
} from "./fixtures.mts";

function withCanonical(value: unknown): ParseResult {
  return {
    ...sampleResult(),
    canonical_presentation: value,
  } as unknown as ParseResult;
}

function replaceBodyMarkdown(
  canonical: CanonicalPresentation,
  markdown: string,
): void {
  const page = canonical.pages[0];
  const [header, body, footer] = page.blocks;
  body.markdown = markdown;
  const fullMarkdown = [
    header.markdown,
    body.markdown,
    footer.markdown,
  ].join("\n\n");
  page.full.markdown = `${fullMarkdown}\n`;
  page.body.markdown = `${body.markdown}\n`;
  canonical.full.markdown = `${fullMarkdown}\n`;
  canonical.body.markdown = `${body.markdown}\n`;
}

function omitBodyAsSourceContradictedOcr(
  canonical: CanonicalPresentation,
  primaryElementType: string,
): void {
  const page = canonical.pages[0];
  const [header, body, footer] = page.blocks;
  body.primary_element_type = primaryElementType;
  body.markdown = "";
  body.text = "";
  body.contributing_element_ids = [];
  body.relationship_ids = [];
  body.excluded_contributions = [];
  body.omission_reason = "source_contradicted_primary_ocr";
  body.suppressed_by_element_id = null;

  page.full = {
    block_ids: [header.id, footer.id],
    markdown: `${header.markdown}\n\n${footer.markdown}\n`,
    text: `${header.text}\n\n${footer.text}\n`,
  };
  page.body = { block_ids: [], markdown: "", text: "" };
  canonical.full = structuredClone(page.full);
  canonical.body = structuredClone(page.body);
}

test("canonical absence alone selects the unchanged legacy fallback", () => {
  const result = sampleResult();

  assert.equal(readCanonicalPresentation(result), null);
  assert.equal(
    serializeDocumentMarkdown(result),
    "# A heading\n\nFallback paragraph\n",
  );
  assert.equal(
    "canonical_presentation" in normalizeDocumentJson(result),
    false,
  );
});

test("backend exclude-none canonical shape validates without materialization", () => {
  const canonical = sampleCanonicalPresentation();
  const firstBlock = canonical.pages[0].blocks[0];
  const result = withCanonical(canonical);
  const before = structuredClone(result);

  assert.equal("omission_reason" in firstBlock, false);
  assert.equal("suppressed_by_element_id" in firstBlock, false);
  assert.equal(readCanonicalPresentation(result), canonical);
  assert.deepEqual(result, before);
  assert.equal("omission_reason" in firstBlock, false);
  assert.equal("suppressed_by_element_id" in firstBlock, false);
});

test("present null, partial, and unsupported canonical contracts fail closed", () => {
  const invalidValues: unknown[] = [
    null,
    undefined,
    {},
    {
      ...sampleCanonicalPresentation(),
      schema_version: "2.0",
    },
    {
      ...sampleCanonicalPresentation(),
      source_ir_version: "2.0",
    },
    {
      ...sampleCanonicalPresentation(),
      policy_id: "future-policy",
    },
  ];

  for (const value of invalidValues) {
    const result = withCanonical(value);
    assert.throws(
      () => readCanonicalPresentation(result),
      CanonicalPresentationError,
    );
    assert.throws(
      () => serializeDocumentMarkdown(result),
      CanonicalPresentationError,
      "malformed canonical data must never fall back to legacy items",
    );
  }
});

test("bad nested keys and page, block, or view references fail closed", () => {
  const mutations: Array<
    (presentation: CanonicalPresentation) => void
  > = [
    (presentation) => {
      (
        presentation.pages[0].blocks[0] as unknown as Record<
          string,
          unknown
        >
      ).unexpected = true;
    },
    (presentation) => {
      presentation.pages[0].blocks[0].page_id = "another-page";
    },
    (presentation) => {
      presentation.pages[0].full.block_ids = ["missing-block"];
    },
    (presentation) => {
      presentation.pages[0].full.markdown = "divergent\n";
    },
    (presentation) => {
      presentation.full.block_ids = ["missing-document-block"];
    },
    (presentation) => {
      presentation.pages[0].page_index = 2;
    },
  ];

  for (const mutate of mutations) {
    const canonical = structuredClone(sampleCanonicalPresentation());
    mutate(canonical);
    assert.throws(
      () => readCanonicalPresentation(withCanonical(canonical)),
      CanonicalPresentationError,
    );
  }
});

test("optional block nulls are accepted and preserved exactly", () => {
  const canonical = sampleCanonicalPresentation();
  canonical.pages[0].blocks[0].omission_reason = null;
  canonical.pages[0].blocks[0].suppressed_by_element_id = null;
  const before = structuredClone(canonical);

  const result = withCanonical(canonical);

  assert.equal(readCanonicalPresentation(result), canonical);
  assert.deepEqual(canonical, before);
  assert.equal(
    Object.prototype.hasOwnProperty.call(
      canonical.pages[0].blocks[0],
      "omission_reason",
    ),
    true,
  );
});

test("source-contradicted OCR is retained as a raw block but omitted from canonical output", () => {
  for (const primaryElementType of ["text", "heading", "TEXT", "Heading"]) {
    const canonical = sampleCanonicalPresentation();
    omitBodyAsSourceContradictedOcr(canonical, primaryElementType);
    const result = withCanonical(canonical);
    result.pages[0].items = [
      {
        id: "canonical-body-element",
        type: primaryElementType,
        reading_order: 0,
        value: "OCR artifact retained for inspection",
        md: "OCR artifact retained for inspection",
      },
    ];

    assert.equal(readCanonicalPresentation(result), canonical);
    assert.equal(
      result.pages[0].items[0].value,
      "OCR artifact retained for inspection",
    );
    assert.equal(
      canonical.pages[0].blocks[1].omission_reason,
      "source_contradicted_primary_ocr",
    );
    assert.deepEqual(canonical.pages[0].full.block_ids, [
      "canonical-header-block",
      "canonical-footer-block",
    ]);
    assert.deepEqual(canonical.pages[0].body.block_ids, []);
    assert.equal(
      serializeDocumentMarkdown(result),
      "CANONICAL HEADER\n\nCANONICAL FOOTER\n",
    );
    const normalized = normalizeDocumentJson(result);
    assert.equal(
      normalized.items.pages[0].items[0].value,
      "OCR artifact retained for inspection",
    );
    assert.equal(
      normalized.markdown_full,
      "CANONICAL HEADER\n\nCANONICAL FOOTER\n",
    );
  }
});

test("source-contradicted OCR omission enforces its exact intrinsic block shape", () => {
  const mutations: Array<(canonical: CanonicalPresentation) => void> = [
    (canonical) => {
      canonical.pages[0].blocks[1].primary_element_type = "table";
    },
    (canonical) => {
      canonical.pages[0].blocks[1].markdown = "leaked OCR";
    },
    (canonical) => {
      canonical.pages[0].blocks[1].text = "leaked OCR";
    },
    (canonical) => {
      canonical.pages[0].blocks[1].contributing_element_ids = [
        "canonical-body-element",
      ];
    },
    (canonical) => {
      canonical.pages[0].blocks[1].suppressed_by_element_id =
        "canonical-header-element";
    },
    (canonical) => {
      canonical.pages[0].blocks[1].relationship_ids = ["unexpected-rel"];
    },
    (canonical) => {
      canonical.pages[0].blocks[1].excluded_contributions = [
        {
          element_id: "unexpected-element",
          reason: "rejected_ocr",
          relationship_ids: [],
        },
      ];
    },
  ];

  for (const mutate of mutations) {
    const canonical = sampleCanonicalPresentation();
    omitBodyAsSourceContradictedOcr(canonical, "text");
    mutate(canonical);
    assert.throws(
      () => readCanonicalPresentation(withCanonical(canonical)),
      CanonicalPresentationError,
    );
  }
});

test("empty relational suppressors fail closed even if an empty ID is presented", () => {
  const canonical = sampleCanonicalPresentation();
  const owner = canonical.pages[0].blocks[1];
  owner.primary_element_id = "";
  owner.contributing_element_ids = [""];
  canonical.pages[0].blocks.push({
    id: "empty-suppressor-alternate",
    page_id: canonical.pages[0].page_id,
    primary_element_id: "alternate-element",
    primary_element_type: "text",
    scope: "body",
    markdown: "",
    text: "",
    contributing_element_ids: [],
    relationship_ids: ["alternate-rel"],
    excluded_contributions: [
      {
        element_id: "",
        reason: "alternate_representation",
        relationship_ids: ["alternate-rel"],
      },
    ],
    omission_reason: "alternate_representation",
    suppressed_by_element_id: "",
  });

  assert.throws(
    () => readCanonicalPresentation(withCanonical(canonical)),
    CanonicalPresentationError,
  );
});

test("outer whitespace follows Python strip semantics at the contract boundary", () => {
  const nextLine = sampleCanonicalPresentation();
  replaceBodyMarkdown(nextLine, "\u0085CANONICAL **BODY**");
  assert.throws(
    () => readCanonicalPresentation(withCanonical(nextLine)),
    CanonicalPresentationError,
    "Python strips U+0085, so an outer U+0085 must fail validation",
  );

  const byteOrderMark = sampleCanonicalPresentation();
  replaceBodyMarkdown(byteOrderMark, "\ufeffCANONICAL **BODY**");
  assert.equal(
    readCanonicalPresentation(withCanonical(byteOrderMark)),
    byteOrderMark,
    "Python does not strip U+FEFF, so it remains canonical content",
  );
});
