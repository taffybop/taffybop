# Static workspace preview

The user authorized publication of the current checkpoint as a **no-database
UI preview** on 2026-11-11. This supersedes the earlier deployment deferral only
for this preview. The full product, hosted identity, database, workers and live
provider qualification remain unfinished.

The preview is a separate static entry point. It shows the document workspace
layout and clearly disables uploads, saved history, parsing, extraction,
templates and downloads. It contains no document inputs, saved/sample results,
product API client or provider integration. Existing `/legacy` and `/knowledge`
paths also show the disabled preview. Preview privacy text describes this scope.

The normal local API/library build is unchanged and still requires PostgreSQL,
private artifact storage and the explicit loopback development principal.
Do not enable that identity on a public host.

## Build and verify

Use the existing Node 24 environment from `frontend`:

```sh
npm run check
TAFFYBOP_STATIC_MODE=preview npm run build:static
```

Preview mode rejects a configured `TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL` or
`TAFFYBOP_STATIC_API_GATEWAY_READY`; leave both unset. The generated
`static-api-config.json` must declare `deploymentMode: "preview"` and
`parseApiUrl: null`. Verify the built site in a real browser: disabled document
actions, honest empty source/results, correct privacy text, refresh/deep links,
and no `/v1`, `/v2` or provider requests.

After that verification, the distinct publication command is:

```sh
TAFFYBOP_STATIC_MODE=preview TAFFYBOP_STATIC_PREVIEW_READY=1 \
  npm run build:release
```

This copies only allowlisted static artifacts and a hash manifest to the
repository root. The readiness value is an operator assertion following the
browser checks; it does not enable an API. Normal API publication retains its
separate endpoint and readiness guard.

## Existing host and source checkpoint

Verify the current signed-in Render workspace, existing static service, tracked
GitHub branch, blank build command and publish directory before updating the
site. Reuse the existing domain/service without changing DNS or adding a paid
database/backend. Record the previous deployed commit for rollback. Public HTTP
asset hashes and the live browser must match the release after deployment.

Publish a reviewed source checkpoint and static release through the existing
GitHub repository. Keep local secrets, databases, uploaded artifacts, browser
downloads, account/billing evidence and private run records out of the public
export. Preserve the full local checkout and private evidence. Public tracker
summaries must state when detailed local evidence was withheld; they must not
present a sanitized summary as an original raw record.

Rollback uses the prior Render deployment or a normal Git revert of the static
release. Do not force-push shared history. Publishing this preview does not
complete the live PX1 gate or any later product phase.
