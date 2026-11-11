# PX1 provider qualification

Checked: 2026-11-11 (Asia/Kolkata)
Scope: Public official documentation plus current local source; no provider calls

## Parsing configuration

LlamaParse remains the parsing service. The public API supports the following
tiers; the first three are the product scope. Account-specific acceptance,
quality and billing have **not** been requalified in this checkpoint.

| Tier ID | Base estimated credits/page | Published current version |
| --- | --- | --- |
| `fast` | 1 | `2026-06-15` |
| `cost_effective` | 3 | `2026-09-28` |
| `agentic` | 10 | `2026-09-29` |
| `agentic_plus` | 25 | `2026-09-28` |

Base prices exclude optional processing surcharges. Pay-as-you-go conversion is
$1.50/1,000 credits: the product tiers correspond to $0.0015, $0.0045 and $0.015
per page before optional extras, retries and account discounts. These are public
list estimates, not observed charges. The legacy prototype's 45-credit Plus
estimate disagrees with the current 25-credit list rate. Its modes and response
contract remain unchanged by PX1-01. [Official pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/)

Both tier and version are explicit parse settings. A dated version pins parsing
behavior; `latest` can move. The dated values above come from the public API
reference, not an authenticated versions response. Before qualifying a product
worker, verify acceptance with the intended account and persist the selected
version in job settings. Never substitute a different tier automatically.
[API create reference](https://developers.llamaindex.ai/reference/resources/parsing/methods/create/),
[versions reference](https://developers.llamaindex.ai/reference/resources/parsing/methods/list_versions/)

Fast has no AI model or custom prompt/forms/chart extraction. Current Fast
supports markdown and items; versions before `2026-06-15` are text-only and reject
markdown expansion. Omitted output must remain unavailable rather than being
fabricated. [Official tiers](https://developers.llamaindex.ai/llamaparse/parse/guides/tiers/)

The existing client uses the documented multipart `POST /api/v2/parse/upload`
with `file` plus JSON-string `configuration`; create returns top-level `id` and
`status`. Polling `GET /api/v2/parse/{id}` returns these under `job`. Preserve the
existing byte-exact raw GET contract while the product API adds its own envelope.
[REST guide](https://developers.llamaindex.ai/llamaparse/parse/guides/api-reference/)

## Retention, budgets and actual usage

Parse uploads and cache are documented as lasting 48 hours. Job-result retention
and presigned-link lifetimes are not published. Retained Files API objects last
until deletion; files with an expiration are ephemeral. Our own source and result
storage is required for durable history. No undocumented expiration parameter
was added to the parse-upload call. [Data retention](https://developers.llamaindex.ai/llamaparse/general/data_retention/)

Retained files are listed at 100 credits/GB/day; ephemeral files incur no storage
charge. [Storage pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/)

Current billing documentation lists 10,000 monthly free credits on Pay as you go
and five concurrent Parse jobs. These are public plan facts, not proof of this
account's remaining balance or billing settings. Auto-reload and legacy extra
usage settings can incur charges. No plan, purchase or billing setting was
changed. Per-job credits may remain null after completion; retain a pending
reconciliation state until actual usage arrives.
[Billing and usage](https://developers.llamaindex.ai/llamaparse/general/billing/)

The safe initial worker policy is one shared-account slot covering submission
through terminal state, no automatic ambiguous-create retry, no tier upgrade,
and fail-closed live-test admission until configured spending limits and account
credit conditions are known. This is an implementation recommendation, not an
implemented queue or budget control in PX1-01.

## Evidence boundaries and next check

- Detailed local account observations are withheld from this public export; live qualification remains disabled.
- No extraction provider/model was selected. Qwen3.7-Flash remains the first
  benchmark candidate; exact availability and pricing must be checked in PX4.
- The TinyFish research skill was read. Its installed CLI could not reach
  `agent.tinyfish.ai`; available web browsing retrieved the official pages above
  as an explicitly recorded fallback. No paid automation/research run ran.
- Next provider check: after durable admission exists, verify configured test
  limits/free-credit conditions and run a bounded authorized synthetic PDF/image
  qualification, recording raw bytes, selected tier/version and actual usage.
