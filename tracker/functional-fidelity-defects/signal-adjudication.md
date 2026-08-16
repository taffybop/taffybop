# Comparator Signal Adjudication

The final machine comparison reports **278 functional-regression signals, 9
review-required signals, 54 acceptable/harmless signals, 2 resolved signals,
and 0 evidence gaps**. Those numbers are deliberately preserved, but they are
not an issue count.

A single missing source token can create separate Markdown text, JSON text,
rendered-DOM text, hierarchy, and table-presentation signals. Visual grouping
differences can also cascade across every later region or table comparison.
Conversely, a severe comparator signal can reflect a source-correct service
decision when LlamaParse emits generated prose, interpolated chart values,
unsupported arrows, or a different component taxonomy.

This tracker therefore uses three layers:

1. **Raw signals** — immutable `FID-*` rows in each per-case `evidence.json`.
2. **Source-grounded gaps** — the 25 authoritative remaining statements in the
   v2 disposition.
3. **Root-cause defects** — 13 baseline cards in `issues/`, plus the separately
   admitted post-baseline production-control card FFD-014.

Each issue card identifies its primary raw signals and links the complete case
evidence for correlated manifestations. The same broad text or DOM signal may
support more than one root cause; it is never counted as a second defect merely
because it appears on another output surface.

## Adjudication labels

- `primary` — directly demonstrates the defect's source-backed behavior.
- `correlated` — another surface manifestation of that behavior.
- `accepted` — formatting/taxonomy difference with no source-backed loss.
- `baseline_overreach` — LlamaParse content not printed or provable in source.
- `review_required` — proxy evidence that cannot decide correctness alone.
- `resolved` — historical defect with final three-surface evidence.

Before moving a card to `Ready`, record exact primary IDs and adjudicate every
other signal that would otherwise be claimed as evidence for that fix. The
complete signal population remains in:

`comparison-final-source-grounded-v2/<case>/evidence.json`

## Post-baseline production-control evidence

FFD-014 was discovered by mandatory production controls after the frozen v2
source-gap disposition. No original `FID-*` row isolates its terminal P04
transaction failure, so its primary evidence is the two exact red Clinical
controls, the stable integrity error, and the bound before/reconstructed
canonical-state comparison. Three existing Clinical `FID-*` rows are recorded
as correlated visual/OCR/DOM evidence only. FFD-014 adds neither a raw signal
nor a fabricated `SG-026`, and it does not rewrite the immutable comparator or
25-gap denominator.

## Non-defects protected from accidental reopening

- Finance 10-K, NY timetable, and purchase agreement are source-grounded fixed.
- Settlement agreement is an acceptable difference.
- LlamaParse chart-as-table values that are not printed in source are not a
  requirement.
- Generated semantic descriptions and unsupported connector arrows are not
  source truth.
- Different but functionally equivalent JSON taxonomies are not defects unless
  they break the public contract or user-visible presentation.
- ACORD logo semantics are deferred/unadjudicated; the authoritative v2 gap is
  only the lower coverage grid.
