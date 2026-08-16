# Independent FFD-011 artifact review

Reviewer: `/root/fresh_artifact_review`  
Review date: 2026-08-13  
Role: independent source/Markdown/UI-DOM/JSON and drift reviewer  
Focused attempt verdict: **PASS**  
Overall defect closure verdict: **keep Validating**

The reviewer independently recomputed all 32 targeted assertions as true.

- The archived complete source is byte-identical to the benchmark: 83,589
  bytes, three pages, SHA-256
  `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74`.
- Fresh LlamaParse job `pjb-frndkxx9xo4bww7bjg78oxfvhqqe` was created after
  the attempt began, completed all three pages, and preserved raw Markdown that
  is byte-identical to the selected reference. Raw LlamaParse JSON is data-
  identical after removing only the new `.job` object and the six newly issued
  expiring `presigned_url` values.
- Service raw/canonical Markdown compares byte-for-byte. Its complete pre/post
  Markdown difference is only removal of the detached FERS paragraph. The full
  public JSON independently validates through `ParseResult` with three pages.
- Actual Clearleaf page-1 article DOM contains 40 table rows, exactly one FERS
  cell pair, one introductory paragraph, and zero detached FERS, CARES, or
  Exchange paragraphs. Actual LlamaParse table DOM likewise contains 40 rows
  and one FERS pair. Visual inspection of the source, Clearleaf affected
  capture, and LlamaParse affected capture agrees.
- All six referenced LlamaParse assets exist and match their retained hashes.
  Fifteen nonempty screenshot captures are inventoried; browser-supplied JPEG
  bytes are intentionally preserved under their original `.png` filenames.
- Service page-2/page-3 public table objects are data-identical to the selected
  baseline. All 39 glossary rows retain content and order; CIO is exact. False
  `ClO` is absent from visible/public projections while its rejected diagnostic
  occurrence remains intentionally attributable in processing provenance.
- Two FERS suppression records retain their shared row-39 owner, both stable
  cell IDs, point bboxes, source/evidence IDs, the safe source line, `1.0`
  content/source-character coverage, and reason
  `table_owned_complete_source_line_duplicate`.
- Service JSON drift consists of target removal, deterministic item/IR identity
  repair, timing/running-region dependent identities, and the new contributor/
  suppression ledger. Pages 2 and 3 are unchanged. Fresh LlamaParse full DOM
  is additive because selected retained HTML was empty; semantic/a11y content
  differs only in job crumb, quota, zoom, and active UI state. No unexpected
  material target or declared-collateral change was found.

The reviewer independently reran the three named P04 controls without cache;
the result was `3 failed in 77.08s`, exactly on missing `table_evidence` or
`canonical_source_custody`. Their configuration leaves
`text_integrity_source_alignment_enabled` false, so the FFD-011 aligner cannot
execute. The fixed P04 five-second resource budget and rollback explain the
failures, and visible table content remains predecessor-exact. They are not
FFD-011 regressions, but they remain current red named controls and therefore
block the user's literal “all controls pass” closure gate.

Recommended disposition: preserve this immutable attempt as an immediate
targeted pass, keep FFD-011 `Validating`, and do not expand this implementation
slice into repairing P04. The stale P02 retained-artifact hash assertion is
also nonbehavioral and pre-existing; the three named P04 controls are the
decisive closure blocker.

