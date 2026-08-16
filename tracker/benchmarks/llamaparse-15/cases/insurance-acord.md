# Source, expert, and baseline validation: `insurance-acord`

## Scope and verdict

This report validates the immutable ACORD PDF against the supplied expert Markdown/JSON and visually compares the successful baseline parser run `baseline-20260728-current`.

The source is a blank, static certificate form made from native text and vector rules; it is not an interactive AcroForm. The expert captures most labels and boilerplate, but its two tables do not preserve the form grid, its coverage table assigns insurance-type content to the blank `INSR LTR` column, its main bbox covers unrelated regions, and it fabricates a `[signature]` in a visibly blank signature area. Our baseline avoids the signature fabrication and includes the full footer, but its coverage table is also structurally unusable, it loses checkbox/grid semantics, and it moves corrupted contact text to the end of the reading order without raising a parse concern.

## Inventory and method

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `insurance-acord.pdf` | 17,086 | `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4` |
| Expert `insurance-acord.md` | 5,523 | `7d2379b35fb2a6bbc566d0b6549f0804e4a3166cd7b113303811fa662eee4e54` |
| Expert `insurance-acord.json` | 54,844 | `2c507394d3452d73e1cf341611cd0a803b48628d588cd95481a678600bc37652` |

- Source: one native portrait PDF page, 612 x 792 pt, rotation 0.
- Category: insurance certificate/static blank form (ACORD 25).
- Layout: logo/title/date; two disclaimer bands; producer/insured/contact/insurer grid; coverages heading and disclaimer; dense policy/limits grid; description box; certificate-holder/cancellation/signature boxes; footer.
- Complex elements: nested and irregular vector grid, blank input areas, drawn unchecked squares, two-level coverage headers, repeated limit rows, small uppercase text, and static-versus-interactive form semantics.
- Source object inventory: 2,843 native characters, 125 lines, 20 rectangles, 1 embedded logo image, 0 annotations, and 5 grid-like tables found by pdfplumber.
- Interactive-form evidence: zero annotations/widgets were present and the expert `forms` field is null. The visible fields and checkboxes are static vector content.
- Visual evidence: `tmp/pdfs/llamaparse-15/insurance-acord/page-001.png` was inspected at original detail; native text, grid geometry, images, and annotations were checked with pdfplumber.
- Baseline evidence: the case's output JSON/Markdown, diagnostics, and comparison metrics in `runs/baseline-20260728-current`.

Status terms are source-evidence judgments: `Verified`, `Partially verified`, `Not independently verifiable`, `Incorrect`, and `Potentially inferred`.

## Source page map

| Physical page | Source regions and reading order |
|---|---|
| 1 | Logo/title/date at approximately `y=18-47`; certificate disclaimer `y=51-88`; important notice `y=92-119`; producer/insured/contact/insurer grid `x=22-594, y=121-240`; headings at `y=243-251`; coverage disclaimer `y=254-286`; policy/limits grid `x=18-594, y=287-565`; description box `y=568-648`; holder/cancellation/signature boxes `y=652-736`; three-part ACORD footer `y=747-768`. |

## Evidence classification

- Explicit: all printed labels, disclaimers, coverage categories, limit labels, footer text, empty field regions, and drawn unchecked boxes.
- PDF-vector-derived: cell boundaries, field ownership, row/column spans, checkbox outlines, and signature-line/blank-area geometry.
- Pixel-estimated: not needed except visual confirmation of the embedded logo.
- Model-inferred: the semantic label `ACORD logo`, Markdown `[ ]` checkbox tokens, HTML/Markdown table topology, and any claim that a blank field has an entered value.
- Unverifiable: intended downstream form schema or interactive behavior not encoded in this static PDF.

## Expert element validation

Indexes refer to `items.pages[0].items`.

| Expert item(s) | Representation | Status | Source-grounded assessment |
|---|---|---|---|
| 0 | `ACORD logo` | Potentially inferred | The embedded ACORD mark is visibly present and the bbox is correct. The words are a semantic image description, not literal body text. |
| 1-2 | Certificate title and date label | Verified | Exact visible text and correct regions. |
| 3-4 | Certificate and important disclaimers | Verified | Complete, correctly ordered, and source-faithful. |
| 5 | Producer/insured/contact/insurer table | Partially verified | Most labels are explicit, but the four-column Markdown concatenates `PRODUCERINSURED`, duplicates insurer labels, and does not preserve the left/right field spans. Confidence is only 0.51. |
| 6 | Coverage/certificate/revision heading band | Partially verified | All three labels are explicit; pipe separators are generated layout encoding rather than printed characters. |
| 7 | Coverage disclaimer | Verified | Complete and exact. |
| 8 | Main coverage table | Incorrect | Content from `TYPE OF INSURANCE` is placed in the blank `INSR LTR` column; header/limit associations are lost. Its bbox `[17.65,251.95,577.67,396.35]` starts in the disclaimer and extends through the description region, overlapping item 9. |
| 8 checkbox tokens | Escaped `[ ]` values | Partially verified | They represent visible drawn unchecked squares, but the source has static vector marks, not interactive Boolean fields. No box-level bbox or static/interactive provenance is supplied. |
| 9-12 | Description, holder, cancellation heading/text | Verified | Exact visible wording and correct regions. |
| 13 | Authorized representative plus `[signature]` | Incorrect | `AUTHORIZED REPRESENTATIVE` is printed, but the signature area is blank. `[signature]` is fabricated and has no source mark. |
| 14 | Copyright, form ID, registered-mark footer | Verified | All three footer components are visible and correctly present in the JSON footer item. |
| Page metadata/confidence | Page confidence 0.963 | Not independently verifiable | No calibration or field/table correctness target is defined. High page confidence coexists with concrete grid errors. |
| Job/forms metadata | `job: null`, `forms: null` | Partially verified | `forms: null` is consistent with no interactive field output. Expert run/tier provenance is unavailable for this case. |

## Concrete expert defects and limitations

### Coverage content is in the wrong logical column

The source's narrow leftmost `INSR LTR` column is blank. `GENERAL LIABILITY`, `AUTOMOBILE LIABILITY`, and the option/checkbox text occupy `TYPE OF INSURANCE`. Expert Markdown places these strings in the first `INSR LTR` cell and leaves `TYPE OF INSURANCE` empty. This is a source-inconsistent column association, not merely a formatting preference.

### Main table bbox is over-broad

The actual coverage grid begins around `y=287` and ends near `y=565`. The expert item begins at `y=251.95`, covering the preceding disclaimer, and extends to `y=648.30`, covering the separate description box. Item 9 at `y=566.58` therefore lies inside the table bbox even though it is represented separately.

### Signature is fabricated

The source prints `AUTHORIZED REPRESENTATIVE` above an otherwise blank field. There is no handwriting, stamp, raster signature, or vector signature mark. The expert's `[signature]` is incorrect and should be excluded from reference truth.

### Static boxes are not interactive values

The checkbox outlines are explicit vector marks, so an accessible textual placeholder can be useful. However, `[ ]` must carry provenance such as `static_drawn_checkbox` rather than implying a widget value. The source has zero annotations/widgets and no AcroForm evidence in the supplied bundle.

## Baseline parser comparison

The baseline completed successfully with one page, 21 items, 2 tables, one image, complete bbox/provenance coverage, and no warnings or parse concerns.

| Our item(s) | Status | Source-grounded assessment |
|---|---|---|
| `p1-i1` | Partially verified | Correct image region and honest placeholder `[Image detected; no reliable text extracted.]`; it does not recover the explicit ACORD brand text or semantic logo identity. |
| `p1-i2` to `p1-i5` | Verified | Date, title, and both disclaimers are source-faithful. |
| `p1-i6`, `p1-i8` | Verified | `PRODUCER` and `INSURED` labels are correct. |
| `p1-i7` | Incorrect | Right-side contact/insurer content is flattened into a one-column table with collapsed phone/fax/e-mail/NAIC header relationships. `CONTACT NAME` is not represented correctly in this table. |
| `p1-i9` to `p1-i12` | Verified | Coverage/certificate/revision headings and disclaimer are exact. |
| `p1-i13` | Incorrect | Main coverage table has malformed headers, collapses `ADDL INSR` and `SUBR WVD`, loses the `LIMITS` header, turns many type/checkbox groups into full-row colspans, corrupts strings such as `LOC JECT PRO- POLICY`, and omits static checkbox marks. It does not preserve grid semantics. |
| `p1-i14` to `p1-i18` | Verified | Description, holder, cancellation, cancellation text, and `AUTHORIZED REPRESENTATIVE` are correct. Crucially, no signature is invented. |
| `p1-i19` to `p1-i20` | Incorrect | Source contact text from around `y=121-139` is emitted after the signature area. OCR merges it into `PHONE NAME:` and duplicates/splits information that belongs in the producer grid. |
| `p1-i21` | Verified | Copyright, ACORD form ID, and registered-mark footer are all included. |

Confirmed strengths relative to the expert:

- No fabricated signature placeholder.
- Main coverage choices are not uniformly asserted as values in the blank `INSR LTR` column.
- Complete footer is present in standalone Markdown.
- Every item carries a bbox and source provenance.
- The source is not falsely represented as an interactive completed form.

Confirmed baseline defects:

- Both form tables lose essential row/column topology and blank-field semantics.
- Static checkboxes are omitted rather than represented with explicit vector provenance.
- Contact text is corrupt, duplicated/split, and out of reading order.
- No parse concern is raised for either malformed table despite null table confidence.
- The image placeholder is safe but semantically weak for a clear logo.

## Bounding boxes, confidence, and metadata

- Expert item 8 has a demonstrably over-broad bbox; child cell/checkbox boxes are absent.
- Our main table bbox `x=17.99, y=287.406, w=576.327, h=277.886` is much tighter and aligns with the coverage grid. Correct region detection does not compensate for incorrect logical topology.
- Our producer table bbox covers only the right-side contact/insurer grid. Separate contact OCR items use source-region boxes but are serialized at the end, showing that bbox correctness and reading order are independent.
- Our confidence coverage is 4.76%: only the logo/image item has confidence. Both structurally unreliable tables have null confidence and no concerns.
- Expert page confidence 0.963 and table confidence 0.66 do not expose cell-level certainty or detect the known column shift.
- Expert `result_content_metadata` says grounded-items JSONL and XLSX sidecars exist, but neither artifact is included in the immutable case triple. Their contents, checksums, and ability to resolve the grid errors are not independently verifiable.
- Our JSON declares bbox units, page dimensions, native/OCR/derived source, processing versions, and no document warnings.

## Standalone Markdown versus JSON

This expert case has a concrete serialization inconsistency. Standalone `insurance-acord.md` exactly equals the JSON page-body Markdown and omits the JSON footer. The JSON item stream and `markdown.pages[0].footer` contain:

- `© 1988-2010 ACORD CORPORATION. All rights reserved.`
- `ACORD 25 (2010/05)`
- `The ACORD name and logo are registered marks of ACORD`

Other expert cases commonly append header/footer content to standalone Markdown, so consumers cannot infer one stable contract from the bundle.

Our schema has no separate page-body Markdown field. `our-output.md` serializes all page items, including the full footer. JSON and Markdown therefore expose the same content, malformed tables, and late contact items.

## Mapped gaps

| Gap | Origin | Mapped capability | Exact evidence |
|---|---|---|---|
| `GAP-FORM-001` | Both | Detect static form grids and drawn checkboxes with semantic roles distinct from AcroForm widgets/entered values. | Entire physical p1; 125 lines, 20 rectangles, zero annotations/widgets, expert `forms:null`. |
| `GAP-TABLE-002` | Both | Recover irregular form-grid topology, header spans, field ownership, and limit rows. | Producer/insured grid `y=121-240` and coverage grid `y=287-565`; both expert and ours have structural errors. |
| `GAP-TABLE-001` | Ours | Gate unusable table candidates against form ownership and emit structural concerns. | The same producer/insured and coverage grids are forced into unusable tables, and ours raises no concern. |
| `GAP-BBOX-001` | Expert | Validate item geometry and provide cell/checkbox boxes. | Expert item 8 spans `y=251.95-648.30` instead of the source grid `y=287-565`; overlaps item 9. |
| `GAP-VISUAL-001` | Expert | Refuse semantic placeholders when the target region is visibly blank. | Signature field at approximately `x=310-594, y=711-736`; expert adds `[signature]`, source is blank, ours correctly does not. |
| `GAP-ORDER-001` | Ours | Keep column/grid labels with their owning region and suppress late duplicate OCR. | `p1-i19`/`p1-i20` originate around `y=121-139` but serialize after `p1-i18` at `y=712`. |
| `GAP-VISUAL-001` | Ours | Provide source-grounded semantic classification for clear logos while retaining uncertainty. | Embedded ACORD logo at `x=21-90, y=18-48`; ours emits only a generic image placeholder. |
| `GAP-PROVENANCE-001` | Both | Attach confidence/provenance to form cells, vector boxes, and recovered relationships; calibrate structural confidence. | Expert high page score coexists with wrong columns; our malformed tables have null confidence and zero concerns. |
| `GAP-SERIALIZATION-001` | Expert/contract | Define whether standalone Markdown includes JSON header/footer content. | Standalone equals JSON body only and omits the verified three-part JSON footer. |

## Open questions

- Should static drawn checkboxes serialize as accessible `[ ]` tokens, vector-shape objects, or both?
- What confidence/concern threshold should prevent malformed form tables from being presented as reliable HTML?
- Should blank field regions be represented structurally even though they contain no entered text?
- Why are source contact labels detached and emitted after the cancellation/signature area?
- Why does this expert case omit footer content from standalone Markdown while comparable cases append it?
- Can expert job/model provenance be supplied for this `job: null` result?
- Can the referenced grounded-items JSONL and XLSX sidecars be added immutably with checksums?

## Guardrail

This is a read-only evidence record. No parser behavior, tests, stories, corpus files, or global benchmark files were changed.
