# Parse and extract status - public checkpoint

Updated: 2026-11-11

PX1-01 through PX1-04 local implementation is verified. Durable PostgreSQL
storage, immutable artifacts, fenced worker lifecycle and the local saved
library are implemented. Captured provider journeys remain labelled simulations;
full live parsing qualification is still open. Ordinary product Parse and
`--run-live` remain disabled. Hosted identity and later product phases are pending.

The user authorized an early no-database UI preview. Its uploads, saved history,
parsing, extraction, templates and downloads are disabled. A separate static
entry prevents calls to unavailable APIs. This does not complete PX1 or deploy
the durable backend. See [preview deployment](../../docs/deployment-static-preview.md),
[public validation](PUBLIC_VALIDATION.md), [plan](README.md) and [design](DESIGN.md).

Private account conditions, spending authorization and detailed local run
records were deliberately excluded from this public source export. Continue
with the full local handoff when performing work against provider credentials
or retained local records. No paid parser work is authorized by this export.
