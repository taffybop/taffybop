# P00-US01 Verification Evidence

Date: 2026-07-28  
Environment: existing `.venv` (Python 3.13.5, pytest 9.1.1, Pydantic 2.13.4)

## Completion-evidence audit and correction

The original P00-US01 gates reproduced at 10 dedicated tests, 34 impacted-gate
tests, and 88 backend tests with 10 opt-in skips. A resume audit then found
four control groups missing from the original completion evidence:

1. positive infinity was accepted for metric values, tolerances, and run
   durations, allowing canonical output to contain the non-standard JSON token
   `Infinity`;
2. measured evidence could be marked for literal exact parity; and
3. manifest and annotation controls were serialized but not independently
   round-tripped; and
4. schema versions defaulted silently, while exported JSON Schemas omitted the
   supported-version constant, hash patterns, unit enum, non-empty command
   constraint, and measured-evidence linkage/method.

The story was conservatively reopened. Numeric contract fields now require
finite, non-negative values, canonical JSON rejects non-finite values even if a
model bypasses validation, and measured/inferred/unknowable annotations cannot
enter literal exact parity. Versions are explicit and required; machine schemas
publish their version, hash, unit, command, and exact-parity constraints.
Measured metrics record a method and optional fixture/annotation links.
Manifest, annotation, metric, and run records all have deterministic
round-trip coverage, including a pinned version-`1.0` wire payload.

## Contract result

The complete synthetic run record validates and deterministically round-trips.
It records parser/model versions, command, hardware, fixture SHA-256, output
SHA-256, duration, metric value/unit/tolerance, and evidence class.

| Control | Result |
|---|---|
| Valid manifest, annotation, metric, and run-record round trips | Pass |
| Pinned initial-version backward read | Pass |
| Explicit required version and machine-schema constraints | Pass |
| Missing/malformed SHA-256 | Rejected with actionable validation error |
| Unknown truth class | Rejected |
| Measured/inferred/unknowable exact-parity claim | Rejected |
| Measured metric method, fixture link, annotation link, unit, and tolerance | Preserved |
| Invalid unit, negative/non-finite tolerance, metric value, or duration | Rejected |
| Deterministic, standards-compliant serialization | Pass |
| Production-import isolation | Pass; references are limited to tests and tracker documentation |
| Rollback feasibility | Pass; contracts have no production imports or public API changes |

## Commands and results

```text
.venv/bin/pytest tests/stories/phase_00/test_p00_us01_metric_contracts.py -q
23 passed, 1 warning in 0.11s

.venv/bin/pytest tests/stories/phase_00/ tests/contract/ tests/regression/phase_00/ tests/test_api.py tests/test_serializer.py -q
50 passed, 1 warning in 0.30s

.venv/bin/pytest tests/ -q
104 passed, 10 skipped, 1 warning in 7.07s

.venv/bin/python -m compileall -q tests/benchmarks tests/stories/phase_00 tests/contract tests/regression/phase_00
exit 0

/opt/homebrew/Cellar/node@24/24.18.0/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false
exit 0

/opt/homebrew/Cellar/node@24/24.18.0/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs
exit 0

/opt/homebrew/Cellar/node@24/24.18.0/bin/node --experimental-strip-types --test tests/*.test.mts
27 passed, 0 failed

jq -r '.cases[].files[] | "\(.sha256)  \(.path)"' tracker/benchmarks/llamaparse-15/manifest.json | shasum -a 256 -c -
45/45 source/expert artifacts OK

rg -n "tests\.benchmarks|benchmarks\.contracts" app frontend --glob '!frontend/node_modules/**'
no matches (expected rg exit 1)
```

The warning is the existing FastAPI TestClient/httpx deprecation warning.
The 10 skipped tests require intentionally disabled real image-model, Docling,
or shared-analysis integrations; no skip was introduced by this story.
Frontend commands used the supported installed Node 24.18.0 runtime. Typecheck
and lint emitted only a shell-level, non-fatal pyenv rehash warning because the
external shim directory is read-only; each command exited 0.

## Resource measurements

| Command group | Elapsed | Child peak RSS |
|---|---:|---:|
| Dedicated P00-US01 test | 0.693 s | 71.44 MiB |
| Dedicated + contract + phase regression + API/serializer | 0.895 s | 77.22 MiB |
| Full backend suite | 8.198 s | 512.78 MiB |

Peak RSS was sampled from macOS `resource.getrusage(RUSAGE_CHILDREN)` and
converted from bytes to MiB. These are test-infrastructure measurements, not
parser-quality benchmark measurements; P00-US03/P00-US05 own parser baselines.

## Before-and-after correction evidence

| Evidence | Before correction | After correction |
|---|---|---|
| Positive-infinity metric/tolerance/duration controls | 0/3 rejected; canonical JSON could emit `Infinity` | 3/3 rejected; strict serializer also fails closed |
| Measured exact-parity claim | Accepted | Rejected, along with inferred and unknowable claims |
| Version presence and machine schema | Version silently defaulted; schema omitted version/hash/unit/command constraints | Version required; JSON Schema exposes constants, patterns, enums, and non-empty commands |
| Measured evidence record | No method or source-claim link | Method plus optional fixture/annotation links, unit, and tolerance |
| Backward read and deterministic round trips | Self-generated run payload only | Pinned v1 run wire plus manifest, annotation, metric, and run round trips |
| Mapping-order regression | Reversed only top-level constructor arguments | Proves raw nested-map order differs before canonical equality |
| P00-US01 dedicated/contract/regression controls | 12 passed but omitted the above cases | 28 passed with the missing cases covered |
| Production parser/API output | Unchanged | Unchanged |
