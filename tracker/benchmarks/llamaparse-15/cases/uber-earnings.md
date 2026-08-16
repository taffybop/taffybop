# Expert validation: `uber-earnings`

## Scope and overall assessment

This report validates both the supplied expert Markdown/JSON and the `baseline-20260728-current` output from our parser against the three source PDF pages. It is analysis-only; source, expert, and run artifacts were treated as immutable evidence.

The expert output captures the slide text and gives useful structured interpretations of the photograph, charts, flags, and topology diagrams. Its main weakness is provenance: generated descriptions, vector-derived chart values, and inferred directed edges are serialized alongside explicit source text without a reliable distinction. It also misidentifies the New Zealand flag as Australia. Our baseline is more conservative about inferred values/edges and has useful visual-region provenance, but leaks false photo OCR and non-rendered construction text into Markdown and leaves chart/diagram relationships unstructured. Intermediate chart values are visually supported by vector geometry, but are not explicitly printed and cannot be certified as exact underlying business data from the rendered slide alone.

Status vocabulary:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — substantially supported, with a material qualification.
- **Not independently verifiable** — the output supplies a claim or score for which the source provides no independent test.
- **Incorrect** — contradicted by the source.
- **Potentially inferred** — plausible, but derived or model-interpreted rather than explicit in the source.

## Artifact inventory

| Artifact | Role | SHA-256 |
|---|---|---|
| `benchmark-expertmodeldata/uber-earnings.pdf` | Ground-truth source | `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5` |
| `benchmark-expertmodeldata/uber-earnings.md` | Expert standalone Markdown | `1b0d635b20cd7d6244109516606ad50ff8fee463ea266ddda13236cda9e03a7e` |
| `benchmark-expertmodeldata/uber-earnings.json` | Expert structured output | `eb2800cb910789901261fb585aa80176c975b11403534a488f3b02dfcec44c34` |

- Document category: investor-relations earnings presentation excerpt.
- Page inventory: 3 landscape slides, each 1920 × 1080 PDF units.
- Layout:
  - slide 1: cover text over white space with a full-width upper photograph;
  - slide 2: market-leadership flag grid, gross-bookings bar chart, adjusted-EBITDA bar/line chart, notes, and footer;
  - slide 3: two visual business-topology diagrams plus a highlights sidebar.
- Complex elements: raster photography, flag icons, bar/line charts, derived numeric data, labeled node diagrams, vector connectors, and side-panel prose.
- Native object inventory:
  - slide 1: 70 characters, 1 rectangle, 2 curves, 1 raster image;
  - slide 2: 626 characters, 24 rectangles, 7 lines, 7 curves, 11 raster images;
  - slide 3: 393 characters, 11 rectangles, 4 lines, 30 curves, 15 raster images.
- Expert job metadata: `tier=agentic`, `cost_optimized=false`, `triggered_auto_mode=false`; orientation 0; page confidences 0.800, 0.726, and 0.881.

## Source page map

| Physical PDF page | Source content | Expert item summary |
|---|---|---|
| 1 | Investor-update cover with an Uber Eats bag photograph, date, title, and footer | Text/headings plus generated photograph description |
| 2 | Ten market flags, Gross Bookings chart, Adjusted EBITDA and margin chart, notes | Flag description text, two structured chart tables, prose/footer |
| 3 | Consumer-to-verticals and merchant-to-platform diagrams, plus key highlights | Two Mermaid code blocks, two image crops, headings/prose/footer |

## Evidence classes used for this slide deck

- **Explicit vector text:** titles, notes, endpoint labels, node labels, and footer text printed in the PDF.
- **Vector-derived:** values estimated/recovered from bar heights, baselines, axes, or line-point positions even when not printed.
- **Pixel-grounded:** objects or identities visible only in raster imagery, such as the cover photograph and flag designs.
- **Model-generated:** natural-language image descriptions and semantic diagram interpretations not literally present in the source.
- **Not independently verifiable:** exact latent data values, generation method, confidence scores, or directed-edge semantics that cannot be proven from the supplied source.

## Expert element validation

| Page | Expert element or claim | Evidence class | Status | Assessment |
|---|---|---|---|---|
| 1 | Date, title, and footer text | Explicit vector text | **Verified** | Wording and reading order match the source. |
| 1 | “Photograph of an Uber Eats delivery bag with flowers and groceries on a doorstep” | Pixel-grounded plus model-generated prose | **Potentially inferred** | The branded green bag, groceries/flowers, doorway, and doorstep are visible. “Delivery bag” and the sentence itself are interpretive, not a source caption. |
| 1 | Photograph represented as a `text` item with image-labelled bbox | Model/schema choice | **Partially verified** | It localizes the image, but does not expose that the prose was generated rather than transcribed. |
| 2 | Printed chart titles, notes, years, and endpoint labels | Explicit vector text | **Verified** | Source text matches. |
| 2 | Gross Bookings `$56B` (2022) and `$82B` (Q1’25 ARR) | Explicit vector text | **Verified** | Both endpoint values are printed. |
| 2 | Gross Bookings `63` (2023) and `73` (2024) | Vector-derived | **Potentially inferred** | Bar geometry supports approximately these values, but they are not printed and lack derivation/tolerance metadata. |
| 2 | Adjusted EBITDA `$0.6B` and `$3.1B` endpoints | Explicit vector text | **Verified** | Both are printed. |
| 2 | Adjusted EBITDA `1.4` and `2.3` | Vector-derived | **Potentially inferred** | Bar geometry supports the values; exact latent data is not independently available. |
| 2 | Margin `1.0%` and `3.7%` endpoints | Explicit vector text | **Verified** | Both are printed. |
| 2 | Margin `2.2%` and `3.2%` | Vector-derived | **Potentially inferred** | Line-point geometry supports approximate values; no point-level provenance or rounding rule is supplied. |
| 2 | First flag described as Australia | Pixel-grounded model classification | **Incorrect** | The source flag is New Zealand. |
| 2 | Remaining flag identities | Pixel-grounded model classification | **Verified** | Canada, Chile, France, Japan, Mexico, Spain, Taiwan, United Kingdom, and United States match the visible flags. |
| 3 | All node labels in both diagrams | Explicit vector text | **Verified** | All labels are printed in the source. |
| 3 | Mermaid directed arrows between nodes | Model interpretation of vector layout | **Potentially inferred** | Gray wedges and spatial grouping support association, but the source has no arrowheads and does not explicitly encode direction. |
| 3 | Diagram image crops plus Mermaid code | Derived representations | **Partially verified** | Both relate to the source regions, but they create parallel semantic representations with no declared primary view. |
| 1–3 | Page confidence values | Model metadata | **Not independently verifiable** | The source cannot validate 0.800, 0.726, or 0.881, and there is no per-datum confidence. |
| 1–3 | `images_content_metadata.total_count=21` as image inventory | Mixed native and derivative artifacts | **Partially verified** | The source does contain raster images, unlike the other cases, but the count also includes generated full-page/crop images and therefore is not a native-image count. |

## Concrete expert discrepancies and derivation checks

### 1. New Zealand flag is mislabeled as Australia

The first flag in the slide-2 market grid—upper-left flag region, approximately `x=77.88`, `top=718.8`, `width=84.56`, `height=61.65`—has the New Zealand design. The expert’s generated flag-name text calls it Australia. This is an **Incorrect** pixel/model classification. The generated flag-name item also lacks a source bbox and generated-content provenance.

### 2. Intermediate Gross Bookings values are geometry-derived

The source prints `$56B` and `$82B`, but not the 2023 or 2024 values. The green bar rectangles share a baseline near `y=834` and have approximate heights:

| Period | Approximate bar x | Height | Expert value | Source status |
|---|---:|---:|---:|---|
| 2022 | 719 | 207 | 56 | Explicit endpoint |
| 2023 | 847 | 237 | 63 | Vector-derived |
| 2024 | 976 | 277 | 73 | Vector-derived |
| Q1’25 ARR | 1105 | 303 | 82 | Explicit endpoint |

Interpolating from visible endpoint scale/geometry supports the expert’s intermediate values. It does not prove the exact underlying business data, rounding convention, or whether the model read hidden construction data. Those cells should carry derivation metadata such as `source=vector_geometry`, marks/axis references, and tolerance.

### 3. Intermediate EBITDA and margin values are geometry-derived

The EBITDA bars at approximate x positions 1358, 1487, 1616, and 1745 share a baseline near `y=834` and have heights about 45, 125, 206, and 255. The source prints the 0.6 and 3.1 endpoints; geometry supports the expert’s unprinted 1.4 and 2.3 intermediates.

The margin line points are approximately:

```text
(1402.07, 706.81), (1532.43, 592.91),
(1662.79, 519.69), (1793.15, 487.15)
```

The source prints 1.0% and 3.7% endpoints. Relative point positions support approximately 2.2% and 3.2%, but exact values remain **Potentially inferred** without explicit tick-to-value mapping and rounding provenance.

### 4. Mermaid arrows overstate the diagram evidence

Slide 3 explicitly prints these node labels:

- consumer side: Consumers, Restaurants, Grocery, Convenience, Alcohol, Pet, Home Improvement, Electronics;
- merchant side: Merchants, Uber Eats Marketplace, Direct, Pickup, Dine-In, Advertising, Offers, Data & Analytics.

Gray wedge-like connectors and layout indicate relationships. They do not have arrowheads. The expert converts them to directed Mermaid edges such as `Consumers --> Restaurants` and `Merchants --> Uber Eats Marketplace`. Direction may be semantically plausible, but it is not an explicit visual property and is therefore **Potentially inferred**.

The code-item boxes cover only selected label nodes rather than all nodes and edges. They do not provide edge-level evidence. The relevant expert crop regions are approximately:

- upper diagram: `x=65.69`, `top=246.15`, `width=1251.29`, `height=339.18`;
- lower diagram: `x=84.54`, `top=663.68`, `width=1230.97`, `height=337.28`.

## Geometry and metadata limitations

- Slide 1’s Uber heading carries overlapping boxes, including one spanning both title lines. Box roles are not documented.
- Chart tables have bbox confidence 0.98 and concerns such as `layout_lvm_disagreement` / `multi_table_page`, but no table cell records which printed label, bar rectangle, axis, or line point supports its value.
- Diagram code boxes omit some nodes and all explicit connector geometry. A box around selected labels cannot validate a Mermaid edge.
- `images_content_metadata` combines native raster source assets with derivative full-slide renders and semantic crops. It needs an origin field before its count can be interpreted.
- Item-level and datum-level confidence are absent. Page scores cannot localize the flag mistake or distinguish explicit chart endpoints from inferred intermediates.

## Standalone Markdown versus JSON representations

The standalone Markdown equals, page by page, the optional JSON page header, `markdown.pages[i].markdown`, and optional footer joined with blank lines, modulo outer whitespace. `markdown_full` and `text_full` are null.

The item-level representation differs materially:

- slide-2 chart items use pipe-table Markdown and structured rows;
- JSON page-body Markdown—and therefore standalone Markdown—uses HTML tables;
- slide 3 includes Mermaid code in the page body while also carrying separate diagram image crops;
- generated image/flag descriptions may appear as text items even when their bboxes are image-labelled.

Consumers need explicit fields for transcription versus generated description, native versus derived images, and primary versus alternate diagram representations.

## Our baseline output versus source

Reviewed artifacts:

- `runs/baseline-20260728-current/uber-earnings/our-output.json`
- `runs/baseline-20260728-current/uber-earnings/our-output.md`

The baseline reports `success`, three pages, 27 native images, seven detected image regions, two chart regions, and no document warnings. The native image count exactly matches the PDF object inventory (1 + 11 + 15). Region provenance and visual classification are useful, but primary Markdown is polluted by false OCR, hidden construction text, and duplicates, while chart/diagram structure remains largely unmodeled.

| Page | Baseline element or claim | Status | Source-grounded finding |
|---:|---|---|---|
| 1 | Photo classified as `photograph` | **Verified** | Class confidence 0.9881 agrees with the visible photographic source. |
| 1 | Photo “document caption” | **Incorrect** | The source has no photo caption. Baseline emits 18 lines of gibberish beginning `é`, `™=`, `aus` and labels it `caption_source=document_caption`. |
| 1 | Title/date/subtitle text | **Partially verified** | All words are present, but two title lines are collapsed into one heading and `Supplemental Data May 7, 2025` reverses/merges distinct spatial text blocks. The item box covers only the subtitle, not the date. |
| 2 | Market-leadership prose and count 8 | **Verified** | Visible words and number are captured. |
| 2 | Ten-flag region | **Partially verified** | Region is localized, but Markdown only says `[Image detected; no reliable text extracted.]`; no flag identities or per-flag boxes are supplied. |
| 2 | Gross Bookings chart classification | **Verified** | Correctly classified as `bar_chart` with 0.9983 classifier confidence. |
| 2 | Profitability chart classification | **Partially verified** | Primary class is `line_chart`; the source is a combined bar-and-line chart. A secondary `bar_chart` probability exists but no explicit combo-chart structure does. |
| 2 | Printed chart endpoint labels | **Verified** but duplicated | `$56B`, `$82B`, `$0.6B`, `$3.1B`, `1.0%`, and `3.7%` are captured, then repeated through caption/OCR composition. |
| 2 | Intermediate chart values | **Not independently verifiable** / not structured | Baseline correctly avoids asserting the expert’s unprinted 63/73, 1.4/2.3, and 2.2%/3.2% as exact data, but provides no geometry-derived structured series. |
| 2 | Hidden/native construction text in Markdown | **Incorrect** for visible presentation | Non-rendered `90000`, `67500`, `45000`, `22500`, `4000`, `3000`, `2000`, `1000`, and zeros are emitted as ordinary visible text. |
| 2 | Chart OCR text | **Incorrect** in part | Adds `Q1'25 ARR!`, `QU25 ARR!`, `O Adj. EBITDA Margin?`, and apparent `0.01`–`0.04` artifacts not shown on the slide. |
| 2 | `chart_values_not_structured` concerns | **Verified** | Both chart items accurately disclose the missing structured series. |
| 2 | Notes/footer reading order | **Incorrect** | Notes 1–2 are followed by the footer/page number and only then Note 3, although all three source notes form one block above the footer. |
| 3 | Diagram classification | **Verified** with uncertainty | Both regions are classified `flow_chart` at moderate confidence (0.5556 and 0.5071), consistent with the visual topology. |
| 3 | Diagram node text | **Verified** | All printed node labels are captured. |
| 3 | Diagram relationships | **Partially verified** | Baseline avoids the expert’s unsupported directed arrows, but emits no association/edge structure at all. |
| 3 | Footer/logo | **Incorrect** in serialization | `Uber` is emitted once as an OCR image item and again inside the footer, producing a duplicate at the end of Markdown. |
| 1–3 | Printed page labels | **Incorrect** in metadata | JSON labels pages 1, 2, and 3; visible printed labels are 1, 5, and 6. Footer text preserves 1/5/6. |

The cover-image error is especially important for provenance. The item has `include_ocr_in_primary=false`, yet its `.md` still equals the false caption text. `caption_generated=false` and `caption_source=document_caption` imply transcription from a real caption, but the rendered source contains no caption in or adjacent to the photograph. This is neither reliable OCR nor a disclosed generated description.

The page-1 text item also combines `Supplemental Data` with `May 7, 2025` while retaining only the subtitle box `(x=70.09, top=932.77, width=508.11, height=68.91)`. The source date is far away at approximately `(x=1682.34, top=630.42, x1=1850.24, bottom=663.42)`. Consequently, the date has text but no valid item localization.

The slide-2 chart regions are well localized:

- Gross Bookings: approximately `(700.78, 485.70, 1215.73, 862.79)`;
- Profitability: approximately `(1334.82, 441.81, 1851.59, 919.06)`.

Their OCR captures visible endpoints but repeats captions, misreads period labels, and does not bind text to bars/points. Separate native text items expose non-rendered axis/construction labels. As a result, baseline Markdown is less semantically useful than the expert tables even where it is more conservative about unprinted intermediate values.

The slide-3 boxes cover the full diagram regions and are more complete than the expert code-item boxes. However, the absence of any edge/association records means the visual topology is lost rather than over-directed.

Baseline standalone Markdown is exactly the non-empty JSON item `.md` values joined in page and `reading_order` sequence, modulo outer whitespace. Thus false photo-caption text, duplicate chart OCR, hidden tick values, and the repeated slide-3 logo are all intentionally propagated from JSON items into Markdown.

### Confirmed baseline gap disposition

| Gap | Baseline disposition | Evidence |
|---|---|---|
| `GAP-VISUAL-001` | **Confirmed** | False OCR is labeled as a real document caption and placed in primary Markdown. |
| `GAP-VISUAL-001` | Same misclassification not observed; identification remains incomplete | Baseline does not call New Zealand Australia, but supplies no flag identities. |
| `GAP-CHART-001` | **Confirmed** | Charts are classified and localized but values/marks/axes are not structured or provenance-linked. |
| `GAP-DIAGRAM-001` | **Confirmed with opposite failure mode** | Baseline avoids unsupported direction but loses all relationships. |
| `GAP-BBOX-001` | **Confirmed with qualification** | Full diagram boxes are good; edge/node-level evidence is absent. |
| `GAP-OCR-001` | **Confirmed** | Non-rendered construction/axis values leak into Markdown. |
| `GAP-SERIALIZATION-001` | **Confirmed** | Chart endpoints/periods and the slide-3 Uber logo are duplicated. |
| `GAP-ORDER-001` | **Confirmed** | Page-1 date/subtitle and page-2 Note 3/footer sequences do not follow source layout. |
| `GAP-PAGE-001` | **Confirmed** | Page metadata uses sequence 1/2/3 rather than printed 1/5/6. |

## Mapped gaps

These findings use the finalized gap taxonomy while retaining expert and
baseline distinctions, dispositions, and exact source regions.

| Gap | Mapped capability | Exact source region | Why reusable |
|---|---|---|---|
| `GAP-VISUAL-001` | Mark generated image descriptions and distinguish them from source captions | Slide 1 upper photograph | Tests provenance for pixel-grounded natural-language descriptions. |
| `GAP-VISUAL-001` | Small visual-identity misclassification | Slide 2 first flag, approximately `(77.88, 718.8, 162.44, 780.45)` | Tests flag/icon recognition and evidence localization. |
| `GAP-CHART-002` | Distinguish printed values from vector-derived chart estimates and record tolerance | Slide 2 middle and right chart panels | Tests mark/axis provenance, derivation, and rounding for unprinted values. |
| `GAP-DIAGRAM-001` | Avoid converting visual association into unsupported directed edges | Slide 3 upper and lower diagram regions | Tests graph extraction where connectors lack arrowheads. |
| `GAP-BBOX-001` | Provide complete node/edge geometry and box roles | Slide 3 diagram code/image items; slide 1 overlapping title boxes | Tests whether structured visual claims can be independently traced to marks. |
| `GAP-OCR-001` | Suppress non-rendered native construction/axis text from the visible reading view | Slide 2 y-axis/construction values beside both charts | Tests reconciliation of native text with pixel visibility. |
| `GAP-SERIALIZATION-001` | Reconcile native text, OCR captions, regions, and footer logos without duplicates | Slide 2 chart labels; slide 3 bottom-left/footer logo | Tests cross-channel deduplication. |
| `GAP-ORDER-001` | Preserve reading order across widely separated title/date and note/footer regions | Slide 1 date/subtitle; slide 2 bottom notes and footer | Tests ordering and prevents one item box from falsely localizing remote text. |
| `GAP-PAGE-001` | Printed page label not propagated to page metadata | Slide footers 1, 5, and 6 | Reuses the excerpt-pagination gap observed in `postal-10k` and `settlement-agreement`. |

## Open questions

1. Were the unprinted chart values recovered from vector geometry, hidden authoring data, OCR/model estimation, or another channel? The output should disclose the method.
2. What numeric tolerance and rounding policy applies to geometry-derived chart data?
3. Should undirected visual associations be represented as `---` rather than `-->`, or as unlabeled groups until direction is explicit?
4. When both Mermaid and an image crop are emitted, which is canonical, and how should consumers avoid double-counting the diagram?
5. Can `images_content_metadata` separate embedded source images, page renders, region crops, and model-generated descriptions?
