# P02-US03 Verification Evidence

Date: 2026-07-30  
Status: Pass

## Scope and compatibility

- Selective span OCR is enabled only when
  `PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED=true`; it requires shared
  IR normalization, font audit, font recovery, and PDF visual analysis, and is
  off by default.
- Only exact-source audited runs with explicit, semantically consistent
  recovery refusals authorize a render. Healthy or safely recovered neighbors
  never become OCR authority.
- OCR candidates remain unselected alternatives with source/refusal/span,
  geometry, pass, engine, language, confidence, and cost provenance.
- Canonical and legacy JSON/text/Markdown remain unchanged until P02-US04
  performs evidence-ranked reconciliation.

## Acceptance coverage

1. All 4 audited unresolved catastrophe target runs produced only their bounded
   three-point-padded crops; broad-page render count was zero.
2. All 25 healthy same-page neighbors and all 14 healthy corpus controls
   produced zero selective render calls, spans, pixels, or area.
3. All 4 real candidates and 4 real tokens retained unique evidence IDs and
   complete bbox, exact affine, realized crop, DPI, pixel, pass, confidence,
   versioned engine/language, elapsed, and cost evidence.
4. Pre-allocation and realized pixel/area bounds, target limits, document and
   crop deadlines, unavailable/failed OCR, malformed geometry/output,
   contradictory provenance, oversized IPC, and child termination fail softly
   without replacing native evidence.
5. Direct-image, direct-raster, and rendered-PDF OCR share typed line, token,
   and pass evidence. Strict selective geometry stays private to selective
   requests, preserving ordinary flag-off projection behavior.

## Independent security and correctness review

The refreshed final review approved the implementation with no blocking or
major findings. It independently verified:

- exact single-padding, quantized PDFium dimensions and affine transforms, plus
  a pre-allocation pixel guard;
- planned and realized pixel/area/deadline accounting;
- truthful pass and cost evidence on post-render failures;
- exact audit/recovery/PDF identity and semantic refusal provenance checks;
- bounded IPC, full-message receive deadlines, bounded child output, and POSIX
  process-group termination;
- default-off, legacy, and canonical presentation parity; and
- a real PDFium plus pinned local Tesseract benchmark path.

The reviewer recorded non-blocking hardening debt for future production
hardening: live-cap Tesseract temporary-file growth, add a child-process memory
ceiling/selective TSV parse cap, and reconcile the 512 retained-outcome limit
with unusually large audits. None changes the accepted bounded routing or
current story criteria.

## Corpus and performance evidence

The retained runner matched all 15 source SHA-256 identities to immutable Phase
0 records and used two warmups plus ten measured samples per scenario. Audit
and recovery preparation are outside the selective component timing. The
deterministic target and failure lanes use controlled render doubles; a
separately labeled series exercises production PDFium and local Tesseract
5.5.3 with the exact accepted English trained-data asset. The target uses the
actual catastrophe corpus PDF with a deterministic test-only recovery-refusal
variant; it is not a naturally unresolved production report.

| Measure | Result |
|---|---:|
| Exact source bindings | 15/15 |
| Deterministic scenarios | 16/16 |
| Unresolved target terminal coverage | 8/8 (100%) |
| Healthy controls / rendered controls | 14 / 0 |
| Healthy same-page neighbors / rendered neighbors | 25 / 0 |
| Real rendered spans / candidates / tokens | 4 / 4 / 4 |
| Real rendered pixels / area | 23,954 / 958.16 pt² |
| Real target page-area ratio | 0.197679% |
| Real isolated OCR p50 / p95 / max | 1758.404 / 2140.842 / 2140.842 ms |
| Healthy planning p50 / p95 / max | 0.085 / 2.842 / 2.946 ms |
| Healthy planning overhead p50 / p95 / max | 0.001390% / 0.010887% / 0.011284% |
| Conservative audit + recovery + selective p95 ceiling | 2.483522% |
| Maximum isolated peak-RSS increment | 60,178,432 bytes |

The cumulative ceiling is an arithmetic reference across independently
measured components, not a paired full-parser percentile.

The OCR binding is Tesseract 5.5.3 with `eng.traineddata` size 4,113,088 bytes
and SHA-256
`7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.

Machine-readable routing, failure, candidate/token, affine, cost, timing, RSS,
environment, and source-binding evidence is retained in
[P02-US03-selective-span-ocr-metrics.json](P02-US03-selective-span-ocr-metrics.json),
SHA-256
`1e6af0c9354b7357bb1a09c0c9a2b3b832d2cd70a3169977b8259d61e111b074`.

## Test gates

- Final focused story, contract, regression, and performance gate:
  **62 passed**.
- Complete Phase 0–2 story, contract, regression, and performance gate:
  **862 passed**.
- Complete backend suite: **939 passed, 10 documented opt-in skips**, and one
  existing Starlette/httpx deprecation warning.
- Python compilation: **Pass**.
- Dependency integrity: **Pass**; `pip check` reports no broken requirements.
- Retained JSON parsing and strict retained-evidence assertions: **Pass**.
- Independent final security/correctness review: **Pass**.

The 10 skips are the existing real image-model, Docling/finance sample, and
shared-analysis integration gates, each requiring its documented opt-in
environment variable. No P02-US03 acceptance criterion depends on a skipped
test.

## Dependency and rollback

P02-US02 is Done. No new Python package, hosted service, model, or network
dependency was added. The accepted runtime is local Tesseract 5.5.3 with its
hash-bound English asset under Apache-2.0; runtime download is prohibited.

Set `PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED=false` to bypass selective
OCR. Font audit/recovery and native evidence may continue, while the prior
canonical and legacy projection remain unchanged.
