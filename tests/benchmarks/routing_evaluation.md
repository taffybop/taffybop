# Offline routing evaluation

This first milestone audits **saved raw `/v1/parse?output_format=json` responses**.
It neither runs the parser nor calls an OCR/model provider. It complements the
existing governed LlamaParse-15 corpus; it does not replace its reviewed claims,
custody rules, release gates, or immutable runner.

Run from the repository root:

```bash
.venv/bin/python -m tests.benchmarks.routing_evaluation \
  --workspace . --manifest tmp/backend-fidelity/routing-manifest.json \
  > tmp/backend-fidelity/routing-report.json
.venv/bin/python -m pytest tests/benchmarks/test_routing_evaluation.py -q
```

The CLI reads inputs and writes only JSON to stdout. Input errors produce JSON
on stderr and exit 2. A successfully produced report exits 0 even when it finds
errors or candidate harm; report creation is not an accuracy/release gate.
Never redirect stdout over an input file. Reports can contain source values and
must be handled with the same access restrictions as the documents.

## Manifest

All artifact paths are relative to `--workspace`; escapes and symlink escapes
are rejected. Hash the **original source bytes**, not extracted text. The source
hash must agree with the file, each response's `document.sha256`, and ground
truth. Response byte hashes are always recorded and can optionally be pinned.
The manifest and expectation file hashes are also retained in the report.

```json
{
  "schema_version": "1.0",
  "cases": [{
    "case_id": "supplier-table-01",
    "source": {"path": "tmp/source.png", "sha256": "<64 lowercase hex characters>"},
    "baseline": {"path": "tmp/baseline.json"},
    "candidate": {
      "path": "tmp/candidate.json",
      "measurements": {
        "latency_ms": 2300.0,
        "cost_usd": 0.012,
        "method": "measured request duration and provider billing record"
      }
    },
    "expected_path": "tmp/expected.json"
  }]
}
```

`candidate`, `expected_path`, and `measurements` are optional. Measurement
numbers in this example illustrate the format; they are not benchmark results.
Without measurements, latency comes only from `processing.duration_ms` when
present and valid; cost remains `null`. An explicit measurement object is
authoritative, including its nulls. Do not compare API processing time with
end-to-end time as equivalent: the report retains the measurement method, but
does not establish compatible environments or measurement boundaries. Aggregate
means/sums include only observed measurements and display missing-case counts.

## Reviewer-authored expectations

Create expectations from the original document or independent source fixture,
never by copying candidate output as truth. Each check names its source evidence.
Only `visible_text`, `native_data`, and `embedded_data` can be exact targets.
Use `selected_claims` unless a reviewer has checked all relevant case content.

```json
{
  "schema_version": "1.0",
  "source_sha256": "<same source hash>",
  "reviewer": "reviewer name / revision",
  "coverage": "selected_claims",
  "checks": [{
    "check_id": "full-line-items",
    "kind": "rows",
    "selector": {"page_index": 1, "item_type": ["table", "table_candidate"]},
    "pointer": "/rows",
    "expected": [["SKU", "Quantity"], ["A-101", "12"], ["B-204", "7"]],
    "ordered": true,
    "truth_class": "visible_text",
    "evidence_ref": "page 1, entire three-row supplier table"
  }, {
    "check_id": "total",
    "kind": "field",
    "selector": {"page_index": 1, "item_type": "key_value", "match": {"key": "Total"}},
    "pointer": "/value",
    "expected": "125.00",
    "expected_count": 1,
    "truth_class": "visible_text",
    "evidence_ref": "page 1, total immediately below supplier table"
  }]
}
```

Selectors match top-level page items by type, optional physical page, and exact
top-level properties in `match`. A pointer is an item-relative RFC 6901 path
(for example `/value`, `/rows`, or `/cells/0/text`). Choose selectors that identify
the same semantic target across runs; item IDs can change when extraction order
changes, and matching on the expected value itself can hide wrong extra values.

Rows from selected items are concatenated in response order. Each complete row
is one ordered tuple: swapping columns or values between SKUs cannot pass by
preserving a bag of tokens. Multisets retain legitimate repeated rows and report
missing rows, extra rows, and extra duplicate copies. Row order is additionally
checked by default; `ordered: false` disables only that check. Fields similarly
retain multiplicity. Exact JSON types and whitespace matter. A missing pointer
is different from an explicit null. Empty table expectations require a matching
item with an explicit empty array; no matching output does not silently pass.

## Reading the report

- `evidence`: item IDs, source labels, physical geometry or declared logical
  coordinates, page completion/count, and table-cell reference **presence**.
  This is not independent pixel verification or a full sidecar/link validator.
- `routing`: validates the existing `p08-release-confidence-v1` categorical
  sidecar and retains public warnings/concerns. An absent sidecar is
  `unobserved`, an invalid one is `invalid`; both have null decision/flag state.
  `has_review_signals` still records concerns when the sidecar is absent.
  No warning, OCR confidence, or table score is promoted into an acceptance.
- `quality`: exact reviewed check results. No expectations means `unevaluated`.
  `checked_claims_pass` means only those claims passed, not that the document is
  correct. Missing/extra/duplicate counts identify concrete value evidence.
- `routing_evaluation`: distinguishes flagged errors from unflagged errors and
  flags without errors in the checked claims. The latter is a false-positive
  **candidate** only for reviewer-declared `complete_for_case` coverage.
- `comparison`: lists independently `corrected`, `harmed`, `still_failing`, and
  `preserved` check IDs. A net improvement cannot hide damage to previously
  correct output. Absent candidate/ground truth is not a successful correction.

There is deliberately no composite score, confidence probability, automatic AI
escalation, default-zero cost, or production-readiness claim. Synthetic tests
include accepted-but-wrong numbers, column swaps, row/field duplication,
false-positive candidates, missing evidence, source drift, and fallback damage.

The local `tmp/backend-fidelity` run covers only a sample PDF and one generated
image; it cannot establish general accuracy or routing quality on real customer
documents. Grow the reviewed corpus and separate document families before using
these measurements to choose production escalation thresholds.
