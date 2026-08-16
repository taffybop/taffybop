# FFD-007 — Component NOTE private-use glyph lacks safe recovery

Status: **Proposed**  
Severity: **Minor**  
Priority: **P3**  
Primary story: **P02-US01 / P02-US02**  
Dependencies: **FFD-005 owns the NOTE callout role, not this scalar mapping**

## Scope and impact

- PDF: `benchmark-expertmodeldata/component-datasheet.pdf`
- SHA-256: `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`
- Page: physical p2, visible source page 7.
- Region: NOTE icon immediately before the `NOTE` callout label.
- Surfaces: public JSON text/run evidence, raw Markdown, rendered DOM.
- Actual: raw/canonical Markdown exposes `#  NOTE`, including raw PUA glyph
  `U+F05A`; FFD-005 separately tracks the false H1 role.
- Expected: preserve the source-visible NOTE meaning using an embedded-font
  proven semantic icon or a documented accessible fallback; never expose an
  unexplained PUA scalar as ordinary text.

Non-goals: do not map arbitrary PUA code points by Unicode number alone, copy
Llama-generated prose, or change the pinout image/OCR/topology.

## Source-grounded oracle

The PDF render proves an information/NOTE callout icon. Llama presents `Note
icon **NOTE**`, which is useful review evidence but not itself source text.
Before Ready, record the embedded font name/subset, glyph ID, cmap/outline
evidence, source-object IDs, bbox, accessible target semantics, and the exact
fallback when that evidence is unavailable.

## Reproducible evidence

- `comparison-final-source-grounded-v2/component-datasheet/evidence.json`
- `service-final-source-grounded-20260813-v2/component-datasheet/response.md`
  around `#  NOTE`, plus `response.json` and p2 `rendered-dom.json`
- `llamaparse/component-datasheet/reference.md` around
  `> Note icon **NOTE**`; job `pjb-vwv4utu38pi1splat9jlfba1cqrc`
- `visual-source-adjudication.json#/cases/3`

There is no isolated `FID-*` row for the PUA scalar. The broad text/Markdown
rows are correlated and cannot move this card to Ready; add a bounded source
oracle and focused regression first.

## Root cause

- State: **Unknown until embedded-font audit**
- Boundary: PDF font audit/recovery and public text-run projection.
- One defect: the raw PUA scalar and UI mojibake are the same missing glyph
  mapping; heading/callout role is deliberately split to FFD-005.
- Safety: mapping requires exact font/glyph evidence. Otherwise omit the glyph
  from ordinary text, preserve diagnostic provenance, and expose an accessible
  non-fabricated fallback.

## Acceptance criteria

1. Ready records the exact font/glyph/source-object/bbox oracle and decides
   proven mapping versus explicit fallback.
2. `U+F05A` is absent from user-visible Markdown and DOM.
3. If mapping is proven, JSON records the original PUA scalar and recovered
   semantic alternative with method/confidence; UI exposes an accessible NOTE
   icon/label once.
4. If mapping is not proven, JSON records an unresolved-font concern and the UI
   uses the approved non-garbled fallback without inventing icon identity.
5. Other PUA glyphs, healthy custom fonts, ligatures, and ordinary icon fonts
   are unchanged; unknown PUA values fail closed.
6. Raw Markdown equals canonical Markdown and fresh Component Llama/service/DOM
   artifacts demonstrate the once-only result.

## Generic-production requirements

- Treat private-use content as a general font/glyph-provenance capability.
  Semantic recovery must come from embedded/source mappings or another reusable,
  independently documented mapping; otherwise use the approved unresolved
  fallback. Production behavior must not branch on a benchmark filename/hash/
  case, page number, item ID, the target PUA scalar, `NOTE`, or fixed coordinates.
- Capability evidence must distinguish proven semantic mapping from an unknown
  private-use glyph and exercise multiple glyphs/fonts; a mapping added solely
  because this benchmark displays a NOTE icon is not acceptable.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes glyph position/scale and surrounding text, and uses both a differently
  encoded source-mapped icon and an unknown PUA glyph. Known semantics must
  survive and the unknown glyph must fail closed without production changes.
- Negative/adversarial variants must include absent/contradictory maps, reused
  PUA values across unrelated fonts, ligatures, ordinary Unicode symbols, and a
  misleading nearby label; proximity or wording alone may not infer identity.
- Run multiple unrelated real-PDF/custom-font controls, including the Clinical
  and ESG font cases plus at least two healthy icon/custom-font fixtures, and
  retain proof that their text and fallback behavior do not change.

Genericity closure gates:

- [ ] Genericity review records provenance-based mapping rules,
  transformed/synthetic proof, adversarial outcomes, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch or single-glyph benchmark lookup

## Test and rerun plan

- Positive fixture reproducing the exact audited font/glyph if rights permit;
  otherwise a structurally equivalent test font plus the real PDF regression.
- Negative tests: same PUA scalar in another font, missing embedded font,
  ambiguous cmap, multiple glyph outlines, and ordinary literal PUA text.
- Controls: all P02 font fixtures, Clinical fonts, Purchase symbols, and
  Component p1/p3.
- Suites: P02-US01/02, P03-US05, canonical/frontend accessible rendering.
- Rerun Component through both systems; all-15 font drift screen if shared
  recovery code changes.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `component-datasheet` PDF
  through both LlamaParse and the service. A crop of p2/visible source page 7 is
  diagnostic only and cannot close the card.
- Create a new immutable `FFD-007` rerun folder for each attempt and retain the
  source SHA-256, parser/model/settings, LlamaParse job ID, service build/commit
  and configuration, timestamps, and hashes/paths for all artifacts.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-007**, not an exhaustive
  whole-PDF/all-feature re-audit. The complete PDF is rerun to exercise glyph
  recovery in normal pipeline context. Manually compare only the NOTE glyph oracle
  and its enclosing line on Component p2/visible 7: the exact Markdown code-point
  fragment and accessibility fallback, rendered NOTE/line DOM selectors and
  snapshot, and JSON paths for run/scalar structure, font/glyph evidence, recovery
  method, alternatives, concerns, and provenance. Broader unrelated comparison
  belongs to the control, wave, and final all-15 gates.
- On Component p2/visible 7, assert the audited NOTE glyph is represented once
  by its source-proven intended character or an approved accessible fallback,
  never by a raw user-visible PUA scalar. Confirm surrounding NOTE text and all
  Component p1/p3 content remain unchanged and an ambiguous mapping fails closed.
- Run an automated full-result drift screen over the complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the NOTE marker, its enclosing run and line, adjacent text, accessible
  fallback, and ambiguous-mapping behavior. Any unexpected material change outside
  that boundary—including Component p1/p3 drift—blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Adjudicate the target-glyph result and every automated drift alert against the
  rendered source and completed font/glyph oracle, recording the Markdown code-
  point fragment, snapshot or DOM selector/excerpt, JSON path, LlamaParse
  expectation, service result, and harmless/accepted/material status.
- Unit/font-fixture success alone cannot close this card. If a material raw-PUA,
  glyph, fallback, Markdown, UI, JSON, or provenance symptom persists, leave the
  issue discrepancy/in progress, fix it, and repeat a fresh full-PDF two-system
  rerun until the issue-specific assertions pass.

## Story and change record

- Story action: **Re-adjudicate after font audit, then add a narrow correction
  AC to P02-US01/P02-US02.**
- Expected production files: unknown until Ready.
- Changed files/tests/artifacts/reviewer: none.

## Closure checklist

- [ ] Font/glyph oracle and rights-safe fixture complete
- [ ] Proven-map versus fallback decision recorded
- [ ] Focused test fails before fix
- [ ] Production correction complete
- [ ] Font controls pass
- [ ] Fresh Component reference/service JSON/Markdown/DOM retained
- [ ] Raw Markdown equals canonical full Markdown
- [ ] No user-visible raw PUA scalar remains
- [ ] Stories/evidence/registry/coverage/index updated
- [ ] Independent closure review recorded
