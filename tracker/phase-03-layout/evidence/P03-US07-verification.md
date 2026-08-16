# P03-US07 Verification Evidence

Date: 2026-08-01  
Status: Pass

## Scope and compatibility

- `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED` defaults off and requires the
  accepted shared IR, relationship-aware order, and canonical presentation
  path.
- Flag off performs zero US07 module import, source extraction, or projection
  work and restores the exact configured predecessor with every non-US07 flag
  unchanged.
- Flag on adds strict typed outline descriptors, closed relationship graphs,
  and an additive anchor sidecar. Public schema version `1.0`, legacy page
  items, source-visible values, tables, and physical reading order remain
  authoritative.
- Canonical Markdown/text is generated from the same validated graph. The
  frontend accepts only a complete bounded sidecar, renders semantic nested
  React lists, and falls back to authoritative canonical content without raw
  HTML or client-side relationship inference.

## Exact reviewed result

| Case / control | Expected | Retained result |
|---|---:|---:|
| Component groups / nodes / relationships | 2 / 16 / 32 | 2 / 16 / 32 exact |
| Component roots / children / parent edges | 11 / 5 / 5 | 11 / 5 / 5 exact |
| Settlement groups / nodes / relationships | 1 / 3 / 6 | 1 / 3 / 6 exact |
| Settlement literal markers | `a.` / `b.` / `c.` | Exact |
| Settlement table continuations | 1 | 1 exact, owned by `b.` |
| Combined groups / nodes / relationships | 3 / 19 / 38 | 3 / 19 / 38 exact |
| Marker/value/bbox loss, duplication, or mutation | 0 | 0 |
| Component P03-US06 groups / pairs / relationships | 3 / 16 / 80 | Exact and disjoint |
| Retained P03-US04 order | 41 / 41 | 41 / 41 |
| Finance false outlines | 0 | 0 |

The combined graph contains 19 `contains`, 13 `outline_next`, five
`outline_parent_of`, and one `outline_continuation_of` relationship. Every
marker bbox, item bbox, raw value, ordinal, parent, evidence path, relationship
backlink, group union, source identity, and predecessor binding matches the
immutable oracle. The table between settlement clauses remains a top-level
table and is not reinterpreted as a clause.

The 11-fixture registry covers 37 named capabilities; all nine generated PDFs
open/render with pdfplumber and pypdfium2. Nested unordered, ordered numeric,
and legal-table-interruption fixtures project. Broken sequences,
parenthesized prose, financial rows, ambiguous indentation, parenthesized-alpha
combined-source ownership, and marker injection preserve source evidence but
produce no false projected outline.

## Failure, security, and resource behavior

- Strict public and IR schemas reject extra fields, invalid enum/cardinality
  combinations, duplicate or unresolved IDs, crossed page/anchor/group
  evidence, malformed parent stacks, and non-exact relationship topology.
- Unsafe continuation Markdown, raw angle-bracket content, unsafe link schemes,
  and nine encoded or obfuscated link variants are rejected. Settlement's
  reviewed table remains accepted byte-for-byte.
- Source-report hash, page, count, marker, bbox, ordering, byte, and limit
  custody is validated before projection; tampering fails closed.
- Page-local ambiguity, geometry failure, comparison overflow, public-group
  overflow, and page deadline failure restore the page. Document/source-report,
  aggregate, terminal replay, or final identity failure restores the complete
  US07 stage. No partial sidecar survives.
- All 22 production resource exact/max+1 boundaries and all three deadline
  boundaries pass. The maximum measured resource-boundary duration is
  15.431375 ms against the 250 ms ceiling.
- Repeated projection and terminal replay are idempotent. Forced replay
  mismatch restores pages, graph identity, and canonical output atomically.

## Performance and custody

| Isolated stage | p50 | p95 | max | Peak traced allocation | Report / IR bytes |
|---|---:|---:|---:|---:|---:|
| Component extraction | 145.649 ms | 171.112 ms | 195.901 ms | 9,341,342 bytes | 3,775 |
| Settlement extraction | 55.505 ms | 56.917 ms | 59.607 ms | 5,879,692 bytes | 1,133 |
| Component projection | 31.627 ms | 32.115 ms | 33.444 ms | 4,891,543 bytes | 598,088 |
| Settlement projection | 5.343 ms | 5.529 ms | 5.535 ms | 793,721 bytes | 77,395 |

Component projection performs 28 instrumented comparisons and settlement
performs four, both below the 65,536/page ceiling. Five alternating
fresh-process pairs pass both relative and absolute gates:

| Case | Paired overhead p50 / p95 | Effective ceiling | Maximum RSS off / on | Delta |
|---|---:|---:|---:|---:|
| Component | 79.820 / 481.838 ms | 528 ms | 2,039,676,928 / 2,057,175,040 bytes | 17,498,112 bytes |
| Settlement | 86.382 / 138.590 ms | 299.231 ms | 1,500,987,392 / 1,511,882,752 bytes | 10,895,360 bytes |

Operating-system caches were not explicitly flushed, so no cold-cache claim
is made. Representative semantic JSON off/on sizes are 319,964/369,006 bytes
component and 48,079/66,198 bytes settlement; Markdown sizes are 3,725/5,425
and 3,144/3,565 bytes. Hosted requests, tokens, and cost are 0, 0, and $0.

The retained artifact binds 31 final code/config/frontend/test/policy paths,
the exact component, settlement, and Finance inputs, the sealed P03-US06
artifact, M0 reference, oracle/contract/addendum identities, dependencies and
local tools, 11 fixture hashes/37 capabilities, limits, rollback, outputs,
deterministic replay, and zero hosted use.

## Test and review gates

- Story/readiness: **21 passed**.
- Strict contract: **23 passed**.
- Real-corpus and controls: **19 passed**.
- Performance/resource: **47 passed**, with five documented upstream warnings.
- Retained artifact: **5 passed**, with one documented upstream warning.
- Combined contract/real-corpus invocation: **42 passed**, with 14 documented
  upstream warnings.
- Total across the five dedicated backend files: **115 tests**.
- Frontend Node 22.18: lint, typecheck, production build, **90/90 unit tests**,
  and **1/1 bundle test** pass.
- Python compilation, Ruff 0.15.22 on the four final evidence/test paths,
  deterministic fixture self-checks, and both local PDF readers: **Pass**.
- Independent production/security and final metrics/custody reviews: **Pass**;
  no blocking finding remains.

Warning counts belong to the named invocations and are not summed across
overlapping reruns. Automated rendering, fallback, normalization, source/page,
copy/download, build, bundle, and proxy-contract paths pass.

## Live frontend milestone

A live local parser plus production frontend renderer check passes on both real
PDFs:

- component projects **2/16/32**, renders two semantic `<ul>` roots with a
  nested `<ul>`, retains exact canonical Markdown and JSON sidecars, contains
  no raw `<script>`, and preserves physical pages/labels **3/[1,2,3]**; and
- settlement projects **1/3/6**, renders one semantic `<ol>` root with its
  owned `<table class="parsed-table">`, retains exact canonical Markdown and
  JSON sidecars, contains no raw `<script>`, and preserves physical
  pages/labels **1/[1]**.

The in-app/Chrome browser surface was unavailable, so manual click-through is
not claimed and remains a Phase 03 exit retry. The vinext development proxy
stalled while the backend remained healthy, so this live renderer check used
the backend directly. Automated proxy contract tests remain green; the timeout
is classified as a local environment/tooling limitation, not a production
parser correctness failure.

## Retained artifact and rejected candidates

Final machine-readable evidence is in
[P03-US07-outline-metrics.json](P03-US07-outline-metrics.json).

- Size: **136,091 bytes**
- Raw SHA-256:
  `cbfe68a90a225adc9896435f7197389998df8ddddfca2ae94f8a917807490765`
- Semantic SHA-256:
  `22c208d8f625cb917e3e27097c6c60fc5fb904282ac7ae3e530dbffdf62d2639`

Two complete candidates were rejected, were not waived, and were not sealed or
retained as final evidence:

- candidate 1: 136,098 bytes; raw SHA-256
  `80be04f205c65da7ac1f4bff891326f3a9aba24d89c0ef275b0a0f4d0497d333`;
  semantic SHA-256
  `d407ed310028c052d58cc3536b22386dc0e8dd5458af4269abf39f1eb49ec3dd`;
  component paired p50/p95 overhead 89.043/639.774 ms; and
- candidate 2: 136,059 bytes; raw SHA-256
  `4ff77743753ef73c1c06e783afce0ebba514e5db812a917d143aa8a73a2d1ed2`;
  semantic SHA-256
  `3bfb7dc03e1fd1cc6976e16d4b671416b1ab81983c5d228fe958a211dba3a03b`;
  component paired p50/p95 overhead 342.796/1,013.963 ms.

Each failed only the component whole-parser paired gate because of an isolated
predecessor/scheduling outlier. A complete unchanged uncontended campaign then
passed every gate and produced the final artifact above.

## Rollback and remaining scope

Set `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED=false`. The outline module is not
loaded, source extraction and projection are skipped, and the exact configured
predecessor is restored with every non-US07 setting unchanged.

Running-region and physical/printed-page identity remain owned by P03-US08,
which is Proposed. Cross-page outline edges, upper-alpha/Roman/custom markers,
inline-enumeration splitting, legal interpretation, Office/image parity, and
Phase 04 table reconstruction remain out of scope. No Phase 04 work has
started.
