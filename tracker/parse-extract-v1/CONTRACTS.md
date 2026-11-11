# PX1 product contracts v2.0

Frozen checkpoint: PX1-01, 2026-11-11  
Implementation: [models](../../app/product/contracts.py), [provider configuration](../../app/product/provider_config.py)  
Machine-readable definition: [JSON Schema](contracts/v2.schema.json)

Current implementation update: [PX1-03 worker core](WORKER.md) now implements
private durable lifecycle/cancellation, terminal persistence and guarded simulated
execution with finite allowances. [PX1-04](ROUTES.md) now connects local product
HTTP routes and the saved library. Live execution stays disabled: ordinary
Parse returns 503 without enqueueing. The frozen resource wire schema is
unchanged; local config and bounded job history are additive envelopes.

These are executable boundary models and a reviewed schema snapshot. No `/v2`
routes, durable records, identity adapter or worker are registered in PX1-01.
The models validate public snapshots; they do not implement the state machine,
ownership checks, foreign keys, storage immutability or budget admission.
Implement those in the ordered PX1/PX2 stories before exposing the product API.
Extraction schemas/reviews are still PX3/PX4; this freeze adds no extraction data.

PX1-02 now implements private relational constraints, ownership/availability
checks and immutable artifact/result storage; see [PERSISTENCE.md](PERSISTENCE.md).
These wire models and schema are unchanged. That checkpoint did not enable
product routes, authentication or the later PX1-03 worker.

## Versioning and compatibility

New product routes use `/v2`; resource bodies carry `schema_version: "2.0"`.
Models reject extra fields, invalid states and naive timestamps. Resource IDs
are opaque UUIDs. Byte counts/page numbers are strict integers, never booleans.
Models and nested settings/artifact references are frozen; page collections are
tuples internally and arrays on the wire. The database must enforce immutable
result/settings snapshots separately. API consumers must not infer durability
from the mere existence of these definitions.

The JSON Schema is a **definition bundle**, not a standalone resource union.
Select `#/$defs/Document`, `DocumentList`, `ParseRequest`, `Job` or `ParseResult`
as the consumer entry point. Pydantic additionally checks cross-field invariants
(timestamps, lifecycle, usage and format availability); JSON Schema alone does
not reproduce those checks. Decimal credit values serialize as strings or null
without binary rounding. Regenerate deliberately and review changes:

```sh
.venv/bin/python -m app.product.export_contracts
.venv/bin/python -m pytest tests/test_product_contracts.py tests/test_product_provider_config.py -q
```

Existing `/v1/parse` and `/v1/llamaparse/*` behavior remains unchanged. In
particular, `GET /v1/llamaparse/jobs/{token}` returns the provider's original JSON
bytes without a product envelope or reformatting. Its tokens still expire and
are lost on restart. Product UUIDs are not aliases for those bearer tokens.
There is no automatic migration of lost in-memory jobs. Historical parser
records and fixtures retain their own contracts.

Before the product worker runs against the shared provider account, legacy
submission must use the same admission service or be mutually exclusive with
that worker. Hosted mode must disable anonymous legacy submission. PX1-01 has
not implemented either profile or enabled a second submitter.

## Frozen PX1 HTTP boundary

| Resource | Input | Success response | Implement in |
| --- | --- | --- | --- |
| `POST /v2/documents` | Multipart `file` only; no owner or local storage path | `201 Document` | PX1-02 persistence; PX1-04 routes |
| `GET /v2/documents` | `limit` 1–100 (default 25), optional opaque cursor | `200 DocumentList` | PX1-04 |
| `GET /v2/documents/{id}` | Document UUID | `200 Document` | PX1-04 |
| `POST /v2/documents/{id}/parse` | Required `Idempotency-Key` header, JSON `ParseRequest` | `202 Job` | PX1-03 worker; PX1-04 routes |
| `GET /v2/jobs/{id}` | Job UUID | `200 Job` | PX1-04 |
| `POST /v2/jobs/{id}/cancel` | No body | `202 Job` while requested; `200 Job` if already terminal | Initial semantics PX1-03; recovery PX2-03 |
| `GET /v2/parse-results/{id}` | Result UUID | `200 ParseResult` | PX1-04 |
| `GET /v2/artifacts/{id}/content` | Artifact UUID, owner/retention authorization | Original media type and exact stored bytes | PX1-02 storage; PX1-04 routes |

PX1-04 implements these local routes except live parse admission, which remains
503 until the qualification gate is met. Additive `/v2/config` and owned
`/v2/documents/{id}/jobs` expose availability and provenance without changing the
frozen Job/ParseResult bodies. See [ROUTES.md](ROUTES.md) for exact local behavior.

Use the existing sanitized `{ "error": { "code": "...", "message": "..." } }`
shape for HTTP failures. Error text must be fixed public-safe text, never a
provider exception body, key or document excerpt. No stack traces are public.
Nonexistent/inaccessible resources return the same 404. Validation/admission
must precede billable provider work. Apply `Cache-Control: no-store` to private
metadata/errors/results/downloads; content hashes are integrity metadata, not
cross-owner cache keys.

Parse requests must explicitly select a mode; an omitted mode cannot silently
override the server's configured UI default. The server resolves its dated
version into the immutable job snapshot.

The idempotency key is a nonempty printable ASCII string, at most 128 bytes,
scoped to the server-derived owner and operation. Repeat with the same document
and settings returns the same job; reusing a key with different input returns
409. Lifetime covers the retained job, including uncertain submissions. The
transaction/uniqueness enforcement belongs to PX1-02/PX2-03, not these DTOs.
List ordering is `(created_at DESC, id DESC)` with owner-scoped opaque cursors.
No client-supplied owner is accepted. A loopback development principal needs an
explicit local profile in PX1-04; production identity remains PX2-01.

## Document, job and result meaning

- `Document.source` identifies original bytes with SHA-256, byte length and
  detected MIME. Preserve the initial PDF/PNG/JPEG, 10 MiB, ten-page and 20M-pixel
  validation limits; images are one page. Display names are sanitized basenames.
  `active`, `deleted` and `expired` describe access state, not processing status.
  A deleted/expired record never grants artifact access. Retention evaluation
  and deletion are server duties in later stories.
- `Job.settings` is a server-authored immutable snapshot: provider/adapter,
  selected mode, dated provider version and page limit. `attempt` starts at one.
  Provider job IDs, owner keys, submission intent, leases/fencing and storage
  paths belong in private database records. A future attempt must not mutate the
  settings or raw results of a prior attempt.
- Nonterminal states are `queued`, `submitting`, `submission_unknown`, `running`
  and `cancel_requested`. `succeeded` requires a persisted result reference;
  `failed` carries a sanitized terminal error. Terminal states have a finish
  time. A request timestamp alone never proves cancellation. `cancelled`
  requires confirmation; its request time may be null for provider-originated
  cancellation. A confirmed local cancellation before submission is also valid.
- `submission_unknown` is unresolved acceptance, not a known failure. It must
  retain capacity/budget intent; do not automatically recreate it. A worker
  lease expiring or a browser stopping polling cannot prove upstream completion
  or cancellation. Lifecycle transitions/recovery are implemented in PX1-03/PX2.
- `Job.raw_response` references original terminal provider JSON even for failure
  or cancellation. It can be null if no valid provider reply exists (for example
  local validation failure). `ParseResult.raw` is mandatory for success and
  references those same bytes. The database must check job/document/result
  relationships and matching artifact hashes. Do not create a successful result
  for a failed provider job just to expose its raw reply.
- `ParseResult.markdown` and `.text` have independent ordered page lists. Each
  page retains its provider page number and content without trimming, sorting,
  deduplication, merging or invented separators. Repeated page IDs remain
  repeated. `available`, `empty`, `not_returned` and `unsupported` are distinct;
  an available page may contain an empty string. Unknown optional structures
  remain inspectable in raw output, with no fabricated presentation.
- `requested_version` is a dated configuration pin; `provider_version` remains
  null unless actually reported upstream. Do not copy the requested pin into
  an observed-version field. Preserve items/metadata/unknown sections in raw;
  they have no invented normalized equivalents in this contract.
- Raw downloads use stored bytes, never `json.dumps` of the model or parsed
  provider object. Human corrections must eventually be separate versioned
  revisions; no model here allows a correction to replace raw provider output.

## Provider settings and usage

The secret-free config loader reads only `TAFFYBOP_PARSE_MODE` and
`TAFFYBOP_LLAMA_PARSE_VERSION`. Defaults are Cost-effective / `2026-09-28`;
Fast / `2026-06-15` and Agentic / `2026-09-29` are the other documented pins.
Invalid configuration fails without a fallback or tier upgrade. Custom dated
pins are representable, but base-price estimation fails until that pair has a
reviewed price entry. This loader is **not yet wired into the legacy client**.

Config marks live qualification false and the initial future slot limit one.
That number is not an implemented queue or proven account capacity. Credentials
remain in the server-side provider transport; no credential is loaded into these
models. Public documentation checks and price provenance are in
[PROVIDERS.md](PROVIDERS.md). No free-credit balance or account settings were read.

`Usage.estimated_credits` requires `estimate_price_version`; neither is an actual
charge. `actual_credits` stays null while reconciliation is `pending` or
`unavailable`; `observed` requires a nonnegative finite observed value. An actual
zero is distinct from unknown. Results may succeed with pending usage. A result's
usage is immutable **at capture**; later observations belong to the usage ledger
and updated job snapshot, without rewriting original result bytes/settings.
Reservations remain until reconciliation/explicit policy resolution in PX2.

The reviewed base estimates (1/3/10 credits per page) are not spending guards.
Account conditions, configured free credits and explicit test limits must be
verified before any live qualification. No live provider call, automatic retry,
model selection or plan change is enabled by this contract work.
