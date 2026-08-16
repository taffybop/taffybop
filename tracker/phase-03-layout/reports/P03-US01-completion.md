# P03-US01 Completion Report

Status: Done  
Story: Preserve external table captions  
Points: 3  
Started: 2026-07-31  
Completed: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — external table captions only; no cell edits, visual captions, notes, or synthesis |
| Points at most 5 | Pass — 3 |
| Dependencies Done | Pass — P01-US02 is Done |
| Acceptance measurable | Pass — exact 3/3 reviewed identities, no duplicates, 100% bbox/link coverage, zero table-content drift, exact rollback |
| Dedicated tests identified | Pass — story, contract, API, canonical, real benchmark, adversarial, performance, custody, and frontend paths |
| Fixtures available and authorized | Pass — immutable catastrophe, clinical, and finance PDFs plus deterministic graph/geometry controls |
| API/frontend impact documented | Pass — additive schema-v1 fields and explicit escaped caption rendering |
| Feature flag identified | Pass — `PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED`, default off |
| Rollback defined | Pass — disable the flag to restore exact predecessor output |
| Quality/performance specified | Pass — 5% stage ceiling, bounded references/candidates, output/RSS snapshots, no hosted work |

Definition-of-Ready result: **10/10 Pass**. P03-US01 was the sole story in
progress. Its accepted promotion, ambiguity, resource, serialization, and
rollback rules are in
[P03-table-caption-policy.md](../decisions/P03-table-caption-policy.md).

## Implementation

The layout projector consumes retained raw `caption_of` relationships and
promotes only source-visible external captions whose graph and page geometry
agree. It unions multiline raw provenance boxes, retains stable public IDs and
source fields, adds bidirectional public link descriptors, and places each
accepted caption immediately before its table without changing rows or cells.

Duplicate source routes use bounded connected overlap components and project
once. Cross-owner physical ambiguity—including overlap chains, extractor
jitter, and conflicting text at one region—fails closed. Missing, internal,
empty, generated, non-text, malformed, distant, dangling, and orphan
candidates remain evidence-only with attributable concerns.

The implementation pre-indexes geometry/evidence, rebuilds presentation order
once per page, limits one table to 64 references, one same-text page bucket to
128 candidates, and one page to 512 candidates. Overflow is all-or-nothing and
does no pairwise geometry work.

The API retains schema `1.0`; additive fields pass through unchanged. The
frontend types the relationship shape, renders captions as escaped distinct
content, and preserves normalized complete-document JSON, canonical Markdown,
page mapping, copy, and download bytes.

## Acceptance result

1. Exhibit 7 exactly once with source bbox: **Pass — exact physical p1 /
   printed p7 text and `[100.700, 210.095, 250.220, 9.351]` bbox**.
2. Table `caption_of` link: **Pass — caption-side scalar, table-side IDs, and
   stable descriptor all resolve and link back**.
3. No table-cell insertion: **Pass — target rows/cells hashes are identical
   with the flag on and off**.
4. Ambiguous/multiple references: **Pass — distinct same-owner captions remain
   ordered with concerns; duplicate/shared/cross-owner components are
   deterministic and fail closed**.
5. Flag-off JSON/Markdown parity: **Pass — finance control is semantically
   exact; target flag-off output contains no projected caption and table
   content is unchanged**.

The generalized real-document gate also passes exact clinical Table 1
(physical p2) and Table 2 (physical p4) identities, for **3/3 reviewed
captions, zero unexpected captions, zero Markdown duplicates, and 100%
bbox/relationship coverage**.

## Verification and metrics

- Final story/contract/API/canonical/real/performance/custody gate:
  **62 passed**, with the existing Starlette warning and upstream Docling
  deprecation warnings.
- Independent production/security gate: **124 passed, 1 documented opt-in
  skip**, compilation and targeted lint clean.
- Real benchmark regression: **5 passed** across catastrophe, clinical, and
  finance.
- Frontend Node 22.18: lint, typecheck, production build, **46/46 unit tests**,
  and **1/1 bundle test** passed.
- Python compilation and dependency integrity: **Pass**; no dependency was
  added.

The isolated layout stage used five warmups and 100 samples. It recorded p50
**1.302 ms**, p95 **1.677 ms**, max **1.984 ms**, and peak traced allocation
**88,477 bytes**. The p95 is about **0.020%** of the retained 8.50-second
catastrophe ceiling and is below both the 5% story ceiling and the 50 ms
absolute gate.

Full-parser flag states were collected in separate fresh processes, with no
in-process converter/model reuse. The one-snapshot off/on wall times were
10.501/8.265 seconds for catastrophe, 15.537/16.338 seconds for clinical, and
21.895/21.217 seconds for finance. Per-worker peak-RSS high-water marks were
1,432,633,344/1,501,167,616 bytes; 1,624,342,528/1,589,526,528 bytes; and
2,005,483,520/2,004,041,728 bytes respectively. These cold snapshots document
the two states but are not treated as causal percentile estimates; the
isolated 100-sample stage measurement is the performance acceptance gate.

Enabled JSON adds 3,997 bytes for catastrophe and 23,014 bytes for clinical,
and adds zero bytes for the finance control. Hosted requests, tokens, and cost
are all zero.

Independent production/security, performance, frontend/API, and final
metrics/custody reviews approved the final snapshot after all correctness,
resource, ambiguity, UI-milestone, measurement-isolation, and identity-binding
findings were fixed and retested.

## Frontend milestone

The composed affected-path check covers catastrophe physical page 1 / printed
page 7, caption-specific canonical Markdown, normalized complete JSON,
clipboard and Blob byte identity, explicit rendering, and flag-off absence.
The local backend and frontend started successfully and the app built, but the
session exposed no controllable browser, so no manual click-through is claimed.
This unavailable channel is recorded for the Phase 03 exit retry; automated
frontend and independent review gates passed.

## Known limitations

- Clinical Table 2 retains the extractor-visible flattened text
  `( N = 538, ...)`; italic-run semantics are deliberately deferred to
  P03-US05.
- Visual/chart captions, source notes/footnotes, and generalized reading-order
  policy remain unresolved here and are owned by P03-US02 through P03-US04.
- A source caption without both retained graph ownership and acceptable
  external geometry remains evidence-only; P03-US01 never infers it from
  nearby language.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated and adversarial tests pass | Pass |
| Impacted regressions and real benchmarks pass | Pass |
| API/schema and canonical compatibility pass | Pass |
| Frontend visible-path compatibility passes | Pass — composed milestone; manual browser unavailability explicitly retained |
| Security/resource bounds pass | Pass — 64/128/512 fail-closed bounds and linear overflow |
| Final-code metrics and exact input custody retained | Pass |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — no remaining Major |
| No concurrent next story | Pass — P03-US02 was not started before this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US01 is Done. P03-US02 is the
next independently dependency-ready Phase 03 story; no Phase 04 work has
started.
