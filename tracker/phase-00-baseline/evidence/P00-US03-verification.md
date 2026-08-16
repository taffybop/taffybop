# P00-US03 Verification Evidence

Status: Pass  
Captured: 2026-07-28  
Scope: Test/reporting-only catastrophe baseline; no production behavior change

## Evidence identity

| Artifact | SHA-256 |
|---|---|
| Immutable run-set record | `a87053e9c3e019ff1aab98c3c73bb8247654c49ac14faa1237f9503dc519ac0d` |
| Baseline JSON | `5ed1342c5c649d661f3c1ecf457484c3c9ad9ad7cb728b34c69b93f9759efa0d` |
| Baseline Markdown | `a75b2a41e0b6a2bc8b5bb7f2e53c4ac526ecd62450b8110555eeac840fc0a89a` |
| Compatibility JSON | `29251854a8e79a37446c5ecea8c4494e94fa336b84fe34b845c8cb32b56292a9` |
| Source truth | `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac` |
| Source-rights record | `a8176f88ca7bebd7b9c5fa28b88db064570c603c926fcd2e0f65f943fbb573ff` |
| Captured source/tool tree | `1a24a65b5a9cca959d1d805e8dc169714e0a67a84e0c4cf47c7cb9154ef4bfd7` |
| Settings payload | `27931e7bf4a5a04afcaa4c6139f35dadb7dc18a7ed16b2121c41b4e72d69e2e3` |

The immutable raw directory is
`P00-US03-baseline-runs-20260728/`. It contains five run directories,
`run-set.json`, and the exact portable capture command. The capture and worker
both refuse to overwrite an existing run directory.

## Reference environment and boundary

- macOS 26.5, arm64, 10 logical CPUs.
- Python 3.13.5; application 0.1.0; Docling 2.114.0;
  docling-core 2.87.1; Pydantic 2.13.4; pytest 9.1.1.
- Node.js v24.18.0; Tesseract 5.5.3.
- Hosted services, optional models, and image captioning disabled.
- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and
  `TOKENIZERS_PARALLELISM=false` enforced in each worker.
- Exact approved public/redistributable catastrophe
  PDF/Markdown/JSON triplet only; no wider corpus custody assumption.

## Repeated-run measurements

| Run | Parse duration (ms) | CPU (ms) | Peak RSS (MiB) | Result |
|---|---:|---:|---:|---|
| `catastrophe-cold-01` | 11,955.223 | 8,450.889 | 1,338.42 | Success |
| `catastrophe-cold-02` | 8,375.082 | 7,683.472 | 1,415.02 | Success |
| `catastrophe-cold-03` | 8,029.354 | 7,680.148 | 1,428.33 | Success |
| `catastrophe-cold-04` | 8,050.770 | 7,710.341 | 1,427.36 | Success |
| `catastrophe-cold-05` | 7,944.886 | 7,588.803 | 1,426.97 | Success |

Nearest-rank distributions:

| Metric | Minimum | p50 | p95/max | Mean |
|---|---:|---:|---:|---:|
| Parse duration (ms) | 7,944.886 | 8,050.770 | 11,955.223 | 8,871.063 |
| Peak RSS (MiB) | 1,338.42 | 1,426.97 | 1,428.33 | 1,407.22 |

All five runs have stable fixture, source-truth, settings, environment,
semantic JSON, backend Markdown, frontend Markdown, frontend text, and atomic
quality identities. Raw JSON and frontend-normalized JSON have five unique
hashes because they retain the measured `processing.duration_ms`; removing
only `/processing/duration_ms` yields semantic JSON SHA-256
`0d31d1cf81f71317c4ceaf6e317502ced47aa4443932eea4eb1afa4d19e3bbc9`
in every run.

Reference output sizes are 79,005–79,006 raw JSON bytes; 38,325 canonical
semantic JSON bytes; 2,008 backend/frontend Markdown bytes; 112,013–112,014
frontend-normalized JSON bytes; and 1,965 frontend text bytes.

## Source-grounded quality

The stable quality signature is
`8507b5d0da5dfccda412b23757e091d59de7178899b3749305420649d9bbc998`:
5 passes and 10 known baseline failures in every run.

Passes:

- exact 6×5 Exhibit 7 table;
- exactly one chart-routed Exhibit 8 item;
- unsupported exact Exhibit 8 value tables/series withheld;
- accepted AON logo OCR retained in JSON;
- backend and frontend Markdown byte parity.

Failures:

- damaged named-event/currency sentence;
- missing separate Exhibit 7 caption;
- Exhibit 8 title merged into chart OCR;
- missing separate source note;
- duplicated fused year-anchor stream;
- missing accepted `1H` legend;
- no structured chart series/mark associations;
- AON omitted from primary Markdown;
- printed page 7 not distinct from physical page 1;
- insufficient targeted warnings/concerns.

Rejected/raw OCR, misplaced captions, rejected AON children, synonymous
fabricated chart tables, and stale expert duplicate-title/span/value defects
cannot produce a false pass.

## Commands and results

| Gate | Exact command | Result |
|---|---|---|
| Capture | `.venv/bin/python -m tests.benchmarks.baseline_report capture --source benchmark-expertmodeldata/catastrophe-recap.pdf --truth tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json --runs-root tracker/phase-00-baseline/evidence/P00-US03-baseline-runs-20260728 --repeat 5 --node /opt/homebrew/opt/node@24/bin/node` | 5/5 successful |
| Dedicated + P00-US03 regression | `.venv/bin/pytest -q tests/stories/phase_00/test_p00_us03_baseline_report.py tests/regression/phase_00/test_p00_us03_baseline_regression.py` | 26 passed |
| Phase 0 + contract + API/serializer | `.venv/bin/python -m pytest -q tests/stories/phase_00 tests/regression/phase_00 tests/contract tests/test_api.py tests/test_serializer.py` | 102 passed; 1 warning |
| API/schema/serializer | `.venv/bin/python -m pytest -q tests/test_api.py tests/test_serializer.py tests/contract` | 25 passed; 1 warning |
| Full backend | `.venv/bin/python -m pytest -q` | 156 passed; 10 explicit skips; 1 warning |
| Frontend typecheck | `/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false` from `frontend/` | Pass |
| Frontend lint | `/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs` from `frontend/` | Pass |
| Frontend unit | `/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts` from `frontend/` | 27 passed |
| Python compile | `.venv/bin/python -m py_compile tests/benchmarks/baseline_report.py tests/stories/phase_00/test_p00_us03_baseline_report.py` | Pass |
| Deterministic summary rebuild | `tests.benchmarks.baseline_report summarize` to a new temporary directory, followed by byte comparison | JSON and Markdown identical |

The 10 full-suite skips are individually recorded with exact node ID, owner,
reason, and opt-in condition in `P00-US03-compatibility.json` and the baseline
report. None is counted as a pass. The only pytest warning is the pre-existing
Starlette `httpx` test-client deprecation. Each worker stderr also retains a
non-failing Transformers `torch_dtype` deprecation and local weight-loading
progress; there is no traceback or hosted/network activity.

## API and serializer compatibility

| Schema | Canonical SHA-256 |
|---|---|
| OpenAPI | `3c71271be81fc55e8f85229e1ffdf01ef6a7977c4638a87449617749a1a2983a` |
| `ParseResult` | `706a1f63bf77eaa6cc3f114b9b5c976d07d764de04a8beffa45cd2b04aafa91f` |
| `ErrorResponse` | `3fde7027b8452307282b52870914475672aed4b4326018867fdf467922d1a5a6` |

No `app` module imports the test-only baseline contracts. Frontend projections
invoke the real normalizer and serializers, and all five retained projections
rebuild byte-identically on Node 24.

## Rollback and limitations

The story changes only test/reporting code and evidence. Removing the runner
and its tests from active use restores the pre-story executable surface with no
production rollback; the completed immutable evidence directory should remain
archived. No feature flag or runtime configuration changed.

Measurements are hardware-specific and use five cold samples, so p95 is the
sample maximum. Optional real-model integration tests remain opt-in, the
catastrophe parser retains 10 known quality failures, and P00-US04 still needs
an exact custody/exception disposition for the other 14 cases.

## Independent review

A fresh independent reviewer returned Pass with no blockers after revalidating
all five runs and 25 output artifacts, only-duration semantic volatility,
nearest-rank distributions, byte-identical report rebuilding, API/schema
hashes, the 156-pass/10-skip backend result, Node 24 gates, source/tool-tree
isolation, scope, rollback, and tracker consistency.
