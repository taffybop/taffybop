# P03-US08 Interactive Full-Default Correction and Renewal

Status: **Requester-authorized semantic correction; active, time-bounded renewal**  
Decision ID: `P03-US08-INTERACTIVE-FULL-DEFAULT-CORRECTION-20260814`  
Owner: Project owner/requester  
Recorded: 2026-08-14  
Review due: 2026-09-02

## Decision

For projected running-region results in the interactive Clearleaf workspace,
the initial page view is **Full**, not Body. Body remains an explicit opt-in
control. One selected view continues to drive the rendered preview, Markdown
source, clipboard copy, and page download. The compatibility serializer and
complete-document serialization retain their existing stored Full semantics;
this decision changes neither the public schema nor stored Body/Full block
membership.

This explicitly supersedes only the phrase “defaults projected pages to Body”
in P03-US08 acceptance criterion 7. It does not supersede the remainder of that
criterion or acceptance criteria 1–6, 8, or 9. It does not remove Body, infer
running regions in the frontend, renumber physical pages, or authorize a
frontend-only content rewrite.

The user authorized the correction while approving the Clinical physical-page-
1 release slice and requested that source header, visual-label, ordering, and
footer content be visible in the Markdown UI. Full is therefore the faithful
initial interactive view; Body remains useful when a consumer intentionally
wants running headers and footers excluded.

## Terminal replay correction

Source alignment may add only a source-proven space to an already classified
header/footer owner. Replaying P03-US08 after that authorized value correction
legitimately rekeys value-derived IR evidence IDs and, for a repeated cohort,
the signature-derived repetition-group ID. Final public/IR output retains the
new derived IDs. Comparison normalization is allowed only when:

- the owner was explicitly aligned and remains the same header/footer owner;
- each evidence record binds exactly to the rebuilt element, bbox, native
  method, and aligned value;
- the old-to-new repetition-group transition is one-to-one; and
- the closed member and page-index set is unchanged and every changed member
  is authorized.

An unaligned owner, wrong evidence binding, partial cohort, split/merge,
membership drift, unrelated descriptor mutation, missing source, or malformed
input rejects and restores the exact predecessor. Old IDs are never copied
back into the public result merely to satisfy a comparison.

## Identity and validation binding

The reviewed current identities are:

| Path | Bytes | SHA-256 |
|---|---:|---|
| `frontend/app/clearleaf-workspace.tsx` | 75,513 | `c7b27a2bf55bdfc2ebe4903653f4b3de8cdd2ad701d1ef42ca0dd9e7405679ab` |
| `frontend/tests/p03-us08-running-regions.test.mts` | 34,822 | `4cc249855be8b103ec09e3c6da567ab0b2ce91fdc4a4678e7d0f8174983531df` |
| `app/services/pipeline.py` | 391,034 | `0a36bd81adcc38b8e301717de2be07412ff11fa0e8f37a303405ff4d4784b9b7` |
| `tests/contract/test_p03_us08_running_region_source_spacing.py` | 26,343 | `a4e6eb3f2b3ad0790413167730fadd09abd56b585a289bb47bdfd91f00174eda` |
| `tests/contract/test_p04_us01_p03_boundary.py` | 147,458 | `43901a3ac9aa455ce3776b5892fbb1732b91fa57310832e92692458b4e659cb2` |

The focused frontend story file passes all **25** tests and `tsc --noEmit`
passes. The source-spacing/running-alignment focus passes **39** tests with
171 deselected and one warning. Nested owner corruption, owner loss, an extra
child, wrong binding, partial cohort, and derived-ID drift are covered as
fail-closed cases. The final Clinical page-one release integration passes
`1/1`, and the repository-native Clearleaf Full renderer shows the source-
spaced footer.

## Renewal boundary

P03-US08 remains `Done` under this requester-authorized correction and the
existing renewal chain. The existing 2026-09-02 review date, default-off
rollback, attempt-48 latency measurement, and every unwaived correctness,
security, custody, API, deadline, memory, and hosted-use condition remain in
force. This record adds no latency allowance and does not accept the open P04
table-custody result. A further required-code or semantic change expires this
renewal unless separately reviewed and recorded.
