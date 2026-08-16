# P00-US10 Verification

Status: Done  
Date: 2026-07-29  
Scope: immutable offline corpus runner and semantic-report contracts only

## Final retained runs

| Evidence | Result |
|---|---|
| Two-case integration | `p00-us10-integration-20260729-03`; 2/2 cases, 2/2 pages |
| Full corpus | `p00-us10-corpus-20260729-03`; 15/15 cases, 30/30 pages |
| Full run directory | `tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/` |
| Full run files / bytes / tree SHA-256 | 94 / 5,922,586 / `a145ac7e2b56a0631c27b565a131e7ec83061ebf69e7c8c66692f383126541da` |
| Run-record file / semantic SHA-256 | `aa6192f99e8c7ac8136aad7a7ed47278e02f9093d8d37b219e2068b020c310e2` / `e9037328dbd5f61fb770c69cc0f6acbd4ec7f64a80896cd50136d7f5b24a3ba7` |
| Semantic-report file / semantic SHA-256 | `3d2e36fd6696039abaeb346fc458687f9f114a340bc895c8ee5b921efbb17c77` / `ceb8765bb06ad4c60bbaeb39f69fff932595163da1811611ff2f86ea2c7fb4cb` |
| Markdown report SHA-256 | `e8448fc677adf1e31debb90e95b27c98d4f42cb3e94fb2fe9ae99102f2975c87` |
| Quality signature | `a18dfdeec1eda8840e269da046285aa518a9a6094e4943e174f0893dc216a1ed` |
| Stable-output signature | `a7b02cdee0e58c881122a692d2bfecdacb13eefbb35225be705ae3ff6c7113a0` |

Every case ran in a fresh subprocess with the fixed local settings and enforced
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and
`TOKENIZERS_PARALLELISM=false`. Image captioning, optional models, network
access, and hosted services were disabled. Each child has raw JSON, Markdown,
worker logs, a raw worker record, and a separately hash-bound coordinator
projection. The top record binds all 30 case-record artifacts.

The run directory must be a direct
`tracker/phase-00-baseline/evidence/<run_id>` child whose basename is its
lowercase run ID. Full frozen-input and engine/version preflight completes
before directory reservation. Existing directories, duplicate/empty/unknown
case selections, altered registered bytes, missing versions, partial pages,
worker errors, timeouts, and silent/missing case records fail closed.

Earlier `-01` and `-02` integration/full-corpus directories remain immutable
historical implementation evidence. They were superseded, not rewritten:
`-01` exposed interpreter-alias sensitivity; `-02` preceded the final
worker/coordinator record binding and canonical run-directory rule. Only the
lowercase `-03` runs are completion baselines.

## Reviewed parity and semantic boundary

| Measure | Result |
|---|---:|
| Reviewed claims | 210 |
| Literal-eligible | 109 |
| Semantic-eligible | 162 |
| Unsupported exclusions | 48 |
| Automatically scored claims | 0 |
| Eligible diagnostic-only claims | 162 |
| Negative/ambiguous safety controls | 25 |
| Unresolved or hidden claims | 0 |

The 210 review rows are source-grounded narrative classifications, not 210
machine-executable expected-value predicates. The report therefore preserves
every original mask, review status, case/claim identity, all 271 source
locators, and the current duration-masked output hash, while marking eligible
claims `diagnostic_only`. It does not infer pass/fail from claim prose, token
overlap, or whole-expert-output similarity.

All 48 incorrect, potentially inferred, or not-independently-verifiable claims
remain `excluded_unsupported` with both masks false. The hallucination section
cross-references those 48 exclusions and all 25 negative/ambiguous controls.
No unsupported expert field enters a numerator or denominator. This preserves
the parser's justified safer disagreements without claiming that Phase 0 built
a semantic matcher.

## Twelve separate dimensions

| Dimension | Claims | Literal | Semantic | Scored | Diagnostic | Excluded | Gap rows | Controls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Text | 77 | 72 | 74 | 0 | 74 | 3 | 14 | 16 |
| Layout | 45 | 20 | 38 | 0 | 38 | 7 | 35 | 24 |
| Reading order | 9 | 0 | 9 | 0 | 9 | 0 | 7 | 8 |
| Table | 30 | 12 | 21 | 0 | 21 | 9 | 12 | 12 |
| Chart | 14 | 3 | 8 | 0 | 8 | 6 | 11 | 8 |
| Diagram | 8 | 2 | 5 | 0 | 5 | 3 | 3 | 4 |
| Markdown | 0 | 0 | 0 | 0 | 0 | 0 | 12 | 4 |
| JSON | 27 | 0 | 7 | 0 | 7 | 20 | 13 | 8 |
| Hallucination | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| Diagnostics | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 12 |
| Performance | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| Cost | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Hallucination additionally carries 48 cross-cutting excluded claim IDs and 25
safety-control IDs. Markdown and JSON each carry 15 exact output comparisons.
Performance and cost use measured execution records rather than claim prose.
All 12 dimensions appear once in canonical order; there is no weighted or
undifferentiated quality score.

## Output stability, performance, and cost

All 15 duration-masked JSON hashes and all 15 exact Markdown hashes match the
frozen M0 reference. Raw JSON totals 5,289,461 bytes versus the frozen
5,289,462-byte snapshot because the public measured duration remains volatile;
only `/processing/duration_ms` is masked. Markdown is byte-identical at
116,260 aggregate bytes.

| Measure | Frozen M0 | Final P00-US10 | Difference |
|---|---:|---:|---:|
| Coordinator case latency p50 | 9,061.991 ms | 9,817.816 ms | +8.34% |
| Coordinator case latency p95/max | 46,758.352 ms | 46,706.960 ms | -0.11% |
| Peak RSS p50 | 1,506,803,712 bytes | 1,503,772,672 bytes | -0.20% |
| Peak RSS maximum | 2,715,254,784 bytes | 2,569,650,176 bytes | -5.36% |
| Aggregate coordinator latency | 212,665.919 ms | 216,711.552 ms | +1.90% |
| Aggregate parse latency | not separately contracted | 199,426.172 ms | recorded |
| Aggregate worker CPU | not separately contracted | 182,206.879 ms | recorded |

The hardware, Python, application, and engine fingerprint matches the frozen
environment. All four declared performance bounds pass the predeclared 25%
upper tolerance. The report records zero hosted requests, zero prompt or
completion tokens, and USD 0.00 billed cost.

Twenty consecutive strict full-run verifications, including current frozen
input reconciliation, all retained artifact hashes, deterministic report
rebuild, and Markdown comparison, measured p50 **342.351 ms**, p95
**370.614 ms**, maximum **395.998 ms**, and **104.953 MiB** process peak RSS.

## Frozen identities and compatibility

- Corpus registry file/semantic SHA-256:
  `f8024ab7…3ceb` / `f7c3bdf4…e4ca`.
- Control registry file/semantic SHA-256:
  `a383938d…6b5` / `d3c73495…8fce`.
- Batch A/B/C file and semantic identities remain unchanged.
- Frozen M0 metadata/comparison SHA-256:
  `386c333b…128f` / `2a23aabc…0e7b`.
- Production source identity:
  `72e3e1bfd2c3efe9abca2d916cb683d3c2c24e4e110014a034320ceff164a4fc`.
- OpenAPI, `ParseResult`, and `ErrorResponse`:
  `3c71271b…983a`, `706a1f63…a91f`, and `3fde7027…a5a6`.

The pre-existing analysis tools and M0/P00-US03 runs remain byte-stable and
read-only. Production code has no import of the runner or its evidence. No
production parser, public API, serializer, dependency, configuration, output
field, feature flag, source triplet, expert artifact, reviewed annotation, or
prior run changed.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Final two-case capture | `.venv/bin/python3 -m tests.benchmarks.corpus_runner capture --workspace . --run-dir tracker/phase-00-baseline/evidence/p00-us10-integration-20260729-03 --run-id p00-us10-integration-20260729-03 --corpus-registry tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json --control-registry tracker/phase-00-baseline/evidence/P00-US09-control-registry.json --timeout-seconds 420.0 --cases catastrophe-recap clean-energy` | 2/2 cases, 2/2 pages |
| Final full capture | `.venv/bin/python3 -m tests.benchmarks.corpus_runner capture --workspace . --run-dir tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03 --run-id p00-us10-corpus-20260729-03 --corpus-registry tracker/phase-00-baseline/evidence/P00-US04-corpus-registry.json --control-registry tracker/phase-00-baseline/evidence/P00-US09-control-registry.json --timeout-seconds 420.0` | 15/15 cases, 30/30 pages |
| Read-only verify | `.venv/bin/python3 -m tests.benchmarks.corpus_runner verify --workspace . --run-record tracker/phase-00-baseline/evidence/p00-us10-corpus-20260729-03/run-record.json` | Pass; zero byte changes |
| Dedicated + contract + regression | `.venv/bin/python -m pytest -q tests/stories/phase_00/test_p00_us10_corpus_runner.py tests/contract/test_p00_us10_corpus_runner_schema.py tests/regression/phase_00/test_p00_us10_corpus_runner_regression.py` | 79 passed |
| Completed Phase 0 + contract + regression | `.venv/bin/python -m pytest -q tests/stories/phase_00 tests/contract tests/regression/phase_00` | 384 passed |
| API/serializer | `.venv/bin/python -m pytest -q tests/test_api.py tests/test_serializer.py` | 22 passed |
| Full backend | `.venv/bin/python -m pytest -q` | 460 passed; 10 explicit opt-in skips |
| Python compile | `.venv/bin/python -m compileall -q app tests` | Pass |
| Frontend typecheck/lint | direct installed Node 22.18.0 TypeScript and ESLint commands | Pass |
| Frontend build | Node 22.18.0 `npm run build` | Pass |
| Frontend unit / built output | Node 22.18.0 test commands | 27 / 1 passed |

Backend gates emit the pre-existing Starlette `httpx` test-client deprecation.
The ten skips retain their explicit real-model/integration opt-ins. Frontend
checks emit the existing non-failing pyenv rehash warning; the build also
retains vinext's non-failing dynamic-route classification notice.

## Rollback

Rollback is additive: stop invoking and remove the test-only runner, its three
test files, and documentation from active validation. Retain all source
triplets, reviewed annotations, registries, legacy runs, and the immutable
P00-US10 run directories as audit evidence. Production behavior needs no
reversion because it never changed.

## Independent review

Pass — no blockers. The reviewer independently passed the 79 focused and 22
API/serializer tests, read-only verified both final runs, reproduced both
retained trees and every worker/coordinator binding, and reconciled 15/30/45,
210/109/162/48, 109 gap rows, 100 controls, 25 safety controls, all 12
dimensions, zero scored claims, and zero failure/skip states.

The reviewer reproduced all 15 duration-masked JSON and exact Markdown
reference matches, both semantic signatures, environment-comparable
performance within tolerance, zero hosted cost, frozen M0/P00-US03
readability, production isolation, application/API identities, and additive
rollback. No limitation was promoted into truth and no completion blocker
remains.
