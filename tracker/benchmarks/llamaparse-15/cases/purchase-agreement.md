# Expert validation: `purchase-agreement`

## Scope and overall assessment

This report validates both the supplied expert Markdown/JSON and the `baseline-20260728-current` output from our parser against the single source PDF page. It is analysis-only; source, expert, and run artifacts were treated as immutable evidence.

The expert output recovers the legal text and reading order well, but it loses material redline semantics in two places: the struck-through draft date and the deleted/replacement execution date. Our baseline preserves the words but loses all redline/inline semantics and moves the physical top matter after the body. Because those markings and order distinguish deleted text from active content, the errors are substantive rather than merely cosmetic.

Status vocabulary:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — substantially supported, with a material qualification.
- **Not independently verifiable** — the output supplies a claim or score for which the source provides no independent test.
- **Incorrect** — contradicted by the source.
- **Potentially inferred** — plausible, but derived or model-interpreted rather than explicit in the source.

## Artifact inventory

| Artifact | Role | SHA-256 |
|---|---|---|
| `benchmark-expertmodeldata/purchase-agreement.pdf` | Ground-truth source | `00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14` |
| `benchmark-expertmodeldata/purchase-agreement.md` | Expert standalone Markdown | `6223d338aefe324f0d364b5b7b442d337964fec91d96e650ce62557b8de4f229` |
| `benchmark-expertmodeldata/purchase-agreement.json` | Expert structured output | `6b8437b4763cfbb1c1d3daed2d496d881fc96afc5ffba16acd71061d2037e869` |

- Document category: legal purchase-agreement execution/redline page.
- Page inventory: 1 portrait page, 612 × 792 PDF units.
- Layout: redline banner at top, blue underlined execution label, centered agreement title, opening paragraph with a marked-up date, underlined “Background,” four WHEREAS recitals, operative paragraph, and footer code.
- Complex elements: red struck-through runs, blue underlined replacement/placeholder text, mixed color, centered headings, underlining, and legal recital structure.
- Native object inventory: 3,338 characters, 511 words, 13 rectangles, no lines, no curves, no raster images, and no annotations.
- Expert job metadata: `tier=agentic`, `cost_optimized=false`, `triggered_auto_mode=false`, page orientation 0, page confidence 1.0.

## Source page map

| Physical PDF page | Source content | Expert item summary |
|---|---|---|
| 1 | Execution-version purchase-agreement opening page with visible redline/deletion and insertion formatting | Ten text/heading/footer items |

## Expert element validation

| Source element | Evidence class | Status | Assessment |
|---|---|---|---|
| Top redline/development banner text | Explicit colored vector text and strike rules | **Partially verified** | Most red struck-through banner text is serialized with `~~...~~`, but `Draft of 6/1/20` is emitted as active plain text. |
| Blue underlined “EXECUTION VERSION” | Explicit colored vector text and underline | **Verified** | Text and emphasis are preserved. |
| Centered agreement title | Explicit text / placement | **Verified** | Wording and reading order match the source. |
| Opening paragraph prose | Explicit text | **Verified** | Text matches, including the source’s grammatical oddity “certain the”. |
| Marked-up date `[June 23_______]` | Explicit colored vector text plus strike/underline geometry | **Incorrect** | Expert text preserves characters but removes the distinction between deleted red text and the active blue placeholder. |
| “Background” heading | Explicit text / underline | **Verified** | Heading text and underline semantics are preserved. |
| WHEREAS recitals and operative paragraph | Explicit text | **Verified** | All visible legal prose is present in reading order. |
| Footer code `A7310832` | Explicit text | **Verified** | Correct. |
| Item bounding boxes | Vector geometry | **Partially verified** | Boxes cover relevant text, but several overlap or repeat, and their role is not documented. |
| Page confidence 1.0 | Model metadata | **Not independently verifiable** | The source cannot establish the score; it is also insensitive to the redline omissions. |
| `images_content_metadata.total_count=1` | Derived parser artifact | **Incorrect** as a source-image inventory | The source contains no raster image; the entry is a generated full-page render. |

## Concrete expert discrepancies

### 1. Struck-through draft date is serialized as active text

The source run `Draft of 6/1/20` is red at approximately `x=474–540`, `top=37.54–48.58`. A red strike rule crosses it at approximately `top=43.32–43.92`. The expert emits the run without strike markup, even though adjacent redline text is correctly represented using Markdown deletion syntax.

This is an **Incorrect** representation of explicit vector formatting. The content exists, but its legal state changes from deleted/draft text to apparently active text.

### 2. Deleted date tokens and blue placeholder are flattened

The opening date contains separate source runs:

- red `June` at approximately `x=465.36–486.29`, `top=141.33–152.85`, with a red strike at `top=147.36–147.96`;
- red `23` at approximately `x=72.00–83.51`, `top=154.53–166.05`, with a red strike at `top=160.56–161.16`;
- blue underscore placeholder at approximately `x=83.52–123.84`, `top=154.53–166.05`, with blue underline rules near `top=164.16` and `165.48`.

The expert emits plain `[June 23_______]`. That preserves the visible character stream but collapses three different source facts—deleted text, replacement placeholder, and color/underline—into one active string. It is therefore not a faithful redline interpretation.

### 3. Confidence does not expose formatting loss

The page confidence is 1.0 and there is no item/run-level confidence or provenance for color, strike, or underline decisions. A consumer cannot tell which visible runs were detected, which rules were associated with them, or why some redline runs received `~~` while the draft/date runs did not.

## Geometry and metadata limitations

- The first expert item uses five boxes, some with overlapping start indexes; the execution-version box also participates in this grouping. The schema does not explain whether boxes are word, line, union, or alternate-detection regions.
- A text box alone cannot validate strikethrough. Faithful redline extraction requires associating nearby colored horizontal vector rules with specific character spans.
- Color is source-explicit. Treating all words as a plain stream discards evidence that is essential to legal redline meaning.
- Item confidence is absent. Page confidence 1.0 is model metadata, not proof of formatting fidelity.
- The PDF has no native raster images. Its single reported image-metadata entry is derivative.

## Explicit, derived, and unverifiable evidence

- Characters, font color, and the strike/underline rectangles are explicit vector evidence.
- Associating a horizontal rule with the character run it crosses is a geometry-derived relationship, but it is independently testable from source coordinates.
- Interpreting red strike as “deleted” and blue underline as “inserted/replacement” is conventional redline semantics. It is strongly supported here, but any canonical active-text policy still needs to be stated.
- The expert’s confidence score is **Not independently verifiable**.
- No pixel-only image interpretation or model-generated description is needed for this page.

## Standalone Markdown versus JSON representations

The standalone Markdown equals the JSON page header, if any, plus `markdown.pages[0].markdown` and the footer, separated by blank lines and modulo outer whitespace. `markdown_full` and `text_full` are null.

Item grouping is distinct from the page presentation: the top banner/execution runs are grouped in item metadata, while the page-body Markdown is the serialized reading view. Consumers should not assume that item boxes map one-to-one to Markdown lines or that item `.md` is a complete formatting-evidence record.

## Our baseline output versus source

Reviewed artifacts:

- `runs/baseline-20260728-current/purchase-agreement/our-output.json`
- `runs/baseline-20260728-current/purchase-agreement/our-output.md`

The baseline reports `success`, one page, native provenance for all twelve items, no native images, and no warnings. It preserves the full visible word inventory, but its reading order and legally meaningful inline formatting are not faithful.

| Baseline element or claim | Status | Source-grounded finding |
|---|---|---|
| Agreement title and body prose | **Verified** for words | All visible body text is present, including “certain the”. |
| Visual reading order | **Incorrect** | The source’s top redline banner and execution label are assigned reading orders 8–10 and emitted after the operative `NOW, THEREFORE` paragraph. |
| `Draft of 6/1/20` | **Incorrect** | It is treated as a level-1 active heading rather than struck-through red draft text. |
| Remaining draft warning | **Incorrect** | Three deleted red lines are flattened into one active paragraph with no deletion, color, line, or confidentiality emphasis. |
| `EXECUTION VERSION` | **Partially verified** | Text is correct, but its blue underline and top-of-page placement are lost. |
| Marked-up opening date | **Incorrect** | As in the expert output, `[June 23_______]` collapses deleted red date tokens and the blue underlined placeholder into plain active text. |
| Defined-term styling and quotation glyphs | **Incorrect** | Source curly quotation marks and bold defined terms become spaced ASCII apostrophes such as `' Agreement '`. |
| Underlined `Background` and `Exhibit A` | **Incorrect** | Both underlines are lost; `Background` is also promoted from the source’s subsection role to a level-1 heading. |
| Footer `A7310832` | **Verified** | Correct text, footer type, and bottom-page localization. |
| Item bounding boxes and native provenance | **Verified** for localization | Single boxes closely cover the relevant source regions and identify native extraction, but they do not carry run-format evidence. |
| Item confidence | **Not independently verifiable** / absent | All item confidence fields are null despite formatting and ordering errors. |
| Native image count | **Verified** | `document.image_count=0` matches the vector-only source. |

The ordering error is directly visible in JSON geometry. `Draft of 6/1/20`, the warning paragraph, and `EXECUTION VERSION` have top-page boxes around `top=38.89`, `51.49`, and `89.69`, but reading orders 8, 9, and 10. The agreement title begins lower, around `top=116.33`, yet receives reading order 0. Baseline Markdown follows those assigned orders, so the top matter appears near the end of the document.

The output’s 100% native-text token recall is therefore not equivalent to document fidelity. It does not test deletion state, underline/color, typography, or spatial order.

Baseline standalone Markdown is exactly the non-empty JSON item `.md` values joined in `reading_order`, modulo outer whitespace. The wrong late placement and formatting flattening are therefore shared by JSON and Markdown rather than being presentation-only differences.

### Confirmed baseline gap disposition

| Gap | Baseline disposition | Evidence |
|---|---|---|
| `GAP-REDLINE-001` | **Confirmed** | All draft/date deletion and insertion semantics are flattened. |
| `GAP-BBOX-001` | **Confirmed with qualification** | Localization is good, but boxes have no linked color/rule/run evidence. |
| `GAP-ORDER-001` | **Confirmed** | Physical top matter is serialized after the body despite its y coordinates. |
| `GAP-REDLINE-001` | **Confirmed** | Bold terms, curly quotes, underlines, color, and confidentiality emphasis are lost. |
| `GAP-PROVENANCE-001` | **Confirmed** | No confidence or uncertainty is attached to any item/run. |

## Mapped gaps

These findings use the finalized gap taxonomy while retaining their baseline
dispositions and exact source regions.

| Gap | Mapped capability | Exact source region | Why reusable |
|---|---|---|---|
| `GAP-REDLINE-001` | Preserve run-level deletion/insertion semantics from color plus strike/underline vectors | `Draft of 6/1/20` at `x=474–540`, `top=37.54–48.58`; opening date at `x=465.36–486.36`, `top=141.33–152.85`, and `x=72–123.84`, `top=154.53–166.05` | Tests legally material formatting that cannot be reduced to plain text. |
| `GAP-BBOX-001` | Link formatting evidence and provenance to the exact character span | Top banner and opening-date regions | Tests whether boxes/rules are attributable rather than only broadly localized. |
| `GAP-ORDER-001` | Geometric top matter assigned after body content | Banner/execution boxes at `top=38.89–99.17` versus agreement title at `top=116.33` | Tests reading-order reconciliation against page geometry. |
| `GAP-REDLINE-001` | Preserve defined-term emphasis, quotation glyphs, underlines, and confidentiality emphasis | Opening paragraph; `Background`; `Exhibit A`; top warning | Tests legally useful inline typography beyond raw token recall. |
| `GAP-PROVENANCE-001` | No uncertainty at item or formatting-run level | All baseline items on physical page 1 | Tests whether formatting/order uncertainty is attributable. |

## Open questions

1. Should canonical output retain deleted text visibly with deletion metadata, or exclude it from an “active contract text” view while preserving it in a redline view?
2. Is Markdown `~~...~~` the normative deletion representation, or should JSON also expose explicit run-level `change_type`, color, and rule evidence?
3. How should blue placeholder underscores be normalized without losing their insertion/blank-field function?
