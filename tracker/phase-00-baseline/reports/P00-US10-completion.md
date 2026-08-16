# P00-US10 Completion Report

Status: Done  
Story: Run immutable corpus baselines and semantic comparisons  
Points: 5  
Started: 2026-07-29
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result | Evidence |
|---|---|---|
| Scope and non-scope explicit | Pass | One bounded benchmark-only runner/report contract for the registered 15-case corpus, isolated execution, immutable run IDs, semantic dimensions, and failure states; parser changes, promotion policy, hosted calls, and Phase 1 are excluded. |
| Points at most 5 | Pass | The approved replacement runner story is 5 points and reuses the completed registry, reviewed claims, control registry, existing parser entry point, and frozen analysis evidence. |
| Dependencies Done | Pass | P00-US03 and P00-US09 are Done after all gates and independent reviews. |
| Acceptance measurable | Pass | Require selected-case completion with no overwrite/skip, complete run identity and resource fields, 12 separate report dimensions, reviewed-mask enforcement, actionable negative states, deterministic stable outputs/quality counts, and declared performance tolerance. |
| Dedicated tests identified | Pass | `tests/stories/phase_00/test_p00_us10_corpus_runner.py`, additive contract/regression gates, a small isolated integration, and the full completed Phase 0/API/frontend suites. |
| Fixtures available and legally usable | Pass | All 15 registered PDF/Markdown/JSON triplets, 210 reviewed claims, 25-owner controls, frozen analysis run, and derived evidence are present and approved public/redistributable with no exceptions. |
| API/schema impact documented | Pass | Test/reporting-only versioned contracts; no public endpoint, production serializer, or parser schema change. |
| Feature flag identified | Pass | None; the runner is an explicit benchmark command and has no production request path. |
| Rollback defined | Pass | Remove only the additive runner, report contracts, new uniquely named run evidence, tests, and documentation while retaining all frozen sources, prior runs, registries, and reviewed evidence. |
| Quality/performance measures specified | Pass | Record 15/15 cases, 30/30 pages, zero silent skips/overwrites, per-dimension counts, output identities, runner overhead, per-case latency/CPU/RSS, aggregate p50/p95/RSS, and reference-environment tolerance. |

Definition-of-Ready result: **10/10 Pass**. P00-US10 transitioned Ready and
then In Progress under the approved sequential Phase 0 authorization only
after P00-US09 passed Definition of Done 10/10 and independent review.
At transition, P00-US10 was the sole story In Progress; Phase 1 remained unauthorized.

## Authorization and concurrency

The requester authorized sequential completion of Phase 0 and confirmed every
triplet and derived annotation is public and redistributable without
exceptions. P00-US09 was marked Done before this story started. No other story
is In Progress.

## Scope and non-scope

Implementation is limited to bounded benchmark tooling, strict run/report
contracts, immutable uniquely named run evidence, dedicated tests, and tracker
evidence. It may invoke the unchanged production parser through an explicit
offline benchmark boundary. It must not change parser/API behavior, overwrite
the frozen `baseline-20260728-current` analysis run or expert artifacts,
accept unsupported expert truth, call hosted services, install dependencies,
or begin Phase 1.

## Pre-implementation evidence

- P00-US04 registers 15 cases, 30 pages, and 45 immutable triplet artifacts.
- P00-US06–US08 provide 210 reviewed claims with separate literal and semantic
  masks; P00-US09 provides 25 four-role owners and all 109 case-gap rows.
- P00-US03 provides the immutable single-case runner pattern and five-run
  reference evidence.
- The frozen heterogeneous analysis run reports 15/15 successful cases,
  212.67 s aggregate parse time, p50 9.06 s, p95/max 46.76 s, median RSS
  1,437 MiB, maximum RSS 2,590 MiB, 5,289,462 JSON bytes, and 116,260
  Markdown bytes. It is input evidence, not proof this story is implemented.

## Implementation evidence

### Files changed

- `tests/benchmarks/corpus_runner.py`
- `tests/stories/phase_00/test_p00_us10_corpus_runner.py`
- `tests/contract/test_p00_us10_corpus_runner_schema.py`
- `tests/regression/phase_00/test_p00_us10_corpus_runner_regression.py`
- final retained integration/full-corpus evidence under
  `tracker/phase-00-baseline/evidence/p00-us10-*-20260729-03/`
- `tracker/phase-00-baseline/evidence/P00-US10-verification.md`
- this report and the Phase 0 tracker/status/closure documentation

Earlier `-01` and `-02` run directories remain immutable implementation
history. They exposed and then verified corrections for interpreter-alias
normalization and explicit worker/coordinator record binding. They were never
overwritten; only the lowercase canonical `-03` directories are completion
baselines.

No production module, dependency, configuration, source triplet, expert
artifact, reviewed annotation, prior run, public endpoint, parser schema,
serializer, feature flag, or parser behavior changed.

### Runner and report contracts

The new runner is isolated under `tests/`. It validates the complete corpus,
three claim batches, control registry, legacy reference outputs, settings,
offline policy, application source, runner source, required engine versions,
and hardware environment before reserving a directory. A run directory must
be a direct canonical evidence child named by its lowercase run ID and is
created with `exist_ok=False`.

Each selected case runs in a fresh subprocess. The coordinator records the
registered source/expert triplet, fixed command/settings/environment hashes,
timestamps, worker exit, parse and coordinator latency, CPU, RSS, warnings,
errors, raw/duration-masked/Markdown output identities, page completion, and
frozen-reference comparison. Raw worker records and coordinator projections
are retained separately and both are hash-bound by the top record.

The semantic report contains exactly 12 canonical dimensions: text, layout,
reading order, table, chart, diagram, Markdown, JSON, hallucination,
diagnostics, performance, and cost. Provenance is cross-cutting on every
claim rather than a thirteenth score. No composite quality score exists.

### Reviewed semantic boundary

The full report preserves all 210 original review records and all source
locators: 109 literal masks, 162 semantic masks, and 48 unsupported
exclusions. The source rows are narrative classifications, not executable
candidate predicates, so the 162 eligible claims are explicitly
`diagnostic_only`; automatic semantic score count is zero.

Incorrect, inferred, and unverifiable expert claims remain outside both masks.
The hallucination section cross-references all 48 exclusions and 25
negative/ambiguous controls. Whole-expert token similarity remains a legacy
diagnostic and is never treated as semantic pass/fail evidence.

### Retained result

| Measure | Result |
|---|---:|
| Selected / successful / skipped cases | 15 / 15 / 0 |
| Registered / successful pages | 30 / 30 |
| Semantic JSON identities stable | 15/15 |
| Exact Markdown identities stable | 15/15 |
| Reviewed / literal / semantic / excluded claims | 210 / 109 / 162 / 48 |
| Automatically scored / diagnostic-only eligible | 0 / 162 |
| Hosted requests / tokens / billed USD | 0 / 0 / 0.00 |
| Run-record file / semantic SHA-256 | `aa6192f9…10e2` / `e9037328…3ba7` |
| Report file / semantic SHA-256 | `3d2e36fd…7c77` / `ceb8765b…b4cb` |
| Quality / stable-output signature | `a18dfdee…a1ed` / `a7b02cde…13a0` |

Every one of the final directory's 94 files is covered by retained tree and
artifact regression identities. Read-only verification under both equivalent
`.venv/bin/python` aliases deterministically rebuilds the JSON/Markdown report
without changing any byte.

## Verification

The focused story/contract/regression gate passed 79 tests. All completed
Phase 0 story, contract, and regression suites passed 384. API/serializer
passed 22. The full backend passed 460 with the same 10 explicit opt-in skips
and one pre-existing warning. Python compile, frontend typecheck, lint, build,
27 unit tests, and one built-output test passed with installed supported Node
22.18.0.

On the matching frozen environment, final coordinator case latency measured
p50 9,817.816 ms and p95/max 46,706.960 ms. Peak RSS measured p50
1,503,772,672 bytes (1,434.11 MiB) and maximum 2,569,650,176 bytes
(2,450.61 MiB). All four values pass the predeclared 25% upper tolerance;
aggregate coordinator/parse/CPU times are 216,711.552/199,426.172/182,206.879
ms. Output totals are 5,289,461 raw JSON and 116,260 Markdown bytes.

Twenty consecutive strict full-run verifications measured p50 342.351 ms,
p95 370.614 ms, maximum 395.998 ms, and 104.953 MiB process peak RSS.

Commands, identities, complete dimension counts, warnings/skips, resource
method, compatibility, immutable history, and rollback are in
[`P00-US10-verification.md`](../evidence/P00-US10-verification.md).

## Independent review

Pass — no blockers. The reviewer independently passed 79 focused and 22
API/serializer tests; read-only verified both final retained runs; reproduced
the 94-file full-run tree, record/report/signature identities, 15/30/45
completion, every worker/coordinator binding, 210/109/162/48 masks, 109 rows,
100 controls, 25 safety controls, 12 dimensions, zero false scoring, all 15
JSON/Markdown reference matches, performance tolerance, zero cost, legacy
readability, production/API isolation, and additive rollback.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and all acceptance criteria complete | Pass — all six criteria met |
| Dedicated story/contract/regression tests pass | Pass — 79 tests |
| Completed Phase 0 and prior regressions pass | Pass — 384 tests; full backend 460 |
| API/schema/serializer compatibility passes | Pass — 22 tests and pinned identities |
| Immutable integration and full runs retained | Pass — 2/2 and 15/15 cases; no overwrite |
| Quality, performance, memory, and cost recorded | Pass — masks/signatures/tolerance/zero cost |
| Unsupported truth and safer disagreements preserved | Pass — 48 excluded; 0 false scores |
| Configuration, feature flag, and rollback verified | Pass — no config/flag; additive rollback |
| Completion report and independent review complete | Pass — no blockers |
| No concurrent story or unauthorized later-phase work | Pass — Phase 1 never started |

Definition-of-Done result: **10/10 Pass**. P00-US10 is Done. All ten Phase 0
stories are now Done; the separate Phase 0 exit assessment follows without
starting Phase 1.
