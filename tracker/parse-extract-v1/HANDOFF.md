# Public source handoff

Updated: 2026-11-11

Read [STATUS.md](STATUS.md), [README.md](README.md), [DESIGN.md](DESIGN.md),
[CONTEXT.md](CONTEXT.md) and [PUBLIC_VALIDATION.md](PUBLIC_VALIDATION.md).

The checkpoint implements PX1-01 through PX1-04 locally, with simulated provider
results and original-byte storage. The normal library requires PostgreSQL,
private artifacts and a loopback development identity. Live provider execution
and production identity remain unavailable.

The separate published UI preview requires no database or backend and disables
all document actions. [Deployment instructions](../../docs/deployment-static-preview.md)
describe its explicit build mode and distinct publication guard. An early static
preview does not complete full product deployment or the live PX1 gate.

The complete local handoff, private account observations, explicit spending
authorization and original local run evidence were not published. Obtain that
context privately before any provider/account operation. Preserve source,
stored originals and the separate local implementation during continuation.
