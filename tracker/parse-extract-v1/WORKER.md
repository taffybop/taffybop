# PX1-03 durable worker checkpoint

Updated: 2026-11-11. **PX1-03 local implementation is complete**: the durable
lifecycle and packaged simulated runner are verified with finite admission and
actual process/database restart. Live execution is deliberately unavailable;
account/free-credit conditions and enforceable charge bounds remain unknown.
Next: PX1-04 local product routes/library. No successful live parse, full PX1
qualification or production worker deployment is claimed.

## Local admission profiles

[Runtime profiles](../../app/product/runtime_profile.py) accept `legacy_local`
(default compatibility behavior), `product_worker_local`, and `disabled`.
Invalid profiles reject submission. Product/disabled profiles reject legacy
POSTs before intake. The additive config field `submission_enabled` describes
profile admission separately from credential presence in `configured`.

Every cooperating local process must use the same private
`TAFFYBOP_PROVIDER_LOCK_PATH`, default `tmp/product/provider.lock` in this
checkout. The lock is held for the process lifetime, including provider waits;
do not unlink or replace it. A private fsynced journal records legacy intent
**before** POST, then its acknowledged provider ID. Only observed terminal
polling clears legacy activity. TTL, process death and missing browser polling
do not clear it. Product acquisition rejects any unresolved legacy activity.

Product ownership is sticky in the journal across worker exit. Returning to
legacy requires an operator to reconcile both durable product jobs and provider
account activity before explicitly clearing that journal; no automatic reset
command is supplied. Tests and restart evidence use isolated lock paths. These
locks do not coordinate another checkout, host, key, or external account client.
Production-wide identity/fair scheduling remain PX2 work.

## Durable lifecycle

[Migration 002](../../app/product/migrations/002_worker.sql) adds a private
execution record, one global provider slot, an admission pause and consistency
constraints. [WorkerRepository](../../app/product/lifecycle.py) serializes
transitions with a transaction advisory lock. This is deliberately conservative:
one active job across all owners, with no second worker process in the local
runtime profile. It is not a throughput qualification.

1. Claim an active, unexpired queued source. Commit `submitting`, submission
   intent, slot, random fencing token and lease **before** calling the adapter.
2. Store the acknowledged provider ID immediately and transition to `running`
   (or retain a cancellation request). IDs cannot be replaced or shared by two
   executions. The next step polls that ID, never calls create again.
3. An ambiguous POST or expired submitting lease becomes `submission_unknown`.
   Its slot remains held indefinitely. Even a crash before actual send is
   treated conservatively. Late acknowledgements from expired claims cannot
   publish; explicit unknown reconciliation remains PX2 work.
4. Known IDs survive lease expiry and restart. Poll errors/unknown statuses
   retain capacity with persisted, bounded backoff. Browser GETs do not drive
   this polling. Definite submission rejection fails that job and durably
   pauses further admission so a bad key or exhausted credits cannot drain the
   backlog through repeated POSTs. No automatic admission-unpause is provided.
5. A fenced terminal capture stores original bytes and successful normalized
   pages, or failure/cancellation raw output, in the same transaction as job
   publication and slot release. Storage failure or lease expiry during fsync
   rolls metadata back and retains capacity. A private orphan file can remain.
   The earlier synthetic capture method refuses any worker-admitted job.
6. Owner revocation still blocks every public repository read. Accepted work
   continues private polling after source deletion/expiry to reconcile capacity;
   revoked queued sources are never admitted. Queued cancellation is confirmed
   locally. Cancellation of submitting/unknown work is only a timestamp; known
   accepted work remains `cancel_requested` and polls until actual terminal
   evidence. There is no undocumented provider-cancel call.

[The adapter](../../app/product/provider.py) submits exactly once with immutable
product tier/version/page settings, independently of legacy configuration. Raw
JSON bytes, unknown properties, page order/repeated IDs and whitespace survive.
Unsupported optional output is labelled unsupported. Missing actual credits and
reported versions remain unknown; requested settings are never presented as an
observed version. Terminal usage may still be pending; later billing
reconciliation and budget reservations remain unfinished.

## Finite simulated admission

[Migration 003](../../app/product/migrations/003_test_allowance.sql) adds immutable
test allowances and append-only reservations. The [allowance model](../../app/product/allowance.py)
requires an ID, explicit job-ID allowlist, exact parse settings, UTC expiry,
finite job/page/credit/USD caps and positive artificial credit/page and USD/credit
rates. **These are authored simulation units, not live prices or spending permission.**
The same allowance ID with changed content is rejected; restarting with the
original file never resets its consumption. A new allowance is a new explicitly
configured local test, not an automatic renewal.

Admission reserves `settings.max_pages` (not the unverified stored page count),
and its exact credit/USD amounts under the existing database admission lock.
Reservation, submission intent and capacity commit atomically before simulated
submission. Database constraints also reject cap overflow, altered reservations
and mismatched settings. Failure, cancellation, unknown acceptance, missing or
zero observed usage never refund this finite allowance. This intentionally
conservative test ledger is separate from later production usage reconciliation.

Expiry/exhaustion stops new admission. The original allowance can still recover
its accepted ID and publish a terminal response. Governed, ungoverned and foreign
allowance executions cannot recover or mutate each other's active claims. This
prevents a simulated runner from falsely completing an existing live execution.

## Execution and current boundary

`Worker.run()` remains a private injectable lifecycle seam. The packaged command
now exposes `--check` and bounded `--run-simulated`; both require the explicit
product profile and private database/storage configuration. Dispatch acquires
the process-lifetime lock before allowance registration or worker steps. The
simulator never reads provider credentials or constructs an HTTP transport, and
its raw/normalized output is explicitly labelled as authored simulation.
The application has no new background import effect and the browser still uses
v1; product HTTP/history remains PX1-04.

Use the [retained-cluster startup commands](PERSISTENCE.md), then:

```sh
export TAFFYBOP_DATABASE_URL='host=/path/to/taffybop/tmp/px1-02/socket port=55471 user=local_user dbname=postgres'
.venv/bin/python -m app.product.manage migrate
TAFFYBOP_RUNTIME_PROFILE=product_worker_local \
TAFFYBOP_ARTIFACT_ROOT="$PWD/tmp/px1-03/artifacts" \
.venv/bin/python -m app.product.worker --check
```

Preflight checks the profile, absolute artifact-root configuration, database,
all migration checksums and required tables. It does **not** create storage,
register an allowance, acquire/change the admission journal, migrate implicitly,
verify account conditions, or make provider requests.

The [guarded restart harness](PUBLIC_VALIDATION.md) generates actual
allowance JSON for isolated simulated queues. To run against an explicitly
prepared allowance, use:

```sh
TAFFYBOP_RUNTIME_PROFILE=product_worker_local \
TAFFYBOP_ARTIFACT_ROOT="$PWD/tmp/px1-03-guarded/store/accepted/artifacts" \
TAFFYBOP_PROVIDER_LOCK_PATH="$PWD/tmp/px1-03-guarded/store/accepted/runtime/provider.lock" \
.venv/bin/python -m app.product.worker --run-simulated \
  --allowance "$PWD/tmp/px1-03-guarded/store/accepted/allowance.json" --steps 4
```

Use the matching isolated scenario database URL from the private harness record,
not the administration database. The command executes 1–1000 steps (default 4),
with 0.1–30 seconds between steps; exiting retains active capacity/reservations.
`--simulation-outcome` selects authored faults: `submission_unknown` or
`submission_rejected` affect new submission; `running` or `poll_unavailable`
affect polling. Already accepted simulated IDs otherwise complete. Outcome policy
is a per-invocation test input, not immutable provider behavior or corpus output.

`--run-live` always exits before database/key/transport access. Do not enable it
by reusing simulated rates or public base estimates. Actual live calls need
verified account/free-credit conditions, explicit credit/USD test limits and an
enforceable charge bound. A local key's existence is insufficient. This live gate
does not prevent reversible PX1-04 routes/library work with labelled simulations;
successful live PDF/image parsing remains a full PX1 qualification requirement.

## Evidence

The [starting snapshot](PUBLIC_VALIDATION.md) records the unchanged
branch/HEAD, dirty status and 103 non-secret hashes. Earlier dirty work and
historical parser records were retained. No dependency version changed.

[Restart preparation](PUBLIC_VALIDATION.md) and
[verification](PUBLIC_VALIDATION.md) use two isolated databases
inside the retained task cluster. PostgreSQL was actually stopped and started.
Fresh child worker processes recovered a known simulated ID without recreating
it, persisted byte-exact PDF/PNG synthetic terminal responses, admitted the
queued image only after PDF completion, and retained an uncertain job/queued
backlog without a second simulated create. Four source artifacts reopened
byte-exactly. All provider observations in this harness are explicitly authored
simulations; **real provider HTTP calls: zero**.

Run the harness with `prepare`, perform a real task-cluster stop/start, then run
`verify`, using the same arguments:

```sh
export TAFFYBOP_TEST_DATABASE_URL="$TAFFYBOP_DATABASE_URL"
.venv/bin/python tracker/parse-extract-v1/evidence/check_worker_restart.py prepare \
  --record "$PWD/tmp/px1-03/worker-restart-record.json" \
  --store "$PWD/tmp/px1-03/worker-restart" \
  --output "$PWD/tracker/parse-extract-v1/evidence/px1-03-restart-prepare.json"
```

For another run, choose new record/store/output paths rather than overwriting
existing evidence. The private manifest records isolated database names and no
credentials. [STATUS.md](STATUS.md) records final tests, HTTP/browser evidence,
resource shutdown and the exact next step.

The latest [guarded preparation](PUBLIC_VALIDATION.md) and
[guarded verification](PUBLIC_VALIDATION.md) use the **packaged CLI**
instead of a private step harness. PostgreSQL was actually stopped/started.
Fresh CLI processes recovered one accepted simulated ID without recreation;
the exhausted allowance preserved the queued PNG after capacity release. A
separate uncertain scenario retained both its reservation and active slot.
Four source artifacts reopened exactly; the 308-byte synthetic terminal raw
response retained its simulation label and unknown actual usage. These records
do not claim that PNG parsing completed or that a provider was contacted.

Reproduce with **new** record/store/output paths: run
`evidence/check_guarded_worker.py prepare --record ABSOLUTE_PATH --store ABSOLUTE_PATH --output ABSOLUTE_PATH`,
actually stop/start the task cluster, then run `verify` with the same record/store
and a fresh output path. Set `TAFFYBOP_TEST_DATABASE_URL` to the administration
socket DSN above. All source documents are authored development fixtures.

Official adapter shape references refreshed in the earlier worker-core checkpoint:
[combined upload and configuration](https://developers.llamaindex.ai/llamaparse/parse/guides/api-reference/),
[polling response and usage](https://developers.llamaindex.ai/reference/resources/parsing/methods/get/).
Public documentation is not proof of this account's accepted versions or charges.
