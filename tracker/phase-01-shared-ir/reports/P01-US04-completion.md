# P01-US04 Completion Report

Status: Done  
Story: Enforce backend/frontend serialization parity  
Points: 5  
Started: 2026-07-29  
Completed: 2026-07-29

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — frontend canonical consumption and parity; no extraction feature or legacy-field removal |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US03 is Done |
| Acceptance measurable | Pass — byte Markdown, ordered text, fallback, JSON preservation, and supported runtimes |
| Dedicated tests identified | Pass — cross-language, frontend unit/API/UI, contract, negative, and corpus gates |
| Fixtures available and authorized | Pass — immutable public/redistributable 15-case corpus plus bounded synthetic payloads |
| API/schema impact documented | Pass — no endpoint change; additive contract with legacy fallback |
| Feature flag identified | Pass — `parser.canonical_serialization.enabled` |
| Rollback defined | Pass — disable the backend contract and retain legacy selection |
| Quality/performance specified | Pass — parity, evidence retention, latency, size, bundle, and cumulative phase ceiling |

Definition-of-Ready result: **10/10 Pass**. P01-US04 was the only story under
implementation.

## Implementation

The frontend now has a strict canonical-presentation boundary in
`lib/canonical-presentation.ts`. It mirrors the Python contract's exact fields,
types, references, uniqueness, scope, omission, suppressor, stored-view, page,
and Python-whitespace invariants without mutating inputs.

`lib/document-api.ts` validates a present contract before returning a result to
the workspace. `lib/serialize-output.ts` returns stored canonical
document/page Markdown. `lib/normalize-document-json.ts` retains the canonical
contract once, preserves raw JSON evidence, and exposes the stored Markdown and
text views. Only absence selects the documented legacy `md`-then-scalar path.

The workspace renders one validated canonical page for display, source, copy,
and download; omitted blocks and legacy raw HTML/OCR cannot enter that path.
README and social metadata document the canonical behavior.

The exact validated frontend was committed locally. Sites publication was
attempted but is unavailable because Sites access is disabled for the
workspace; no credential, project ID, remote, or deployment exists to fabricate.

## Acceptance result

1. Backend/frontend document Markdown byte parity: **Pass — 15/15 canonical
   documents and every page use the stored backend bytes**.
2. Ordered semantic text parity: **Pass — 15/15 document and page text views
   equal the canonical contract**.
3. Older additive fallback: **Pass — 15/15 frozen flag-off documents plus an
   unknown additive type retain documented behavior**.
4. JSON evidence preservation: **Pass — complete payload JSON is preserved,
   raw pages/metadata/future fields remain exact, and canonical data appears
   exactly once in normalized output**.
5. Supported suites: **Pass — Node 22 frontend, Python/Node parity, and the
   complete backend all pass**.

## Verification and metrics

The cross-language story gate passed 49 tests on Node 24.18.0; combined with
the retained Phase 0 projection it passed 50. The complete Phase 0–1
story/regression/contract gate passed 536 tests. The frontend passed ESLint,
TypeScript, production build, 42 unit tests, and one built-output test. The
complete backend passed 804 tests with 10 documented opt-in skips; compilation
and dependency checks passed.

Independent core review matched the TypeScript boundary to Python across 15
real contracts and 239 adversarial mutations. Independent UI/API review also
passed with no blocker.

Canonical normalization p95 is 0.443750 ms. Conservative cumulative Phase 1
p95 is 655.055750 ms, or 1.402480% of the Phase 0 parse p95. The controlled
code-only production bundle delta is 32,603 bytes (0.6811%). The 689,676-byte
social card is reported separately.

Complete evidence is in
[P01-US04-verification.md](../evidence/P01-US04-verification.md).

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — 5/5 criteria |
| Dedicated story tests pass | Pass — 49 cross-language parity tests and 42 frontend unit tests |
| Phase 0 and impacted regressions pass | Pass — 804 full backend plus complete frontend check |
| API/schema compatibility passes | Pass — present strict, absent legacy, endpoint unchanged |
| Unrelated fixtures have no unexplained regression | Pass — all 15 canonical and legacy corpus cases |
| Quality/performance recorded | Pass — parity, mutations, latency, size, and bundle |
| Tracker/configuration documentation current | Pass |
| Feature flag and rollback verified | Pass — default-off backend field and absent-only fallback |
| Completion report and independent review complete | Pass |
| No concurrent next story | Pass — P02-US01 was not started before closure |

Definition-of-Done result: **10/10 Pass**. P01-US04 and all Phase 1 stories are
Done.
