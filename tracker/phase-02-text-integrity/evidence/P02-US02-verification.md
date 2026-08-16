# P02-US02 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- Font recovery is enabled only when
  `PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED=true`; it requires the shared
  IR normalization and font-audit flags and remains off by default.
- Recovery is limited to audited indirect Type0/CIDFontType2 fonts with
  `Identity-H`, identity CID-to-GID mapping, an embedded TrueType `FontFile2`,
  one unambiguous Unicode scalar per live glyph, and matching PDF/embedded
  advances.
- Original text, glyphs, font identity, bboxes, and alternatives remain
  attributable. Only uniquely owned native prose is projected as repaired
  primary text; chart recovery remains an unselected alternative for P02-US04.
- The endpoint, schema version, JSON/Markdown serializers, and flag-off legacy
  projection remain compatible.

## Acceptance coverage

1. The exact sentence `Windstorm Éowyn in Ireland and the UK followed with
   $690 million (€620 million).` appears once in projected and canonical
   output.
2. All 24 reviewed catastrophe chart/source regions match their visible truth.
3. All 14 healthy corpus controls short-circuit with zero recovery runs and
   zero rewrites.
4. Non-identity, ambiguous/many-to-one, ligature, missing-program,
   width-mismatch, unsafe-code-point, malformed, bounded-resource, and timeout
   cases fail closed with explicit reason codes.
5. All 150 recovered glyphs have unique evidence IDs and retain original text,
   recovered scalar, font/object/CID/glyph identity, bbox, widths, method, and
   confidence basis.

## Security re-review

The independent code/security re-review approved the final implementation with
no remaining Critical, Major, or Moderate runtime-security findings. It
verified:

- every audit report is bound to the exact recovery PDF SHA-256, and missing or
  mismatched bindings fail closed before eligibility;
- Unicode format controls (`Cf`), including bidi overrides and isolates, are
  refused; an exhaustive probe rejected all 170 Unicode 15.1 `Cf` scalars;
- `hmtx` and cmap retention is scoped to live used glyph IDs;
- cmap state and mappings are bounded, conflicts across trusted subtables
  remain visible, and compact ranges do not force aggregate expansion;
- one document-wide cmap budget is shared across fonts and subtables; and
- deadlines are enforced inside format-4, format-12, subtable, and per-font
  parsing loops.

The reviewer independently observed `recovery_timeout` from a format-4
inner-loop deadline probe and `embedded_cmap_limit` on the second font in a
cross-font aggregate-budget probe.

The review's sole Major closure finding was evidence freshness: the previous
artifact predated the final security fixes. The benchmark was regenerated on
the final code at `2026-07-30T08:27:47.473382+00:00`, after which all retained
artifact tests passed. No further code re-review was required.

## Corpus and performance evidence

The retained runner matched every source SHA-256 to the immutable Phase 0
record and measured 15 cases/30 pages with two warmups and ten samples per
case. Recovery latency includes `recover_pdf_font_text` plus strict report
serialization, with the required audit prepared outside the timed region.
Phase 0 parse records remain historical comparators, not paired full-parser
samples.

| Measure | Result |
|---|---:|
| Deterministic cases | 15/15 |
| Healthy short-circuits / rewrites | 14/14 / 0 |
| Recovered fonts / runs / glyphs | 2 / 29 / 150 |
| Grounded recovered glyphs | 150/150 (100%) |
| Reviewed regions exact | 24/24 |
| Target sentence exact | Pass |
| Catastrophe recovery p50 / p95 / max | 65.336125 / 98.378583 / 98.378583 ms |
| Healthy recovery p50 / p95 / max | 0.081709 / 3.033292 / 3.428667 ms |
| Healthy recovery overhead p50 / p95 / max | 0.001370% / 0.011618% / 0.013133% |
| Conservative audit + recovery healthy p95 ceiling | 2.472635% |
| Maximum isolated peak-RSS increment | 5,242,880 bytes |

Machine-readable per-case, per-font, per-run, and per-glyph evidence is retained
in
[P02-US02-font-recovery-metrics.json](P02-US02-font-recovery-metrics.json),
SHA-256
`7f418317fd93efc320896adc1472b35140fad102abddacc07a4ba51eceec5a39`.

## Test gates

- Focused story, adversarial, contract, regression, corpus, metrics, and
  performance gate after final evidence regeneration: **39 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **800 passed**.
- Complete backend suite: **877 passed, 10 documented opt-in skips**, and one
  existing Starlette/httpx deprecation warning.
- Python compilation: **Pass**.
- Dependency integrity: **Pass**; `pip check` reports no broken requirements.
- Retained JSON parsing and strict retained-evidence assertions: **Pass**.
- Independent code/security re-review: **Pass** after the stale evidence was
  regenerated.
- Independent corpus/correctness/performance review: **Pass**.

The 10 skips are the existing real image-model, Docling/finance sample, and
shared-analysis integration gates, each requiring its documented opt-in
environment variable. No P02-US02 acceptance criterion depends on a skipped
test.

## Dependency and rollback

P02-US01 is Done. Recovery uses the already pinned `pdfminer.six==20260107`
plus Python standard-library TrueType parsing; no new package, model, network
service, or font asset was introduced.

Set `PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED=false` to bypass recovery.
The audit may continue to emit concerns, while native text and the prior public
projection remain unchanged.
