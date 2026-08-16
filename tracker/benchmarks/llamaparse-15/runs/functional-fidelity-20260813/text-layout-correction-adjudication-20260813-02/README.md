# Text/layout correction adjudication — 2026-08-13

This immutable ledger covers the six-case bounded source-grounded correction
pass. The PDF source is authoritative; LlamaParse remains the comparison
baseline. The machine-readable record is [`ledger.json`](./ledger.json).

The affected service recapture is
[`service-text-layout-correction-20260813-02`](../service-text-layout-correction-20260813-02):
eight successful fresh-server HTTP outputs and ten repository-native rendered
body DOM pages. Its `run.json` SHA-256 is
`d50d633748f75bca71fe0222a19f7cd481be69ed1c9b050d5bee940373f54011`.
No `service-final-20260813` or LlamaParse reference artifact was overwritten.
The earlier `-01` directory is preserved as a non-final capture attempt.

| PDF | Adjudication |
|---|---|
| catastrophe-recap | Match; already correct. |
| finance-10k | Fixed, with a non-rendering JSON `md` marker accepted on pages 2–3. |
| ny-timetable | Fixed. |
| postal-10k | Partially fixed; detached full FERS, table-cell italics, and four em dashes remain. |
| purchase-agreement | Fixed; deletion presentation intentionally follows the source. |
| settlement-agreement | Accepted/already correct for Look-Back spelling and clause hierarchy. |

No fresh signed-in LlamaParse browser session was available to this worker, so
the newest immutable references are hash-bound in the ledger instead of being
recaptured.
