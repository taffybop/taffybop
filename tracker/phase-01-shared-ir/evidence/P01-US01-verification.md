# P01-US01 Verification Evidence

Date: 2026-07-29  
Status: Pass

## Scope and compatibility

- Internal IR version: `1.0`.
- Feature flag: `PARSER_SHARED_IR_ENABLED`, default `false`.
- Public endpoint/schema version: unchanged `POST /v1/parse`, schema `1.0`.
- Default-off path returns the original payload object without importing or
  executing the IR adapter.
- Enabled path validates the IR and immediately produces the lossless v1
  compatibility projection; no internal IR field is exposed.
- No dependency version changed and `pip check` reports no broken requirements.

The Phase 01 schema decision requires optional additive evolution and an
unchanged flag-off projection. OpenAPI, ParseResult, and ErrorResponse hashes
remain on their Phase 0 pins.

## Contract and negative coverage

The focused tests cover:

- strict Document/Page/Region/Element/Evidence/Relationship records;
- native, OCR, vector, embedded, recovered, model, and derived methods;
- typed confidence or an explicit unavailable reason on every evidence record;
- deterministic IDs that remain stable when source arrays are reordered;
- PDF-point and image-pixel coordinate spaces;
- declared transforms and explicit unavailable reasons for undeclared
  cross-unit transforms;
- contains, caption, source-note, footnote, legend, axis, annotation,
  alternative, and reading-before relationships;
- complete page, region, element, bbox, evidence, and relationship ownership;
- rejection of dangling IDs, invalid transforms, cross-page ownership,
  cross-owner evidence, false native labels on generated content, self-links,
  and forbidden cycles;
- a 1,200-element / 1,199-edge reading chain without recursion failure;
- live `_parse_loaded_document` execution with the feature off and on.

## Retained-corpus result

All 15 immutable P00-US10 outputs (30 pages) were adapted:

| Measure | Result |
|---|---:|
| Exact v1 compatibility projections | 15/15 |
| Primary items retained | 291/291 |
| Observed current primary item types | 9/9 |
| Total IR elements | 3,799 |
| Total evidence records | 3,805 |
| Total relationships | 3,769 |
| Rejected OCR alternatives retained | 2/2 |
| Dangling/cross-owner graph references | 0 |

The nine observed primary types are text, heading, header, footer, list, table,
image, chart, and diagram. The adapter also retained 2,597 table cells, 859
nested items, and all current rejected OCR candidates as typed subordinate or
diagnostic elements.

## Quality and performance

Ten adaptations of each retained case produced 150/150 exact projections:

| Measure | Result |
|---|---:|
| Adapter p50 | 10.395 ms |
| Adapter p95 | 488.363 ms |
| Adapter maximum | 528.361 ms |
| Phase 0 parse p95 | 46,706.960 ms |
| Adapter p95 / Phase 0 parse p95 | 1.0456% |
| Largest retained case traced peak | 16.634 MiB |

This is below the Phase 01 cumulative p95 ceiling of 5%. Flag-off adapter
overhead is one boolean branch and the live flag-off/on duration-masked payload
hashes are equal.

## Test gates

- Focused P01-US01 story/regression: 21 passed.
- Completed Phase 0 story/contract/regression gate: 384 passed.
- API and serializer compatibility: 22 passed.
- Full backend: 481 passed, 10 documented opt-in model/integration tests
  skipped, one pre-existing Starlette/httpx deprecation warning.
- Python compilation: pass.
- Dependency integrity: pass.
- Supported frontend baseline: lint, typecheck, production build, 27 unit tests,
  and one built-output test passed on Node 22.18.0; no frontend runtime behavior
  changed in this story.
- Frozen P00-US10 two-case and full-corpus verification: pass and read-only.

## Security and custody

All benchmark inputs remain within the authorized public/redistributable
project scope. No source triplet, reviewed annotation, retained run, or prior
baseline was rewritten.

An unreferenced local frontend fixture contains expired presigned asset URLs.
It is absent from the build and is now explicitly ignored by source control;
the credential-bearing contents were not printed, copied, or committed.

## Independent review

Pass after two repair rounds. The reviewer found and verified fixes for
cross-unit coordinate fidelity, source-order round trips, graph ownership,
semantic relationship population, mixed model/OCR evidence, all-current-type
coverage, flag-off hash parity, recursive graph validation, and
position-dependent IDs. No blocker remains.

The reviewer noted one bounded follow-on: a legacy
`caption_source=document_caption` field alone cannot always distinguish native
from OCR provenance. P01-US02 owns preservation of the raw caption reference
and its own source evidence.

## Rollback

Set `PARSER_SHARED_IR_ENABLED=false` (the default) to bypass the adapter.
Removing the additive IR module, its flags, tests, and documentation restores
the pre-story code path. Retained Phase 0 evidence stays immutable. The
historical-verification decision should remain in later-phase checkouts because
it separates immutable historical provenance from evolving live source.
