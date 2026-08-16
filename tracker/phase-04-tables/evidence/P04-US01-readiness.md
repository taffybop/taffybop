# P04-US01 readiness fixture evidence

Date: 2026-08-03  
Scope: readiness contracts, source-qualified oracle, synthetic controls, and
frontend implementation plan only  
Story status consequence: none; P04-US01 remains **Proposed** pending a fresh
independent 10/10 Definition-of-Ready review.

## Outcome and claim boundary

The repaired readiness slice is strict, closed, finite, and test-only. It does
not change parser, schema, API, serializer, frontend production code,
configuration, rollout, or rollback behavior.

The oracle now separates:

- exhaustive source truth: catastrophe Exhibit 7 has 6 rows, 5 columns, 30
  explicit cells, five separate `United States` values, exact cell bboxes and
  source refs, and no spans;
- source-qualified structural truth: only the explicitly enumerated finance,
  postal, clinical, and timetable dimensions may be scored; and
- observation-only evidence: ACORD's form-owned coverage region bbox and the
  visible `INSR LTR`, `TYPE OF INSURANCE`, and `LIMITS` labels remain
  independently addressable, but are not canonical cell topology.

Unavailable real-document cell, bbox, provenance, ownership, or span truth is
excluded from both numerator and denominator and requires its targeted
fail-closed concern. It is never treated as an accuracy pass. The story and
metrics now use that same boundary.

## Source-reviewed executable denominators

- Finance: page 1 and page 3 each have four columns and one reviewed
  three-column period span; page 2 has three columns and one logical wrapped
  source row.
- Postal page 1: 40 rows including the header, 39 data rows, two columns, 80
  explicit logical cells, two visible column-header owners, and one reviewed
  bottom-boundary row. Executable rows bind `Term or Acronym` / `Definition`
  and final `FERS` / `Federal Employees Retirement System`; the FERS row bbox
  is `(58.5, 708.75, 495.0, 15.75)` pt. Exact per-cell bboxes and complete
  cell-level provenance remain unresolved. Postal pages 2/3 each retain four
  columns and one reviewed three-column period span.
- Clinical page 2: six columns, six reviewed leaf header slots, five stub-only
  section rows, and zero full-width spans for those section rows. Clinical
  page 4: nine columns, nine reviewed leaf header slots, two stub-only section
  rows, two supported group spans of four and three columns, and zero
  full-width section spans. Exhaustive cells/bboxes/provenance remain
  unresolved.
- Timetable: each of three pages has 52 visual rows, 50 service rows, and 13
  columns. Page 3 source row 28 retains all 13 exact values including `3:32`.
- ACORD: only one form-owned coverage region plus three exact visible-header
  observations are addressable. Row/column/cell topology, spans, ownership,
  cell bboxes, cell provenance, and form-grid topology remain unresolved; the
  required action is retain-candidate-with-concern, not canonicalize.

The source PDFs are byte-verified in the focused test. Visual review confirms
the postal striped table ends in FERS, the clinical six- and nine-column
structures and reviewed headers/spans, and ACORD's form ownership. No expert
JSON/Markdown topology is used as ground truth.

## Closed limits and adversarial controls

The executable readiness caps are:

- 4,096 rows, 256 columns, and 65,536 cells/slots per table;
- 16,384 UTF-8 bytes per cell and 64 concerns per table;
- 64 oracle tables, 64 evidence IDs per record, and 64 source-object IDs per
  record;
- 256 UTF-8 bytes for every identifier, raw reference, and portable evidence
  path;
- 8,388,608 output bytes per marked table and 67,108,864 Phase 04 sidecar
  bytes per document;
- 0.500 seconds/page and 5.000 seconds/document for span fidelity;
- table-stage p95 overhead ratio at most 0.10; and
- enabled-minus-disabled peak-RSS delta at most 67,108,864 bytes.

Exact-bound witnesses pass and maximum-plus-one witnesses fail. Denominator
`expected` values are dimension-capped, units are dimension-bound, span member
count must equal the denominator, column-span widths are `[2,256]`, and
row-span heights are `[2,4096]`.

Portable paths reject absolute, drive/URI, encoded, tilde, backslash,
empty/dot, and non-portable segments, every occurrence of `..`, outer
whitespace, NUL/control characters, invalid UTF-8, and more than 256 bytes. An
executable temporary-directory test proves that a
lexically valid path resolving through a symlink outside the workspace is
rejected.

Seventeen registered controls are material rather than name-only. They contain
distinct rotated/multiline header grids, a bottom FERS boundary, an incomplete
partial grid, a decorative static-form grid, a genuine overlapping-span
collision, four hostile HTML-like cell values, and a flag-off witness with all
four flags false, zero fixture/stage calls, and predecessor/output byte-hash
identity. Legitimate row/column spans each carry two independently addressable
source objects, geometry and structure evidence records, and one linked span
decision. Missing decisions/evidence/source objects, wrong dimensions,
single-source evidence, duplicate evidence IDs, overlaps, negative indexes,
non-finite geometry, unsafe strings, and fan-out overflows all fail validation.

## Frontend readiness plan

`frontend/tests/p04-us01-table-readiness.test.mts` freezes the implementation
test path, three responsive viewports, hostile text inputs, strict sidecar
reader, escaped React grid, predecessor fallback, and copy/download parity
requirements. It intentionally does not claim those behaviors exist. The
separate production test
`frontend/tests/p04-us01-table-span-fidelity.test.mts` remains an
implementation-stage requirement before story completion.

Health-report and manufacturing charts, component-datasheet aligned prose, and
ACORD form regions remain non-target observations for US01. Canonical ownership
classification belongs to P04-US04 and was not started.

## Evidence identities

| Artifact | Raw SHA-256 |
|---|---|
| `tracker/phase-04-tables/decisions/P04-table-evidence-policy.md` | `81ae5843129bd0903d7b4517eb90d1100e0aaf8b7c46715d55bdcd9788903cc2` |
| `tracker/phase-04-tables/stories/P04-US01.md` | `1238f97d3e3595279d6cf7c6df71f4ef3481f83589028160a5205411bbc3deb3` |
| `tracker/phase-04-tables/metrics.md` | `c6c51cee8e987dc5e018936bc29121a32787a17a0bdd8221646f19d0c3939a0b` |
| `tests/contract/test_p04_us01_table_contract.py` | `b6967f31b25ec201f2a5552d1539e534a213a013bdbc532c2ae919d017d30a2b` |
| `tests/stories/phase_04/test_p04_us01_span_fidelity.py` | `551ca0e894759eb71d07fa0e95767b1ba0153ce7237b5fecc33fb88c1a0afeba` |
| `frontend/tests/p04-us01-table-readiness.test.mts` | `e0635f4564b0f462e3a9fc04bb7125cfecafca4f67603f79ef92d14baccb2979` |
| `tests/fixtures/phase_04/__init__.py` | `abbecc08d2706d9345b9c10809b02ee787ee6e310d246ebd02575aa6b93f1074` |
| `tests/fixtures/phase_04/tables/__init__.py` | `d475f22d170d885685369cbb5bd457a8ac2a84630dc3bd6f6e5c63f2ceca8769` |
| `tests/fixtures/phase_04/tables/contract.py` | `c62b3b401e9782b4c9326dd8d179d7adaf4c2585034068a150adf57f039928d9` |
| `tests/fixtures/phase_04/tables/oracle.py` | `41fd4b6b4330d9f13d9aa8c48ede4a43f2bc807767a80790fc893acebbd84ae6` |
| `tests/fixtures/phase_04/tables/synthetic.py` | `a67037f72dce9153c934aa3234fbad3daf3580c35ad4e6b4479c53594104b094` |

- Canonical oracle semantic SHA-256:
  `d34eba8a3a4fce187d607eb95fa61d85e9a3f473522718fe488fabeb4d6950e3`.
- Synthetic registry semantic SHA-256:
  `0ef6b9689c9f4edbde4e273c9d1a0e2f63366ea0cbcd5ce3c909eecaa17b8bee`.
- Reused P00 Exhibit 7 truth raw SHA-256:
  `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac`.

The six source PDF identities remain byte-validated. Custody remains
`public-redistributable` under requester/provider attestation; no independent
license review or named license was supplied.

## Verification

Backend readiness contract + story command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/contract/test_p04_us01_table_contract.py tests/stories/phase_04/test_p04_us01_span_fidelity.py
```

Result: **101 passed, 0 failed, 0 skipped, 1 warning in 0.30 seconds**.

Adding existing table normalization/classification regressions:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/contract/test_p04_us01_table_contract.py tests/stories/phase_04/test_p04_us01_span_fidelity.py tests/test_table_normalization.py tests/test_table_classification.py
```

Result: **108 passed, 0 failed, 0 skipped, 1 warning in 0.33 seconds**.

Python compilation of `tests/fixtures/phase_04`, `tests/stories/phase_04`, and
the P04 contract test passed. The one backend warning is the pre-existing
FastAPI `StarletteDeprecationWarning` for `httpx`/`starlette.testclient`; no
Phase 04 warning was emitted.

With exact Node **24.14.0**:

- the new frontend readiness file: **3 passed, 0 failed/skipped**;
- complete frontend unit suite: **109 passed, 0 failed/skipped**;
- frontend lint: pass; and
- frontend typecheck: pass.

The shell printed two non-test `pyenv` rehash notices because its shim
directory is read-only; all Node commands exited zero.

## Guardrail and deferred implementation gates

This is a candidate readiness package, not a self-approval. It does not claim
production acceptance, story readiness, story implementation/completion,
TEDS/GriTS, measured latency/RSS/output, API/serializer/frontend production
behavior, benchmark drift, full backend, build/bundle/responsive results, or
Phase 04 exit. Those are implementation-stage and phase-exit gates. P04-US01
must remain Proposed until the fresh independent 10/10 review is recorded; no
later Phase 04 story and no Phase 05 work is started by this evidence.
