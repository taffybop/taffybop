# TaffyBop document workspace

TaffyBop is a standalone web interface for the existing Python document parser.
It uploads PDFs and supported image files over HTTP, previews the original file
where the browser can render it, and presents the parser's normalized content
as page-aligned Markdown or complete-document JSON.

The frontend does not contain parsing or OCR logic and does not change the
backend's `/v1/parse` endpoint, multipart `file` field, `output_format` query
parameter, or response bodies.

## Supported inputs

- PDF (`.pdf`)
- PNG (`.png`)
- JPEG (`.jpg`, `.jpeg`)
- TIFF (`.tif`, `.tiff`), including multiple frames when the backend detects them
- WebP (`.webp`)

The browser checks the extension, declared MIME type, empty-file state, and
configured upload size before sending. The backend remains authoritative for
file signatures, corruption, decoded-pixel limits, orientation, and page/frame
limits.

## Result workflow

The workspace displays one physical document page and that page's Markdown at a
time. Its single page navigator keeps the PDF or raster-image preview and
Markdown result synchronized. Browsers do not reliably render TIFF, so TIFF
files show a clear preview fallback; after parsing, the same navigator moves
through the backend-detected TIFF frames and their page-specific results. The
JSON tab is document-wide: it contains every page in one scrollable,
syntax-highlighted viewer with line numbers, folding, and a clickable structure
summary.

Markdown copy and download operate on the selected page. JSON copy and download
always operate on the complete document and use a filename without a page
suffix. Page navigation does not submit another request and does not reset the
JSON viewer's scroll or fold state.

When a response contains the backend's versioned `canonical_presentation`
contract, that stored contract is authoritative for document/page Markdown,
semantic text, header/footer views, page content gating, rendered results,
copy, and download. The frontend does not trim, reorder, or reconstruct those
bytes. Rendered mode selects only the block IDs in the canonical page's full
view and displays their semantic text as escaped, whitespace-preserving React
content; omitted audit blocks and legacy OCR cannot leak into the display.

The JSON tab applies a non-breaking presentation normalization to the cached
API response. It groups page text, Markdown, structured items, metadata,
images, and generated-result metadata in a reference-friendly shape while
retaining the backend's original page, item, table, geometry, confidence,
warning, and additive fields. A validated canonical contract remains unchanged
at the normalized document's top level and supplies `markdown_full`,
`text_full`, and page views verbatim. When the canonical field is absent, older
responses retain the legacy item-based fallback. A present malformed or
unsupported contract fails closed instead of silently switching semantics.
When the backend does not provide a confidence, image, or generated file, the
UI reports it as unavailable or empty instead of inventing a value.

Source-grounded table captions returned by the backend remain distinct
`caption` items and are rendered immediately before their linked tables. The
frontend preserves their bbox, provenance fields, and `caption_of`
relationships in complete-document JSON; it does not move caption text into
table cells or infer missing relationships. The parser's default-off layout
flag remains the sole rollout and rollback control.

Source-grounded visual captions use the same escaped visible-caption milestone.
Validated internal visual children remain additive `contained_items` in JSON
and never become rendered prose. OCR suppression is applied only when an owner
explicitly carries `layout_visual_relationships_projected=true`; a marked owner
may expose raw OCR only with `include_ocr_in_primary=true`. Unmarked responses
retain the exact legacy UI and normalization precedence, including explicitly
present empty strings, so disabling the backend visual-relationship flag
restores the earlier frontend behavior.

## Requirements

- Node.js 22.13 or newer (Node.js 24 LTS is recommended)
- The existing Python parser running at a URL reachable by this application

## Run locally

From this `frontend` directory:

```bash
cp .env.example .env.local
npm ci
npm run dev
```

Then open `http://localhost:3000`. The checked-in example already targets the
local parser at `http://127.0.0.1:8000`.

Do not rename or move `.env.example`. Keep it as the safe configuration
template, copy it to `.env.local`, and edit `.env.local`. Environment files are
not committed.

### Deterministic rendered-UI benchmark capture

The functional-fidelity harness can render retained `response.json` artifacts
through the same React page components used by the interactive results pane.
This path does not start a browser or reinterpret Markdown, and defaults to the
UI's initial **Body** presentation view:

```bash
npm run capture:rendered-ui -- \
  --run-dir ../tracker/benchmarks/llamaparse-15/runs/<run>/service
```

For every case containing `response.json`, the command writes
`pages/page-<N>/rendered-dom.json` with the analyzer contract
`{ page_number, html, text }` plus `rendered-capture.json` with source and
output hashes. Use repeatable `--case <case-id>` filters for a bounded rerun or
`--view full` to capture the user-selectable Full presentation instead.

## API transport

The recommended request path is:

```text
browser → POST /api/parse → POST {PARSE_API_URL}/v1/parse
```

The server-side proxy forwards the multipart body and output format to the
existing parser without transforming successful or error responses. This keeps
the parser URL out of browser code and normally avoids browser CORS changes.

Set `NEXT_PUBLIC_PARSE_API_URL` only when the browser must call the parser
directly. Direct mode requires the parser or gateway to allow the exact frontend
origin, `POST`, `Accept`, and multipart form requests. Never manually add a
multipart `Content-Type` header; the browser must generate its boundary.

## Configuration

| Variable | Purpose |
| --- | --- |
| `PARSE_API_URL` | Server-side parser base URL or full `/v1/parse` endpoint |
| `PARSE_API_TIMEOUT_MS` | Same-origin proxy timeout; defaults to 330 seconds |
| `NEXT_PUBLIC_PARSE_API_URL` | Optional direct browser parser URL; blank uses the proxy |
| `NEXT_PUBLIC_PARSE_API_TIMEOUT_MS` | Browser request timeout; defaults to 330 seconds |
| `NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES` | Client preflight limit; defaults to 20 MiB |

For development, staging, and production, deploy the same frontend artifact and
change only environment values. Production parser URLs should use HTTPS and must
be reachable from the frontend runtime. Variables prefixed with `NEXT_PUBLIC_`
are visible in the browser and must never contain credentials or secrets.

Example staging values:

```dotenv
PARSE_API_URL=https://parser-staging.example.com
PARSE_API_TIMEOUT_MS=330000
NEXT_PUBLIC_PARSE_API_URL=
NEXT_PUBLIC_PARSE_API_TIMEOUT_MS=330000
NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES=20971520
```

## Quality checks

```bash
npm run lint
npm run typecheck
npm test
```

`npm test` creates a production build, tests PDF and image validation plus API
error mapping, verifies proxy pass-through behavior, checks deterministic
Markdown and full-document JSON normalization, and inspects the built upload
workspace.

## Deployment

Deploy this directory independently from the Python API:

1. Install dependencies with `npm ci`.
2. Configure `PARSE_API_URL` in the frontend hosting environment.
3. Run `npm run build`.
4. Deploy the generated Cloudflare/vinext worker artifact using the frontend's
   own release pipeline.

No frontend deployment step should run backend migrations, package backend
code, or modify the parser service.

## Troubleshooting

- `413`: the document exceeds a frontend gateway or backend upload limit.
- `415`: the extension and MIME type are unsupported or do not agree.
- `422`: the backend rejected an invalid, damaged, encrypted, or unsupported
  PDF/image, or an image exceeded configured pixel/frame limits.
- `503`: the parser is unavailable or the frontend proxy URL is invalid.
- `504`: parsing exceeded the configured request timeout.
- Network/CORS error in direct mode: allow the deployed frontend origin at the
  parser gateway, or clear `NEXT_PUBLIC_PARSE_API_URL` to use the proxy.
- Empty result: the request succeeded, but the parser reported no readable page
  items; the raw JSON response remains available.
