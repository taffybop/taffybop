# LlamaParse-15 functional-fidelity comparison

Run: `functional-fidelity-20260813`  
Analyzer schema: `functional-fidelity-comparison-v1`  
Story mapping: `tracker/benchmarks/llamaparse-15/gap-to-story-matrix.md`

This is a functionality/output-quality comparison. It does not make latency, CPU, memory, or exhaustive hardening claims.

## Release readiness

**NOT READY** — 2 functional regression(s), 2 evidence gap(s), 0 accepted/harmless difference(s), and 0 hash-validated resolved discrepancy/discrepancies.

A `pending` case lacks one or more service artifacts or rendered-page captures; it is not a fidelity pass. A `fixed` case requires a hash-bound resolution ledger and a clean rerun.

## Per-PDF status

| PDF | Status | Critical | Major | Minor | Functional | Evidence gaps | Evidence |
|---|---|---:|---:|---:|---:|---:|---|
| `catastrophe-recap.pdf` | **discrepancy_found** | 2 | 0 | 0 | 1 | 1 | [`evidence.json`](catastrophe-recap/evidence.json) |
| `postal-10k.pdf` | **discrepancy_found** | 2 | 0 | 0 | 1 | 1 | [`evidence.json`](postal-10k/evidence.json) |

## Findings

### catastrophe-recap

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | n/a | n/a | n/a | yes | no | 2 |

- `FID-CATASTROPHE-RECAP-80d905db1393` — **critical / functional_regression** — service_api, page(s) 1: The public parse API did not return successful, valid Markdown and JSON outputs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-CATASTROPHE-RECAP-816f0f04c861` — **critical / evidence_gap** — rendered_dom, page(s) 1: Rendered DOM page capture set is incomplete or has unexpected pages. Owner: `GAP-BENCHMARK-002` / `P00-US10`; test: `test_p00_us10_corpus_runner.py`.

### postal-10k

Status: **discrepancy_found**

| Physical page | Page status | JSON text recall | JSON text precision | Sequence ratio | Reference DOM | Service DOM | Findings |
|---:|---|---:|---:|---:|---|---|---:|
| 1 | discrepancy_found | n/a | n/a | n/a | yes | no | 2 |
| 2 | discrepancy_found | n/a | n/a | n/a | yes | no | 2 |
| 3 | discrepancy_found | n/a | n/a | n/a | yes | no | 2 |

- `FID-POSTAL-10K-805dd524ea4c` — **critical / functional_regression** — service_api, page(s) 1, 2, 3: The public parse API did not return successful, valid Markdown and JSON outputs. Owner: `GAP-SERIALIZATION-001` / `P01-US03`; test: `test_p01_us03_canonical_presentation.py`.
- `FID-POSTAL-10K-d6869828e07e` — **critical / evidence_gap** — rendered_dom, page(s) 1, 2, 3: Rendered DOM page capture set is incomplete or has unexpected pages. Owner: `GAP-BENCHMARK-002` / `P00-US10`; test: `test_p00_us10_corpus_runner.py`.

## Validation and resolution rule

Each machine-readable discrepancy contains the expected LlamaParse projection, actual service projection, page/output type, complete table cell evidence where applicable, severity, story owner, acceptance criterion, and a stable reproduction command. Unit-test success alone is insufficient: resolved cases must retain fresh raw Markdown, JSON, rendered DOM, and snapshot evidence. The optional resolution ledger can label a clean case `fixed` only when it binds the current four raw artifact hashes and identifies prior discrepancy IDs.
