# Render deployment

Keep `taffybop.io` on the existing static service and deploy the Python parser
as a separate Docker web service. The static service cannot execute Python.
This runbook records the intended configuration, not a completed deployment.
No successful Render image build, public parse, or capacity test is asserted.

## Services

| Setting | Existing frontend | Proposed API |
| --- | --- | --- |
| Service | `srv-da0a5hm417fc73cdgu90` | `taffybop-api`; ID and public URL pending creation |
| Repository | `https://github.com/taffybop/taffybop` | Same |
| Branch | `main` | `codex/backend-fidelity-foundation` |
| Type | Static site | Docker web service |
| Build/publish | Blank build command; publish directory `.` | Repository-root `Dockerfile`, build context `.` |
| Start | Static files | Keep Docker CMD: `python -m app.release_start` |
| Public address | `https://taffybop.io` | `https://<created-api-host>`; replace after creation |

API placement: **My project → Production → Oregon**. The UI candidate is
**4 GB RAM / 2 CPUs / $85 per month**, pending approval and creation when this
runbook was prepared. This is a trial configuration, not a capacity guarantee.
Do not create an additional static service or change the custom domain.

## Configure and verify the API first

1. Record the source commit, chosen plan, region, environment values and eventual
   service/deploy IDs. Configure the API from
   [`deploy/render-api.env.example`](../deploy/render-api.env.example).
   Keep deployment manual while validating the candidate.
2. Use `/healthz` as the health-check path. Keep the Docker start command and
   Render-provided `PORT`: the entry point binds `0.0.0.0` with one worker.
   Preserve Docker's generated artifact manifest/digest verification; do not
   substitute the local launcher or bypass the release gate to obtain green health.
3. Confirm the image actually builds and its startup verification passes.
   Model downloads happen during the image build. Runtime uses
   `/opt/docling-models`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and
   `PARSER_LATENCY_PREWARM_ENABLED=false`. The template preserves all 33 enabled
   feature flags from `start-ui-backend-8042.sh` without editing that launcher.
4. Replace the placeholder below with the URL Render assigns, then retain the
   actual responses, response headers, timings and source hashes as evidence.
   `/healthz` checks the process, not model readiness or extraction correctness.

```bash
API_ORIGIN='https://<created-api-host>'
curl --fail-with-body --max-time 30 "$API_ORIGIN/healthz"
curl --fail-with-body --max-time 330 \
  -H 'Origin: https://taffybop.io' \
  -F 'file=@frontend/public/samples/customer-support-handbook.pdf;type=application/pdf' \
  "$API_ORIGIN/v1/parse?output_format=json" \
  -D /tmp/taffybop-api-handbook.headers \
  -o /tmp/taffybop-api-handbook.json
curl --fail-with-body --max-time 30 -X OPTIONS \
  -H 'Origin: https://taffybop.io' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type' \
  -D - -o /dev/null "$API_ORIGIN/v1/parse"
```

Repeat CORS checks for `https://www.taffybop.io`; allowed origins must be exact,
without wildcards or credentials. Confirm an unrelated origin receives no
allow-origin grant. CORS does not authenticate callers or prevent direct API use.
Test a real image as well as the PDF, and verify two simultaneous uploads and
oversized uploads return the intended errors without crashing the process.

The initial bounds are 20 MiB per file, 21 MiB for the entire multipart body,
20 pages, 20 million pixels per image and 40 million total image pixels.
`PARSER_MAX_CONCURRENT_PARSE_REQUESTS=1` admits one parse per API process across
upload and processing; an additional parse receives `429 parser_busy` with
`Retry-After`. Declared oversized bodies are rejected before spooling; streamed
body bytes are checked before each chunk reaches the multipart parser. The configured
`PARSER_UPLOAD_TIMEOUT_SECONDS=60` sets an absolute admitted-upload deadline;
receiving another chunk does not reset it. Expiry returns `408 upload_timeout`.
Incomplete, cancelled and rejected multipart uploads close their temporary files.
The separate 180-second document timeout is not a hard end-to-end deadline. Measure cold
and warm requests, memory and timeout behavior before raising these bounds.

Review output against source truth. The saved local PDF baseline matched its
12 reviewed paragraphs. The local intake-form PNG baseline omitted
`Intravenous` and returned a 1×2 table candidate for an expected 3×3 table.
These are known extraction limitations, not successful table extraction.
Keep warnings visible; do not equate HTTP 200 or confidence signals with accuracy.
The [offline evaluator](../tests/benchmarks/routing_evaluation.md) can compare
saved real API JSON with source-hashed expectations without making model calls.

## Publish the static frontend after API verification

The API address is compiled into the static bundle. Changing Render environment
values on the existing static service will not change already-built JavaScript,
especially with its blank build command.

After the API and browser access are verified, build locally from the reviewed
release checkout with Node.js 24. Use the same real API origin throughout:

```bash
cd frontend
npm ci
npm run check
TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL="$API_ORIGIN" \
  npm run build:static
```

Serve `frontend/dist-static` locally to inspect the release, then validate the
deployed-origin browser path and CORS before enabling publication. The explicit
readiness value below is an operator assertion; it does not test the API:

```bash
TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL="$API_ORIGIN" \
TAFFYBOP_STATIC_API_GATEWAY_READY=1 \
  npm run build:release
```

Review the generated root files and `site-manifest.json`, then publish that
reviewed artifact through `main` to the existing static service. Do not publish
from an unverified API candidate. Keep the static publish directory `.` and
blank build command; the repository root holds the prebuilt public files.

On `https://taffybop.io/studio`, verify PDF and image uploads, raw JSON copy and
download, source preview, warnings and visible server errors. Retain browser
network evidence and compare downloaded JSON hashes with the response bytes.
Check `/`, `/studio`, `/knowledge` and `/privacy`, plus apex/www redirects.
Only these live checks establish that the public frontend reaches the new API.

## Rollback

Record the previous successful Render deploy before each update. If the new
frontend fails, roll the static service back to the deployment for commit
`643ace6` (the previous Knowledge Studio), then verify its public pages. Use
Render's deployment rollback; do not force-push or reset shared history.

For an API regression, restore its previous successful deployment and matching
environment values, then rerun a real PDF and image parse. On the first API
deployment there is no previous API deployment: restore the static frontend and
suspend the failed API candidate instead. Keep automatic deployment disabled
while investigating so a new deployment cannot immediately undo the rollback.
Record the failure and retained evidence before retrying.
