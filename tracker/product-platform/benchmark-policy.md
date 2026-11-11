# Product benchmark and failure policy

Status: Evaluation policy for the proposed product phases  
New runtime measurements in this planning package: not_run

Benchmarking begins in PP0 and accompanies every capability change. Parser
accuracy, schema extraction, routing effectiveness and UI fidelity are separate
questions. A successful HTTP response or valid JSON answers none of them alone.

## Source truth and splits

Each case identifies original source bytes/hash, permitted use, family, task,
source-visible evidence, expected values/relationships, critical claims, coverage
and allowed abstention. Expectations are authored from the source, never copied
from a candidate response. Fully reviewed tasks and selected-claim checks remain
separate populations.

Keep development and held-out qualification sets separate. Put alternate renders,
scans and closely related layouts of the same document in one split. Existing
fixtures used for fixes are regression/development inputs, not newly unseen test
cases. If a held-out failure becomes a development case, record the move and
replenish/version the held-out set before claiming new independent qualification.

Retain existing governed corpora and their custody rules. The
[offline evaluator](../../tests/benchmarks/routing_evaluation.md) checks saved
responses and declared claims; its `--fail-on-quality` flag does not establish
provider/routing effectiveness or release readiness.

## Measures by task

| Task | Measure | Failure examples |
| --- | --- | --- |
| Text and structure | Reviewed word/character errors, omissions, order and page coverage | Missing paragraph, damaged number, reordered columns |
| Tables | Cell values plus complete-row correctness, headers/spans and duplicate multiplicity | Right tokens assigned to the wrong SKU, lost row, invented merged cell |
| Schema fields | Exact/typed value precision and recall, required-value coverage and evidence correctness | Wrong date selected, missing value replaced with zero, unsupported citation |
| Forms and handwriting | Field/transcription accuracy and, only where supported, marked-control state | Checkbox inferred from unrelated text, ambiguous handwriting accepted |
| Equations | Symbol/structure fidelity, parseable notation and rendered comparison | Wrong exponent, changed sign, malformed fraction; compiling alone is insufficient |
| Charts | Values within source-justified tolerances, series/axis/unit association | Log axis treated as linear, swapped series, guessed numeric values |
| Diagrams | Node/edge precision and recall, direction and label association | Invented connection or reversed arrow |
| Product UI and exports | Result/artifact identity, value parity, source association and selected revision | Displaying a different run, hiding partial pages, exporting stale edits |

Report counts and denominators per family. Record accepted-output errors,
automatic acceptance coverage, review/abstention rate and successful reviewed
completion separately. Routing everything to review cannot satisfy a minimum
automatic-coverage requirement or demonstrate extraction improvement.

For timing, distinguish queue wait, processing and end-to-end time. Use comparable
environments, configuration, warm/cold conditions and timing boundaries. Report
observed p50/p95 with sample counts where meaningful. Cost includes attributable
attempts and retries; unknown charges remain unknown.

## Setting acceptance rules

PP00-04 freezes a rule set per supported task family before candidate qualification:
source/task population, critical claims, quality/error ceiling, minimum successful
coverage, maximum review burden, latency/concurrency boundary and cost ceiling.
Numeric targets must be justified by the baseline and intended task. Unset rules
mean the family is unqualified, not automatically passing.

Regardless of those targets, no known critical wrong value may silently pass on
the acceptance set. Unsupported content is explicit. A candidate must not add
critical harm to previously correct controls. Every result preserves the source,
version and quality scope needed to interpret its claim.

## When another provider is justified

First reproduce the failure and determine whether it is source quality, OCR,
layout/table reconstruction, semantic field selection, validation or presentation.
An additional OCR engine will not fix a frontend mapping error. A model experiment
must name the failure class, supported input, result contract, cost limit and
comparison method before calling the provider.

Compare the same reviewed cases with and without the candidate route, including
unflagged errors and already-correct controls. Report rescued, harmed, still
failing and preserved claims separately. False-positive routing estimates need
fully reviewed tasks; partial truth produces candidates, not definitive counts.
Enable a route only when it improves its intended failure class, adds no critical
harm, meets the frozen operating limits and preserves honest unresolved outcomes.

## Failure to implementation loop

1. Preserve the failed source, raw response, configuration and reproducible command.
2. Identify the first incorrect boundary: intake, parsing, extraction, validation,
   routing, storage or UI/export. Link the failure to its owning story/code area.
3. Add a source-grounded regression with relevant positive variants and negative
   or ambiguous controls. Follow the existing
   [generic remediation policy](../functional-fidelity-defects/generic-production-policy.md).
4. Change the responsible implementation. Do not add filename/document-specific
   exceptions, weaken truth or hide failures in presentation.
5. Rerun affected cases and bounded previously passing controls. Record new harm
   separately; a net gain cannot conceal damaged correct output.
6. Qualify the candidate on the held-out set under the frozen policy. If it fails,
   revise the approach, keep the previous route, or explicitly narrow support.
   Preserve unsuccessful attempts and any remaining review requirement.

## Phase evidence

| Gate | Required evidence |
| --- | --- |
| PP0 | Contracts, source inventory, split/version, raw baseline, failure list, actual primary-engine experiment and frozen per-family rules |
| PP1 | Durable document/parse identity; restart and idempotency checks; browser/API/export agreement; existing v1 compatibility |
| PP2 | Actual schema consumption; source-backed field/row evaluation; immutable original and reviewed revision; truthful missing/ambiguous behavior |
| PP3 | Baseline/candidate routing comparison, rescued/harmed counts, acceptance/review coverage, usage reconciliation and budget/deadline checks |
| PP4 | Separate support and qualification record for every enabled specialist/source adapter |
| PP5 | Integrated local browser run, identity/retention checks, recovery and resource limits, revision-specific regression and rollback evidence |

Record `not_run`, missing measurements, excluded cases and partial coverage
explicitly. Reuse focused checks during a story; run applicable broader regression
and product qualification at phase boundaries. This policy does not retroactively
turn deferred historical hardening checks into passes.
