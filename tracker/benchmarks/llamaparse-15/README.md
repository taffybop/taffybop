# LlamaParse-15 Benchmark Assessment

Status: Analysis frozen; Phase 0 P00-US01–P00-US10 Done  
Assessment date: 2026-07-28  
Corpus: `benchmark-expertmodeldata/`  
Baseline run: `runs/baseline-20260728-current/`

## Purpose and authority

This package validates 15 LlamaParse benchmark outputs against their source
PDFs, records a reproducible run of the current parser, compares both outputs,
and maps confirmed reusable gaps into the existing delivery tracker.

The rendered source page is the primary ground truth. Native PDF objects are
supporting evidence and can themselves be wrong. The expert output is a
comparison target only where review classifies it as source-grounded; inferred,
unverifiable, and incorrect expert claims are not requirements for our parser.

No source or expert file was modified. No production parser, dependency,
configuration, API, schema, fixture, or test behavior was changed during this
analysis.

## Prospective latency source-of-truth update

The frozen `baseline-20260728-current` timing is our own isolated parser with
networking disabled; it is not LlamaParse service latency and is non-operative
for unfinished-phase latency acceptance. Effective 2026-08-08, the sole
latency benchmark for Phases 04–08 is the authenticated
[`LlamaParse latency reference v1`](latency-reference-v1.md), with its
machine-readable [job ledger](latency-reference-v1.json) and controlling
[`source-of-truth decision`](../../decisions/2026-08-08-llamaparse-latency-source-of-truth.md).
Historical local runs remain immutable quality/resource diagnostics only.

Subsequent approved tracker execution completed the test/reporting-only
P00-US01 contracts and catastrophe source-truth P00-US02, then captured the
five-run P00-US03 catastrophe reference baseline without changing these frozen
analysis artifacts or production behavior. P00-US03 passed independent review.
All 15 triplets and derived annotations are now approved as public and
redistributable with no exceptions. On 2026-07-29, the requester approved the
bounded P00-US04–P00-US10 registry/claim/control/runner split. The new portable
P00-US04 passed readiness, all implementation gates, and independent review
and is Done. P00-US05 passed Definition of Ready 10/10, all implementation
gates, and independent review and is Done. The requester approved the corrected
71/210 denominators. P00-US06 registered all 71 Batch A rows, passed every
gate and independent review, and is Done. P00-US07 registered all 76 Batch B
rows, passed every gate and independent review, and is Done. P00-US08
registered all 63 Batch C rows, closed the 210-claim corpus, passed every gate
and independent review, and is Done. P00-US09 registered all 25 owners, 100
roles, and 109 case-gap rows, passed every gate and independent review, and is
Done. P00-US10 then retained a new strict 15/15-case, 30/30-page offline
baseline, preserved all reviewed masks, emitted 12 separate reports, and
passed every gate and independent review. Phase 0 is complete; no later phase
has started.

## Results at a glance

The current all-15 functional-fidelity execution is retained at
[`runs/functional-fidelity-20260813/`](runs/functional-fidelity-20260813/).
Its [consolidated comparison](runs/functional-fidelity-20260813/consolidated-functional-fidelity-report.md)
and [machine comparison](runs/functional-fidelity-20260813/comparison-final-source-grounded-v2/report.md)
bind the newest per-case Agentic LlamaParse outputs, final public-service JSON/Markdown,
and 30-page rendered-UI DOM evidence. It is **not release ready**: the
source-grounded disposition is 3 fixed, 1 acceptable difference, and 11 with
at least one remaining functional gap. The conservative machine comparator
continues to show signals on all 15 because it deliberately compares every
surface before source adjudication. Fixed clusters are retained separately
from independent open findings, and source-contradicted or model-inferred
baseline content is classified as an acceptable difference.

The run's [artifact manifest](runs/functional-fidelity-20260813/artifact-manifest-final-source-grounded-v2.json)
independently hash-binds all 15 source PDFs, 15 completed Agentic jobs in the
requested project, 15+15 raw Markdown/JSON reference outputs, 30 LlamaParse
DOM snapshots and 30 visual snapshots, 30 successful public-service HTTP outputs,
and 30 Clearleaf rendered-DOM captures. It also verifies byte-exact service
Markdown/canonical-JSON parity and confirms that every source is below the
20 MiB upload boundary (largest: `uber-earnings.pdf`, 7,584,019 bytes). The
LlamaParse visual downloads contain valid JPEG/JFIF payloads despite their
retained `.png` filenames; the manifest records the detected media type rather
than concealing that upstream extension mismatch.

- 15/15 expected PDF/Markdown/JSON triplets are present and uniquely paired.
- All 15 PDFs open and all 30 pages render.
- All expert JSON and Markdown files are machine-readable.
- All 15 documents completed the fixed current-parser baseline with no
  document-level error.
- Successful execution is not a quality pass: the page reviews identify
  source-grounded text, layout, table, visual-content, and serialization gaps.
- The corpus contains only PDFs and no fully scanned case. Direct-image,
  image-only-PDF, and Office semantic twins are required before M5 can pass.
- All 15 triplets and derived annotations are approved public/redistributable
  for workspace, repository, benchmark, and CI use with no exceptions.
- The corrected executable denominators are 15 cases/30 pages/45 artifacts,
  210 reviewed claims, and 25 gap owners/109 case-gap rows.

## Assessment index

- [Validated corpus inventory](manifest.json)
- [Corpus validation report](corpus-validation.md)
- [Expert-output validation](expert-output-validation.md)
- [Current-parser baseline](baseline-summary.md)
- [Canonical LlamaParse latency reference](latency-reference-v1.md)
- [Canonical latency job ledger](latency-reference-v1.json)
- [Central gap register](gap-register.md)
- [Gap-to-story matrix](gap-to-story-matrix.md)
- [Milestone plan](milestone-plan.md)
- [Recommended execution order](execution-order.md)
- [Phase impact summary](reports/phase-impact-summary.md)
- [Backlog update summary](reports/backlog-update-summary.md)
- [Per-case reviews](cases/)
- [Immutable baseline artifacts](runs/baseline-20260728-current/)

## Review status vocabulary

Important expert elements use these statuses:

- **Verified** — directly supported by visible or native source evidence.
- **Partially verified** — only the identified subset is source-supported.
- **Not independently verifiable** — plausible, but the retained source does
  not expose enough evidence to prove it.
- **Incorrect** — contradicted by the rendered source or source objects.
- **Potentially inferred** — a model or reconstruction appears to have supplied
  content beyond literal source evidence.

For chart values and diagram relationships, the case report also records
whether evidence is explicitly printed, derived from vector geometry, estimated
from pixels, inferred by a model, or unknowable.

## Reproduction boundary

The exact environment, fixed settings, timestamps, source-tree hash, dependency
versions, output hashes, latency, and peak RSS are retained in
[`run-metadata.json`](runs/baseline-20260728-current/run-metadata.json).
[`command.txt`](runs/baseline-20260728-current/command.txt) records the baseline
command. Audit and comparison tooling is under [`tools/`](tools/).

Reruns must use a new immutable run directory. They must never overwrite the
expert files or this baseline.

## Approval boundary

The frozen assessment changed planning evidence only. Authorized Phase 0
test/reporting work has since completed P00-US01 through P00-US03, including
independent validation of the isolated reference evidence. Parser-quality
behavior work remains outside this boundary.
