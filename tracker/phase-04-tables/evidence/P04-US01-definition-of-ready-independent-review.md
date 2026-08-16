# P04-US01 Definition-of-Ready Independent Review

Date: 2026-08-03  
Status: **10/10 Pass — independent readiness approval recorded**  
Scope: P04-US01 readiness inputs and plans only

This is a fresh, non-recursive review of the policy, story, readiness record,
source-qualified oracle, synthetic controls, contract/story tests, and frontend
readiness-plan test. It does not approve implementation or completion, change a
story status, or alter production, Phase 05, source, or benchmark artifacts.

## Definition of Ready

| Requirement | Result |
|---|---|
| 1. Scope and non-scope explicit | **Pass** — span evidence, explicit repeated cells, multilevel/rotated headers, logical rows, isolated selected grids, provenance, and serializers are bounded in scope; candidate reconciliation and multi-page tables are explicitly excluded. |
| 2. Points at most 5 | **Pass** — 5 points. |
| 3. Dependencies Done | **Pass** — sole predecessor P03-US01 is `Done`, with its completion report present. |
| 4. Acceptance measurable | **Pass** — source-qualified criteria pin Exhibit 7 at 6 x 5 / 30 cells / five separate `United States` values; enumerate finance, postal, clinical, timetable, and ACORD facts; require zero fabricated spans/row shifts; and restrict exhaustive representation parity to exact-cell truth. |
| 5. Dedicated tests identified | **Pass** — backend contract and story paths plus a frontend readiness-plan path exist; the production frontend path is explicitly deferred to implementation. |
| 6. Fixtures available and legally usable | **Pass** — all six exact PDFs exist and match their pinned sizes, page geometry, page counts, and SHA-256 identities. Custody is the accepted requester/provider `public-redistributable` attestation; the record correctly discloses that no independent license review or named license was supplied. |
| 7. API/schema/frontend impact documented | **Pass** — the additive schema-v1 sidecar, closed cells/slots/evidence contract, predecessor compatibility, escaped React grid, strict reader, responsive viewports, fallback, and copy/download parity plan are explicit. |
| 8. Feature flag identified and default off | **Pass** — `parser.tables.span_fidelity.enabled` / `PARSER_TABLES_SPAN_FIDELITY_ENABLED`, default `false`; the flag-off witness requires all four Phase 04 flags false, zero readiness-fixture/stage calls, and exact predecessor/output byte identity. |
| 9. Rollback defined | **Pass** — disabling span fidelity restores prior selected-table normalization and serialization; policy requires complete predecessor page/table/canonical restoration on failure. |
| 10. Quality and performance specified | **Pass** — quality denominators are numeric and source-qualified; stage p95 overhead is <= 10%, peak-RSS delta <= 67,108,864 bytes, marked-table output <= 8,388,608 bytes, document Phase 04 sidecars <= 67,108,864 bytes, and deadlines are <= 0.500 seconds/page and <= 5.000 seconds/document. |

Definition-of-Ready result: **10/10 Pass**. This approves the readiness package,
not implementation completion or any story-status transition by this review.

## Source and truth verification

| Source PDF | Bytes | Pages | Raw SHA-256 |
|---|---:|---:|---|
| `catastrophe-recap.pdf` | 58,779 | 1 | `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e` |
| `finance-10k.pdf` | 87,105 | 3 | `e924db5e2dbe8845997093d550b3dcdea5560b5c4a75957b6ef084f556149086` |
| `postal-10k.pdf` | 83,589 | 3 | `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74` |
| `clinical-study.pdf` | 750,004 | 4 | `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2` |
| `ny-timetable.pdf` | 26,109 | 3 | `f9c4069d4a7910d64de79c0f0635c009a4d20f092c4ca09deebfa2f6a2d7bd30` |
| `insurance-acord.pdf` | 17,086 | 1 | `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4` |

Independent render and source-report review confirmed the scored facts: Exhibit
7's 30 explicit cells and five repeated locations; finance page-1/page-3
three-column period headers and page-2 logical wrapped row; postal's 40-row,
two-column glossary ending in `FERS` plus page-2/page-3 period headers;
clinical's six- and nine-column structures, stub-only rows, and reviewed 4+3
group headers; and each timetable page's 13 columns and 50 service rows,
including page-3 source row 28 with `3:32`. ACORD remains a form-owned region
with only its exact region bbox and three visible labels addressable; topology,
ownership, spans, cell boxes, and cell provenance remain unresolved and cannot
enter canonical-table accuracy.

Every unscored qualified-table dimension is disjoint from scored denominators
and has exactly one dimension-specific fail-closed concern. The exact Exhibit 7
projection is bound to the P00 truth file at raw SHA-256
`d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac`.

## Controls, bounds, and isolation

The 17-item synthetic registry is substantive: eight complete canonical grids,
three distinct fail-closed grids, five malformed/resource validation controls,
and one flag-off identity witness. Positive row/column spans bind one decision
to separate geometry and structure evidence backed by two independently
addressable source objects. Negative controls exercise repeated values, visual
wraps, ambiguous/partial/form grids, overlap, duplicate positions, negative
indexes, non-finite geometry, hostile cell text, missing or duplicate evidence,
and fan-out overflow.

The closed models enforce strict types and unknown-field rejection; finite
geometry; UTF-8 byte caps; NUL/C0/DEL rejection; identifier/reference caps;
portable forward-slash paths; rejection of traversal, absolute, drive/URI,
encoded, tilde, backslash, empty/dot, whitespace, and non-portable segments;
and resolved symlink containment. Exact-bound resource witnesses pass and
maximum-plus-one witnesses fail for all 16 registered counters.

Import inspection found only standard-library, Pydantic, pytest, pdfplumber,
and `tests.fixtures.phase_04` imports. No production configuration, parser,
serializer, API, or frontend module is imported. All four P04 story files and
all ten P05 story files remained `Proposed`; no production or P05 file was
changed by this review.

## Audited package identities

| Artifact | Bytes | Raw SHA-256 |
|---|---:|---|
| Policy | 15,116 | `81ae5843129bd0903d7b4517eb90d1100e0aaf8b7c46715d55bdcd9788903cc2` |
| P04-US01 story | 7,213 | `1238f97d3e3595279d6cf7c6df71f4ef3481f83589028160a5205411bbc3deb3` |
| Metrics | 3,114 | `c6c51cee8e987dc5e018936bc29121a32787a17a0bdd8221646f19d0c3939a0b` |
| Readiness evidence | 9,714 | `4b6d51f4144c720b796c4210f04f6851beef9641b9bccaff68349b3812ed835b` |
| Contract test | 6,723 | `b6967f31b25ec201f2a5552d1539e534a213a013bdbc532c2ae919d017d30a2b` |
| Story test | 27,818 | `551ca0e894759eb71d07fa0e95767b1ba0153ce7237b5fecc33fb88c1a0afeba` |
| Frontend readiness test | 2,158 | `e0635f4564b0f462e3a9fc04bb7125cfecafca4f67603f79ef92d14baccb2979` |
| Phase 04 fixture package | 40 | `abbecc08d2706d9345b9c10809b02ee787ee6e310d246ebd02575aa6b93f1074` |
| Table fixture package | 742 | `d475f22d170d885685369cbb5bd457a8ac2a84630dc3bd6f6e5c63f2ceca8769` |
| Fixture contract | 36,176 | `c62b3b401e9782b4c9326dd8d179d7adaf4c2585034068a150adf57f039928d9` |
| Real oracle | 21,532 | `41fd4b6b4330d9f13d9aa8c48ede4a43f2bc807767a80790fc893acebbd84ae6` |
| Synthetic controls | 26,992 | `a67037f72dce9153c934aa3234fbad3daf3580c35ad4e6b4479c53594104b094` |

Canonical oracle semantic SHA-256:
`d34eba8a3a4fce187d607eb95fa61d85e9a3f473522718fe488fabeb4d6950e3`.
Synthetic registry semantic SHA-256:
`0ef6b9689c9f4edbde4e273c9d1a0e2f63366ea0cbcd5ce3c909eecaa17b8bee`.

## Fresh execution results

- Focused backend contract/story: **101 passed, 0 failed, 0 skipped, 1
  pre-existing Starlette deprecation warning in 0.25 seconds**.
- Focused backend plus table normalization/classification regression: **108
  passed, 0 failed, 0 skipped, 1 pre-existing warning in 0.31 seconds**.
- In-memory compilation: **8 Python files compiled successfully** across the
  Phase 04 fixtures/stories and P04 contract test.
- Exact Node **24.14.0** frontend readiness test: **3 passed, 0 failed, 0
  skipped**.
- Focused frontend ESLint: **pass, exit 0**.
- Frontend TypeScript `--noEmit` typecheck: **pass, exit 0**.

The frontend shell emitted only the known non-test `pyenv` rehash notices; all
three frontend commands exited zero.

## Deferred implementation and completion gates

This review does not claim production behavior, measured after-values,
TEDS/GriTS, parser or corpus correctness, API/serializer/frontend implementation,
enabled-path or production frontend tests, full regressions, build/bundle and
responsive rendering, final latency/RSS/output measurements, rollback drill,
completion evidence, P04-US01 `Done`, later Phase 04 readiness, or Phase 04
exit. Those gates remain mandatory during implementation and completion. P05
remains outside the authorized boundary.
