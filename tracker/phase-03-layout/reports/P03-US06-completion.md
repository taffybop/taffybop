# P03-US06 Completion Report

Status: Done  
Story: Extract form controls and key-value relationships  
Points: 5  
Started: 2026-07-31

## Definition of Ready

| Requirement | Result |
|---|---|
| Scope and non-scope explicit | Pass — source-visible static/interactive forms, controls, empty/value regions, and aligned key-values; no filling, signing, insurance inference, OCR-only controls without a reviewed twin, or Phase 04 table recovery |
| Points at most 5 | Pass — 5 |
| Dependencies Done | Pass — P01-US02 and P03-US04 |
| Acceptance measurable | Pass — exact ACORD 6 groups, 42 labels, 24 empty fields, 24 controls, 216 relationships; exact component 16 pairs and 80 relationships; zero fabricated values |
| Dedicated tests identified | Pass — story, integration, negative, contract, real-corpus, frontend, resource, rollback, performance, and custody paths |
| Fixtures available and authorized | Pass — immutable ACORD/component PDFs plus 25 deterministic local synthetics covering 37 named capabilities, 20 AcroForm boundaries, and 8 semantic/relationship graph boundaries |
| API/frontend impact documented | Pass — strict additive public sidecars, six typed IR variants, closed enums/cardinalities, exact relationship backlinks, canonical contributor custody, safe read-only rendering, and authoritative fallback |
| Feature flag identified | Pass — `PARSER_LAYOUT_FORMS_ENABLED` / `parser.layout.forms.enabled`, default false with zero flag-off extractor/projector work |
| Rollback defined | Pass — affected-page atomic restoration and complete-stage rollback for document-global source, custody, deadline, and aggregate failures |
| Quality/performance specified | Pass — frozen source/oracle denominators, isolated production exact/max+1 resource counters, direct defensive-schema boundaries, deterministic AFOB-v1 accounting, isolated p95/allocation gates, five paired fresh-process samples, RSS normalization, and zero hosted use |

Definition-of-Ready result: **10/10 Pass**. Independent source-truth,
schema/custody, algorithm/fixture, and final contract/security/performance
reviews found no remaining blocker. At that readiness transition P03-US06 was
the sole story In Progress; P03-US07–US08 remained Proposed and no Phase 04
work had started.

The accepted contract is
[P03-form-and-key-value-semantics-policy.md](../decisions/P03-form-and-key-value-semantics-policy.md).

## Accepted source truth

The immutable inputs are:

- `insurance-acord.pdf`: 17,086 bytes,
  SHA-256 `85571deac2362e67829587656d915df1b4d1683f9df62f3b77971743a963cfd4`;
- `component-datasheet.pdf`: 329,199 bytes,
  SHA-256 `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`.

The reviewed ACORD denominator fixes six logical groups, 19 field labels,
three group headings, 20 control labels, 24 empty fields, 19 unchecked and
five ambiguous controls, and no checked control. Its exact graph is 114
`contains`, 53 `label_of`, 24 `value_of`, 24 `control_of`, and one
`form_overlay_of` relationship. All ACORD form groups are canonical-inert and
the mixed coverage table remains available for Phase 04.

The component denominator fixes three same-page borderless key-value groups
with 4 + 7 + 5 ordered pairs. Its exact graph is 48 `contains`, 16 `key_of`,
and 16 `value_of` relationships. Only these three reviewed groups may replace
their exact, ordered predecessor contributors in canonical Markdown/text.

Every public contributor is paired with its exact predecessor internal element
ID. Fresh source review confirmed same-page uniqueness, exact anchor indexes,
mutually disjoint replacement sets, and unchanged predecessor canonical
hashes.

## Readiness fixtures and limits

The deterministic registry in
`tests/fixtures/phase_03/form_semantics/synthetic.py` contains 25 fixtures with
25 unique hashes. Both pdfplumber and pypdfium2 accept/render every applicable
PDF. The registry covers all 37 named form/control/key-value capabilities,
20 independently isolated AcroForm exact/max+1 cases, and eight valid
single-owner semantic/relationship boundary graphs.

The frozen semantic caps are 8,192 records/page and 32,768/document; the
relationship caps are 32,768/page and 65,536/document. AcroForm traversal
separates 32,768 distinct visited references from 65,536 resolution steps and
uses deterministic `AFOB-v1` local object/tree accounting. Exact witnesses
remain below every non-target cap; max+1 witnesses exceed only their named
target.

The approved per-group reconciliation preserves the 262,144-byte public JSON
cap, 64 contributors, and every page/document aggregate. Exact group maxima
are 128 fields and value regions, 256 controls, 256 labels, 32 key-value
pairs, and 13 distinct concern codes. The four structural witness sizes are
260,530, 259,952, 247,413, and 93,075 bytes respectively; the concern witness
is also below 256 KiB. A
production-shaped 32-pair/64-contributor witness is 95,105 bytes and pair 33
is refused at 66 contributors. Exact materialization is required for frozen
resource-table counters. Defensive Pydantic list ceilings outside that table
retain direct exact/max+1 validator tests and may be shadowed by topology or
the stricter public-group byte cap.

Python compilation, the exact Ruff 0.15.22 binary, deterministic fixture
self-checks, and reader checks pass at this transition.

## Implementation and acceptance

The default-off local stage now extracts bounded source evidence, projects
strict typed form records and relationship graphs, preserves canonical
contributors, and restores the configured predecessor atomically on page- or
document-scope failure. Public JSON remains additive and schema version `1.0`;
canonical Markdown/text remains authoritative.

The frozen real-corpus results are exact:

- ACORD: **6** groups, **42** labels, **24** empty fields, **24** empty value
  regions, **24** controls (**19** unchecked, **5** ambiguous), and **216**
  relationships. No checked state or value is fabricated, and the mixed
  coverage table remains canonical with a form overlay.
- Component datasheet: **3** replace-mode groups, **16** ordered key-value
  pairs, **16** labels, **16** present value regions, and **80** relationships.
  Contributor custody, Markdown, text, JSON, source order, and idempotence are
  exact.
- Non-target, malformed, cyclic, transform, geometry, source-size, candidate,
  relationship, comparison, deadline, concern, and max+1 cases fail closed
  without partial sidecars.

The frontend validates the same role caps—128 fields/value regions, 256
controls/labels, 32 pairs, 13 concern codes, and 256 KiB complete sidecar—then
renders safe read-only React structures. Malformed or inconsistent sidecars
fall back to authoritative canonical content. No live inputs, source mutation,
raw HTML, or client-side relationship inference was added.

## Verification and independent review

- focused story/contract/adversarial/real-corpus gate: **142 passed**, with 12
  documented upstream deprecation warnings;
- isolated performance/resource gate: **19 passed**, with 6 documented
  upstream deprecation warnings;
- final cap/source-security slice: **26 passed**;
- frontend Node 22.18 lint, typecheck, production build, **84/84 unit**, and
  **1/1 bundle**: **Pass**;
- Python compilation, Ruff 0.15.22, deterministic 25-fixture self-check, and
  pdfplumber/pypdfium2 reader checks: **Pass**;
- independent algorithm/security review: **Pass**;
- independent projection audit: **70 focused tests**, 100,000 coverage-oracle
  queries, 2,500 ruled-cell brute comparisons, 10,000 randomized compact-JSON
  checks, exact comparison ledgers, output isolation, and no blocker; and
- independent final metrics/custody review: **Pass** for all 34 bound code
  paths, both immutable inputs, the sealed US05 predecessor, formulas,
  deterministic outputs, and zero hosted use.

No controllable browser surface was available. As in prior Phase 03
checkpoints, automated visible-path rendering, normalization, source/page,
copy/download, build, and bundle gates pass; manual click-through is not
claimed and remains a Phase 03 exit retry.

## Performance, resources, and retained evidence

The final controlled campaign records:

- ACORD extraction p50/p95 **75.456/76.933 ms**, peak allocation
  **16,851,449 bytes**, report **425,351 bytes**;
- component extraction p50/p95 **178.592/181.412 ms**, peak allocation
  **11,262,672 bytes**, report **537,282 bytes**;
- ACORD projection p50/p95/max **42.478/44.532/46.016 ms**, peak allocation
  **6,458,160 bytes**, and **59,849/65,536** page comparisons;
- component projection p50/p95/max **27.234/28.097/28.155 ms**, peak allocation
  **5,392,187 bytes**, with page ledgers **10/5,327/2,328**;
- exact/max+1 256/257-group projection **96.587/5.139 ms**; max+1 restores the
  page and emits only `form_projection_failed_closed`;
- five alternating fresh-process pairs: ACORD clipped p95 **300.827 ms** below
  the **453 ms** effective ceiling, and component **516.890 ms** below the
  **528 ms** effective ceiling; and
- maximum paired RSS deltas **42,844,160** and **11,255,808 bytes**, both below
  64 MiB. Hosted requests/tokens/cost are **0/0/$0**.

The accepted retained artifact is
[P03-US06-form-metrics.json](../evidence/P03-US06-form-metrics.json), **82,347
bytes**, raw SHA-256
`7e7da0d0d2a2f528b247e560399940e7c091ad765903ef5177381d140a01c290`,
and semantic SHA-256
`7cfff9b19f129ab29f2a14317a479c50ed38397921ef9111b0a4b57f7d557fc7`.
It binds all 34 final code/config/frontend/test/policy paths, immutable source
and oracle identities, 25 synthetic hashes/37 capabilities, dependencies,
rollback, exact outputs, and the unchanged US05 artifact.

The first complete controlled candidate is retained transparently as
[P03-US06-form-metrics-attempt-01-failed.json](../evidence/P03-US06-form-metrics-attempt-01-failed.json),
**82,341 bytes**, raw SHA-256
`7d51d18f8420951a0adf0121107b6b2535b83c128a39181ba1616ae9423c0ec1`,
semantic SHA-256
`3e829005470fe78e1486a6a693ae38ca6086745e4495672a1f0f31f9d579fcba`.
It failed only the ACORD paired gate because one fresh-process sample added
2.003430 s. It was not waived or edited; the one full unchanged rerun passed,
and independent review confirmed identical code/input/oracle custody.

## Rollback

Set `PARSER_LAYOUT_FORMS_ENABLED=false`. This performs zero US06 extractor or
projector work and restores the exact configured P03-US05 predecessor while
retaining the other accepted flags.

## Definition of Done

| Requirement | Result |
|---|---|
| Implementation and acceptance complete | Pass — exact ACORD 6/42/24/24 and component 3/16 denominators with exact 216/80 graphs |
| Dedicated and adversarial tests pass | Pass — story, contract, AcroForm, source, role-cap, malformed, boundary, timeout, and rollback coverage |
| Impacted regressions and real benchmarks pass | Pass — exact ACORD/component outputs plus non-target controls |
| API/schema and canonical compatibility pass | Pass — additive public `1.0`, strict typed IR, canonical authority, exact flag-off predecessor |
| Frontend visible-path compatibility passes | Pass — strict bounded validator, safe read-only rendering, fallback, normalization, copy/download, build, and bundle |
| Security/resource bounds pass | Pass — bytes, identities, objects, depth, fan-out, records, relationships, comparisons, deadlines, and transactional rollback |
| Final-code metrics and exact input custody retained | Pass — raw/semantic digests, 34 code paths, immutable sources/oracles/synthetics, sealed US05 predecessor |
| Configuration, policy, tracker, and rollback current | Pass |
| Independent review complete | Pass — algorithm/security, projection/oracle, and final metrics/custody approval |
| No concurrent next story | Pass — P03-US07 remained Proposed through this checkpoint |

Definition-of-Done result: **10/10 Pass**. P03-US06 is Done. P03-US07 is the
next dependency-ready Phase 03 story but remains Proposed until its source
truth, outline contract, fixtures, limits, and independent readiness review
pass. P03-US08 remains Proposed. No Phase 04 work has started.
