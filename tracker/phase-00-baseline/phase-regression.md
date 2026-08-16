# Phase 00 Regression Plan

## Suites

- `tests/stories/phase_00/`
- `tests/regression/phase_00/`
- `tests/contract/`
- existing backend suite: `tests/`

## Required assertions

- Manifest/annotation schema validation is deterministic.
- Fixture hashes and source identities are stable.
- Explicit chart text is never confused with measured/inferred values.
- Baseline JSON and Markdown are stored as evidence, not treated as truth.
- All 15 triplets and 30 physical pages resolve to reviewed page maps; printed
  page labels are recorded separately.
- Expert claims marked incorrect, inferred, or unverifiable cannot enter literal
  truth or exact-parity denominators.
- Custody and redistribution state fail closed; the PDF-only corpus cannot imply
  scanned, direct-image, DOCX, PPTX, or XLSX coverage.
- A repeated corpus run creates a new immutable run ID, executes 15/15 cases,
  reports partial/error states, and emits all semantic report dimensions.
- Positive fixtures preserve source-supported expert text/tables; non-target
  fixtures preserve safer parser refusals; negative controls cover changed
  hashes, unsupported claims, missing cases, partial output, and run-ID
  collisions.
- Current public API/schema behavior remains unchanged.

## Exit report

Record command, environment, parser versions, pass/skip counts, elapsed time,
peak RSS, fixture hashes, output hashes, custody decisions, coverage exclusions,
semantic findings, and all known baseline defects. Compare performance against
the frozen p50 9.06 s, p95/max 46.76 s, median RSS 1,437 MiB, and maximum RSS
2,590 MiB reference values under a declared tolerance.

## P00-US01 evidence

On 2026-07-28, the corrected P00-US01 phase-regression controls passed:
deterministic serialization is stable despite demonstrably different nested
mapping order, and measured evidence cannot enter literal exact parity. The
machine-schema gate also verifies explicit required versions, SHA-256 patterns,
metric units, non-empty commands, and a pinned initial-version wire record.
Its complete synthetic fixture, negative validation controls, command results,
and test-only resource measurement are recorded in
`evidence/P00-US01-verification.md`. No parser run or source corpus artifact was
created or changed.

## P00-US02 evidence

On 2026-07-28, P00-US02 registered the exact approved catastrophe triplet and a
hash-pinned reviewed truth bundle. The separate governance decision is recorded
in `evidence/P00-US02-source-rights.md`; the immutable source claims,
relationships, table grid, chart labels/measurements, calibration, and negative
controls are in `evidence/P00-US02-catastrophe-truth.json`.

The dedicated and regression gate passed 26 tests, the impacted Phase 0,
contract, regression, API, and serializer gate passed 76, the full backend gate
passed 130 with 10 unchanged opt-in skips, and supported frontend typecheck,
lint, and 27 unit tests passed. An adversarial review verified that corrupt
custody links, source identity/geometry/order, relationship semantics, table
cells/spans, chart label/value/year associations, evidence classes, and
negative controls reject. Exact commands, resource measurements, hashes, stale
expert differentiation, and review results are in
`evidence/P00-US02-verification.md`.

No production module imports the test-only contracts. Frozen catastrophe parser
outputs remain unchanged at JSON SHA-256
`3f1f0d9b7768e119d65a887e73f54173df633eeca004e9296bcfeb6aebc91abe`
and Markdown SHA-256
`9d5bb7a233e672f928baa5946af8d54c18de2df187d343bc40e826a455a604e1`.

## P00-US03 evidence

On 2026-07-28, P00-US03 captured five new isolated cold catastrophe runs under
an enforced offline policy. The immutable raw set is
`evidence/P00-US03-baseline-runs-20260728/`; validated summaries are
`evidence/P00-US03-baseline.json` and `.md`, and full command/hash/warning
evidence is in `evidence/P00-US03-verification.md`.

Every run reproduced the exact approved fixture/settings/environment identity,
the same duration-masked semantic JSON, backend/frontend Markdown, frontend
text, and 5-pass/10-fail atomic quality vector. Nearest-rank p50/p95 parse time
is 8,050.770/11,955.223 ms; p50/p95 peak RSS is
1,426.97/1,428.33 MiB. Raw JSON hashes remain distinct because the public
output records its measured duration; no other volatility pointer is allowed.

The final gates passed 26 P00-US03 dedicated/regression tests, 102 impacted
Phase 0/contract/API/serializer tests, 156 full backend tests with 10 exact
owner-tagged opt-in skips, Node 24 typecheck/lint, and 27 frontend unit tests.
Canonical OpenAPI, `ParseResult`, and `ErrorResponse` hashes remain unchanged.
A fresh summary rebuild is byte-identical to the retained JSON and Markdown,
and all five frontend projections rebuild from raw output byte-identically.

No production module imports the runner and no production output behavior,
dependency, feature flag, or configuration changed. The pre-existing Starlette
test-client warning and non-failing Transformers worker deprecation remain
explicit; neither is normalized into a pass.

## P00-US04 evidence

On 2026-07-29, the bounded P00-US04 registered a separate portable corpus
contract without changing the frozen absolute-path analysis manifest. The
registry validates exactly 15 cases, 30 physical pages, and 45 immutable
PDF/Markdown/JSON artifacts from a caller-supplied workspace root. It records
case categories, layout/complex metadata, reviewed printed-page labels, raw PDF
rotation, and the no-exceptions public/redistributable custody decision.

All 45 current artifact bytes and three pinned support records verify. The
registry canonical payload is stable at SHA-256
`f7c3bdf460f64c51a7d7e29765ab1e621dc5f59224ddeba8c8a66959c901e4ca`;
the newline-terminated evidence file is
`f8024ab7a47df2cedf2d10b996fc8eb140404cdafea0b0a0a9ae2bb059263ceb`.
The dedicated/contract/regression gate passed 50 tests, the impacted Phase 0
gate passed 152, the API/schema/serializer gate passed 38, and the full backend
passed 206 with the same 10 explicit opt-in skips and one pre-existing warning.
Node 24 typecheck/lint and all 27 frontend unit tests passed.

Metadata load plus byte verification measured 20.198 ms and 36.188 MiB process
peak RSS. No parser, model, network call, production import, API/schema, feature
flag, or output behavior changed. Full evidence is in
`evidence/P00-US04-verification.md`.

## P00-US05 evidence

On 2026-07-29, P00-US05 added versioned reviewed-claim and inclusion-mask
contracts under `tests/` only. They reuse the unchanged P00-US01 truth classes,
require explicit reviewer/version and review-row provenance, support
multi-page registered locators, separate literal/semantic masks, require
method/tolerance/unit for measured evidence, and reject unsupported truth
promotion.

The frozen P00-US02 truth projects into 163 generalized claims and back to
identical P00-US01 annotations: 32 visible-text, 33 native-data, 89 measured, 8
inferred, and 1 unknowable; 62 are literal-scored and all 163 retain reviewed
semantic expectations. The canonical batch hash is
`225fc37091849cc4ab7535b7e1dd51c9c1aa390fa2cb50feba051299ae14da71`.

The focused gate passed 48 tests, Phase 0 regression passed 17, the impacted
gate passed 200, API/schema/serializer passed 47, and the full backend passed
254 with 10 unchanged opt-in skips. Frontend typecheck/lint and 27 unit tests
passed. Contract validation measured 14.416 ms and 37.406 MiB maximum RSS in
one fresh process. No production behavior or frozen evidence changed. Full
evidence is in `evidence/P00-US05-verification.md`.

## P00-US06 evidence

On 2026-07-29, P00-US06 registered exactly 71 narrative expert-validation
rows from five cases as strict reviewed claims: 44 verified, 17 partially
verified, 6 not independently verifiable, and 4 incorrect. The claims use 75
registry-valid locators, 41 literal masks, 61 semantic masks, and one measured
derivation. Grouped source rows remain one-to-one and no unsupported field
enters literal parity.

The canonical semantic batch SHA-256 is
`f6f0ef58f4cb1379f808e8d5bb7253f260a8f643a83e98e75e4d2e1a3fff01ee`;
the newline-terminated evidence file is
`f987d84ca1b0d08dfd304d7ea3164a78366643f4b42ef03bc4975d4d09548de4`.
The focused and Phase 0 regression gates each passed 22 tests, the impacted
gate passed 222, API/schema/serializer passed 55, and the full backend passed
276 with 10 unchanged opt-in skips. Frontend typecheck/lint and 27 unit tests
passed. Validation measured 11.716 ms and 36.156 MiB maximum RSS in one fresh
process. Independent review passed. Full evidence is in
`evidence/P00-US06-verification.md`.

## P00-US07 evidence

On 2026-07-29, P00-US07 registered the next 76 one-to-one review rows across
five cases. Batch B contains 43 verified, 15 partially verified, 8 incorrect,
5 potentially inferred, and 5 not-independently-verifiable claims. It uses 121
registered locators, 36 literal masks, 58 semantic masks, and no measured
evidence or derivations.

The canonical Batch B semantic SHA-256 is
`9afe6c098adcd32e3a8370af5ecb2b27ac4730f098e39128e787eef991990d0f`;
the newline-terminated evidence file is
`7e4728c1c5d76a6453d42c640de8a25c24989ed3a160cac2fe4640b22a55814e`.
Batch A remains byte- and semantic-stable.

The focused gate passed 23 tests, Phase 0 regression passed 27, the impacted
gate passed 245, API/schema/serializer passed 63, and the full backend passed
299 with 10 unchanged opt-in skips. Frontend typecheck/lint and 27 unit tests
passed. Loading and comparing both batches and serializing Batch B measured
21.561 ms and 37.156 MiB maximum RSS. Independent review passed. Full evidence
is in `evidence/P00-US07-verification.md`.

## P00-US08 evidence

On 2026-07-29, P00-US08 registered the final 63 one-to-one review rows across
five cases. Batch C contains 34 verified, 9 partially verified, 9 incorrect,
6 not-independently-verifiable, and 5 potentially inferred claims. It uses 75
registered locators, 32 literal masks, 43 semantic masks, and three bounded
Uber vector derivations. The health chart remains incorrect and inferred
without fabricated derivation metadata.

The canonical Batch C semantic SHA-256 is
`69c58b8ab7a3b9bdd21bc49183fb5334ee88bee1a4850061820b551ae416eb89`;
the newline-terminated evidence file is
`1411d75d2701e51b815f9f3c0e0e5ba5f799f6ec32ca2788cd31ee4f69f05be1`.
Batches A and B remain byte- and semantic-stable. Together, all three batches
contain exactly 210 unique claims across 15 cases and 271 locators, with 109
literal and 162 semantic masks.

The focused gate passed 25 tests, prior-batch compatibility passed 45, Phase 0
regression passed 32, the impacted gate passed 270,
API/schema/serializer passed 73, and the full backend passed 324 with 10
unchanged opt-in skips. Frontend typecheck/lint and 27 unit tests passed.
Loading and comparing all three batches and serializing Batch C measured
26.920 ms and 37.203 MiB maximum RSS. Independent review passed. Full evidence
is in `evidence/P00-US08-verification.md`.

## P00-US09 evidence

On 2026-07-29, P00-US09 converted the frozen 25-row gap/story matrix and all
109 case-gap rows into a strict canonical control registry backed by the
completed 210-claim corpus. Every owner has exactly four distinct roles:
target, related positive, non-target regression, and negative or ambiguous.
All 209 role/row references resolve exact case/claim/region identities.

The positive and non-target roles require supported semantic evidence. The 25
negative/ambiguous controls are mask-false and divide into 13 incorrect, 7
not-independently-verifiable, and 5 potentially inferred claims. Frozen matrix,
report, role-policy, row, claim, locator, and canonical-payload drift fail
closed. The one missing postal page-identity review is retained as an explicit
mask-false metadata proxy rather than fabricated truth.

The semantic/file identities are
`d3c734957b507f07508f8eeffe43ac450f50f53d5f42f8cf63e354fe60738fce`
and
`a383938d41d067e0b3e01729d12def7b573764092100ef76228e4c23707c86b5`.
The focused gate passed 57 tests, completed Phase 0/contract/regression passed
305, API/serializer passed 22, and the full backend passed 381 with 10
unchanged explicit opt-in skips. Supported frontend and Python compile gates
passed. Fifty strict reload/build comparisons measured p50 71.899 ms, p95
75.652 ms, and 41.484 MiB peak RSS. Independent review reproduced all
identities, counts, locators, masks, custody, API isolation, and rollback with
no blockers. Full evidence is in `evidence/P00-US09-verification.md`.

## P00-US10 and Phase 0 exit evidence

On 2026-07-29, P00-US10 retained a fresh strict two-case integration and a
fresh full 15-case offline run without changing or overwriting any earlier
artifact. The final full run completed 15/15 cases and 30/30 pages with zero
partial, error, timeout, or skip states. All 45 registered source/expert
artifacts, 15 raw worker records, and 15 coordinator projections are
hash/size-bound. Existing run directories and noncanonical run-ID/directory
pairings reject.

The semantic report preserves all 210 reviewed claims and their locators:
109 literal masks, 162 semantic masks, and 48 unsupported exclusions. Because
the narrative review rows are not executable expected-value predicates, all
162 eligible claims remain explicitly diagnostic-only and the automatic score
count is zero. All 48 incorrect, inferred, or unverifiable expert claims and
all 25 negative/ambiguous controls remain outside scored denominators.

All 12 canonical dimensions are present separately. All 15
duration-masked JSON outputs and all 15 exact Markdown outputs match the
frozen reference. On the matching environment, coordinator latency p50/p95 is
9,817.816/46,706.960 ms and RSS p50/max is
1,503,772,672/2,569,650,176 bytes; all predeclared 25% upper bounds pass.
Hosted requests, tokens, and billed cost are zero.

The final focused gate passed 79 tests, the complete Phase 0 story/contract/
regression gate passed 384, API/serializer passed 22, and the full backend
passed 460 with the same 10 explicit opt-in skips. Supported frontend
typecheck, lint, build, 27 unit tests, one built-output test, and Python
compile passed. Independent review reproduced the run trees, bindings,
claims/masks/controls, dimensions, stable outputs, performance, cost, frozen
legacy/API identities, production isolation, and additive rollback with no
blockers.

All ten Phase 0 stories and all 44 points are Done. The Phase 0 exit criteria
pass. Phase 1 has not started and requires new explicit authorization.
Complete evidence is in `evidence/P00-US10-verification.md` and
`reports/phase-summary.md`.

## 2026-08-13 P00-US10 live functional-fidelity evidence

The `functional-fidelity-20260813` extension retains all 15 fresh Agentic
LlamaParse references and the matching public-service outputs across 30
physical pages. The fail-closed artifact manifest verifies 15 raw Markdown +
15 full JSON outputs per system, 30 LlamaParse rendered DOM + PNG pairs, 30
Clearleaf rendered DOM pages, 30/30 successful service HTTP format responses,
and exact service Markdown/canonical-JSON parity. Its two focused manifest
tests pass. Semantic analyzer evidence remains per-PDF and per-page under the
existing 25 gap owners; release remains fail-closed while functional findings
or manual-review findings remain.
