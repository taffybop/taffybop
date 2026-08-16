# P03-US08 Hardened Phase 04 Tables Latency Exception Renewal

Status: Requester-authorized administrative reissue; executable guard resealed; fresh independent approval pending  
Decision ID: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`  
Renews: `P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES`  
Owner: Project owner/requester  
Recorded: 2026-08-03  
Review due: 2026-09-02

## Decision

The requester authorized the narrow administrative renewal of the existing
P03-US08 latency exception needed to permit unrelated Phase 04 table changes,
subject to the constraints below. The implementation team derived this closed
grammar under that authority; the exact helper designs and scanners are
implementation controls, not mechanics attributed to the requester.

The earlier Phase 04 renewal, its failed independent audit, and the later
blocked red-team review remain immutable history. The blocked red-team review
is bound separately and retains finding IDs `TS-01` through `TS-06`, `PL-01`
through `PL-04`, `CFG-01` through `CFG-03`, `FE-01` through `FE-12`, and
`GUARD_ACCEPTED_REFLECTION_ALIAS_DYNAMIC_IMPORT_SIDE_EFFECT`. This reissue may
not be relied on for production changes until a fresh independent reviewer
approves the final sealed implementation.

Independent review 02 also remains immutable blocked history. It found that a
strict subset of the claimed nine backend functions could pass and required
the frontend export claim to be exact. A follow-up probe against the first
remediation patch demonstrated additional CommonJS exports through unmasked
`module` and `exports` objects. The second review is separately identity-bound;
this reissue does not overwrite or reclassify it.

The executable record may admit only unrelated, default-off Phase 04 table
work on the exact paths and AST surfaces below. `app/services/tables.py` and
`.env.example` are admitted only through the identity-bound two-state surfaces
described below; neither is a general edit surface. No Phase 05 path, status,
or behavior is authorized.

The semantics grammar below is the contract for the final resealed
implementation. This renewal may not authorize Phase 04 production changes
until every stated control is represented by the executable constants and
tests and the resulting identities receive fresh independent approval.

The hardened renewal enumerates exactly five Phase 04 paths added after the
frozen P03 code baseline:

- `app/services/table_semantics.py`;
- `frontend/lib/table-semantics.ts`;
- `frontend/tests/p04-us01-table-readiness.test.mts`;
- `frontend/tests/p04-us01-table-span-fidelity.test.mts`; and
- `frontend/tests/p04-tables.test.mts`.

It observes exactly eight existing paths under closed normalizers or exact
two-state identity binding:
`.env.example`, `app/config.py`, `app/services/pipeline.py`,
`app/services/tables.py`, `app/services/source_text_alignment.py`,
`app/services/text_reconciliation.py`, and
`frontend/app/clearleaf-workspace.tsx`, plus the administrative contract
`tests/performance/test_p03_us08_running_region_metrics_contract.py`. The P03
86-path required-code manifest continues to govern its original members;
neither the five separately governed Phase 04 paths nor `.env.example` is
inserted into that historical manifest.

The administrative contract is accepted only at its exact 162,944-byte
baseline SHA-256
`3604bf403b900970414ce8cc86d40bf806958cb0b1cb2d17e776ee404c2b408e`
or its exact 165,157-byte candidate SHA-256
`3862f5d386f0bf4440da646d1cc7603dedb7f14cf694d275da49a6d9d0c97e75`.
The candidate leaves `REQUIRED_CODE_PATHS` unchanged at 86 and disjoint from
an exact five-path Phase 04 table-only set. Repository `app`/`frontend` code
may fall outside the frozen P03 set only through that exact separate set; the
already-present readiness test is identity-pinned at 2,156 bytes and SHA-256
`ffc15e1ed0511b20a34bdead5342345b521f25e644b705806e2d9060a7d1f817`,
and backend/frontend sixth-path controls fail. This is an administrative
classification of unrelated Phase 04 custody, not a change to running-region
runtime, metrics, the frozen manifest, or any waived gate.

The story-specific frontend test is the P04-US01 acceptance surface. The
existing `p04-tables.test.mts` path is deliberately retained for cumulative
whole-Phase-04 regression coverage; it does not authorize another production
surface or any Phase 05 work.

## Exact configuration surface

`app/config.py` may add exactly four `bool = False` settings, in dependency
order immediately before `__post_init__`:

1. `table_span_fidelity_enabled`;
2. `table_evidence_reconciliation_enabled`;
3. `table_candidate_gate_enabled`; and
4. `table_multi_page_merge_enabled`.

It may append exactly four ordered dependency guard ASTs: span fidelity
requires shared IR, shared-IR normalization, and canonical serialization;
evidence reconciliation requires span fidelity; candidate gating requires
evidence reconciliation; and multi-page merge requires candidate gating. The
four `from_env` bindings must be final keywords, use their exact environment
names, and call `_read_bool(..., False)`. Kill switches, duplicate or combined
guards, inverted polarity, reordered dependencies, default-on values, and
other table keywords are rejected.

`.env.example` may be either its exact 4,696-byte predecessor or that exact
predecessor followed at end of file, immediately after
`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=false`, by the four unique table
environment bindings in dependency order, each exactly `false`. Moving,
duplicating, reordering, renaming, adding a fifth flag, changing whitespace or
polarity, or changing the running-region line is rejected. The environment
file is not part of the 86-path P03 code manifest and does not change that
manifest's count; it is read, normalized, and custody-checked separately.

## Exact vector-geometry surface

`app/services/tables.py` is admitted atomically in only two AST-normalized
states: the baseline four-node vector with the retained-module AST identity,
or the identity-bound Phase 04 geometry vector pending fresh independent
approval. The current baseline file is 18,319 bytes with raw SHA-256
`dc889c00eea03ee3506093c6e806966e16f76f02ff941e6476e61c32545d0d42`.
The retained-module digest freezes every import, constant, detector, threshold,
helper, and other function. Mixed or partial states are rejected. The candidate
changes exactly `RawTable`, `_clean_table`, `_page_candidates`, and
`extract_vector_tables`.

The retained-module AST identity is
`d7caf061838240af598fcb2f91108410324d776d2a9a5fe22718402c65638372`.
The bound candidate's four-node AST vector, in that order, is
`0dafc1586a131a11131db4e0894ea61caa732c522a37c6f48defc57173fd21c8`,
`9932b9fe544463ad1f445440f28469706b10eb6b1f665cd876727e5543804adf`,
`0b66c2f7d400731baca041eb1c8ffd8bf8d63f424706647f289035b3218a5624`,
and `e916c77211e82794ff99c6577821bd32921c4aaca0b642a7a3fac230febbfe00`.
The executable tests construct those bytes from the predecessor in memory;
production is not changed merely by reviewing or binding the candidate.

`RawTable` retains its five predecessor fields in their exact order and adds
only `cell_bboxes` as a tuple-of-tuples aligned to rows and columns, followed
by nullable `geometry_inferred`. The three functions add only the keyword-only
`preserve_cell_geometry: bool = False` parameter. The enabled branch reads
source cell boxes, validates finite source coordinates with strictly positive
width and height, preserves aligned nulls and geometry-backed blank edge
cells/rows, and retains whether
the candidate came from inferred or standard geometry. It never subdivides a
box by equal width or height and never fabricates missing cell geometry. The
inclusive ceilings are 4,096 rows, 256 columns, and 65,536 cells. The disabled
branch never reads row-cell geometry and retains the exact predecessor
detector behavior, candidate ordering, duplicate handling, and all legacy
field values and serialized outputs; the two new internal fields remain at
their inert defaults.

## Exact pipeline surface

General pipeline helper changes are limited to `_analyze_shared_pages`,
`_docling_table_item`, `_merge_tables`, `_normalize_docling_body`, and
`_vector_table_item`; `_merge_body_items` is excluded. After removal of the
enumerated additions, each function and the remaining module must match its
baseline AST identity.

`_parse_loaded_document` is not added to that general function allowlist. A
separate exact two-state normalizer admits only its predecessor vector-table
`try` statement or one complete replacement: for PDF input with span fidelity
enabled, call `extract_vector_tables` once with
`preserve_cell_geometry=True`; for PDF input with span fidelity disabled, make
the exact predecessor one-argument call; and for non-PDF input, return the
same empty mapping without reading geometry or invoking extraction. The exact
predecessor exception handling and content-bounded warning are unchanged. Any
other mutation in `_parse_loaded_document` is rejected.

Only these direct imports/calls are admitted:

- `_docling_table_item`: `prepare_docling_table_input` at the start and
  `prepare_docling_table` immediately before return, with the exact existing
  locals and the span flag;
- `_normalize_docling_body`: forward only the span flag to
  `_docling_table_item`;
- `_vector_table_item`: `prepare_vector_table` immediately before return,
  using `item`, the existing raw-table input, and the span flag;
- `_merge_tables`: forward span to `_vector_table_item`, then call
  `reconcile_table_candidates` immediately before return with `merged`, both
  original evidence maps, span, and reconciliation flags; and
- `_analyze_shared_pages`: forward span into normalization and span plus
  reconciliation into merge; call `gate_table_candidates` immediately after
  merge with `tables`, `body_items`, and only the enumerated context fields
  `image_regions`, `raw_docling`, and `source_document_identity`; after OCR
  enrichment call `seal_table_pages` with only `pages`,
  `source_document_identity`, and bounded/private `native_texts`; then call
  `merge_continued_tables` with only `pages` and
  `source_document_identity`.

All helper flag keywords bind to the exact local flag or
`context.settings.<exact flag>`. Helper names, call counts, assignment forms,
positions, positional paths, keyword order, and forwarding edges are exact.
The grammar never strips a table keyword from an unrelated call. Whole
contexts/settings, builtins, callback objects, arbitrary attributes, dynamic
calls/imports, aliases, unlisted helpers, and running-region identifiers are
rejected.

## Exact backend helper surface

From P04-US01 onward, `app/services/table_semantics.py` must expose exactly all
nine runtime functions below. No function may be missing or added. Functions
owned by later stories remain present but execute their exact leading
default-off no-op until their story flag chain is enabled.

1. `prepare_docling_table_input(raw_item, page_heights,
   page_words_by_page, *, table_span_fidelity_enabled=False)`;
2. `prepare_docling_table(item, raw_item, *,
   table_span_fidelity_enabled=False)`;
3. `prepare_vector_table(item, raw_table, *,
   table_span_fidelity_enabled=False)`;
4. `reconcile_table_candidates(merged, docling_tables, vector_tables, *,
   table_span_fidelity_enabled=False,
   table_evidence_reconciliation_enabled=False)`;
5. `gate_table_candidates(tables, body_items, image_regions, raw_docling,
   source_document_identity, *, table_span_fidelity_enabled=False,
   table_evidence_reconciliation_enabled=False,
   table_candidate_gate_enabled=False)`;
6. `seal_table_pages(pages, source_sha256, native_texts, *,
   table_span_fidelity_enabled=False,
   table_evidence_reconciliation_enabled=False,
   table_candidate_gate_enabled=False,
   table_multi_page_merge_enabled=False)`;
7. `merge_continued_tables(pages, source_sha256, *,
   table_span_fidelity_enabled=False,
   table_evidence_reconciliation_enabled=False,
   table_candidate_gate_enabled=False,
   table_multi_page_merge_enabled=False)`;
8. `replay_table_semantics(table, table_evidence)`; and
9. `replace_marked_table_text(owner, *, selected_text, replacement_mode,
   original_text)`.

Each flag-owned stage has an exact leading no-work return before input
validation, clock creation, or allocation. Span owns the three preparation
helpers and terminal page sealing. Evidence reconciliation owns attachment and
retention of overlapping alternatives. `reconcile_table_candidates` returns
immediately when span fidelity is false; when span is true and reconciliation
is false, it returns an owned, unchanged copy of the already merged candidates.
That input may already contain non-overlapping source/vector candidates
retained upstream, but the reconciliation function may not attach, score,
select, or discard a candidate on the span-only path. Span plus reconciliation
plus gating owns candidate gating, and all four flags own continued-table
merging. Thus all-four-false behavior is the exact predecessor without new
exceptions,
copies, timing, diagnostics, or allocations. Replay hooks are marker-gated by
their exact callers and validate marked data.

Validation has an exact per-argument commit policy. Return-value stages must
rebind each declared input to its validated copy. Only the intentional
in-place mutation arguments—page lists for sealing/continuation and the
marked table for replay—may validate the original expression in place. The
opposite form is rejected. This syntactic boundary rule does not itself prove
transactional rollback for later in-place mutations. Each enabled story must
separately demonstrate snapshot/atomic-commit behavior, including injected
exceptions before commit, under the non-waived correctness and rollback gates.

The module uses exact symbol imports without aliases. Its only project import
is the exact `RawTable` class from the already admitted table service, used for
an exact-type data copy; all other project imports remain rejected. Top level
is limited to an optional docstring, ordered imports, literal-only constants,
and top-level functions. Classes, decorators, nested definitions,
comprehensions, module-level calls, callable defaults, reflection, loaders,
debug/input facilities, dynamic execution/import, filesystem, network,
subprocess, sleep, and unknown method receivers are rejected.
Phase 05 and running-region scope is rejected across separated, camel, compact,
plural, and case-varied forms, including table-prefixed and enabled-suffixed
identifiers, or when reconstructed from bounded constant string expressions;
scanning individual literal fragments is not sufficient. Unrelated lexical
words and Phase 04 identifiers remain admissible controls.

Every enabled public function creates exactly one
`deadline = perf_counter() + 0.25` after its default-off guard. All validators,
copy/hash helpers, loop-bearing helpers, and terminal assertions receive that
same exact deadline. Private helpers may not create or reset a deadline, local
call edges must forward it exactly, and resource-bearing helpers may not be
called directly or transitively beneath a loop. Every loop uses the exact
bounded iterator and begins with the exact deadline check. These stricter
local clocks supplement the 0.500-second page, 5.000-second document, and
10.000-second total Phase 04 gates; they do not replace or waive them.

Exact plain-data validation checks type, depth, node count, string size,
container size, active-path cycles, aggregate bytes, and the shared deadline.
Repeated acyclic references are legal and remain aliased in a detached copy;
direct or indirect cycles fail closed. Exact-dictionary traversal snapshots
items and validates key/value pairs without looking a key up again, so a
hostile key cannot execute `__hash__` or `__eq__` before rejection. The frozen
raw-table copier accepts only exact `RawTable`, `dict`, or `defaultdict`
inputs, closes the predecessor-plus-geometry key set, converts it to canonical
plain data, and caps the cumulative candidate total across all pages at
65,536. Unknown mapping subclasses, fields, callbacks, misaligned geometry,
and maximum-plus-one graphs fail closed. The only opaque attribute access is
the seven enumerated `RawTable` data fields and `owner.value`,
`owner.markdown`, and `owner.properties`; neither opaque input may dispatch a
method.

Outside the frozen bounded/validation/copy/hash helpers, augmented assignment and
the growing methods `add`, `setdefault`, and `writerow` are rejected. An
`append` receiver must be an exact empty local list with one binding; every
append must be a standalone statement directly inside a top-level bounded
loop, and the cumulative append cardinality per accumulator is at most 65,536;
payload allocation bytes are charged independently. Dynamic item stores use
cumulative loop ceilings on an exact empty local dictionary. Literal
integer/string item stores occur outside loops and may target only that bounded
local dictionary or a public input already copied or validated at the
boundary. A derived read from a subsequently mutated root is admitted only
through an exact alias-breaking copying/scalar helper; borrowed `.get` or
subscript aliases, mutation through them, and alias escape remain rejected.
Rebinding, private-helper mutation of caller-owned mappings, pre-population,
nested/conditional growth, and cumulative maximum-plus-one cases fail closed.
Direct or transitive graph-copy, canonical serialization, hash, and unmodelled
constructor work beneath a loop is rejected rather than multiplied without an
allocation bound.

Every public plain-output function has exactly one enabled-path terminal
return of its declared compatibility root. Immediately before that return it
must run the exact same-deadline canonical-JSON boundary and no-copy plain
assertion for the complete mutated root; no conditional or post-validation
mutation is allowed. The canonical boundary permits only JSON null, exact
booleans, finite numbers, UTF-8 strings, lists, and string-keyed dictionaries;
it uses deterministic sorted-key compact JSON, rejects tuples/bytes/non-string
keys, and applies an explicitly enumerated 8 MiB table or 64 MiB document byte
limit. Its SHA helper accepts only exact bounded bytes, checks the shared
deadline before and after hashing, and returns lowercase 64-hex SHA-256.
Source identities are separately exact lowercase 64-hex strings; this renewal
does not claim to rehash a document whose raw bytes are not in a function's
authorized signature.

These terminal checks make cycles, callable/range/set values, non-finite
numbers, invalid UTF-8, depth/node/container overflow, non-JSON values, hash
or byte-limit overflow, and aggregate maximum-plus-one output fail closed
before return. For an in-place root they do not undo mutations that occurred
before a raised exception; the separate story-level snapshot, injected-error,
and atomic-commit gate above remains mandatory. Exact API/schema/serializer
tests and output-size checks also remain mandatory non-waived gates before any
story is Done. The default-off leading return remains before all validation,
clock creation, and allocation.

Non-frozen functions are limited to 4,096 AST nodes and the complete module to
32,768 AST nodes. Explicit list, tuple, set, dictionary, byte, and sequence
allocations use a conservative, type-aware byte estimate, including nested
expressions, loop multipliers, and acyclic inter-function call expansion, with
a 67,108,864-byte ceiling. Unsupported binary allocation forms are rejected.
Callable arguments and keywords participate in the call graph and provenance
checks. Method-call arguments may not contain an unvalidated call result or a
local callable reference, preventing unaccounted callback multiplicity. A
non-frozen bounded-loop function may not catch or suppress its deadline via a
`try` construct. These static controls supplement rather than waive measured
RSS, runtime deadline, output-size, and final-schema gates.

## Exact replay and frontend surfaces

`app/services/source_text_alignment.py` is authorized only for the executable
record's exact trailing `_refresh_table` marker hook. Removing those exact
bytes restores the baseline source and AST. `app/services/text_reconciliation.py`
is authorized only for its exact marker-gated leading branch in
`_ir_replace_owner_text`; removing it likewise restores the baseline. Both
helpers must fail closed on malformed or over-budget evidence and rebuild all
marked table serializations from authoritative cells/slots without fabricating
content or flattening unsupported structure.

The frontend source remains sealed outside the exact helper import, the
`ContentItemView` table branch, and one exact optional
`CanonicalRenderedPage` table delegation. That delegation may replace only
the final `canonicalFallback` return immediately after the complete
`formSemantics` branch. Form ownership therefore remains prior and unchanged.
It filters `sourcePage.items` only by exact equality between `item.id` and
`block.primary_element_id`, requires exactly one match, requires a string
`table` type, and requires `Object.hasOwn(primaryItem, "table_evidence")`
before passing that one item to `ContentItemView`. Zero or multiple matches,
a non-table or malformed type, and a missing own marker all return the same
precomputed `canonicalFallback`. With no marker or no delegation, the default
fallback is byte-identical to the predecessor. No other canonical block or
frontend surface may delegate.

`frontend/lib/table-semantics.ts` must contain exactly one unmasked export
token and one matching non-async
`export function readTableSemantics(item)` declaration. Async, default, named
list, additional ES-module, CommonJS `module`/`exports`, or other export forms
are rejected. Computed or optional calls/members, member dispatch on call or
parenthesized results, constructors, reflection, dynamic import/evaluation,
browser/network/storage/resource APIs, escaped global names, unsafe HTML, JSX
spreads, and resource/event/ref/style JSX are rejected. JSX is limited to inert
table presentation tags and properties.

Named-function default-parameter expressions participate in the complete
call graph, and implicit coercion or serializer hooks such as `toString`,
`valueOf`, and `toJSON` are rejected rather than treated as inert object
members. Process/runtime, filesystem, environment, browser, storage, cache,
performance, and cryptographic global roots are forbidden on property or
element reads as well as calls; a capability cannot become admissible merely
because no method is invoked.

Adding a path, helper, call edge, public export, import symbol, context field,
opaque attribute, JSX capability, or relaxing a scanner expires this renewal
before the change and requires a new explicit decision.

## Preserved observation and ceilings

The sole accepted observation remains immutable attempt 48:

- target: `ny-timetable`;
- stage: `running_region_projection`;
- metric: `latency_p95_seconds`;
- observed: **0.050946750 seconds**;
- strict ceiling: **0.050000000 seconds**;
- overrun: **0.000946750 seconds / 1.8935%**; and
- maximum candidate-specific authorization: **5%**.

Attempt 48 remains failed. The strict ceiling is unchanged, the canonical
strict-final artifact remains absent, the complete companion remains
quarantined, and Phase 03 must not be described as a strict current-artifact
metrics pass. Failed history remains sealed at 55 artifacts with manifest
`bca401f2207619ba84422e020104b9a609e0be0f4dc2b42f3ae4fb53d315ceff`.

## Non-waived gates, expiry, and rollback

This renewal waives no RSS, allocation, paired-parser latency,
source-extraction latency, Uber projection latency, correctness or quality,
security, API/schema compatibility, dependency/input/fixture/code custody,
resource/deadline, output-size, rollback, or hosted-use gate. It authorizes no
production enablement, hosted model use, broader latency bound, new benchmark
observation, or Phase 05 work.

The record is reviewable no later than 2026-09-02 and expires before any
production enablement; any relevant running-region semantic or runtime
behavior change; any relevant running-region custody change; authorized Phase
04 scope or path expansion; or any hardened grammar or scanner relaxation.
Expiry or revocation returns P03-US08 to In Progress and blocks dependent exit
claims until strict current-code evidence or another explicit decision exists.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` remains false by default; disabling it
performs zero P03-US08 work and returns the exact configured predecessor. The
four Phase 04 flags also remain default-off and outside the P03-US08 latency
exception.

## Approval record

The requester authorized the narrow Phase 04 tables renewal in the active
Codex thread on 2026-08-03, requiring the exact attempt-48 observation,
unchanged ceilings and maximum 5% candidate-specific bound, default-off
rollback, every non-waived gate, review no later than 2026-09-02, and expiry
before production enablement or any relevant running-region behavior or
custody change. Fresh independent approval of this final sealed implementation
remains required; this decision is not self-approval.
