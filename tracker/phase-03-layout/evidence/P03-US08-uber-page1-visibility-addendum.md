# P03-US08 Uber page-1 visibility addendum

Date: 2026-08-01  
Status: Readiness source-truth correction  
Scope: `uber-earnings.pdf`, physical page 1, predecessor item `p1-i4`

## Source custody

- Path: `benchmark-expertmodeldata/uber-earnings.pdf`
- Bytes: 7,584,019
- SHA-256: `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`
- Pages: 3
- Displayed page-1 dimensions: 1,920 × 1,080 points

No Phase 00–02 source, annotation, or retained evidence was changed. This
addendum corrects only the proposed P03-US08 interpretation before its oracle
was sealed.

## Finding

The PDF text layer contains character index 69 / word index 11 with text `1`
at top-left bbox `[1841.616, 1025.407, 7.884, 18.0]` points. Its
`non_stroking_color` is `(0.9999966, 1.0, 1.0)`, effectively white.

A pypdfium2 RGB render of that exact bbox at 4 pixels/point is 32 × 72 = 2,304
pixels. Every pixel is `(255, 255, 255)`; channel extrema are
`((255,255),(255,255),(255,255))`. The glyph therefore has no composited
source-visible mark on the white page.

Controls on the same source are visible:

| Physical page | Text | Exact bbox render | Pixels differing from modal RGB by at least 16 in any channel |
|---:|---:|---:|---:|
| 1 | hidden `1` | 32 × 72 | 0 |
| 2 | visible `5` | 30 × 56 | 457 |
| 3 | visible `6` | 33 × 56 | 512 |

An exhaustive 4-pixel/point sweep found non-uniform rendered pixels for every
other one of the 27 reviewed printed-label bboxes. Uber page 1 was the sole
uniform crop and sole near-white native fill.

## Corrected decision

- Uber physical page 1 has `detected_printed_label = null`, no label candidate,
  and no accepted running region for `p1-i4`.
- Its unchanged safe legacy `page_label = "1"` supplies
  `display_source = legacy_display_fallback`; physical navigation remains page
  index 1.
- Uber pages 2 and 3 retain detected labels `5` and `6`.
- The full reviewed denominator is corrected from 28 labels / 2 nulls / 48
  running regions to 27 labels / 3 nulls / 47 running regions.
- The generic implementation contract must reject transparent, unpainted, or
  zero-contrast text-layer candidates and must retain a visible light-on-dark
  positive. In v1, the candidate must intersect a positive-area PDFium text
  object selected by exact label text plus local geometry, in fill-painting
  mode `0`, `2`, `4`, or `6`, with fill alpha greater than zero. DeviceGray/
  RGB custody is exact; DeviceCMYK admits only the frozen bidirectional
  36-channel conversion bound while PDFium RGB remains authoritative for
  contrast. A filename, source hash, fixed public ID, or case-specific
  exception is forbidden.

## Executable custody

The real-source regression in
`tests/stories/phase_03/test_p03_us08_running_regions.py` rechecks the native
character, fixed render, corrected null identity, empty page-1 source
candidates, absence from the accepted running-region ledger, and visible
page-2/page-3 controls. The corrected oracle remains unsealed until the generic
visibility contract and independent review pass.
