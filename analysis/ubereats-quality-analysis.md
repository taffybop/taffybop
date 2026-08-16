# Image-parsing quality analysis: Uber earnings cover

## Executive finding

The main quality problem was not image-region detection. The current Docling
layout pass located the photograph within roughly one pixel of the visible
region. The failures were introduced later: unfiltered Tesseract candidates
were promoted into the visual item, spacing variants were not reconciled
against layout text, recovered OCR bypassed heading classification, and the
serializer treated image-level OCR as document prose.

The implemented changes are image-specific and additive. They preserve the
existing endpoint and response fields, retain raw/rejected OCR for diagnostics,
and do not alter the PDF conversion branch. The supplied image now has clean
primary text and Markdown. A real semantic caption is supported only when an
optional local vision-language model is explicitly enabled and available; the
model is not installed in the configured artifacts directory, so the verified
after-output uses a truthful placeholder rather than fabricating a description.

This is not a claim of benchmark-level parity. It is a verified improvement on
the supplied fixture plus a varied local regression set.

## Ground truth used

The 600×800 source PNG—not either JSON—was treated as ground truth.

Verified primary document text:

1. `Uber Technologies, Inc.`
2. `May 7, 2025`
3. `Q1 2025 Earnings`
4. `Supplemental Data`

The photograph occupies approximately `(48, 267, 504, 148)` px. It visibly
contains a green Uber Eats bag among plants/foliage near an entrance. `Uber
Eats` is visible inside the photograph and is photo-level text, not ordinary
page prose. “Flowers on a doorstep” is a plausible model interpretation, but
it is not a verbatim fact that should be inserted without model provenance.

## Pre-change comparison

| Area | Current output before changes | Expert benchmark | Source-grounded verdict |
| --- | --- | --- | --- |
| Text completeness | All four verified blocks were present | All four were present in Markdown | Both had 100% recall for the four main blocks |
| Text correctness | Primary output also contained `‘`, `fae`, and `May7,2025` | Raw text contained unsupported `Uber`, `X`, and `May 7,2025`; its Markdown was cleaner | The expert raw channel is not clean ground truth |
| OCR overlap | `Uber Technologies, Inc, 7` remained in full-page OCR diagnostics without rejection status | Not emitted as text | The standard and sparse OCR passes were not punctuation-normalized before comparison |
| Duplicate content | The date appeared twice | One date in Markdown | Compact spacing was not considered by layout/OCR reconciliation |
| Heading classification | Heading recall was 1/2; the company title was plain text | Both large lines were headings | The recovered fallback hard-coded `type: text` |
| Reading order | After ignoring artifacts: photo, title, date, Q1, subtitle | Caption, date, title, Q1, subtitle | Our left-to-right order for the title/date row is at least as defensible as the benchmark |
| Photo-region detection | `(47.211, 266.304, 505.041, 148.887)` px | Scales to approximately `(47.54, 266.33, 505.21, 149.42)` px | Both are excellent; our approximate IoU with visible ground truth is 0.992 |
| Photo representation | Correct image item, but its value was low-confidence OCR noise; full-page raster existed elsewhere | Separate full-page and layout-image records plus a generated description | Detection was correct; role labelling and serialization were not |
| Image OCR | Missed exact `Uber Eats`; promoted false `‘`/`fae` | Raw text retained only partial `Uber` | Neither output reliably preserved the photograph’s exact logo text |
| Captioning | No semantic caption | Plausible semantic description | Classification cannot produce a caption; a separate VLM stage is required |
| Bounding boxes | Explicit 600×800 px/top-left coordinates; company-title box was over-tall | 144×192 coordinate space with no unit; one title bbox extended through the Q1 line | Our units are clearer, but title geometry remains imperfect |
| Confidence | Per item/OCR candidate, but confidence did not gate primary output | Item confidence exists, but page/caption score meanings are not explained | Scores are not calibrated or comparable across systems |
| Markdown | Noisy photo OCR, duplicate date, first title not a heading | Clean presentation, but backed by imperfect raw text | Benchmark Markdown was materially cleaner |
| JSON | Rich processing, confidence, geometry, OCR and provenance detail | Smaller remote-job result with generated-asset URLs and many null operational fields | Larger JSON was primarily richer representation, not proof of worse extraction |
| Fabrication risk | No semantic claim, but false OCR looked authoritative | Caption was not separately marked as generated; raw `X` was unsupported | Generated descriptions and rejected OCR must be explicitly identified |

## Field-by-field structure comparison

| Field | Current normalized output before changes | Expert output | Assessment |
| --- | --- | --- | --- |
| `result_content_metadata` | Empty object | `null` | Neither contains extraction quality evidence |
| `text.pages` | Full primary text, including noise/duplicate | Includes partial photo text and `X` | Both text channels require independent evaluation |
| `markdown.pages` | Page Markdown generated from normalized items | Clean page Markdown | This was the benchmark’s strongest channel |
| `items.pages` | IDs, reading order, source, confidence, labels, concerns, OCR children, explicit units | Simpler item objects with one or more bbox records | Our detail is useful if accepted/rejected status is clear |
| `metadata` | Schema, document hash/type/count, processing engines/timing, warnings, page/image metadata | Page confidence/orientation/auto-mode flags | Different operational goals; fields should not be copied blindly |
| `images_content_metadata` | One full-page source raster; content photograph remained in page items | Full-page rendition plus layout photograph and expiring URLs | New `region_role` fields now make the distinction explicit in the API response |
| `markdown_full` | Populated | `null` | Our full document convenience field is useful, though repetitive by design |
| `text_full` | Populated | `null` | Same trade-off as `markdown_full` |
| Job/debug fields | Not present | `job`, `forms`, `job_metadata`, `raw_parameters`, `debug` | Remote service lifecycle fields are not parsing-quality fields |

The benchmark’s `total_count: 2` means one generated full-page rendition plus
one detected photograph; it does not mean the source contained two independent
embedded images. Its 144×192 bboxes are the 600×800 source scaled by about
0.24, but the unit/transform is not documented.

## End-to-end trace and root causes

| Stage | Code path | Finding |
| --- | --- | --- |
| Upload validation | `app/api.py`, then `input_documents.detect_upload_type` and `validate_file_signature` | Extension, MIME, signature, empty/corrupt, and size validation were not responsible for the quality defect |
| Decode/orientation | `input_documents._load_image_document` | Pillow decoded RGBA, applied EXIF transpose where needed, composited transparency, and created one 600×800 source page correctly |
| Layout | `pipeline._docling_pipeline_options` → `_image_converter_and_lock` → `_convert_with_docling` | Docling found the photograph, date, Q1 heading, and subtitle, but omitted the company title from structured text |
| Picture classification | `_picture_classifier_model_available` and `_convert_with_docling` | The configured `.models/docling` lacks `docling-project--DocumentFigureClassifier-v2.5`, so the optional classifier was correctly skipped instead of causing a 500. With a reachable cached model it classified this region as `photograph` at 0.9916 |
| Semantic captioning | Previously absent; now `_picture_description_model_available`, Docling picture-description options, and `_picture_description` | Classification supplies a category, not a description. SmolVLM is now optional, local-only, off by default, and provenance-preserving |
| Full-page OCR | `ocr.extract_raster_ocr` | Standard PSM 3 and sparse PSM 11 both ran. No primary confidence policy existed |
| OCR-pass merge | Previously `_merge_sparse_ocr_lines`; now `_merge_sparse_ocr_lines_with_diagnostics` | Raw punctuation made `Inc.` and `Inc,` different tokens, so the bad longer line survived. Normalized text, overlap, similarity and confidence now select the better candidate and retain the loser as rejected |
| Visual normalization | `pipeline._visual_item` | Every OCR line whose center fell inside the photo became its `value`/`md`; low-confidence noise therefore entered reading order |
| Layout/OCR supplement | `_supplement_unrepresented_raster_ocr` | `May7,2025` did not match `May 7, 2025` under token coverage. Compact normalization now reconciles them. OCR inside non-text visual regions is now subordinate |
| Heading inference | New `_infer_image_headings` | High-confidence recovered text can be promoted using relative height, page-height ratio, position, length and geometry; the decision is recorded as a parse concern |
| Reading-order merge | `_merge_body_items` | Existing stamped Docling order plus geometric insertion was reasonable; the pollution came from candidates admitted before this stage |
| Units/confidence | `_apply_image_provenance_and_units` | Image coordinates remain top-left pixels. Confidence inheritance now requires both geometry and normalized text, rather than geometry alone |
| Markdown | `serializer._item_markdown` | Content-region images now prefer a source/model caption or explicit safe presentation; subordinate photo OCR is not emitted as prose |

## Minimal implementation

1. Added configurable image-only thresholds and feature flags in
   `app/config.py` and `.env.example`.
2. Reconciled PSM 3/PSM 11 overlap candidates with normalized text, bbox
   overlap, confidence and source-pass priority. Rejected candidates retain raw
   text, confidence, bbox, pass, reason, and replacement.
3. Added accepted/rejected status to OCR diagnostics. Low-confidence primary
   artifacts are suppressed; a moderately low-confidence but sufficiently
   informative line can still be recovered, reducing small-text loss.
4. Added compact spacing/punctuation reconciliation for overlapping layout and
   OCR text.
5. Added conservative image-only heading inference with explicit
   `heading_inferred_from_image_geometry`.
6. Added `region_role: page_source` for the uploaded raster and
   `region_role: content_region` for layout-detected photographs/charts/
   diagrams.
7. Kept photograph OCR in `ocr_text`/`raw_ocr_text` diagnostics and out of
   primary prose. Chart/diagram visible labels remain eligible for primary
   output because they are needed for downstream use.
8. Added optional local SmolVLM picture descriptions. Generated captions retain
   `caption_source`, `caption_generated`, and
   `model_generated_visual_description`. Missing models produce a warning and
   safe fallback, not a 500.
9. Restricted confidence propagation to text-matched OCR candidates.
10. Left the PDF converter/cache/options and PDF normalization behavior
    unchanged.

All schema changes are additive. Existing fields and `/v1/parse` query/request
formats are unchanged.

## Before and after

Before Markdown:

```markdown
‘
fae

Uber Technologies, Inc.

May 7, 2025

May7,2025

# Q1 2025 Earnings

Supplemental Data
```

Verified after Markdown with the configured local artifacts:

```markdown
[Image detected; no reliable text extracted.]

# Uber Technologies, Inc.

May 7, 2025

# Q1 2025 Earnings

Supplemental Data
```

The placeholder is intentional: no local semantic-caption model is installed,
and copying the expert sentence would fabricate model output. When a local VLM
is enabled, its description occupies this position and is explicitly marked as
generated.

In the after JSON:

- `fae` is present only under raw visual/page-source diagnostics with
  `accepted: false` and `rejection_reason: low_confidence`.
- `May7,2025` is accepted as a potentially informative raw OCR candidate but
  deduplicated against authoritative layout text, so it never becomes a
  primary item.
- `Uber Technologies, Inc, 7` is present only in
  `rejected_ocr_candidates`, with `replaced_by: Uber Technologies, Inc.`.
- The company title is a level-1 heading with both recovery and inferred-heading
  concerns.
- The page raster and photograph have distinct roles and bboxes.

## Before/after metrics

These are fixture-specific, insertion-sensitive measurements against the four
verified source-text blocks. They do not estimate general model accuracy.

| Metric | Before | After | Definition |
| --- | ---: | ---: | --- |
| Verified text-block recall | 4/4 (100%) | 4/4 (100%) | Presence of the four source blocks |
| Normalized word-sequence accuracy | 72.7% | 100% | `1 - word edit distance / 11 verified words`; extra noise and duplicate words count as errors |
| Normalized character-sequence accuracy | 80.7% | 100% | Alphanumeric character edit score against verified source text |
| Unsupported literal-artifact rate | 2/7 (28.6%) | 0/4 (0%) | `‘` and `fae` among primary textual candidates |
| Duplicate-candidate rate | 1/7 (14.3%) | 0/4 (0%) | Compact-normalized duplicate source blocks |
| Heading recall | 1/2 (50%) | 2/2 (100%) | Company title and Q1 title |
| Four-text-block type accuracy | 3/4 (75%) | 4/4 (100%) | Two headings plus date/subtitle text |
| Verified-block reading order | 4/4 (100%) | 4/4 (100%) | Title → date → Q1 → subtitle |
| Photograph-region IoU | 0.992 | 0.992 | Detected bbox versus approximate visible photo bounds |
| Missing verified primary blocks | 0/4 | 0/4 | Verified source blocks absent |
| Photo-level `Uber Eats` OCR recall | 0/1 | 0/1 | Exact logo text remains a limitation |
| Semantic caption in default run | No | No | Optional model unavailable; no fabricated fallback |

The company-title bbox remains over-tall (`y=395, h=73` versus visible glyphs
around `y=426, h=38`; approximate IoU 0.52). Q1, subtitle, date, and photo
geometry are substantially closer. The benchmark also contains padded or
overlapping title geometry, so it is not a reliable geometry oracle.

## Validation

Automated coverage now includes:

- exact supplied PNG when `UBEREATS_IMAGE_FIXTURE` is provided;
- low-confidence photo OCR and text-inside-photo separation;
- overlapping standard/sparse OCR selection and rejection diagnostics;
- compact date-spacing deduplication;
- conservative title promotion without promoting normal body text;
- informative small/low-confidence text retention;
- page-source/content-region roles;
- generated-caption provenance and unavailable-model fallback;
- text-heavy screenshots, forms, raster tables, charts, diagrams;
- rotated image decode, supported image types, corrupt/empty/oversized images;
- multi-frame TIFF ordering;
- all existing PDF fixtures, including the page-7 wrapped paragraph and the
  three-page finance tables.

Executed results:

- ordinary suite: 71 passed, 9 opt-in integration tests skipped;
- real varied-image suite, including the exact supplied image: 6/6 passed;
- focused image-quality regressions: 8/8 passed;
- supplied PDF regression suite: 6/6 passed.

## Performance and regression risk

The provided before-output reported 8,539 ms. The saved after-output reported
8,375 ms; repeated after-runs ranged from about 6,614 to 8,375 ms. This supports
“no observed regression,” not a speedup claim, because model warm-up and cache
state vary. One measured process peaked around 1.38 GiB RSS, dominated by
Docling model loading rather than the new string/bbox post-processing.

The confidence, deduplication, role, and heading passes operate on existing OCR
lines/items and add negligible work relative to layout/OCR. OCR candidate
comparison is worst-case quadratic on a very dense page, though overlap gates
limit typical comparisons. A spatial index would be appropriate if dense
screenshots with thousands of lines become common.

Optional semantic captioning is the material performance risk. It is disabled
by default, uses batch size 1, and was not timed because the local SmolVLM
snapshot is absent. Enabling it will increase startup latency, per-picture
latency, and memory. Its output also remains probabilistic and must not be
treated as OCR truth.

## Remaining limitations and confidence

- High confidence: removal of the observed primary noise/duplicate/overlap,
  heading correction, role separation, diagnostics, exact-image behavior, and
  PDF non-regression.
- Moderate confidence: general heading inference. Conservative geometry reduces
  form-label promotion, but unusual posters/banners can still be ambiguous.
- Moderate confidence: very small or degraded text. Informative low-confidence
  lines are retained, all rejected text remains diagnostic, and thresholds are
  configurable, but no OCR threshold can separate every real glyph from noise.
- Moderate-to-low confidence until a model is installed: end-to-end semantic
  caption inference. Configuration, extraction, provenance, and fallback are
  tested; actual SmolVLM inference was not run locally.
- Remaining known miss: exact `Uber Eats` text inside the photograph.
- Remaining geometry issue: the recovered company-title bbox is padded upward.
- Captions may contain plausible but unverified visual inferences. Downstream
  consumers should use `caption_generated`/`caption_source` and not conflate
  captions with `ocr_text`.
- Single-sample improvement does not establish parity with the expert model.
