# Functional-Fidelity Defect Execution Order

Status: **Active remediation sequence; FFD-014 is In Progress and FFD-011 is Blocked**  
Baseline: `source-grounded-final-disposition-v2.json`  
Scope: functionality and output quality only  
Operating limit: **one production work item in progress at a time**

## Purpose

This is the operative order for resolving the 13 source-grounded root defects
tracked as `FFD-001` through `FFD-013` and the post-baseline P04 production-
control defect `FFD-014`. It deliberately does not sequence the 278 raw
comparator signals: those signals are correlated Markdown, JSON, table,
visual, and DOM manifestations rather than 278 independent defects.

The queue contains 23 bounded implementation slices. A slice is small enough
to reproduce, correct, review, and validate independently. One correction may
improve more than one PDF, but each affected defect and PDF keeps its own
acceptance evidence and may close only after its focused three-surface gate
passes.

This functionality queue supersedes the historical phase/latency order only
for the duration of defect remediation. Latency, CPU, memory, and exhaustive
hardening remain out of scope unless they directly prevent correct parsing or
output.

## Working policy

1. Keep a strict WIP limit of one production slice. Source inspection, test
   design, and review may run in parallel, but a second production behavior
   must not change while the active slice is `In Progress` or `Validating`.
2. Take the first unblocked item below. Complete its owning FFD card's
   Definition of Ready before changing production code.
3. Bind expected behavior to the hash-proven PDF page and bounded source
   region. LlamaParse is the requested comparison baseline; it is not
   authority for generated prose, interpolated values, or unsupported arrows.
4. Add a focused failing regression before the fix. Include a positive target,
   a related positive, a non-target, and a malformed or ambiguous negative
   whenever the capability can overreach.
5. Make one bounded correction through the owning reusable capability. Do not
   add filename-, hash-, page-, or element-ID-specific production branches.
   The same prohibition applies to pre-existing logic in the affected or
   dependent production path: identify it before implementation and remove or
   generalize it before closure. See
   [`pre-remediation-genericity-audit.md`](pre-remediation-genericity-audit.md).
6. Immediately after the correction and focused tests pass, reparse every
   affected **full benchmark PDF separately** through fresh LlamaParse and
   service jobs into new immutable folders. This affected-benchmark gate must
   pass before the slice can become `Done` or the next production slice can
   begin. Page references below identify the review target; they do not permit
   a partial-document validation shortcut.
7. For both systems and every affected PDF, preserve the complete raw Markdown,
   full unprojected JSON response, actual rendered Markdown UI/DOM, and visual
   snapshots. Capture LlamaParse's displayed rendering and the actual Clearleaf
   DOM; a locally synthesized preview is not equivalent. Service raw Markdown
   must be byte-identical to canonical full Markdown.
8. Rerun the exact control matrix named below through the service and compare
   it with its immutable selected LlamaParse reference. Refresh a control's
   LlamaParse capture if the service changes any reviewed surface or if the
   reference itself is unavailable or stale.
9. Record an issue-specific, source-grounded comparison of the expected
   LlamaParse result and actual service result for the card's exact defect
   oracle, named symptoms, and predeclared collateral boundary. Prove the
   particular defect is resolved across Markdown structure, rendered
   presentation, and JSON structure/content.
10. Run an automated structural drift comparison across each complete captured
    Markdown, rendered DOM representation, and JSON output, comparing the
    post-fix service run with the bound pre-fix service run. Flag any drift
    between the fresh and selected prior LlamaParse references. Manually review
    every post-fix service change outside the declared boundary; unchanged
    unaffected regions do not require exhaustive manual re-audit at this
    per-slice gate.
11. Mark a slice Done only after the focused affected-benchmark comparison and
    outside-boundary drift disposition pass. Unit or focused tests alone never
    close a slice.
12. Run the all-15 wave gate before starting the next wave. A wave failure
    returns the responsible slice to `In Progress`; it is not deferred to the
    final campaign.
13. Passing a slice or wave gate never substitutes for the final frozen
    end-to-end validation across all 15 PDFs. That fresh dual-system campaign
    remains mandatory after every tracker defect is closed.

## Per-slice affected-benchmark transition gate

For each numbered slice below, “Affected rerun through both systems” is a hard
state-transition gate, not deferred release evidence. Keep the card in
`Validating` while its listed PDF or PDFs are run one at a time through fresh
LlamaParse and service jobs using the same source bytes. The immutable evidence
bundle for each PDF must contain:

1. source, settings, reference-job, service-build, and artifact hashes;
2. both raw Markdown outputs;
3. both actual rendered Markdown UI/DOM captures and snapshots;
4. both full original JSON responses; and
5. a source-grounded, issue-specific comparison decision covering the exact
   oracle, named symptoms, and declared collateral boundary; and
6. an automated post-fix-versus-pre-fix service complete-output drift report,
   any fresh-versus-selected LlamaParse reference drift report, and the manual
   disposition of every changed service region outside that boundary.

The slice returns to `In Progress` if any target behavior remains wrong, the
three surfaces disagree, or an outside-boundary change is material or remains
unexplained. An acceptable difference requires an explicit, bounded approval
with source evidence; it cannot be inferred from a test pass. The immediate
gate does not require a manual re-audit of unchanged, unaffected content. Only
after this transition gate passes may the slice be marked `Done` and the next
slice start. Wave gates and the final all-15 release gate remain additional,
independent requirements.

## Dependency waves

| Wave | Work items | Objective | Entry dependency | Exit gate |
|---|---:|---|---|---|
| A — bounded text/table closures | 1, 1a, 2–6 | Close the blocking Clinical P04 control, the narrow Postal and ACORD gaps, then stabilize source Unicode/text | Final v2 baseline and issue-card DoR | Focused matrices pass; all 15 service outputs are drift-screened |
| B — ownership and page semantics | 7–11 | Establish safe cross-owner text attribution, then stabilize order and hierarchy | Wave A | All visual-owner controls and all relationship/order controls pass; all 15 drift-screened |
| C — chart semantics | 12–18 | Assemble only printed, source-grounded panels, axes, categories, legends, series, and values | Wave B | All seven chart PDFs and non-chart controls pass; all 15 drift-screened |
| D — diagram semantics | 19–21 | Recover only source-proven topology for three distinct diagram families | Wave B; relevant chart controls from Wave C must remain stable | Clinical, Uber, and Component diagram matrix passes; all 15 drift-screened |
| E — diagnostic adjudication and release | 22 | Decide whether diagnostic-only board OCR is a functional release gap and, if so, correct it safely | Waves A–D | Fresh all-15 LlamaParse/service benchmark and consolidated release decision |

Within each wave, order is mandatory unless the earlier item is formally
blocked by unavailable source evidence. A blocker does not authorize skipping
the wave exit gate.

## Ordered implementation slices

### Wave A — bounded text and table closures

#### 1. Postal detached FERS duplicate — `FFD-011`

- Target: `postal-10k`, physical page 1 / printed page 2.
- Expected: the glossary contains exactly one `FERS / Federal Employees
  Retirement System` row and no detached duplicate paragraph in JSON,
  Markdown, or DOM.
- Owner: P02-US04, with P04-US01 table ownership as secondary.
- Dependency: FFD-014 for the Clinical named-control blocker; the independent
  NY control remains separately governed.
- Risk/size: quick-to-medium; terminal source alignment and table ownership
  custody make broad text-based suppression unsafe.
- Affected rerun through both systems: `postal-10k` full PDF.
- Service controls: `ny-timetable` pp1–3, `clinical-study` pp2 and 4,
  `finance-10k` pp1–3, and `purchase-agreement` p1.
- Closure evidence: exact once-only FERS row on p1; CIO remains exact; no
  detached `ClO`; no table rows, source-alignment evidence, or page order are
  lost.
- Current validation: immutable run `20260813T151137Z-FFD-011-focused` passes
  the complete Postal dual-system target across source, raw/canonical Markdown,
  actual LlamaParse/Clearleaf UI-DOM, and full JSON. All 39 glossary rows and
  Postal page-2/page-3 table objects remain exact. Slice 1 is `Blocked`, not
  `Done`: FFD-014 owns the two Clinical failures, while the independent NY
  control remains separately governed. Exact capture supersedes the earlier
  optional-key interpretation: the validated Crossmark block is an included
  placeholder with a contributor, while fresh reconstruction is empty and
  omitted as `unsupported_primary_ocr` with different graph custody. FFD-011
  source alignment is disabled in those tests and the reviewed predecessor is
  preserved. Elevated diagnostic output is not closure evidence. Slice 2
  remains unstarted.

#### 1a. Clinical page-1 visual-overlay custody — `FFD-014`

- Target: `clinical-study`, physical page 1 / printed `1 / 21`, first-segment
  Crossmark visual owner and the generic terminal non-target visual rebind.
- Expected: preserve the existing included image placeholder and public visual
  contributor exactly once while committing both existing P04 table sidecars
  and `canonical_source_custody`; never promote Crossmark OCR or encoded native
  pseudo-text.
- Owner: P04-US01, with P01-US03 public-item/canonical input as secondary.
- Dependency: post-baseline blocking control admitted by the 2026-08-14 queue
  amendment; it blocks FFD-011 closure and is the active production defect.
- Risk/size: medium; baseline included-placeholder semantics must be retained
  only after exact public identity, contributor, scope, order, and closed-graph
  proof. Any ambiguity must preserve the exact atomic rollback.
- Affected rerun through both systems: `clinical-study` full PDF. The manual
  source/output boundary is page 1 only; existing page-2/page-4 table assertions
  are automated custody controls, not authorization for page-2 remediation.
- Service controls: `postal-10k`, `ny-timetable`, `catastrophe-recap`, and
  `component-datasheet`, plus the second Clinical page-1 visual owner.
- Closure evidence: positive `unsupported_primary_ocr` and `empty_visual`
  variants, rename/hash independence, page-offset and batch-order tests,
  adversarial graph rollback, valid public JSON, raw/canonical Markdown byte
  parity, and actual DOM agreement. Production remains at 5.0 seconds/document
  and 0.500 seconds/page; no deadline widening is permitted.
- Boundary: this first segment pauses after page-1 validation and returns to
  the user before any page-2-specific inspection or remediation. The separate
  NY deadline/page-boundary failure is not FFD-014.
- Current validation: the focused P04 transaction suite passes `18/18`, and
  the two existing Clinical P04 controls pass together `2/2`, at the unchanged
  5.0-second document and 0.500-second page budgets. The fresh bounded service/
  actual-Clearleaf capture proves page-1 target and non-regression behavior.
  Its release profile leaves the page-2/page-4 objects unresolved
  `table_candidate`, exactly as pre-fix, so it does not exercise terminal P04
  authority and is not the required fresh transaction-exercising dual-system
  closure bundle. User page-1 validation, that closure bundle, NY, Wave A, and
  the final all-15 campaign remain pending.

**2026-08-14 page-one release-slice supersession:** the requester later
authorized source-visible page-one content, ordering, footer, and interactive
Full-default corrections. The earlier placeholder-preservation and no-order/
no-text constraints above are superseded only for that bounded page-one
projection by the
[`release-slice amendment`](decisions/2026-08-14-ffd-014-clinical-page-one-release-slice-amendment.md).
The final page-one regression plus fresh HTTP/repository-native Clearleaf Full
render passes the header, article-label, main-preamble, visual-label, Citation,
and spaced-footer oracle. No page-2 source was inspected.

Terminal P04 custody remains a separate blocker. The latest named production-
5-second and test-only-10-second observations both lack
`canonical_source_custody`; they predate the final footer replay and were not
rerun afterward. Production remains 5.0 seconds/document and 0.500 seconds/
page, and the 10-second seam is diagnostic-only. Item 1a is therefore `In
Progress`, item 1 remains `Blocked`, and item 2 remains unstarted. Wave A and
the final frozen all-15 campaign remain pending.

#### 2. Postal table-cell italics — `FFD-012`

- Target: `postal-10k`, physical page 1 / printed page 2.
- Expected: the four source-italic spans (`CARES Act`, its expanded name,
  `Exchange Act`, and its expanded name) remain italic in table Markdown and
  rendered DOM while the existing JSON run evidence stays attributable.
- Owner: P03-US05, with P04-US01 and canonical/frontend table serialization as
  secondary consumers.
- Dependency: item 1, so the final glossary ownership is stable before inline
  table presentation changes.
- Risk/size: quick-to-medium; cell escaping, spans, and plain-text exports must
  remain safe.
- Affected rerun through both systems: `postal-10k` full PDF.
- Service controls: `purchase-agreement` p1, `settlement-agreement` p1,
  `clinical-study` pp2 and 4, and `finance-10k` pp1–3.
- Closure evidence: four and only four source-supported italic spans in raw
  Markdown and semantic DOM; no literal HTML/script injection; CSV/plain cell
  values remain unformatted text.

#### 3. Postal source em dashes — `FFD-013`

- Target: `postal-10k`, physical page 3 / printed page 49.
- Expected: the four zero-value cells preserve source em dashes instead of
  ASCII hyphens across JSON cell content, Markdown, and DOM.
- Owner: P02-US04, with P04-US01 table serialization secondary.
- Dependency: item 2.
- Risk/size: quick; a global hyphen substitution is forbidden because it can
  corrupt legitimate minus signs, redlines, and word punctuation.
- Affected rerun through both systems: `postal-10k` full PDF.
- Service controls: `finance-10k` pp1–3, `ny-timetable` pp1–3,
  `purchase-agreement` p1, and `catastrophe-recap` p1.
- Closure evidence: exact four source em dashes; numeric negatives, ordinary
  hyphens, smart quotes, and table column structure remain unchanged.

#### 4. ACORD lower coverage-grid ownership — `FFD-010`

- Target: `insurance-acord`, physical/printed page 1, lower coverage grid.
- Expected: one source-faithful semantic owner represents the lower grid with
  correct table-versus-form ownership; it is neither omitted nor duplicated.
- Owner: P04-US04, with P03-US06 and P03-US04 secondary.
- Dependency: item 3, because the shared table presentation path must be
  stable first.
- Risk/size: medium; an over-broad gate can turn forms or charts into false
  tables or suppress real borderless tables.
- Affected rerun through both systems: `insurance-acord` full PDF.
- Service controls: `health-report` p1, `component-datasheet` p3,
  `clinical-study` pp2 and 4, `ny-timetable` pp1–3, `finance-10k` pp1–3, and
  `postal-10k` pp1–3.
- Closure evidence: upper parties-and-insurers form remains once-only and
  unchanged; lower coverage grid has one owner; Health's blank visual-owned
  table remains suppressed; NY keeps 13 columns.

#### 5. Component NOTE private-use glyph — `FFD-007`

- Target: `component-datasheet`, physical page 2 / printed page 7, NOTE
  callout.
- Expected: the source NOTE callout is readable without a raw private-use
  character or duplicate generic image placeholder.
- Owner: P02-US01.
- Dependency: item 4 only as queue order; technically independent.
- Risk/size: quick, but recovery must require safe font/glyph evidence and
  must not invent a semantic icon name from an unknown private-use glyph.
- Affected rerun through both systems: `component-datasheet` full PDF.
- Service controls: `catastrophe-recap` p1, `clinical-study` pp1 and 4, and
  `purchase-agreement` p1.
- Closure evidence: readable NOTE presentation exactly once; raw glyph
  evidence remains attributable; healthy Unicode, legal symbols, and source
  smart quotes do not drift.

#### 6. Clinical damaged text and diacritics — `FFD-006`

- Target: `clinical-study`, principally physical pages 1, 2, and 4.
- Expected: source-supported names, diacritics, word boundaries, punctuation,
  DOI spacing, and body text remain intact without semantic completion.
- Owner: P02-US04, with P02-US01 as the font-evidence provider.
- Dependency: item 5, so private-use and normal Unicode policies are tested
  against each other.
- Risk/size: medium; candidate reconciliation can silently rewrite healthy
  multilingual text or choose two engines reading the same damaged layer.
- Affected rerun through both systems: `clinical-study` full PDF.
- Service controls: `catastrophe-recap` p1, `component-datasheet` p2,
  `esg-metrics` p1, `postal-10k` p1, and `settlement-agreement` p1.
- Closure evidence: a bounded source oracle for each repaired token; one
  selected representation; alternatives/provenance retained; no title/sidebar
  reorder is claimed by this text-only slice.

### Wave B — ownership, order, and hierarchy

#### 7. Shared visual-text owner boundaries — `FFD-001`

- Targets: `health-report` p1 chart 2, `manufacturing-report` p2 charts, and
  `uber-earnings` p3 first diagram.
- Expected: a source label crossing a coarse owner boundary is admitted only
  from uniquely attributable glyph/occurrence evidence; correct labels appear
  exactly once and noisy OCR is not promoted merely because it overlaps.
- Owner: P03-US02/P02-US06, with P03-US04 and P05-US03 consumers.
- Dependency: Wave A, especially item 6's candidate-evidence policy.
- Risk/size: high shared-root risk; this gate feeds charts, diagrams,
  canonical Markdown, and layout projection.
- Affected reruns through both systems: `health-report`,
  `manufacturing-report`, and `uber-earnings` full PDFs.
- Service controls: `catastrophe-recap` p1, `clean-energy` p1,
  `egov-survey` p1, `esg-metrics` p1, `clinical-study` p3,
  `component-datasheet` p2, and `insurance-acord` p1.
- Closure evidence: affected labels are source-grounded and once-only; owner
  bboxes are not widened; photographs, captions, tables, forms, and adjacent
  visual owners remain non-targets; `detected_text` remains boolean.

#### 8. Clinical reading order and hierarchy — `FFD-004`, `FFD-005`

- Target: `clinical-study`, especially p1 sidebar/title/abstract and source
  heading hierarchy.
- Expected: article title and main opening content precede the metadata
  sidebar as source layout requires; `Abstract`, `Background`, and subordinate
  sections retain a coherent hierarchy without moving table or flowchart
  ownership.
- Owner: P03-US04 and P03-US07.
- Dependency: items 6 and 7.
- Risk/size: medium-to-high; geometric ordering and heading inference can
  alter every page and stable element rank.
- Affected rerun through both systems: `clinical-study` full PDF.
- Service controls: `esg-metrics` p1, `manufacturing-report` pp1–3,
  `uber-earnings` pp1–3, `component-datasheet` p1, `finance-10k` pp1–3, and
  `purchase-agreement` p1.
- Closure evidence: exact reviewed order pairs and heading levels; IDs,
  bboxes, evidence, table order, printed pages, and running regions remain
  stable.

#### 9. ESG superscripts and source-column order — `FFD-004`, `FFD-006`

- Target: `esg-metrics` p1.
- Expected: source superscripts remain attributable and readable, and
  multi-column content follows source reading order without pulling chart or
  navigation content into prose.
- Owner: P03-US04 and P02-US01/P02-US04.
- Dependency: items 6 and 8.
- Risk/size: medium; column rules must not become document-specific semantic
  guesses.
- Affected rerun through both systems: `esg-metrics` full PDF.
- Service controls: `clinical-study` p1, `clean-energy` p1,
  `manufacturing-report` pp1–3, and `finance-10k` pp1–3.
- Closure evidence: reviewed source order pairs and superscripts pass in JSON,
  Markdown, and DOM; the two ESG chart owners remain distinct and once-only.

#### 10. Manufacturing caption/order and `4.3.` hierarchy — `FFD-004`, `FFD-005`

- Target: `manufacturing-report` pp1–3, especially captions/source lines and
  the printed `4.3.` hierarchy on p3.
- Expected: headings, charts, below-captions, source notes, and footers retain
  source order and ownership; `4.3.` is neither flattened nor promoted beyond
  its source level.
- Owner: P03-US04 and P03-US07.
- Dependency: items 7–9.
- Risk/size: medium; owner bundles and numbered-heading rules share the final
  canonical presentation path.
- Affected rerun through both systems: `manufacturing-report` full PDF.
- Service controls: `clinical-study` full PDF, `esg-metrics` p1,
  `uber-earnings` pp1–3, and `clean-energy` p1.
- Closure evidence: exact chart/caption/source/footer sequence on all three
  pages; no caption enters chart-owned OCR; no heading drift in controls.

#### 11. Uber page order, hierarchy, and construction filtering — `FFD-004`, `FFD-005`

- Target: `uber-earnings` pp1–3.
- Expected: p1 title/date/subtitle, p2 notes/footer, and p3 headings/footer
  follow visible source order; non-rendered construction text stays out of the
  primary view; legitimate printed chart labels remain available.
- Owner: P03-US04/P03-US08 and P03-US07.
- Dependency: items 7 and 10.
- Risk/size: high; visibility filtering must distinguish printed labels from
  hidden construction data without deleting valid chart evidence.
- Affected rerun through both systems: `uber-earnings` full PDF.
- Service controls: `finance-10k` pp1–3, `clinical-study` full PDF,
  `manufacturing-report` pp1–3, `purchase-agreement` p1, and
  `settlement-agreement` p1.
- Closure evidence: reviewed order pairs and heading levels pass; printed page
  identities remain null/5/6 as adjudicated; photo OCR remains diagnostic-only;
  p2 chart labels are retained for Wave C.

### Wave C — source-grounded chart semantics

Chart slices may organize only explicitly printed labels/values and
source-proven mark relationships. They must not reproduce LlamaParse's
interpolated bar/line values without an independently validated derivation,
provenance, and tolerance contract.

#### 12. eGov year/category series association — `FFD-003`

- Target: `egov-survey` p1.
- Expected: the existing 74 exact native occurrences are associated into the
  printed years, EGDI categories, and bar-label series with closed evidence
  references; `40` and `44` remain exact.
- Owner: P05-US03.
- Dependency: Wave B. This is the first chart case because it has complete,
  exact native labels and a single conventional panel.
- Risk/size: medium and the safest reusable chart-assembly proving case.
- Affected rerun through both systems: `egov-survey` full PDF.
- Service controls: `catastrophe-recap`, `clean-energy`, `esg-metrics`,
  `health-report`, `manufacturing-report`, and `uber-earnings`; non-chart
  controls `insurance-acord`, `component-datasheet`, and `ny-timetable`.
- Closure evidence: complete printed label association, no inferred values,
  zero lost/repeated labels, and context-free public chart validation.

#### 13. Catastrophe OCR and chart organization — `FFD-002`, `FFD-003`

- Target: `catastrophe-recap` p1 Exhibit 8.
- Expected: explicit legend, y-axis ticks, selected years, four panels, and
  region labels are normalized and ordered; fused/noisy OCR is absent from the
  primary view.
- Owner: P02-US06 and P05-US03.
- Dependency: item 12's association primitive.
- Risk/size: medium-to-high; sparse year anchors and unprinted bar values must
  remain unresolved rather than fabricated.
- Affected rerun through both systems: `catastrophe-recap` full PDF.
- Service controls: `egov-survey`, `clean-energy`, `health-report`,
  `manufacturing-report`, and `uber-earnings`; `postal-10k` and
  `finance-10k` as table/text controls.
- Closure evidence: four panels and printed legend/axis/year structure; chart
  text once-only; Exhibit 7 table and source note unchanged; no exhaustive
  inferred value matrix.

#### 14. Health owner closure and chart assembly — `FFD-001`, `FFD-003`

- Target: `health-report` p1, both charts and especially chart 2.
- Expected: item 7's boundary-safe labels close the second owner; both charts
  expose source-grounded axes, categories, and series organization without
  reviving the blank visual-owned table.
- Owner: P03-US02/P02-US06 and P05-US03.
- Dependency: items 7, 12, and 13.
- Risk/size: high; owner attribution, character coalescing, chart assembly, and
  false-table suppression interact on one page.
- Affected rerun through both systems: `health-report` full PDF.
- Service controls: `egov-survey`, `esg-metrics`, `catastrophe-recap`,
  `manufacturing-report`, and `insurance-acord`.
- Closure evidence: both charts validate; chart 2 contains correct labels once;
  series use only printed evidence; zero user-visible blank table rows.

#### 15. Clean Energy rotated OCR and six-panel structure — `FFD-002`, `FFD-003`

- Target: `clean-energy` p1.
- Expected: six technologies, local axes/units, repeated 2022/2023 categories,
  legends/callouts, and panel order are represented without rotated OCR noise
  or duplicate occurrences.
- Owner: P02-US06 and P05-US03.
- Dependency: items 12–14.
- Risk/size: high; the native layer is incomplete for OCR-visible years and
  each panel has an independent scale.
- Affected rerun through both systems: `clean-energy` full PDF.
- Service controls: `catastrophe-recap`, `egov-survey`, `esg-metrics`,
  `manufacturing-report`, `component-datasheet`, and `insurance-acord`.
- Closure evidence: six panels, complete printed category/axis evidence,
  once-only OCR, and no Llama-inferred bar values.

#### 16. ESG OCR and fiscal-chart organization — `FFD-002`, `FFD-003`

- Target: `esg-metrics` p1, especially the small fiscal-row chart.
- Expected: noisy/fused fiscal OCR is corrected or withheld with evidence, and
  both chart regions expose complete printed label/series organization.
- Owner: P02-US06 and P05-US03.
- Dependency: item 9 for page order and item 15 for bounded small-panel
  organization.
- Risk/size: high; small labels, footnote fusion, and owner boundaries can make
  plausible but false year/series associations.
- Affected rerun through both systems: `esg-metrics` full PDF.
- Service controls: `egov-survey`, `health-report`, `clean-energy`,
  `manufacturing-report`, and `clinical-study` p1.
- Closure evidence: no `FY245`/`CY211`-style fused token in primary output;
  exact source occurrences and series close; superscript/order fixes remain.

#### 17. Manufacturing chart series and curve semantics — `FFD-003`

- Target: `manufacturing-report` pp1–3, all five chart owners.
- Expected: complete source-grounded series and curve organization across the
  mixed vector/raster charts while every unsupported interpolated value remains
  absent.
- Owner: P05-US03.
- Dependency: items 7, 10, and 12–16.
- Risk/size: deep; five regions span multiple chart families, rotated labels,
  owner boundaries, and raster/vector evidence.
- Affected rerun through both systems: `manufacturing-report` full PDF.
- Service controls: all other chart cases (`catastrophe-recap`,
  `clean-energy`, `egov-survey`, `esg-metrics`, `health-report`,
  `uber-earnings`) plus `clinical-study` p3 and `component-datasheet` p2 as
  diagram/image non-targets.
- Closure evidence: all five charts validate with stable panels/axes/series;
  caption/order/hierarchy remains fixed; no inferred time-series table.

#### 18. Uber page-2 chart assembly — `FFD-003`

- Target: `uber-earnings` p2, Gross Bookings and Adjusted EBITDA/margin charts.
- Expected: printed years, endpoints, axes, bar/line series, and combo-chart
  roles are organized with explicit provenance; hidden construction values and
  unprinted intermediate values remain out of the primary structured result.
- Owner: P05-US03.
- Dependency: items 7, 11, and 12–17.
- Risk/size: deep; one chart is combined bar/line and source contains hidden
  construction text alongside valid endpoint labels.
- Affected rerun through both systems: `uber-earnings` full PDF.
- Service controls: all six other chart cases plus `clinical-study` p3,
  `component-datasheet` p2, and `uber-earnings` p1 photograph.
- Closure evidence: two valid chart owners; printed endpoints exactly once;
  no intermediate geometry-inferred values without proof; p1 photo and p3
  diagrams remain unchanged.

### Wave D — source-grounded diagram semantics

#### 19. Clinical raster flowchart topology — `FFD-008`

- Target: `clinical-study` p3 / printed page 10.
- Expected: visible nodes, containment, connectors, endpoints, and direction
  are represented only where raster/path evidence proves them; detail bullets
  stay with their owning nodes.
- Owner: P05-US10.
- Dependency: items 6–8 and 7's owner-boundary contract.
- Risk/size: deep, but this is the first diagram family because it is a
  conventional directed flowchart with visible connectors.
- Affected rerun through both systems: `clinical-study` full PDF.
- Service controls: `uber-earnings` p3, `component-datasheet` p2,
  `clean-energy` p1, `health-report` p1, and `uber-earnings` p1 photograph.
- Closure evidence: every emitted node/edge has source geometry and evidence;
  ambiguous connectors remain unresolved; caption/OCR occurs exactly once.

#### 20. Uber undirected fan/group geometry — `FFD-008`; new story required

- Target: `uber-earnings` p3, both seven-node association diagrams.
- Expected: explicit fan/group geometry is represented as source-grounded
  undirected association or grouping, with zero invented arrow direction.
- Story action: create a bounded Phase 05 follow-up story for undirected visual
  association/group topology. Do not expand completed P05-US10's directed-edge
  contract silently.
- Dependency: item 19 establishes directed-flow positives and missing-arrow
  negatives.
- Risk/size: deep; spatial proximity alone must never create a relationship.
- Affected rerun through both systems: `uber-earnings` full PDF.
- Service controls: `clinical-study` p3, `component-datasheet` p2,
  `manufacturing-report` charts, and `uber-earnings` p1 photograph.
- Closure evidence: two seven-node groups; fan evidence linked to source
  geometry; zero directed connectors; chart and order fixes remain stable.

#### 21. Component pinout OCR and topology — `FFD-002`, `FFD-008`; new story required

- Target: `component-datasheet` p2 / printed page 7.
- Expected: explicit pin labels are readable and spatially associated into a
  source-grounded pinout/engineering graph without generated board prose or
  guessed electrical semantics.
- Story action: create a bounded Phase 05 follow-up story for engineering and
  pinout topology. P05-US10 currently treats this diagram family as a
  non-target, so an acceptance addendum is insufficient.
- Dependency: item 5 for NOTE glyph behavior, item 7 for owner attribution,
  and items 19–20 for diagram-family separation.
- Risk/size: deepest and specialized; incomplete raster labels must not be
  auto-completed into a 1–40 sequence.
- Affected rerun through both systems: `component-datasheet` full PDF.
- Service controls: `clinical-study` p3, `uber-earnings` p3,
  `component-datasheet` p1 photograph, and `health-report` p1 charts.
- Closure evidence: every emitted pin/node/association has visible label or
  geometry evidence; uncertain pins remain explicit concerns; p1 photograph,
  p2 NOTE, and p3 key-value/table content remain stable.

### Wave E — diagnostic adjudication and final release gate

#### 22. Component board-photo diagnostic OCR — `FFD-009`; re-adjudicate first

- Target: `component-datasheet` p1 board photograph diagnostic JSON.
- Required first action: decide whether noisy diagnostic-only OCR is a public
  functional defect or an acceptable, clearly labelled alternative. Do not
  change production behavior before this source/API adjudication.
- Story action: if retained as release-blocking, create a dedicated diagnostic
  OCR quality/provenance story. Existing primary-text stories intentionally
  permit attributable alternatives and do not promise clean diagnostic prose.
- Dependency: items 5 and 21; the NOTE and pinout paths must already establish
  the intended image/diagram boundaries.
- Risk/size: low user impact but high false-suppression risk.
- Affected rerun through both systems if retained: `component-datasheet` full
  PDF.
- Service controls: `uber-earnings` p1 photograph, `insurance-acord` p1 logo,
  `manufacturing-report` visual regions, and `component-datasheet` pp2–3.
- Closure evidence if fixed: diagnostic text is visibly source-supported,
  explicitly non-primary, and attributable; no photograph OCR enters Markdown
  or UI. If accepted instead, record the non-primary contract and source-grounded
  rationale in FFD-009 and the final release disposition.

## Exact rerun matrix summary

`Both` means a fresh full-PDF LlamaParse job plus a fresh full-PDF service job.
`Control` means a fresh service run compared with the immutable selected
LlamaParse reference; refresh LlamaParse whenever that control changes on any
reviewed surface.

| Item | FFD | Both: affected full PDFs | Control full PDFs |
|---:|---|---|---|
| 1 | FFD-011 | postal-10k | ny-timetable, clinical-study, finance-10k, purchase-agreement |
| 1a | FFD-014 | clinical-study | postal-10k, ny-timetable, catastrophe-recap, component-datasheet |
| 2 | FFD-012 | postal-10k | purchase-agreement, settlement-agreement, clinical-study, finance-10k |
| 3 | FFD-013 | postal-10k | finance-10k, ny-timetable, purchase-agreement, catastrophe-recap |
| 4 | FFD-010 | insurance-acord | health-report, component-datasheet, clinical-study, ny-timetable, finance-10k, postal-10k |
| 5 | FFD-007 | component-datasheet | catastrophe-recap, clinical-study, purchase-agreement |
| 6 | FFD-006 | clinical-study | catastrophe-recap, component-datasheet, esg-metrics, postal-10k, settlement-agreement |
| 7 | FFD-001 | health-report, manufacturing-report, uber-earnings | catastrophe-recap, clean-energy, egov-survey, esg-metrics, clinical-study, component-datasheet, insurance-acord |
| 8 | FFD-004, FFD-005 | clinical-study | esg-metrics, manufacturing-report, uber-earnings, component-datasheet, finance-10k, purchase-agreement |
| 9 | FFD-004, FFD-006 | esg-metrics | clinical-study, clean-energy, manufacturing-report, finance-10k |
| 10 | FFD-004, FFD-005 | manufacturing-report | clinical-study, esg-metrics, uber-earnings, clean-energy |
| 11 | FFD-004, FFD-005 | uber-earnings | finance-10k, clinical-study, manufacturing-report, purchase-agreement, settlement-agreement |
| 12 | FFD-003 | egov-survey | catastrophe-recap, clean-energy, esg-metrics, health-report, manufacturing-report, uber-earnings, insurance-acord, component-datasheet, ny-timetable |
| 13 | FFD-002, FFD-003 | catastrophe-recap | egov-survey, clean-energy, health-report, manufacturing-report, uber-earnings, postal-10k, finance-10k |
| 14 | FFD-001, FFD-003 | health-report | egov-survey, esg-metrics, catastrophe-recap, manufacturing-report, insurance-acord |
| 15 | FFD-002, FFD-003 | clean-energy | catastrophe-recap, egov-survey, esg-metrics, manufacturing-report, component-datasheet, insurance-acord |
| 16 | FFD-002, FFD-003 | esg-metrics | egov-survey, health-report, clean-energy, manufacturing-report, clinical-study |
| 17 | FFD-003 | manufacturing-report | catastrophe-recap, clean-energy, egov-survey, esg-metrics, health-report, uber-earnings, clinical-study, component-datasheet |
| 18 | FFD-003 | uber-earnings | catastrophe-recap, clean-energy, egov-survey, esg-metrics, health-report, manufacturing-report, clinical-study, component-datasheet |
| 19 | FFD-008 | clinical-study | uber-earnings, component-datasheet, clean-energy, health-report |
| 20 | FFD-008 | uber-earnings | clinical-study, component-datasheet, manufacturing-report |
| 21 | FFD-002, FFD-008 | component-datasheet | clinical-study, uber-earnings, health-report |
| 22 | FFD-009 | component-datasheet, only if retained after adjudication | uber-earnings, insurance-acord, manufacturing-report |

## Wave gates

Every wave gate preserves a new immutable service artifact root, the selected
or refreshed LlamaParse references, hashes, commands/profile, public JSON,
raw/canonical Markdown, rendered DOM, and source-page renders.

### Wave A gate

- Items 1, 1a, and 2–6 pass their focused regressions and exact matrices.
- Clinical page-1 visual custody commits at the unchanged production deadlines
  while its one public placeholder, contributor, order, and closed graph remain
  exact; no page-2-specific work is included in item 1a.
- Postal pp1 and 3 have no FERS duplicate, preserve four italic spans, and use
  four source em dashes.
- ACORD's upper form and lower coverage grid each have one semantic owner.
- Component NOTE and Clinical repaired text are source-grounded once-only.
- All 15 service PDFs reparse successfully with no unrelated JSON, Markdown,
  table, order, or DOM drift.

### Wave B gate

- Items 7–11 pass their focused regressions and exact matrices.
- Health/Manufacturing/Uber owner-boundary labels close without bbox widening,
  duplication, or photograph/form/table contamination.
- Clinical, ESG, Manufacturing, and Uber reviewed order/hierarchy assertions
  pass on JSON, raw Markdown, and DOM.
- All 15 service PDFs pass an order, hierarchy, canonical-custody, and rendered
  drift screen.

### Wave C gate

- Items 12–18 pass their focused regressions and exact matrices.
- All seven chart PDFs (`catastrophe-recap`, `clean-energy`, `egov-survey`,
  `esg-metrics`, `health-report`, `manufacturing-report`, and
  `uber-earnings`) are rerun through both systems into fresh immutable roots.
- Every emitted panel, axis, legend, category, series, point, or value closes
  over source evidence. Unsupported Llama-interpolated values remain absent.
- ACORD, Component, Clinical, NY, Postal, and photograph controls show no
  table/form/image/diagram promotion drift.
- All 15 service PDFs pass the complete drift screen.

### Wave D gate

- Items 19–21 pass their focused regressions and exact matrices.
- Clinical, Uber, and Component are rerun through both systems.
- Directed edges require explicit direction; undirected associations require
  explicit fan/group geometry; pinout structure requires visible label and
  spatial evidence. No relationship is created from proximity or language
  plausibility alone.
- All chart, photograph, table, form, caption, and source-order controls pass.
- All 15 service PDFs pass the complete drift screen.

### Wave E and final release gate

- FFD-009 is either fixed under a new approved story or explicitly accepted as
  a non-primary diagnostic difference with source/API evidence.
- Execute the complete normative gate in
  [`final-all-15-validation.md`](final-all-15-validation.md) against one frozen
  release candidate. Its requirements supersede any abbreviated final-run
  language in individual issue cards.
- Rerun all 15 complete PDFs through both LlamaParse and the service into new,
  immutable artifact roots. Preserve job IDs, source/settings/build identity,
  hashes, full original JSON, raw Markdown, and the actual rendered UI/DOM for
  both systems.
- Compare and source-adjudicate document structure/order, text and OCR,
  Markdown and rendered presentation, tables and merged cells, forms,
  charts/diagrams, images and image-derived content, formatting, and full JSON
  type/page/nesting/component order for every PDF.
- Require a genericity packet for every fix. Any filename-, hash-, page-,
  benchmark-, job-, or document-specific production rule fails the gate even
  if all benchmark outputs appear to match.
- Regenerate the comparator, artifact manifest, source-grounded disposition,
  defect registry, issue statuses, per-case status table, approvals, and
  consolidated report. Unit tests, aggregate scores, or text-only comparisons
  cannot close this gate.
- A case is `fixed` only when every FFD affecting it is Done. Every material
  discrepancy must be resolved or explicitly approved as acceptable with
  bounded source evidence. The product may be declared functionally on par
  with LlamaParse only after all 15 rows and every artifact, review, and
  genericity requirement in the normative gate pass.

## Case-closure checkpoints

These are planning checkpoints, not automatic status transitions:

| Case | Required completed items before final source review |
|---|---|
| postal-10k | 1–3 |
| insurance-acord | 4 |
| component-datasheet | 5, 21, and 22 disposition |
| clinical-study | 1a, 6, 8, 19 |
| health-report | 7, 14 |
| manufacturing-report | 7, 10, 17 |
| uber-earnings | 7, 11, 18, 20 |
| esg-metrics | 9, 16 |
| egov-survey | 12 |
| catastrophe-recap | 13 |
| clean-energy | 15 |

The three already-fixed cases (`finance-10k`, `ny-timetable`, and
`purchase-agreement`) and the accepted-difference case
(`settlement-agreement`) remain mandatory regression controls throughout this
queue.

## 2026-08-15 item 19 current-code checkpoint

The implementation target for item 19, Clinical physical-page-3 directed
raster topology, is green in the current service and renderer. One grounded
root, 15 nodes, 14 explicit-arrow connectors, and 13 owned details serialize as
one semantic nested list. The caption and `.g001` visual note each occur once
in the required order, page 2 contains zero `.g001` occurrences, and no
paragraph, Mermaid, or node/connection-debug fallback is present. The fresh
four-page current-renderer capture also retains one structured candidate table
on each of physical pages 2 and 4.

The full Clinical integration passed **2 tests in 28.15 seconds**; the adjacent
backend family passed **523 tests in 6.38 seconds**; and the complete frontend
unit suite passed **182 tests** together with TypeScript, focused ESLint, and
the production build/bundle.

This checkpoint does not mark item 19 `Done` under the per-slice transition
gate: it does not claim the required fresh LlamaParse/service immutable
Markdown, actual UI/DOM, full-JSON, and complete-output drift package. Items 20
and 21, the Wave D gate, and final all-15 validation remain pending. FFD-008
therefore remains `Proposed`; FFD-014 remains the sole `In Progress` defect and
FFD-011 remains `Blocked`.
