# P00-US02 Verification Evidence

Verified: 2026-07-28  
Environment: macOS 26.5 arm64, Python 3.13.5, Node.js 24.18.0

## Registered evidence

- Source-use decision:
  `P00-US02-source-rights.md`.
- Source-truth bundle:
  `P00-US02-catastrophe-truth.json`.
- Source-truth SHA-256:
  `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac`.
- Source-truth size: 144,444 bytes.
- Exact approved triplet:
  - PDF:
    `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e`
  - Markdown:
    `5104172e1d81eed0a001efaec7bec6f05d32a95f58dc169aacdc5842082069e8`
  - JSON:
    `cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db`

The bundle records physical page 1 / printed page 7 in unrotated
612 × 792-point top-left PDF coordinates. It contains 11 source elements,
5 semantic relationships, 30 explicit Exhibit 7 cells, 23 printed Exhibit 8
labels, 88 source-measured chart points, and 4 executable synthetic negative
controls.

Every PDF-derived claim is source-verified. Printed/native claims and exact
parity masks remain distinct from inferred relationships, measured chart
values, and unknowable exact chart values. The custody approval is a separate
governance record and is not misclassified as visible PDF text.

## Chart review

The reviewed linear-axis calibration records a 557.105-point inferred zero
baseline, 0.822964 points per 2025 USD billion, 0.401614-point coordinate
quantization, and ±1.0 billion measurement tolerance. Raw vector bboxes,
panel/year/series identity, annual/1H pairing, label geometry, and left-to-right
year/panel associations are validated.

Comparison with the current registered expert JSON found:

- 88/88 source measurements carry method, unit, tolerance, and evidence link;
- 57/88 expert values differ from source geometry by more than $1 billion;
- 35/88 differ by more than $2 billion;
- 17/88 are within ±$0.5 billion;
- source-reviewed examples include Americas 2017 annual = 54.17,
  USA 2022 annual = 118.10, and USA 2025 1H/annual = 91.75.

The older assessment used
`frontend/app/expertmodel.json`
(`c22eb9bc2571f06f0f87f3873d8935e2d2f241ae2d9ee49a035cfdda776722c4`).
The current registered expert JSON has hash
`cf0e1b11bd4e44b9ac20725e2bdf51a8301ea9bde173bbf1224c1280511381db`
and directly verifies one Exhibit 8 title, five explicit “United States”
table rows without `rowspan`, and 44 chart rows where annual total is never
below 1H. Duplicate title, false row span, and annual-below-1H therefore remain
synthetic validator controls, not current-expert defects.

## Verification commands and results

Dedicated P00-US02 story and regression gate:

```text
.venv/bin/python -m pytest -q tests/stories/phase_00/test_p00_us02_catastrophe_truth.py tests/regression/phase_00/test_p00_us02_catastrophe_regression.py
26 passed, 1 pre-existing warning in 0.24s
wrapper elapsed_seconds=0.790
wrapper max_rss_mib=75.70
```

Impacted Phase 0, contract, regression, API, and serializer gate:

```text
.venv/bin/python -m pytest -q tests/stories/phase_00/ tests/contract/ tests/regression/phase_00/ tests/test_api.py tests/test_serializer.py
76 passed, 1 pre-existing warning in 0.54s
wrapper elapsed_seconds=1.298
wrapper max_rss_mib=81.69
```

Full backend gate:

```text
.venv/bin/python -m pytest -q
130 passed, 10 unchanged opt-in integration skips, 1 pre-existing warning in 8.81s
wrapper elapsed_seconds=9.955
wrapper max_rss_mib=505.53
```

The warning is Starlette's existing `httpx` test-client deprecation. The ten
skips still require explicit real-model/shared-analysis integration flags.

Supported frontend compatibility gate, run directly with Node.js 24.18.0:

```text
/opt/homebrew/opt/node@24/bin/node node_modules/typescript/bin/tsc --noEmit --pretty false
exit 0

/opt/homebrew/opt/node@24/bin/node node_modules/eslint/bin/eslint.js . --ignore-pattern dist --ignore-pattern .next --ignore-pattern public/pdf.worker.min.mjs
exit 0

/opt/homebrew/opt/node@24/bin/node --experimental-strip-types --test tests/*.test.mts
27 passed, 0 failed
```

The successful frontend commands emitted only an environment-level pyenv rehash
warning because the shim directory is read-only; it did not affect the gates.

Additional integrity and compatibility checks:

```text
.venv/bin/python -m compileall -q tests/benchmarks/source_truth.py tests/stories/phase_00/test_p00_us02_catastrophe_truth.py tests/regression/phase_00/test_p00_us02_catastrophe_regression.py
exit 0

jq -r '.cases[].files[] | "\(.sha256)  \(.path)"' tracker/benchmarks/llamaparse-15/manifest.json | shasum -a 256 -c -
45/45 source/expert artifacts OK

rg -n "tests\.benchmarks|benchmarks\.contracts|benchmarks\.source_truth" app frontend
no matches (rg exit 1)
```

Frozen current-parser catastrophe outputs remain byte-identical:

```text
our-output.json  3f1f0d9b7768e119d65a887e73f54173df633eeca004e9296bcfeb6aebc91abe
our-output.md    9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1
```

## Review result

An independent adversarial review mutated custody links, page identity,
element content/order/geometry, relationships, table spans/cells/grid,
chart labels/calibration/values/year associations, measurement IDs, review
statuses, evidence classes, and negative controls. Each substantive accepted
corruption was converted into a rejecting validator and regression test. The
reviewer then independently passed the full backend, compile, import, and hash
gates and found no remaining code/evidence gap.

