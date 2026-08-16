# Phase 03 Regression Plan

Run Phase 00–03 regressions, API/schema contracts, canonical serialization, and
existing layout/image/table suites.

Required assertions:

- type and relationship precision/recall for captions and source notes;
- reading-order pair accuracy;
- caption bbox does not become the object's bbox;
- every serialized title appears exactly once;
- internal children remain evidence, not document prose unless explicitly typed;
- footer/header behavior and table ordering do not regress;
- direct images and rendered PDF regions use the same relationship rules.

LlamaParse-15 fixture slices:

- positive: `catastrophe-recap` p1 captions/source note,
  `clinical-study` p2/p4 table captions/notes, `purchase-agreement` p1
  redlines, `insurance-acord` p1 form controls, `component-datasheet` p1 lists
  and p3 key-values, `settlement-agreement` p1 clauses, and mismatched printed
  page excerpts;
- non-target: `finance-10k` native financial tables, ordinary underlined
  headings, natural images, body numbers, and plain parenthesized prose;
- negative/ambiguous: shared/dangling captions, two possible note owners,
  cyclic order edges, decorative/table rules, ambiguous squares, broken list
  markers, and conflicting page labels.

Required benchmark assertions cover `GAP-LAYOUT-001`, `GAP-ORDER-001`,
`GAP-PAGE-001`, `GAP-REDLINE-001`, `GAP-FORM-001`, `GAP-LIST-001`,
`GAP-LINK-001`, `GAP-BBOX-001`, `GAP-PROVENANCE-001`,
`GAP-DIAGNOSTICS-001`, and `GAP-SERIALIZATION-001`. Run each story flag both
on and off, verify its documented rollback, and record p50/p95 latency, peak
RSS, and output-size deltas. `uber-earnings` remains the Phase 03 memory guard.

## P03-US01 checkpoint

Status: Pass

- Exact catastrophe p1 and clinical p2/p4 caption page/text/bbox identities:
  3/3.
- Caption precision/recall, bbox coverage, and relationship/backlink coverage:
  1.0; duplicates and unexpected captions: 0.
- Table rows/cells: identical flag on/off.
- Finance non-target: exact semantic JSON and Markdown parity.
- Negative/adversarial coverage: internal, dangling, shared, orphan,
  generated, empty, non-text, malformed, multiline, multiple, duplicate,
  overlap-chain, conflicting-text, and overflow candidates.
- Bounds: 64 references/table, 128 same-text candidates/page, 512 total
  candidates/page; overflow does zero pairwise geometry work.
- Backend focused/real/custody gate: 62 passed. Independent broader impacted
  gate: 124 passed with one documented opt-in skip.
- Frontend Node 22.18: lint, typecheck, production build, 46 unit tests, and
  one bundle test passed.
- Retained artifact:
  `evidence/P03-US01-table-caption-metrics.json`, SHA-256
  `98ccfb93b352dee0d01b5d614b1b298816ff80d817f1363fe27f682906f2857a`.

This checkpoint closes only the external table-caption slice. Visual captions,
source notes, generalized order/bbox ownership, redlines, forms, outlines, and
running regions remain open under P03-US02–US08.

## P03-US02 checkpoint

Status: Pass

- Exact catastrophe Exhibit 8 and manufacturing Figure 2.2/2.7/2.8/4.3
  caption identities: 5/5; precision/recall, bbox, side-order, relationship,
  backlink, and owner-clean coverage: 1.0.
- Exhibit 8 internal children: exact values/bboxes; zero caption fragments.
- Uber photograph: exact frozen 15-value subordinate set, no invented caption,
  primary OCR, page-item, or canonical-primary leak.
- Component caption: preserved once unowned; finance: exact flag parity.
- Negative/adversarial coverage: raw generated/model/derived laundering,
  nested/overflow/malformed provenance, missing raw values, punctuation caption,
  table cross-domain promotion, shared/ambiguous geometry, malformed endpoints,
  and payload/reference/concern overflow.
- Bounds: 64 captions and 256 children/owner, 512 owners and 512 combined
  caption candidates/page, 128 same-text candidates/page, 64 KiB/caption,
  256 KiB contained JSON/owner, and bounded provenance/concern scans.
- Focused US02: 74 passed; adjacent US01: 37 passed; real corpus: 7 passed;
  custody: 8 passed; broad matrix: 1,347 passed with one documented opt-in skip.
- Frontend Node 22.18: lint, typecheck, production build, 60 unit tests, and
  one bundle test passed.
- Retained artifact:
  `evidence/P03-US02-visual-relationship-metrics.json`, SHA-256
  `8fa4704412f75138f885b8b8a6c7b62053f2232f9ce1070f509df5ded12462d3`.

This checkpoint closes visual caption/child separation. Source notes,
generalized order/bbox ownership, redlines, forms, outlines, and running
regions remain open under P03-US03–US08.

## P03-US03 checkpoint

Status: Pass

- Exact reviewed source notes/footnotes: 8/8 — Aon 1, Clinical Table 1 three,
  and Clinical Table 2 four.
- Exact emitted note/control inventory: 14/14; five grounded links; zero false
  associations, missing controls, unexpected records, bbox/order violations,
  unresolved endpoints, duplicate IDs, backlink failures, or canonical
  descriptor failures.
- Health note and both StatLinks retain exact unique ownership; finance retains
  exact semantic JSON and Markdown parity.
- Negative/adversarial coverage: nearby footer/prose, distant and orphaned
  notes, competing owners, cross-page edges, raw-edge rollback, generated and
  nested provenance, malformed Unicode, annotation overflow, unsafe/overlong
  links, duplicate IDs/backlinks, and canonical exception paths.
- Bounds: 64 references/owner, 256 owners/page, 512 candidates/page, 128
  same-text candidates/page, 16 KiB/note, 2 KiB/URI, 256 annotations/page,
  1,024 annotations/document, and 16 narrow OCR bands/page.
- Final US03 focused/real gate: 71 passed; retained: 4 passed; predecessor
  story/contract/performance/custody gate: 169 passed; predecessor real corpus:
  12 passed.
- Frontend Node 22.18: lint, typecheck, production build, 65 unit tests, and
  one bundle test passed.
- Retained artifact:
  `evidence/P03-US03-source-note-metrics.json`, SHA-256
  `c9f0cbbc0071bdf47ad19b00c6ed2996fb9bb80b1bf785bf9ae3e3c128a8ef7f`.

This checkpoint closes source-note/footnote association. Generalized
relationship order/bbox ownership, redlines, forms, outlines, and running
regions remain open under P03-US04–US08.

## P03-US04 checkpoint

Status: Pass

- Fixed reviewed relationship-order denominator: **41/41** across catastrophe,
  clinical, component, ESG, manufacturing, purchase, timetable, clean-energy,
  and finance.
- Side-aware captions/notes remain atomic and distinct; physical-page-2
  timetable prefixes precede their table; the page-3 negative is unchanged.
- All enabled IDs are unique, ranks contiguous, canonical/public order aligned,
  JSON round trips exact, and keyed mutations limited to the two audited
  clean-energy/clinical corrections.
- Finance semantic JSON/Markdown and all flag-off outputs preserve exact
  predecessor parity.
- Negative/adversarial coverage includes cycles, duplicate anchors, ownership
  conflicts, partial overlaps, unavailable/cross-unit/affine transforms,
  untrusted and borrowed markers, malformed presentation/evidence, byte/node/
  reference/page/document limits, diagnostic caps, validation rollback, and
  terminal source-alignment re-entry.
- Bounds: 512 anchors/page and 65,536/document; 4,096 edges/page and
  65,536/document; 64 refs/anchor; bounded prefix, presentation, evidence, IR,
  and concern work.
- Final focused/performance/custody gate: **47 passed**; real corpus:
  **44 passed**; independent truth/security and contract reviews:
  **10/10 Pass** each.
- Frontend Node 22.18: lint, typecheck, production build, **67 unit tests**,
  and one bundle test passed.
- Retained artifact:
  `evidence/P03-US04-reading-order-metrics.json`, SHA-256
  `826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154`.

This checkpoint closes generalized relationship-aware presentation order and
source-bbox ownership. Redline/text-run semantics, forms/key-values, outline
hierarchy, and running-region/page identity remain open under P03-US05–US08.

## P03-US05 checkpoint

Status: Pass

- Purchase fixed denominator: **28** runs, **13** rules, **3/3** omission
  repairs, **6/6** deleted groups, **7/7** group/rule edges, **9/9** deleted
  run/rule links, **2/2** blue runs, and **4/4** underline links.
- `EXECUTION VERSION`, `Background`, `Exhibit A`, postal, finance, ordinary
  underline, decorative/table rule, ambiguity, boundary, and transform
  controls produce zero false deletion.
- Postal italic targets bind exact table cells 20/21/66/67; finance retains 26
  bold runs with zero deletion; no PDF run is inferred inserted/replacement.
- Complete source text, exact target offsets/digests, redline Markdown, active
  omission IDs, canonical/public order, frontend overlays, and P03-US04
  **41/41** order remain coherent.
- Negative/adversarial coverage includes strict/curly quote matching,
  divergent fallbacks, NFKC cluster boundaries, scalar/child aliases,
  competing targets, setext/markup injection, transforms, page rollback,
  report custody, concern idempotence, and aggregate line clustering.
- Bounds cover source characters, page/document runs and rules, traversal,
  slots, target bytes, per-run/font bytes, comparisons, associations, links,
  report bytes, deadlines, and page/document/total diagnostics. Exact/max+1
  tests cover every frozen resource class.
- Integrated US05 gate: **147 passed**; cumulative Phase 01 and P03-US01–US04:
  **566 passed**; performance: **10 passed**; retained custody: **5 passed**.
- Frontend Node 22.18: lint, typecheck, production build, **76 unit tests**,
  and one bundle test passed.
- Flag-off zero-extractor behavior and all 15 sealed Phase 01 serialized IR
  hashes/sizes preserve exact predecessor parity.
- Live purchase source composition is **7/7**, and enabled public/canonical
  source order is **41/41** across the nine retained P03-US04 cases.
- Retained artifact:
  `evidence/P03-US05-text-run-metrics.json`, raw SHA-256
  `0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659`,
  semantic SHA-256
  `e432ce80d6351d1d161010aec7f8b32a1622a54cf1b14e14bfccb3411c79c3c3`.

This checkpoint closes source-visible redline/text-run semantics. Forms and
key-values, outline/list hierarchy, and running-region/printed-page identity
remain open under P03-US06–US08. No Phase 04 work has started.

## P03-US06 checkpoint

Status: Pass

- ACORD exact reviewed denominator: **6** groups, **42** labels, **24** empty
  fields/value regions, **24** controls, and **216** relationships, with zero
  fabricated values or checked states and the mixed coverage table retained.
- Component exact reviewed denominator: **3** replace-mode groups, **16**
  ordered key-value pairs, and **80** relationships with exact predecessor
  contributor custody and canonical Markdown/text parity.
- Negative/adversarial coverage includes decorative and filled squares,
  ambiguous overlaps, true tables, malformed/cyclic AcroForms, transform and
  geometry failures, Unicode/markup concerns, source/report bytes, object and
  resolution work, group-role limits, candidate comparisons, relationships,
  deadlines, transaction rollback, and terminal source-alignment re-entry.
- Bounds cover 8,192 records/page and 32,768/document; 32,768
  relationships/page and 65,536/document; 32,768 AcroForm identities and
  65,536 resolution steps; 256 KiB/group; 64 contributors; 128 fields/value
  regions; 256 controls/labels; 32 pairs; and 13 concern codes.
- Final backend gates: **142 passed** focused, **19 passed** performance, and
  **26 passed** cap/source-security. Compilation, Ruff, all 25 synthetic
  fixture self-checks/37 capabilities, and both local readers pass.
- Frontend Node 22.18: lint, typecheck, production build, **84/84** unit
  tests, and **1/1** bundle test pass.
- Independent projection audit passes **70** focused tests, 100,000 coverage
  oracle queries, 2,500 ruled-cell brute comparisons, 10,000 compact-JSON
  randomized checks, exact comparison ledgers, and predecessor isolation.
- Five-pair ACORD/component performance, allocation, RSS, output, custody,
  deterministic replay, exact rollback, and zero-hosted-use gates pass.
- Passing retained artifact:
  `evidence/P03-US06-form-metrics.json`, raw SHA-256
  `7e7da0d0d2a2f528b247e560399940e7c091ad765903ef5177381d140a01c290`,
  semantic SHA-256
  `7cfff9b19f129ab29f2a14317a479c50ed38397921ef9111b0a4b57f7d557fc7`.
- The first complete failed candidate remains preserved unchanged and records
  its single ACORD paired-gate failure; no waiver was used.

This checkpoint closes forms and key-values. Outline/list hierarchy and
running-region/printed-page identity remain open under P03-US07–US08. No
Phase 04 work has started.

## P03-US07 checkpoint

Status: Pass

- Component exact denominator: **2 groups / 16 nodes / 32 relationships**, with
  11 bullet roots, five circle children, five parent edges, 11 next edges, and
  16 contains edges.
- Settlement exact denominator: **1 group / 3 nodes / 6 relationships**, with
  literal `a.`/`b.`/`c.`, two next edges, three contains edges, and one exact
  table-to-`b.` continuation. Combined output is **3/19/38**.
- Marker/item bboxes, source values, ordinals, parents, evidence paths,
  backlinks, canonical Markdown/text, predecessor IDs, deterministic replay,
  and terminal re-entry are exact.
- Component retains exact P03-US06 form ownership at **3 groups / 16 pairs /
  80 relationships** and P03-US04 remains **41/41**. Finance produces zero
  outlines; all 11 synthetics retain the approved positive/non-target
  partition and both local readers accept all nine PDFs.
- Negative/adversarial coverage includes parenthesized prose/alpha, broken
  sequence, ambiguous indentation, financial rows, marker injection, source
  report tampering, malformed/partial sidecars, crossed graph evidence,
  reversed next edges, unsafe/encoded links, page/document rollback, terminal
  replay mismatch, and flag-off zero module loading.
- All **22** resource and **3** deadline exact/max+1 gates pass. Extraction
  p95 is **171.112/56.917 ms** and projection p95 is **32.115/5.529 ms** for
  component/settlement. Five-pair p95 overhead is **481.838 ms ≤ 528 ms** and
  **138.590 ms ≤ 299.231 ms**; maximum RSS deltas are
  **17,498,112/10,895,360 bytes**.
- Final backend files collect **115 tests**: 21 story/readiness, 23 contract,
  19 real/control, 47 performance/resource, and five retained custody tests.
  Frontend Node 22.18 lint, typecheck, production build, **90/90 unit tests**,
  and **1/1 bundle test** pass. Python compilation and Ruff pass.
- Live local-parser plus production-frontend-renderer checks pass: component
  **2/16/32** renders two semantic `<ul>` roots and a nested `<ul>` at
  pages/labels **3/[1,2,3]**; settlement **1/3/6** renders one semantic `<ol>`
  plus its owned parsed table at **1/[1]**. Canonical Markdown/JSON remain
  exact and no raw `<script>` appears. Browser click-through remains unclaimed;
  automated proxy contracts pass and the stalled dev proxy with a healthy
  backend is classified as a local environment/tooling limitation.
- Independent production/security and final metrics/custody reviews approve
  the final implementation. Hosted requests/tokens/cost are **0/0/$0**.
- Retained artifact:
  `evidence/P03-US07-outline-metrics.json`, **136,091 bytes**, raw SHA-256
  `cbfe68a90a225adc9896435f7197389998df8ddddfca2ae94f8a917807490765`,
  semantic SHA-256
  `22c208d8f625cb917e3e27097c6c60fc5fb904282ac7ae3e530dbffdf62d2639`.
- Two unsealed candidates failed only the component paired whole-parser gate
  at **639.774 ms** and **1,013.963 ms** and were rejected without waiver;
  one complete unchanged uncontended campaign passed.

This checkpoint closes outline/list/legal-clause hierarchy. Only
running-region/physical-page/printed-page identity remains open under
P03-US08. No Phase 04 work has started.

## P03-US08 checkpoint

Status: Pass with approved, active, time-bounded metrics exception renewal

- Exact reviewed identity denominator: **30/30 pages**, with **27** detected
  source-visible printed labels and **3** explicit nulls. Physical identity,
  embedded label, detected label, legacy fallback, and display value remain
  distinct.
- Exact running-region denominator: **47/47** regions — 16 headers, 30
  footers, zero top navigation regions, and one bottom navigation region.
  Body excludes every accepted running region; Full includes each once in
  source-proven order.
- Canonical output retains **223 Body**, **16 header**, **31 footer**, and
  **270 Full** blocks. The manufacturing fused owner remains byte-identical
  publicly and its source reconstruction is exact.
- Strict additive public/IR/canonical contracts, physical-only navigation,
  source/page identity, relationship custody, bounded resources and deadlines,
  atomic rollback, idempotent replay, and default-off predecessor parity pass.
- Fresh active-renewal verification passes: the six-file focused Phase 03/US08
  gate records **291 passed, 1 intentional strict-final skip, 1 warning in
  65.87 seconds**, and the focused renewal guard records **28/28 passed, 1
  pre-existing Starlette warning in 16.88 seconds**.
- Attempt 48 remains an immutable failed candidate. Its sole failure is the New
  York timetable projection p95 of **0.050946750 seconds** against the strict
  **0.050000000-second** ceiling: **0.000946750 seconds / 1.8935%** over.
- The requester-approved exception is candidate-specific, capped at 5%, and
  applies only to that latency observation for P03-US08 exit adjudication. It
  does not change the strict ceiling or convert attempt 48 into passing
  evidence.
- The complete companion remains quarantined at
  `evidence/P03-US08-running-region-metrics-attempt-31-post-seal-invalid.json`.
  It completed **20/20** paired workers and passed every strict aggregate gate,
  including peak RSS deltas of **12,877,824** bytes for Uber and **47,316,992**
  bytes for New York, both below 64 MiB. RSS is not waived.
- Current code has renewed 86-path manifest
  `b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`.
  It differs from attempt 48 at exactly the two authorized frontend paths, so
  **84/86** required paths match. All **29** `app/**` backend paths remain
  identical, with manifest
  `3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`,
  and `measured_backend_parser_runtime_paths_match_original` is true. Current
  code differs from the companion at exactly four paths, so **82/86** match.
- The canonical strict final artifact is absent. The active renewal waiver
  binds the immutable original decision and waiver, attempt 48, the quarantined
  companion, the failed ledger through attempt 55, the exact frontend delta,
  current manifest, zero hosted use, default-off rollback, and expiry.

This checkpoint closes running-region and physical/printed-page identity only
under active renewal
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX`](decisions/P03-US08-frontend-bbox-latency-exception-renewal.md),
with its executable record in
[P03-US08-frontend-bbox-latency-waiver-renewal.json](evidence/P03-US08-frontend-bbox-latency-waiver-renewal.json).
The renewal must be reviewed by **2026-09-02** and expires earlier on any
further required-code custody change, production enablement, or Phase 04 exit.
Expiry or revocation returns P03-US08 to In Progress and blocks dependent exit
claims. Phase 04 remains Proposed and unstarted pending separate authorization.

## Phase 03 exit checkpoint

Status: Complete with approved, active, time-bounded metrics exception —
**8/8 stories, 38/38 points Done**

- All Phase 03 functional, schema, source-custody, rollback, security, output,
  resource, and default-off acceptance gates pass within their declared
  scopes.
- P03-US08 closes through the narrow exception above, not through a strict
  current-artifact pass. No other failed gate, including peak RSS, is waived.
- Retained pre-renewal complete-backend regression: **2,383 passed, 11 skipped,
  163 warnings in 892.68 seconds (14:52)**. It predates the frontend correction
  and renewal guard/test changes and is not claimed as a fresh
  current-required-code run; all 29 `app/**` backend/parser paths remain
  identical, while the fresh 291/28 focused gates cover the active renewal.
- Python compilation: **Pass**. Offline dependency lock integrity:
  **Pass — 140 packages resolved with no lock drift**.
- Frontend Node **24.14.0** lint, typecheck, production build, **106/106 unit
  tests**, and **1/1 bundle test** pass after the compatibility correction;
  responsive checks remain **22/22**.
- Live `clinical-study.pdf` UI verification passes with four physical pages,
  printed label `1/21`, 22 canonical blocks, and working Body/Full views.
- The strict final-candidate test remains one expected skip because the
  canonical strict final artifact is intentionally absent; this limitation is
  disclosed rather than reclassified.
- Detailed exit adjudication and evidence identities are recorded in
  `reports/P03-phase-exit-completion.md` and
  `evidence/P03-phase-exit-verification.md`.
- Phase 04 remains Proposed and unstarted. Its implementation and status
  transition require separate authorization.

### Hardened superseding renewal — 2026-08-03

The preceding P03-US08 and Phase 04 statements preserve the prior exit
checkpoint. Current applicability is governed, only together with fresh
independent approval of the hardened implementation, by
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
which leave all earlier identities and results unchanged. Attempt 48 remains
failed at `ny-timetable` / `running_region_projection` p95 **0.050946750
seconds** against the unchanged **0.050000000-second** ceiling (**0.000946750
seconds / 1.8935%**, maximum **5%** candidate-specific). The companion remains
quarantined, canonical strict-final evidence remains absent, and Phase 03 is
not a strict current-artifact metrics pass.

Only default-off Phase 04 table changes admitted and structurally sealed by
the executable record—and Phase 04 exit within that unchanged scope—are exempt
from the former blanket required-code/Phase-04-exit trigger. A protected
running-region semantic/runtime/custody change or admitted-scope expansion
requires a new explicit decision and expires the renewal before the change;
production enablement remains prohibited and review is due no later than
**2026-09-02**. Default-off exact-predecessor rollback and every non-waived
RSS, paired/source/Uber latency, correctness, security, compatibility, custody,
resource/deadline, output, rollback, and hosted-use gate remain enforced. This
note neither changes a Phase 04 story status nor authorizes Phase 05.
