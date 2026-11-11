# Phase 0 start checklist

Status: Ready to begin PP00-01 design review; no benchmark run is complete here

Phase 0 makes development decisions testable before changing product behavior.
Its outputs are finalized contracts, reviewed task coverage, a fresh local
baseline, an actual primary extraction-engine experiment and explicit acceptance
rules. See the [ordered backlog](backlog.md).

## Available inputs

| Input | Current use | Boundary |
| --- | --- | --- |
| [Parser API](../../app/api.py) and [result models](../../app/models.py) | Existing synchronous parse and source/evidence contract | They do not provide a persistent schema-extraction platform |
| [Backend Studio](../../frontend/app/backend-workspace.tsx) | Existing source/result inspector | Reuse without treating HTTP success as accuracy |
| [Synthetic invoice fixture](../../tests/fixtures/invoices/README.md) | Authored source plus PDF/PNG, repeated SKU, wrapped descriptions and linked numeric columns | PDF/PNG are siblings of one underlying source; selected table checks are not broad invoice coverage |
| [Source JSON](../../tests/fixtures/invoices/source.json) | Independent authored invoice values | Never replace it with a parser response |
| [PDF expectations](../../tests/fixtures/invoices/supplier-repeat-sku.pdf.expected.json) and [PNG expectations](../../tests/fixtures/invoices/supplier-repeat-sku.png.expected.json) | Existing exact table and numeric checks | Validate hashes/coverage before reuse; do not infer full schema truth |
| [Routing evaluator](../../tests/benchmarks/routing_evaluation.md) | Audits saved responses and paired reviewed claims | Does not call providers or qualify routing by itself |
| [LlamaParse corpus](../benchmarks/llamaparse-15/README.md) and [defect queue](../functional-fidelity-defects/README.md) | Existing governed evidence and failure ownership | Preserve historical manifests, execution rules and incomplete claims |

## PP00-01 readiness record

Story points: 3  
Dependencies: None  
Status: Ready  
Scope: Review and finalize product contracts and fixed screen behavior  
Non-scope: Runtime code, model calls, database installation, deployment and benchmark claims

| Readiness item | Decision |
| --- | --- |
| Scope and non-scope | Defined above; output is an internally consistent design |
| Size | Three points; split any runtime experiment into its later story |
| Dependencies | Existing source and agreed product direction are available |
| Acceptance | Walk through all scenarios below; resolve contradictions and record concrete decisions in design.md |
| Checks | Verify internal links, story dependencies and source/API contract references; perform an independent design review |
| Fixtures | Source fixture inventory is available for examples; this story does not process documents |
| Contract impact | Proposed `/v2` resources only; existing `/v1/parse` remains unchanged |
| Feature controls | No runtime flags are changed |
| Rollback | Revert only this planning package's changes if the direction changes; preserve existing work |
| Measurements | Documentation checks only; runtime metrics are `not_run` |

Acceptance scenarios: parse-only export; selected-table CSV; schema-only rerun
reusing a parse; partial pages; required-but-missing field; ambiguous source value;
human correction and original export; concurrent edit; duplicate submission;
provider unavailable or budget exhausted. Each must have an unambiguous state,
authoritative result and source/revision identity.

## Remaining Phase 0 work

- [ ] Complete PP00-01 review and record the final contract decisions.
- [ ] Register development cases with hashes, rights, task coverage and critical claims.
- [ ] Add independent held-out documents; keep render/layout siblings together.
- [ ] Cover clean text, native/raster tables, simple forms and expected failures.
- [ ] Capture fresh real local parser outputs and preserve the known failures.
- [ ] Run a bounded real primary-engine experiment for the requested field schema.
- [ ] Record engine location, required access, limits and observed usage.
- [ ] Freeze family-specific quality, coverage, review, latency and cost rules.
- [ ] Record the PP0 exit decision before starting PP1 implementation.

The repository contains historical saved responses, but this package does not
promote them to a fresh product baseline. New source/output hashes, commands and
measurement records belong to the actual execution record when these steps run.
