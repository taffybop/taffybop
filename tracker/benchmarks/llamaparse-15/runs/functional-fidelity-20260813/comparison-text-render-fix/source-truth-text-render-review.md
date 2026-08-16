# Source-truth text, Markdown, and rendered-UI review

Scope: text integrity, reading order, Markdown syntax/hierarchy, and the
rendered Markdown UI across the retained 15-PDF functional-fidelity run. This
review uses the rendered source PDF and the case-level source audits as truth;
LlamaParse remains the requested comparison baseline but is not treated as
ground truth where it adds generated descriptions, derived chart values, or
source-contradicted structure.

## Production fixes in this cluster

1. Scalar text-run Markdown projection now serializes non-overlapping,
   source-supported bold and italic runs as `**`, `*`, or `***`, while
   retaining the existing deletion/underline precedence and escaping rules.
   Headings keep their Markdown heading envelope without redundant emphasis.
2. The canonical result UI now preserves a uniquely matched source heading as
   `h1`-`h6` instead of flattening every canonical block to `p`. Validated
   bold/italic runs render as semantic `strong`/`em` nodes, and every
   top-level canonical block exposes its authoritative `data-item-type` in
   canonical order for UI/evidence auditing.
3. Already accepted, explicitly primary visual OCR now tolerates at most 1.0
   point of same-unit source-crop rounding drift. Greater drift, cross-unit
   geometry, foreign ownership, and `include_ocr_in_primary=false` continue to
   fail closed. This restores the clinical p3 diagram and manufacturing p1
   chart labels coherently across public JSON, raw/canonical Markdown, and UI.

Both bridges fail closed: an ambiguous heading contributor or invalid text-run
graph retains the authoritative canonical/plain-text fallback.

## Source-grounded per-PDF disposition

| PDF | Text / order / Markdown / UI status | Source-grounded disposition |
|---|---|---|
| `catastrophe-recap` | Discrepancy remains | The event name and euro amount still require Unicode/font recovery; chart OCR labels remain noisy. LlamaParse's reconstructed chart values are not literal source truth. |
| `clean-energy` | Discrepancy remains | Chart native/OCR passes are duplicated and fused, and the right-side `Overview` tab precedes the left running title. Exact bar values inferred by LlamaParse are not required without provenance. |
| `clinical-study` | Diagram projection fixed; separate discrepancies remain | The approved p3 flowchart OCR and its external caption now render once in JSON, raw/canonical Markdown, and UI. P1 sidebar still precedes the article title, body words/diacritics are damaged, and extracted heading levels remain flat. LlamaParse's known table-span and Mermaid-containment defects are accepted baseline differences rather than parity targets. |
| `component-datasheet` | Discrepancy remains | Figure caption order, nested-list structure, and visual OCR remain degraded. LlamaParse's Markdown markers inside raw HTML cells are not a correct rendered-format target. |
| `egov-survey` | Partially degraded | Ordinary prose/order is substantially retained; chart text still duplicates native/OCR passes. LlamaParse's duplicate full-chart bboxes are not required. |
| `esg-metrics` | Discrepancy remains | Superscript note markers/words are corrupted, chart text is duplicated/noisy, and the left footer/navigation precedes right-column chart content. LlamaParse's unprinted footer URL is not required. |
| `finance-10k` | Acceptable text difference; taxonomy gap remains | Accounting text and symbols are source-faithful and the service table structure is stronger than the baseline. Repeated `Apple Inc.` is still inconsistently typed as header/heading. |
| `health-report` | Discrepancy remains | Explicit rotated labels are garbled or absent and a lower chart is duplicated as a false table. Unsupported LlamaParse point estimates are not literal recall requirements. |
| `insurance-acord` | Discrepancy remains | Contact text is corrupted/duplicated and serialized after the signature region; form-grid semantics remain degraded. LlamaParse's fabricated blank-area signature is not required. |
| `manufacturing-report` | P1 chart projection fixed; separate discrepancies remain | The source-valid p1 owner OCR, including the boundary `-15.0%` label, now renders once across JSON, Markdown, and UI. Other chart text passes/captions remain duplicated or misordered and visible section `4.3.` remains mistyped. Unsupported exact chart series from LlamaParse are not required. |
| `ny-timetable` | Discrepancy remains | P2 title fragments follow the table and false OCR fragments remain; the systematic table grid issue is owned by the table cluster. |
| `postal-10k` | Discrepancy remains | The final `FERS` definition is still lost/detached, false `ClO` OCR remains, and table-cell italics/em-dashes are not fully preserved in primary Markdown. |
| `purchase-agreement` | This cluster fixed; separate gaps remain | Bold defined terms now survive raw/canonical Markdown and rendered UI; redline/underline content and top-matter order remain intact; canonical UI now exposes headings and item types. Remaining source-backed gaps are the false heading role for struck `Draft of 6/1/20`, `Background` at level 1 instead of subsection level, and later quotation-glyph normalization. Extra/split strong runs are rendering-equivalent source style, not missing emphasis. |
| `settlement-agreement` | Discrepancy remains | One source line-break-spanning `Look-Back` still loses its lexical hyphen and legal clause structure remains implicit. The final mid-sentence text is source-complete for the supplied page. |
| `uber-earnings` | False photo OCR fixed; separate gaps remain | The source photograph contains no caption text, so suppressing gibberish and using a no-reliable-text placeholder is source-correct even though LlamaParse supplies generated prose. The current UI now exposes heading elements/item types. Heading levels/title grouping, date/subtitle order, note/footer order, chart construction-text filtering, and diagram structure remain separate extraction gaps. |

## Focused rerun and rendered evidence

Immutable predecessor: `service-post-fix` (not modified).

Focused sibling candidate: `service-text-render-fix`, derived from the immutable
predecessor with 13 inherited cases and fresh affected-case evidence.

Final visual-OCR sibling: `service-visual-ocr-final`; it contains fresh HTTP
and rendered-DOM evidence for clinical and manufacturing without changing
either predecessor directory.

### `purchase-agreement`, physical page 1

- Source PDF SHA-256:
  `00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14`.
- Source render SHA-256:
  `95d77d7b0bf161ff6918a42626265bbf19ef8a7d86ffa6cb4d5a824fa2e399f1`.
- Exact deterministic profile, direct current-pipeline rerun with absolute
  Docling artifact root `/Users/vignesh/Downloads/taffybop/.models/docling`:
  JSON `5ec541699f97fbb161f189dc15ab84540fbad953c9a13655edd99a6f08591378`;
  Markdown `a0d1dfc2eeb80b537365daaf01200713c998a8918ab76f3c1f6b2deb3da5fac8`.
- Repository-native current React capture:
  manifest `2ca4838fbc44fc574204a51cfef293285d4c1d8b627d7cda46647c8437c7637f`;
  DOM artifact `356fe9201ec4888c7bb64513eadafad5b56cc421528988d99c13ccdecf7a8f68`;
  HTML `1c8a3feedb56042c81d33bdc5e2b3543c9d531803d1679d6819c4f1558459151`.
- Final Markdown contains `**Agreement**`, `**Effective Date**`, `**Seller**`,
  `**Buyer**`, and `**Parties**`. Final UI capture contains 17 source-backed
  `strong` nodes, three currently extracted heading nodes, and the complete
  12-entry canonical item-type sequence. Before this fix, the retained capture
  had 11 paragraphs, no heading tags, no item-type sequence, and no strong
  tags; retained predecessor DOM artifact SHA-256 was
  `06ba38cd7d99c26dddf5b5f25ce278feeaf8e56f21c62a64c1d3bfe3e0249783`.
- Fresh LlamaParse job `pjb-637vhqamkp2x2p0tzgd1xve8iqc5` was recaptured
  after the fix: reference JSON
  `a6db0458fc32a6216374a775333665322185a4205f457e157d078c79aaaa6aaa`;
  raw Markdown
  `6223d338aefe324f0d364b5b7b442d337964fec91d96e650ce62557b8de4f229`;
  rendered DOM
  `5215d201970a5b559cb2e9c382e77bec974594664285b7224107b03366c190d2`;
  rendered PNG
  `8b6d8c7b7c016856e080e1003dc9cce991327a1ff7a21436046a6bb88830c59b`.

### `uber-earnings`, physical pages 1-3

- Source PDF SHA-256:
  `76a4d3fb8af06adc88ed68538997ef28afb26b377f41014cd83eeaddcbcd29e5`.
- Fresh exact-profile HTTP response supplied by the visual-fidelity fix:
  JSON `8a9a5daa68703f287472ff9899753ebf742c30df3f094b70c5e8b427a75508e9`;
  Markdown `38a70ffc902eb7b15775327f2a90c0c28716256bdfd7c0d7a5def19f3857b62a`.
- Current React capture manifest:
  `12e1b11d9bb1a9a182f8e6131a4e5d3b22a5c605d47ce5b93b36845208ef6d25`.
- Page DOM artifact SHA-256 values:
  p1 `18446daff0d52b9ec59ba2dd9c7eac20e7e474e7e77343c6050406d607d8802e`;
  p2 `83215683ba7ed3033ea4464d0a2cef7b00956d2233f2a4464337573354efb759`;
  p3 `43267ff1d79c5f3567d09fbab2ae4dc3fb4df0956f4362b1cda581539fc4b832`.
- P1 no longer presents photograph gibberish as source text. All three pages
  expose the service heading/item sequence in semantic DOM; their remaining
  hierarchy/content differences are retained as unresolved, not marked fixed.

### `clinical-study`, physical page 3

- Source PDF SHA-256:
  `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`.
- Fresh exact-profile HTTP JSON
  `ad1e8ba564f2bf719a2759871026caca44843915efb1fda44346d1467f8fd9be`;
  Markdown
  `8239dab80521dc2cefd42f50c1dcb3cc19255bb6bc6208a0e085e3e28b348ef2`;
  p3 DOM artifact
  `36a25e704845430a4d291d59d51c39c5ade38ead8f577ad8c0d0a3a742047fbb`.
- Item `p3-i2` is a diagram with `value == md == ocr_text`, `source=ocr`,
  and 802 characters of accepted owner OCR. The raw Markdown, canonical
  Markdown, and DOM each present it once; the separately owned caption appears
  once and the prior placeholder is absent.

### `manufacturing-report`, physical page 1

- Source PDF SHA-256:
  `414570f576f16adb8cbe37c43f92ef474a0a0a218d3a2b5a77ffb595dc9eb58f`.
- Fresh exact-profile HTTP JSON
  `6029852e9b662ab2f9897da6f9965e98f2730ceedc4e890e6d9e6e11e911699f`;
  Markdown
  `6aef58c75d563a3ed714c1d0b245fb8879e3a55e452cc8614bf1f76d7fd7a483`;
  p1 DOM artifact
  `3ca5309d30a69fc37552154fc5b640af1558f74b518c433d324304dd1c4a1762`.
- Item `p1-i2` has `value == md == ocr_text`, `source=ocr`, and 244
  characters of accepted owner OCR. The final `-15.0%` label is retained, the
  OCR block appears once in raw/canonical/UI output, and the placeholder is
  absent.

## Validation

- Backend text-run unit/adversarial/contract suites: **102 passed**.
- Backend real-corpus P03-US05 regression: **10 passed** in the offline local
  profile with the absolute Docling artifact path; the focused current
  purchase checks also independently passed 2/2.
- Backend P03-US02 visual relationship suite: **64 passed**.
- Focused exact-profile clinical/manufacturing/Uber corpus slice: **3 passed**
  in 57.07 seconds.
- Frontend unit suite: **160 passed**.
- Frontend TypeScript check: passed.
- Frontend ESLint: passed.
- Production frontend build: passed.
- Fresh two-case analyzer output:
  `comparison-text-render-fix/report.md`; it records 0 evidence gaps and keeps
  both PDFs at `discrepancy_found` because independent extraction gaps remain.
  Raw LlamaParse tag/marker counts are not used to erase the source-truth
  dispositions above.

## Story ownership

- Markdown/style-run projection and semantic emphasis: `P03-US05`
  (`GAP-REDLINE-001`, `GAP-SERIALIZATION-001`).
- Canonical rendered structural types, heading tags, and item-type custody:
  `P01-US04` (`GAP-SERIALIZATION-001`).
- Accepted owner-OCR crop interoperability and exactly-once presentation:
  `P03-US02` (`GAP-LAYOUT-001`, `GAP-SERIALIZATION-001`).
- Remaining heading-level extraction belongs to `P03-US07`; character/text
  reconciliation remains `P02-US04`; column/page reading order remains
  `P03-US04`. No unresolved item is relabeled fixed solely because a unit test
  passes.
