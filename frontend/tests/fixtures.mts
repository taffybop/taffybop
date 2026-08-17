import type {
  CanonicalBlock,
  CanonicalPresentation,
  CanonicalView,
  PageResult,
  ParseResult,
} from "../lib/types.ts";

export const samplePage = (overrides: Partial<PageResult> = {}): PageResult => ({
  page_index: 1,
  page_number: 1,
  page_label: "1",
  page_width: 612,
  page_height: 792,
  unit: "pt",
  success: true,
  warnings: [],
  items: [
    {
      id: "paragraph",
      type: "text",
      reading_order: 2,
      value: "Fallback paragraph",
    },
    {
      id: "heading",
      type: "heading",
      reading_order: 1,
      md: "# A heading",
      value: "Ignored when markdown exists",
    },
  ],
  ...overrides,
});

export const sampleResult = (overrides: Partial<ParseResult> = {}): ParseResult => ({
  schema_version: "1.0",
  document: {
    filename: "sample.pdf",
    mime_type: "application/pdf",
    sha256: "abc123",
    page_count: 1,
  },
  pages: [samplePage()],
  processing: {
    engine: "parser",
    ocr_engine: "ocr",
    ocr_languages: ["eng"],
    duration_ms: 120,
  },
  warnings: [],
  ...overrides,
});

function canonicalView(blocks: CanonicalBlock[]): CanonicalView {
  const included = blocks.filter(
    (block) => (block.omission_reason ?? null) === null,
  );
  const render = (values: string[]) => {
    const present = values.map((value) => value.trim()).filter(Boolean);
    return present.length ? `${present.join("\n\n")}\n` : "";
  };
  return {
    block_ids: included.map((block) => block.id),
    markdown: render(included.map((block) => block.markdown)),
    text: render(included.map((block) => block.text)),
  };
}

export const sampleCanonicalPresentation = (): CanonicalPresentation => {
  // Included blocks intentionally omit both optional null fields. This is the
  // shape emitted by the backend's exclude-none public projection.
  const blocks: CanonicalBlock[] = [
    {
      id: "canonical-header-block",
      page_id: "canonical-page-1",
      primary_element_id: "canonical-header-element",
      primary_element_type: "header",
      scope: "header",
      markdown: "CANONICAL HEADER",
      text: "Canonical header semantic text",
      contributing_element_ids: ["canonical-header-element"],
      relationship_ids: [],
      excluded_contributions: [],
    },
    {
      id: "canonical-body-block",
      page_id: "canonical-page-1",
      primary_element_id: "canonical-body-element",
      primary_element_type: "text",
      scope: "body",
      markdown: "CANONICAL **BODY**",
      text: "Canonical body semantic text",
      contributing_element_ids: ["canonical-body-element"],
      relationship_ids: [],
      excluded_contributions: [],
    },
    {
      id: "canonical-footer-block",
      page_id: "canonical-page-1",
      primary_element_id: "canonical-footer-element",
      primary_element_type: "footer",
      scope: "footer",
      markdown: "CANONICAL FOOTER",
      text: "Canonical footer semantic text",
      contributing_element_ids: ["canonical-footer-element"],
      relationship_ids: [],
      excluded_contributions: [],
    },
  ];
  const full = canonicalView(blocks);
  const body = canonicalView(
    blocks.filter((block) => block.scope === "body"),
  );
  const header = canonicalView(
    blocks.filter((block) => block.scope === "header"),
  );
  const footer = canonicalView(
    blocks.filter((block) => block.scope === "footer"),
  );
  return {
    schema_version: "1.0",
    source_ir_version: "1.0",
    policy_id: "canonical-presentation-v1",
    pages: [
      {
        page_id: "canonical-page-1",
        page_index: 1,
        page_number: 1,
        page_label: "1",
        blocks,
        full,
        body,
        header,
        footer,
      },
    ],
    full,
    body,
    header,
    footer,
  };
};
