# P04-US01 Exact-Bbox Metrics Controlled Supersession

Status: Implemented for review; final metrics and independent approval pending  
Date: 2026-08-05  
Scope: P04-US01 metrics and test evidence only  
Policy ID: `p04-us01-dual-bbox-role-v1`

## Trigger and classification

The first real catastrophe all-corpus application of the exact-table scorer
exposed a role conflict that the synthetic fixture had masked. Cell text,
rows, value, CSV, spans, and header ownership were exact, but the scorer
compared P04-US01's public Docling content rectangles with the Phase-00 ruled
grid-slot rectangles. It also generated bare `<th>` expectations even though
the accepted serializer/runtime contract requires `scope="col"` or
`scope="row"`.

This is a controlled supersession of the test-only metric interpretation. It
is not a production-code change, a relaxation, a retrospective real-metrics
pass, or completion evidence. The old real gate remains unpassed until fresh
final-code metrics are run and independently approved.

The retained report schema, semantic-projection schema, and isolated quality
evidence schema advance from `v1` to `v2`. This prevents an old bare-header/
grid-as-content report from validating under the superseding interpretation;
no final `v1` report is relabelled.

## Immutable inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| `benchmark-expertmodeldata/catastrophe-recap.pdf` | 58,779 | `d4d365e06715c4bf9b9ab2159caf79c1ef827234b3bf0b586357e3601795b87e` |
| `tracker/phase-03-layout/evidence/P03-US08-post-US07-predecessor-20260801/catastrophe-recap/our-output.json` | 69,758 | `f9db554d1975d498a6f9e3d53c0058716847335ee661c3fb3cd6c0c0acc8a4a3` |
| `tracker/phase-00-baseline/evidence/P00-US02-catastrophe-truth.json` | 144,444 | `d14d9f4bdbbffee24961d731b7bca75227eaec6bac77cce7508ded4252c9b4ac` |

The Phase-00/P04 structural oracle is unchanged. The new
`tests/fixtures/phase_04/tables/content_bbox_oracle.py` verifies all three
identities without following a workspace, ancestor, or leaf symlink; parses
the sealed predecessor as duplicate-key-free finite JSON; selects the exact
page-1 `p1-i3` table; validates all 30 row-major cell text/span/header facts;
normalizes only the predecessor's equal `w`/`width` and `h`/`height` aliases;
and exposes exact five-key `pt` bboxes. Its semantic identity is
`f730746f00e15e5aeeed5fdaf277c957098714242e723a52c63f4ee5c5e4d4ff`.

## Superseding rule

The immutable Phase-00 cell rectangle has role `grid_slot_bbox`. The public
P04-US01 cell rectangle has role `source_content_bbox`. Each of all 30 exact
cells must satisfy both checks:

1. exact row, column, row span, column span, text, and header flags;
2. exact five-key public bbox equality to the hash-bound content-bbox oracle,
   using the pre-existing at-most `0.011 pt` numeric comparison slack; and
3. whole-rectangle containment in the unchanged Phase-00 grid slot, using the
   same numeric slack.

Generic containment is insufficient. A shifted content rectangle, an
outside-slot rectangle, or the structural grid rectangle substituted as the
public content rectangle fails. Exact HTML/Markdown generation follows
retained header ownership and requires `scope="col"`/`scope="row"`, supported
row/column spans, escaping, and multiline breaks.

## Non-waiver and boundary

- Exact-cell and bbox denominators remain `30`; representation denominator
  remains `6` (`rows`, `value`, `cells`, HTML, Markdown, CSV).
- No threshold, tolerance, TEDS/GriTS implication, repeated-value count,
  reviewed denominator, unresolved exclusion, correctness, security,
  compatibility, custody, output, rollback, resource, latency, RSS, hosted-use,
  or all-corpus gate is waived.
- The all-corpus screen continues to call the corrected exact scorer; it is not
  replaced by a weaker local assertion.
- No pdfplumber candidate or vector-grid rectangle becomes canonical here.
  Reconciliation remains P04-US02 scope. P04-US04, P04-US03, and Phase 05 are
  untouched.
- This record changes neither story status nor terminal evidence. Fresh
  final-code identities, the opt-in reviewed quality run, all-corpus drift,
  full regressions, and independent production/security plus metrics/custody
  approvals remain required before P04-US01 can be marked Done.

## Superseded-code custody

The retained pre-edit review checkpoint binds the superseded executable bytes:

| Superseded path | Pre-supersession SHA-256 |
|---|---|
| `tests/fixtures/phase_04/tables/metrics.py` | `70c459df7a9279e8a872b239fbf6d0a168d7ad1e2270b8b5ffa7baf816038b0e` |
| `tests/performance/test_p04_us01_table_metrics.py` | `6d15443b951fa33e31a51a35261c0e120f240c42602821a2129b8c2aa3ffe4dc` |

These historical identities are copied verbatim from that retained checkpoint;
they are not reconstructed from the workspace, which has no repository history.
Final review must retain both historical identities and the exact final
identities rather than rewriting the old readiness record.
