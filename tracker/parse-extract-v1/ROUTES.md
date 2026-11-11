# PX1-04 local routes and saved library

Updated: 2026-11-11. Local implementation and validation record; deployment is
deferred. Full PX1 still requires successful live PDF/image parsing after the
account and enforceable spending gate is satisfied.

## Local startup

Use a dedicated PostgreSQL database and private artifact directory. Apply the
packaged migrations explicitly with `python -m app.product.manage migrate` and
the private `TAFFYBOP_DATABASE_URL`. Startup checks installed migration checksums
without applying changes. See [retained database commands](PERSISTENCE.md).

```sh
export TAFFYBOP_DATABASE_URL='host=/absolute/private/socket port=55471 user=local_user dbname=local_product'
export TAFFYBOP_ARTIFACT_ROOT='/absolute/private/product/artifacts'
export TAFFYBOP_LOCAL_OWNER='local-developer'
bash start-local-product.sh
```

Open `http://127.0.0.1:8042/documents`. The script selects
`TAFFYBOP_PRODUCT_MODE=local_development`, `TAFFYBOP_DEPLOYMENT=local` and
`TAFFYBOP_RUNTIME_PROFILE=product_worker_local`. It clears the provider key,
checks the existing worker schema, builds the static frontend and binds only
loopback with proxy-header interpretation disabled. It does not load `.env`,
seed documents, start workers, apply migrations or call a provider.

Changing the configured owner selects a different library. All clients of the
same local server use that owner. This is an explicit development principal,
not separate user login or production authentication. The mode rejects hosted
deployment markers and nonlocal runtime configuration. Requests require direct
loopback peer/Host, matching local Origin when supplied and acceptable fetch
metadata. Forwarding headers are rejected. Bind behind no forwarding proxy.

## Product behavior

- `/`, `/studio` and `/documents` open the durable library. `/legacy` retains
  the ephemeral v1 parsing screen, disabled in the product runtime profile.
  `/extract` explains its unavailable status; schema extraction/templates remain
  later work. Both static and Next/Vinext routes use the same product component.
- Upload saves original bytes after existing type, size, page and pixel checks.
  It does not create a job. Save-only use needs no provider key.
- `/v2/config` reports local identity, upload availability, mode names/default
  and `parse_enabled: false`. `POST /v2/documents/{id}/parse` validates ownership
  and returns a sanitized 503 without enqueueing or accessing a transport.
- The [frozen metadata/read/cancellation routes](CONTRACTS.md) are connected to
  durable repositories. All private responses/errors use `Cache-Control:
  no-store`. Foreign and missing resources have the same fixed 404 response.
- `GET /v2/documents/{id}/jobs` adds a bounded newest-first history of at most
  100 entries: `{schema_version, jobs: [{job, evidence_kind}]}`. The fixed Job
  wire model is unchanged. Immutable simulated-allowance reservations establish
  `simulation`; older authored captures without that evidence are `unverified`.
  Job/result/raw reads also carry `X-TaffyBop-Evidence`. None is labelled live.
- Source previews read authorized private bytes. Artifact downloads preserve
  original bytes and media type; `?download=true` requests attachment. Raw JSON
  is always an attachment, with a safe server-authored filename.
- `?document=UUID&job=UUID` preserves selection through refresh/reopen. Polls read
  our saved jobs; they never poll the provider. Result pages retain backend
  order, repeated page IDs, empty strings and whitespace. Raw preview is bounded
  to 1 MiB; original download remains available. Unknown usage stays unknown.
- Cancelling an unsubmitted queued job can confirm locally; accepted/uncertain
  work retains a request until terminal confirmation. A browser closing or
  stopping polling does not cancel a provider job.

The history limit is explicit: older runs beyond the latest 100 are not paged
by this story. Document history uses `(created_at DESC, id DESC)` opaque cursors.
Production identity, fair scheduling, billing reconciliation, physical cleanup
and backup enforcement remain later work. No template service is enabled.

## Validation

The fresh pre-change focused baseline passed **361 Python tests**, including
112 real PostgreSQL checks, with one existing Starlette warning. The starting
[snapshot](PUBLIC_VALIDATION.md) records dirty work and source hashes.
The reproducible [local harness](PUBLIC_VALIDATION.md) starts with
an empty isolated database; the actual browser uploads authored sources before
private finite simulations exercise progress/results. Simulations do not parse
the document and are not evidence of model accuracy or live usage.

Final checks passed **486 Python tests**, including **169 real PostgreSQL
checks**, and lint/typecheck/Vinext build, **261 frontend unit tests**, five
bundle checks and static build. Real HTTP assertions passed **61 before / 64
after** actual API and PostgreSQL restart. The offline wheel contains the new
modules and existing migrations byte-exactly. The full launcher itself was not
invoked; its syntax was checked, and the API/browser used the isolated harness.

The [actual browser record](PUBLIC_VALIDATION.md) and
[validation](PUBLIC_VALIDATION.md) distinguish authored simulation
from real browser/API/storage evidence. The API and database are stopped with
their data retained in ignored `tmp/px1-04/library` and `tmp/px1-02/pgdata`.
To revisit that exact saved library, first start the retained task cluster as
documented in [PERSISTENCE.md](PERSISTENCE.md), set
`TAFFYBOP_TEST_DATABASE_URL` to its private administrative socket DSN and run:

```sh
.venv/bin/python tracker/parse-extract-v1/evidence/check_product_library.py serve
```

This reads the ignored local manifest, binds port 8043 and exposes only the
recorded development owner. `verify-restart` checks the initial two captured
results and optional recorded format-simulation job set. The third format
simulation was created after the actual restart, so it is separate presentation
evidence, not a third restarted result. Do not rerun `setup`/`enqueue`/`fidelity`
over retained evidence; use a new explicitly isolated scenario for new work.
