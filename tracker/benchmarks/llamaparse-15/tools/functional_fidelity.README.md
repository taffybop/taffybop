# Functional-fidelity analyzer

`functional_fidelity.py` compares retained artifacts. It does not invoke a
parser, mutate parser evidence, or measure runtime resources.

## Artifact contract

For each case `<case-id>` beneath a run directory:

```text
llamaparse/<case-id>/reference.md
llamaparse/<case-id>/reference.json
llamaparse/<case-id>/pages/page-<N>/rendered-dom.json
llamaparse/<case-id>/pages/page-<N>/rendered.png
service/<case-id>/response.md
service/<case-id>/response.json
service/<case-id>/pages/page-<N>/rendered-dom.json
service/<case-id>/pages/page-<N>/rendered.png
```

The candidate root defaults to `service`. Pass `--service-dir service-post-fix`
to select a sibling artifact set beneath the run, or pass an absolute/explicit
relative path. Paths are resolved before the immutable-root guard, including
symlink aliases.

When an affected PDF was rerun through LlamaParse after a correction, pass
`--reference-selection <json>`. The selection file maps each case ID to an
immutable sibling reference root beneath the run; unlisted cases continue to
use `llamaparse/`. Absolute and parent-escaping roots fail closed.

Rendered DOM JSON is `{ "page_number": N, "html": "...", "text": "..." }`.
If `service/run.json` exists, its HTTP status/content-type records are included
and a non-200 response is recorded as a public API failure rather than compared
as document text.

## Run

```bash
.venv/bin/python \
  tracker/benchmarks/llamaparse-15/tools/functional_fidelity.py \
  tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813 \
  --service-dir service-final-20260813 \
  --reference-selection \
    tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/reference-selection.json
```

Build the fail-closed artifact manifest after capture:

```bash
.venv/bin/python \
  tracker/benchmarks/llamaparse-15/tools/build_functional_fidelity_manifest.py \
  tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813 \
  --service-dir service-final-20260813 \
  --reference-selection \
    tracker/benchmarks/llamaparse-15/runs/functional-fidelity-20260813/reference-selection.json
```

The manifest binds all source PDFs, LlamaParse jobs/raw Markdown/full JSON/UI
DOM and PNG captures, public-service HTTP Markdown/full JSON, and Clearleaf UI
DOM captures by SHA-256. It fails closed unless all 15 cases and 30 pages are
complete, every public response is HTTP 200, service Markdown is byte-exact to
canonical JSON Markdown, and every source is within the 20 MiB upload limit.
Snapshot media types are detected from file signatures; an upstream filename
extension mismatch is retained and reported rather than silently normalized.

Outputs are written only under `<run>/comparison`:

```text
comparison/summary.json
comparison/report.md
comparison/<case-id>/evidence.json
```

Use `--cases ...` for a bounded rerun, `--output-dir` for another derived-output
location, and `--fail-on-discrepancy` for a release gate. The tool refuses an
output directory inside either resolved parser artifact root.

## Interpretation

- `match`: no projected functional or user-visible difference.
- `acceptable_difference`: only reviewed-compatible or harmless formatting
  signals remain.
- `discrepancy_found`: at least one functional regression or unresolved manual
  review signal remains. Missing UI evidence may coexist with this status.
- `pending`: capture/evidence is incomplete and no functional comparison has
  failed yet.
- `fixed`: a clean rerun plus an optional hash-bound resolution ledger proves a
  previously recorded discrepancy is absent from the current four raw outputs.

Every discrepancy includes output type, physical page(s), severity,
classification, expected/actual projections, reproducible evidence, the
existing gap/story owner, its dedicated test anchor, and a focused acceptance
criterion. Tables retain complete logical matrices, span records, row-order
signals, and individual differing cells. Rendered comparisons retain semantic
tag/text/link/table projections, layout-class counts, PNG identity/dimensions,
and pixel metrics when both snapshots exist.

The analyzer is deterministic: it emits no timestamps, uses sorted JSON, and
derives stable discrepancy IDs from case/category/page/evidence content.

Exact JSON envelope parity is not assumed. Raw schema paths/types remain in the
machine evidence, while component decomposition or nesting-only differences are
reported as acceptable schema differences and semantic content/order is tested
separately. LlamaParse `table` items carrying a `chart` region label are compared as
visual models rather than double-counted as business tables. Service
`page_index` is the physical page association; printed labels are compared on a
separate projection. Non-scanned visual OCR aggregation is explicitly a
`review_required` proxy, not an accepted difference or spatial source truth.
The generated report records these and the
other interpretation limits in a dedicated section.

## Resolution ledger

`--resolution-ledger <path>` accepts a JSON ledger. A resolution is reported
only when the ledger's four hashes equal the current retained raw artifacts:

```json
{
  "cases": {
    "case-id": {
      "prior_discrepancy_ids": ["FID-CASE-ID-..."],
      "validated_artifact_sha256": {
        "reference_markdown": "...",
        "reference_json": "...",
        "candidate_markdown": "...",
        "candidate_json": "..."
      },
      "code_changes": ["app/path.py: description"],
      "validation": ["focused test command", "fresh raw/UI rerun"],
      "resolved_discrepancies": [
        {"prior_id": "FID-CASE-ID-...", "category": "api_parse_failure"}
      ]
    }
  }
}
```

A clean case becomes `fixed`. If unrelated discrepancies remain, its status
stays `discrepancy_found` while the hash-validated resolution evidence is
reported separately.
