# FFD-009 — Board-photo diagnostic OCR remains noisy in JSON

Status: **Proposed**  
Severity: **Minor**  
Priority: **P3**  
Primary story: **New diagnostics story only if source review retains this as release-relevant**  
Dependencies: **None; re-adjudicate before implementation**

## Scope and impact

- PDF: `benchmark-expertmodeldata/component-datasheet.pdf`
- SHA-256: `5fc8143f33d156d914b0f139177344be6ad2b0a8d2906413424d6dda93fe36a4`
- Page/region: physical p1, visible source page 3, Raspberry Pi Pico board
  photograph/board image.
- Surface: full public JSON diagnostic OCR. Primary Markdown/UI fidelity is not
  the defect; generated Llama prose is not source truth.
- Actual: noisy board-region OCR is retained diagnostically in JSON.
- Expected: diagnostic state clearly communicates unreliability and does not
  expose a long gibberish string as trustworthy extracted content.

Non-goals: do not promote photo OCR to Markdown/UI, copy Llama's generated
description, identify board components from model knowledge, or change the
page-2 pinout (FFD-002/008).

## Source-grounded oracle

The source image has no native PDF text inside the owner. Existing source
review accepts that the board remains an image and rejects generated semantic
description as OCR. Before Ready, product/schema owners must decide one of two
bounded contracts:

1. retain OCR diagnostics with a measurable reliability/noise gate and bounded
   payload, or
2. preserve only attempt/method/quality metadata when the result is unreliable.

Record current item ID, diagnostic fields, exact payload/hash, confidence, and
the approved target contract. Until that decision, this is not implementation-ready.

## Reproducible evidence

- `source-grounded-final-disposition-v2.json` Component case
- `comparison-final-source-grounded-v2/component-datasheet/evidence.json`
- `service-final-source-grounded-20260813-v2/component-datasheet/response.json`
  and p1 rendered DOM
- `visual-source-adjudication.json#/cases/3`
- `llamaparse/component-datasheet/`, job `pjb-vwv4utu38pi1splat9jlfba1cqrc`

No isolated `FID-*` proves this diagnostic-only concern. Broad visual/text
signals include generated Llama prose and are not primary. A focused diagnostic
quality assertion is required before Ready.

## Root cause

- State: **Unknown / policy decision required**
- Boundary: diagnostic OCR quality classification and public JSON projection.
- Why one defect: only the diagnostic payload/meaning is at issue; primary
  photo suppression already works.
- Safety: never hide that OCR was attempted, never label gibberish as reliable,
  and never alter user-visible primary output as a side effect.

## Acceptance criteria

1. Re-adjudication records whether diagnostic noisy text is a release defect and
   selects one explicit JSON contract.
2. If retained, a finite documented metric/threshold marks the exact board OCR
   unreliable; unreliable text is bounded and segregated from extracted value.
3. If omitted, JSON still retains attempt, engine/method, owner, confidence or
   concern, and a reproducible diagnostic hash without claiming text content.
4. In either contract, the board remains an image, `include_ocr_in_primary` is
   false, and gibberish occurs zero times in raw/canonical Markdown and DOM.
5. Uber's natural photograph and other image controls preserve diagnostic-only
   behavior; charts/diagrams with approved OCR remain primary where intended.
6. Fresh Component reference/service/DOM evidence validates the chosen contract
   and public schema compatibility.

## Generic-production requirements

- Apply the selected diagnostic-quality policy through reusable, documented
  evidence such as OCR confidence, character/line consistency, entropy, language
  agreement, payload bounds, image class, and engine status. Production behavior
  must not branch on filenames, hashes, benchmark cases, page numbers, image/
  element IDs, gibberish/expected strings, or fixed image coordinates.
- Capability evidence must show the same reliability/segregation decision for
  varied photographs and scans and must never use a target-token blacklist or
  whitelist. Thresholds must be calibrated on non-benchmark fixtures and expose
  the metrics/reason codes needed to audit a decision.
- Add a renamed/reserialized transformed or synthetic PDF that prepends a page,
  changes photo crop/scale/noise/lighting, changes any visible text, and includes
  both a readable scanned-text image and a noisy board-like photograph. The
  policy must classify/segregate them correctly without production changes.
- Negative/adversarial variants must cover empty OCR, engine failure, huge
  payloads, random high-confidence fragments, a readable scan, approved chart
  OCR, a natural photograph, and an image with sparse legitimate labels.
- Run multiple unrelated real-PDF controls through the same policy, including
  Uber p1, Clinical visual OCR, Manufacturing visuals, and a readable scanned
  document, preserving primary-versus-diagnostic custody on all surfaces.

Genericity closure gates:

- [ ] Genericity review records metric/threshold provenance,
  transformed/synthetic proof, adversarial outcomes, and unrelated real-PDF controls
- [ ] Production diff and repository-search attestation find no benchmark/file/hash/
  case/page/element/string/coordinate branch, token blacklist, or fixture leakage

## Test and rerun plan

- First test is a schema/policy test for the selected unreliable-diagnostic
  contract, followed by the real Component p1 assertion.
- Negative controls: reliable scanned text, approved chart OCR, empty OCR,
  engine failure, huge payload, and natural photograph.
- Required PDFs: Component plus Uber p1; control Clinical/Manufacturing visual OCR.
- Suites: P02 OCR reconciliation, P05 visual fallback, public model/schema,
  canonical no-primary-photo tests.
- Rerun Component and Uber through both systems; run all 15 only if shared JSON
  projection changes.

## Immediate affected-benchmark validation (mandatory)

- If remediation is authorized, after every production fix run the complete
  `component-datasheet` PDF through both LlamaParse and the service; also run
  complete `uber-earnings` whenever shared photo/OCR projection changes. A crop
  of the Component p1 board photo or Uber p1 photograph is diagnostic only.
- Use a new immutable `FFD-009` rerun folder for every attempt and capture source
  hashes, parser/model/settings, LlamaParse job IDs, service build/commit and
  configuration, timestamps, and artifact paths/hashes. If the disposition is
  accepted/deferred without code, preserve the same source-grounded decision
  packet instead of claiming a fix.
- Preserve LlamaParse raw Markdown, actual rendered Markdown UI snapshot and
  DOM/rendered representation where available, and full original JSON. Preserve
  service raw and canonical full Markdown, actual Clearleaf DOM/snapshot, and
  full original JSON.
- This immediate gate is a **targeted validation of FFD-009**, not an exhaustive
  whole-PDF/all-feature re-audit. Complete PDFs are rerun to exercise photo OCR in
  normal pipeline context. Manually compare only the approved diagnostic-quality
  contract and target photo owners below: relevant primary Markdown fragments
  around image/caption placement, rendered image/caption DOM selectors and
  snapshots, and JSON paths for page/image association, diagnostic OCR payload,
  reliability/state, concerns, limits, and provenance. Broader unrelated comparison
  belongs to the control, wave, and final all-15 gates.
- For the Component p1 board photograph, assert the approved diagnostic-quality
  contract exactly: unreliable text stays bounded and explicitly diagnostic (or
  is omitted per the approved policy) and never enters primary Markdown/UI.
  Confirm Uber p1 and reliable scan/chart OCR controls keep their intended
  behavior and that image placement/captions are unchanged.
- Run an automated full-result drift screen over each complete Markdown, rendered
  DOM, and JSON result. Manually adjudicate changes inside the declared impact
  boundary: the Component p1 photo, its diagnostic payload and primary-output
  exclusion, its caption/placement, and—when shared projection changes—the named
  Uber p1 and reliable-OCR controls. Any unexpected material change outside that
  boundary blocks closure and must be escalated as a cross-defect regression or
  separately tracked defect.
- Adjudicate every target-photo mismatch and every automated drift alert against
  the rendered source and selected product/schema contract, retaining a snapshot
  or DOM selector/excerpt, Markdown fragment, JSON path, reference behavior,
  service behavior, and harmless/accepted/material status.
- Passing policy/schema tests alone cannot close a remediation. If any material
  photo-OCR, Markdown, UI, JSON, limit, or provenance symptom remains, keep the
  issue discrepancy/in progress, fix it, and repeat a fresh full-PDF two-system
  rerun; an acceptable/deferred outcome requires explicit recorded approval.

## Story and change record

- Story action: **Re-adjudicate first. Create a new diagnostic-quality story
  only if the chosen contract is release-relevant; otherwise record an explicit
  accepted/deferred decision.**
- Expected production files: none until Ready.
- Changed files/tests/artifacts/reviewer: none.

## Closure checklist

- [ ] Product/schema diagnostic contract decided
- [ ] Exact current payload/item oracle recorded
- [ ] New story or explicit accepted/deferred decision recorded
- [ ] Focused test fails before any fix
- [ ] Production correction complete if authorized
- [ ] Visual/OCR/schema controls pass
- [ ] Fresh Component service/reference evidence retained
- [ ] Primary Markdown/UI remains free of photo gibberish
- [ ] Raw Markdown equals canonical full Markdown
- [ ] Story/evidence/registry/coverage/index updated
- [ ] Independent closure review recorded
