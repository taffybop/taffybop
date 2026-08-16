# Pre-remediation Genericity Audit

Date: **2026-08-13**  
Status: **Blocking finding recorded; no remediation performed**  
Scope: production-code identity checks relevant to the functional-fidelity queue

## Purpose

The generic-production policy applies to every new correction, but the current
production tree must not be assumed compliant merely because future changes
follow that policy. Before starting defect work, the affected capability path
must also be checked for pre-existing fixture-specific rules. Any such rule in
the path must be generalized or removed before the defect can close.

## Search performed

The initial read-only audit searched production backend and frontend sources
for the 15 benchmark case names, known item/element ID shapes, job IDs, long
hashes, and benchmark-specific language. Representative commands:

```text
rg -n 'benchmark-expertmodeldata|catastrophe-recap|clean-energy|clinical-study|component-datasheet|egov-survey|esg-metrics|finance-10k|health-report|insurance-acord|manufacturing-report|ny-timetable|postal-10k|purchase-agreement|settlement-agreement|uber-earnings' app frontend/app frontend/lib

rg -n 'p[0-9]+-i[0-9]+|el-[0-9a-f]{8,}|[0-9a-f]{64}|pjb-' app frontend/app frontend/lib
```

This is an initial audit, not the final per-defect diff/search attestation.

## Blocking production finding

[`app/services/layout_order.py`](../../app/services/layout_order.py) contains
explicit fixture-identifying rules, including:

- `_CLEAN_ENERGY_HEADER_ID = "p1-i1"`
- `_CLEAN_ENERGY_TITLE = "Clean Energy Market Monitor - March 2024"`
- `_CLEAN_ENERGY_SECTION = "Overview"`
- `_CLINICAL_OWNER_ID = "p1-i14"`
- `_CLINICAL_REJECTED_CONTRIBUTION = "RESEARCHARTICLE"`
- exact `_CLEAN_ENERGY_OWNER_BOX`, `_CLEAN_ENERGY_CHILD_BOXES`, and
  `_CLINICAL_OWNER_BOX` coordinates
- `_reviewed_clean_energy_header(...)` and `_reviewed_clinical_owner(...)`
  gates that use those identities in production decisions

These violate the new policy even though they predate this defect queue. They
are not evidence that current fixes are generic, and they cannot be preserved
as a compatibility shortcut when FFD-004/FFD-005 or a dependent ordering path
is remediated.

## Required disposition

1. FFD-004 is blocked from `Done` until these rules are replaced by a reusable,
   source/geometry/relationship capability that passes the genericity tests.
2. Any defect touching or depending on the same projection must include this
   code in its pre-implementation audit and prove that it neither calls nor
   recreates the fixture gates.
3. The replacement must pass renamed-file, changed-text, translated/scaled
   geometry, page-offset, positive-variant, negative, adversarial, and unrelated
   real-PDF controls.
4. Benchmark strings, IDs, and exact coordinates may remain in tests/evidence
   only; they must be absent from production runtime decisions.
5. Historical evidence remains immutable. Generalizing the implementation must
   not rewrite past reports as if they had already met this policy.

## Other observations

- `app/services/visual_source_text.py` contains benchmark-oriented comments,
  and its chart-domain vocabulary includes example domain words. Comments do
  not activate runtime behavior, but the vocabulary is a decision input and
  must be reviewed under FFD-002/FFD-003 to prove it is a documented generic
  chart signal rather than a benchmark phrase list.
- No production match in this initial scan, other than the explicit layout
  rules above, is adjudicated here as a confirmed fixture recognizer. Each
  defect still requires its own complete search and diff review.

## Closure

This audit closes only when a final repository search over production code and
the FFD-004 capability tests prove the explicit fixture rules are absent and
their generic replacement satisfies
[`generic-production-policy.md`](generic-production-policy.md). Until then,
the product must not be described as fully generic or functionally on par with
LlamaParse.

## 2026-08-14 Clinical page-one audit disposition

The Clinical-specific production gate recorded above has been removed and
replaced by source-proven fused-text partitioning plus structural preamble/
sidebar ordering. The affected production search was rerun over
`pipeline.py`, `visual_source_text.py`, `layout.py`, `layout_order.py`,
`presentation.py`, `models.py`, and the Clearleaf workspace for the Clinical
case name, source hash, page/item identity, reviewed labels/content, DOI,
artifact timestamp, and FFD ID. It returned no match.

The companion search still returns `_CLEAN_ENERGY_HEADER_ID`, exact Clean
Energy title/section/box data, and `_reviewed_clean_energy_header(...)` in
`app/services/layout_order.py`. That historical finding is unchanged. The
Clinical page-one implementation is locally generic, but the whole ordering
path is not yet policy-clean and FFD-004 cannot close. This disposition does
not rewrite the 2026-08-13 audit or claim repository-wide genericity.
