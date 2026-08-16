# P03-US07 Completion Report

Status: Done  
Story: Preserve list and legal-clause hierarchy  
Points: 5
Estimate history: re-estimated 3→5 at readiness  
Started: 2026-08-01

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — native-PDF bullet/decimal/lower-alpha hierarchy and one bounded same-page table interruption; no upper/Roman/custom marker, caption/callout continuation, legal inference, text repair, inline enumeration splitting, form ownership, table reconstruction, cross-page edge, or M5 adapter |
| Points at most 5 | Pass — 5; re-estimated after the independent architecture/fixture audit exposed cross-layer canonical custody, terminal replay, and strict frontend validation work |
| Dependencies Done | Pass — P01-US02 and P03-US04 are Done; operational P03-US06 predecessor is also Done |
| Acceptance measurable | Pass — component exact 2 groups/16 nodes/32 relationships; settlement exact 1 group/3 nodes/6 relationships; zero false-list controls and exact marker/value custody |
| Dedicated tests identified | Pass — story, contract, real-corpus, adversarial/resource, performance, metrics/custody, frontend, and regression paths |
| Fixtures available and authorized | Pass — immutable component/settlement sources, exact machine oracle, executable closed-schema/canonical contract, and 11 deterministic synthetics covering 37 capability labels; nine PDFs pass both local readers |
| API/frontend impact documented | Pass — strict additive anchor sidecar with byte-identical legacy nested entries, typed IR descriptors/relationships, exact marker ownership, complete canonical closure/hashes, nested React DOM, and authoritative fallback |
| Feature flag identified | Pass — `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED` / `parser.layout.outline_structure.enabled`, default false with zero flag-off US07 work |
| Rollback defined | Pass — in-transaction canonical dry run, page restoration for page-local failure, complete-stage restoration for source/document/final failure, reverse-strip/forward-replay terminal path, and exact configured predecessor with non-US07 flags unchanged |
| Quality/performance specified | Pass — 22 exact/max+1 measurement primitives and three deadline witnesses are ready; production-shaped validator bindings, isolated latency/allocation/report gates, five paired fresh-process samples, RSS normalization, final custody, and zero hosted use are mandatory before Done |

Definition-of-Ready result: **10/10 Pass**, independently confirmed on
2026-08-01 with 103 passing checks. At that readiness transition P03-US07 was
the sole In Progress story.

The accepted contract is
[P03-outline-structure-policy.md](../decisions/P03-outline-structure-policy.md).

## Corrected source truth

The settlement markers are literal `a.`, `b.`, and `c.`. Their exact top-left
point bboxes are `[180,169.644,8.28,12]`, `[180,319.644,9,12]`, and
`[180,598.524,8.28,12]`. The hash-pinned Phase 00 case review and retained
comparison remain byte-identical; their historical parenthesized shorthand is
superseded only for US07 by the
[source-truth addendum](../evidence/P03-US07-settlement-marker-addendum.md),
this report, and the machine oracle.

Component page 1 has two list groups, 16 nodes, 11 `•` roots, five `◦`
children, and five direct parent edges. Settlement has one three-node ordered
group plus one existing table continuation owned by `b.`. Across the target
cases the exact total is three groups, 19 nodes, five parent edges, 13 sibling
next edges, one continuation edge, 19 contains edges, and 38 relationships.

## Readiness evidence

- source identities:
  - component: 329,199 bytes,
    `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`;
  - settlement: 164,483 bytes,
    `adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc`;
- oracle file SHA-256:
  `65d6a1a95e5bb76af4220d87a287b30600171b9cc443c4798a7987a544d6a3ad`;
- oracle semantic SHA-256:
  `e3bddd0ce86ccbf1089b2e667b4b42922b41daaa20c5051634d21646d4f58bc5`;
- executable contract file SHA-256:
  `980e4622105cbe230c23889545cd083f5b88f0919b82b700169196787e655746`;
- synthetic file SHA-256:
  `42200360e918050a4b298bce5736481fdd7495460fca93eed243c103004ac83d`;
- synthetic registry semantic SHA-256:
  `56d1ae95917de879b992030c7d8dddc4e03fada4e1b715974bdd4bde6a6e27c3`;
- readiness test file SHA-256:
  `639b54635037ee69b36114323190c8a9a1e76581ea3129e1a2970c7bacbab9e9`;
- lightweight readiness gate: **21 passed**, with one existing Starlette/httpx
  deprecation warning;
- Ruff 0.15.22 and formatting: **Pass**; and
- pdfplumber/pypdfium2 open/render all nine synthetic PDFs: **Pass**.

## Implementation and acceptance

The default-off local stage now extracts a bounded native marker report,
projects strict typed outline groups/items and exact relationship graphs, and
derives canonical Markdown/text from the validated graph. The legacy page-item
stream remains authoritative outside the additive anchor sidecar. Flag off
performs zero US07 import, extraction, or projection work and returns the exact
configured predecessor with every non-US07 flag unchanged.

The frozen real-corpus results are exact:

- component datasheet: **2 groups / 16 nodes / 32 relationships**, with 11
  bullet roots, five circle children, five parent edges, 11 next edges, and 16
  contains edges;
- settlement agreement: **1 group / 3 nodes / 6 relationships**, with literal
  `a.`, `b.`, and `c.`, two next edges, three contains edges, and one exact
  table-to-`b.` continuation; and
- combined: **3 groups / 19 nodes / 38 relationships**, comprising 19
  `contains`, 13 `outline_next`, five `outline_parent_of`, and one
  `outline_continuation_of` relationship.

All markers, item/marker bboxes, raw values, ordinals, parents, evidence paths,
relationship backlinks, canonical blocks, and predecessor bindings match the
immutable oracle. Component retains the exact P03-US06 form predecessor—three
groups, 16 key-value pairs, and 80 relationships—and the accepted P03-US04
order remains 41/41. Finance produces zero outline nodes. The nine synthetic
PDFs and all 11 registry entries preserve the approved positive/non-target
partition, including fail-closed parenthesized-alpha and marker-injection
projection controls.

Strict public/IR models reject extra fields, malformed graphs, mismatched
page/anchor/group evidence, unsafe continuation Markdown, and incomplete
sidecars. Page-local failures restore the page; source/document or terminal
identity failures restore the complete US07 stage. Repeated projection and
terminal replay are idempotent. The frontend validates the same closed graph,
renders semantic nested React lists, preserves exact continuation ownership,
and falls back to authoritative canonical content without raw HTML or client
inference.

## Verification and independent review

- story/readiness gate: **21 passed**;
- final strict contract gate: **23 passed**;
- real-corpus and control regression gate: **19 passed**;
- isolated performance/resource gate: **47 passed**, with five documented
  upstream warnings;
- final retained-artifact gate: **5 passed**, with one documented upstream
  warning;
- combined contract/real-corpus invocation: **42 passed**, with 14 documented
  upstream warnings;
- frontend Node 22.18 lint, typecheck, production build, **90/90 unit tests**,
  and **1/1 bundle test**: **Pass**; and
- Python compilation, Ruff 0.15.22 on the four final evidence/test paths,
  deterministic fixture self-checks, and pdfplumber/pypdfium2 reader checks:
  **Pass**.

The five dedicated backend files collect **115 tests** in total: 21 story,
23 contract, 19 real/control, 47 performance/resource, and five retained
custody tests. Warning counts above belong to their named invocations and are
not added across overlapping reruns.

Independent production/security review approved the final strict schemas,
source custody, graph coexistence, deadline/resource accounting, rollback,
terminal re-entry, and canonical safety without a blocker. Its adversarial
probes rejected nine encoded or obfuscated unsafe-link forms, proved zero
outline-module loading with the flag off, and proved atomic restoration under
forced replay mismatch. Independent final metrics/custody review approved the
accepted artifact, exact inputs, predecessor, formulas, bounds, deterministic
outputs, and zero hosted use.

Automated visible-path rendering, fallback, normalization, source/page,
copy/download, build, bundle, and proxy-contract coverage passes. A live local
parser plus production frontend renderer check passes on the real PDFs:

- component projects **2/16/32**, renders two semantic `<ul>` roots with a
  nested `<ul>`, retains exact canonical Markdown and JSON sidecars, contains
  no raw `<script>`, and preserves physical pages/labels **3/[1,2,3]**; and
- settlement projects **1/3/6**, renders one semantic `<ol>` root with its
  owned `<table class="parsed-table">`, retains exact canonical Markdown and
  JSON sidecars, contains no raw `<script>`, and preserves physical
  pages/labels **1/[1]**.

The in-app/Chrome browser surface was unavailable, so manual click-through is
not claimed. The vinext development proxy stalled while the backend remained
healthy; the live renderer check therefore used the backend directly. The
automated proxy contract remains green, and this timeout is an environment and
tooling limitation rather than a production parser correctness failure.

## Performance, resources, and retained evidence

The final controlled campaign records:

- component extraction p50/p95/max **145.649/171.112/195.901 ms**, peak traced
  allocation **9,341,342 bytes**, report **3,775 bytes**;
- settlement extraction p50/p95/max **55.505/56.917/59.607 ms**, peak traced
  allocation **5,879,692 bytes**, report **1,133 bytes**;
- component projection p50/p95/max **31.627/32.115/33.444 ms**, peak traced
  allocation **4,891,543 bytes**, projected IR **598,088 bytes**, and **28**
  comparisons;
- settlement projection p50/p95/max **5.343/5.529/5.535 ms**, peak traced
  allocation **793,721 bytes**, projected IR **77,395 bytes**, and **4**
  comparisons;
- five alternating fresh-process pairs: component clipped p50/p95 overhead
  **79.820/481.838 ms**, below the **528 ms** effective ceiling, and settlement
  **86.382/138.590 ms**, below the **299.231 ms** effective ceiling; and
- maximum paired RSS deltas **17,498,112** and **10,895,360 bytes**, both below
  64 MiB. Hosted requests/tokens/cost are **0/0/$0**.

All **22** resource exact/max+1 boundaries and all **3** deadline boundaries
pass; the maximum measured resource-boundary duration is **15.431375 ms**
against the 250 ms ceiling. Representative semantic JSON off/on sizes are
**319,964/369,006 bytes** component and **48,079/66,198 bytes** settlement;
Markdown is **3,725/5,425** and **3,144/3,565 bytes** respectively.

The accepted retained artifact is
[P03-US07-outline-metrics.json](../evidence/P03-US07-outline-metrics.json),
**136,091 bytes**, raw SHA-256
`cbfe68a90a225adc9896435f7197389998df8ddddfca2ae94f8a917807490765`,
and semantic SHA-256
`22c208d8f625cb917e3e27097c6c60fc5fb904282ac7ae3e530dbffdf62d2639`.
It binds 31 final code/config/frontend/test/policy paths, both immutable target
sources, the Finance control, the sealed US06 predecessor, the M0 reference,
oracle/contract/addendum identities, 11 synthetics/37 capabilities, limits,
rollback, outputs, dependencies/tools, and zero hosted use.

Two complete candidates were rejected without waiver and were not sealed or
retained as final evidence:

- candidate 1: **136,098 bytes**, raw SHA-256
  `80be04f205c65da7ac1f4bff891326f3a9aba24d89c0ef275b0a0f4d0497d333`,
  semantic SHA-256
  `d407ed310028c052d58cc3536b22386dc0e8dd5458af4269abf39f1eb49ec3dd`,
  component paired p50/p95 overhead **89.043/639.774 ms**; and
- candidate 2: **136,059 bytes**, raw SHA-256
  `4ff77743753ef73c1c06e783afce0ebba514e5db812a917d143aa8a73a2d1ed2`,
  semantic SHA-256
  `3bfb7dc03e1fd1cc6976e16d4b671416b1ab81983c5d228fe958a211dba3a03b`,
  component paired p50/p95 overhead **342.796/1,013.963 ms**.

Each failed only the component whole-parser paired gate because of an isolated
predecessor/scheduling outlier; neither result was waived or presented as
passing evidence. One complete unchanged uncontended campaign then passed all
gates and produced the accepted artifact above.

## Rollback

Set `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED=false`. The outline module is not
loaded, source extraction and projection are skipped, no US07 sidecar or
concern is emitted, and the exact configured predecessor is restored with all
non-US07 flags unchanged.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — exact component 2/16/32 and settlement 1/3/6 output |
| Dedicated and adversarial tests pass | Pass — 115 story, contract, real/control, resource, performance, and retained tests |
| Impacted regressions and real benchmarks pass | Pass — both targets exact, Finance and synthetics controlled, P03-US04 41/41 retained |
| API/schema and canonical compatibility pass | Pass — additive public `1.0`, strict typed IR, exact canonical closure, predecessor parity |
| Frontend visible-path compatibility passes | Pass — bounded validator, nested DOM, fallback, normalization, copy/download, build, and bundle |
| Security/resource bounds pass | Pass — bytes, counts, comparisons, deadlines, unsafe Markdown, strict graphs, and atomic rollback |
| Final-code metrics and exact input custody retained | Pass — 136,091-byte artifact with raw/semantic hashes and 31 bound paths |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — production/security and final metrics/custody approval |
| No concurrent next story | Pass — P03-US08 remained Proposed through this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US07 is Done. P03-US08 remains
Proposed. No Phase 04 work has started.
