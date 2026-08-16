# LlamaParse-15 Corpus Validation

Status: Pairing and machine-readability validated; source-grounded element
validation is recorded in the case reports.

## Corpus boundary

- Corpus root: `benchmark-expertmodeldata/`
- Expected cases: 15
- Discovered cases: 15
- Source files: 15 PDF files
- Expert Markdown files: 15
- Expert JSON files: 15
- Total source pages: 30
- Source mutation: prohibited; all generated artifacts are stored under
  `tracker/benchmarks/llamaparse-15/` or `tmp/pdfs/llamaparse-15/`.

The complete sizes and SHA-256 checksums are recorded in `manifest.json`.

## Pairing result

Every base filename has exactly one `.pdf`, one `.md`, and one `.json` file.
There are no missing triplets, unexpected extensions, duplicate base names, or
duplicate file hashes.

| Case | PDF pages | PDF | Markdown | JSON | Pairing result |
|---|---:|---:|---:|---:|---|
| catastrophe-recap | 1 | Present | Present | Present | Valid triplet |
| clean-energy | 1 | Present | Present | Present | Valid triplet |
| clinical-study | 4 | Present | Present | Present | Valid triplet |
| component-datasheet | 3 | Present | Present | Present | Valid triplet |
| egov-survey | 1 | Present | Present | Present | Valid triplet |
| esg-metrics | 1 | Present | Present | Present | Valid triplet |
| finance-10k | 3 | Present | Present | Present | Valid triplet |
| health-report | 1 | Present | Present | Present | Valid triplet |
| insurance-acord | 1 | Present | Present | Present | Valid triplet |
| manufacturing-report | 3 | Present | Present | Present | Valid triplet |
| ny-timetable | 3 | Present | Present | Present | Valid triplet |
| postal-10k | 3 | Present | Present | Present | Valid triplet |
| purchase-agreement | 1 | Present | Present | Present | Valid triplet |
| settlement-agreement | 1 | Present | Present | Present | Valid triplet |
| uber-earnings | 3 | Present | Present | Present | Valid triplet |

## Machine-readability checks

1. All 15 PDFs open through both PDFium and pdfplumber.
2. All 30 pages render successfully to PNG for visual verification.
3. All 15 JSON files are valid UTF-8 JSON.
4. All 15 Markdown files are valid UTF-8 text.
5. For every case, the expert `markdown.pages`, `text.pages`, and
   `items.pages` counts match the source PDF page count.
6. Every source page exposes some native text objects. This does not prove that
   the native mapping is correct; `catastrophe-recap` is a known counterexample.
7. No case is a fully scanned PDF. The corpus therefore cannot by itself close
   scanned-document or direct-image release gates.

## Expert serialization distinction

The standalone expert Markdown and the concatenated JSON page-body Markdown are
not the same artifact:

- Exact after trimming: `clean-energy`, `insurance-acord`.
- Different: the other 13 cases.

The differences are retained as evidence rather than normalized away. In the
reviewed cases they primarily arise because the standalone Markdown injects
headers, footers, printed page labels, or `<page_number>` tags that the JSON
page body's `markdown` field omits. Each case report validates whether the
difference is justified and whether the ordering is source-faithful.

All expert JSON files include `markdown_full` and `text_full` keys with `null`
values. Consumers must use the page arrays or the standalone `.md` file rather
than assuming the `*_full` fields are populated.

## JSON schema variability

`clean-energy` and `insurance-acord` contain the core result keys but omit the
debug/job/forms/raw-parameter metadata present in the other 13 exports. This is
not a source-content error, but it prevents treating every expert JSON file as
one byte-stable operational schema.

## Corpus limitations and blockers

- All sources are PDFs; there are no direct images, DOCX, PPTX, or XLSX files.
- No source is fully scanned, though image-heavy and mixed visual pages are
  present.
- The corpus contains selected pages from longer publications, so physical PDF
  page index and printed page label may differ.
- At original validation, only the exact catastrophe PDF/Markdown/JSON triplet
  was approved as public/redistributable for P00-US02. On 2026-07-29, the
  requester subsequently approved all remaining 14 triplets and derived
  annotations as public and redistributable with no exceptions; the current
  decision is recorded in
  [`P00-US04-source-rights.md`](../../phase-00-baseline/evidence/P00-US04-source-rights.md).
- Expert output may contain vector-, pixel-, or model-derived content not
  explicitly printed in the source. Such content is classified per element in
  the case reports and is never promoted to literal ground truth by default.

## Reproduction

Inventory and renders were generated with:

```text
.venv/bin/python tracker/benchmarks/llamaparse-15/tools/corpus_audit.py \
  benchmark-expertmodeldata \
  --output tracker/benchmarks/llamaparse-15/manifest.raw.json \
  --render-root tmp/pdfs/llamaparse-15
```

The final `manifest.json` preserves the validated hashes and adds the reviewed
case categories and complex-element inventory.
