# Phase 04 Backlog

Release-first override (2026-08-10): use the story-local release acceptance
criteria and the [shared policy](../release-first-phases-04-08.md). The table
below preserves ordering and functional dependencies; benchmark/evidence
campaign language is deferred. P04-US01, P04-US02, P04-US04, and P04-US03 are
release-first complete. Phase 04 is complete under that standard; Phase 05 has
not been started.

Historical status: Phase authorized on 2026-08-03; the exact hardened P03-US08 renewal
received final independent approval on 2026-08-04; the sponsor-authorized
2026-08-07 administrative continuity renewal now permits only unrelated,
default-off Phase 04 table development and its exact classifier received
independent policy/custody approval on 2026-08-07. P04-US01 entered In Progress
at that historical checkpoint, but on 2026-08-08 returned to **Ready —
execution paused** when Phase Latency became the sole active workstream. The
other three stories remain Proposed. The classifier
approval does not replace P04-US01 final-code or story reviews. Canonical v11
attempt 01 failed closed and remains sealed. The unapproved v12 leased-
identity design and all accidental preapproval activity remain history. The
initial v13 compact-transport implementation was rejected by two independent
reviews on 2026-08-07. Its exact rejection is immutable at
[`P04-US01-v13-initial-exact-bundle-independent-review-rejected.md`](evidence/P04-US01-v13-initial-exact-bundle-independent-review-rejected.md).
Corrective successor work is not yet frozen or approved and has no
predeclaration, candidate, qualification, or canonical campaign authority.

| Story | Points | Acceptance summary | Dedicated test path | Dependencies |
|---|---:|---|---|---|
| [P04-US01](stories/P04-US01.md) — **Done (release-first)** | 5 | Explicit cells, multilevel/rotated headers, multiline rows, and source-supported spans remain faithful on focused representative grids | `tests/stories/phase_04/test_p04_us01_span_fidelity.py` | P03-US01 |
| [P04-US02](stories/P04-US02.md) — **Done (release-first)** | 5 | Competing table candidates resolve by coverage/geometry without silent loss | `tests/stories/phase_04/test_p04_us02_table_reconciliation.py` | P04-US01, P02-US04 |
| [P04-US04](stories/P04-US04.md) — **Done (release-first)** | 5 | Table candidates are gated against chart/form ownership; true borderless/dense tables emit or fail closed with structural concerns | `tests/stories/phase_04/test_p04_us04_table_candidate_gate.py` | P04-US02, P03-US06 |
| [P04-US03](stories/P04-US03.md) — **Done (release-first)** | 5 | Only gated, verified continuations merge; headers/spans/provenance and serializer parity remain correct | `tests/stories/phase_04/test_p04_us03_continued_tables.py` | P04-US02, P04-US04, P03-US04 |

Total: 20 story points.

## Canonical latency contract

The sole prospective latency benchmark for every Phase 04 story is the
[`Phase 04 LlamaParse latency supersession`](decisions/P04-LlamaParse-latency-canonical-supersession.md),
using
[`LlamaParse latency reference v1`](../benchmarks/llamaparse-15/latency-reference-v1.md).
The reference fixes LlamaCloud Parse v2, Agentic 10 credits/page, cost optimizer
off, cache disabled, and provider UI **Total Latency**. The 2026-08-08 single
sample per case is a planning/reference ceiling only. Before Definition of Done
or phase exit, refresh each applicable case with at least five interleaved
candidate/Llama samples and require candidate p50 and inclusive nearest-rank
p95 to be no greater than the paired Llama p50/p95, case by case. Do not mask a
failure with a corpus average or omit failed runs.

Semantically incomparable cases are **Unmeasured/Blocked**. Local M0,
predecessor flag-off, and stage/component timings are diagnostics only. A
latency result cannot compensate for a quality or reliability failure, and the
existing correctness, RSS/memory, security, compatibility, custody/hosted-use,
resource, output, timeout/fail-closed, default-off, and rollback gates remain
unchanged. This planning update changes no story status and does not authorize
Phase 05.

## Governing benchmark gaps

- P04-US01–US03: `GAP-TABLE-002`, `GAP-TABLE-003`, `GAP-BBOX-001`,
  `GAP-OCR-001`, `GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`, and
  `GAP-SERIALIZATION-001`.
- P04-US04: `GAP-TABLE-001`, `GAP-TABLE-002`, `GAP-FORM-001`,
  `GAP-BBOX-001`, and `GAP-DIAGNOSTICS-001`.
