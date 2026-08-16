# FFD-NNN — Short source-grounded title

Status: **Proposed**  
Severity: **Critical | Major | Minor**  
Priority: **P0 | P1 | P2 | P3**  
Primary story: **Pxx-USyy | New story required**  
Dependencies: **None | FFD-NNN**

Policy: [`generic-production-policy.md`](generic-production-policy.md) is
mandatory. Benchmark identity and expected-output lookups are prohibited in
production.

## Scope and impact

- Affected PDF/page/region:
- Affected surfaces: raw Markdown / public JSON / rendered DOM.
- User-visible consequence:
- Explicit non-goals:

## Source-grounded oracle

- Source PDF path and SHA-256:
- Physical page / printed page:
- Region/bbox or exact token/cell/node oracle:
- Source review evidence:
- Expected LlamaParse behavior:
- Actual service behavior:

## Reproducible evidence

- Final v2 comparison evidence:
- Final v2 service JSON/Markdown/DOM:
- LlamaParse job/artifact hashes:
- Primary `FID-*` signals:
- Correlated-signal disposition:
- Reproduction command/profile:

## Root cause

- State: **Confirmed | Hypothesis | Unknown**
- Production boundary:
- Why this is one defect:
- Failure mode and safety constraints:

## Generic production capability contract

- Reusable document feature:
- Identity-independent invariant/algorithm:
- Production decision inputs (must not identify a fixture):
- Deterministic tie-breaking:
- Expected raw/canonical Markdown contract:
- Expected public JSON/schema contract:
- Expected rendered DOM contract:
- Page/order/grouping/provenance contract across all three surfaces:
- Ambiguity boundary and fail-closed representation:
- Safe behavior for malformed/partial inputs at the changed boundary:
- Shared-boundary flag/rollback decision:
- Why this applies to unseen PDFs rather than only the benchmark fixture:

Production must not branch on PDF names/paths, hashes, benchmark case IDs,
fixed pages, fixture-only printed labels, stable fixture element IDs, exact
benchmark strings/coordinates, Llama job IDs/artifact paths, prompt/example
lookups, or memorized outputs. Fixture-specific values belong only in tests and
evidence.

## Acceptance criteria

1. Exact positive requirement.
2. Exactly-once/public-surface requirement.
3. Negative or adversarial requirement.
4. Non-target compatibility requirement.
5. Fresh post-fix LlamaParse + service JSON/Markdown/DOM evidence requirement.

## Defect validation boundary

- Exact defect oracle to validate:
- Named pre-fix symptoms that must disappear:
- Allowed collateral boundary (pages/regions/components/fields/DOM subtree):
- Expected changes inside that boundary:
- Everything outside the boundary is expected to remain unchanged, except:
- Bound pre-fix service Markdown/DOM/JSON artifact paths/hashes:
- Selected prior LlamaParse reference artifact paths/hashes:
- Automated post-fix-versus-pre-fix service Markdown/DOM/JSON drift command/profile:
- Fresh-versus-selected LlamaParse reference drift command/profile:
- Rule for manually adjudicating every changed outside-boundary region:

## Test and rerun plan

- Focused failing regression:
- Positive variant 1 (different identity/content/structure):
- Positive variant 2 (different identity/content/structure):
- Renamed-PDF identity test:
- Batch-reorder test (or reason not applicable):
- Page-offset test (or reason not applicable):
- Negative/adversarial tests:
- Fail-closed assertions:
- Required unrelated control PDFs (minimum two):
- Shared-family suite:
- Wave/all-15 drift gate:
- Cross-surface JSON/schema + Markdown + DOM assertions:

## Immediate affected-benchmark closure gate

Complete this section immediately after the production correction and focused
tests pass. Keep the card in `Validating` until every relevant full benchmark
PDF has passed this gate; do not defer it to the wave or final all-15 campaign.

- Relevant full benchmark PDF(s), run separately:
- Exact source bytes/SHA-256 used by both systems:
- Fresh LlamaParse job ID, settings, timestamp, and artifact root:
- Fresh service build/commit, settings, timestamp, and artifact root:
- Immutable LlamaParse raw Markdown path/hash:
- Immutable service raw Markdown path/hash:
- Actual LlamaParse rendered UI/DOM snapshot path/hash:
- Actual Clearleaf rendered UI/DOM snapshot path/hash:
- Full unprojected LlamaParse JSON path/hash:
- Full unprojected service JSON path/hash:
- Exact defect oracle and named symptoms reviewed:
- Declared collateral boundary used:
- Defect-focused raw Markdown structure comparison result/evidence:
- Defect-focused rendered Markdown UI/DOM comparison result/evidence:
- Defect-focused full JSON structure/content comparison result/evidence:
- Relevant text/OCR/table/form/chart/diagram/image comparison result:
- Automated post-fix-versus-pre-fix complete raw-Markdown drift report path/hash/result:
- Automated post-fix-versus-pre-fix complete rendered-DOM drift report path/hash/result:
- Automated post-fix-versus-pre-fix complete JSON drift report path/hash/result:
- Fresh-versus-selected LlamaParse complete-output drift report path/hash/result:
- Every changed outside-boundary region and manual disposition:
- Remaining difference and explicit acceptable-difference approval, if any:
- Reviewer and pass/fail decision:

A unit, focused, fixture, or schema-test pass is necessary but never sufficient
for this gate. A failure returns the issue to `In Progress`. A pass permits
`Done` only when the remaining closure and genericity gates also pass. The
complete artifacts are retained and automatically drift-compared, but unchanged
unaffected pages and features do not receive an exhaustive manual re-audit at
this immediate gate. The subsequent wave screens and final frozen all-15
dual-system validation remain mandatory.

## Story and change record

- Story action: **Add correction AC | Create new story | Re-adjudicate first**
- Expected production files: **Unknown until Ready**
- Changed files:
- Test commands/results:
- Production prohibited-identifier search command/results:
- Production diff genericity review:
- Fresh artifact paths/hashes:
- Rollout flag/rollback evidence or not-required decision:
- Reviewer/source decision:

## Closure checklist

- [ ] Definition of Ready complete
- [ ] Genericity Definition of Ready complete
- [ ] Reusable capability contract approved
- [ ] Focused regression fails before fix
- [ ] Production correction complete
- [ ] No production branch/lookup uses prohibited fixture identifiers or memorized output
- [ ] Two positive variants pass
- [ ] Rename test and applicable reorder/page-offset tests pass
- [ ] Negative/adversarial controls take the expected unchanged or fail-closed path
- [ ] At least two unrelated PDF controls pass
- [ ] Focused and control suites pass
- [ ] Each relevant full benchmark PDF reruns separately through fresh LlamaParse and service jobs
- [ ] Fresh immutable raw Markdown from both systems retained; defect boundary compared and complete output drift-scanned
- [ ] Full unprojected JSON from both systems retained; defect boundary compared, schema validated, and complete output drift-scanned
- [ ] Actual rendered Markdown UI/DOM snapshots from both systems retained
- [ ] Exact defect oracle, named symptoms, and collateral boundary were declared before implementation
- [ ] Issue-specific three-surface comparison proves the particular defect resolved
- [ ] Post-fix-versus-pre-fix service Markdown, rendered-DOM, and JSON drift reports retained
- [ ] Fresh-versus-selected LlamaParse reference drift report retained
- [ ] Every changed outside-boundary region was manually reviewed and is non-regressive
- [ ] Raw Markdown equals canonical full Markdown
- [ ] JSON/schema, Markdown, and DOM agree on content/order/grouping/provenance
- [ ] Determinism and safe malformed-input behavior pass at the changed boundary
- [ ] Production diff/search review records no prohibited fixture knowledge
- [ ] Flag/rollback evidence recorded where relevant
- [ ] Story, evidence, registry, coverage, and index updated
- [ ] Genericity Definition of Done complete
- [ ] Independent closure review recorded
- [ ] Final all-15 gate remains pending until all tracker defects are closed, or its completed release record is linked
