# Expert-output validation: `component-datasheet`

## Scope and verdict

The expert output preserves the datasheet's ordinary text, lists, captions, links, key-value data, headers, and footers well. Its treatment of visual regions is much weaker: the board photos and pin-numbering drawing become unmarked semantic descriptions, and the explicit pin labels in the technical drawing are omitted. The operating-conditions values are correct, but their raw-HTML Markdown styling is defective and the source is an unruled key-value block rather than an unequivocal table.

## Inventory

All expected files are present and paired correctly.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `component-datasheet.pdf` | 329,199 | `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4` |
| `component-datasheet.md` | 3,845 | `73c00a11c9d719ef6413e51bb20de690a7beb5b69eb031839e537ace11e8e7b4` |
| `component-datasheet.json` | 105,212 | `be6790098274c52e6b1267822fb8a3f72ae3b5de6470a1955da7250982348573` |

- Source format: three-page mixed native-text PDF, 595.28 × 841.89 pt, rotation 0.
- Physical-to-printed pages: 1→3, 2→7, 3→11.
- Category: hardware/component datasheet.
- Layout: chapter page with two board photos and nested feature lists; technical vector drawing with adjacent caption and note callout; sparse operating-conditions page with a borderless two-column key-value region.
- Complex elements: raster board imagery containing small silkscreen text, dense vector engineering drawing with numbered pins/test points, callout styling, nested lists, symbols (`×`, `Ω`, `±`, `°C`), and key-value/table ambiguity.
- Source object inventory:

| Physical page | Native chars | Images | Lines | Rectangles | Curves | Dominant content |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 1,383 | 2 | 2 | 1 | 0 | Two board photos and nested feature lists |
| 2 | 1,211 | 0 | 263 | 2 | 374 | Vector pin-number drawing, note, lists, prose |
| 3 | 514 | 0 | 2 | 0 | 0 | Heading, key-value block, short prose |

- Renders inspected: all three `tmp/pdfs/llamaparse-15/component-datasheet/page-*.png`.
- The standalone Markdown differs from concatenated JSON page-body Markdown because it includes repeated headers/footers; the triple is otherwise correctly paired.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 3 | Chapter heading and introduction; Figure 1 caption at left; two board photos around `x≈130–412, y≈152–417`; introductory feature list and nested sublists below; running footer. |
| 2 | 7 | Figure 4 caption at left and vector drawing at `x≈113, y≈79, w≈173, h≈293`; NOTE callout below; GPIO and interface-pin lists; three explanatory paragraphs; footer. |
| 3 | 11 | Section heading and introduction; operating-conditions key-value block at `x≈125, y≈143, w≈195, h≈82`; two short paragraphs; large whitespace; footer. |

## Expert element validation

| Element | Expert representation | Status | Source-grounded assessment |
|---|---|---|---|
| Page count and dimensions | Three successful item pages, 595.28 × 841.89 | Verified | Matches source. |
| Printed pagination | Footer markup 3, 7, 11 | Verified | Matches visible pages; structured printed page fields remain null. |
| Headers/headings | Header and heading items | Verified | Wording and hierarchy are faithful. |
| P1 introduction and feature lists | Text plus nested lists | Verified | Text, nesting, symbols, and reading order match. |
| Figure 1 caption | Text item | Verified | Exact visible caption. |
| P1 board-photo description | `The ... board showing top and bottom views with pinout labels` | Potentially inferred | Accurate high-level description, but it is not printed prose and no field marks it as model-derived. |
| P1 image text/OCR | No detailed transcription of silkscreen labels | Partially verified | The photos are recognized semantically; most explicit pixel labels are not represented. |
| Figure 4 caption | Text item | Verified | Exact visible caption. |
| P2 technical drawing description | Generic text item, bbox label `table` | Potentially inferred | The wording is plausible but not printed. It is neither a faithful diagram representation nor a table. |
| P2 pin/test-point labels | Omitted from Markdown/structured content | Incorrect | Visible vector labels 1–40, TP1/TP4/TP5/TP6, D1/D2/D3, and reverse-side note are not serialized. |
| P2 note, lists, and prose | Callout text, list items, paragraphs | Verified | Content and symbols such as `100kΩ` match. |
| P3 operating-condition values | Two-column table/key-value item | Verified | All five labels and values match the source. |
| P3 element classification | JSON `type=table`, bbox label `key-value-region` | Partially verified | The source is an aligned, unruled key-value block. A two-column table is usable, but the JSON contains competing classifications. |
| P3 Markdown/HTML formatting | Raw HTML cells containing `**...**` | Incorrect | Markdown emphasis syntax inside raw HTML is normally literal text; the expert output does not faithfully render the source's bold labels. |
| Headers/footers | Separate items; included in standalone Markdown | Verified | Correct text and printed page numbers. |
| Major region bboxes | Photo/drawing/key-value regions | Verified | Bboxes align closely with the intended regions. |
| Confidence values | Pages 0.958/0.933/0.977; items 0.58–1.00 | Not independently verifiable | No calibration definition or separate semantic-description confidence is supplied. |
| Structured metadata | Physical pages present; printed pages/full fields null | Partially verified | Physical pagination is correct; printed labels and full serializations are not structured. |

## Concrete expert errors and limitations

### Visual descriptions are not distinguished from printed text

On p1, the source prints the caption `Figure 1. The Raspberry Pi Pico Rev3 board.` It does not print the additional sentence `The Raspberry Pi Pico Rev3 board showing top and bottom views with pinout labels`. That sentence is a reasonable visual description inferred from two raster images. It is emitted as an ordinary `text` item with confidence 0.84, so a consumer cannot distinguish author text from generated alt text.

The item bboxes do cover both photo regions (`y≈170–270` and `y≈296–399`) and multiple detected subregions, making the location plausible. The content's provenance, not the association, is the problem.

### The pin-number drawing is reduced to a generic, incomplete sentence

Physical p2 is vector content, not a source raster. The drawing explicitly contains:

- left pins 1 through 20;
- right pins 40 through 21;
- top labels including TP2/TP3 and TP1;
- TP4, TP5, TP6;
- `TP1-6 ARE ON REVERSE SIDE`;
- bottom labels D1, D2, D3.

The expert emits only `The pin numbering of the Raspberry Pi Pico Rev3 board engineering drawing`, an unprinted semantic description. Its main bbox (`x=113.01, y=79.03, w=173.16, h=293.06`) correctly covers the figure and child boxes cover many labels, yet none of the explicit label content is exposed in Markdown, rows, nodes, or relations. The item is typed `text` while the bbox is labeled `table`, which is internally inconsistent.

This output is not adequate diagram ground truth. A safer representation would preserve the figure/caption, explicit OCR/native labels with geometry, and a diagram or visual-region object; a generated description should remain clearly marked as inferred.

### Operating-conditions serialization has a rendering defect

The values are source-correct:

- Operating Temp Max — 85°C (including self-heating)
- Operating Temp Min — -20°C
- VBUS — 5V ± 10%.
- VSYS Min — 1.8V
- VSYS Max — 5.5V

The standalone Markdown uses raw `<table>` markup with cells such as `<td>**Operating Temp Max**</td>`. Markdown emphasis is generally not parsed inside raw HTML blocks, so the literal asterisks can appear instead of the source's bold text. JSON `md` also escapes the asterisks, while `rows`, HTML, and CSV preserve the markers as content. This is a serialization error even though the underlying values are verified.

The JSON's own parse concerns note a layout/model disagreement: layout found a `key-value-region`, not a table/form. The `header_value_type_mismatch` concern is also spurious because the first column contains labels, not numeric headers.

## Bounding boxes, confidence, and metadata

- The photo description has two main bboxes corresponding to the top and bottom photos, plus many small child regions.
- The p2 drawing bbox is accurate, but its many child boxes are not exposed as named pin/test-point elements.
- The p3 key-value bbox and per-line child bboxes align to the displayed values.
- Coordinate units/origin are not declared, though values align with PDF points and a top-left origin.
- Confidence values do not state whether they measure region detection, transcription, visual description, or structural classification.
- The p3 table confidence is 1.0 despite an explicit classification disagreement in `parse_concerns`.

## Standalone Markdown versus JSON page-body Markdown

The standalone Markdown includes `Raspberry Pi Pico Datasheet`, section/chapter footers, and `<page_number>` values between pages. The JSON page-body Markdown excludes these repeated regions. Both scopes retain substantive page content, including the unmarked inferred visual descriptions.

Top-level `markdown_full` and `text_full` are null. Evaluators must not compare standalone Markdown to joined JSON page bodies without accounting for this intentional scope difference.

## Mapped gaps

These findings use the finalized gap taxonomy. Their baseline confirmation
status is recorded in the next section.

| Gap | Mapped capability | Exact evidence |
|---|---|---|
| `GAP-VISUAL-001` | Separate explicit caption/OCR text from generated visual descriptions, with source region and provenance. | Physical p1 / printed p3, board photos `x≈130–412, y≈152–417`; expert adds unmarked descriptive prose. |
| `GAP-DIAGRAM-001` | Preserve technical-diagram labels, nodes/components, and spatial relationships rather than only generic alt text. | Physical p2 / printed p7, vector drawing `x≈113, y≈79, w≈173, h≈293`; pin/test-point labels omitted. |
| `GAP-TABLE-003` | Keep Markdown, HTML, rows, and CSV semantically consistent; do not embed literal Markdown markers in raw HTML cells. | Physical p3 / printed p11, key-value region `x≈125, y≈143, w≈195, h≈82`. |
| `GAP-PROVENANCE-001` | Record author text, native/OCR text, pixel-visible text, and model-generated description as distinct provenance. | P1/P2 visual descriptions are ordinary `text` items; p2 explicit vector labels are absent. |
| `GAP-BBOX-001` | Promote detected visual subregions into traceable semantic elements. | P2 item has numerous child label boxes but only one generic output sentence. |
| `GAP-PAGE-001` | Preserve non-contiguous printed pagination and declare coordinate conventions. | Physical pages 1–3 are printed 3, 7, 11; metadata printed-page fields are null. |

## Fixed-baseline assessment

Baseline artifacts: [our Markdown](../runs/baseline-20260728-current/component-datasheet/our-output.md) and [our JSON](../runs/baseline-20260728-current/component-datasheet/our-output.json).

The parse reports success for all three pages and emits 60 top-level items: three headers, three footers, three headings, two images, one diagram, two lists, and 46 text items.

### Source-grounded results

- Verified strengths:
  - All three pages, major prose, feature content, numeric operating conditions, headers, footers, and visible printed page numbers are retained.
  - The p1 visual region is correctly classified as a photograph and the p2 visual region as an engineering drawing.
  - The p2 drawing has a specific `diagram_relationships_not_structured` concern rather than an invented semantic graph.
  - With picture captioning disabled, the parser does not add the expert's unmarked model-generated descriptions. This is source-safer.
  - P3 avoids the expert's literal-`**` raw-HTML defect; all five labels and values are plain, correct text.
- Confirmed source errors:
  - P1 serializes the left-side Figure 1 caption before the chapter heading even though the heading and introduction occur first in the natural page flow.
  - P1 photograph OCR is promoted to Markdown as a long sequence of corrupt/incomplete silkscreen tokens (`@`, `veus`, `TPL`, `1P4`, `os`, `Gp2i`, and others).
  - Nested feature bullets are flattened to one list level. The three sub-features under the 40-pin PCB and the power-supply sub-feature lose their parent-child relation.
  - P2 engineering-drawing OCR is highly corrupt and incomplete, with repeated/malformed pin labels. It does not provide a usable ordered 1–40 pin sequence, test-point inventory, or spatial relationship model.
  - The note icon produces both a generic image placeholder and a private-use glyph in `#  NOTE`.
  - P2's two aligned label/value groups (GPIO29/IP..., PIN40/VBUS...) are emitted as dozens of separate text paragraphs rather than lists or key-value rows.
  - P3's five operating-condition pairs are likewise emitted as ten independent text items rather than one key-value/table structure.
  - Minor text normalization defects include `Datasheet ,` and `100k Ω` where the source has no space before the comma or between `k` and `Ω`.

### Confirmed mapped gaps

| Gap | Severity | Baseline status | Exact baseline evidence |
|---|---|---|---|
| `GAP-DIAGRAM-001` | High | Confirmed | Physical p2 / printed p7, engineering drawing around `x≈114–286, y≈79–372`: classification is right, but OCR labels are corrupt/incomplete and relationships are unstructured. |
| `GAP-OCR-001` | Medium | Confirmed | P1 board photos `x≈115, y≈152, w≈296, h≈265` and p2 drawing: low-quality visual OCR is promoted into primary Markdown. |
| `GAP-LIST-001` | Medium | Confirmed | Physical p1 / printed p3, feature lists below `y≈459`: nested source bullets are flattened. |
| `GAP-FORM-001` | Medium | Confirmed | P2 aligned GPIO/interface-pin pairs and p3 operating-condition block `x≈125, y≈143–225` become unrelated text items rather than row pairs. |
| `GAP-ORDER-001` | Medium | Confirmed | P1 Figure 1 caption at left is ordered before the chapter heading/main introduction. |
| `GAP-VISUAL-001` | Low | Confirmed for explicit-vs-noisy OCR policy | The parser avoids inferred captions, but still mixes unreliable pixel OCR into ordinary Markdown without a concise source-region placeholder or confidence policy. |
| `GAP-PAGE-001` | Low | Confirmed | Output `page_label` values are physical 1–3; printed 3, 7, 11 remain only in footer text. |

### Source-correct disagreements with the expert

- The baseline does not invent the expert's two unprinted visual descriptions because local captioning was disabled. This is a justified, safer difference.
- P3 outputs correct plain text rather than the expert's malformed raw HTML with literal `**` markers. The remaining baseline gap is loss of key-value grouping, not failure to match the expert serialization.

## Open questions

- Is detailed OCR/native extraction of labels inside figures required, optional, or exposed through a separate visual-content channel?
- What schema should represent a technical drawing whose labels are explicit but whose topology is spatial rather than connector-based?
- Should the p3 region be typed `key_value`, `table`, or both through distinct semantic and layout fields?
- Are model-generated descriptions allowed in Markdown by default, and if so, how are they marked?
- What renderer defines the required Markdown behavior for HTML tables and inline emphasis?

## Guardrail

The baseline was assessed read-only. No parser behavior, source artifact, phase/story file, test, or global benchmark aggregate was changed. Expert-generated visual descriptions remain excluded from verbatim parity requirements.
