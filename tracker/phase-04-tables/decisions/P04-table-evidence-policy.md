# P04 Table Evidence and Custody Policy

Status: Accepted table-evidence policy  
Date: 2026-08-03  
Policy ID: `p04-table-evidence-v1`  
Sidecar version: `1.1`

## Current P04-US01 measurement supersession

The last approved pre-retention mechanics remain
[`P04-US01-external-rss-lane-final-code-amendment.md`](P04-US01-external-rss-lane-final-code-amendment.md)
and the later
[`conditional stage-reachability final-code amendment`](P04-US01-conditional-stage-reachability-final-code-amendment.md).
Their canonical v11 attempt failed closed. The never-approved v12 leased-
identity reservation and all accidental preapproval activity remain historical
evidence. Any future execution is controlled by the pending
[`v13 compact-transport monitor supersession`](P04-US01-v13-compact-transport-monitor-controlled-supersession.md),
subject to exact-byte independent approval and a separately reviewed immutable
one-shot predeclaration. Its embedding lineage is report/projection/paired/
quality `v13`/`v13`/`v12`/`v9`, external attestation `v9`, observer process
`v4`, execution accounting `v3`, and lane wire/protocol/terminal/compact/
runtime `v3`/`v6`/`v3`/`v1`/`v4`. All formulas and gates remain unchanged.

Any later statement in this policy that calls the sealed `v6` parent-thread,
attestation-v1, 65,536-exchange, `v11`, reserved `v12`, or earlier embedding
lineage “current” is historical and superseded. Canonical `v10` and `v11`
remain sealed failures with no final artifact. No current-artifact metrics pass
is asserted.

## Decision and present boundary

Phase 04 table work is a deterministic, local-only, default-off overlay on the
accepted public schema `1.0` and shared IR. It may preserve more source table
evidence, but it must not fabricate a cell, header, span, continuation, or
ownership decision. Existing page-local table items remain the compatibility
projection.

This record freezes the four-story contract so the stories cannot adopt
incompatible meanings later. The P04-US01 oracle, synthetic controls, limits,
and contract checks formed its executable readiness scope; the independently
reviewed package subsequently passed Definition of Ready. The exact hardened
P03-US08 renewal received independent final approval on 2026-08-04. P04-US01
entered In Progress on 2026-08-04 under separate requester authorization. This
decision did not start P04-US02, P04-US04, or P04-US03 and is not itself
completion evidence. Phase 05 remains forbidden without separate explicit
authorization.

## Rollout controls and dependencies

The exact environment controls are:

| Story | Public setting | Environment variable | Default | Required table flags |
|---|---|---|---|---|
| P04-US01 | `parser.tables.span_fidelity.enabled` | `PARSER_TABLES_SPAN_FIDELITY_ENABLED` | `false` | none |
| P04-US02 | `parser.tables.evidence_reconciliation.enabled` | `PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED` | `false` | span fidelity |
| P04-US04 | `parser.tables.candidate_gate.enabled` | `PARSER_TABLES_CANDIDATE_GATE_ENABLED` | `false` | span fidelity and evidence reconciliation |
| P04-US03 | `parser.tables.multi_page_merge.enabled` | `PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED` | `false` | span fidelity, evidence reconciliation, and candidate gate |

The existing story dependencies also remain mandatory: P04-US01 follows
P03-US01; P04-US02 additionally follows P02-US04; P04-US04 additionally
follows P03-US06; and P04-US03 additionally follows P03-US04. A completed
predecessor story is not the same as enabling its runtime flag. Configuration
validation enforces the table-flag chain without silently enabling a flag.

With all four flags false, no Phase 04 candidate collection, normalization,
sidecar, summary, timing, representation, or frontend work occurs. The public
JSON, canonical output, Markdown, ordering, and warnings are the exact
predecessor result. Disabling a story flag removes only that story and its
dependents; rollback never converts retained alternatives into canonical
tables. All flags remain false for production unless separately approved.

## Closed additive public contract

A flag-on page-local table adds one `table_evidence` object. Its exact keys are
`policy_id`, `version`, `scope`, `status`, `table_id`, `candidate_id`,
`page_index`, `grid`, `slots`, `source_objects`, `evidence`, `span_decisions`,
`representation_custody`, `reconciliation`, `gate`, `continuation`, and
`concerns`. Unknown keys fail the affected table closed. `scope` is the ordered
set of enabled story names. `status` is one of `valid`, `unresolved`, or
`structural_failure`. The last three story-owned members are null until their
own flag and readiness contract are active.

The existing public `cells` array becomes authoritative only when this marker
is present. A marked cell has exactly `id`, `row`, `column`, `row_span`,
`col_span`, `text`, `column_header`, `row_header`, `row_section`, `bbox`,
`source`, `page_index`, `evidence_ids`, `source_object_ids`,
`span_decision_id`, and `confidence_dimensions`. Rows and columns are
zero-based strict integers. Spans are positive strict integers. Header fields
record source ownership and must not be inferred from display position.
`confidence_dimensions` has exactly nullable `text`, `geometry`, `structure`,
and `header` values in `[0,1]`; it is not described as calibrated probability.

Each non-null bbox has exactly `x`, `y`, `width`, `height`, and `unit`, uses
finite top-left page coordinates, has positive dimensions, fits its referenced
page, and is source-supported. A missing bbox is legal only with a targeted
concern and cannot satisfy geometry or span evidence.

For the exhaustive Exhibit 7 metric, two source-supported bbox roles remain
separate. The immutable Phase-00 cell `bbox` is the structural
`grid_slot_bbox`: the ruled rectangle that owns one row/column slot. The
flag-on P04-US01 public `cell.bbox` is the selected Docling
`source_content_bbox`: the exact five-key rectangle retained for that explicit
cell's native source content. Exact scoring requires all 30 public rectangles
to match the separately hash-bound content-bbox oracle within the existing
`0.011 pt` numeric comparison slack and independently requires each rectangle
to be wholly contained by its unchanged Phase-00 grid slot. A grid rectangle
cannot be substituted for a content rectangle, and generic containment alone
cannot satisfy the metric. This distinction does not add pdfplumber grid
geometry, reconcile candidates, or authorize P04-US02 behavior.

`grid` has exactly `row_count`, `column_count`, and `cell_ids`. Each slot has
exactly `id`, `row`, `column`, `kind`, `cell_id`, and `covered_by_cell_id`.
`kind` is `anchor`, `explicit_blank`, or `covered`. Anchors and explicit blanks
name one cell and have no `covered_by_cell_id`; covered slots name no cell and
name the covering anchor. Thus an explicit empty source cell cannot be
confused with an absent value created by a span. Slots cover the rectangular
grid exactly once, with no collision or out-of-bounds span.

A Docling source-object record has exactly `id`, `engine`, `object_type`,
`page_index`, `raw_ref`, and `content_sha256`. A pdfplumber recovery source is
the distinct exact `table_word_set` variant with `id`, `engine`, `object_type`,
`page_index`, `raw_ref`, `role`, `target_row`, `target_column`, `words`, and
`content_sha256`. Its engine is `pdfplumber`, its `raw_ref` is null because
pdfplumber supplies no object reference, and its role is `header`,
`body_control`, or `bottom_row`. Each set contains 1–64 exact word records with
`id`, `text`, `bbox`, `font_name`, and `bold`; the bounded retained font name
must independently reproduce the derived bold fact. A table may retain at
most 48 recovery word sets. An evidence record has exactly `id`, `method`,
`dimension`, `page_index`, `bbox`, `source_object_ids`, `confidence`, and
`content_sha256`. Methods are `native_text`, `ocr_text`, `vector_rule`,
`source_grid`, `embedded_grid`, `model_structure`, `recovered_structure`, or
`derived_comparison`. Dimensions are `text`, `geometry`, `structure`,
`header`, `ownership`, or `continuation`. Text transcription and grid topology
are always separate evidence dimensions; table-wide `source=native` cannot
prove a span.

A span decision has exactly `id`, `cell_id`, `claimed_row_span`,
`claimed_col_span`, `emitted_row_span`, `emitted_col_span`, `outcome`,
`evidence_ids`, and `concern_codes`. `outcome` is `supported`, `refused`, or
`ambiguous`. Every claim above one requires independently addressable
structure or geometry evidence. Repetition, blank text, engine preference, or
visual proximity alone is never sufficient. A refused or ambiguous claim
emits unit spans only when explicit independent cells are supported; otherwise
the complete table fails closed rather than being flattened.

IDs are lower-case, domain-separated SHA-256 identities derived from source
SHA-256, physical page index, stable engine/raw references, canonical bbox,
and structural coordinates. Reading order, mutable text, array order, process
hashes, timestamps, and filesystem paths are forbidden ID inputs. Canonical
arrays are sorted by stable ID or documented grid order. A collision or
unstable identity fails the complete affected table closed; no random suffix
is allowed.

For Docling's explicit `data.table_cells`, a safe direct cell reference is used
when the engine supplies exactly one. When the engine supplies no per-cell
reference, the cell remains source-addressable through the table's exact
`self_ref` together with its start/end row and column coordinates and declared
spans. The public source object's `raw_ref` remains the truthful table
reference; no synthetic JSON pointer is invented. Structural coordinates,
source document SHA-256, page, bbox, and table reference remain mandatory ID
inputs. Duplicate structural locators, duplicate or conflicting supplied cell
references, unsafe references, and contradictory end offsets fail the complete
affected table closed. Missing per-cell references never authorize inference
from text or array position.

## Source-bound recovery amendment

Sidecar version `1.1` adds only source support for P04-US01 recovery on an
already selected Docling table. It does not add or compare a pdfplumber table
candidate. `reconciliation`, `gate`, and `continuation` remain null, and no
P04-US02, P04-US04, or P04-US03 decision is authorized.

Header recovery retains one bounded pdfplumber header word set and one
comparison-body word set for every recovered column. Its per-cell
`recovered_structure` header evidence links both sets and the immutable
pre-recovery Docling grid. Replay requires exact cell-text agreement, all
header words to be bold, all comparison words to be non-bold, complete column
coverage, unique geometry, and exact evidence identity, content, confidence,
and links. A source-declared Docling header remains `model_structure`; the two
methods are not interchangeable.

Bottom-row recovery retains one bounded pdfplumber word set per emitted
column and never invents a Docling cell reference. The original Docling grid
source remains committed at its original shape. Recovery evidence separately
commits the predecessor grid, rule version, row pitch, same-line band, column
starts and unique assignments, source word geometry, and emitted unit-span
coordinates. Each recovered cell's text and bbox are reproduced exactly from
its retained words and have independent text, geometry, and structure
evidence. Missing columns, ambiguous assignment, duplicate geometry, malformed
typography, unsupported cadence, or any identity/content/link disagreement
refuses the recovery atomically.

Recovery word order is canonical physical geometry order, never incoming
array order. Word and source identities are bound to source SHA-256, physical
page, stable table context, structural target, bbox, role, and rule domain;
mutable text, font names, process state, and array indexes are excluded from
stable identity inputs but included in the separately verified content
commitment. Every retained source and evidence record must be reachable from
one exact generated semantic fact, every expected record must be present once,
and extras fail the affected table closed.

## Representation contract

Validated marked cells and slots are the single semantic grid. `rows`, `value`,
HTML, Markdown, and CSV are generated from that grid by one serializer. They
are never parsed back to infer cells.

`representation_custody` has exactly `serializer_policy_id`, `grid_shape`,
`cells_sha256`, `rows_sha256`, `html_sha256`, `markdown_sha256`, and
`csv_sha256`. Hashes use UTF-8 canonical JSON or exact UTF-8 serialized bytes.
For the cells and rows hashes, canonical JSON recursively replaces every
strict finite integer or float (booleans excluded) with
`{"$p04_f64":"<hex>"}`, where `<hex>` is the 16-character lowercase
big-endian IEEE-754 binary64 encoding; both signed zero values use positive
zero. Object keys are ASCII schema keys sorted lexicographically, JSON is
compact UTF-8, and an input object containing the reserved `$p04_f64` key
fails closed. This representation is identical in Python and JavaScript and
does not depend on either runtime's decimal-number formatting.
Rows/CSV contain the rectangular anchor matrix; covered slots are empty while
an explicit blank remains identifiable through cells and slots. HTML/Markdown
preserve supported `rowspan`, `colspan`, header scope, and escaped multiline
content. CSV is not claimed to encode span semantics. Any shape, cell-text,
header, span, or hash disagreement fails the table closed before commit.
Column-owned HTML/Markdown header cells serialize as `<th scope="col">` and
row-owned header cells as `<th scope="row">`; a bare or incorrectly scoped
`th` is not exact representation parity.

Captions, source notes, form fields, and visual captions remain separate
owners. They may reference the stable table ID but never enter a cell or table
markup. Frontends render a marked grid from validated cells with escaped React
content; they do not trust or inject table HTML, and an older text-run overlay
cannot replace a custodied cell at render time. An invalid or unresolvable
marked table falls back to escaped predecessor/canonical text without semantic
reconstruction.

## Resource, deadline, and diagnostic bounds

Inclusive P04-US01 readiness limits are 4,096 rows, 256 columns, 65,536 cells
and slots, 16,384 UTF-8 bytes per cell, 64 concerns per table, and 64 oracle
tables. The later story ceilings are: 128 candidates and 64 candidate clusters
per page, 16 retained alternatives per cluster, 8,192 comparisons per page,
131,072 comparisons per document, 512 continuation pairs per document, and 32
page-local tables per derived continuation. A marked table sidecar is at most
8 MiB; all Phase 04 sidecars are at most 64 MiB per document. Each record has
at most 64 evidence IDs and 64 source-object IDs; IDs/codes/raw references are
at most 256 UTF-8 bytes. Portable evidence paths are also at most 256 UTF-8
bytes, use canonical forward-slash workspace-relative form, contain no `..`,
empty, dot, backslash, drive/URI, encoded, tilde, or non-portable ASCII
component, and must remain inside the resolved workspace after following
symlinks. NUL, C0 controls, DEL, invalid UTF-8, and
unbounded diagnostic or metadata strings fail closed; cell text may retain
source line breaks and tabs but no other control characters.

Every readiness denominator `expected` value is capped by its dimension:
4,096 for row quantities, 256 for column quantities, 65,536 for cell/value/
span/header quantities, and 64 for table quantities. A column-span member is
in `[2,256]`, a row-span member is in `[2,4096]`, member count equals the
declared span denominator, and no denominator may evade its cap through its
member array.

The span-fidelity stage has a 0.500-second page and 5.000-second document
deadline. Reconciliation and gating each have a 0.500-second page and
5.000-second document deadline. Continuation scoring has a 2.000-second
document deadline, and total Phase 04 projection has a 10.000-second document
deadline. These are safety ceilings, not performance waivers; the Phase 04
p95 overhead target remains at most 10% and all RSS/output gates remain.
Every table on one physical page consumes the same absolute span-fidelity page
deadline, and all span-fidelity work in the document consumes one absolute
document deadline; neither deadline may be reset per candidate or replay.
Exhaustion rolls the applicable page or document transaction back to its exact
flag-off predecessor rather than exposing a partial overlay or failing an
otherwise parseable document.
For P04-US01 readiness, the executable ceilings are a table-stage p95 overhead
ratio of `0.10`, a maximum-of-five nonnegative enabled-minus-disabled
candidate-window RSS-growth delta of `67,108,864` bytes (64 MiB), `8,388,608`
output bytes per marked table, and `67,108,864` Phase 04 sidecar bytes per
document. Exact-bound observations pass and any maximum-plus-one observation
fails. These ceilings do not replace the paired full-parser, corpus,
correctness, or custody gates.

The controlled latency interpretation names the formula
`p04-us01-paired-nonnegative-additive-table-stage-over-flag-off-wall-v1` and
defines each paired table-stage additive-overhead ratio as
`max(0, enabled_table_stage_seconds - disabled_table_stage_seconds) /
disabled_whole_parser_wall_seconds`. The denominator is the matching positive,
finite flag-off whole-parser wall observation, never the usually tiny flag-off
named-stage union. All five candidate-specific ratios per case remain retained;
p50 and p95 remain empirical inclusive nearest-rank observations and both stay
at the unchanged `0.10` ceiling. Raw signed and nonnegative named-stage deltas
remain retained. Independently, the full-parser p50 and p95 ratios continue to
use `max(0, enabled_wall_seconds - disabled_wall_seconds) /
disabled_wall_seconds` at the same ceiling, so work outside named hooks cannot
be hidden. Zero, negative, boolean, NaN, or infinite flag-off wall observations
fail closed. Both latency clocks stop immediately at successful
`parse_document` return; the RSS parse checkpoint and production-output probe
described next are excluded from latency.

The controlled RSS interpretation in
[`P04-US01-phase04-stage-peak-rss-controlled-supersession.md`](P04-US01-phase04-stage-peak-rss-controlled-supersession.md)
applies the unchanged `67,108,864`-byte ceiling to candidate-window growth
rather than to unrelated cross-worker lifetime high-water variance. In each
worker, `B` is synchronous current RSS immediately before the earliest
P04-owned/first measured outermost hook. Immediately after successful parse
return, the still-running sampler retains `P_parse`, current endpoint
`E_parse`, and normalized self HWM `H_parse`; with the start HWM `H0`,
`G_parse=max(max(0,P_parse-B),max(0,H_parse-H0))`.

The first non-retained `postal-10k` enabled smoke failed closed with no snapshot
or final artifact. Its `1,817`-byte, `28`-line stderr had SHA-256
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5` and
surfaced `child process observed`; that observation remains exact failed
history. Later protected traced reproductions saw no child and instead failed
`first async sample is late`, then internal `sampling cadence exceeded`.
Direct `psutil` `7.2.2` timings established the mechanism: 100 recursive-child
calls measured minimum/p50/p95/maximum `5598292`/`6366604`/`6866666`/`8009000`
ns, `memory_info()` p50 was `2584` ns, and two child calls plus RSS measured
`11151375`/`12825500`/`13876791`/`15760500` ns. The former 10 ms combined
loop was structurally impossible. These failed/traced observations are design
diagnostics, not a canonical pass, and the original child result is not
relabelled.

After the approved two-lane renewal, the standard non-retained `postal-10k`
enabled `fresh_snapshot` smoke exited nonzero and wrote no snapshot or final
artifact. Its stderr identity is exactly `2,046` bytes, `33` lines, and SHA-256
`d66eb3a2e92523decaf073edf95c5f434f8cfbc1bd88a7f5a11e1121b80ea612`.
The protected reproduction exposed a `current_rss` `RuntimeError`; its exact
private-category diagnostic is `Phase04-stage RSS sampling cadence exceeded`.
This remains failed, non-retained evidence and does not relabel the earlier
`b13d0b76880a4282f7657c6f145fd833c9ec2611cb5c658d3acf0580c89a7bc5`
child observation or establish a pass.

The same-worker two-lane/FIFO design and its exact identities below are now
historical. The later, also historical, `v6` evidence design moved continuous
current RSS, recursive-child
observation, FIFO scans, and their monotonic timeline into controller-parent
threads bound to the exact fresh-worker PID/create time and owned private
PGID/SID. The worker supplies self-HWM and full `RUSAGE_CHILDREN` endpoints over
the closed `p04-us01-external-rss-monitor-v1` AF_UNIX protocol. Only after the
worker, monitor threads, sockets, and controller scheduler are cleaned up does
the parent attach `p04-us01-external-rss-monitor-attestation-v1`; raw workers
must retain `null`. The attestation binds controller and worker ownership,
operation sequence and duplex digest, exact scheduler restoration, source and
scope, resource-payload digest, and exact round-trip record custody. It does
not describe the round trip as a second independent measurement.

The monitor socket is the sole measurement `pass_fds` descriptor and is made
and verified non-inheritable immediately in the worker. Worker CLI execution
without that descriptor is forbidden; controller writes and worker requests
share a five-second bound. Controller sampler/child-observer allocations are
outside worker `G`, never subtracted, and provide no credit. The proxy executes
only in the worker and receives zero manual resource credit: PREPARE identity
and START/HWM/rusage setup are pre-`t0` and can affect inherited `B`/`H0`,
intermediate boundary IPC and production-output work are inside `G`, and
FINISH-response decode plus socket close are post-`t1`. The transcript is
aggregate-bounded to `65,536` exchanges and `16,777,216` canonical duplex
bytes; oversized expected counts fail before count-sized allocation. Failed
ABORT is terminal, while FINISH-accepted cleanup may retry close only and is
idempotent. Report/projection/paired/quality schemas are
`v6`/`v6`/`v5`/`v3`; the formula IDs and every ceiling are unchanged. No
canonical campaign or current metrics pass is asserted.

That historical `v6` non-real metrics module passed `322`, with `2` expected
real-campaign skips and `1` known Starlette warning. Three independent reviews
of fixture SHA-256
`955383dd2b9ed4b778623fee652b72850a916713614e39f200cbff234c7cf28f` /
`397444` bytes and test SHA-256
`61a83c0b00e96e168eaf34cfd1a00f2f02a2f9bfbc9a701cb71158ff81080393` /
`281525` bytes each reported `0` Blocking and `0` Major. These results are
contract/review evidence, not a retained real campaign or terminal approval.

A historical, non-retained `postal-10k` enabled smoke passed at wall
`23.843067667` seconds, table stage `1.136875792` seconds, RSS gap `5077708`
ns / `1140` samples, child gap `36056209` ns / `93` samples / `50` boundary
checks, `51` exchanges / `18183` duplex bytes, zero diagnostics, exact
scheduler restoration, and matching records. Its `23920640`-byte absolute
stage increment is observational only, not a paired RSS result or gate pass.

The same RSS sampler, independent child observer, and `B`/`H0` baseline then
remain live while a conservative test-only dual-branch composite records and
releases a bounded streaming
identity of the true parsed result, invokes the exact production callables and
options for `jsonable_encoder`, `ParseResult.model_validate`,
`model_dump(mode="json", exclude_unset=True)`, and a materialized
`JSONResponse` body, releases that body, then invokes the production Markdown
serializer and materializes a text/markdown `Response` body. JSON then
Markdown is solely the composite's measurement order; production selects one
branch per request. This does not claim a literal single-request
production/API operation order, ASGI scheduling, or production
`run_in_threadpool` scheduling. The validated public mapping has distinct
bounded streaming identities after its dump and after both measured branches.
The validated `ParseResult` remains live until after `t1_api`, so its
conservatively retained memory is included in `G`. At final `t1_api`, `P_api`
is the maximum current RSS across the complete window, `E_api` is its current
endpoint, and
`H_api` is normalized self HWM.
`G_api=max(max(0,P_api-B),max(0,H_api-H0))`, and authoritative worker growth is
`G=max(G_parse,G_api)` under
`p04-us01-worker-max-parse-and-output-current-hwm-growth-v3`.

Within the RSS window, only the one released parsed-result pre-projection,
exact-callable per-branch materialization in that measurement-only composite,
ordered synchronous boundaries, bounded streaming identities, and length/
SHA-256 over the existing JSON body are allowed.
`t1_api` occurs immediately after the
Markdown response body and validated-public-mapping post identity. Allocation-
heavy JSON decode/replay, parsed-result post projection/identity, Markdown
UTF-8 hash/parity, and final output-record validation run strictly after
`t1_api`. The final record retains distinct parsed-result before/after,
jsonable-result, validated-public-mapping before/after, JSON body, and Markdown
body identities; nonmutation/parity/media/release/schema/path checks cannot
conflate the parsed result with the jsonable projection. JSON release precedes
Markdown preparation, so both response bodies are not deliberately retained
together. Instrumentation restoration runs after the parse checkpoint while
both observers are armed and before output work; it is included in `G`,
excluded from parser latency, and never subtracted.

The corrected observer has two independent lanes. The RSS lane uses only bound
PID/create-time identity validation plus project-pinned `psutil` `7.2.2`
`memory_info().rss`; it never enumerates children, targets 2 ms, and fails if
its maximum observed gap exceeds 10 ms across the start edge, internal cadence,
or end edge. The child lane makes one recursive `Process.children` observation
per cycle, targets 25 ms, and fails above 100 ms across its independently
retained edges and cadence. A protected two-thread diagnostic recorded child
count `76` with p50/p95/maximum `40004666`/`42270750`/`47250166` ns and RSS
count `985` with p50/p95/maximum `2524625`/`8793625`/`8842125` ns. These
diagnostic timings do not establish a canonical pass.

The baseline tuple completes before recorded `t0`, and both lanes must prove
their first zero-child/RSS observations before production is released. Slow
zero-child checks run outside the RSS lock at `t0`, every outermost hook, the
parse checkpoint, every exact output boundary, and `t1_api`. Each lane retains
and validates its exact source/version, edge offsets, target/hard interval,
maximum gap, count, readiness, completion, and error fields; the exact child
field names are bound in the controlled supersession decision. Existing
`phase04_stage_rss_child_processes_observed` stays strict zero. A missing, late,
early, duplicate, invalid, incomplete, incoherent, nonzero-child, parity/
nonmutation, or join state fails closed.

Every active recursive child scan is now FIFO-serialized and bracketed by an
exact forced-current-RSS `F-C-F` protocol: await a request/completion generation,
perform one recursive child scan, then await a second request/completion
generation. An active logical boundary therefore causes four forced RSS reads
around its two child scans, an independent observer sample causes two, and the
pre-`t0` baseline causes zero. Each continuous read captures the current
generation before reading RSS and acknowledges it only after successful sample
append/timestamp, so a stale in-flight read cannot satisfy a later request. The
cancellation-safe FIFO deque releases between a boundary's first and second
scan, every stop/error/end transition notifies waiters, `finish()` uses a FIFO
barrier, and the lock order remains acyclic.

The superseded same-worker `phase04_stage_rss_sampling_scope` bound those
forced generation handoffs. Its historical exact code custody is
`tests/fixtures/phase_04/tables/metrics.py`
`ec2fa9085d5e2d2929f7b32e30d1afc7fb32f2399048ff518b863f6968963c63` /
`332756` bytes and `tests/performance/test_p04_us01_table_metrics.py`
`9d51bb5ca45aa561c8b9bbbbb5aabc1e1f06f9e323dae64d81fa95be25680129` /
`237378` bytes. Verification retained `458` passed, `2` expected real skips,
and `1` warning; independent focused review passed `17`; the full metrics-file
run retained `278` passed, `2` expected real skips, and `1` warning; and the
four-test race slice passed five consecutive repetitions. Independent review
approved this narrow correction with `0` Blocking and `0` Major findings.

That was a no-waiver measurement correction. Report/projection/paired schemas
then remained `v5`/`v5`/`v4`; both exact formula IDs remained `v3`; RSS remained 2 ms
target/10 ms hard; the child observer remains 25 ms target/100 ms hard; and all
ceilings and non-waived gates remain unchanged. The review is not terminal
story, metrics/custody, or production approval.

Only the exact manifest-bound P04-owned `app/` Python final-code paths are
subject to the static no-spawn guard; it does not attest the full transitive
dependency closure. The complete cumulative `RUSAGE_CHILDREN` fingerprint—
normalized `ru_maxrss` plus every platform-exposed numeric cumulative field—
must be exactly equal before `t0` as part of the completed baseline and at
`t1_api`. A nonzero baseline is permitted because predecessor OCR/Tesseract may
run before `t0`; full-fingerprint equality also catches a later smaller reaped
child that does not raise inherited child HWM. The independent child observer
and slow boundary checks remain residual controls. Together these defenses
mitigate a child created and reaped between observations; they do not convert
child memory into a candidate measurement. Source/version, PID/create-time,
platform, window, component, timestamps, duration, both lanes' cadence/counts/
readiness/completion/error, parse/output checkpoints, child controls, output
identities, and every formula input/result remain retained.

Each outer fresh worker is launched by `subprocess.Popen` on supported POSIX
platforms in a private session/process group with `start_new_session=True`,
`close_fds=True`, `stdin=subprocess.DEVNULL`, and only bootstrap pipes plus the
exact monitor socket in `pass_fds`; worker setup immediately makes that socket
non-inheritable. A bootstrap barrier binds the
exact leader PID and
create time plus PGID and SID before releasing the requested command. Every
success, nonzero exit, zero exit with a lingering descendant, timeout, and
diagnostic-overflow path enters bounded group TERM-to-KILL cleanup while pipes
are drained. The resumable state machine defers cancellation until cleanup is
terminal, never sends a second signal after `EPERM` or `ESRCH` uncertainty, and
allows one KILL retry only after uninterrupted proof of the same group across
the intervening wait. Success requires PGID absence by `ESRCH`, exact leader
reap, and selector/pipe/bootstrap-FD/stream closure; failures are sanitized and
do not expose output, paths, commands, environment values, or secrets.

Adversarial tests must cover timeout, TERM-ignore, diagnostic overflow with
inherited FDs, nonzero and zero exits with a lingering same-group descendant,
identity/group mismatch without signalling, cancellation/resumption, the
single conditional KILL retry, cleanup uncertainty, reap/closure, and sanitized
errors. Containment applies to descendants that remain in the private POSIX
session/process group. It cannot claim cleanup of arbitrary detached
`setsid`/double-fork descendants or elimination of theoretical PGID-reuse
TOCTOU. The static no-spawn guard, independent recursive child observer plus
slow boundary checks, and exact `RUSAGE_CHILDREN` fingerprint equality remain
required controls for those disclosed residuals.

For each of the five alternating pairs, `S_i=G_on_i-G_off_i` and
`D_i=max(0,S_i)`. Each of the three reviewed cases passes RSS only when
`max(D_0,...,D_4) <= 67,108,864`. Absolute process HWM values and their raw
cross-worker deltas remain observational only and cannot be called passes.
The bounded RSS sampler's possible sub-10-ms, below-inherited-waterline
transient and between-observation child residuals are explicitly disclosed.
Synchronous parse/
hook/output boundaries, self-HWM growth, the manifest-bound static no-spawn
guard, exact `RUSAGE_CHILDREN` fingerprint equality, and stress probes mitigate
them.
The proxy runs only in the worker and receives zero manual resource credit.
Its pre-`t0` identity/HWM/rusage work can affect inherited `B`/`H0`, its
intermediate boundary IPC and production-output work are inside `G`, and its
FINISH-response decode/close is post-`t1`. Controller RSS-sampler, child-
observer, FIFO, and child-check allocations are outside the worker and create
no credit. None is a waiver or an exact
instantaneous-peak claim.

Defense-in-depth sampler sensitivity uses two bounded, non-real fresh-worker
controls: a touched 16 MiB allocation sustained through `t1_api`, and a touched
16 MiB allocation released before `t1_api`. Each must observe at least 8 MiB
current-RSS/HWM sensitivity while preserving cadence and resource limits. The
managed-sandbox probes use a no-child adapter because psutil child enumeration
is denied with `EPERM`; they do not test child scope. Separate deterministic
tests own the child-observer, boundary-check, and cumulative-fingerprint
behavior. Canonical retained campaign workers must run outside that sandbox
with the real independent child lane and boundary checks, no adapter or
permission bypass, and fail closed if permission is unavailable. These
controls do not replace canonical three-case-by-five-pair
evidence and do not prove near-bound empirical behavior. Exact 64 MiB equality
and maximum-plus-one are owned by deterministic boundary arithmetic.

The historical pre-retention report and semantic projection were respectively
`p04-us01-table-metrics-v11` and
`p04-us01-final-metrics-semantic-projection-v11`; paired performance is
`p04-us01-paired-performance-v10`, quality evidence is
`p04-us01-quality-evidence-v7`, and both carry the unchanged exact paired formula
`p04-us01-paired-nonnegative-enabled-minus-disabled-worker-phase04-output-complete-peak-rss-increment-v3`.
Older schemas, formulas, endpoint-only records, or absolute-HWM gate records
are rejected rather than relabelled. These controlled interpretations change
no ceiling and waive no latency, RSS, output, resource, correctness, security,
compatibility, custody, rollback, diagnostic, determinism, corpus, or
hosted-use gate. The interim `v2` worker and paired RSS IDs were never finalized
or used for retained evidence; the accepted-but-unretained report/projection
`v5`, paired `v4`, and quality `v2` same-worker schemas are rejected, as are
the earlier report/projection `v4` and paired `v3` one-lane schemas.
No current real-metrics pass is asserted, and the exact retained final artifact
remains absent.

Overflow, deadline, malformed geometry, invalid UTF-8, hash mismatch, or graph
inconsistency rejects the complete affected table or cluster. Diagnostics
contain policy ID, stage, stable subject ID, counts, limits, evidence IDs, and
content digests only. They never expose raw cell text, document paths, source
bytes, credentials, exception representations, or unbounded engine output.
No network request, hosted model, package download, executable content, or
unsafe HTML is introduced.

## Stage order, custody, and terminal replay

The enabled stage order is:

1. retain all bounded raw table candidates and source objects;
2. apply US01 cell/grid/span fidelity to already selected page-local regions;
3. apply US02 candidate clustering and evidence reconciliation;
4. apply US04 typed ownership gating before body suppression or image binding;
5. finish source-text alignment without changing stable structural identity;
6. replay and validate table semantics, representations, caption/note links,
   text-run cell targets, and canonical custody transactionally; and
7. apply US03 continuation scoring only to validated gated page-local tables.

The projector takes a predecessor snapshot and commits only after strict IR,
public sidecar, representation, canonical, resource, and deadline validation.
Unexpected failure restores the complete predecessor page/table/canonical
closure. Terminal replay may refresh text evidence and representations, but it
may not change cell order, structural IDs, spans, or caption/note ownership
without a fresh evidence decision. Original engine candidates and page-local
tables remain evidence; no winning or merged view deletes them.

## Later-story decision contracts

P04-US02 `reconciliation` has exactly `cluster_id`, `candidate_ids`,
`selected_candidate_id`, `outcome`, `absolute_threshold`, `selection_margin`,
`scores`, `evidence_ids`, and `concern_codes`. Selection requires both an
absolute threshold and a positive winner margin using text, geometry, grid,
and provenance dimensions. Engine name is not a score. Below-margin conflicts
remain `unresolved`; bounded alternatives and reasons survive without silent
cell loss.

P04-US04 `gate` has exactly `decision_id`, `candidate_id`, `outcome`,
`owner_item_ids`, `feature_scores`, `evidence_ids`, and `concern_codes`.
Outcomes are `canonical_table`, `form`, `key_value`, `chart`, `visual`,
`unresolved`, or `structural_failure`. Rejected/unresolved regions cannot
suppress prose or consume an image. Forms and charts remain their typed owner;
true borderless/dense grids may pass on sufficient cell/alignment evidence
without fabricated rules or headers.

P04-US03 `continuation` has exactly `merge_id`, `outcome`, `source_table_ids`,
`continued_from`, `page_indexes`, `signal_ids`, `repeated_header_cell_ids`,
`evidence_ids`, and `concern_codes`. Only adjacent, US04-gated, structurally
valid page-local tables are eligible. A merge requires at least two
independent sufficient signals among compatible column boundaries, header
topology, page-boundary placement, and explicit caption/continuation evidence;
repeated template text alone is insufficient. Original page tables stay
normative. A derived view retains every row/cell's source page, bbox, and
evidence; omitted repeated headers remain evidence.

US02, US04, and US03 schemas above are frozen design constraints, not
executable readiness or authorization to implement those stories. Each still
requires its own Definition-of-Ready evidence and independent review in the
authorized dependency order.

## P04-US01 executable readiness scope

The executable readiness package may validate only immutable source identities,
reviewed table truth, synthetic positive/negative/resource controls, closed
fixture models, limits, deterministic fixture digests, and this policy's
constants. It must not import or assert production Settings, table extraction,
serialization, API, or frontend implementation that does not yet exist.

Scoring is limited to dimensions explicitly present in the source-qualified
oracle. Exhaustive cell text/bbox/provenance and cross-representation claims
apply only to exact-cell oracle fixtures. A reviewed real table with an absent
cell-level oracle must emit the targeted unresolved concern and cannot enter
the accuracy numerator or denominator. Postal and clinical visual review may
score the explicitly enumerated row/column/header/span facts. The ACORD
coverage region remains a form-owned vector grid: independently addressable
visible labels and its region bbox are observations only, while cell topology,
ownership, spans, cell bboxes, and provenance remain unresolved and cannot be
canonicalized by P04-US01.

The readiness-only frontend test may freeze the required implementation test
path, viewports, hostile text fixtures, strict-sidecar reader, escaped React
grid, predecessor fallback, and copy/download parity plan. It is not evidence
that any frontend behavior is implemented or that the story is In Progress or
Done.

The recorded readiness pass means only that P04-US01 inputs and expected
semantics are reviewable. Implementation start, quality, performance,
security, completion, and Phase 04 exit remain separate gates.
