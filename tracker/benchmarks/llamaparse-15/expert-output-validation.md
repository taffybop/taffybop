# Expert-Output Validation

Status: Complete — 15/15 cases, 30/30 pages visually reviewed

## Conclusion

The expert output is a useful comparison target, not ground truth. It is usually
strong on visible prose, headings, captions, and explicit numeric text, but it
also contains source-inconsistent table topology, chart associations, bboxes,
visual identities, redline semantics, and metadata. It sometimes converts
unprinted visual geometry into exact values without method or tolerance.

Expert parity is therefore valid only within the source-reviewed portion of an
element. Incorrect, potentially inferred, and not-independently-verifiable
fields remain audit evidence and are excluded from literal-parity requirements.

## Corpus-wide validation results

- Expert page counts match all 15 source PDFs and all 30 physical pages.
- Major page regions are usually detected, but region-level bbox confidence
  does not ground individual cells, chart marks, diagram edges, or text runs.
- Visible prose and explicit table values are generally strong. Structural
  fidelity is materially less reliable.
- All expert `markdown_full` and `text_full` fields are `null`.
- Standalone Markdown equals joined JSON page-body Markdown after trimming for
  only `clean-energy` and `insurance-acord`. The other 13 add or rearrange
  headers, footers, printed labels, or page-number markup.
- `clean-energy` and `insurance-acord` expose a smaller top-level JSON schema
  than the other 13 cases.
- Expert confidence is not independently calibratable from the bundle. High
  page/region scores coexist with wrong values, rows, spans, bboxes, and visual
  claims.
- Expert image metadata often combines embedded source images with page renders
  and derivative crops. Counts cannot be treated as native-image inventories
  without origin metadata.

## Per-case verdicts

| Case | Expert verdict | Most important source-grounded qualification |
|---|---|---|
| [catastrophe-recap](cases/catastrophe-recap.md) | Partially verified | Correct repaired prose and explicit table; Exhibit 8 exact values are unprinted and several are assigned to wrong years |
| [clean-energy](cases/clean-energy.md) | Partially verified | Titles/growth labels verified; exact bar values are geometry/model-derived and lack tolerance |
| [clinical-study](cases/clinical-study.md) | Partially verified | Text and values strong; Table 1 false spans, Table 2 10-versus-9-column error, diagram containment loss, and contaminated footer bbox |
| [component-datasheet](cases/component-datasheet.md) | Partially verified | Ordinary text/lists strong; inferred image descriptions are unmarked, pin labels are omitted, and key-value HTML is defective |
| [egov-survey](cases/egov-survey.md) | Verified content with metadata qualifications | All 24 chart values are explicitly printed and correct; field-level grounding and printed-page metadata are absent |
| [esg-metrics](cases/esg-metrics.md) | Partially verified | Table/printed chart values strong; title bbox is wrong and a footer URL is unsupported by visible text or annotations |
| [finance-10k](cases/finance-10k.md) | Partially verified | All financial values verified; spanning headers and one wrapped row are structurally wrong |
| [health-report](cases/health-report.md) | Partially verified | Captions/notes strong; exact chart tables are unprinted, weakly grounded, and some bubble coordinates follow labels rather than marks |
| [insurance-acord](cases/insurance-acord.md) | Incorrect for form structure | Boilerplate strong; grids/column ownership fail and `[signature]` is fabricated in a blank field |
| [manufacturing-report](cases/manufacturing-report.md) | Mixed | Explicit callouts/text strong; line/raster tables are ungrounded and the printed stacked-bar table has series/category shifts |
| [ny-timetable](cases/ny-timetable.md) | Partially verified | 149/150 service rows match; one page-3 row shifts and headings/serialization are inconsistent |
| [postal-10k](cases/postal-10k.md) | Partially verified | Values largely correct; multi-row headers, currency presentation, heading types, and one concern are wrong/inconsistent |
| [purchase-agreement](cases/purchase-agreement.md) | Incorrect for redline meaning | Words are present, but deleted dates and active placeholder state are flattened |
| [settlement-agreement](cases/settlement-agreement.md) | Verified content with structural qualifications | Text/table exact; legal outline semantics are weak and a datatype concern is false |
| [uber-earnings](cases/uber-earnings.md) | Partially verified | Useful charts/diagrams, but New Zealand is called Australia, unprinted values lack method, and undirected associations become arrows |

## Important expert-error classes

### Incorrect

- Source-inconsistent chart year/series associations:
  `catastrophe-recap`, `manufacturing-report`.
- Table/grid topology errors:
  `clinical-study`, `finance-10k`, `insurance-acord`, `ny-timetable`,
  `postal-10k`.
- Fabricated blank-field content: `[signature]` in `insurance-acord`.
- Visual identity error: New Zealand flag labeled Australia in `uber-earnings`.
- Legally material style loss: deleted/active date state in
  `purchase-agreement`.
- Source-inconsistent geometry: clinical footer and ESG title bboxes.
- False or unsupported metadata: several datatype concerns, one ESG URL, and
  derivative assets presented without a source/derived distinction.

### Potentially inferred

- Exact values reconstructed from vector or raster charts when the page prints
  no values.
- Natural-language descriptions of photos, logos, and technical drawings.
- Mermaid direction where connectors show association but no arrowhead.
- Generated table headers or semantic groupings not literally present.

### Not independently verifiable

- Confidence scores without a calibration target.
- Hidden source datasets, rounding, sampling, or aggregation behind exact chart
  rows.
- Claims based on referenced sidecars that are not part of the immutable
  triplet.
- Native-versus-derived image counts where origin is not declared.

## Evidence-class policy for scoring

| Expert field class | Literal parity? | Required treatment |
|---|---|---|
| Verified explicit source text/value | Yes | Exact or declared normalized comparison |
| Partially verified | Only verified subset | Mask or score fields separately |
| Vector-derived | Not as literal text | Compare method, mark, calibration, and tolerance |
| Pixel-estimated | Not as literal text | Compare region, method, uncertainty, and supported value tolerance |
| Potentially inferred/model-generated | No | Evaluate as an optional observation with provenance and grounding |
| Not independently verifiable | No | Retain for review; do not use as a release target |
| Incorrect | No | Negative regression fixture |

## Source-correct parser disagreements

The current parser is more source-faithful than the expert in several important
places:

- it preserves the catastrophe table's repeated `United States` cells rather
  than a false row span;
- it declines to emit unsupported exact chart values across multiple cases;
- its clinical and finance table column/span structures are often more faithful;
- it keeps finance wrapped common-stock content in one row;
- it avoids the fabricated ACORD signature and unsupported ESG URL.

These differences are retained as positive safety evidence. They must not be
penalized by byte or unreviewed expert-parity metrics.

## Open expert-benchmark questions

- Can referenced XLSX/grounded-item sidecars and authoritative chart datasets be
  added with hashes and custody?
- What methods, sampling dates, aggregation, rounding, and tolerances produced
  unprinted chart rows?
- What do page, bbox, item, and table confidence scores measure?
- What are the contractual coordinate units/origin and bbox-role semantics?
- Is there a stable standalone-versus-page-body Markdown contract?
- Can embedded source images, page renders, crops, and model-generated
  descriptions be distinguished explicitly?
