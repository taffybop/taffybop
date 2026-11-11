# Ordered product development backlog

All stories are proposed except PP00-01, which is ready for its bounded design
review. No runtime story or quality gate is complete. Story points estimate
complexity; they are not elapsed-time commitments. Any story that expands beyond
five points must be split before implementation.

Dependencies refer to story IDs; phase gates also apply. A later story starts
only when its dependencies are Done and its own readiness record is complete.

## PP0 Contracts and baseline

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP00-01 Product contracts and fixed screens | 3 | None | Resolve the draft design's records, states, API boundary and screens. Walk through parse-only, table export, schema extraction, missing data, correction and rerun scenarios without contradictory states. | Documentation links and contract consistency; source-to-result walkthrough. See the readiness record in phase-00.md. |
| PP00-02 Reviewed corpus and family coverage | 3 | PP00-01 | Register source hashes, permitted use, family, task, reviewed expectations, critical claims and unsupported cases. Group alternate renders/layout siblings into the same split. | Verify source/expectation hashes; review full rows and evidence; validate split leakage and coverage declarations. |
| PP00-03 Fresh local baseline | 5 | PP00-02 | Capture real parser outputs and reproducible failures on the declared development set. Preserve revision, environment, options and raw bytes. Baseline failures become backlog evidence, not a reason to alter truth. | Existing evaluator on real responses; selected source review; explicit missing measurements. No external provider calls in this story. |
| PP00-04 Primary engine and acceptance rules | 5 | PP00-03 | Test one feasible primary extraction engine on bounded development tasks. Record supported schema subset, source-evidence behavior, limits and observed cost/latency. Freeze per-family targets and held-out decision rules before qualification. | Real execution, including missing/ambiguous fields and repeated rows; no mocked result can qualify the engine. External credentials/budget are prerequisites if a hosted engine is selected. |

## PP1 Persistent parsing

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP01-01 Document and artifact storage | 3 | PP00-04 | Add workspace-scoped document/artifact records, migrations and local storage. Failed uploads leave no usable half-created record. | Hash/MIME integrity; storage failure; workspace access; orphan cleanup. |
| PP01-02 Durable parse runs | 5 | PP01-01 | Add v2 parse submission/status and an atomic leased worker queue. Persist input snapshots, attempts, cancellation and failures. | Duplicate key/same payload returns the same run; changed payload conflicts; worker death and stale publication cannot lose/overwrite results. |
| PP01-03 Existing parser provider | 3 | PP01-02 | Wrap the current parser, persist its exact serialized result and a versioned platform projection, and retain warnings/partial coverage. | PDF/image controls; failure path; existing v1 contract regressions; no equality claim for independently generated volatile timing fields. |
| PP01-04 Documents and persistent Studio | 5 | PP01-03 | Upload, view status, reopen source/result and export original JSON or a selected table as CSV. Fixed tabs render persisted backend output. | Browser upload to export on PDF, scan and known failure; refresh/restart persistence; CSV row identity; raw artifact byte equality. |

## PP2 Extraction and review

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP02-01 Immutable extraction schemas | 3 | PP01-04 | Store versioned schemas and reject constructs outside the declared subset. Existing runs retain the version they used. | Type/nesting/size limits; immutable versions; ownership; reproducible fingerprints. |
| PP02-02 Real primary extraction engine | 5 | PP02-01 | Execute the engine chosen in PP00-04 against a saved parse and schema. Preserve raw replies, field/row evidence and missing/ambiguous states. | Actual-engine fixtures; source references; no reparse for a schema-only change; timeout/cancellation; finite usage when applicable. |
| PP02-03 Field and row validation | 5 | PP02-02 | Check types, business-required values, row relationships, declared arithmetic and evidence. Persist check results and coverage separately from execution completion. | Null versus zero; duplicate rows; swapped values; conflicting dates/units; unsupported values; held-out family evaluation. |
| PP02-04 Extraction setup screen | 3 | PP02-03 | Define fields and repeating records, test the chosen schema and save a version actually consumed by the backend. | Capture the submitted schema/run IDs; displayed values and statuses match API output; invalid schema shows the backend error. |
| PP02-05 Review revisions and selected exports | 5 | PP02-04 | Append corrections/approval against a base revision, keep the original intact and export an explicitly selected revision/table. | Concurrent-edit conflict; idempotent review request; correction/revert history; source link; original byte integrity; CSV/JSON agreement. |

## PP3 Measured provider fallback

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP03-01 One alternate provider | 3 | PP02-05 | Connect one real alternate for a named observed failure class. Map supported evidence into the platform contract. | Actual provider response and usage; unsupported task; invalid response; unavailable service. |
| PP03-02 Bounded routing and usage ledger | 5 | PP03-01 | Select an eligible route with one quality fallback per job. Persist reservations and settlement; keep conflicting candidates. | Local-only denial; budget exhaustion; total deadline; duplicate attempt; unknown timeout billing; zero automatic acceptance from self-confidence alone. |
| PP03-03 Route qualification | 3 | PP03-02 | Compare the frozen baseline/candidate on flagged and unflagged held-out cases. Enable a route only for its qualified task family. | Rescued/harmed/still-failing/preserved claims, accepted coverage, review rate, missed errors, needless calls and observed cost/latency. |

## PP4 Specialist tasks and flexible sources

Each specialist starts with one bounded family. Qualification can expose a need
for a smaller implementation story; adding one adapter is not an accuracy pass.

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP04-01 One handwriting family | 5 | PP03-03 | Qualify transcription or field extraction for a declared handwriting/form family, with source evidence and refusal for unsupported writing. | Reviewed characters/words and target fields; numbers; ambiguous/missing entries; review rate. |
| PP04-02 Printed equation crops | 5 | PP03-03 | Qualify bounded equation images to editable LaTeX with rendered review. Declare handwritten math unsupported until separately qualified. | Notation structure, symbols/subscripts, rendered source comparison and invalid output; no expression execution. |
| PP04-03 One chart family | 5 | PP03-03 | Qualify a declared single-panel bar-chart family into series/values/axes/units and source-based tolerances. | Numeric error, series association, axis calibration and unsupported scales; a description is insufficient. |
| PP04-04 Basic directed diagrams | 5 | PP03-03 | Qualify one simple flowchart family into labeled nodes and directed edges. | Node/edge recall, false edges, direction, label association and ambiguous crossings. |
| PP04-05 Public HTTPS source adapter | 3 | PP03-03 | Ingest a bounded public URL through the same document/run flow with source identity. | Redirect/address revalidation, private-network denial, size/MIME limits, timeout and duplicate-source behavior. |

## PP5 Local product qualification

| Story | Points | Depends on | Deliverable and acceptance | Checks |
| --- | --- | --- | --- | --- |
| PP05-01 Integrated browser acceptance | 5 | PP04-01, PP04-02, PP04-03, PP04-04, PP04-05 | Exercise each enabled capability through upload/API, jobs, extraction, review and exports. Record any explicitly deferred capability before acceptance. | Real network responses and persisted artifact identity; fixed UI states; empty/partial/failure cases; no substitute browser-generated data. |
| PP05-02 Identity and retention boundaries | 5 | PP05-01 | Implement the chosen user/workspace identity boundary and retention/deletion policy needed before shared use. | Unauthenticated and cross-workspace access denied; artifact/export access; deletion invalidates caches; provider keys absent from UI. |
| PP05-03 Recovery and operating limits | 5 | PP05-02 | Verify declared upload, worker, memory, queue, deadline and spending limits at the intended local concurrency. | Restart, cancellation, retry, storage/provider failure and stale lease; no lost terminal result or duplicated known usage charge. |
| PP05-04 Local release candidate | 3 | PP05-03 | Record the exact revision/configuration, supported capability matrix, benchmark results, known limitations and rollback steps. | Applicable existing regressions and local acceptance pass; unresolved required gates remain failures; no deployment performed. |

## Checks and completion records

The Checks column describes tests to select or implement; it does not claim new
test files already exist. Reuse these existing foundations when applicable:

- [Routing evaluator tests](../../tests/benchmarks/test_routing_evaluation.py).
- [Invoice source fixture checks](../../tests/benchmarks/test_synthetic_invoice_fixture.py).
- [Frontend API client checks](../../frontend/tests/document-api.test.mts).
- [Backend-result display checks](../../frontend/tests/backend-result-view.test.mts).
- Existing parser API/schema and impacted story regressions selected after
  inspecting the changed code.

Before each story, record its status, scope, concrete fixtures, acceptance rules,
test commands, API impact, feature controls, rollback and measurements in its
execution record. Afterward attach the exact revision and evidence, identify any
remaining failures, and update its status. Do not mark a story Done from a mock,
an HTTP 200, generated report, successful build or review flag alone.
