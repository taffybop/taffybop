# P01-US03 Completion Report

Status: Done  
Story: Generate canonical presentation blocks  
Points: 5  
Started: 2026-07-29  
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — canonical blocks and views from existing IR; no new extraction, reading-order repair, or frontend migration |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US02 is Done |
| Acceptance measurable | Pass — unique contributions, explicit type rules, HTML spans, deterministic output, and reviewed flag behavior |
| Dedicated tests identified | Pass — unit, integration, negative, contract, corpus, serializer, and direct-image coverage |
| Fixtures available and authorized | Pass — immutable public/redistributable 15-case corpus plus bounded synthetic graphs |
| API/schema impact documented | Pass — optional strict `canonical_presentation`; legacy public fields remain unchanged |
| Feature flag identified | Pass — `PARSER_CANONICAL_SERIALIZATION_ENABLED`, default off with both IR prerequisites |
| Rollback defined | Pass — disable canonical serialization and retain the legacy projection |
| Quality/performance specified | Pass — duplicates, determinism, views, output size, p50/p95/max/RSS, and cumulative phase ceiling |

Definition-of-Ready result: **10/10 Pass**. P01-US03 was the only story under
implementation.

## Implementation

`app/services/presentation.py` now derives one strict versioned presentation
contract from normalized `DocumentIR`. It allocates each semantic contribution
to at most one included block, retains excluded and evidence-only identities
for audit, resolves alternatives deterministically, and emits ordered page and
document `full`, `body`, `header`, and `footer` views.

Caption, subordinate OCR, note, footnote, structured-child, nested-visual,
table, and furniture rules are explicit. Structured owners recursively render
only selected descendants, so shared, rejected, or alternate children cannot
leak through flattened values. Span-bearing tables retain identity-safe HTML;
malformed spans fail contextually. Every represented non-ordering relationship
assertion remains auditable.

`app/services/pipeline.py` computes the contract once only when all three
Phase 1 flags are enabled. `app/services/serializer.py` validates the stored
contract strictly and returns its full Markdown instead of rebuilding or
falling back silently. Configuration and runtime documentation describe the
default-off dependency chain and rollback.

The accepted policy is recorded in
[P01-canonical-presentation-policy.md](../decisions/P01-canonical-presentation-policy.md).
The complete frozen-corpus contract is pinned in
[P01-US03-reviewed-differences.json](../evidence/P01-US03-reviewed-differences.json).

## Acceptance result

1. Each semantic element appears at most once: **Pass — 3,009/3,009 unique
   contributing IDs across 274 included corpus blocks**.
2. Captions and subordinate OCR follow explicit rules: **Pass — direct,
   nested, attachment, conflict, rejection, and omission matrices pass**.
3. Tables retain span-capable HTML: **Pass — selected-cell identity and strict
   row/column-span positive and negative tests pass**.
4. Canonical output is deterministic: **Pass — repeated corpus, live PDF,
   randomized graph, alternative-cycle, and strict round-trip checks pass**.
5. Flag behavior and differences are reviewed: **Pass — flag-off legacy
   behavior remains unchanged; 10 changed and 5 byte-stable cases are fully
   pinned with zero unreviewed differences**.

## Verification and metrics

The combined focused/reviewed gate passed 227 tests. The complete backend
passed 755 tests with 10 documented opt-in skips. Python compilation,
dependency integrity, supported-Node TypeScript, lint, production build, 27
frontend unit tests, and one built-output test all passed.

The frozen corpus contains 291 canonical blocks: 274 included and 17 omitted;
233 included body blocks, 13 headers, and 28 footers across 30 pages. The
contract declares nonempty full/body views on all 15 documents and all 30
pages, with header/footer views only where source-supported.

Existing-IR canonical construction measured p50 5.149 ms, p95 86.062 ms, and
maximum 314.818 ms over 3,000 individual observations. Stored serialization
measured p50 0.458 ms and p95 1.858 ms. Maximum benchmark-process RSS was
139.578 MiB. Conservative Phase 1 cumulative p95 is 654.612 ms, or 1.4015% of
the 46,706.960 ms Phase 0 parse p95, below the 5% ceiling.

Two full catastrophe parses produced identical canonical contract and Markdown
hashes, 40/40 unique contributions, strict round-trip equality, exact stored
serializer equality, and no warnings. The known missing Aon source note remains
an honest upstream boundary owned by P03-US03.

Full commands, fixture rationale, output identities, quality, performance,
security, and rollback evidence are in
[P01-US03-verification.md](../evidence/P01-US03-verification.md).

## Independent review

Pass — no production blockers. Independent review covered 209 focused tests,
all 15 frozen cases, 72 nested-visual combinations, 96 nested-attachment
combinations, 300 randomized relationship graphs, and a 500-case alternative
SCC sweep. It confirmed strict validation, deterministic output, unique claims,
complete non-ordering assertion coverage, redaction safety, and exact stored
serialization.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 227 focused/reviewed |
| Phase 0 and impacted regressions pass | Pass — 755 full backend |
| API/schema compatibility passes | Pass — additive strict field, exact flag-off path, stored serializer, and supported frontend build |
| Unrelated fixtures have no unexplained regression | Pass — 15/15 cases fully reviewed; 10 intended changes and 5 byte-stable |
| Quality/performance recorded | Pass — unique claims, views, sizes, p50/p95/max/RSS, cumulative overhead |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default off, prerequisites enforced, legacy fallback retained |
| Completion report and independent review complete | Pass |
| No concurrent next story | Pass — P01-US04 implementation did not begin before closure |

Definition-of-Done result: **10/10 Pass**. P01-US03 is Done. P01-US04 is the
next dependency-ready story.
