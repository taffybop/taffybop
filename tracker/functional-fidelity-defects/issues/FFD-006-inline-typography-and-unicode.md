# FFD-006 — Native inline typography and Unicode semantics are lost

Status: **Proposed**  
Severity: **Major**  
Priority: **P1**  
Primary story: **P02-US01 / P02-US02 / P03-US05**  
Dependencies: **None; coordinate with FFD-004 so scalar repair does not reorder text**

## Scope and impact

- `clinical-study`, physical p1–p4 / printed 1/21, 7/21, 10/21, 11/21:
  some source body scalars/diacritics and inline author/footnote typography are
  damaged or flattened. Affected surfaces are JSON text/run evidence, Markdown,
  and DOM.
- `esg-metrics`, physical p1 / printed 80: source superscript footnote markers
  in the heading/table/chart labels are flattened into baseline digits; column
  presentation is partly degraded. Affected surfaces are JSON run semantics,
  Markdown/table markup, and DOM.

Source PDFs/SHA-256:

- `benchmark-expertmodeldata/clinical-study.pdf` — `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`
- `benchmark-expertmodeldata/esg-metrics.pdf` — `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9`

Non-goals: no language-model spelling repair; no general reading-order work;
no table shape or chart series changes; no unsupported replacement of visible
minus/hyphen/diacritic forms based only on Llama output.

## Source-grounded oracle

Expected: source-authored Unicode scalars, combining marks, superscript roles,
spacing, and inline emphasis survive from source evidence to all public
surfaces. ESG visibly uses superscript note markers around `Energy 1,2`,
`Unit 3`, `CY21 4`, `FY24 5`, and the chart footnotes `6,7`; the exact
occurrence/role count must be fixed in the Ready oracle rather than inferred
from this shorthand.

Actual: ESG serializes these markers as baseline text (for example `# Energy
1,2`, `Unit 3`, `CY21 4`, `FY24 5`). Clinical retains broad damaged/fused
tokens and flattened inline author/footnote styling. The disposition does not
identify a complete Clinical token list; Ready requires an exact scalar/run
oracle tied to source bboxes and source-object IDs.

## Reproducible evidence

- `comparison-final-source-grounded-v2/clinical-study/evidence.json`
- `comparison-final-source-grounded-v2/esg-metrics/evidence.json`
- `service-final-source-grounded-20260813-v2/{clinical-study,esg-metrics}/`
- `llamaparse-visual-routing-fix/clinical-study/`
  (`pjb-33emg9582knzmzw35de91sw2y56q`)
- `llamaparse/esg-metrics/` (`pjb-dnqqsnjbdx1np5utnrt9nx6fcibd`)

No comparator row isolates this cause. Broad candidates
`FID-CLINICAL-STUDY-7ff711b5ea91` and
`FID-ESG-METRICS-0ce54fb8433b` are correlated text aggregates; ESG's
Markdown-structure row `FID-ESG-METRICS-73b6b0dfdc92` is also correlated.
Ready requires per-token primary evidence. Heading/order/table diffs remain
assigned to FFD-004/005 and table source-truth decisions.

## Root cause

- State: **Hypothesis; exact token/run causes pending Ready**
- Boundary: font mapping/recovery, text-run semantic projection, and inline
  canonical/table serialization.
- Failure: valid source run distinctions are fused, normalized, or omitted
  between extraction evidence and public presentation.
- Safety: repair only from embedded-font/native glyph/run evidence; preserve
  original and recovered alternatives and fail closed on ambiguous mappings.

## Acceptance criteria

1. Ready contains an exact Clinical scalar/run oracle and an exact ESG
   superscript occurrence oracle with bboxes, source IDs, and expected markup.
2. Every oracle scalar is Unicode-exact and appears once in JSON, raw/canonical
   Markdown, and DOM; no replacement/private-use/combining-mark damage remains.
3. Every oracle superscript is represented in JSON run semantics, serialized
   without changing table cells, and rendered as semantic `<sup>`.
4. Unsupported/ambiguous font mappings retain alternatives and concern codes;
   no language-model or dictionary completion is permitted.
5. Clinical table numbers, mathematical minus signs, links, and source order do
   not change unless explicitly included in the oracle.
6. ESG table values, chart ownership, columns, and footnote text remain
   unchanged apart from the approved inline roles.
7. Purchase emphasis, Postal table formatting controls, and healthy-font
   fixtures remain correct.
8. Fresh Clinical/ESG dual-system JSON/Markdown/DOM evidence and an all-15 text
   drift screen are retained.

## Generic-production requirements

- Preserve/recover inline Unicode and typography through reusable font encoding,
  glyph/source mapping, run ownership, scalar offsets, and provenance. Production
  behavior must not branch on filenames, document hashes, benchmark cases, page
  numbers, item/run IDs, target words/scalars, or fixed coordinates; standard
  source-proven encoding maps must apply independently of document identity.
- Capability evidence must cover different fonts, scripts, combining sequences,
  ligatures, superscripts, and table/non-table runs and explain every recovery or
  fail-closed concern without dictionary completion or expected-output lookup.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes the words/numbers/diacritics, swaps source-proven fonts, moves and
  rescales the runs, and places superscripts in different cells. Unicode and
  inline semantics must remain exact without modifying production constants.
- Negative/adversarial variants must cover missing/contradictory font maps,
  malformed combining sequences, overlapping/out-of-range runs, unsupported
  private-use glyphs, math minus signs, and cross-cell spans; uncertain evidence
  must remain explicit and must not be guessed.
- Run multiple unrelated real-PDF controls, including `purchase-agreement`,
  `postal-10k`, `clinical-study` table-number controls, and healthy custom-font
  fixtures, retaining scalar-exact JSON/Markdown/DOM evidence.

Genericity closure gates:

- [ ] Genericity review records source-proven mapping/run rules,
  transformed/synthetic proof, adversarial outcomes, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch or document-specific substitution map

## Test and rerun plan

- Failing regressions: one test per Clinical oracle run and ESG superscript
  location, plus real-pipeline once-only assertions.
- Adversarial: combining mark, ligature, PUA glyph, ambiguous cmap, baseline
  digit that is not superscript, and table cell with mixed runs.
- Controls: Purchase, Postal, Finance, Component NOTE (FFD-007), and healthy
  unusual-font fixtures.
- Suites: P02-US01/02, P03-US05, canonical Markdown, table inline serializer,
  frontend semantic inline rendering.
- Rerun Clinical and ESG through both systems, then all 15.

## Immediate affected-benchmark validation (mandatory)

- After every production fix, run the complete `clinical-study` and
  `esg-metrics` PDFs through both LlamaParse and the service. Page/line crops are
  useful diagnostics but are not closure evidence.
- Save each attempt in a new immutable `FFD-006` rerun folder. Its manifest must
  include source SHA-256 values, parser/model/settings, LlamaParse job IDs,
  service build/commit and configuration, timestamps, and every artifact path
  and hash.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM and snapshot,
  and full original JSON.
- This immediate gate is a **targeted validation of FFD-006**, not an exhaustive
  whole-PDF/all-feature re-audit. Complete PDFs are rerun to preserve text-run
  processing in normal pipeline context. Manually compare only the completed
  scalar/run oracles and affected Clinical and ESG inline spans below: their exact
  Markdown fragments and run boundaries, rendered inline-element DOM selectors
  and snapshots, and JSON paths for scalar values, run types/offsets, page/item
  association, original/recovered values, and provenance. Broader unrelated
  comparison belongs to the control, wave, and final all-15 gates.
- Verify every completed Clinical run oracle on the affected pages and the ESG
  p1/80 superscript location: source characters are preserved exactly, inline
  spans occur once at the correct offsets, the fiscal superscript is neither
  flattened nor moved, and unrelated baseline digits or punctuation are not
  promoted. Component NOTE remains governed by FFD-007.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: each target text run, its enclosing line/item, adjacent characters
  and punctuation, inline offsets, and the named ESG superscript control. Any
  unexpected material change outside that boundary blocks closure and must be
  escalated as a cross-defect regression or separately tracked defect.
- Adjudicate every target-run mismatch and every automated drift alert against the
  rendered source and scalar/run oracle, retaining exact Markdown/Unicode fragment,
  snapshot or DOM selector/excerpt, JSON path, expected reference behavior, actual
  service behavior, and materiality.
- Passing font/run unit tests cannot close this card. Any material scalar,
  typography, run-boundary, order, Markdown, rendered-UI, JSON, or provenance
  symptom keeps it discrepancy/in progress; fix and repeat a fresh two-system
  full-PDF rerun until the assertions pass.

## Story and change record

- Story action: **Add correction ACs to P02-US01/P02-US02 for identified font
  mappings and P03-US05 for public inline projection.**
- Expected production files: unknown until Ready.
- Changed files/tests/artifacts/reviewer: none; remediation not started.

## Closure checklist

- [ ] Exact scalar/run/superscript oracle complete
- [ ] Focused tests fail before fix
- [ ] Production correction complete
- [ ] Font/run/table/front-end controls pass
- [ ] Fresh references and service outputs retained
- [ ] Public JSON preserves original/recovered provenance
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Clearleaf inline semantics reviewed
- [ ] All-15 text drift screen passes
- [ ] Stories/evidence/registry/coverage/index updated
- [ ] Independent closure review recorded
