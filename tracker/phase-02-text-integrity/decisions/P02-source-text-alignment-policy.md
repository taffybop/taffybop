# P02 Source-Text Alignment Policy

Status: Accepted  
Date: 2026-07-30  
Applies to: Phase 02 exit alignment for reviewed native-PDF text targets

## Decision

Phase 02 may add one bounded source-text alignment pass for text that is
present in the immutable PDF but is damaged, fused, detached, or displaced by
the current layout projection. The pass is:

- default off;
- source only;
- deterministic;
- provenance complete;
- transactional and fail closed; and
- incapable of language-model, dictionary, filename, or document-specific
  completion.

The feature is controlled by
`PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED`. When the flag is false, the
prior call path, canonical text, Markdown, JSON, diagnostics, and serializer
behavior remain byte-equivalent. Disabling this flag is the complete rollback
for source alignment.

Source alignment may select only text evidenced by the exact uploaded PDF:
native PDF character/run data, embedded font dictionaries and safe glyph
names, PDFium character metadata, source geometry, or an already retained
source-safe candidate. Reference Markdown, case reviews, and the target
registry below are test or adjudication aids; they are not runtime text
sources.

## Source-of-truth order

For character and punctuation fidelity, authority is:

1. the rendered immutable PDF at its pinned SHA-256;
2. consistent native character codes, glyph names, PDFium metadata, and
   geometry from those same bytes;
3. reviewed reference output only where it agrees with the PDF; and
4. an explicit unresolved result when the source evidence does not determine
   one value.

No review assertion may override visible source bytes. The approved corpus
bindings are:

| Case | PDF SHA-256 |
|---|---|
| `clinical-study` | `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2` |
| `esg-metrics` | `6eda6d5871098ca8d99bc5b5a1fcf869366147a3440e409c63319fb2813799e9` |
| `purchase-agreement` | `00a8eec6c3ade84be7f9016c8c27547eab4a1802746bc146b00af71216ccfd14` |
| `settlement-agreement` | `adaaf7578748ec1c215ebdfd9601a9938ec1bee918316122c56b22212a3595bc` |
| `postal-10k` | `72b984cde38a5dc8e13949c3699eb371eb26e14cdd92480091fe3f10f2857e74` |

These hashes pin regression fixtures. Production routing must never branch on
a filename, document title, case ID, hash, quoted phrase, page number, or bbox.
The production rules must operate only on the generic evidence predicates in
this policy.

## Accepted source-truth corrections

The rendered clinical PDF resolves two conflicts in the retained review:

- The exact Table 2 cell is `−0.76 (−2,26, 0.74)`. The comma after `2` is
  visible in the PDF. `−2.26` is not source truth for this fixture.
- The exact footnote begins `Hedges‘ g`, using U+2018 LEFT SINGLE QUOTATION
  MARK after `Hedges`. `Hedges’ g` is not source truth for this fixture.

The rendered postal PDF also overrides the expert omission of currency
symbols. Fifteen visible `$` glyphs are source text and must remain present;
alignment must not make the parser agree with that source-incorrect omission.

Purchase-agreement styling establishes literal curly quotation marks and the
literal bracketed date. It does not, in Phase 02, establish the legal meaning
of redline color, deletion, insertion, bold, or underline.

## Reviewed exit-target registry

Every target below must be exact on its applicable canonical surfaces or have
one explicit unresolved decision with the original bytes, alternatives, and
reason retained. Silent preservation of a known damaged value is not closure.

### Clinical study

The approved Phase 02 scope is physical pages 1 and 4.

#### `CLIN-P1-AUTH`

Owner bbox: `[200.012, 208.353, 358.713, 31.492]`.

The exact reviewed author content, with superscript roles represented
explicitly, is:

```text
Sebastian Burchert<sup>1</sup>*, Mhd Salem Alkneme<sup>1</sup>, Ammar Alsaod<sup>1</sup>, Pim Cuijpers<sup>2,3</sup>, Eva Heim<sup>4</sup>, Jonas Hessling<sup>1</sup>, Nadine Hosny<sup>4,5</sup>, Marit Sijbrandij<sup>2</sup>, Edith van’t Hof<sup>6</sup>, Pieter Ventevogel<sup>7</sup>, Christine Knaevelsrud<sup>1</sup>, on behalf of the STRENGTHS Consortium
```

Superscript digits and `*` retain their role evidence. The visible `ID` text
inside each ORCID icon is not lexical text in the adjacent author name and
must not produce `BurchertID`, `CuijpersID`, or another fused name. Alignment
does not claim semantic classification of the icon; it only prevents
geometry- and style-distinct icon text from entering the author owner.
Markdown may escape the literal source asterisk as `\*`; that serializer
escape does not change the selected U+002A source character.

#### `CLIN-P1-DIACRITIC`

Owner bbox: `[200.012, 250.835, 370.863, 76.885]`.

The decisive exact spans are:

```text
Freie Universität Berlin
Babeș-Bolyai University
```

The source has an `a` bbox of approximately
`[564.270, 250.021, 568.718, 258.021]` and an overlapping U+00A8 spacing
diaeresis bbox of approximately
`[565.169, 249.851, 567.833, 257.851]`. The raw two-glyph evidence must be
retained when the safe composition rule below emits `ä`.

#### `CLIN-P1-WORD`

Owner bbox: `[200.012, 562.662, 375.919, 148.301]`.

```text
We conducted a 2-arm pragmatic randomized controlled trial.
```

PDFium supplies the source space. The observed `e`-to-`c` gap is approximately
`2.061 pt`. `Weconducted` is forbidden as the selected value.

#### `CLIN-P4-WORD`

Owner bbox: `[200.012, 383.291, 351.504, 34.396]`.

```text
of +3% in the HSCL-25 scores (indicating higher psychological distress) and +2% in the WHODAS scores (indicating lower functioning) were sufficient to render the results not significant.
```

PDFium supplies the source space in `WHODAS scores`; the observed `S`-to-`s`
gap is approximately `2.190 pt`. `WHODASscores` is forbidden as the selected
value.

#### `CLIN-P4-NUM`

Source cell bbox is approximately
`[383.526, 241.528, 60.178, 8.743]`; the retained table-cell bbox is
`[383.526, 242.728, 60.178, 7.315]`.

```text
−0.76 (−2,26, 0.74)
```

Both minus signs are U+2212. PDFium and PDFMiner/pdfplumber are source-exact
for the punctuation. The damaged `- 0.76 ( - 2,26, 0.74)` is forbidden. This
is a native glyph-preservation and table-serialization target, not an OCR or
decimal-correction target.

#### `CLIN-P4-QUOTE`

Source bbox is approximately `[36.000, 332.440, 322.244, 9.384]`.

```text
Hedges‘ g effect sizes were derived by combining multiple imputation estimates using Rubin’s rules.
```

The character after `Hedges` is U+2018 and the character in `Rubin’s` is
U+2019. PDFium is source-exact. If no unique owner can retain the footnote,
the result is explicitly unresolved; alignment must not reverse the first
quotation mark or invent an owner.

The known physical-page-2 text beginning `COD was` and containing
`“e-helpers”` is outside the currently approved clinical pp1/4 target scope.
It is not silently fixed or claimed by this decision. Expanding the exit
registry to page 2 requires an explicit tracker change; a global replacement
of PDFium sentinel characters is prohibited.

### ESG metrics

The target is physical page 1, printed page 80. Each leading marker is the
ASCII digit shown below plus retained `superscript` role and bbox evidence.
The exact source strings are:

```text
3 Energy consumption is in megawatt hours (MWh)
4 Energy data is revised from prior annual disclosures to reflect the divestiture of Lehi, Utah, operations.
5 Beginning with fiscal year 2024, Micron's environmental, health and safety performance data is reported on a fiscal year basis to align with emerging regulatory requirements.
6 Energy consumption in millions of megawatt hours (M MWh)
7 Renewable electricity purchased and generated prior to CY22 is not shown.
```

| Target | Source bbox |
|---|---|
| `ESG-N3` | `[133.800, 390.633, 75.573, 3.545]` |
| `ESG-N4` | `[133.800, 397.233, 153.625, 3.545]` |
| `ESG-N5` | `[133.800, 403.833, 222.327, 7.446]` |
| `ESG-N6` | `[389.550, 424.318, 91.977, 3.545]` |
| `ESG-N7` | `[389.550, 430.918, 114.830, 3.545]` |

The selected values must not contain the damaged marker substitutions
`$`, `%`, `'`, `(`, or `)`, nor the font-extraction artifacts `re&ect`,
`re & ect`, or `#scal`.

### Purchase agreement

Owner bbox: `[72.195, 142.249, 466.452, 76.683]`.

The exact plain-text opening is:

```text
THIS ASSET PURCHASE AGREEMENT (this “Agreement”), dated as of [June 23_______], 2020 (the “Effective Date”), is by and between The City of Johnstown, a political subdivision of the Commonwealth of Pennsylvania operating as a Third Class City under a Home Rule Charter (the “Seller”), and the Greater Johnstown Water Authority, a body corporate and politic organized under the Pennsylvania Municipality Authorities Act (the “Buyer” and together with Seller, the “Parties”).
```

The bracketed date must also pass as an independently addressable exact span:

```text
[June 23_______]
```

Decisive native-run bboxes are:

| Run | Bbox |
|---|---|
| `“Agreement”` | `[334.938, 142.445, 63.924, 10.391]` |
| `[June` | `[462.484, 142.445, 23.488, 10.184]` |
| `23_______]` | `[72.241, 155.646, 54.484, 10.391]` |
| `“Effective Date”` | `[180.379, 155.634, 78.803, 8.076]` |
| `“Seller”` | `[155.192, 182.165, 37.632, 8.087]` |
| `“Buyer”` | `[387.985, 195.365, 39.559, 10.391]` |
| `“Parties”` | `[121.960, 208.553, 43.984, 8.076]` |

PDFium provides these literal characters. Alignment must not replace the
curly quotations with spaced ASCII apostrophes. Redline and legal-state
semantics remain excluded.

### Settlement agreement

The exact canonical phrase is:

```text
Look-Back Date
```

It occurs three times in the reviewed page. Canonical text must contain three
`Look-Back Date` occurrences and zero `LookBack Date` occurrences:

| Target | Source evidence |
|---|---|
| `SA-TEXT-01` | Complete source occurrence within `[144.400, 293.830, 191.800, 10.910]` |
| `SA-TEXT-02` | `Incentive Payment D Look-` at `[403.740, 612.312, 135.816, 10.908]`; `Back Date` at `[144.204, 626.112, 51.708, 8.484]`; hyphen sentinel at `[536.532, 617.508, 3.024, 0.876]` |
| `SA-TEXT-03` | Complete source occurrence within `[243.420, 681.310, 295.580, 10.910]` |

The second occurrence is authorized only through the corroborated PDFium
hyphen rule below. It is not a dictionary-based dehyphenation decision.

### Postal 10-K

The page-1 exact source targets are:

```text
CIO Chief Information Officer
FERS Federal Employees Retirement System
```

`CIO Chief Information Officer` has source bbox approximately
`[61.630, 335.500, 206.740, 7.510]`. It must occur once in the canonical
glossary text, and `ClO` must occur zero times as a competing primary value.

`FERS Federal Employees Retirement System` has source bbox approximately
`[61.950, 713.510, 271.390, 9.480]`. It must occur once as canonical text or
be explicitly unresolved as one complete source-native alternative. A
standalone OCR `FERS` is not a complete replacement.

The source also contains fifteen `$` glyphs that must remain source text. Their
reviewed positions are:

- page 2: x approximately `260.63`, `360.38`, and `460.13` at top
  approximately `133.02` and `318.27`;
- page 3: x approximately `408.00`, `457.50`, and `507.00` at top
  approximately `133.02`, `627.27`, and `670.02`.

Currency preservation is a negative control. No alignment rule may delete a
source-supported `$` merely to match the expert output.

## Generic eligibility and selection

A source candidate is eligible only when all of the following hold:

- the source PDF hash matches every participating analysis report;
- page dimensions, page index, owner identity, and coordinate transform are
  finite and consistent;
- the candidate has one unique, ordered alignment to a single owner or table
  cell;
- every emitted code point is traceable to a retained source character,
  allowlisted glyph name, or narrowly authorized composition below;
- the candidate is complete for the proposed replacement range;
- the candidate does not require a document name, fixture hash, phrase
  lookup, language prior, or semantic guess; and
- applying it leaves all unrelated owners and source occurrences unchanged.

An eligible source-safe candidate outranks a damaged layout projection of the
same PDF layer. A tie, ambiguous owner, partial span, cross-page alignment,
contradictory mapping, unsupported glyph name, missing transform, resource
exhaustion, deadline, or validation failure produces `unresolved` and no
canonical mutation.

Comparison may use Unicode NFC and whitespace normalization to establish an
alignment. Emission is byte-for-byte source candidate text except for the
spacing-diaeresis composition and PDFium hyphen rules explicitly authorized
below. NFKC, case folding, transliteration, confusable substitution, spelling
correction, punctuation normalization, and broad whitespace cleanup are
prohibited.

## Type1 glyph-name recovery

An embedded Type1 font `/Encoding /Differences` entry may repair text only
when the dictionary is structurally valid, the character code maps to exactly
one name, the used run references that exact font object and code, and the
name appears in this closed allowlist:

| PDF glyph name | Emitted Unicode | Retained role |
|---|---|---|
| `/zero.numr` through `/nine.numr` | ASCII `0` through `9` | `superscript` / numerator glyph |
| `/f_i` | `fi` | ligature source |
| `/f_l` | `fl` | ligature source |

The ESG font evidence
`[33 /one.numr /two.numr /f_i /three.numr /four.numr /f_l /five.numr /six.numr /seven.numr]`
therefore grounds the reviewed digits and `fi`/`fl` text without OCR.

Unknown names, `.notdef`, duplicate or conflicting differences, non-ASCII or
overlong names, malformed dictionaries, missing font identity, and
unallowlisted ligatures remain unresolved. The implementation does not
execute font programs or infer a mapping from glyph appearance. It retains
font object identity, character code, glyph name, emitted scalar sequence,
role, run bbox, and method for every recovered occurrence.

## PDFium source rules

### Semantic hyphen

A PDFium sentinel such as U+0002 or U+FFFE may emit literal U+002D HYPHEN-MINUS
only when:

- `FPDFText_IsHyphen(text_page, character_index)` returns `1`;
- the sentinel has a finite positive bbox at the end of one source line;
- the adjacent left and right fragments align uniquely to one owner in source
  order;
- at least one separate, complete, source-native occurrence in the same PDF
  contains the same anchored term with a literal hyphen; and
- the replacement changes only that sentinel and passes all provenance and
  serialization checks.

This authorizes the broken-line settlement `Look-Back Date` using its two
complete same-document occurrences. It does not authorize global
U+0002/U+FFFE replacement, dictionary dehyphenation, or deletion of a
discretionary line-break hyphen. Without corroboration, the span remains
unresolved.

### Source-supported spaces

A missing U+0020 may be restored only when PDFium emits that space in the
exact aligned source range and adjacent glyph geometry corroborates it:

- both neighboring glyphs are on the same page and baseline;
- the gap is at least `max(0.75 pt, 0.15 × local font size)` and no more than
  `1.5 × local font size`;
- the PDFium range and neighboring glyph order align uniquely to one owner;
  and
- the edit inserts only the source U+0020.

Geometry alone never invents a word boundary. This rule covers the reviewed
`We conducted` and `WHODAS scores` gaps because PDFium supplies the spaces.

### Spacing diaeresis

U+00A8 SPACING DIAERESIS may be converted to U+0308 COMBINING DIAERESIS and
NFC-composed with the immediately preceding Latin vowel only when:

- base and mark come from adjacent source characters in the same font run;
- their baselines differ by no more than `0.10 × local font size`;
- at least 80% of the mark's horizontal width overlaps the base and the mark
  center lies inside the base bbox;
- there is no encoded whitespace between them;
- NFC of the base plus U+0308 produces one assigned precomposed character; and
- the unique owner alignment and raw source bboxes are retained.

This is a narrow, evidence-backed emission exception for the reviewed
`Universität`. Other spacing marks, detached diaereses, arbitrary combining
marks, multiple possible bases, or failed NFC composition remain unchanged
and unresolved.

## False-OCR suppression

A complete, verified source-safe native candidate is authoritative over an
OCR candidate when the OCR bbox and the matching native **token subrange**
have at least `0.80` reciprocal area overlap and both ranges refer to the same
source position. The native line may be wider than that token subrange; full
row-to-token reciprocal overlap is neither expected nor sufficient. If the
OCR text conflicts, it is retained only as a rejected alternative with reason
`source_safe_native_conflict`; it cannot enter canonical text, Markdown, or a
table cell.

This rule suppresses the postal `ClO` false duplicate because the PDF layer
already provides source-safe `CIO Chief Information Officer`. It also rejects
standalone OCR `FERS` as incomplete when the source-native phrase includes the
definition. A native span with suspicious or unresolved font mapping is not
declared source safe merely because it is native; existing font recovery and
reconciliation policy continues to govern that case.

For these two reviewed examples, the native acronym anchors are approximately
`CIO [61.630, 335.500, 16.820, 7.510]` and
`FERS [61.950, 713.510, 25.310, 7.500]`. Expansion from the matched `FERS`
token to its complete native glossary line is permitted only when that
source-safe line is unique, begins with the exact matched token, has compatible
line geometry, and is not already represented canonically.

Suppression is scoped by source identity and geometry. Equal strings at
different bboxes are never globally deduplicated, and OCR evidence is never
deleted.

## Table and projection consistency

One selected table-cell repair is an atomic update across:

- canonical cell value;
- row arrays;
- HTML;
- CSV;
- table Markdown;
- enclosing document Markdown; and
- projected JSON fields that serialize the same value.

The implementation must regenerate these forms from one updated table model,
then reparse or validate them for equal row/column shape and exact selected
cell text. It must not patch serialized strings independently. Any mismatch,
shape change, duplicate cell, or validation failure rolls back the complete
table mutation and records one bounded unresolved concern.

This policy authorizes text consistency, including the clinical U+2212 cell.
It does not authorize table span inference, row reattachment, column-count
changes, or reconstruction of missing table structure.

A source line immediately adjacent to but outside a represented table may be
retained as an `unrepresented_source_line_near_table` concern when it has at
least 24 alphanumeric characters, is absent from every canonical item and
table cell on that page, has finite source geometry, and remains within 64
points of the table boundary. This diagnostic is bounded to 64 lines per page
and 512 per document. It does not create a primary item or infer an owner.
This generic rule makes an omitted table note explicit without a phrase,
fixture, or page lookup; ambiguous or excess candidates remain unselected.

## Provenance requirements

Every considered alignment records:

- policy/schema version and exact PDF SHA-256;
- page index, page dimensions, coordinate units, and transform;
- owner/item/table/cell identity and original bbox;
- original selected bytes and candidate bytes;
- stable source character/run indices and ordered raw code points;
- font object/reference, character code, encoding entry, glyph name, and role
  when applicable;
- PDFium character index, raw sentinel, `FPDFText_IsHyphen` result, glyph
  bboxes, gaps, and corroborating occurrence IDs when applicable;
- method, eligibility checks, terminal reason, and every retained
  alternative/evidence ID;
- OCR token/candidate identity, confidence, bbox, and suppression reason when
  an OCR candidate conflicts;
- pre- and post-update table serialization digests when a table cell changes;
  and
- deterministic selected, unchanged, or unresolved status.

Raw embedded font-program bytes are never persisted, logged, returned, or
committed. Missing, dangling, duplicate, cross-document, or contradictory
provenance fails closed before mutation.

## Proposed conservative resource bounds

The initial implementation must not exceed:

| Bound | Value |
|---|---:|
| Input PDF bytes | 25 MiB |
| Pages inspected | 100 |
| Font objects | 256 |
| PDF names preflighted | 200,000 |
| Source characters | 500,000 |
| Source runs | 10,000 |
| `/Differences` entries per Type1 font | 256 |
| Type1 glyph-name length | 64 ASCII bytes |
| Total Type1 difference entries inspected | 4,096 |
| Owners/groups considered | 512 |
| Page items and table cells traversed | 10,000 |
| Source candidates per owner | 8 |
| Total source candidates | 2,048 |
| Candidate text | 4,096 Unicode code points |
| Evidence references per candidate | 64 |
| Selected replacements per document | 512 |
| Retained concerns | 512 |
| Serialized source-alignment report | 8 MiB |
| Aggregate source-alignment deadline | 2 seconds |

Existing lower upload, parser, font-audit, table, reconciliation, or request
limits remain authoritative. Traversal is bounded and deterministic; it must
use page/owner/run identity or a bounded spatial index rather than an
unbounded all-pairs scan. Bounds and deadlines are checked inside loops.

On exhaustion, timeout, malformed input, or report-validation failure, no
partial primary, canonical, table, Markdown, or JSON mutation is committed.
Prior output remains authoritative and one bounded unresolved concern is
retained when safely possible.

## Performance target

On healthy PDFs, the source-alignment component's additive p95 target is at
most `1.0%` of the P00-US10 reference, and cumulative Phase 02 healthy-PDF p95
overhead must remain at or below `10%`. The retained pre-alignment
conservative component ceiling is `3.095326%`; it is an arithmetic reference,
not a paired full-parser percentile.

Final evidence must record warmups and repeated p50/p95/max latency, peak RSS,
candidate/report counts, fail-closed behavior, exact flag-off parity, target
case results, and the all-15 healthy/drift screen. A measured regression above
either ceiling blocks enablement rather than weakening a bound.

The all-15 screen treats `finance-10k` as the named GAP-TEXT non-target:
source alignment must select zero replacements there and its canonical
text/Markdown must remain unchanged.

## Compatibility, flag, and rollback

`PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED` is default off. The enabled
path requires the existing shared-IR normalization and font-audit primitives
and may feed the existing reconciliation stage without relaxing its
provenance, overlap, script, or transactional gates. A missing or disabled
dependency must reject or bypass the new path explicitly; it must not run a
partial alignment mode.

Flag-off execution must omit new call arguments at adapter boundaries where
that is required for observer and monkeypatch compatibility. It must not emit
alignment reports or change the previous public response.

Disabling only
`PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED` restores the exact prior
selection behavior while leaving existing audit, recovery, selective OCR,
reconciliation, numeric cleanup, and occurrence evidence under their own
independent flags.

## Explicit exclusions

This decision does not authorize:

- production branches keyed by document name, path, title, hash, page number,
  target ID, bbox literal, or target phrase;
- hard-coded replacement strings for any corpus document;
- a language model, remote service, web lookup, dictionary, spell checker,
  regular-expression phrase correction, or semantic completion;
- NFKC, transliteration, confusable correction, case restoration, broad
  punctuation conversion, or whole-document whitespace normalization;
- global U+0002/U+FFFE replacement or general-purpose dehyphenation;
- OCR promotion over a complete source-safe native span;
- new whole-page or broad-region OCR initiated by source alignment;
- redline, deletion, insertion, underline, bold, contract-state, or other
  legal-semantic interpretation;
- semantic ORCID/icon descriptions;
- table span, row, column, or missing-structure reconstruction;
- diagram, chart, reading-order, caption, footer, or general layout repair;
- altering source-supported currency or other characters to match a
  source-incorrect expert output; or
- silently treating an unaligned reviewed span as healthy.

Fixture-specific hashes, exact strings, pages, and bboxes in this document are
verification assertions only. They must prove that generic rules close the
reviewed cases; they must never become production dispatch data.
