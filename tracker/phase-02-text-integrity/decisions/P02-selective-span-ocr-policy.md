# P02 Selective Span OCR Policy

Status: Accepted  
Date: 2026-07-30  
Applies to: P02-US03 through P02-US06

## Context

The parser already uses the same local Tesseract implementation for direct
images, embedded PDF image regions, and selected PDF page renders. P02-US03
adds a narrower lane for font spans that P02-US02 explicitly refuses to
recover. That lane needs fixed routing, resource, coordinate, evidence,
dependency, and failure contracts before implementation.

The retained Phase 0 environment and the current reference environment use
Tesseract 5.5.3. The configured language is `eng`; `osd` and `snum` are
installed but are not requested by the parser. The current reference
`eng.traineddata` is 4,113,088 bytes with SHA-256
`7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`.
The installed Tesseract distribution and local license file declare
Apache-2.0. P02-US03 introduces no new OCR engine, language, model, network
service, or package.

## Routing decision

- “Unresolved span” means an affected run belonging to a font with an explicit
  P02-US02 refusal. A safe recovered font, a healthy/unused font, and an
  unselected-but-safe font alternative are not OCR escalation authority.
- The exact PDF SHA-256 in the audit must match the rendered PDF before any
  bbox is trusted.
- Each distinct unresolved audit run receives one bounded crop or one terminal
  reason-coded concern. This terminal-outcome denominator defines 100% routing
  coverage.
- Identical targets may be deduplicated. Nearby spans are not merged or widened
  into a page or broad line region.
- Healthy neighboring spans and healthy control documents never create
  selective requests.
- Selective results remain separate from the existing `image_regions` primary
  analysis lane. P02-US03 records alternatives only; P02-US04 owns selection.

## Render and resource bounds

The reference policy is:

| Bound | Value |
|---|---:|
| Target render scale | 5 pixels/point (360 DPI) |
| Crop padding | 3 points on each side, clipped only at page edges |
| Maximum pixels per crop | 4,000,000 |
| Maximum targets per page / document | 16 / 64 |
| Maximum rendered pixels per document | 32,000,000 |
| Maximum cumulative selective area per page | 5% |
| Aggregate render/OCR timeout per crop | 30 seconds |
| Aggregate selective-OCR deadline | 60 seconds |
| Retained candidates per crop | 256 |
| Retained tokens per crop | 2,048 |
| Retained concerns/diagnostics | 256 |

Source bboxes must be finite, positive, in top-left PDF-point page space, and
fully intersect the declared page. Invalid/off-page source geometry is
rejected; only padding is clipped. Pixel estimates are computed before PDFium
allocation. Work that exceeds a pixel, target, page-area, document-pixel, or
deadline bound is refused rather than silently downscaled.

No OCR engine or language asset may be downloaded at runtime. The Docker/native
package version is not yet reproducibly pinned, so acceptance and retained
metrics bind the reference executable version and English asset digest above;
P08-US08 remains responsible for the production artifact manifest.

## Coordinate and evidence contract

Every attempted target records:

- source and padded crop bboxes;
- page size, coordinate unit, and edge-clipping state;
- requested/actual scale and DPI;
- actual pixel width, height, and count;
- crop-pixel-to-page-point and inverse affine transforms;
- OCR pass/PSM, confidence, line/token bboxes, method, and language;
- render/OCR elapsed time, timeout budget, and terminal status; and
- audit/recovery/font/run provenance and stable evidence identity.

Transforms are derived from actual raster dimensions and must round-trip crop
corners within tolerance. Transform mismatch discards projected OCR candidates
and emits a concern.

Direct-image and PDF-render OCR use the same typed line/token evidence
contract. Input adapters differ only in coordinate unit, crop metadata, and
transform.

## Failure and compatibility policy

Pixel/time limits, invalid transforms, unavailable/disappearing Tesseract,
malformed OCR output, and OCR failures are soft failures for this selective
lane: native/font evidence remains and the terminal concern is retained.
The endpoint's existing initial Tesseract availability requirement is unchanged;
the selective lane also handles loss/failure after that preflight and is
directly testable as a soft-fail component.

Flag-on output may add versioned selective-OCR candidates, tokens, costs, and
concerns to internal IR and optional legacy-item diagnostics. It must not
change primary value, Markdown, reading order, source, or canonical
presentation until P02-US04. Flag-off output remains byte-equivalent to the
P02-US02 path.

## Feature flag and rollback

`parser.text_integrity.selective_span_ocr.enabled` /
`PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED` is default off and requires:

- `PARSER_SHARED_IR_ENABLED=true`;
- `PARSER_SHARED_IR_NORMALIZATION_ENABLED=true`;
- `PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED=true`; and
- `PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED=true`; and
- `PDF_VISUAL_ANALYSIS_ENABLED=true`.

Disable the selective flag to remove all new render work and diagnostics while
retaining P02-US01 audit, P02-US02 recovery, and native text.
