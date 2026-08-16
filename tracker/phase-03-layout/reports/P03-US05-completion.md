# P03-US05 Completion Report

Status: Done  
Story: Preserve source-visible redline and text-run semantics  
Points: 5  
Started: 2026-07-31  
Completed: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — sparse native text/style/rule evidence and source/redline/active projections; no legal-intent inference, OCR redline detection, change acceptance, Office adapter, or Phase 04 work |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US02 and P03-US04 |
| Acceptance measurable | Pass — 3/3 omission repairs, 6/6 deleted groups, 7/7 group/rule edges, 9/9 run/rule links, 2/2 blue runs, 4/4 blue underline links, zero false deletion, exact per-target offsets/digests, and retained 41/41 order |
| Dedicated tests identified | Pass — story, adversarial, contract, real-corpus, frontend, performance, custody, and cumulative regression paths |
| Fixtures available and authorized | Pass — immutable purchase/postal/finance/Uber PDFs, mandatory P00-US09 quartet, three same-page underline controls, and eight named local synthetics |
| API/frontend impact documented | Pass — self-contained additive item JSON, typed internal records, unchanged strict canonical-v1 shape, redline Markdown with preserved type envelopes, explicit derived active text, and safe React run rendering |
| Feature flag identified | Pass — `PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED`, default off and gated by shared normalization plus P03-US04 relationship order |
| Rollback defined | Pass — disable one flag for exact P03-US04 predecessor, including zero US05 extractor calls, fields, records, or concerns |
| Quality/performance specified | Pass — fixed source denominator, bounded indexed line/rule/target association, five fresh-process pairs, 0.309 s/5% paired ceiling, isolated p95/allocation gates, 250 ms maximum boundary, 8 MiB report cap, and zero hosted use |

Definition-of-Ready result: **10/10 Pass**. Independent source-truth,
contract/readiness, and adversarial/performance/custody reviews each returned
10/10 with no remaining material blocker. At its implementation transition,
P03-US05 was the sole story In Progress and P03-US06–P03-US08 remained
Proposed. The accepted contract is
[P03-text-run-semantics-policy.md](../decisions/P03-text-run-semantics-policy.md).

## Accepted source truth

The primary purchase page has 3,338 glyphs and 13 filled horizontal-rule
rectangles. The fixed target is six logical deleted groups, seven unique
change-group/rule edges, and nine style-run/rule links. Blue evidence is two
runs and four underline links; `EXECUTION VERSION` remains active and exactly
seven underscores remain a placeholder with unknown change state. Ordinary
black `Background` and inline `Exhibit A` underlines are retained without
false deletion.

The policy freezes deterministic baseline clustering, rule-driven glyph
refinement, boundary-whitespace handling, same-color geometry thresholds,
group overhang, target-path resolution, and half-open Unicode code-point
offsets. Postal's four italic spans bind to table cell indexes 20, 21, 66, and
67. Source-visible text is authoritative; active text removes only proven
deletions and discloses every omitted run ID.

## Implementation

The default-off US05 stage now extracts bounded, source-grounded font/style
runs and horizontal vector rules, then transactionally associates that
evidence with exact scalar, table-cell, and nested-item target slices after the
P03-US04 order projection. The implementation:

- retains complete source-visible text while storing sparse half-open
  Unicode-code-point run offsets, target digests, source character custody,
  font/style/color evidence, page-space bboxes, rule links, and derivation;
- recognizes deletion only from accepted same-color midline geometry, retains
  underline independently, and never infers PDF insertion/replacement;
- groups only source-character-adjacent deleted runs, exposes exact redline
  Markdown, and derives active text only by listing and removing proven
  deletion IDs;
- resolves only allowlisted target paths, with strict quote matching, bounded
  NFKC alignment, exact scalar/child alias handling, deterministic path order,
  and ambiguity refusal;
- escapes Markdown injection and setext-heading forms, validates frontend
  overlays against exact backend redline recomputation, and renders safe React
  nodes without making the frontend a new source of truth;
- applies page-transactional extraction/projection rollback, document-global
  custody limits, deterministic bounded concerns, report-size custody, and
  deadline/comparison/association caps; and
- omits empty additive US05 collections from flag-off serialized IR while
  retaining typed empty defaults internally, restoring every sealed Phase 01
  canonical IR digest exactly.

The public ParseResult and strict canonical-presentation schema remain `1.0`.
Enabled item JSON is additive and self-contained; canonical text and item
values remain complete source-visible text.

## Verification

The fixed purchase target passes all reviewed denominators: 28 sparse runs and
13 retained rules; 3/3 expert omissions repaired; 6/6 deleted logical groups;
7/7 group/rule edges; 9/9 deleted run/rule links; and 2/2 blue runs with 4/4
underline links. `EXECUTION VERSION`, `Background`, and `Exhibit A` have zero
false deletion. Postal retains the four exact italic cell targets at indexes
20, 21, 66, and 67; finance retains 26 bold runs with zero deletion. No
source-proven PDF insertion/replacement is emitted, and P03-US04 remains
41/41.

Final gates:

- integrated contract/story/adversarial/hardening/real-corpus: **147 passed**,
  including live enabled-US05 purchase 7/7 and full P03-US04 41/41 order;
- cumulative Phase 01 plus P03-US01–US04 compatibility: **566 passed**;
- live performance gates: **10 passed**;
- retained artifact custody: **5 passed**;
- frontend Node 22.18 lint, TypeScript, production build, **76/76 unit**, and
  **1/1 bundle**: **Pass**;
- targeted Python compilation and Ruff: **Pass**; and
- independent production/security and final custody review: **Pass**, with no
  remaining material blocker.

The isolated source extractor recorded p50 **107.093 ms**, p95 **118.615 ms**,
max **134.893 ms**, and peak traced allocation **9,753,721 bytes**. Projection
recorded p50 **9.235 ms**, p95 **9.884 ms**, max **10.996 ms**, and peak
allocation **1,222,889 bytes**. The exact 64-link boundary completed in
**6.173 ms**; 65 links failed closed at page scope in **5.664 ms**.

Five alternating fresh-process purchase pairs recorded clipped inclusive p95
overhead of **0.161812 s** (**2.24727%** of the current 7.200387 s paired
predecessor), below both the 5% ceiling (**0.360019 s**) and absolute
**0.309 s** ceiling.

The purchase flag-off/on medians were **6.203529/6.324927 s**; maxima were
**7.428094/6.626299 s**, and maximum worker RSS was
**1,478,098,944/1,489,289,216 bytes**. Semantic JSON grew
**49,579 → 82,421 bytes** (+32,842), raw JSON
**49,598 → 82,440 bytes** (+32,842), and Markdown
**3,370 → 3,426 bytes** (+56). Every flag-off sample made zero extractor
calls, omitted every US05 projection, and retained deterministic exact
predecessor semantic bytes.

Uber semantic/raw JSON grew **186,160/186,180 → 186,979/186,999 bytes**
(+819 each); Markdown remained **1,152 bytes**. Maximum off/on worker RSS was
**3,444,916,224/3,444,490,240 bytes**. Uber remains the Phase 03 memory guard,
not a semantic exception. Hosted requests/tokens/cost are **0/0/$0**.

The retained artifact is
[P03-US05-text-run-metrics.json](../evidence/P03-US05-text-run-metrics.json),
82,934 bytes, with raw SHA-256
`0ba7e13f1fce12dc0f6c2d0a4e65aab850d2012025ca9996b9645d371aff7659`
and semantic SHA-256
`e432ce80d6351d1d161010aec7f8b32a1622a54cf1b14e14bfccb3411c79c3c3`.
It binds 31 final code/config/frontend/test/policy paths, four direct US05
source identities, nine reviewed-order source identities, eight named
synthetics, local dependencies/tools, rollback, and zero hosted use. Detailed
evidence is in
[P03-US05-verification.md](../evidence/P03-US05-verification.md).

The reported Starlette/httpx and Docling notices are existing upstream
deprecation warnings. Automated frontend rendering, normalization,
copy/download, build, and bundle gates pass; manual browser click-through is
not claimed.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — all seven acceptance criteria and fixed corpus denominators |
| Dedicated and adversarial tests pass | Pass — quote, Unicode, alias, Markdown, transaction, idempotence, and every frozen exact/max+1 resource class |
| Impacted regressions and real benchmarks pass | Pass — 147 integrated plus 566 cumulative |
| API/schema and canonical compatibility pass | Pass — public/canonical `1.0`; exact flag-off predecessor IR restored |
| Frontend visible-path compatibility passes | Pass — automated safe overlay, normalization, copy/download, build, and bundle |
| Security/resource bounds pass | Pass — page/document bytes, slots, text, runs, rules, comparisons, associations, deadlines, diagnostics, and rollback |
| Final-code metrics and exact input custody retained | Pass — raw and semantic digests pinned and 5/5 custody tests |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — production/security and final custody approved |
| No concurrent next story | Pass — P03-US06 remained Proposed through this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US05 is Done. P03-US06 is the
next dependency-ready Phase 03 story and remains Proposed until its separate
readiness gate passes. No Phase 04 work has started.
