# FFD-014 Clinical page-1 validation report

This is a bounded first-page handoff, not an FFD-014 closure bundle. Physical
page 2 and later source content were not inspected or remediated.

## Source and target

- Complete source: `benchmark-expertmodeldata/clinical-study.pdf`, 750,004
  bytes, SHA-256
  `4e33db9cb9171f0b274ab3ba20a288510b5aee309a723412e59f843b59c76ff2`.
- Physical page 1 contains no flowchart. Its two relevant non-text visuals are
  the Crossmark `Check for updates` form and the Open Access mark.
- The minimum safe public representation remains the existing conservative
  `[Image detected; no reliable text extracted.]` placeholder. OCR and encoded
  form pseudo-text remain attributable evidence, not primary prose.

## Production correction exercised by the focused transaction profile

The bounded generic correction in `app/services/pipeline.py` permits a proven
P03 included visual placeholder to survive a P04 terminal canonical rebind
when the independently reconstructed visual is intrinsically omitted as
`unsupported_primary_ocr` or `empty_visual`. It validates the public visual,
ledger-to-omission coupling, contributor owner, source-alternative graph,
singleton evidence-only exclusions, and endpoint custody. Any mismatch keeps
the existing atomic rollback.

No filename, source hash, page number, item ID, target wording, or coordinate
constant activates the branch. The production document/page budgets remain
5.0/0.500 seconds, and no diagnostic override was used.

Focused settled command:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q tests/regression/phase_04/test_p04_us01_clinical_page1_visual_overlay_custody.py
```

Result: `18 passed, 5 warnings in 20.53s`. The warnings are dependency
deprecations. The suite includes two structurally distinct positives, the
direct fail-closed adversarial matrix, and one complete Clinical-PDF P04
transaction at the unchanged production budgets.

Settled supporting validation:

- the two existing Clinical P04 production controls passed together: `2
  passed, 5 warnings in 19.80s`;
- all P04-US01 contracts plus public projection: `590 passed`;
- P03 visual contracts/stories/real controls: `76 passed`;
- canonical serialization/public-model validation: `177 passed`;
- exact deadline and rollback invariants: `31 passed`; and
- independent production review found no genericity, custody, rollback, or
  fixture-activation defect in the bounded correction.

One separately governed NY P04 custody control remains red and is not claimed
as an FFD-014 fix. One sealed P03 retained-artifact check also retains a known
historical test-file hash mismatch; its functional/performance assertions
pass. The optional all-corpus drift screen retains broader frozen-predecessor
differences and is not promoted as a page-1 pass.

## Actual Clearleaf page-1 capture

The exact source bytes were uploaded to the local Clearleaf application and
rendered through its actual React presentation path. At a 1920x802 viewport,
the page-1 article contains exactly two `data-item-type="image"` placeholder
paragraphs. The retained DOM verdict records:

- article present;
- image paragraph count 2;
- placeholder count 2;
- pseudo-text absent;
- Mermaid/graph content absent; and
- literal escaped newline text absent.

The screenshot file named `clearleaf-viewport.png` contains original browser
JPEG bytes. The filename mismatch is retained and disclosed rather than
rewriting the captured evidence.

The full public response independently validates as `ParseResult`, and
`response.md` is byte-identical to
`.canonical_presentation.full.markdown`.

## Full-profile qualification

The release-fidelity profile enables the candidate gate. Under that profile,
the Clinical page-2 and page-4 objects remain `table_candidate` with gate
outcome `unresolved` and reason `upstream_reconciliation_unresolved`; they do
not form a P04 terminal authority transaction. This is byte-for-byte identical
to the selected pre-fix full-service artifact: all four public page objects and
the page-1 canonical presentation have identical hashes.

Accordingly, this actual UI capture proves page-1 public-surface consistency
and absence of collateral drift, while the focused P04 integration regression
proves the corrected terminal transaction. This bundle does not claim that the
release-profile response contains P04 table sidecars or document custody.

## Handoff state

The page-1 target is ready for user validation. FFD-014 remains in validation;
work pauses before page 2. A fresh LlamaParse closure job was not created for
this bounded handoff. The independent NY resource-boundary condition, Wave A
all-15 gate, and final frozen all-15 campaign remain pending.
