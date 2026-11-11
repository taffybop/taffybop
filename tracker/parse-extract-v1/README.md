# TaffyBop parse and extract implementation plan

Updated: 2026-11-11  
Scope: Active product plan requested in the current conversation  
Current phase: PX1 in progress; PX1-04 local implementation verified; live qualification gate next  
Deployment: Deferred until the local phases are complete

Build a small document workspace that parses PDFs and images, extracts fields
described by the user, saves documents and extraction templates, and returns
the same authoritative results through the UI and API. Use LlamaParse for
parsing and an independently selected LLM for extraction. Use the LlamaExtract
workspace as a visual reference; TaffyBop owns the data, schemas, execution,
validation and review flow.

This is the active product backlog. The older [PP roadmap](../product-platform/README.md)
is an archived proposal. Existing parser, LAT and fidelity-defect records keep
their own scope and status. These PX phases do not mark any legacy work complete.

## Documents to read

- [Conversation summary](CONTEXT.md): decisions, earlier directions, costs and boundaries.
- [Product design](DESIGN.md): screens, modules, records, API and job behavior.
- [Current status](STATUS.md): verified baseline, completed work, checks and next story.
- [New chat handoff](HANDOFF.md): a ready-to-paste continuation prompt.
- [Frozen PX1 contracts](CONTRACTS.md), [initial evaluation set](EVALUATION.md) and [provider qualification](PROVIDERS.md): PX1-01 implementation records.
- [PostgreSQL and artifact persistence](PERSISTENCE.md): PX1-02 implementation, actual evidence and retained local database commands.
- [Worker checkpoint](WORKER.md): PX1-03 lifecycle, guarded simulated CLI and durable finite allowance.
- [Local routes and library](ROUTES.md): PX1-04 local identity, startup, saved UI/API and actual browser/restart evidence.

## First release scope

- PDF, PNG and JPEG upload through the UI and our API; preserve existing intake limits initially.
- Parsing modes Fast, Cost-effective and Agentic, subject to live provider qualification.
- Fixed document preview and results layout; original parse JSON and text downloads.
- Extraction schemas with field names, supported types, descriptions and required flags.
- Scalars and bounded arrays of objects for repeating rows; explicit missing and ambiguous values.
- Saved documents, immutable template versions, history, review revisions and exports.
- Ownership, durable jobs, shared provider limits, usage accounting and retention enforcement.
- Browser validation locally throughout; hosting preparation and deployment at the end.

Keep ingestion behind a common source interface. Email, URL and cloud-drive
connectors are later additions. General transformations, branching automation,
arbitrary code, outbound business actions, GPU hosting, additional OCR providers,
and universal chart/formula/diagram guarantees are outside this first release.
Here, a saved workflow means a reusable parsing/extraction configuration.

## Phases and completion gates

| Phase | Deliverable | Completion gate | Status |
| --- | --- | --- | --- |
| PX0 Product plan and handoff | Current-state audit, scope, design, ordered backlog and reusable chat context | Documents agree; local links resolve; no runtime completion claims | Complete |
| PX1 Persistent parsing foundation | Database, durable uploads/jobs/results, worker, stable product API and document history | A real PDF and image can be parsed, reopened after refresh/restart, and exported without changing raw output | Local PX1-01 through PX1-04 verified; successful live qualification remains open |
| PX2 Multiuser reliability and usage | Identity, owner checks, shared capacity, recovery, fair scheduling and spending limits | Two users remain isolated; worker/process failures and provider throttling do not create unbounded or duplicate work | Planned |
| PX3 Extraction workspace and templates | Source preview, Build/Results panels, schema editor and saved versions | Schema creation/edit/reload and template reuse work through real backend APIs; unavailable extraction is clearly disabled | Planned |
| PX4 Extraction engine and quality | Qwen candidate adapter, schema validation, evidence, corrections and evaluated fields/rows | Actual model outputs pass the declared task-level gates; UI, API and export agree | Planned |
| PX5 Product limits and local qualification | Storage tiers, retention, own API keys, performance work and complete browser journeys | Tier, deletion, ownership, restart, quality and load checks pass for the enabled scope | Planned |
| PX6 Hosted release | Deployment, live smoke checks, observability and rollback | Local release candidate accepted; correct hosting access and production configuration verified | Deferred |

Each phase is a separate chat-sized workstream. Start with one bounded story;
continue within the requested phase as context allows. A phase may need more
than one chat. At the boundary, update STATUS.md and HANDOFF.md with exact
completed work and the next story. Do not restart the design in a new chat.

## Ordered implementation stories

Story sizes express complexity, not days. Split a story further if it cannot be
implemented and verified as one reviewable change. Dependencies flow from earlier
stories in the phase and the preceding phase's completion gate.

| Story | Size | Work and decisive check |
| --- | --- | --- |
| PX1-01 | 3 | Capture a fresh focused baseline; define versioned document/job/result contracts and provider configuration. Freeze the initial evaluation set and expected source values. Existing raw-response contracts remain explicit. |
| PX1-02 | 5 | Add PostgreSQL migrations and local artifact storage. Persist documents, ownership keys, job intent and immutable results; prove migration, restart and artifact access behavior. |
| PX1-03 | 5 | Run provider work in a separate worker. Add submission intent, provider IDs, polling and terminal-result persistence; record uncertain submissions without automatic recreation. Start with a conservative global limit. **Local implementation verified, including guarded simulation/finite allowance; live execution gated**, see [checkpoint](WORKER.md). |
| PX1-04 | 3 | Add the persistent document list and owned-job API client. **Local implementation verified**: actual uploads/previews, simulated progress/results, original downloads and actual API/database restart reopen. Explicit loopback development identity only; live parse remains unavailable. See [evidence](ROUTES.md). |
| PX2-01 | 5 | Implement production identity/session handling and authorization on every document, job, result and download. Verify two-user isolation; disable anonymous legacy submission in the hosted product profile. |
| PX2-02 | 5 | Enforce provider-wide capacity using database coordination, worker leases and fair per-user scheduling. Prove limits across two workers and restart with accepted provider jobs. |
| PX2-03 | 5 | Add idempotent admission, bounded retries, uncertain-submission reconciliation and cancellation semantics. Verify duplicate requests, 429/402, timeout and crash behavior. |
| PX2-04 | 3 | Add estimated reservations, actual usage reconciliation, user caps and queue limits. Concurrent requests cannot over-admit work; estimates are visibly distinct from provider usage. |
| PX3-01 | 3 | Implement versioned template CRUD and bounded schema validation. Referenced versions cannot be changed by later edits. |
| PX3-02 | 5 | Build the extraction workspace, synchronized field editor/JSON editor and controlled document preview. Save/load uses the backend; illustrative fixtures stay in tests only. |
| PX3-03 | 3 | Implement result states and template/history selection using the agreed API contract. Both static and Next routes resolve correctly. No demo extraction is presented as a real result. |
| PX4-01 | 5 | Integrate the first extraction provider behind an adapter. Run a bounded live sample against parsed text plus schema; persist model, prompt/schema versions, tokens, cost and raw response. |
| PX4-02 | 5 | Validate typed values, nulls, repeated rows and source evidence. Reject document instructions as executable instructions; retain original output and separate human corrections. |
| PX4-03 | 3 | Complete UI/API/export fidelity and schema-only reruns using the saved parse. A changed schema must not trigger a new paid parse unnecessarily. |
| PX4-04 | 5 | Evaluate representative development and held-out cases; compare one challenger where credentials permit. Record stage-specific failures, fixes, review burden, latency and successful-result cost. |
| PX5-01 | 5 | Enforce plan allowances, storage caps, template counts, retention, deletion and restore behavior. Test with an accelerated clock and two users. |
| PX5-02 | 3 | Add hashed, scoped, revocable product API keys, documented async endpoints and per-user admission limits shared with the UI. |
| PX5-03 | 5 | Reduce initial JS, defer previews, bound large JSON rendering and paginate history. Test normal browsing while uploads and jobs run. |
| PX5-04 | 5 | Run the complete local browser/API/quality/recovery acceptance set. Freeze the supported scope, deployment settings and unresolved exclusions. |
| PX6-01 | 3 | Prepare a lean provider-only image, static frontend, migrations, worker, object storage, secret configuration and rollback instructions. |
| PX6-02 | 3 | After the deployment boundary is reached, publish and validate hosted auth, uploads, extraction, retention and recovery. Record the actual deployment identity and operating bill. |

## Benchmarking starts before extraction

PX1-01 registers source documents and independently authored expectations,
captures current behavior, and states which claims each fixture actually tests.
Existing PDF/image render siblings stay in the same split. Historical parser
benchmarks are evidence to inspect, not an automatic pass for this product.

Every later phase runs its focused regression checks. PX4 evaluates extraction
quality; PX5 combines it with browser and load qualification. Use authored,
publicly licensed or explicitly authorized documents for hosted-provider calls.
Begin with a small development set, then target 50-100 independent documents
covering clean/scanned text, tables, forms, contracts and known failures. Do not
claim that this sample establishes universal document accuracy.

Initial release targets for the enabled field families are below. Freeze scoring,
normalization and critical-field definitions before tuning. Report denominators
and per-family results; do not hide a failing family inside a pooled average.

| Dimension | Initial gate |
| --- | --- |
| Typed output | Every accepted response passes the application schema; malformed/truncated output remains failed or review-required |
| Field quality | Target at least 98% normalized exact match on the held-out supported-field set; include missing/ambiguous cases and report abstentions separately |
| Repeating rows | Target at least 95% exact row match plus explicit row-count/missing-row checks; separately qualify each table family |
| Critical mistakes | No unflagged wrong critical values on the release set; any such error blocks that capability until fixed or explicitly removed from scope |
| Evidence and review | Every accepted value has verified source evidence where the source supports it; unsupported evidence and ambiguous values require review |
| Fidelity | UI and exported original data match the selected backend revision; corrections never overwrite the original |
| Reliability | No ownership leaks, lost accepted jobs or automatic duplicate billable submissions in the declared recovery tests |
| Speed | Target LCP <=2.5 s and INP <=200 ms at the 75th percentile; lab checks before launch, field measurements after launch. Measure API, queue and provider time separately |
| Cost | Record actual successful-result cost, retries and review rate; the approximately $6/1,000-page allowance is a planning target, not a guaranteed bill |

These numbers are initial engineering targets for this plan, not measured
accuracy. Human-review outcomes and straight-through coverage are reported
separately: flagging every document for review cannot satisfy an automation claim.

## When a benchmark fails

| Failure observed | First implementation change to investigate |
| --- | --- |
| Wrong or missing parsed text, table structure or reading order | Inspect source and raw parse; change parser configuration or qualify a higher parse tier on the affected cases |
| Correct parse but wrong person, role, date or field | Improve field descriptions, context selection, prompt/schema and extraction validation; compare the extraction model |
| Wrong JSON shape or truncated output | Fix adapter/schema support and output budgeting; use bounded retry only after a known terminal failure |
| Missing, ambiguous or contradictory source value | Return null/needs-review with evidence; do not force a value |
| UI differs from API or export | Fix serialization, revision selection, stale responses or formatting; do not change the model |
| Slow UI, high memory, queue starvation or duplicate jobs | Fix frontend loading, database queries, job coordination or request admission |

For each failure, preserve the source and response, add an independent expected
case, change the responsible layer, and rerun impacted checks plus the held-out
set. Never rewrite expected values to agree with a provider. A repeatedly tuned
holdout becomes development data and needs a fresh holdout before a quality claim.

Add a second OCR provider only when paired tests show a recurring parsing gap
that configuration/tier changes do not resolve economically. Add automatic
fallback only with measured improvement, a maximum number of attempts, a cost
cap and a time limit. Initially use one parser and one selected extractor.

## Access and execution boundaries

No new approval or account access is needed to complete PX0. Reversible local
implementation is already within the user's requested scope. The following
dependencies become relevant when their phase starts:

- PX1: a local PostgreSQL instance or available container runtime, a writable artifact directory, and a locally configured LlamaCloud key for live checks. Never print key values.
- PX2: the selected identity provider's configuration for real sign-in. Test identities are not proof of a production login flow.
- PX3-PX5: working browser control for real local upload, template, result and download checks; prefer the user's existing Chrome session when needed.
- PX4: a server-side extraction-provider key and a finite test allowance. Start with free credits where available; do not upgrade plans or enable automatic paid top-ups as an incidental test action.
- PX6 only: the owning hosting workspace, storage/DNS access and production secrets. Recheck service ownership rather than repeat old account assumptions.

Saved tier limits can be tested locally with assigned plans. Paid checkout is a
separate launch decision requiring chosen prices and payment-account access;
do not present the tier sketches as a launched subscription offering.
