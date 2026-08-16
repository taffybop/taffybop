# Source, expert, and baseline validation: `health-report`

## Scope and verdict

This report validates the immutable one-page health-report PDF against the supplied expert Markdown/JSON and visually compares the successful baseline parser run `baseline-20260728-current`.

The expert output is reliable for captions, notes, sources, links, trend semantics, and the footer. Its exact chart tables are not safe as literal ground truth. The upper chart's 99 numeric values are not printed and are supplied without a derivation method, tolerance, or point boxes. The lower bubble-chart table contains several values that conflict materially with measured bubble centers. Our baseline is safer because it does not invent exact chart values, but it fails to recover useful country/value relationships, emits garbled upper-chart labels, and misclassifies a set of lower-chart labels as a separate one-column table that duplicates the chart.

## Inventory and method

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `health-report.pdf` | 222,282 | `fe0bd5c224d5df5cedf26129a04980ac06b67e165875bca0296c6f2cd483b181` |
| Expert `health-report.md` | 6,271 | `a85539100ab3067d149441af72b48ca4ade8cb1bd8d719aba4b610ff4dc3d00d` |
| Expert `health-report.json` | 43,114 | `e1b7c94e8eefc1eac9611222848cd2680eb70a4993a8a7d1710fa0b3783f45dc` |

- Source: one native portrait PDF page, 595.276 x 793.701 pt, rotation 0; printed page 103.
- Category: public-health statistical report.
- Layout: running page marker; upper country-by-gender combo chart; note/source/link; lower cancer-site bubble chart; note/source/link; running footer.
- Complex elements: 33-country grouped visual marks with total/men/women encodings, rotated category labels, weighted-average note, bubble x/y/size/color encoding, annotations, and dense vector geometry.
- Source object inventory: 1,154 native characters, 148 lines, 502 curves, 0 images, 2 link annotations, and one chart-like table detected from aligned native text. Both charts are vector page content.
- Visual evidence: `tmp/pdfs/llamaparse-15/health-report/page-001.png` was inspected at original detail. Native text, vector grid positions, annotations, and render-space colored components were independently checked.
- Baseline evidence: the case's JSON, Markdown, diagnostics, and metrics in `runs/baseline-20260728-current`.

Status terms:

- `Verified`: explicit source content/structure is supported.
- `Partially verified`: the element exists, but exactness, structure, or geometry is incomplete.
- `Not independently verifiable`: a plausible exact claim cannot be proved from the supplied bundle.
- `Incorrect`: the claim conflicts with source evidence.
- `Potentially inferred`: a semantic or numeric claim is added beyond explicit source evidence.

## Source page map

| Physical page | Printed page | Source regions and reading order |
|---|---:|---|
| 1 | 103 | Page marker at upper right; Figure 3.9 caption around `y=58-70`; upper chart approximately `x=45-542, y=79-276`; note/source/link at `y=286-319`; Figure 3.10 caption around `y=332-344`; bubble chart approximately `x=51-541, y=353-548`; explanatory note/source/link at `y=560-615`; footer around `y=739`. |

## Evidence classification

- Explicit: figure captions, country/site labels, axes/ticks, total/men/women legend, red/green/size semantics, notes, source text, link text/targets, footer, and printed page 103.
- PDF-vector-derived: upper-chart mark positions and lower-chart bubble centers/sizes/colors relative to vector grids.
- Pixel-estimated: colored-component centers in the rendered bubble chart, used as a cross-check against vector axes.
- Model-inferred: exact rounded values reconstructed from mark locations and any generated table schema.
- Unverifiable: the underlying chart datasets, intended rounding, point-picking method, and error tolerance.

## Expert element validation

Indexes refer to `items.pages[0].items`.

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | Header `| 103` | Partially verified | Page 103 is explicit; the vertical bar represents a small visual icon/rule rather than literal body text. |
| 1 | Figure 3.9 caption | Verified | Exact wording and correct placement. |
| 2 | 33-row country/Total/Men/Women table | Not independently verifiable | Country order and approximate mark positions are visually plausible, but none of the 99 exact values is printed. One chart-region bbox/confidence does not ground individual cells. |
| 3-4 | Upper note and source | Verified | Exact visible wording. |
| 5-6 | First StatLink label and URL | Verified | The text/target match one of the source's two PDF link annotations. |
| 7 | Figure 3.10 caption | Verified | Exact visible caption. |
| 8 | Bubble chart transformed to 13 exact rows | Incorrect | Site labels and increase/decrease direction are source-supported, but multiple x/y values conflict with bubble centers. Concrete measurements appear below. |
| 9 | X-axis label | Verified | Explicit text, though its bbox overlaps the chart item's lower edge and the same semantic label is also generated as a table column. |
| 10-11 | Lower note and source | Verified | Exact wording, including color, bubble-size, and cancer-name qualifications. |
| 12-13 | Second StatLink label and URL | Verified | Matches the second source annotation. |
| 14 | Running footer | Verified | Exact visible footer. |
| Region confidence/metadata | Chart boxes 0.99/0.98; page metadata confidence 0.8 | Not independently verifiable | These scores do not define whether they measure region detection, OCR, point association, or numeric accuracy. |

Both expert chart items carry a `layout_lvm_disagreement` concern because layout detected charts rather than tables. That concern is appropriate and should prevent their exact cell values from being assumed authoritative.

## Concrete expert chart errors and limitations

### Upper chart exactness is not independently verifiable

The source prints a 0-500 scale, 33 country labels, and visual marks for total, men, and women. It does not print the expert's numeric rows. Vector measurement can estimate each mark, but the expert JSON supplies no point bbox, measurement rule, rounding interval, or external data sidecar. The table can be used as a hypothesis, not exact benchmark truth.

### Lower chart values conflict with measured bubble centers

The vector axes place approximately:

- x=0 at 72.63 pt and x=50 at 534.04 pt.
- y=20 at 357.69 pt, y=0 at 414.65 pt, and y=-40 at 528.45 pt.

Colored-component centers from the original-detail render were mapped through those axes. Small anti-aliasing and bubble-size effects make these approximate, but several discrepancies are much larger than that uncertainty.

| Cancer site | Expert `(mortality, change)` | Approximate visible bubble center | Assessment |
|---|---:|---:|---|
| Pancreas | `(18, +5)` | `(17.4, +4.6)` | Close; plausible rounding. |
| Ovary | `(6, -21)` | `(5.2, -15.6)` | Incorrect y association; expert value is near label placement, not bubble center. |
| Bladder | `(9, -20)` | `(7.6, -13.8)` | Material x/y discrepancy. |
| Stomach | `(11, -34)` | `(9.5, -29)` | Material discrepancy. |
| Colorectum | `(27, -21)` | `(27.0, -17.3)` | X is close; y is materially too low. |
| Lung | `(45, -15)` | `(47.0, -14.0)` | Approximate but not exact as emitted. |
| Leukaemia | `(12, -22)` | No distinct teal bubble at the claimed coordinate in the color-component evidence | Exact point claim is unsupported. |

Other approximate visible centers include Cervix `(1.9,-17.0)`, Skin `(3.1,-7.4)`, Brain `(6.7,-5.3)`, Liver `(9.7,-10.7)`, Prostate `(13.7,-9.3)`, and Breast `(17.4,-9.5)`. These are measurements, not replacement authoritative data. The key finding is that the expert has no disclosed derivation and several rows are inconsistent with the visual marks.

## Baseline parser comparison

The baseline completed successfully with one page, 10 items, 100% bbox/provenance coverage, two chart items, one table item, and three parse concerns.

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p1-i1` | Partially verified | Page 103 is correct, but the visual marker is serialized as a private-use glyph ``. |
| `p1-i2` | Partially verified | Correctly identified as a chart and flagged `chart_values_not_structured`. Caption, axes, and legend are present, but most rotated country labels are garbled or absent and no country/series/value relationship is produced. Its bbox begins at `y=79.088`, while the item Markdown also includes the caption around `y=58`, outside that bbox. |
| `p1-i3` | Verified | Upper note and source are accurate; combining them into one text item does not change content. |
| `p1-i4` | Partially verified | StatLink text and URL are accurate, but the PDF's link annotation is flattened into ordinary text rather than represented as a link object. |
| `p1-i5` | Partially verified | Correctly classified as a chart, with caption, site labels, axes, and `chart_values_not_structured`. It safely avoids unsupported exact points but gives no x/y/size/color structure. Its Markdown includes the caption above the item's bbox. |
| `p1-i6` | Incorrect | A separate native `table` over the same bubble-chart region groups cancer labels by visual y position into one column. It is not a source table and duplicates `p1-i5`; the concern only says `contains_empty_visual_rows`. |
| `p1-i7` to `p1-i8` | Verified | Lower explanatory note and source text are complete. |
| `p1-i9` | Partially verified | Second StatLink text/URL are correct but again flattened from an annotated link to text. |
| `p1-i10` | Verified | Footer wording and bbox are correct. |

Confirmed strengths relative to the expert:

- No unsupported exact upper-chart or bubble-chart values are asserted.
- Both visual regions are explicitly typed as charts and flagged as unstructured.
- The source annotations' visible URLs are preserved.
- Chart classification, OCR tokens, bboxes, source, and parse concerns are available in JSON.

Confirmed baseline defects:

- The upper chart loses the main category information because rotated country labels are corrupted.
- The lower chart is represented twice, once as a chart and once as a false one-column table.
- Neither chart has semantic mark/series/value output.
- Chart item bboxes do not include captions that are serialized inside their Markdown.
- Link annotation semantics are lost even though target text survives.
- Confidence exists only on the two chart regions and does not cover the false table or text/link extraction.

The automated expert-to-ours similarity is low largely because ours declines to reproduce 112 unsupported expert numeric cells. That is not, by itself, a parser-quality failure. The missing explicit labels and duplicated false table are source-confirmed failures.

## Bounding boxes, confidence, and metadata

- The expert chart bboxes cover their chart regions but provide no country mark, bubble, cell, or axis-calibration geometry.
- Expert item 9 overlaps item 8 near the lower chart edge. This is not content loss, but it shows that table-body versus axis-label ownership is ambiguous.
- Our chart bboxes closely cover the visual plots, but both exclude captions included in the same item Markdown.
- Our false table `p1-i6` overlaps the same region as chart `p1-i5`, making duplication detectable geometrically.
- Expert page metadata confidence is 0.8; chart region scores are 0.99 and 0.98 even where exact values are wrong. Our chart confidences are 0.6926 and 0.8754, but their scope is still region/classification oriented rather than value accuracy.
- Expert `job.tier` is `agentic`; `markdown_full` and `text_full` are null.

## Standalone Markdown versus JSON

Expert standalone Markdown equals the JSON header, page-body Markdown, and footer after trimming. JSON page-body Markdown excludes the page marker and running footer. This is internally explainable but differs from a full-document serialization.

Our schema has no separate JSON page-body Markdown field. `our-output.md` is the ordered item serialization, including header/footer and both overlapping lower-chart representations. The duplicate table is therefore visible in both JSON and Markdown.

## Mapped gaps

| Gap | Origin | Mapped capability | Exact evidence |
|---|---|---|---|
| `GAP-CHART-001` | Both | Reconstruct explicit chart labels, axes, series, and relationships without flattening them. | P1 Figure 3.9 `x=45-542, y=79-276` and Figure 3.10 `x=51-541, y=353-548`; ours emits no useful structure. |
| `GAP-CHART-002` | Expert | Distinguish text-label position from the associated data-mark center and require a method/tolerance. | Figure 3.10 Ovary/Bladder/Stomach/Colorectum rows; expert y values are materially below measured bubbles and often closer to label placement. |
| `GAP-TABLE-001` | Ours | Suppress native-table false positives and duplicate representations inside chart regions. | `p1-i5` and `p1-i6` overlap the lower chart; `p1-i6` groups labels as table rows despite no source table. |
| `GAP-OCR-001` | Ours | Recover rotated/dense chart labels and normalize private-use glyphs without inventing text. | Upper chart country-label band and header ` 103`. |
| `GAP-BBOX-001` | Both | Represent plot, axis, series, mark, and table-cell geometry hierarchically. | Expert has chart-only boxes with no field-level geometry. |
| `GAP-LAYOUT-001` | Ours | Keep chart captions as linked elements with their own source geometry. | Our chart items serialize captions outside their plot bboxes. |
| `GAP-LINK-001` | Ours | Preserve PDF annotation semantics and target provenance, not only visible URL text. | Two StatLinks at `y=310` and `y=605`; source has two annotations, ours emits ordinary text. |
| `GAP-PROVENANCE-001` | Both | Separate detection confidence from OCR, association, and numeric confidence. | Expert chart 0.98 with wrong point values; our chart confidence has no field-level interpretation. |
| `GAP-SERIALIZATION-001` | Contract | Define full Markdown versus page-body/header/footer and overlapping-item serialization. | Expert body excludes header/footer; our item-stream Markdown includes the false table alongside the chart. |

## Open questions

- Is an authoritative source dataset available for either figure, with stable point IDs?
- What rounding/tolerance was used for the expert chart values?
- Should a chart's native aligned labels ever become a table when layout explicitly classifies the region as a chart?
- How should caption bbox ownership be represented when a chart item includes caption text?
- Should PDF link annotations be first-class link items even when the URL is also visible?

## Guardrail

This report is a read-only evidence record. It makes no parser, test, story, corpus, or benchmark-aggregation change.
