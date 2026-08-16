# Phase 01 — Shared Intermediate Representation

Status: Complete — 4/4 stories and 20/20 points Done; exit criteria Pass  
Outcome: A versioned evidence graph and one canonical presentation contract

## Entry criteria

- Phase 00 exit gate passed.
- Additive versus versioned public-schema policy is decided.

## Exit criteria

- Elements retain evidence, relationships, provenance, and confidence dimensions.
- Normalization does not flatten captions, children, or alternatives.
- Caption, source-note, footnote, link-annotation, header/footer, and visual-region
  ownership remains explicit even when presentation order differs from geometry.
- Element-, child-, and field-level bboxes use declared units/transforms and do
  not imply grounding for text outside their regions.
- JSON, Markdown, and text use one canonical presentation contract.
- Full-document, page-body, header/footer, item Markdown, and alternate
  representations have declared inclusion rules; one semantic element is not
  serialized twice.
- Existing v1 API clients pass compatibility tests.

## Stories

1. [P01-US01](stories/P01-US01.md) — Introduce versioned evidence and relationship IR
2. [P01-US02](stories/P01-US02.md) — Normalize elements without flattening evidence
3. [P01-US03](stories/P01-US03.md) — Generate canonical presentation blocks
4. [P01-US04](stories/P01-US04.md) — Enforce backend/frontend serialization parity
