# Phase 03 Metrics

| Metric | Before | Target | After |
|---|---:|---:|---:|
| Exhibit 7 caption recall | 0/1 | 1/1 | 1/1 |
| Exhibit 8 caption separation | Fail | Pass | Pass — exact linked caption |
| Damaged internal fragments emitted as caption | 2 | 0 | 0; exact `er cas` / `C` subordinate children |
| Source note recall | 0/8 | 8/8 | 8/8 exact reviewed notes |
| Caption/source-note relationship F1 | Unmeasured | 1.0 on phase fixtures | 1.0 for P03-US01–US03 reviewed captions/notes |
| Relationship bbox violations | At least 1 | 0 | 0 for 8 reviewed captions and 14 US03 note/control records |
| Duplicate title rate | Benchmark risk/current merge | 0 | 0 for reviewed table and visual captions |
| Pairwise reading-order accuracy | Unmeasured | 100% on phase fixtures | P03-US04: 41/41 fixed real-corpus pairs |
| Reviewed redline run-state accuracy | 0/3 complete | 3/3 with bbox/rule/style provenance | P03-US05: 3/3 omissions; 6 groups, 7 group/rule edges, 9 run/rule links |
| False deletion/underline classification | Unmeasured | 0 on negative controls | 0; exact 2 blue runs / 4 underline links retained |
| Structured reviewed form/control relationships | 0 | 100% linked; 0 fabricated values | P03-US06: ACORD 6 groups / 42 labels / 24 fields / 24 controls / 216 relationships; component 3 groups / 16 pairs / 80 relationships |
| False form-to-table conversion | Confirmed on ACORD regions | 0 on form controls | 0 on reviewed controls and overlay; mixed coverage table retained |
| Reviewed list/clause parent and ordinal accuracy | Text present, hierarchy incomplete | 100%; 0 false-list controls | P03-US07: exact 3 groups / 19 nodes / 38 relationships; 0 false-list controls |
| Reviewed physical/printed page-pair accuracy | 0% structured on mismatched excerpts | 100% | P03-US08: 30/30 reviewed pages exact; 27 printed labels exact and 3 intentionally null |
| Running-region body/full duplication | Reviewed failures present | 0 | P03-US08: 47/47 reviewed regions exact; 0 duplicate canonical contributions |
| Material layout failures without targeted concern | Confirmed in benchmark | 0 on reviewed phase fixtures | 0 for P03-US01–US08 reviewed targets and controls |
| p95 layout-normalization overhead | Baseline | ≤ 5% | P03-US07 strict pass; P03-US08 accepted only for attempt 48's candidate-specific NY projection p95 of 50.946750 ms vs 50.000000 ms (+1.8935%) under the approved time-bounded exception; global ceilings unchanged |

Benchmark performance fixtures retain their M0 baselines: `uber-earnings`
29.15 s / 2,589.5 MiB, `manufacturing-report` 11.58 s / 1,825.8 MiB,
`clinical-study` 13.96 s / 1,561.9 MiB, and `purchase-agreement`
6.18 s / 1,401.0 MiB. Story reports must record before/after latency, peak RSS,
output size, and flag-off parity; a faster result cannot excuse a semantic
regression.

## P03-US01 retained checkpoint

- Reviewed external table captions: 3 expected / 3 actual / 3 exact
  page-text-bbox identities.
- Precision/recall: 1.0 / 1.0; unexpected captions and Markdown duplicates: 0.
- Caption bbox and relationship/owner-backlink coverage: 100%.
- Target table rows/cells: identical flag on/off.
- Finance control: exact semantic JSON and Markdown parity.
- Isolated layout stage: p50 1.302 ms, p95 1.677 ms, max 1.984 ms,
  peak traced allocation 88,477 bytes.
- JSON size delta: +3,997 bytes catastrophe, +23,014 bytes clinical, 0 bytes
  finance.
- Artifact:
  `evidence/P03-US01-table-caption-metrics.json`, 15,548 bytes, SHA-256
  `98ccfb93b352dee0d01b5d614b1b298816ff80d817f1363fe27f682906f2857a`.

## P03-US02 retained checkpoint

- Reviewed visual captions: 5 expected / 5 actual / 5 exact
  page-text-bbox-side identities; precision/recall 1.0 / 1.0.
- Unexpected captions, Markdown duplicates, unresolved endpoints, child
  page-item leaks, canonical-primary leaks, and caption fragments: 0.
- Relationship/backlink, bbox, side-order, and owner-clean coverage: 100%.
- Catastrophe Exhibit 8 children: exact `er cas` / `C` source values and bboxes.
- Uber photograph: exact 15 unique contained values, frozen digest
  `459ab313b2309c951fb41189a7cec8d5e63130147628cdb45fcc27b86f2eced2`,
  no caption or primary OCR leak.
- Component caption: preserved once without invented ownership; finance:
  exact semantic JSON and Markdown parity.
- Isolated layout stage: p50 4.691 ms, p95 4.896 ms, max 5.764 ms,
  peak traced allocation 302,576 bytes.
- Artifact:
  `evidence/P03-US02-visual-relationship-metrics.json`, 71,287 bytes,
  SHA-256
  `8fa4704412f75138f885b8b8a6c7b62053f2232f9ce1070f509df5ded12462d3`.

## P03-US03 retained checkpoint

- Reviewed notes: 8 expected / 8 matched — one Aon source note, three
  Clinical Table 1 footnotes, and four Clinical Table 2 footnotes.
- Exact emitted notes/related controls: 14/14 — catastrophe 1, clinical 10,
  health 3, finance 0.
- Grounded link targets: 5/5 — clinical `.t001`, `.g001`, `.t002` and both
  health StatLinks.
- False associations, missing controls, unexpected records, relationship,
  backlink, order, canonical, and bbox violations: 0.
- Finance control and all flag-off projections: exact predecessor parity.
- Paired clipped inclusive p95 overhead: catastrophe 205.315 ms
  (2.4155%, 425 ms ceiling); clinical 407.439 ms
  (2.9186%, 698 ms ceiling).
- Maximum enabled peak RSS: 1,438.000 MiB catastrophe and 1,718.234 MiB
  clinical, or 100.7356% and 110.0092% of their retained Phase 02 baselines.
- Representative JSON size deltas: +1,436 bytes catastrophe, -6,755 clinical,
  +1,206 health, and 0 finance.
- Isolated layout stage: p50 12.270 ms, p95 13.424 ms, max 13.694 ms,
  peak traced allocation 458,305 bytes.
- Artifact:
  `evidence/P03-US03-source-note-metrics.json`, 62,312 bytes, raw SHA-256
  `c9f0cbbc0071bdf47ad19b00c6ed2996fb9bb80b1bf785bf9ae3e3c128a8ef7f`,
  semantic SHA-256
  `6f52064c2b7edce268edf2ba5443274019c25ab89a277283fd0fa7ffd1e2987d`.

## P03-US04 retained checkpoint

- Fixed reviewed order: **41 expected / 41 matched** across ten page slices
  in nine real corpus cases, including one exact nested pair.
- Public IDs unique, ranks contiguous, canonical/public order aligned, JSON
  round trips exact, and Markdown/canonical parity: **Pass**.
- Keyed mutation outside the exact clean-energy nested reorder and clinical
  terminal off-bbox suppression: **0**.
- Finance semantic JSON/Markdown flag parity and exact flag-off rollback:
  **Pass**.
- Paired clipped inclusive p95 overhead: manufacturing **256.858 ms**
  (**2.2181%**, 579 ms ceiling); Uber **140.290 ms**
  (**0.4813%**, 1,457.5 ms ceiling).
- Maximum enabled peak RSS: **1,936.719 MiB** manufacturing and
  **2,565.391 MiB** Uber.
- Isolated layout stage: p50 **26.970 ms**, p95 **31.095 ms**, max
  **40.115 ms**, peak traced allocation **875,312 bytes**.
- Maximum 512-anchor boundary: **44.638 ms**, exact order, contiguous ranks,
  250 ms ceiling.
- Artifact:
  `evidence/P03-US04-reading-order-metrics.json`, 373,160 bytes, raw SHA-256
  `826af5de42950c11e4fa2bcbf8a24f5adc2ad2c62d7a09cb760c4e08bc591154`,
  semantic SHA-256
  `46cef72e08707cc57fd54834c7ff4369a59558b4e2de1a47155da23b66803ab1`.

## P03-US05 retained checkpoint

- Purchase: **28** sparse runs and **13** rules; **3/3** omission repairs;
  **6/6** deleted groups; **7/7** group/rule edges; **9/9** deleted run/rule
  links; **2/2** blue runs and **4/4** underline links.
- False deletion and source-proven PDF insertion/replacement: **0 / 0**.
- Postal italic targets: exact table cells **20, 21, 66, 67**. Finance:
  **26** bold runs, zero deletion.
- Source-visible text, redline Markdown, active text, target slices/digests,
  provenance, deterministic serialization, purchase source composition
  **7/7**, and enabled public/canonical P03-US04 order **41/41**: **Pass**.
- Isolated extraction: p50 **107.093 ms**, p95 **118.615 ms**, max
  **134.893 ms**, peak traced allocation **9,753,721 bytes**.
- Isolated association/projection: p50 **9.235 ms**, p95 **9.884 ms**, max
  **10.996 ms**, peak traced allocation **1,222,889 bytes**.
- Paired purchase clipped inclusive p95 overhead: **161.812 ms**
  (**2.24727%**), below the 5% **360.019 ms** and absolute **309 ms**
  ceilings.
- Exact/max+1 64/65-link cases: **6.173/5.664 ms**; overflow fails closed at
  page scope. Every frozen resource class has deterministic boundary coverage.
- Purchase flag-off/on median wall time is **6.204/6.325 s** and maximum peak
  RSS is **1,478,098,944/1,489,289,216 bytes**. Semantic JSON is
  **49,579/82,421 bytes**, raw JSON **49,598/82,440 bytes**, and Markdown
  **3,370/3,426 bytes**; flag-off semantics remain exactly predecessor-clean.
- Uber flag-off/on maximum peak RSS is
  **3,444,916,224/3,444,490,240 bytes**. Semantic JSON is
  **186,160/186,979 bytes**, raw JSON **186,180/186,999 bytes**, and Markdown
  remains **1,152/1,152 bytes**.
- Artifact:
  `evidence/P03-US05-text-run-metrics.json`, 82,934 bytes, raw SHA-256
  `0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659`,
  semantic SHA-256
  `e432ce80d6351d1d161010aec7f8b32a1622a54cf1b14e14bfccb3411c79c3c3`.

## P03-US06 retained checkpoint

- ACORD: **6** form groups, **42** labels, **24** empty fields/value regions,
  **24** controls, and **216** relationships; no checked state or value is
  fabricated and the mixed coverage table remains available.
- Component: **3** replace-mode key-value groups, **16** ordered pairs, and
  **80** relationships with exact contributor custody and canonical parity.
- Isolated extraction p50/p95: ACORD **75.456/76.933 ms**, component
  **178.592/181.412 ms**; peak traced allocations **16,851,449** and
  **11,262,672 bytes**.
- Isolated projection p50/p95/max: ACORD **42.478/44.532/46.016 ms** and
  component **27.234/28.097/28.155 ms**; peak traced allocations **6,458,160**
  and **5,392,187 bytes**.
- ACORD uses **59,849/65,536** page comparisons; component page ledgers are
  **10/5,327/2,328**. Exact/max+1 256/257-group projection is
  **96.587/5.139 ms**, with transactional fail-closed restoration at max+1.
- Five alternating fresh-process pairs pass: ACORD clipped p95
  **300.827 ms ≤ 453 ms** and component **516.890 ms ≤ 528 ms**. Maximum
  paired RSS deltas are **42,844,160** and **11,255,808 bytes**.
- Frontend lint/typecheck/build, **84/84** unit tests, and **1/1** bundle test
  pass. Focused backend, performance, cap/security, compilation, fixture, and
  reader gates pass; independent algorithm, projection, and metrics/custody
  reviews found no blocker.
- Passing artifact:
  `evidence/P03-US06-form-metrics.json`, 82,347 bytes, raw SHA-256
  `7e7da0d0d2a2f528b247e560399940e7c091ad765903ef5177381d140a01c290`,
  semantic SHA-256
  `7cfff9b19f129ab29f2a14317a479c50ed38397921ef9111b0a4b57f7d557fc7`.
- The unedited first candidate is retained as
  `evidence/P03-US06-form-metrics-attempt-01-failed.json`, 82,341 bytes, raw
  SHA-256
  `7d51d18f8420951a0adf0121107b6b2535b83c128a39181ba1616ae9423c0ec1`,
  semantic SHA-256
  `3e829005470fe78e1486a6a693ae38ca6086745e4495672a1f0f31f9d579fcba`;
  it failed only the ACORD paired gate before one full unchanged rerun passed.

## P03-US07 retained checkpoint

- Component: **2** groups, **16** nodes, and **32** relationships—11 bullet
  roots, five circle children, five parent edges, 11 next edges, and 16
  contains edges.
- Settlement: **1** three-node lower-alpha group and **6** relationships with
  literal `a.`/`b.`/`c.` markers and one exact table-to-`b.` continuation.
- Combined reviewed graph: **3 groups / 19 nodes / 38 relationships**—19
  `contains`, 13 `outline_next`, five `outline_parent_of`, and one
  `outline_continuation_of`—with exact marker, value, bbox, ordinal, parent,
  backlink, and canonical custody.
- Component retains exact P03-US06 coexistence at **3 groups / 16 pairs / 80
  relationships**; accepted P03-US04 order remains **41/41**. Finance and the
  reviewed negative controls produce zero false outlines.
- Isolated extraction p50/p95/max: component
  **145.649/171.112/195.901 ms**, settlement **55.505/56.917/59.607 ms**;
  peak traced allocations **9,341,342/5,879,692 bytes**, reports
  **3,775/1,133 bytes**.
- Isolated projection p50/p95/max: component
  **31.627/32.115/33.444 ms**, settlement **5.343/5.529/5.535 ms**; peak
  traced allocations **4,891,543/793,721 bytes**, projected IR
  **598,088/77,395 bytes**, and **28/4** comparisons.
- Five alternating fresh-process pairs pass: component clipped p50/p95
  overhead **79.820/481.838 ms ≤ 528 ms** and settlement
  **86.382/138.590 ms ≤ 299.231 ms**. Maximum RSS deltas are
  **17,498,112/10,895,360 bytes**.
- All **22** resource and **3** deadline exact/max+1 gates pass; maximum
  resource-boundary duration is **15.431375 ms**. Hosted requests/tokens/cost
  are **0/0/$0**.
- Dedicated backend paths total **115 passing tests**: 21 story/readiness, 23
  contract, 19 real/control, 47 performance/resource, and five retained
  custody tests. Frontend lint/typecheck/build, **90/90** unit tests, and one
  bundle test pass; independent production/security and metrics/custody review
  found no blocker.
- Live local-parser plus production-frontend-renderer checks pass: component
  **2/16/32** renders two `<ul>` roots plus a nested `<ul>` at pages/labels
  **3/[1,2,3]**; settlement **1/3/6** renders one `<ol>` plus its owned parsed
  table at **1/[1]**. Canonical Markdown/JSON are exact and no raw `<script>`
  appears. Manual browser click-through is unclaimed because the browser was
  unavailable; a vinext dev-proxy timeout with a healthy backend is retained
  as a local tooling limitation while automated proxy contracts remain green.
- Passing artifact:
  `evidence/P03-US07-outline-metrics.json`, **136,091 bytes**, raw SHA-256
  `cbfe68a90a225adc9896435f7197389998df8ddddfca2ae94f8a917807490765`,
  semantic SHA-256
  `22c208d8f625cb917e3e27097c6c60fc5fb904282ac7ae3e530dbffdf62d2639`.
- Two unsealed candidates were rejected without waiver for component paired
  p95 results of **639.774 ms** and **1,013.963 ms**. Their identities and
  results are recorded in the completion and verification reports; an
  unchanged uncontended campaign then passed every gate.

## P03-US08 renewed exception-bound checkpoint

- Quality is exact on the reviewed corpus: **30/30** physical page identities,
  **27** exact printed labels plus **3** explicit null labels, **47/47** running
  regions, and **0** duplicate canonical contributions.
- Immutable attempt 48 remains a failed candidate. Its Uber
  and New York source-extraction p95 values are **48.295959/215.154375 ms**;
  Uber projection is **6.768750 ms**. New York projection is
  **50.946750 ms** against the unchanged **50.000000 ms** strict ceiling—an
  exact **0.946750 ms / 1.8935%** candidate-specific overrun accepted only by
  active renewal
  [P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-FRONTEND-BBOX](decisions/P03-US08-frontend-bbox-latency-exception-renewal.md).
- Attempt 48 fail-fast leaves paired and paired-output measurements empty; it
  is not used for memory or whole-parser acceptance. The quarantined
  post-seal-invalid companion completed **20/20** workers and passed every
  strict gate: Uber paired p95/RSS **267.703208 ms / 12,877,824 bytes** and New
  York **1,447.505041 ms / 47,316,992 bytes**, both RSS results below
  **67,108,864 bytes**. Memory is not waived.
- Current code has renewed 86-path manifest
  `b5bfab2739f231a57abddf787a6c566c5fddec5b2128bd4892f3682622a06fcc`.
  Exactly the frontend validator and its frontend contract test differ from
  attempt 48; the other **84/86** paths match. In particular,
  `measured_backend_parser_runtime_paths_match_original` is true: all **29**
  `app/**` backend paths are identical, with manifest
  `3f60c9b297760cf5fc0b1e89cd0ef02666f35c77ccc474202b80e26915703bb7`.
  Current code differs from the companion at exactly four paths—the two
  authorized frontend paths plus the companion's historical retained-artifact
  validator and contract test—so **82/86** match. The companion remains
  quarantined and is not a canonical final artifact.
- The active sealed renewal is
  `evidence/P03-US08-frontend-bbox-latency-waiver-renewal.json`. It retains the
  original immutable decision and waiver identities and binds all **55** failed
  attempts (history manifest
  `bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`),
  both candidates, the exact frontend delta, current manifest, zero hosted use,
  default-off rollback, and expiry. The original waiver remains unchanged at
  `evidence/P03-US08-provisional-latency-waiver.json`, **4,873 bytes**, raw
  SHA-256
  `1fe75bc3d749730938653030052d463340eb2e856b810e0586e9afb12e9a72c8`,
  semantic SHA-256
  `0d3cd13942dd465c537dd7075baf0d2e8b30bc5dd891af55622c07f493610554`.
- The strict canonical final artifact is absent. P03-US08 is therefore Done
  only with the approved active time-bounded metrics exception renewal, which
  expires no later than **2026-09-02**, or earlier on any further required-code
  change, production enablement, or Phase 04 exit, and reverts the story to In
  Progress if not replaced or explicitly renewed.

### Hardened superseding renewal — 2026-08-03

The requester-authorized chain now ends at
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
with executable record
[`P03-US08-phase04-tables-latency-waiver-hardened-renewal.json`](evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
with final approval bound in
[the independent approval record](evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
The earlier frontend renewal, 86-path baseline manifest, and every historical
identity/result remain unchanged. Attempt 48 remains failed for
`ny-timetable` / `running_region_projection` p95 at **0.050946750 seconds**
against the unchanged **0.050000000-second** strict ceiling (**0.000946750
seconds / 1.8935%** over, within the unchanged maximum **5%**
candidate-specific bound). Its complete companion remains quarantined,
strict-final evidence remains absent, and these metrics are not a strict
current-artifact pass.

The superseding record admits only named, default-off Phase 04 table paths and
protected functions. Changes structurally sealed inside that scope, and Phase
04 exit within it, no longer trigger the former blanket required-code expiry.
Any protected running-region semantic/runtime/custody change or admitted-scope
expansion requires a new explicit decision and expires this renewal before the
change; production enablement remains prohibited and review is due no later
than **2026-09-02**. Exact-predecessor default-off rollback and all non-waived
RSS, paired/source/Uber latency, correctness, security, compatibility, custody,
resource/deadline, output, rollback, and hosted-use gates remain in force.
