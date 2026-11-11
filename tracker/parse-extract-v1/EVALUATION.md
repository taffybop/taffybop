# PX initial evaluation set and frozen scoring

Updated: 2026-11-11  
Story: PX1-01  
Corpus version: `px1-initial-v1`  
Evidence class: authored synthetic sources and offline custody checks only

## Registration and provenance

The [manifest](../../tests/fixtures/parse_extract_v1/manifest.json) registers
**four independent fictional documents, eight one-page assets**. Each document
has a PDF and an image-only render. Source definitions and expected values were
authored separately from provider output; no hosted parser or LLM response was
used. The author has checked the visible documents against the oracle, but an
independent human review has not been performed. This is a starting development
corpus, not a representative quality benchmark or a measured accuracy claim.

| Independent source | Split | Selected claims | Assets |
| --- | --- | --- | --- |
| `dev-invoice-104` | Development | Invoice ID/date/currency/total; three ordered rows; repeated SKU with different quantities/prices | PDF, PNG |
| `dev-contract-201` | Development | First-party representative first/last name despite another party's name; effective date; missing governing law | PDF, PNG |
| `holdout-request-305` | Held out | Form ID/applicant/date/amount; absent email; date normalization | PDF, JPEG |
| `holdout-agreement-407` | Held out | Conflicting first-party representatives require abstention; second-party role; missing expiry date | PDF, JPEG |

The sources are authored for this repository and authorized for future hosted
provider tests. They include no customer/private data. Source authorization does
not bypass the provider configuration or test spending limit. All remain below
the current 10 MiB, ten-page and 20M-pixel intake limits.

The [source definitions](../../tests/fixtures/parse_extract_v1/sources.json),
[oracle](../../tests/fixtures/parse_extract_v1/expected.json), and every asset have
SHA-256 hashes in the manifest. Each field identifies its source page and quote;
the row oracle records full ordered rows and critical columns. Regeneration and
custody commands are in the [fixture README](../../tests/fixtures/parse_extract_v1/README.md).

## Splits and denominators

| Split | Independent documents | Scalar targets | Found | Missing | Ambiguous | Critical scalar targets | Source rows |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Development | 2 | 8 | 7 | 1 | 0 | 5 | 3 |
| Held out | 2 | 8 | 5 | 2 | 1 | 5 | 0 |
| Total | 4 | 16 | 12 | 3 | 1 | 10 | 3 |

Render siblings stay in the same split. Report asset modality separately and
count the independent parent once when stating sample size. Do not mix a PDF in
development with its image sibling in the held-out set. Do not pool field
families to conceal a failing family. There is **no held-out repeating-row
case** yet, and each family has too few independent examples for qualification.

Held-out expectations are visible in the repository but excluded from tuning.
Once they influence a prompt/configuration fix, reclassify them as development
in a new corpus version and add fresh independent holdouts before a quality
claim. Expand toward the plan's 50-100 reviewed documents before PX4/PX5 gates;
add real scans, multipage sources, varied tables/layouts and authorized failure
cases. This initial set covers neither handwriting nor charts/formulae.

## Frozen scoring rules

These rules are fixed before model tuning. A future evaluator must implement
them and test failure cases; PX1-01 supplies no model scoring runner or measured
provider results.

1. Match by parent document, explicit field name and source row position. A
   field passes only when its status, typed value and evidence checks pass.
   Missing response fields fail; invalid/truncated responses cannot pass.
2. Strings use Unicode NFC and trim/collapse whitespace. Preserve case,
   punctuation and spelling; no fuzzy or substring value matching. Do not
   normalize one person's name into another or discard role identity.
3. Dates must have a valid ISO `YYYY-MM-DD` typed value matching the oracle;
   retain the provider/source raw text separately. The form's printed
   `23 September 2026` maps to `2026-09-23` by the frozen oracle.
4. Decimal values compare as exact decimal numbers, with no floating-point
   epsilon. Decimal strings in this oracle avoid binary rounding. Currency is
   its own critical field. Integers in rows must be integers, excluding booleans.
   Numeric-looking strings do not by themselves prove typed adapter validity.
5. Missing targets require `null` and `missing`. The ambiguous target requires
   `null`, `ambiguous` and review. Its two named candidates are source evidence,
   not permission to choose one. Any non-null answer to these targets fails.
6. Evidence must refer to the source page and a verified snippet. Match snippets
   against stored source/parse after whitespace normalization; check source
   disagreement independently so a parser hallucination cannot validate itself.
   Geometry is not required and must not be invented. Unsupported evidence fails
   acceptance even when the value is coincidentally correct.
7. Rows compare complete typed column values in printed order, including both
   `A100` deliveries. Report exact matching row positions over three expected
   rows, row-count errors, missing/extra rows and complete-table correctness.
   Do not deduplicate, sort or best-match rows. Subtotal arithmetic is an
   additional check, never a substitute for correct SKU/quantity ownership.
8. Report correct found values over all 12 present targets, present-target
   coverage, incorrect abstentions and missing/ambiguous correctness separately
   (three missing, one ambiguous). Also report strict scalar passes over 16 and
   each family's denominators. Abstaining on a present target fails and reduces
   coverage; flagging everything for review cannot establish automation quality.
9. Critical fields are the ten scalars marked `critical` in the oracle; the
   invoice's SKU, quantity and amount are critical row columns. Any unflagged
   wrong critical value blocks the affected capability. Report review-required
   outcomes and straight-through coverage separately from correctness.

## Checks actually performed

On 2026-11-11:

- `.venv/bin/python -m tests.fixtures.parse_extract_v1.builder`: generated four
  PDF and four raster assets and their manifest, without network access.
- `.venv/bin/python -m pytest tests/test_parse_extract_evaluation_set.py -q`:
  **11 passed**, one existing FastAPI/Starlette TestClient deprecation warning.
  Checks cover hashes, split isolation, distinct asset custody, all quoted PDF
  evidence, actual ruled-table cells, decimal arithmetic and repeated SKUs,
  PNG exact pixels/JPEG bounded render loss, and frozen denominators.
- Visual inspection of all four latest raster pages: legible text and table,
  consistent margins, no clipping/overlap. PDFium was used because Poppler and
  ReportLab were not installed; no unrelated service/package was changed.

No live provider request, extraction, latency/cost/accuracy measurement, browser
journey or production qualification was performed for this corpus. The manifest's
`provider_results` is empty. Later runs must register actual saved raw responses,
source/settings hashes, provider/model/version, observed usage and timing; they
must never manufacture responses to fill the record.
