# Decision: amend the FFD-014 Clinical page-one release slice

Date: **2026-08-14**  
Status: **Accepted for the active FFD-014 slice**

## Decision

The requester authorized a bounded, page-at-a-time Clinical correction and
then supplied explicit physical-page-1 review feedback. For that page only,
the release projection must preserve source-visible content and convey it in a
logically correct order even when its presentation is not pixel-identical to
LlamaParse. Production decisions must remain reusable for unseen PDFs.

This decision therefore supersedes only the earlier FFD-014 page-one
expectations that required the existing visual placeholder to remain exact and
prohibited page-one text, heading, or reading-order changes. The corrected
page-one boundary is:

1. present the source header `PLOS MEDICINE` and source label
   `RESEARCH ARTICLE`;
2. keep the title, authors, affiliations, and author email in the primary
   preamble;
3. present attributable `Check for updates` and `OPEN ACCESS` visual labels,
   rather than an empty image placeholder, after the email and before the
   citation column;
4. preserve the remainder of the source-proven body order; and
5. present the footer with its source word boundary, DOI, date, and printed
   page identity.

Those literals identify the reviewed oracle only. They are prohibited as
production activation rules. The implementation must decide from source
lineage, complete character coverage, page/unit-consistent geometry, visual
ownership, bounded OCR agreement, and deterministic layout structure. Missing,
conflicting, independently owned, malformed, or ambiguous evidence must retain
the attributable predecessor and a concern; it must not be silently deleted.

## Story corrections

- P03-US04 acceptance criterion 3's Clinical-specific deletion of the fused
  `RESEARCHARTICLE` suffix is superseded. The source-visible contribution is
  now retained as its own source-proven item when and only when a closed fused-
  text partition is established. With incomplete lineage the fused predecessor
  remains unchanged.
- P03-US08 acceptance criterion 7's interactive default is corrected from
  Body to Full. Body remains an explicit user-selectable view. The selected
  view continues to drive render, source, copy, and page download, while the
  compatibility/document serializer continues to use stored Full semantics.
  The exact renewal is recorded in
  [`P03-US08-interactive-full-default-correction-renewal.md`](../../phase-03-layout/decisions/P03-US08-interactive-full-default-correction-renewal.md).
- P03-US02 may present a visual's own source/native or compact-OCR label only
  under closed owner, geometry, source-character, and contributor proof. This
  does not authorize generated image descriptions or unrelated visual OCR.

All earlier text remains immutable history and is superseded only to the
extent stated here.

## Limits and non-closure

- No Clinical physical-page-2 source inspection, oracle expansion, or
  page-2-specific remediation is authorized or claimed.
- Production remains at **5.0 seconds per document** and **0.500 seconds per
  page**. The one 10-second document setting was a test-only diagnostic and is
  not a production setting, API switch, environment option, release result, or
  closure exception. Root-cause and budget/performance work remains future
  work.
- The bounded page-one release projection may pass while P04 terminal table
  custody remains red. In that state FFD-014 remains `In Progress` and FFD-011
  remains `Blocked`.
- This decision starts or closes no other defect. It does not change FFD-012
  or FFD-013, waive the NY P04 control, replace the Wave A all-15 drift gate,
  or replace the final frozen all-15 campaign.

## Bounded result

The final page-one integration passed `1/1` in 28.89 seconds. A fresh HTTP 200
response independently validates through the public model, and the repository-
native Clearleaf Full renderer presents the required page-one sequence and the
spaced footer. The browser shell reached Ready, but Chrome file-upload
permission prevented a second interactive upload; the renderer consumed the
fresh HTTP response directly. This is a bounded page-one release pass, not a
dual-system defect closure bundle.

The latest observed production-5-second and test-only-10-second P04 custody
runs both lacked `canonical_source_custody`. They predate the final footer-
replay patch and were not rerun afterward, so they are retained as unresolved
current-slice observations rather than described as settled current-candidate
failures or passes. FFD-014 is consequently `In Progress`.
