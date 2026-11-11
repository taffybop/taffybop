# TaffyBop conversation summary

Updated: 2026-11-11  
Purpose: Durable context for continuing this product across separate chats

Current implementation checkpoint: PX1-01 through PX1-04 local work is verified,
including owned local routes/library and real browser/API/database restart
checks with explicitly simulated results. Full PX1 remains at its live provider
qualification gate. Read [STATUS.md](STATUS.md) and [HANDOFF.md](HANDOFF.md) for
the exact current boundary; deployment remains deferred.

## Goal and latest direction

The user wants a useful, affordable document micro-SaaS, built and verified end
to end. The active direction is a simple parsing and extraction workspace using
TaffyBop as the starting repository. Parsing uses LlamaParse; extraction uses our
own schema/prompt/validation backend with a low-cost LLM. The extraction screen
should resemble LlamaParse's extraction product in layout and interaction, while
remaining our own implementation.

The latest request is a phased implementation plan plus a summary that allows
work to continue in new chats. Complete one phase or bounded part of a phase at
a time. The active plan is [README.md](README.md); the exact next work is in
[STATUS.md](STATUS.md) and the reusable prompt is in [HANDOFF.md](HANDOFF.md).

## How the discussion evolved

1. The original aim was to turn TaffyBop into a working micro-SaaS and make it live. The user granted broad control and requested browser verification.
2. Hosting/account ownership proved difficult to establish through Render/GitHub and browser control was intermittently unavailable. The user later explicitly deferred deployment: validate locally and deploy after all local phases. Earlier deployment approval does not override that later instruction.
3. The user explored successful small/midsize document products and narrow niches: invoice fields/line items, tables, forms, handwriting, equations, charts and diagrams. HandwritingOCR, Mathpix, Cradl and LlamaParse were discussed as examples or references; no market winner or final vertical was established.
4. A broader idea emerged: one app that chooses parsers/models, then supports customizable branching, transformations, email and system actions. The scope was deliberately reduced to parsing first, with flexible source interfaces and automation later.
5. A barebones LlamaParse prototype was built. The user asked for three modes and free-tier use initially, with Mistral/other providers possible later.
6. The discussion addressed many app users sharing one provider account. The agreed direction was a durable shared queue, full-job concurrency controls, usage limits and fair scheduling. Extra app logins or API keys do not multiply provider capacity.
7. Direct Llama models and LlamaParse self-hosting were considered. Hosted APIs remain the starting choice; self-hosting has infrastructure/model/license costs and capacity constraints. It was not selected for launch.
8. The user then asked about extracting a field from its description, using a Cradl screenshot as an example: the first party's representative's first and last name. This requires semantic selection, beyond simply reading the document.
9. Cheap extraction models and full app operating costs were compared. The latest request expands the parsing prototype into a staged parse-and-extract product, with saved documents/configurations and a familiar extraction UI.

## Decisions to carry forward

- Reuse the current TaffyBop repository and working components. A new repository or wholesale rewrite is not required for this plan.
- Use LlamaParse initially. Product modes should be Fast, Cost-effective and Agentic after verifying current provider support. The current prototype instead has Cost-effective, Agentic and Agentic Plus; this mismatch is an implementation task.
- Keep parsing and extraction separate. Good parsing helps extraction but does not resolve role ambiguity, missing fields, repeated rows or schema correctness by itself.
- A saved workflow initially means a versioned parsing/extraction template. It does not imply a full automation engine.
- Use a stable source/result layout and fixed typed output. Show backend values faithfully; keep raw output, normalized presentation and human corrections distinguishable.
- Preserve document/page identity and evidence. Return null or review-required for ambiguity. An LLM confidence percentage is not a calibrated accuracy estimate.
- Save documents/results/templates on the backend, with owner checks, tier limits and expiry. Browser storage alone is not the durable product store.
- Share limits and budgets across UI and product API submissions. Keep a provider slot until the upstream job is terminal, including after local worker failure.
- Benchmark by document family and task. Distinguish parser failures, extraction failures, UI mismatches and infrastructure problems before changing providers or code.
- Use browser validation for actual uploads, template persistence, results, evidence navigation and exports. Local tests and mocked provider responses cannot prove live model quality.
- Deployment stays deferred. No new Render/GitHub account investigation is needed during local product phases.

## Model candidates and cost assumptions

Qwen3.7-Flash is the first low-cost extraction candidate to test, not an accuracy
winner. Ministral 3 3B and GPT-6 Luna are comparison candidates. Exact model
availability, regional schema support, current prices and terms must be checked
when integrations are implemented. In particular, Qwen's documentation had a
Singapore strict-schema limitation, so application validation is mandatory.

These were the pricing inputs checked during the conversation on 2026-11-11:

| Service | Planning rate | Official source |
| --- | --- | --- |
| LlamaParse Fast | $0.0015/page | [Pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/) |
| LlamaParse Cost-effective | $0.0045/page | [Pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/) |
| LlamaParse Agentic | $0.015/page | [Pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/) |
| Qwen3.7-Flash International, input <=32K | $0.03/M input tokens and $0.13/M output tokens | [Model pricing](https://www.alibabacloud.com/help/en/model-studio/qwen3-7-flash) |
| Ministral 3 3B | $0.10/M input and $0.10/M output | [Model](https://docs.mistral.ai/models/ministral-3b-latest) |
| GPT-6 Luna | $0.10/M input and $0.50/M output | [Model](https://developers.openai.com/api/docs/models/gpt-6-luna) |

For 5,000 input and 500 total billable output tokens per document, Qwen costs
$0.000215 per document. At 1,000 pages arranged as 200 five-page documents,
the example extraction cost is $0.043. Cost-effective parsing adds $4.50, giving
approximately $4.54 before retries and other operating expenses. Page count and
document count are different; LLM billing depends on tokens and call structure.

The user's expected parsing mix was 99% Fast and Cost-effective combined, 1%
Agentic. The split within that 99% is unknown and the mix has not been measured.
The operating estimate conservatively uses Cost-effective for the base pages.

## Full app operating estimate

The planning reference is approximately $75/month shared infrastructure plus
$6 per 1,000 pages for parsing, extraction, modest retained files/requests and
retry allowance. It is a forecast, not an observed bill or a capacity guarantee.

- Approximately $61/month covers a lean paid Render API, worker, database/storage and Pro workspace; around $14 is a domain/monitoring/operational allowance. [Render pricing](https://render.com/pricing)
- Low-volume transactional email may fit the free plan; Resend's paid starting plan is $20/month. [Email pricing](https://resend.com/pricing)
- Private object storage such as R2 costs $0.015/GB-month before its free allowance and request charges. The storage estimate assumes modest files and bounded retention; actual retained bytes accumulate. [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- Use expiring LlamaCloud uploads. Retained LlamaCloud files were priced at 100 credits/GB/day, equivalent to $4.50/GB for 30 days on pay-as-you-go. That is not included as the long-term library storage choice. [Storage pricing](https://developers.llamaindex.ai/llamaparse/general/pricing/)

| Monthly app-wide pages | Illustrative monthly total | Effective cost per 1,000 pages |
| --- | --- | --- |
| 1,000 | $81 | $81 |
| 10,000 | $135 | $13.50 |
| 50,000 | $375 | $7.50 |

The table assumes the same hosting allocation still suffices. Add upgrades,
payment fees, taxes, support/development time and acquisition spend as applicable.
Free parser credits can lower the launch bill but are shared by the provider
account, not granted independently to each app user. Paid checkout and final
subscription prices have not been selected.

Illustrative tier allowances discussed were Starter: 5 templates, 30 days, 5 GB;
Pro: 25 templates, 90 days, 25 GB; Business: 100 templates, 365 days, 100 GB.
These are configurable proposals, not approved customer commitments. Retention,
stored GB, processing credits and concurrent jobs need independent limits.

## Performance expectations

The proposed static CDN frontend, paid API and separate worker can support a
responsive application, but no capacity or speed result has been established
for that deployment. Provider parsing time is distinct from website loading.
Targets discussed were LCP <=2.5 seconds and INP <=200 ms at the 75th percentile,
following [Core Web Vitals](https://web.dev/articles/vitals). Local lab checks
help before release; real-user measurements are required afterward.

Current selected-page results are useful. Eager workspace imports, complete raw
JSON rendering, large response copies, and small instance memory are candidates
for measurement and improvement. Monthly page volume alone does not define peak
concurrent load.

## Working preferences and exclusions

The user prefers autonomous progress within the agreed scope, concrete browser
and API evidence, and minimal repeated permission questions. Preserve existing
dirty work. Keep one bounded implementation story in progress and make it easy
to continue in a new chat. Record incomplete checks honestly rather than calling
a mock or historical smoke test a completed end-to-end benchmark.

Do not copy credentials, personal account details, private documents or raw chat
secrets into handoffs. Keys remain server-side in local secret configuration.
Current access is checked when a phase needs it; previous browser interruptions
or account assumptions are not evidence of present availability.

This summary preserves the product decisions and their evolution. It does not
reproduce every repeated research request, old login attempt or secret-bearing
message. For exact current implementation facts, read [STATUS.md](STATUS.md).
