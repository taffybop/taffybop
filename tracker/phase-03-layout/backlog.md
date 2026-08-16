# Phase 03 Backlog

| Story | Status | Points | Acceptance summary | Dedicated test path | Dependencies |
|---|---|---:|---|---|---|
| [P03-US01](stories/P03-US01.md) | Done | 3 | Table captions survive as separate linked elements with source bbox | `tests/stories/phase_03/test_p03_us01_table_captions.py` | P01-US02 |
| [P03-US02](stories/P03-US02.md) | Done | 5 | Visual captions and internal children remain separate and grounded | `tests/stories/phase_03/test_p03_us02_visual_children.py` | P01-US02, P03-US01 |
| [P03-US03](stories/P03-US03.md) | Done | 5 | Source notes/footnotes link by graph+geometry and survive crop boundaries | `tests/stories/phase_03/test_p03_us03_source_notes.py` | P03-US01, P03-US02 |
| [P03-US04](stories/P03-US04.md) | Done | 5 | Exact 41-pair order and source-bbox ownership pass with serializer parity | `tests/stories/phase_03/test_p03_us04_reading_order.py` | P03-US03, P01-US03 |
| [P03-US05](stories/P03-US05.md) | Done | 5 | Redline and styled text runs retain source-visible state, geometry, provenance, order, and safe projections | `tests/stories/phase_03/test_p03_us05_redline_runs.py` | P01-US02, P03-US04 |
| [P03-US06](stories/P03-US06.md) | Done | 5 | Form labels, empty regions, controls, and key-value pairs remain explicit without fabricated values | `tests/stories/phase_03/test_p03_us06_forms_key_values.py` | P01-US02, P03-US04 |
| [P03-US07](stories/P03-US07.md) | Done | 5 | Nested lists and legal clauses preserve marker, parent, ordinal, and continuity | `tests/stories/phase_03/test_p03_us07_outline_structure.py` | P01-US02, P03-US04 |
| [P03-US08](stories/P03-US08.md) | Done | 5 | Running regions and physical/printed page identity remain distinct with stable body/full serialization | `tests/stories/phase_03/test_p03_us08_running_regions.py` | P01-US03, P03-US04 |

Total: 38 story points. P03-US07 and P03-US08 were each re-estimated 3→5 on
2026-08-01 at their Definition-of-Ready transitions.
P03-US08 is Done only under the approved active time-bounded
[frontend bbox compatibility renewal](decisions/P03-US08-frontend-bbox-latency-exception-renewal.md).
It preserves the original 1.8935% candidate-specific exception within the 5%
authorization, the 2026-09-02 review date, default-off rollback, and every
non-waived gate. Any further required-code change, production enablement, Phase
04 exit, expiry, or revocation returns the story to In Progress.

Hardened superseding renewal (2026-08-03): P03-US08 remains Done only under
[`P03-US08-LATENCY-EXCEPTION-RENEWAL-20260803-PHASE04-TABLES-HARDENED`](decisions/P03-US08-phase04-tables-latency-exception-hardened-renewal.md)
and its
[executable record](evidence/P03-US08-phase04-tables-latency-waiver-hardened-renewal.json),
with final approval bound in
[the independent approval record](evidence/P03-US08-phase04-tables-hardened-renewal-independent-approval.md).
The prior sentence remains the historical frontend-renewal checkpoint; its
blanket required-code and Phase-04-exit triggers do not apply to default-off
Phase 04 table-only changes admitted and structurally sealed by the new record.
Attempt 48 remains failed at **0.050946750 seconds** versus the unchanged
**0.050000000-second** New York projection-p95 ceiling (**0.000946750 seconds /
1.8935%**, maximum **5%** candidate-specific), its companion remains
quarantined, strict-final evidence remains absent, and this is not a strict
current-artifact metrics pass. Production enablement, admitted-scope expansion,
or a protected running-region semantic/runtime/custody change requires a new
explicit decision and expires the renewal before the change; review is due no
later than **2026-09-02**. Default-off rollback and every non-waived RSS,
paired/source/Uber latency, correctness, security, compatibility, custody,
resource, output, rollback, and hosted-use gate remain in force.

## Governing benchmark gaps

- P03-US01–US04: `GAP-LAYOUT-001`, `GAP-ORDER-001`, `GAP-LINK-001`,
  `GAP-BBOX-001`, `GAP-PROVENANCE-001`, `GAP-DIAGNOSTICS-001`, and
  `GAP-SERIALIZATION-001`.
- P03-US05: `GAP-REDLINE-001`, `GAP-ORDER-001`,
  `GAP-PROVENANCE-001`, and `GAP-SERIALIZATION-001`.
- P03-US06: `GAP-FORM-001`, `GAP-BBOX-001`, `GAP-PROVENANCE-001`,
  `GAP-DIAGNOSTICS-001`, and the form side of `GAP-TABLE-001`.
- P03-US07: `GAP-LIST-001`, `GAP-ORDER-001`, and
  `GAP-SERIALIZATION-001`.
- P03-US08: `GAP-PAGE-001`, `GAP-LAYOUT-001`, `GAP-ORDER-001`, and
  `GAP-SERIALIZATION-001`.
