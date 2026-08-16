# Catastrophe Recap Parsing Assessment

**Status:** Analysis only — no production code, dependency, configuration, or API changes  
**Assessment date:** 2026-07-28  
**System assessed:** `document-parse-api` in this workspace  
**Benchmark:** Attached LlamaParse `agentic_plus` result  
**Primary ground truth:** Attached `catastrophe-recap.pdf`, cross-checked against the official [Aon 1H 2025 Global Catastrophe Recap](https://www.aon.com/getmedia/01e165ae-1788-4997-a51b-9225bce850dd/1H-2025-Global-Catastrophe-Recap.pdf)

## Executive summary

The current parser has a credible native-first, local, layout-aware foundation. On this page it preserves the main reading order, extracts the narrative outside one damaged span, reconstructs the Exhibit 7 table accurately, retains table-cell geometry, and correctly avoids inventing chart data. Its Exhibit 7 table is more faithful than the benchmark because the source repeats `United States` in five distinct cells, whereas the benchmark incorrectly creates one five-row span.

The observed failures do not share one root cause:

1. **The sentence damage originates in the source PDF's text layer.** Two embedded Type0 font subsets have actively incorrect `/ToUnicode` maps. Most visible glyph IDs in the damaged runs map to U+0020 spaces. The visible page and embedded TrueType glyph programs are intact. Standard PDFium, pdfplumber, Docling, and the benchmark's own raw-text layer all reproduce the corruption.
2. **Exhibit 7 is successfully detected, then discarded by our normalization.** Docling returns the exact caption and links it to the table. `_docling_table_item()` ignores the relationship, and `_normalize_docling_body()` returns after emitting the table.
3. **Exhibit 8 is merged because picture captions and internal children are treated identically.** The true title is outside and above the chart; damaged internal chart text (`er cas`, `C`) is inside it. `_visual_item()` concatenates both sets as one caption and suppresses their independent elements.
4. **The chart is not parsed as data.** In this run it remains a generic `image` because the optional classifier artifact is missing. More importantly, the codebase has no chart-to-series/value analyzer. Installing the classifier would improve routing, not reconstruct values.
5. **Two avoidable OCR/reconciliation bugs make the chart text worse.** A hexadecimal-token cleanup rule concatenates twelve numeric years, while text-only deduplication collapses spatially distinct repeated years. The `1H` legend is recognized as `iH` at 0.4437 and rejected just below the global 0.45 threshold.
6. **Presentation is not canonical.** Backend Markdown, frontend Markdown, and frontend plain-text normalization apply different rules to the same image item. The same content can therefore be caption-only, caption-plus-OCR, or OCR-only.

The benchmark is useful but is not ground truth:

- Its structured layer repairs the damaged sentence and preserves both titles, proving a downstream or alternate repair step absent from our normalized output. The exact method is proprietary and cannot be established from the result.
- Its chart table has **88 inferred numeric cells, none printed explicitly in the PDF**. The values are approximately measurable from vector bar geometry, but 19 differ from a source-grounded vector estimate by more than $1B. Eight differ by more than $2B. The Americas 2023 row is internally impossible: annual total `2` is less than 1H `3`.
- It duplicates Exhibit 8, creates a false row span in Exhibit 7, replaces visible `AON` with generic `logo`, and supplies no cell-level provenance or uncertainty for the inferred chart data.

The recommended strategy is not to imitate this one benchmark output. It is to build a measurable, source-faithful parser:

- preserve a relationship-rich intermediate representation;
- audit and repair PDF font mappings before OCR;
- escalate suspicious spans or regions rather than whole pages;
- keep OCR words and coordinates through reconciliation;
- preserve captions as separate linked elements;
- add a CPU-cheap, vector-first chart analyzer;
- use optional local or hosted vision only for low-confidence visual regions;
- validate every derived value against source evidence and emit uncertainty instead of false precision;
- serialize once from a canonical intermediate representation.

The recommended next implementation phase, after approval, is a **foundation/correctness phase**: regression fixtures, caption/child relationship fixes, coordinate-aware OCR deduplication, numeric-token cleanup correction, font-health detection with safe recovery/fallback, confidence/provenance separation, and canonical serializer parity. A chart-value service should follow only after these evidence and validation contracts exist.

## Scope and method

### Inputs

The assessment used:

- `catastrophe-recap.pdf`
- `expertmodel-json.json`
- `expertmodel-markdown.md`
- `ourmodel-json.json`
- `ourmodel-markdown.md`
- the complete backend and frontend source in this workspace

### Evidence hierarchy

Claims in this report use this order of authority:

1. visible source page and PDF drawing geometry;
2. PDF content streams, font dictionaries, embedded font programs, and glyph positions;
3. independent native extractors;
4. raw Docling graph and raw OCR diagnostics;
5. normalized JSON/Markdown;
6. semantic/model-generated output.

This avoids treating a polished result as more authoritative than the document.

### Work performed

- Rendered the source page and visually inspected its layout.
- Inspected PDF objects, fonts, `/ToUnicode` maps, content streams, text positions, images, and drawing primitives.
- Compared native extraction from PDFium and pdfplumber.
- Reproduced the current Docling graph using the configured local artifacts.
- Traced each item through loading, extraction, rendering, layout, OCR, normalization, reconciliation, reading order, deduplication, and serialization.
- Compared both systems' JSON and Markdown field by field.
- Calibrated the chart's vector bars against its axes and compared all 88 benchmark cells.
- Reviewed public LlamaParse documentation, SDKs, open-source repositories, public research, pricing, and deployment statements.
- Ran the local backend test suite: **76 passed, 10 integration/model tests skipped, 1 deprecation warning**. The passing tests do not cover the defects identified here.

No production code or dependency was changed. The frontend build was not treated as a valid verification run because the current shell has Node 20.19.6 while `frontend/package.json` requires Node 22.13 or newer.

## Source document anatomy

The attachment is one 612×792 point page, visually page 7 of the Aon report. It contains:

- a vector AON logo;
- two narrative paragraphs;
- an Exhibit 7 caption and a five-row table;
- an Exhibit 8 caption and four-panel stacked bar chart;
- a source note, `Data: Aon Catastrophe Insight`;
- a footer and printed page number.

There are **no raster images** in the PDF. The logo, table, chart bars, axes, and visible labels are vector content or glyphs. The chart is held in a Form XObject.

Important geometry:

| Element | Approximate source bbox/top |
|---|---:|
| Exhibit 7 caption | x 100.7–348.6; top 210.84–219.84 |
| Exhibit 7 table | top 230.14 |
| Exhibit 8 caption | x 100.7–316.8; top 402.02–411.02 |
| Exhibit 8 chart | top 437.31; bottom 586.37 |
| Source note | top about 591.1–592.1 |

The two exhibit titles are visibly separate from their objects. The Exhibit 8 title is roughly 26 points above the chart region.

## End-to-end pipeline trace

| Stage | Current path/configuration | What happened on this sample |
|---|---|---|
| Input loading | `app/services/input_documents.py:428-447` | PDF bytes pass through unchanged. No corruption is introduced here. |
| Native extraction | `app/services/pipeline.py:252-317` | PDFium `get_text_bounded()` honors the bad `/ToUnicode` map and returns the damaged sentence/chart labels. |
| Font/Unicode validation | No dedicated stage | The parser does not audit font maps, glyph advances, improbable space mappings, or embedded-font alternatives. |
| Docling conversion | `pipeline.py:360-429` | OCR and accurate TableFormer are enabled; remote services are disabled; full-page OCR is not forced. Docling returns the same damaged native text but correctly finds the titles and table. |
| Selective visual routing | `pipeline.py:3098-3241`; defaults in `app/config.py:97-115` | Page-level native/layout coverage is high, so no page OCR is requested. Only the logo and chart become rendered visual regions. |
| Page/region rendering | `app/services/ocr.py:212-260,853-983` | Regions render at target scale 5, bounded by 16M pixels, with only 3pt padding. The chart crop excludes the source note. |
| Layout detection | Docling graph | Table caption, picture caption, table, chart picture, internal chart children, and footer are all detected. |
| Region classification | `pipeline.py:432-458,1797-1821` | Configured Docling artifacts lack the optional picture classifier, so the chart remains `image`. |
| OCR | `ocr.py:625-693` | Tesseract PSM 3 and PSM 11 recover axes, region labels, repeated years, and part of the legend. They cannot infer bar heights as data. |
| Table analysis | Docling plus `app/services/tables.py` | Exhibit 7 cells are extracted well. pdfplumber geometry support is table-specific; chart curves are not analyzed. |
| Chart/diagram analysis | No structured chart service | Flat OCR is retained; no axes/series/mark/value reconstruction exists. |
| Caption association | `pipeline.py:1326-1408,1836-1844,1987-2130` | Exhibit 7 caption is dropped; Exhibit 8 title and internal children are merged. |
| Reading order | `pipeline.py:2628-2805` | Remaining main elements are ordered sensibly, but missing/merged elements cannot be repaired here. |
| Native/OCR reconciliation | `pipeline.py:2149-2542,2884-2957` | There is no page-source OCR for the damaged narrative. Native and Docling agree on the same bad text, creating false confidence. |
| Deduplication | `pipeline.py:1849-1858` and OCR overlap merge | Repeated text is deduplicated by string rather than source position at the visual-item stage. |
| Backend Markdown | `app/services/serializer.py:38-118` | Content-region images prefer caption, potentially excluding OCR. |
| Frontend Markdown | `frontend/lib/serialize-output.ts:13-38` | Uses `item.md` directly, which includes the merged caption and flattened OCR. |
| Frontend plain text | `frontend/lib/normalize-document-json.ts:126-175` | For images, prefers `ocr_text`, which can omit the caption. |

### Relevant runtime snapshot

| Setting/component | Observed/default value | Relevance |
|---|---:|---|
| Docling | 2.114.0 | Layout, reading order, TableFormer, picture graph |
| pypdfium2 | 5.12.1 | Native text and selective rendering |
| pdfplumber | 0.11.10 | Vector table and drawing inspection |
| Tesseract language | `eng` | No multilingual alternative was active |
| Docling OCR | enabled; PSM 3; `force_full_page_ocr=false`; bitmap threshold 0.05 | Searchable damaged text was not automatically re-read |
| TableFormer | `ACCURATE` | Exhibit 7 structure is strong |
| Targeted render scale | 5 (about 360 DPI) | Applied to logo/chart regions |
| Targeted crop limit | 16M pixels; 30s timeout; 3pt padding | Source note falls outside the chart crop |
| Primary OCR threshold | 0.45 | `iH` at 0.4437 is rejected |
| Informative low-confidence length | 8 alphanumeric characters | Too long to rescue a two-character legend token |
| Picture classifier threshold | 0.60 | Classifier did not run because its artifact was unavailable |
| Semantic picture description | disabled | Existing SmolVLM path did not run and is not a chart-table parser |
| PDF visual analysis | enabled | Only selected regions were rendered |
| Page OCR native minimum | 24 alphanumeric characters | This page easily passes despite a locally damaged span |
| Page layout coverage minimum | 0.55 | Measured page coverage about 0.795 suppresses page OCR |

## Root-cause analysis

### 1. Corrupted `Windstorm Éowyn … (€620 million)`

#### Exact origin

The source uses a Type0, `Identity-H` font subset for the damaged spans. It has:

- an embedded TrueType font program;
- `/CIDToGIDMap /Identity`;
- a `/ToUnicode` CMap that exists but is wrong.

Most distinct, visible non-space glyph CIDs map to U+0020. This is more dangerous than a missing map because extractors regard the mapping as authoritative.

For example, the source CID sequence:

```text
0078 00D5 00EE 00BC 0108 010F 00F5 0104 00ED 0003
001D 00F5 0120 0126 00EE
```

resolves through the embedded font's glyph identities to:

```text
Windstorm Éowyn
```

The `/ToUnicode` map instead preserves only a few characters, producing the observed `É w`. The same method recovers `€620 million` from its CID sequence. A second malformed bold Type0 subset causes internal chart headings to degrade to `er cas` and `C`.

The official Aon PDF has the same native-extraction corruption, so this is not caused by the one-page attachment process.

#### Why our pipeline does not repair it

- PDFium and Docling both honor the same source mapping.
- `_text_item()` at `pipeline.py:752-796` collapses whitespace and discards the raw glyph-level alternative.
- `_normalized_search_text()` at `pipeline.py:236-249` is ASCII-oriented, so Unicode evidence is weakened during comparisons.
- `_select_pdf_render_requests()` at `pipeline.py:3120-3241` evaluates page-global native character count and native/layout token coverage. On this page, native alphanumeric count is 1,010 and measured layout coverage is about 0.795, above the 0.55 threshold.
- Because two extractors agree on the same bad source mapping, agreement is mistakenly treated as correctness.
- `force_full_page_ocr=False` means searchable text is not automatically re-read visually.

The responsible stages are **font/Unicode validation and selective visual routing**, with a later reconciliation gap. This is not a serializer defect.

#### Why the benchmark differs

The benchmark's raw `text.pages[0].text` contains the same corruption, while its normalized item and Markdown contain the repaired sentence. That proves a later or alternate repair layer. It does **not** reveal whether the repair came from:

- embedded-font recovery;
- targeted OCR;
- a rendered-page vision pass;
- language-model completion;
- or a combination.

The repaired benchmark tokens have no token-level source boxes; its native sub-boxes visibly skip the repaired gaps. The mechanism and its error controls are therefore unknown.

#### Reusable solution

Add a PDF font-integrity audit before accepting native text:

1. inspect used Type0 fonts and mappings;
2. flag many-to-one collapse to spaces, replacement characters, private-use code points, or improbable glyph/advance patterns;
3. when `Identity-H`, identity CID-to-GID mapping, and an embedded TrueType cmap agree, produce a font-derived candidate;
4. preserve original and candidate glyph runs with font object, bbox, and method;
5. validate uncertain runs against a tight 300–400 DPI line crop;
6. select or flag the candidate using evidence agreement, never language plausibility alone.

This exact sample can be repaired deterministically without OCR. Generic font repair is conditional: some PDFs lack a usable embedded font, use custom/non-identity mappings, or intentionally obfuscate text. Those cases require targeted OCR or remain uncertain.

#### Implications

- **Accuracy:** High gain for broken custom fonts; avoids OCR errors when glyph evidence is intact.
- **Latency:** Low. Audit once per used font and cache the mapping; targeted OCR only for unresolved spans.
- **Memory:** Low incremental memory, primarily font tables and glyph-run evidence.
- **Deployment:** CPU-only and offline.
- **Licensing:** A robust font parser may add a small dependency; verify its software license. Inspect embedded fonts in memory and do not redistribute extracted font programs.

### 2. Missing Exhibit 7 title

#### Exact origin

Raw Docling output contains:

- table `#/tables/0`;
- exact caption text `#/texts/1`;
- both `captions` and `children` references from the table to that text;
- a correct caption bbox above the table.

The caption is lost after layout detection:

- `_normalize_docling_body()` handles the table and returns at `pipeline.py:2033-2041`.
- `_docling_table_item()` at `pipeline.py:1326-1408` normalizes cells but ignores captions, children, footnotes, and related references.
- The caption is not independently present in the top-level body order, so it is never emitted.

This is a **normalization and relationship-preservation bug**. It is not caused by Unicode, OCR, cropping, reading order, deduplication, or serialization.

#### Why the benchmark differs

The benchmark preserves a separate caption-like item with bbox confidence 0.96 and serializes it as bold text. That is consistent with a layout graph that retains external caption relationships.

#### Reusable solution

- Preserve captions as distinct elements.
- Add a typed `caption_of` relationship to the table.
- Keep the caption's own bbox, source, and confidence.
- Place it immediately before the table in reading order when geometry and graph order agree.
- Do not force every caption into the document heading hierarchy; `caption` is a distinct semantic role.
- Retain table footnotes/source notes through the same relationship mechanism.

Cost and memory are negligible; no new dependency is required.

### 3. Exhibit 8 merged into the chart

#### Exact origin

Docling distinguishes:

- true caption `#/texts/3`, outside and above the picture;
- internal children `#/texts/4` and `#/texts/5`, inside the picture and damaged by the second font map;
- the chart picture itself.

`_visual_item()` loops over both `captions` and `children` at `pipeline.py:1836-1844`, appending every referenced string to one `child_values` list. It then:

- makes all of them `document_caption`;
- concatenates that caption with accepted OCR;
- assigns only the chart bbox to the combined item;
- marks all referenced children seen so they cannot be emitted separately.

The resulting item begins with a title whose source bbox is outside its own bbox, followed by meaningless internal fragments.

This is a **caption-association and provenance-model bug**. Reading-order and serialization only expose the already-merged object.

#### Why the benchmark differs

The benchmark preserves a separate title item and a separate chart-region item. However, it then duplicates the title as both a Markdown heading and an HTML `<caption>` inside the chart-derived table. Its chart item bbox also excludes the duplicated title. It therefore demonstrates better initial separation but imperfect final deduplication.

#### Reusable solution

- Treat only `captions` as caption candidates.
- Retain `children` as internal region evidence with their own bboxes.
- Use geometry to reject a child as caption evidence when it lies inside the visual and the declared caption lies outside it.
- Model `caption_of`, `source_note_of`, `legend_of`, and `contains` explicitly.
- Never flatten related elements before reading order, validation, and serialization.

### 4. Unusable chart text and absent data

#### Classification and routing

The raw region is labeled `picture`. The configured artifact directory lacks the optional Docling picture classifier, so `_visual_content_type()` returns `image`. The Dockerfile downloads the classifier, meaning this particular routing failure is environment-specific.

Installing the classifier is not a chart parser. Current tests intentionally assert that chart items contain no `series` or `visible_values` and carry `chart_values_not_structured`.

#### OCR failures

The chart crop is rendered at target scale 5, approximately 360 DPI. Tesseract recovers:

- `Americas`, `APAC`, `EMEA`, `USA`;
- axis ticks `25` through `125`;
- all twelve visible year labels;
- `Annual total`;
- `1H` as low-confidence `iH`.

Two code paths degrade those candidates:

1. `_join_split_hex_tokens()` at `ocr.py:516-539` accepts `[A-F0-9]{2,}`. Pure-digit years therefore look like hexadecimal chunks, and twelve years exceed the 24-character join threshold.
2. `_visual_item()` applies `dict.fromkeys()` to accepted text at `pipeline.py:1849-1858`. This removes repeated labels based on text alone, even when their bboxes differ across four panels.

The raw diagnostics still contain the twelve individual year boxes, so the loss is introduced during normalization, not OCR recognition.

`iH` has confidence 0.4437, just below the 0.45 primary threshold. Its two characters are too short for the relaxed rule requiring eight alphanumeric characters. A single global threshold is inappropriate for short legend tokens when color swatch and legend geometry provide supporting evidence.

#### Missing source note

The chart picture ends near y=586.37. Rendering adds only 3 points of padding, ending near y=589.37. The source note begins around y=591.1–592.1 and is omitted from the crop. Its native font map is also damaged, so no other path recovers it.

This is a **relationship/crop-selection failure combined with the font issue**. A source note should be a linked external element, not accidental crop padding.

#### No structured chart stage

OCR cannot derive unprinted bar heights. The source provides rich vector geometry, but `app/services/tables.py` uses thin drawing rules only to infer table boundaries. It does not analyze chart axes, ticks, marks, series colors, groups, or stacked segments.

A reusable chart service should use this priority:

1. embedded Office chart data or accessible PDF metadata, if present;
2. PDF vector marks and text/glyph geometry;
3. raster CV plus coordinate-aware OCR;
4. optional vision model for ambiguous structure;
5. validation, uncertainty, and human review for unresolved values.

The output should distinguish:

- `explicit_text`;
- `embedded_data`;
- `vector_measured`;
- `raster_measured`;
- `model_inferred`;
- `unresolved`.

Every data point should include the relevant source mark bbox/path, axis calibration, units, method, confidence, and numeric tolerance.

### 5. Logo handling

Our OCR correctly reads `AON` at 0.967, but the primary image item has an empty value and `include_ocr_in_primary=false`. The attached frontend-generated Markdown emits a generic image placeholder. The plain-text normalization can expose `AON`, creating another representation mismatch.

The benchmark instead outputs generic `logo`, which is semantic inference and loses the visible brand text. Source-faithful output should keep `AON` as subordinate visible text and may additionally classify the region as a logo.

### Additional discrepancy: physical versus printed page identity

The attachment's physical page index is 1, but the visible report page number is 7. Our `page_index`, `page_number`, and `page_label` are all `1`; the benchmark also identifies the physical page as 1 while carrying `7` only inside its footer markup.

`_PAGE_NUMBER_RE` at `pipeline.py:47` recognizes only forms like `Page X of N`, so `_native_pdf_pages()` at `pipeline.py:292-300` cannot promote this bare footer number to a printed label. A reusable model should keep these concepts separate:

- physical page index;
- embedded PDF page label;
- detected printed page label;
- confidence and source bbox for the detected label.

Footer-layout detection can recover this case cheaply, but should not overwrite the physical index used for array access.

### 6. Confidence, provenance, concerns, and serialization

Our chart item confidence 0.9565 is essentially confidence in accepted OCR text. It is not chart-detection, legend-completeness, structural, or value-extraction confidence. Presented as a single item confidence, it is badly calibrated: the item is missing a legend token, all values, the source note, and correct year structure. `parse_concerns` is empty because the region was not classified as a chart.

The benchmark has page confidence 0.669, chart bbox confidence 0.98, and repaired paragraph bbox confidence 0.99, but:

- reconstructed chart cells have no cell bboxes, confidence, provenance, or tolerance;
- repaired paragraph tokens have no token-level grounding;
- parse concerns mention only that two tables occur on the page;
- the raw and normalized text disagree.

Confidence should be multidimensional:

```text
detection_confidence
recognition_confidence
structure_confidence
relationship_confidence
value_confidence
grounding_confidence
validation_status
```

The current serializer split should be removed. JSON should carry structured elements and a canonical presentation block. Backend and frontend clients should render that contract, not reinterpret image semantics independently.

### Remediation impact summary

| Issue/remediation | Accuracy effect | Latency/CPU | Memory | Deployment | Licensing |
|---|---|---|---|---|---|
| Font audit + safe cmap recovery | High on damaged embedded fonts; neutral when healthy; uncertain cases remain flagged | Low per-font cached work; optional OCR only for unresolved spans | Low | CPU-only, offline | Small parser dependency may need review; do not redistribute embedded fonts |
| Exhibit 7 caption preservation | Restores omitted content and relationship | Negligible | Negligible relationship records | No runtime/model change | No new exposure |
| Exhibit 8 caption/child separation | Removes noise, fixes bbox/provenance and order | Negligible geometry checks | Small IR growth | No runtime/model change | No new exposure |
| Coordinate-aware OCR cleanup/dedup | Preserves repeated labels and prevents joined years | Negligible relative to OCR | Modest increase from words/alternatives | CPU-only, offline | No new model; existing OCR terms |
| Source-note relationship/crop routing | Restores notes without blanket page OCR | Small extra crop only when native/font evidence fails | Low transient bitmap memory | CPU-only, offline | No new exposure |
| Vector-first chart service | Large gain for common vector charts; values remain approximate | Low-to-moderate CPU by chart complexity | Low for primitives/graphs | CPU-only and offline for vector path | Existing PDF stack; new CV libraries require review only if added |
| Raster/VLM chart fallback | Improves difficult raster coverage; hallucination risk remains | Potentially seconds/region, GPU or API | Hundreds MB to many GB locally | Optional GPU or hosted service | Model-card/vendor terms and data processing review |
| Canonical serializer | Eliminates representation drift; no extraction gain | Negligible | Negligible | Simplifies clients | No new exposure |
| Multidimensional confidence/concerns | Improves calibration, audit, and safe escalation | Cheap deterministic aggregation/validation | Small metadata increase | Adds observability and review policy | No new exposure unless retries invoke models |

## Detailed sample-level comparison

| Field | Source | Our output | Benchmark output | Assessment |
|---|---|---|---|---|
| Text completeness | Full narrative visible | Loses `Windstorm`, most of `Éowyn`, and `620 million` | Repaired in items/Markdown; broken in raw text | Benchmark presentation wins, but its repair provenance is absent. |
| Unicode correctness | `Windstorm Éowyn … (€620 million)` | `É w … (€ )` | Correct normalized text | Root cause is bad source mapping; deterministic recovery is possible here. |
| Exhibit 7 caption | Separate caption above table | Missing | Separate bold caption | Our layout graph had it; normalization dropped it. |
| Exhibit 8 caption | Separate caption above chart | Merged into image with noise | Separate, then duplicated inside chart table | Our relationship handling is wrong; benchmark deduplication is also wrong. |
| Main reading order | Logo, paragraph, Exhibit 7, table, paragraph, Exhibit 8, chart, note, footer | Main surviving elements ordered correctly | Mostly correct, but title duplicated and logo moved late | Both need relationship-aware final ordering. |
| Exhibit 7 cells | Five separate `United States` cells | Correct five values and 30 cell boxes | False `rowspan=5`; rows/CSV blank four locations | Our table is more source-faithful. |
| Table structure | Five columns, header plus five rows | Correct | Mostly correct except false row span | Our output wins this sample. |
| Chart-region detection | Four-panel stacked bar chart | Generic `image`; classifier unavailable | Chart bbox emitted as `table`, label `chart` | Benchmark routes to chart analysis; ours lacks robust fallback routing. |
| Chart-title association | External title | Title, `er cas`, and `C` flattened into chart | External title plus duplicated table caption | Neither final representation is fully correct. |
| Axis extraction | Ticks 25–125 | Recognized as flat OCR | Reflected implicitly in derived values; not emitted as structured axis | Our OCR sees labels but lacks schema; benchmark lacks auditable axis representation. |
| Legend extraction | Light = Annual total; dark = 1H | `Annual total` only; `iH` rejected | Encoded into table columns | Benchmark is more usable, but no legend provenance is supplied. |
| Series extraction | Four regions | Region labels OCR'd | Four structured region series | Requires chart service, not generic OCR cleanup. |
| Year labels | 2015–2025 positions, only selected years printed per panel | One 48-digit string plus one deduplicated triplet in primary item; all positions remain in diagnostics | Eleven table rows 2015–2025 | Our normalization destroys positional repetition. |
| Chart values | Not printed; approximately measurable from vector bars | None | 88 integers | Benchmark is more actionable, but 19 cells fall outside the selected ±$1B vector-measurement tolerance. |
| Source note | Visible below chart | Missing | Correct separate text | Our crop/relationship selection excludes it. |
| Page identity | Physical attachment page 1; printed report page 7 | All page identity fields are `1`; `7` survives only in footer text | Page number `1`; `7` survives in footer markup | Both need a separate printed-page-label field with provenance. |
| Diagram support | Not present on this page | Schema/routing exists; no relationship extraction | Not evaluated by this sample | Broader benchmark required. |
| OCR noise | No source noise | `er cas`, `C`, joined years; low-confidence raw noise retained in diagnostics | Polished output | Benchmark likely has stronger semantic post-processing, but exact mechanism unknown. |
| Native/OCR reconciliation | Bad native map should trigger local repair | Page-level agreement suppresses fallback | Structured layer repairs raw layer | Per-span anomaly detection is required. |
| Bounding boxes | All visible elements locatable | Good item/table-cell/OCR boxes; merged title lies outside chart bbox | Good item boxes; no chart-cell boxes; duplicated title outside chart bbox | Our lower-level OCR geometry is richer; both normalized graphs are inconsistent. |
| Confidence | Must distinguish evidence dimensions | Null for native items; over-high chart OCR confidence | Page 0.669; high bbox scores; no chart-cell uncertainty | Neither is sufficiently calibrated for audit use. |
| Provenance | Native glyphs/vector paths available | Good table/OCR evidence but flattened item source | Sparse; repaired/chart-derived values lack token/cell evidence | Our architecture can become stronger here without a large model. |
| Parse concerns | Bad font, missing relationship, unstructured chart, rejected legend, source note omission | Empty on chart; no font warning | Only `multi_table_page` | Both under-report the material risks. |
| Markdown | Should mirror canonical IR | Missing Exhibit 7; noisy merged chart; logo placeholder | Correct sentence; false row span; duplicate Exhibit 8; unsupported values | Neither is a faithful canonical view. |
| JSON | Should preserve evidence and relationships | Rich OCR/table detail but no relationships/chart data | Polished items but weak derivation provenance | A common evidence-rich IR is preferable. |
| Missing content | None | Sentence spans, Exhibit 7, `1H`, source note, chart data | Visible `AON` text; four repeated table locations | Both omit source content. |
| Duplicated content | None | Chart has joined plus individual year alternatives across layers | Exhibit 8 appears twice | Both need evidence-aware deduplication. |
| Unsupported/fabricated content | None | No fabricated numeric data; contains meaningless damaged fragments | Source-inconsistent row span and 19 chart cells outside the selected vector tolerance; `logo` is supported classification but loses visible `AON` | Benchmark must not be used as unreviewed ground truth. |

## Chart ground-truth validation

### What is and is not present

The PDF contains:

- vector bar segments;
- vector/text axes, tick labels, years, regions, and legend;
- no bar-value labels;
- no `/ActualText` values for the bars;
- no embedded spreadsheet or chart dataset;
- no raster image.

Therefore:

- **labels and legend are recoverable** from glyph/font evidence or OCR;
- **values are derived measurements**, not extracted literal text;
- exact hidden source data is unavailable;
- values near rounding boundaries need an explicit tolerance.

### Vector calibration

In the chart Form XObject:

- baseline is approximately y=12.515;
- tick positions for 25, 50, 75, 100, and 125 are about 18.635, 24.875, 30.995, 37.115, and 43.235;
- fitted scale is about 0.245897 form units per $B;
- dark segment height represents 1H;
- dark plus light segment height represents annual total;
- coordinates are quantized in roughly 0.12 form units, about $0.49B.

This supports approximate, provenance-bearing measurements. It does not justify unqualified exact integers.

### Source-grounded estimates

Values below are approximate `$B`, shown as `1H / annual total`. The tolerance counts use the two-decimal estimates shown here; calibration was performed at higher internal precision.

| Region | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Americas | 1.95/3.90 | 5.86/7.81 | 1.46/54.17 | 1.95/2.93 | 1.46/5.37 | 2.93/3.90 | 2.93/4.88 | 3.42/6.34 | 1.95/6.83 | 2.44/9.27 | 1.46/1.46 |
| APAC | 4.39/11.22 | 10.25/17.57 | 3.42/8.78 | 2.93/33.67 | 2.93/28.79 | 3.90/11.71 | 6.34/12.20 | 8.78/13.18 | 3.42/7.32 | 3.42/4.88 | 1.46/1.46 |
| EMEA | 3.42/10.74 | 8.78/11.71 | 4.39/13.66 | 9.27/17.08 | 8.30/14.64 | 7.81/12.69 | 11.71/32.21 | 19.03/20.98 | 11.71/31.23 | 8.30/20.50 | 5.37/5.37 |
| USA | 20.50/31.23 | 23.91/42.94 | 28.79/125.91 | 22.94/78.08 | 29.28/49.29 | 33.67/100.53 | 42.94/110.78 | 36.60/118.10 | 54.66/85.89 | 56.12/118.59 | 91.75/91.75 |

Using deliberately generous comparison bands:

- 54 of 88 benchmark cells are within ±0.5B;
- 15 are 0.5–1.0B away;
- 19 are more than 1.0B away;
- 8 are more than 2.0B away.

Cells more than 1.0B away:

- **Americas:** 2018 annual; 2019 1H; 2020 both; 2021 both; 2022 annual; 2023 both; 2024 annual; 2025 both.
- **APAC:** 2024 both; 2025 both.
- **EMEA:** 2019 1H; 2020 1H.
- **USA:** 2021 annual.

The clearest discrepancies over 2B are Americas annual values for 2018 and 2020–2024, plus both APAC 2024 values. Americas 2023 is also logically invalid in the benchmark before geometry is considered: annual `2` cannot be less than first-half `3`.

### Interpretation

It is possible that the benchmark used vector measurement, a vision model, semantic completion, or several passes. Its many good values are consistent with recoverable geometry. The erroneous cluster in the smaller Americas/APAC panels is also consistent with an imperfect visual/chart reconstruction pass. The result alone cannot identify the mechanism.

These should be classified as **unsupported derived values outside the selected vector-measurement tolerance**. The logical impossibility and the largest geometry conflicts are source-inconsistent; applying that stronger label to every borderline cell, or calling every one a VLM hallucination, would overstate what the evidence proves.

## Public LlamaParse research

Sources were reviewed as available on 2026-07-28.

### Publicly documented facts

1. The attached job declares tier `agentic_plus`, `cost_optimized=false`, and `triggered_auto_mode=false`. Its raw parameters are not included.
2. The current [LlamaParse create API](https://developers.api.llamaindex.ai/api/python/resources/parsing/methods/create/) documents four tiers: rule-based `fast`, `cost_effective`, `agentic`, and `agentic_plus`; it also exposes dated version pinning.
3. The API documents conditional auto-mode rules, page-tier overrides, high-resolution OCR, crop boxes, layout extraction, spatial text, aggressive table extraction, granular cell/line/word bboxes, and a `fail_on_buggy_font` control.
4. The API describes `specialized_chart_parsing` as AI-powered with `efficient`, `agentic`, and `agentic_plus` modes, automatically enabling layout and precise bounding boxes.
5. LlamaIndex's [LlamaParse v2 article](https://www.llamaindex.ai/blog/introducing-llamaparse-v2-simpler-better-cheaper) says v2 routes to models behind a tier abstraction and lets clients pin versions. It lists 1, 3, 10, and 45 credits/page for the four tiers.
6. LlamaIndex's [Agentic OCR article](https://www.llamaindex.ai/blog/agentic-ocr) describes an architecture using multimodal reasoning, visual grounding, document-type recognition, specialist tasks, internal consistency checks, and self-correction. This is a vendor architectural description, not source-code disclosure or proof that every attached page used every layer.
7. The official [Python SDK](https://github.com/run-llama/llama-parse-py) is an MIT-licensed cloud API SDK. It is not the server implementation.
8. [LiteParse](https://github.com/run-llama/liteparse) is a separate Apache-2.0 local parser. Its public architecture uses PDFium native extraction, selective Tesseract/HTTP/custom OCR, native/OCR merge, and spatial projection. Its README explicitly distinguishes it from proprietary cloud LlamaParse for complex layouts, charts, handwriting, and scans.
9. LlamaParse is [not open source](https://www.llamaindex.ai/pricing). Public deployment options are SaaS and enterprise cloud/VPC arrangements, not a redistributable offline server binary. The pricing page states 1,000 credits = $1.25 and a default 48-hour cache that can be disabled.
10. [ParseBench](https://arxiv.org/abs/2604.08538) evaluates about 2,000 enterprise pages across tables, charts, content faithfulness, semantic formatting, and grounding. Its public [repository](https://github.com/run-llama/ParseBench) lists LlamaParse Agentic at 84.88 overall and 78.11 on charts, while concluding no method is consistently strong across all dimensions.

### Evidence-based inferences for this sample

| Observation | Reasonable inference | Confidence |
|---|---|---|
| Raw text is damaged; normalized text is repaired | A downstream or alternate repair pass exists | High |
| Titles have separate caption bboxes | Layout/caption classification survives into structured output | High |
| Chart becomes a table with chart bbox | A chart-specific visual/semantic pass likely ran | High |
| Chart values are not printed | Values were measured or inferred, not native-text extracted | Certain |
| Many values match vector bars | Vector geometry and/or competent visual measurement may have contributed | Medium |
| Nineteen values fall outside the selected ±$1B vector tolerance | Verification is incomplete or the reconstruction made errors | High |
| No token/cell provenance is present | The result cannot demonstrate how repairs/values were obtained | High |

### Unknown or proprietary

The public evidence does not establish:

- the native PDF engine used for this job;
- the OCR engine or engines;
- the layout detector;
- the selected model provider/model/version behind `agentic_plus`;
- render DPI, crop logic, or retry count;
- whether the broken sentence used font recovery, OCR, VLM, or language completion;
- whether vector chart primitives were read directly;
- prompts, thresholds, confidence calibration, or reconciliation rules;
- how the chart's 88 values were generated;
- whether a numerical verifier ran and, if so, why it accepted an annual total below 1H.

The public `llama_index`, SDK, LiteParse, and benchmark repositories must not be presented as the commercial server implementation.

### Reproducible and non-reproducible capabilities

**Reproducible locally with existing evidence and engineering:**

- native/visual multi-pass extraction;
- per-region high-resolution rendering and OCR;
- font-map health checks and conditional embedded-font recovery;
- caption/layout relationship preservation;
- coordinate-aware native/OCR reconciliation;
- vector chart axes/marks/series measurement for common chart types;
- deterministic numerical and structural validation;
- bounding boxes, provenance, concerns, and confidence components;
- selective escalation.

**Reproducible with optional models but not guaranteed:**

- stronger chart/diagram region classification;
- semantic image descriptions;
- chart structure interpretation when raster geometry is ambiguous;
- diagram node/connector interpretation;
- confidence-aware repair suggestions.

**Not reproducible from public evidence:**

- exact LlamaParse server behavior;
- exact `agentic_plus` model routing and prompts;
- proprietary verifier/retry logic;
- commercial quality/latency without running broad matched benchmarks.

## Proposed shared target architecture

```text
PDF adapter              Image adapter             Office adapter
glyphs/fonts/text         pixels/EXIF/frames        XML/text/tables/charts
vectors/images/renders    camera/scan quality       shapes/media/data/fallback
          \                    |                    /
           \                   |                   /
            +------ Common evidence ingestion -----+
                              |
                 Document / Page / Region / Element
                              |
        +---------------- Evidence graph ----------------+
        | native glyph runs | OCR words | vector marks   |
        | layout regions    | model observations         |
        | bboxes/transforms | alternatives/provenance    |
        +-----------------------------------------------+
                              |
        layout / OCR / tables / charts / diagrams / forms
          caption links / reading order / reconciliation
           validation / confidence / escalation policy
                              |
                    Canonical normalized IR
                              |
            JSON / Markdown / text / future serializers
```

### Adapter responsibilities

**PDF adapter**

- preserve bytes, page geometry, labels, rotations, and transforms;
- extract glyph runs, font objects, native text, vector primitives, annotations, and embedded media;
- audit font maps;
- expose selective page/region rendering;
- prefer native/embedded/vector evidence before pixels.

**Image adapter**

- validate signature and decoded dimensions;
- apply EXIF orientation and frame handling;
- detect scan/photo quality, skew, perspective, and rotation;
- enter the shared visual evidence path directly.

**Office adapter**

- read native XML text, styles, tables, relationships, chart workbooks/data, shapes, and embedded media;
- preserve source relationships;
- use rendering/conversion only as a fallback;
- pass native and visual evidence into the same IR.

**Future adapters**

- implement source loading and evidence extraction only;
- do not create format-specific copies of OCR cleanup, chart parsing, deduplication, validation, or serialization.

### Core intermediate representation

Minimum first-class records:

- `Document`, `Page`, `Region`;
- `TextSpan`, `Heading`, `Caption`, `Table`, `Chart`, `Diagram`, `Image`, `Form`, `Header`, `Footer`, `SourceNote`;
- `Evidence` records for native glyph, recovered glyph, OCR word, vector mark, embedded data, layout observation, and model observation;
- `Relationship` records such as `contains`, `caption_of`, `source_note_of`, `legend_of`, `axis_of`, `connects_to`, and `reading_before`;
- `Hypothesis` records when evidence conflicts;
- separate confidence dimensions and validation outcomes.

Every transformed claim should retain:

```text
source element/region
method
source bbox/path
transform
confidence components
validation checks
numeric tolerance where applicable
```

### Reconciliation principles

- Native-first does not mean native-blind trust.
- Agreement between two engines using the same damaged text layer is not independent evidence.
- Deduplicate evidence only when strings and geometry overlap; repeated text at different coordinates is meaningful.
- Never use semantic plausibility to silently overwrite source evidence.
- When evidence conflicts, retain alternatives and a concern or escalate.
- A validator may reject or flag `annual < 1H`; it must not invent a replacement value.

## Tiered, lightweight processing strategy

The ranges below are planning estimates, not benchmark measurements. Actual latency depends on page area, hardware, concurrency, and model choice. The attached run took 3.365 seconds with local Docling plus two rendered OCR regions.

| Tier | Work | Trigger | Expected quality effect | Incremental latency/resource order | Deployment/cost |
|---|---|---|---|---|---|
| **1. Native + deterministic evidence** | Native text/glyphs, font audit, layout graph, table extraction, vector inventory, relationship preservation | Every document | Fixes omissions/relationships; can exactly repair this font case | Usually tens of ms/page beyond existing native/layout work; low memory; CPU | Offline; no GPU; near-zero marginal infrastructure cost |
| **2. Selective visual verification** | Tight span/region renders, word-level PSM variants, rotation/language checks, coordinate-aware merge | Bad font, scan, low coverage, anomalous glyph run, low-confidence region | Recovers damaged/scanned text and short labels without whole-page OCR | Roughly 0.1–1.5s per crop on CPU; tens to low hundreds MB transient | Offline with Tesseract; bounded cost proportional to escalated area |
| **3. Targeted structure analyzers** | Table repair, vector/raster chart analysis, form graph, diagram primitive analysis | Detected table/chart/form/diagram or validator concern | Major structural gain; vector chart path can recover this sample approximately | Vector work often tens–hundreds ms; raster CV/model work higher; modest-to-medium memory | CPU-first; optional small local models; additional engineering/ops |
| **4. Optional visual model** | Local VLM or hosted multimodal analysis with constrained schema and grounding | Ambiguous complex region after tiers 1–3 | Better semantic descriptions and difficult visual structure; hallucination risk remains | Small local VLMs: hundreds MB–several GB and seconds on CPU; hosted: network/model latency | GPU optional but useful; hosted adds per-call cost/privacy; model licenses vary |
| **5. Validation and retry** | Geometry checks, totals, axis/mark consistency, caption uniqueness, evidence coverage, calibrated retry/human review | Failed constraints or low combined confidence | Reduces unsupported output; surfaces uncertainty | Deterministic checks are cheap; retry multiplies only escalated-region cost | Works offline; operational complexity comes from queues, review, and observability |

### Deployment profile by tier

| Tier | GPU | Model/asset footprint | Offline | Licensing exposure | Operational complexity |
|---|---|---|---|---|---|
| 1 | None | No new model weights; small font/vector metadata | Yes | Existing PDF/layout dependencies; optional font-parser review | Low |
| 2 | None | Existing Tesseract binary and language data, typically tens of MB per language family | Yes | Tesseract/language-pack distribution and notices | Low–medium: crop queues, timeouts, language routing |
| 3 | None for vector analysis; optional for learned raster analysis | No new weights for vector path; classifiers/CV models can add tens to hundreds of MB; existing TableFormer/Docling assets remain | Yes when local assets are packaged | Per-model and native-CV dependency review | Medium: content-type routing, analyzers, validation |
| 4 | Optional but strongly beneficial for local VLMs | Planning range from small ≈0.25–2B models to 3–7B+ models; roughly 0.5–15GB of weights depending on model and precision | Local model: yes; hosted model: no | Model-card/weights terms or hosted vendor terms | High: batching, warmup, GPU/network, quotas, privacy, version drift |
| 5 | Inherits the retried tier | Validators need little storage; retries reuse upstream assets | Yes for deterministic/local paths | No new license for rules; human-review tooling and retried models inherit their terms | Medium–high: calibration, review queues, observability, rollback |

The model-size ranges are order-of-magnitude planning bands, not a recommendation to adopt a particular model. The lowest-cost useful path for this sample needs no new large model.

### Escalation policy

Cheap signals should determine the next action:

- font-map collapse ratio;
- replacement/private-use/control character rate;
- positive glyph advances mapped to spaces;
- native-vs-render disagreement;
- layout coverage by region, not page only;
- low OCR confidence weighted by token role and corroborating geometry;
- unlinked caption/source-note proximity;
- chart/diagram primitive density;
- structural invariants and provenance coverage.

Whole-page VLM processing should not be the default. It is slower, more expensive, harder to deploy offline, and makes source attribution more difficult.

## Feasibility classification

| Capability | Classification | Technical justification |
|---|---|---|
| Repair this exact Unicode sentence | **Possible with minor changes** | Embedded TrueType glyph identities and identity CID-to-GID mapping recover it deterministically. |
| Generic damaged-Unicode repair | **Possible with minor changes, conditionally** | Font audit plus targeted OCR covers many cases; not all fonts expose recoverable glyph semantics. |
| Recover Exhibit 7 | **Possible with current stack** | Exact caption is already in the Docling graph; only normalization drops it. |
| Separate Exhibit 8 title | **Possible with current stack** | Graph type and geometry already distinguish external caption from internal children. |
| Extract chart labels/years | **Possible with minor changes** | OCR diagnostics already contain them with boxes; prevent numeric joining and spatially blind deduplication. |
| Recover `1H` legend | **Possible with minor changes** | Use word boxes, alternate OCR hypotheses, and swatch/legend geometry instead of one global text threshold. |
| Preserve boxes/provenance | **Possible with current stack** | Table cells and OCR lines already carry boxes; the IR must stop flattening them. |
| Maintain low CPU latency | **Possible with minor changes** | Font audit, relationship fixes, and vector analysis are cheap; render only suspicious spans/regions. |
| Reconstruct this vector chart | **Possible with current dependencies, substantial new analyzer** | PDF curves, colors, axes, and labels are sufficient for approximate series measurement. |
| Raster chart with printed values | **Possible with an optional local model/CV pipeline** | OCR plus mark/axis detection can structure explicit labels; robustness requires more than flat text. |
| Raster chart without data labels | **Possible only approximately with stronger CV/VLM** | Values must be measured from pixels; resolution, occlusion, and scale ambiguity bound accuracy. |
| Exact values hidden behind coarse raster bars | **Not reliably possible** | The source does not contain enough information to recover exact pre-render data. |
| Basic diagram nodes/connectors | **Possible with an optional local model/CV pipeline** | Shape/line/text detection can recover explicit topology in clean diagrams. |
| Semantic diagram relationships | **Possible only with a larger or hosted model, not guaranteed** | Relationships often depend on visual conventions and domain context beyond OCR. |
| Concise semantic image descriptions | **Possible with an optional local model** | Current code already supports disabled SmolVLM description artifacts, but descriptions need grounding and clear generated provenance. |
| Apply VLM reasoning to every page | **Technically possible but not cost-effective** | It increases latency, memory/GPU or API spend, privacy exposure, and hallucination surface on easy pages. |
| Match exact LlamaParse agentic behavior | **Unknown because implementation is proprietary** | Public SDKs and LiteParse do not expose the commercial server, routing, models, or prompts. |
| Guarantee commercial-parser parity | **Not reliably possible from one sample** | Broad, stratified, version-pinned evaluation is required; leading systems also have category-specific gaps. |

## Cost-versus-quality options

### Option A — deterministic local core

Includes tiers 1, selective tier 2, existing Docling/TableFormer/Tesseract, relationship fixes, font repair, and validators.

- Best privacy and offline operation.
- Lowest variable cost and operational dependence.
- Strong for native PDFs, scans with ordinary text, tables, and vector-rich documents.
- Limited semantic image/diagram understanding.
- Recommended default.

### Option B — enhanced local visual stack

Adds local chart/diagram classifiers, raster CV, stronger OCR alternatives, and optionally a small VLM.

- Better visual coverage without document egress.
- Larger container/model storage, startup time, RAM, and possibly GPU needs.
- Model-card and weight-redistribution licenses require review.
- Appropriate when offline visual parsing is a product requirement.

### Option C — selective hosted escalation

Uses local tiers first and sends only approved low-confidence crops to a hosted model/parser.

- Highest quality/cost leverage when escalation stays low.
- Adds network latency, vendor availability, data-governance, and per-call cost.
- Requires explicit tenant policy, redaction where possible, caching rules, model/version pinning, and provenance of generated content.
- Better than sending every page when privacy policy permits.

### Option D — commercial parser for every page

The current public LlamaParse list-equivalent, calculated from documented credits and 1,000 credits = $1.25, is approximately:

| Tier | Credits/page | List-equivalent USD/page |
|---|---:|---:|
| Fast | 1 | $0.00125 |
| Cost Effective | 3 | $0.00375 |
| Agentic | 10 | $0.01250 |
| Agentic Plus | 45 | $0.05625 |

These calculations exclude subscription minimums, discounts, taxes, retries, storage, and enterprise terms. The attached job was Agentic Plus. Full commercial routing may be useful as a benchmark or fallback, but this page demonstrates that premium output still needs source-grounded validation.

## Prioritized roadmap

### Phase 0 — benchmark and evidence contracts

**Effort:** Small–medium  
**Risk:** Low  
**Goal:** Make correctness measurable before changing output.

- Freeze this PDF and a minimal synthetic malformed-Type0 fixture.
- Create human-reviewed element, relationship, text-span, and bbox truth.
- Preserve separate explicit versus derived chart truth.
- Add serializer parity snapshots.
- Establish metrics and regression thresholds.
- Record parser/model versions and environment with every run.

### Phase 1 — foundation correctness

**Effort:** Medium  
**Risk:** Low–medium  
**Goal:** Fix existing-evidence loss without adding a large model.

- Preserve table/picture captions as separate linked elements.
- Separate visual `captions` from internal `children`.
- Retain OCR word boxes and repeated tokens by position.
- Restrict hexadecimal joining to contextual non-decimal identifiers.
- Link source notes geometrically rather than relying on padding.
- Add classifier-unavailable chart heuristics and material parse concerns.
- Separate OCR confidence from detection/structure/completeness.
- Make one canonical Markdown/text serialization contract.

Acceptance on this sample:

- Exhibit 7 and Exhibit 8 are separate elements in correct order.
- No `er cas` or `C` appears as caption content.
- Twelve spatial year labels remain distinguishable; no 48-digit year string exists.
- `1H` is recovered with corroborating evidence or explicitly flagged.
- The source note is present.
- Logo output retains visible `AON`.
- Backend and frontend Markdown are byte-equivalent for the same IR.

### Phase 2 — font health and selective repair

**Effort:** Medium  
**Risk:** Medium  
**Goal:** Repair damaged native text without blanket OCR.

- Add font-level and glyph-run anomaly signals.
- Recover safe identity-mapped embedded-font candidates.
- Preserve original/repaired alternatives and method.
- Render only unresolved line/span crops.
- Add cross-evidence selection and concern policy.

Acceptance:

- The exact sentence is recovered on this source.
- A negative-control font is not rewritten.
- Unrecoverable custom fonts escalate or remain flagged, not semantically completed.

### Phase 3 — vector-first chart service

**Effort:** Large  
**Risk:** Medium–high  
**Goal:** Produce auditable chart structure and approximate values.

- Detect axes, tick calibration, panels, bars/lines/points, colors, legend swatches, and grouping.
- Use embedded Office chart data before visual measurement.
- Emit series/data points with evidence, tolerance, and validation.
- Require `annual >= 1H`, monotonic axis mapping, mark/legend consistency, and source coverage.
- Fall back to chart image plus labels when structure confidence is insufficient.

Acceptance on this chart:

- four panels, two series semantics, 11 years, axis units, and source note are represented;
- vector-derived values meet an agreed tolerance against human-reviewed geometry;
- no cell is emitted without mark/axis provenance;
- no annual total is below 1H;
- low bars carry larger relative uncertainty.

### Phase 4 — optional model escalation

**Effort:** Large  
**Risk:** High  
**Goal:** Improve ambiguous raster charts, diagrams, and semantic descriptions.

- Compare small local classifiers/VLMs and selective hosted models.
- Constrain outputs to schemas grounded in region/word/mark IDs.
- Route only low-confidence regions.
- Never let generated prose overwrite raw evidence.
- Add privacy, model-license, version, and cost controls.

### Phase 5 — production calibration and operations

**Effort:** Ongoing  
**Risk:** Medium  
**Goal:** Maintain quality under document and model drift.

- confidence calibration by content type;
- golden-set release gates;
- p50/p95 latency, peak RSS/GPU, escalation, and cost dashboards;
- canary version upgrades;
- review queue for unsupported/low-confidence artifacts;
- rollback and version pinning.

## Proposed benchmark and regression suite

### Corpus

Use licensed or internally authorized examples, stratified into:

- clean native-text PDFs;
- missing, malformed, and custom font mappings;
- scanned documents;
- mixed native/scanned pages;
- borderless and ruled tables;
- merged-cell and multi-page tables;
- financial statements;
- charts with/without labels;
- stacked, grouped, line, scatter, pie, dual-axis, multi-panel, and multi-series charts;
- flowcharts, network diagrams, org charts, and engineering diagrams;
- forms, checkboxes, signatures, and key-value graphs;
- screenshots and camera photos;
- direct PNG/JPEG/TIFF/WebP uploads;
- rotated, skewed, low-resolution, noisy, and compressed pages;
- multilingual and Unicode-heavy documents;
- Office files with native charts/tables plus rendered fallbacks.

Keep a public/redistributable synthetic set for CI and a private representative holdout for release evaluation.

### Ground truth schema

Annotate:

- page and element bboxes;
- exact visible text and Unicode normalization policy;
- semantic element type;
- caption/source-note relationships;
- reading-order edges;
- table grid, spans, headers, and cell text;
- chart axes, legends, series, explicit labels, and values;
- whether each chart value is explicit, embedded, measured, inferred, or unknowable;
- diagram nodes/connectors/labels when visible;
- provenance expectations and unsupported artifacts.

Human reviewers should inspect the source, not copy a parser's output. Derived chart values require at least two reviewers or a geometry script plus reviewer sign-off.

### Metrics

| Dimension | Metric |
|---|---|
| Character recognition | CER = character edit distance / ground-truth characters |
| Word recognition | WER = word edit distance / ground-truth words |
| Text completeness | Ground-truth span recall; omission rate by visible characters/tokens |
| Unicode | Exact code-point accuracy plus normalization-aware accuracy |
| Headings/captions | Precision, recall, F1; hierarchy accuracy; relationship F1 |
| Reading order | Pairwise order accuracy or Kendall-style rank correlation |
| Tables | Cell text accuracy, grid/span accuracy, TEDS and/or GriTS |
| Deduplication | Duplicate content units / emitted content units |
| Chart labels | Axis/legend/series/category precision, recall, F1 |
| Chart values | Match within `max(abs_tolerance, rel_tolerance × |truth|)`; MAE/RMSE by chart type |
| Grounding | Bbox IoU/coverage and percentage of emitted claims with valid source evidence |
| Unsupported artifacts | Emitted elements/values not supported by source |
| Hallucination | Unsupported semantic content units / all generated semantic units |
| Confidence | Reliability plots, expected calibration error, Brier score where applicable |
| Performance | p50/p95 time/page and time/document |
| Resources | Peak RSS, model-weight storage, CPU time, GPU memory/time |
| Cost | Infrastructure and external API cost/page; retry and review cost |
| Escalation | Percentage of pages/regions reaching each tier and human review |

Report all metrics by document category, not just a single aggregate. A system can score well on text-heavy pages and still fail charts or custom fonts.

### Critical regression fixtures from this assessment

1. Minimal Type0 PDF with a wrong-but-present `/ToUnicode` map.
2. Negative-control Type0 PDF whose mapping is unusual but correct.
3. Table caption referenced only through `table.captions`.
4. Picture with an external caption plus internal text children.
5. Four-panel chart with repeated identical year labels at different bboxes.
6. Pure-digit run that must not trigger hexadecimal joining.
7. Short legend token near the OCR threshold with corroborating swatch geometry.
8. Source note just outside a detected chart bbox.
9. Classifier-unavailable chart routing.
10. Backend/frontend JSON, Markdown, and plain-text parity.
11. Vector chart with known values and explicit measurement tolerance.
12. Raster chart whose exact hidden values are intentionally unknowable; expected output must flag uncertainty rather than fabricate.

## Risks, limitations, and licensing

### Technical risks

- Embedded-font recovery is not universal and can produce confident errors if mappings are assumed rather than validated.
- OCR confidence is engine-specific and not a substitute for semantic or structural confidence.
- Vector chart conventions vary; gradients, clipping, log axes, dual axes, broken axes, 3D effects, and overlapping marks need explicit unsupported states.
- Raster chart measurement has unavoidable resolution and quantization limits.
- Vision models can generate plausible but ungrounded content; constrained schemas do not remove that risk.
- Deterministic validators catch contradictions but cannot always identify the correct replacement.
- Model or parser upgrades can change outputs without code changes unless versions are pinned.

### Benchmark limitations

- This is one page and cannot establish overall rank or commercial parity.
- The attached LlamaParse result omits raw parameters and server/model details.
- The benchmark's polished structure contains demonstrable source errors.
- ParseBench is valuable broader evidence, but it is vendor-authored, evaluates named configurations rather than this exact attached version, and still reports category-specific gaps.
- No system should be called “second to LlamaParse” without a broad, version-pinned, independently reviewed evaluation.

### Licensing and deployment

- Current production dependencies are pinned in `pyproject.toml`; optional Docling model artifacts are downloaded separately. Package license and each model artifact/model card must be reviewed independently.
- The workspace has no obvious top-level application `LICENSE` file; clarify the product's own licensing and third-party notice policy before distribution.
- Embedded fonts may have redistribution restrictions. Analyze them in memory and avoid persisting or shipping extracted font files.
- New OCR/CV/VLM dependencies increase container size and may introduce native build/runtime obligations.
- Open-weight does not automatically mean commercially redistributable; record model version, source, license, acceptable-use terms, and hash.
- Hosted escalation requires data-processing, retention, residency, confidentiality, and subprocessor review.
- LlamaParse's public offering is proprietary SaaS/hybrid/VPC, not an open-source offline server. Its SDK license does not grant the server implementation.

## Recommended next implementation phase

After explicit approval, implement **Phases 0 and 1 plus the safe portion of Phase 2**:

1. add the regression/evidence fixtures;
2. preserve caption/source-note relationships;
3. separate visual captions from children;
4. preserve word-level OCR geometry and deduplicate by overlap;
5. correct numeric-token cleanup;
6. add font-map anomaly detection and deterministic identity-font recovery;
7. use tight OCR only when font evidence is unresolved;
8. split confidence/provenance dimensions;
9. establish one canonical serializer with backend/frontend parity.

Do **not** emit reconstructed chart values in that first phase. First make the chart a correctly typed, correctly titled, source-noted element with clean labels, positional evidence, and an explicit `values_not_structured` concern. Then implement and benchmark the vector chart service against reviewed source geometry.

This sequence delivers the largest source-faithfulness gain at low compute and licensing cost, removes several deterministic defects, and creates the evidence contract required to add chart intelligence safely.

Implementation should remain paused until this report and the proposed acceptance criteria are approved.

## Public references

- [Aon — 1H 2025 Global Catastrophe Recap](https://www.aon.com/getmedia/01e165ae-1788-4997-a51b-9225bce850dd/1H-2025-Global-Catastrophe-Recap.pdf)
- [LlamaParse v2 create API](https://developers.api.llamaindex.ai/api/python/resources/parsing/methods/create/)
- [LlamaParse v2 tiers and versioning](https://www.llamaindex.ai/blog/introducing-llamaparse-v2-simpler-better-cheaper)
- [LlamaIndex Agentic OCR architectural article](https://www.llamaindex.ai/blog/agentic-ocr)
- [LlamaParse pricing, deployment, caching, and open-source status](https://www.llamaindex.ai/pricing)
- [Llama Cloud Python SDK](https://github.com/run-llama/llama-parse-py)
- [LiteParse local parser](https://github.com/run-llama/liteparse)
- [ParseBench paper](https://arxiv.org/abs/2604.08538)
- [ParseBench repository and leaderboard](https://github.com/run-llama/ParseBench)
- [Historical public issue illustrating the need for version-pinned golden tests](https://github.com/run-llama/llama_cloud_services/issues/621)
