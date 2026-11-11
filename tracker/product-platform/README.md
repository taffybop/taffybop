# TaffyBop product development phases

The [PX parse and extract plan](../parse-extract-v1/README.md), created on
2026-11-11, is now the active product backlog. This PP document is retained as
historical planning; do not resume it instead of the PX status and handoff.

Updated: 2026-11-04  
Status: Deferred by the parsing-only scope decision on 2026-11-04  
Current work: barebones LlamaParse prototype; see the [project README](../../README.md)

The broader phases below are retained as future planning. They are not the
current implementation backlog. The active scope is upload, three LlamaParse
modes, polling, and original output/export, validated locally. Extraction,
persistent libraries, routing, workflows, and deployment are deferred.

Build one workspace that accepts documents, preserves their structure, extracts
requested fields and tables, and lets users inspect the source before exporting.
Develop and validate locally. Deployment follows the completed local phases and
remains deferred.

This product roadmap uses `PP` story IDs. The existing parser phases, completion
records, exceptions, defects and benchmark evidence retain their original meaning.
This roadmap does not restart or relabel them.

## Scope and first usable outcome

The first usable slice is a PDF or image containing a table, submitted through
the UI or API, processed as a saved job, inspected beside its source, exported
as CSV and original JSON, and reopened after a browser refresh. Phase 2 adds
custom extraction schemas and separately versioned corrections.

Initially qualify PDF, PNG and JPEG inputs. Preserve existing supported input
formats and `/v1/parse` behavior; an existing format does not automatically gain
a product quality claim. Tables and business fields are the initial extraction
tasks. Handwriting, equations, charts and diagrams receive separate qualification.

Upload and API ingestion share one source contract. Add public HTTPS URLs in
Phase 4. Email and cloud connectors can later feed the same contract; their
integration and operational checks require separate stories.

Transformations, workflow builders, outbound business actions, arbitrary code
execution, subscription checkout and deployment are outside the local product
phases. Provider usage accounting is included because it is needed to evaluate
cost and enforce budgets.

## Phase outcomes

| Phase | Outcome | Dependencies | Exit condition | Status |
| --- | --- | --- | --- | --- |
| PP0 Contracts and baseline | Supported tasks, fixed UI behavior, reviewed corpus, baseline and primary extraction-engine decision | Current source and existing fixtures | Contracts and task coverage are explicit; reviewed baseline and engine evidence are recorded; family-specific acceptance rules are frozen | Planned |
| PP1 Persistent parsing | Document intake, durable runs, current parser adapter, source preview and JSON/CSV export | PP0 | Real PDF/image flow survives refresh and worker restart; exported data matches the selected backend result; v1 remains compatible | Planned |
| PP2 Extraction and review | Versioned schemas, a real extraction engine, source-backed values, review revisions and exports | PP1 and PP0 engine decision | Fields and whole rows meet declared rules; missing/ambiguous values remain explicit; edits do not overwrite original output | Planned |
| PP3 Measured fallback | One additional provider, bounded routing and durable usage accounting | PP2 | Intended failures improve without new critical harm; call, time and spend limits work; review burden and unflagged errors are measured | Planned |
| PP4 Specialist tasks and sources | Separately qualify handwriting, equations, one chart family, basic diagrams and URL ingestion | PP3 | Each enabled task has its own reviewed evidence and truthful unsupported behavior; unqualified tasks stay disabled | Planned |
| PP5 Local product qualification | Integrated browser/API checks, identity and retention controls, failure recovery and operating limits | PP1–PP4 for enabled capabilities | Local acceptance set and applicable regressions pass on an identified revision; failures and exclusions are explicit | Planned |
| Later Deployment | Publish the qualified application and validate hosted behavior | PP5 and hosting access | A separate deployment plan, smoke checks and rollback are executed | Deferred |

The first locally usable milestone is PP1. PP2 adds the complete schema extraction
and correction journey. PP4 is evaluated task by task: one failing specialist
must not silently disable safeguards or be presented as supported. Any deliberate
scope deferral is recorded before the local release candidate is accepted.

## Working documents

- [Product and architecture design](design.md): modules, API boundaries, records,
  fixed Studio layout and result semantics.
- [Ordered development backlog](backlog.md): small stories, dependencies and
  concrete checks. Estimates are complexity points, not calendar promises.
- [Benchmark and failure policy](benchmark-policy.md): source truth, held-out
  cases, routing decisions and how failures change the implementation.
- [Phase 0 start checklist](phase-00.md): existing inputs, remaining decisions
  and the first story's readiness record.

## Implementation discipline

Work in the current repository and preserve existing dirty changes. Keep one
implementation story in progress. Before starting a story, complete its
readiness record: bounded scope, inputs, acceptance, checks, contract impact,
feature controls, rollback and measurements. Split a story if it exceeds five
points or introduces more than one independent unresolved algorithm.

Use the current session's authorization. These documents add no new approval
step for already authorized reversible work, and grant no deployment permission.
Existing applicable parser delivery and fixture-use rules remain in force.

A story is Done only when its implementation and declared checks are complete,
with evidence attached to the actual revision. Creating this plan completes no
runtime story or benchmark gate. Record unexecuted checks as `not_run`.

## Access and dependencies

Planning and existing local fixture inspection need no additional access.
PostgreSQL and a writable artifact directory are needed for PP1. The primary
engine experiment may require a local model or an external provider account;
credentials and a finite budget are required before any paid experiment. This
dependency can arise in PP0/PP2, before fallback work in PP3. Keep keys out of
documents and browser code.

Browser validation is required in PP1, PP2 and PP5. Cloud/email accounts are only
needed when their connectors are scheduled. Hosting access is only needed for
the deferred deployment phase.
