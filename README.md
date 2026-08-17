# TaffyBop

A local Python API that accepts PDF, PNG, JPEG/JPG, TIFF, and WebP documents,
plus default-off DOCX, PPTX, and XLSX native adapters, and returns normalized
JSON, Markdown, or plain text. It combines native source evidence, layout and
table analysis, image detection, and Tesseract OCR while retaining honest
geometry or an explicit logical-coordinate state and reading order.

The document itself is processed locally and is not sent to a remote service.
The first setup may download Docling model weights; pre-download them to run the
service without network access afterward.

## API

`POST /v1/parse` is the only document-processing endpoint.

It accepts:

- `file`: a multipart PDF, PNG, JPEG/JPG, TIFF, WebP, or enabled DOCX/PPTX/XLSX upload.
- `output_format`: query parameter: `json` (default), `markdown`, or `text`.

PDF to JSON:

```bash
curl --fail-with-body \
  -X POST "http://localhost:8000/v1/parse?output_format=json" \
  -H "accept: application/json" \
  -F "file=@Original document.pdf;type=application/pdf" \
  -o parsed.json
```

PDF to Markdown:

```bash
curl --fail-with-body \
  -X POST "http://localhost:8000/v1/parse?output_format=markdown" \
  -H "accept: text/markdown" \
  -F "file=@Original document.pdf;type=application/pdf" \
  -o parsed.md
```

The same endpoint and query parameter are used for image files. For example,
PNG to JSON:

```bash
curl --fail-with-body \
  -X POST "http://localhost:8000/v1/parse?output_format=json" \
  -H "accept: application/json" \
  -F "file=@scanned-form.png;type=image/png" \
  -o scanned-form.json
```

TIFF to Markdown:

```bash
curl --fail-with-body \
  -X POST "http://localhost:8000/v1/parse?output_format=markdown" \
  -H "accept: text/markdown" \
  -F "file=@multipage-scan.tiff;type=image/tiff" \
  -o multipage-scan.md
```

Image uploads must use a supported filename extension and the matching declared
MIME type. Accepted pairs are `.png` with `image/png`, `.jpg` or `.jpeg` with
`image/jpeg` (also `image/jpg` or `image/pjpeg`), `.tif` or `.tiff` with
`image/tiff` (also `image/x-tiff`), and `.webp` with `image/webp`. The decoded
format and file signature are checked as well. Existing PDF clients retain
their current behavior, including support for the established PDF and generic
binary MIME types.

DOCX, PPTX, and XLSX remain unsupported until their Phase 07 conformance,
OOXML-intake, and format-specific native flags are enabled. Office packages are
then inspected in memory under configured ZIP/XML limits; macros, formulas,
fields, and external relationships are never executed or fetched.

FastAPI also exposes interactive OpenAPI documentation at
`http://localhost:8000/docs`.

## Output model

All output formats are serialized from the same normalized item stream. This
keeps Markdown and JSON reading order consistent. A shortened JSON response
looks like this:

```json
{
  "schema_version": "1.0",
  "document": {
    "filename": "Original document.pdf",
    "mime_type": "application/pdf",
    "sha256": "4d2f...",
    "page_count": 6,
    "image_count": 4
  },
  "pages": [
    {
      "page_index": 5,
      "page_number": 6,
      "page_label": "6",
      "page_width": 612.0,
      "page_height": 792.0,
      "unit": "pt",
      "success": true,
      "items": [
        {
          "id": "p5-i1",
          "type": "heading",
          "reading_order": 0,
          "value": "Table of Contents",
          "md": "# Table of Contents",
          "level": 1,
          "bbox": {
            "x": 54.0,
            "y": 72.0,
            "w": 180.0,
            "h": 18.0,
            "width": 180.0,
            "height": 18.0,
            "unit": "pt"
          },
          "source": "native",
          "confidence": null
        }
      ],
      "warnings": []
    }
  ],
  "processing": {
    "engine": "docling",
    "ocr_engine": "tesseract",
    "ocr_languages": ["eng"],
    "duration_ms": 1423
  },
  "warnings": []
}
```

`page_index` is the one-based physical position in the uploaded document. A
single image has one page with `page_index` and `page_number` both set to `1`.
Each frame in a multi-page TIFF becomes a separate page in frame order.
Animated PNG/WebP inputs intentionally use their first frame; TIFF is the
supported multi-page raster container.
`page_label` is the printed or embedded document label, and `page_number` is
its integer form when possible. They can differ when an excerpt skips a printed
page, or when front matter uses labels such as Roman numerals. Consumers should
use `page_index` for array navigation and `page_label` for citations shown to
people.

Every content item has a stable page-local ID and `reading_order`. Common item
types are `heading`, `text`, `list`, `table`, `image`, `chart`, `diagram`,
`form`, `key_value`, `header`, and `footer`.
Type-specific fields extend the base item: for example, tables include rows,
cells, spans, HTML, Markdown and CSV representations; forms retain explicit
graph cells, links, and fields; images include OCR text and OCR line items.
Each page also has a `detected_images` catalog, including
images whose OCR was merged into a table or into structured items for a
full-page scan. Bounding boxes use a top-left origin and PDF points.
For image inputs, page dimensions and bounding boxes use pixels (`px`) after
EXIF orientation correction. Native PDF text has no synthetic confidence
score; OCR items include the recognizer's confidence when available.

For charts and diagrams, the default path retains the detected content type,
OCR text, geometry, metadata, confidence, and parse concerns without inventing
values or relationships. The default-off Phase 05 controls can add a strictly
validated `visual_structure` sidecar for supported, source-grounded chart or
diagram evidence. Unsupported, ambiguous, malformed, or over-budget content
keeps the useful predecessor image/chart/diagram fallback instead of returning
fabricated series, values, connectors, or labels. Structured output remains
owned by the original chart or diagram and is never promoted to a second table.

Markdown keeps headings and lists as Markdown, emits tables as HTML where that
is necessary to preserve row or column spans, and represents detected images
by their recognized text. Detailed geometry and provenance remain available in
JSON.

### Table span-fidelity preview and rollback

P04-US01 table span fidelity is a local-only, default-off preview controlled by
`PARSER_TABLES_SPAN_FIDELITY_ENABLED=false`. Enabling it requires all three
predecessor controls below to be true; configuration fails closed instead of
silently enabling a dependency:

```dotenv
PARSER_SHARED_IR_ENABLED=true
PARSER_SHARED_IR_NORMALIZATION_ENABLED=true
PARSER_CANONICAL_SERIALIZATION_ENABLED=true
PARSER_TABLES_SPAN_FIDELITY_ENABLED=true
```

For an eligible already-selected Docling table, the preview can preserve
explicit repeated or blank cells, source-supported row and column spans,
header ownership, multiline text, cell bboxes, provenance, and matching
rows/HTML/Markdown/CSV representations. A successfully admitted overlay adds
an additive JSON `table_evidence` sidecar. Its cells are authoritative only
when `table_evidence.status` is exactly `valid` and the complete bounded
schema, grid, evidence links, representations, and custody hashes verify. An
unresolved, structurally failed, malformed, oversized, or custody-invalid
overlay never supplies a replacement grid; the exact predecessor table remains
authoritative. Every non-null source-content rectangle must also remain inside
its independently bound table region. The containment check allows an
inclusive `0.500 pt` edge-rounding tolerance; it establishes table ownership
only and never substitutes for the closed source grid or assigns a span slot.
If the private predecessor snapshot is missing, cyclic, oversized, too deep,
or cannot be copied, rollback fails closed: every affected table candidate is
quarantined and the operation raises instead of returning a mutated projection
with its marker removed. The preview does not reconcile table engines, decide whether
charts/forms/aligned prose are tables, or merge tables across pages.

Uploaded content and span-fidelity processing stay local. The preview does not
add hosted inference or a network path. As with the base parser, install model
artifacts before operating offline.

To roll back, set `PARSER_TABLES_SPAN_FIDELITY_ENABLED=false` (or remove the
variable) and restart every application worker so its cached settings are
rebuilt. Keep `PARSER_TABLES_EVIDENCE_RECONCILIATION_ENABLED`,
`PARSER_TABLES_CANDIDATE_GATE_ENABLED`, and
`PARSER_TABLES_MULTI_PAGE_MERGE_ENABLED` false. With all four table flags off,
the parser emits the predecessor JSON and Markdown without a Phase 04 table
sidecar. This flag change is the rollback mechanism; production enablement
still requires separate approval.

## Architecture

The request path is intentionally small:

1. FastAPI validates the filename, declared media type, signature, upload size,
   and requested output format.
2. A thin input adapter loads the source into a common page model: the existing
   PDF loader retains PDF page geometry and native text, while Pillow decodes
   image inputs, applies EXIF orientation, and expands TIFF frames into pages.
3. Both adapters produce the same page/region evidence model. Docling then
   performs layout, heading, reading-order, table, form, and visual analysis.
4. The same standard/sparse Tesseract OCR, confidence filtering, text
   normalization, and overlap reconciliation run for direct images and
   PDF-rendered regions.
5. PDFs prefer native text and geometry. Visual work is selected only for
   scanned pages, embedded visuals, uncovered charts/diagrams, unreliable
   tables, or incomplete layout text; pdfplumber still supplements vector
   tables.
6. Shared services resolve reading order, de-duplicate native/layout/OCR
   evidence, classify visual regions, retain concerns, and serialize the same
   normalized result as JSON or Markdown.

The adapter boundary keeps format-specific loading out of the shared extraction
and serialization pipeline:

```text
PDF loader                         Image loader
  native text + geometry             decode + EXIF orientation
  embedded images                    multi-frame TIFF expansion
  selective page/region renders      oriented raster pages
             \                         /
              v                       v
               shared page + region evidence
                           |
          layout / OCR / tables / charts / diagrams
          reading order / dedup / confidence / concerns
                           |
                      JSON / Markdown
```

Every visual region has a `region_role` (`page_source` or `content_region`),
`region_origin` (`uploaded_page`, `pdf_embedded`, or `pdf_page_render`), and a
coordinate unit. A selectively rendered PDF region is analysis evidence and
does not inflate the source document's `image_count`.

The application disables Docling remote services. No uploaded document content
is transmitted by the parsing pipeline. See the
[Docling pipeline options](https://docling-project.github.io/docling/reference/pipeline_options/)
and [Tesseract documentation](https://tesseract-ocr.github.io/) for the
underlying local engines.

## Local setup

Python 3.11 through 3.14 is supported; Python 3.13 is a good deployment target.
Install Tesseract with English language data first.

macOS with Homebrew:

```bash
brew install tesseract
```

Debian or Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
```

Create the environment and install the app:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Download the local layout and table models once:

```bash
mkdir -p .models/docling
docling-tools models download layout tableformer picture_classifier \
  -o .models/docling
export DOCLING_ARTIFACTS_PATH="$PWD/.models/docling"
```

If an existing artifacts directory does not yet contain the optional picture
classifier, image parsing still runs layout analysis, OCR, tables, and
normalization, and reports that classification was skipped in `warnings`.
Installing the classifier later restores chart/diagram/image classification
after the service is restarted.

That command needs network access only to obtain the model artifacts; it does
not process or upload a document. With the artifacts present, the service can
run on a network-isolated host. For an explicitly offline shell, also set:

```bash
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

### Optional parser prewarming

Prewarming is disabled by default, so startup and converter caching are the
same lazy path as the predecessor. To enable it, first freeze the local model
tree and installed runtime, enable the two offline controls above, and derive
the expected identities with the exact service interpreter and OCR settings:

```bash
export DOCLING_ARTIFACTS_PATH="$PWD/.models/docling"
export TESSERACT_CMD="$(realpath "$(command -v tesseract)")"
export TESSERACT_DATA_PATH="$(realpath /opt/homebrew/share/tessdata)"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
PARSER_LATENCY_PREWARM_ENABLED=false .venv/bin/python -c \
  'from app.config import Settings; from app.services.parser_worker import artifact_identity, dependency_identity; s=Settings.from_env(); print("artifact=" + artifact_identity(s.docling_artifacts_path).sha256); print("dependency=" + dependency_identity(s).sha256)'
```

Copy those two lowercase digests into
`PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256` and
`PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256`. Setting
`PARSER_LATENCY_PREWARM_ENABLED=true` is supported only when the process is
launched by the reviewed, capability-bearing Darwin/non-root supervisor. That
supervisor pre-binds a dedicated Tesseract broker, fork-denied parser worker,
external watchdog, and their private inherited control sockets before any
parser dependency is imported. These private descriptors and identities are
not operator configuration and must not be synthesized in an `.env` file.
Plain `uvicorn`, the Docker command, Linux, root, or a missing/invalid
supervisor capability fail closed before readiness when the flag is true.

The supervised evidence boundary treats the privately staged Tesseract image
and its recursively resolved native/Mach-O dependency closure as trusted,
pinned computation. Every non-system image, vnode identity, load-command
graph, rpath resolution, and source/staged projection is hashed before launch
and reobserved at shutdown. Apple system-library references are bound to the
running sealed-OS/dyld-cache identity; that trust is recorded explicitly.
This is dependency custody, not a claim that a malicious native binary is
contained. Hard process-count denial still prevents Tesseract descendants,
and the reviewed outer profiles and controller-owned probes separately prove
the required network and filesystem-write denials on the approved host.

In that supervised topology, the enabled application validates the
complete artifact content, installed core distribution RECORD content,
Tesseract binary/symlink chain, and every configured language file before and
after constructing its uncached PDF and image converters. It also validates
the concrete converter options and initializes both pipelines under the
existing conversion lock. Readiness is published only after that transaction
succeeds. Missing or changed identities, offline controls, dependencies, or
artifacts fail startup closed; the configured deadline has a process-fatal
watchdog so a stuck initializer cannot leave a serving process behind.

Each request leases that process-owned converter pair and rechecks the PID,
frozen settings, artifact metadata, converter/options identity, and offline
environment. Shutdown stops admission, drains active leases within the grace
period, clears the converters' initialized pipelines and owned references, and
fails the process closed if initialization or a lease cannot terminate. Model
downloads remain out of scope: `DOCLING_ARTIFACTS_PATH` is mandatory,
Docling remote services are disabled, and both Hugging Face offline controls
are mandatory. Recompute both expected digests only after an intentional
artifact, package, Python, Tesseract, or OCR-language change.

Rollback is only:

```bash
export PARSER_LATENCY_PREWARM_ENABLED=false
```

Auxiliary prewarm values are not parsed while that switch is false, so stale
or malformed timeout and digest variables cannot affect lazy startup.

Start one lazy predecessor worker (the default/rollback mode):

```bash
export PARSER_LATENCY_PREWARM_ENABLED=false
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

Do not use that direct command with prewarming enabled. The supervised launch
entry points are private evidence/operations plumbing and intentionally require
pre-created capability FDs, exact process identities, frozen profiles, and an
external watchdog; there is no permissive fallback to direct process spawning.

Docling's current installation and model-download commands are documented in
the [installation guide](https://docling-project.github.io/docling/getting_started/installation/)
and [CLI reference](https://docling-project.github.io/docling/reference/cli/).

## Release artifact verification

Phase 08 provides an offline, profile-bound build/startup gate. It is disabled
when both `PARSER_RELEASE_ARTIFACT_MANIFEST_PATH` and
`PARSER_RELEASE_ARTIFACT_MANIFEST_SHA256` are unset, so the default local-core
startup is unchanged. Setting either variable requires both. The manifest must
match the externally pinned lowercase SHA-256, the repository-owned release
profile, and the bytes below `PARSER_RELEASE_ARTIFACT_ROOT` (the process working
directory when that optional root is unset). A partial configuration, unknown
artifact/capability, required-artifact downgrade, unusable source/license,
candidate-root escape, or byte mismatch fails startup before requests are
served. Optional failures resolve their canonical shipping capabilities to the
documented local fallback.

Generate and verify a candidate inventory without network access:

```bash
.venv/bin/python -m app.services.artifact_manifest generate \
  --release-id <bounded-release-id> \
  --candidate-root <candidate-root> \
  --output <release-manifest.json>
.venv/bin/python -m app.services.artifact_manifest verify \
  --manifest <release-manifest.json> \
  --expected-sha256 <digest-from-independent-release-control> \
  --candidate-root <candidate-root>
```

The checked-in Phase 08 developer reference is explicitly labelled for Darwin
arm64/Python 3.13. It uses the `local_reference` profile, contains concrete
hashes and installed metadata for the eight direct Python distributions pinned
in `pyproject.toml`, and leaves visual models and Office fallback rendering
optional-disabled. It is not a production manifest.

The Docker build uses the production profile after every selected artifact is
installed. It generates and immediately verifies exact Python/Torch records;
installed Debian package identities, complete file/symlink inventories, and
shipped Debian copyright records for Tesseract/OCR data and native libraries;
and the exact revision, model-card source/license, and complete bytes of all
three downloaded Docling repositories. Missing or unusable candidate-local metadata
fails the image build instead of inventing evidence. The final image starts
through `app.release_start`, reads the image-generated digest, and selects the
same production manifest before Uvicorn imports the application. A changed
manifest or artifact therefore fails before serving. Exhaustive transitive
supply-chain/license automation remains deferred; it is not implied by this
bounded direct selected-artifact inventory.

## Configuration

Copy `.env.example` as a reference and export values in the service process.
The app reads environment variables directly; it does not automatically load a
`.env` file.

| Variable | Default | Purpose |
| --- | ---: | --- |
| `MAX_UPLOAD_BYTES` | `20971520` | Maximum multipart file size (20 MiB). |
| `MAX_DOCUMENT_PAGES` | `100` | Maximum PDF pages or image frames per request. |
| `MAX_PDF_PAGES` | `100` | Backward-compatible fallback when `MAX_DOCUMENT_PAGES` is unset. |
| `MAX_IMAGE_PIXELS` | `50000000` | Maximum decoded pixels in one image frame. |
| `MAX_IMAGE_TOTAL_PIXELS` | `100000000` | Maximum decoded pixels across all image frames. |
| `DOCUMENT_TIMEOUT_SECONDS` | `300` | Overall Docling document timeout. |
| `OCR_LANGUAGES` | `eng` | Comma-separated Tesseract language codes. |
| `TESSERACT_CMD` | `tesseract` | Tesseract executable name or absolute path. |
| `TESSERACT_DATA_PATH` | unset | Optional directory containing language data. |
| `TARGETED_OCR_TIMEOUT_SECONDS` | `30` | Timeout for each targeted OCR process. |
| `TARGETED_OCR_SCALE` | `5` | Render scale for embedded-image OCR. |
| `TARGETED_OCR_MAX_PIXELS` | `16000000` | Pixel ceiling for one OCR crop. |
| `IMAGE_PRIMARY_OCR_MIN_CONFIDENCE` | `0.45` | Shared visual-OCR confidence threshold; rejected candidates remain in diagnostics. |
| `IMAGE_LOW_CONFIDENCE_MIN_ALNUM_CHARS` | `8` | Minimum informative length that can retain a moderately low-confidence visual OCR line. |
| `IMAGE_HEADING_MIN_CONFIDENCE` | `0.75` | Minimum confidence for geometry-based heading recovery from page OCR. |
| `IMAGE_HEADING_HEIGHT_RATIO` | `1.8` | Minimum recovered-line height relative to median text height for heading inference. |
| `IMAGE_HEADING_MIN_PAGE_HEIGHT_RATIO` | `0.025` | Minimum line-height/page-height signal used by heading inference. |
| `IMAGE_PICTURE_CLASSIFICATION_THRESHOLD` | `0.6` | Minimum optional classifier confidence for chart/diagram routing. |
| `PDF_VISUAL_ANALYSIS_ENABLED` | `true` | Enable selective PDF page/region rendering when native/layout evidence is insufficient. |
| `PDF_RENDER_OCR_MIN_NATIVE_ALNUM_CHARS` | `24` | Sparse-native-text signal used by selective PDF rendering. |
| `PDF_RENDER_OCR_MIN_LAYOUT_COVERAGE` | `0.55` | Render a native PDF page when layout text covers less than this share of native tokens. |
| `IMAGE_CAPTIONING_ENABLED` | `false` | Enable optional local SmolVLM descriptions for visual regions in either input type. |
| `IMAGE_CAPTIONING_PROMPT` | faithful one-sentence prompt | Prompt for optional local semantic descriptions. |
| `PARSER_ADAPTERS_CONFORMANCE_ENABLED` | `false` | Route PDF/image loading through the versioned Phase 07 adapter registry; disabling restores the legacy dispatch path. |
| `PARSER_ADAPTERS_IMAGE_PARITY_ENABLED` | `false` | Enable shared direct-image/PDF-render semantic comparison; requires adapter conformance. |
| `PARSER_ADAPTERS_OOXML_INTAKE_ENABLED` | `false` | Enable bounded, non-executing OOXML intake; requires adapter conformance. |
| `PARSER_ADAPTERS_DOCX_NATIVE_ENABLED` | `false` | Advertise and parse DOCX through native XML evidence; requires OOXML intake and conformance. |
| `PARSER_ADAPTERS_PPTX_NATIVE_ENABLED` | `false` | Advertise and parse PPTX through native XML evidence; requires OOXML intake and conformance. |
| `PARSER_ADAPTERS_XLSX_NATIVE_ENABLED` | `false` | Advertise and parse XLSX without formula execution; requires OOXML intake and conformance. |
| `PARSER_ADAPTERS_OFFICE_CHARTS_ENABLED` | `false` | Prefer grounded PPTX/XLSX native chart data; requires both native adapters. |
| `PARSER_ADAPTERS_OFFICE_FALLBACK_ENABLED` | `false` | Add bounded native-first rendering only for unresolved Office placeholders; requires the Phase 07 native/chart/parity stack. |
| `PARSER_ADAPTERS_FUTURE_CONFORMANCE_GATE_ENABLED` | `false` | Require future adapters to pass the Phase 07 compatibility gate before registration. |
| `PARSER_ADAPTERS_OOXML_MAX_*` | see `.env.example` | Enabled-only package, part, XML, relationship, and time safety limits. |
| `PARSER_ADAPTERS_XLSX_MAX_*` | see `.env.example` | Enabled-only worksheet/sparse-range/cell safety limits. |
| `PARSER_ADAPTERS_OFFICE_FALLBACK_MAX_*` | see `.env.example` | Enabled-only renderer-output byte, region, pixel, and timeout bounds. |
| `DOCLING_ARTIFACTS_PATH` | unset | Pre-downloaded Docling model directory. |
| `PARSER_RELEASE_ARTIFACT_MANIFEST_PATH` | unset | Select an offline release manifest for build/startup verification; requires the matching expected-digest variable. Both unset is a no-op. |
| `PARSER_RELEASE_ARTIFACT_MANIFEST_SHA256` | unset | Externally pinned lowercase SHA-256 of the selected manifest; partial configuration or mismatch fails startup closed. |
| `PARSER_RELEASE_ARTIFACT_ROOT` | working directory | Candidate filesystem boundary for every manifest locator, including installed distributions; an artifact outside it fails closed. |
| `PARSER_RELEASE_ARTIFACT_PROFILE` | `production` | Select the authoritative production profile. `local_reference` is restricted to the checked-in Darwin developer evidence and must not be deployed. |
| `PARSER_LATENCY_PREWARM_ENABLED` | `false` | Under the reviewed Darwin/non-root capability supervisor, validate and initialize one owned PDF/image converter pair before readiness. Direct/plain/Docker launches fail closed when `true`; `false` is the complete lazy rollback. |
| `PARSER_LATENCY_PREWARM_ARTIFACTS_SHA256` | unset | Required lowercase SHA-256 identity of the configured local artifact tree when prewarming is enabled. Ignored while disabled. |
| `PARSER_LATENCY_PREWARM_DEPENDENCY_SHA256` | unset | Required lowercase SHA-256 identity of core installed-distribution RECORD files, Tesseract, and every configured language file when prewarming is enabled. Ignored while disabled. |
| `PARSER_LATENCY_PREWARM_TIMEOUT_SECONDS` | `300` | Enabled-only hard startup deadline, bounded from 1 to 900 seconds. Ignored while disabled. |
| `PARSER_LATENCY_PREWARM_SHUTDOWN_GRACE_SECONDS` | `2` | Enabled-only shutdown/watchdog grace, bounded from 0.1 to 30 seconds. Ignored while disabled. |
| `HF_HUB_OFFLINE` | unset | Must be truthy when prewarming is enabled so local model initialization cannot fall back to Hugging Face downloads. |
| `TRANSFORMERS_OFFLINE` | unset | Must be truthy when prewarming is enabled so Transformers remains local-only. |
| `PARSER_SHARED_IR_ENABLED` | `false` | Round-trip normalized items through the internal versioned evidence/relationship IR while retaining the unchanged public v1 projection. |
| `PARSER_SHARED_IR_NORMALIZATION_ENABLED` | `false` | With shared IR enabled, overlay the raw Docling reference graph so captions, children, footnotes, alternatives, annotations, source evidence, and original coordinate systems remain distinct. |
| `PARSER_CANONICAL_SERIALIZATION_ENABLED` | `false` | Add a strict versioned canonical Markdown/text presentation and make the Markdown serializer use its stored full-document view; requires both shared-IR flags. |
| `PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED` | `false` | Audit used PDF fonts and glyph runs for suspicious mapping collapse and retain reason-coded internal IR concerns without rewriting text; requires both shared-IR flags. |
| `PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED` | `false` | Recover only audited, indirect Type0/Identity-H glyph runs from bounded one-to-one embedded TrueType cmap and width evidence; requires font audit and both shared-IR flags. |
| `PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED` | `false` | Render and OCR only font runs that recovery explicitly refused, retaining bounded unselected evidence without changing canonical text; requires shared-IR normalization, font audit/recovery, and PDF visual analysis. |
| `PARSER_TEXT_RECONCILIATION_ENABLED` | `false` | Deterministically select one attributable native, safe-font, or complete high-confidence OCR representation while retaining alternatives and unresolved conflicts; requires shared IR, normalization, font audit/recovery, and selective span OCR. |
| `PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED` | `false` | Join uppercase OCR digest fragments only beside an explicit MD5/SHA/hash label with an exact standard length and at least one `A`–`F`; decimal runs and raw token evidence remain unchanged. |
| `PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED` | `false` | Add bounded, bbox-addressable OCR token occurrences and preserve distant repeated OCR lines. Requires numeric cleanup v2; rejected and short alternatives remain outside canonical prose. |
| `PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED` | `false` | Align layout and OCR text only to unique, bounded native PDF character evidence, including explicit semantic hyphens, overlapping combining marks, and safe Type 1 glyph names. Requires the complete Phase 2 evidence stack. |
| `PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED` | `false` | Project graph- and geometry-grounded external table captions as separate linked items immediately before their tables. Requires shared IR normalization; ambiguous, internal, empty, shared, or ungrounded captions remain evidence-only with concerns. |
| `PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED` | `false` | Project declared visual captions as separate side-aware items and expose validated internal children as bounded subordinate records. Requires shared IR normalization; graph/geometry conflicts remain evidence-only. |
| `PARSER_LAYOUT_SOURCE_NOTES_ENABLED` | `false` | Project source-visible notes, footnotes, and annotation-backed HTTP(S) links as distinct items after one unique nearby table or visual owner. Requires shared IR normalization; unsafe, ambiguous, distant, or ungrounded candidates remain evidence-only. |
| `PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED` | `false` | Project trusted relationship bundles and unambiguous finite page-space order, with bounded bbox-ownership validation. Requires shared IR normalization; malformed, ambiguous, cyclic, or over-limit pages retain predecessor order. |
| `PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED` | `false` | Preserve uniquely mapped native-PDF font/color runs and vector strike/underline evidence as additive source/redline/active projections. Requires shared IR normalization, canonical serialization, and relationship order; ambiguous or unsupported evidence fails closed. |
| `PARSER_LAYOUT_FORMS_ENABLED` | `false` | Add bounded source-visible form/control and aligned key-value semantic overlays. Requires shared IR, shared IR normalization, canonical serialization, and relationship order, but not text-run semantics; malformed or over-limit evidence fails closed. |
| `PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED` | `false` | Preserve source-grounded bullet, decimal, and lower-alpha hierarchy plus one bounded same-page table continuation. Requires shared IR, shared IR normalization, canonical serialization, and relationship order; malformed, ambiguous, form-owned, or over-limit candidates fail closed. |
| `PARSER_LAYOUT_RUNNING_REGIONS_ENABLED` | `false` | Separate source-grounded running headers, footers, bounded navigation, and printed page identity from the canonical Body view while retaining each once in Full. Requires shared IR, normalization, canonical serialization, and relationship order; malformed, ambiguous, invisible, unowned, or over-limit evidence fails closed. |
| `PARSER_VISUAL_STRUCTURE_SCHEMA_ENABLED` | `false` | Add the strict, typed chart/diagram `visual_structure` sidecar and conservative fallback routing. This is the Phase 05 schema foundation and has no Phase 05 prerequisite. |
| `PARSER_CHARTS_VECTOR_INVENTORY_ENABLED` | `false` | Inventory only chart-owned vector primitives, panels, transforms, and clips. Requires the visual-structure schema. |
| `PARSER_CHARTS_STRUCTURE_ENABLED` | `false` | Ground supported chart labels, linear axes, legends, panels, and series without values. Requires vector inventory. |
| `PARSER_CHARTS_VECTOR_VALUES_ENABLED` | `false` | Measure supported vertical linear vector bars with grounded category, series, axis, geometry, method, and tolerance. Requires chart structure. |
| `PARSER_CHARTS_STRUCTURED_OUTPUT_ENABLED` | `false` | Strictly validate candidate chart values and serialize authoritative chart-owned JSON/Markdown. Requires the visual schema, shared IR, normalization, and canonical serialization; it intentionally has no vector-only dependency. |
| `PARSER_CHARTS_RASTER_STRUCTURE_ENABLED` | `false` | Ground supported raster labels, linear axes, categories, units, legends, and swatches without values. Requires the visual schema and spatial OCR preservation; public authority also requires the raster umbrella. |
| `PARSER_CHARTS_RASTER_BAR_VALUES_ENABLED` | `false` | Measure supported 2-D vertical raster bars. Requires raster structure and structured chart output; public authority also requires the raster umbrella. |
| `PARSER_CHARTS_RASTER_LINE_VALUES_ENABLED` | `false` | Measure supported simple 2-D raster line marks. Requires raster structure and structured chart output; public authority also requires the raster umbrella. |
| `PARSER_CHARTS_RASTER_ANALYSIS_ENABLED` | `false` | Outer public admission and rollback boundary for raster chart analysis. Requires the visual schema, spatial OCR, raster structure, and structured output; optional bar and line branches can be enabled independently. |
| `PARSER_CHARTS_RASTER_MAX_CROP_WIDTH` | `2048` | Enabled-only maximum raster-analysis crop width in pixels (1–8192). |
| `PARSER_CHARTS_RASTER_MAX_CROP_HEIGHT` | `2048` | Enabled-only maximum raster-analysis crop height in pixels (1–8192). |
| `PARSER_CHARTS_RASTER_MAX_TOTAL_PIXELS` | `4000000` | Enabled-only maximum pixels admitted for one raster chart (1–16000000). |
| `PARSER_CHARTS_RASTER_MAX_WORK_UNITS` | `10000` | Enabled-only bounded-work budget for one raster chart (1–100000). |
| `PARSER_CHARTS_RASTER_TIMEOUT_SECONDS` | `2.0` | Enabled-only raster-analysis deadline in seconds (0.001–30). |
| `PARSER_CHARTS_RASTER_MINIMUM_QUALITY` | `0.6` | Enabled-only minimum finite raster quality score (0–1). |
| `PARSER_CHARTS_RASTER_COORDINATE_TOLERANCE` | `0.5` | Enabled-only direct-image/PDF-render normalization tolerance (0–10). |
| `PARSER_DIAGRAMS_TOPOLOGY_ENABLED` | `false` | Recover only supported, explicitly directed diagram nodes/connectors. Requires the visual schema and spatial OCR preservation; it is independent of chart/vector/raster branches. |

Changing OCR languages also requires the corresponding Tesseract language
packages to be installed.

All Phase 05 controls default to `false`. Disabling the visual schema removes
the additive sidecar and restores the exact predecessor path. Each inner
vector or raster switch removes only its own later-stage authority. For raster
charts, `PARSER_CHARTS_RASTER_ANALYSIS_ENABLED=false` is the single public
rollback: it bypasses source-pixel analysis and restores the P05-US05 result
even when an inner raster component flag is true. Raster limit values are
ignored while that umbrella is disabled. Disabling diagram topology restores
the P05-US01 diagram fallback.

Visual OCR has two representations by design. Cleaned, accepted text is used
for primary items and Markdown; every raw candidate, confidence, bounding box,
acceptance decision, and overlap rejection remains available under
`detected_images`. Uploaded pages and full-page scanned PDF rasters have
`region_role: "page_source"`, whereas photographs, screenshots, charts,
diagrams, and other embedded visuals have `region_role: "content_region"`.
The `IMAGE_*` configuration names are retained for backward compatibility,
but those quality thresholds now apply to the shared visual pipeline.

The shared IR is an internal, versioned graph of pages, regions, elements,
evidence, bounding boxes, coordinate systems, confidence, and relationships.
It records native, OCR, vector, embedded, recovered, model, and derived
evidence separately and rejects dangling ownership, cross-page references,
invalid transforms, and forbidden relationship cycles. The feature is
default-off. When `PARSER_SHARED_IR_ENABLED=true`, the parser validates and
immediately projects the graph back to the same public `1.0` response; it does
not expose internal records or change endpoint behavior. Disable the flag to
return directly to the legacy item path.

`PARSER_SHARED_IR_NORMALIZATION_ENABLED=true` additionally requires
`PARSER_SHARED_IR_ENABLED=true`. It traverses Docling collection plus
body/furniture root references, binds each `self_ref` to one element, retains
typed ownership and per-node provenance, and records malformed, duplicate,
dangling, cyclic, shared, ambiguous-page, or cross-page references as internal
concerns. The public v1 projection remains unchanged, and disabling the
normalization flag returns to the compatibility-only IR adapter.

`PARSER_CANONICAL_SERIALIZATION_ENABLED=true` requires both shared-IR flags.
It adds a top-level `canonical_presentation` contract with its own `1.0`
schema version, stable per-primary-element blocks, explicit contribution and
relationship IDs, audited omissions, and ordered `full`, `body`, `header`,
and `footer` Markdown/text views at page and document scope. The existing
`pages` and legacy item fields are unchanged. Captions, subordinate OCR,
tables, visuals, headers, and footers follow one identity-based policy, so
equal text at distinct locations is not globally deduplicated. The Markdown
serializer validates and returns the stored canonical full view; a present but
malformed canonical object is an error rather than a silent legacy fallback.
Disable only this flag to remove the additive object and restore legacy
Markdown serialization.

`PARSER_TEXT_INTEGRITY_FONT_AUDIT_ENABLED=true` requires shared-IR
normalization. For PDFs, it inspects used font dictionaries, mappings,
CID-to-GID declarations, embedded-program availability, character advances,
and affected run geometry once per font object. Suspicious mappings become
bounded, reason-coded internal IR concerns. Font programs are never executed,
persisted, logged, or returned, and this detection-only stage does not rewrite
native text. Disable the flag to bypass the audit and retain the prior path.

`PARSER_TEXT_INTEGRITY_FONT_RECOVERY_ENABLED=true` additionally requires the
font audit. It reparses only suspicious indirect Type0/Identity-H fonts,
accepts only identity CID-to-GID mappings and one-to-one used-glyph Unicode
evidence, cross-checks PDF widths against bounded embedded TrueType `hmtx`
metrics, and retains original/recovered glyph alternatives with top-left PDF
geometry. Unsupported, ambiguous, ligature, missing-program, or width-mismatch
fonts remain reason-coded unresolved concerns. Font bytes are never executed,
returned, logged, or persisted. Disable only the recovery flag to retain audit
concerns while restoring the original native text.

`PARSER_TEXT_INTEGRITY_SELECTIVE_SPAN_OCR_ENABLED=true` additionally requires
font recovery and `PDF_VISUAL_ANALYSIS_ENABLED=true`. It routes only explicitly
refused audit runs through the shared local Tesseract renderer, with fixed
crop, area, pixel, count, and deadline bounds. Crop geometry, transforms,
tokens, confidence, OCR pass, and cost remain attributable unselected
alternatives; native values, Markdown, reading order, and canonical
presentation remain unchanged while text reconciliation is disabled.
Disable only this flag to remove the extra render work and diagnostics.

`PARSER_TEXT_RECONCILIATION_ENABLED=true` additionally requires the complete
shared-IR, font-audit, font-recovery, and selective-span-OCR evidence pipeline.
It reconciles only source-bound candidates with safe lineage, reciprocal
geometry, Unicode/script, completeness, confidence, and fixed-margin evidence.
The selected value is always byte-for-byte one retained candidate; the parser
does not perform language completion or confusable substitution. Low-margin,
partial-overlap, mixed-script, incomplete, or contradictory cases remain
unchanged with attributable alternatives and a reason-coded concern. Disable
only this flag to restore the P02-US03 projection while retaining audit,
recovery, and selective-OCR evidence.

`PARSER_OCR_NUMERIC_CLEANUP_V2_ENABLED=true` replaces only the permissive
split-hex line cleanup. It joins a maximal uppercase ASCII digest run only when
an immediately adjacent MD5, SHA, hash, checksum, digest, or fingerprint label
declares its exact standard length and the value contains at least one
hexadecimal letter. Pure years and decimal lists are never joined, even after a
hash label. Dates, money, percentages, page numbers, raw OCR tokens, bboxes,
confidence, and word counts remain unchanged. The same bounded policy applies
to embedded PDF images, rendered regions, direct rasters, selective span OCR,
and both standard and sparse passes. Disable the flag to restore the exact
legacy cleanup and call shape.

`PARSER_OCR_SPATIAL_TOKEN_PRESERVATION_ENABLED=true` requires numeric cleanup
v2 and adds `ocr_token_occurrences` plus a bounded
`ocr_occurrence_summary` to OCR-backed items. Exact token text, bbox,
confidence, pass, and stable SHA-256 occurrence identity remain addressable;
only exact NFC/whitespace-equivalent tokens with at least 80% reciprocal bbox
overlap share a selected representative. Distant equal labels remain distinct.
Low-confidence one-to-three-character alternatives are flagged only inside a
chart or diagram and never enter canonical prose solely because this flag is
enabled. Disable the flag to remove the additive fields and restore the exact
US05 projection and adapter call shapes.

`PARSER_TEXT_INTEGRITY_SOURCE_ALIGNMENT_ENABLED=true` requires text
reconciliation, numeric cleanup v2, and spatial-token preservation. It may
replace a layout or OCR span only when bounded PDF character evidence supplies
a unique page-local match with compatible geometry. Explicit PDFium hyphen
metadata, overlapping spacing-diacritic geometry, and an allowlisted Type 1
glyph name can contribute source text; unsafe, ambiguous, oversized, or
unmapped evidence fails closed. Every selected replacement retains its source
span and reason code. Disable this single flag to restore the exact P02-US06
pipeline behavior.

`PARSER_LAYOUT_TABLE_CAPTIONS_ENABLED=true` requires shared IR and raw-graph
normalization. A declared caption is projected only when its own source box is
external, horizontally aligned, and near the referenced table. The caption
retains its top-left page bbox, source, confidence, and `caption_of`
relationship; table rows and cells are unchanged. Duplicate graph routes
project once, while multiple distinct captions remain separate with a concern.
Internal, empty, distant, dangling, or shared captions fail closed. Disable
this single flag to remove the additive caption items and restore the exact
completed Phase 02 JSON and Markdown projection.
When a table caption also has raw graph evidence, that raw node must pass the
same bounded provenance gate as a visual caption; inherited legacy evidence
cannot upgrade generated, model-derived, malformed, or unscannable raw input.

`PARSER_LAYOUT_VISUAL_RELATIONSHIPS_ENABLED=true` also requires shared IR and
raw-graph normalization. It separates declared visual captions from internal
children, preserves the visual bbox, and keeps natural-image child OCR
subordinate. Only source-visible raw native, OCR, vector, embedded, or recovered
evidence is eligible; derived, generated, model-marked, ambiguous, or
ungrounded nodes remain evidence-only with bounded concerns. Processed owners carry
`layout_visual_relationships_projected=true`, which scopes frontend suppression
to this projection. Primary visual OCR additionally requires an explicit
promotion flag and accepted same-unit diagnostic bboxes fully inside the owner.
The only derived-method exception is child-only, bbox-grounded
punctuation/symbol text matched to trusted retained source evidence;
inherited-only text and inferred punctuation captions remain ineligible.
Disable the flag for exact legacy flattening and legacy frontend precedence.

`PARSER_LAYOUT_SOURCE_NOTES_ENABLED=true` requires shared IR and raw-graph
normalization. Declared footnotes and source notes must agree with same-page,
same-unit geometry below their owner. Geometry-only `Source:`, `Data:`,
`Note:`, and `StatLink` candidates require one unique nearby table or visual;
ordinary prose, furniture, shared candidates, and generated/model-derived
content fail closed. Missing visual notes may use a narrow, owner-external OCR
strip without expanding the owner crop. PDF links are admitted only from
bounded, visible or annotation-backed HTTP(S) evidence; unsafe targets are
omitted from sanitized diagnostics. Accepted notes retain their own bbox,
source, confidence, stable ID, typed owner relationship, and exact backlink,
and serialize once after the owner and any below-owner caption. Disable this
single flag to restore the exact predecessor JSON and Markdown projection.

`PARSER_LAYOUT_RELATIONSHIP_ORDER_ENABLED=true` runs after the accepted table
caption, visual relationship, and source-note projections. It keeps each
trusted owner/caption/note bundle atomic, uses only finite same-page geometry
and explicit source-grounded order relationships, and rewrites public item
arrays plus contiguous `reading_order` and canonical presentation order.
Bounded source evidence may exclude a contribution independently proven
outside its unchanged owner bbox or reorder contained header fragments; raw
evidence remains retained. Invalid geometry, ownership conflicts, cycles,
duplicates, and resource-limit overflow fail closed for the affected page
with content-free diagnostics. Disable this single flag to restore the exact
P03-US03 predecessor projection.

`PARSER_LAYOUT_TEXT_RUN_SEMANTICS_ENABLED=true` runs after relationship order.
It keeps the complete source-visible scalar authoritative while adding sparse
typed run/rule evidence, redline Markdown, and an explicit derived active-text
view that omits only source-proven deletions. Native PDF geometry must map to
one exact scalar, table cell, or nested item; ambiguous, transformed, raster,
or over-limit evidence fails closed without fabricating a change state.
Disabling this single flag restores the exact P03-US04 projection and skips
the text-run source extractor.

`PARSER_LAYOUT_FORMS_ENABLED=true` runs after relationship order and, when
enabled alongside text-run semantics, after that projection. It adds strict
typed form groups, fields, labels, value regions, controls, and aligned
key-value pairs without filling blank fields or replacing the retained ACORD
coverage table. Component key-value replacement is allowlisted and atomic;
all other form semantics remain canonical-inert. Disabling this single flag
restores the exact configured predecessor and performs no form extraction or
projection work.

`PARSER_LAYOUT_OUTLINE_STRUCTURE_ENABLED=true` runs after form semantics when
both flags are enabled. It adds strict anchor-only outline sidecars, typed IR
nodes and relationships, and one safe canonical list replacement while
leaving predecessor item values, nested legacy markers/levels, tables, and
physical reading order unchanged. V1 recognizes only source-bounded bullet,
decimal, and lower-alpha markers and may carry one same-page table as a
continuation of the preceding item. Inline enumerations, broken sequences,
cross-page edges, form-owned contributors, and malformed or excessive graphs
retain the configured predecessor. Disabling this single flag performs no
outline extraction or projection work and restores that predecessor exactly.

`PARSER_LAYOUT_RUNNING_REGIONS_ENABLED=true` runs after the other Phase 03
layout projections. It preserves physical page indexes and legacy labels while
adding independently validated embedded, detected printed, display, and source
identity fields. Accepted running headers, footers, and bounded navigation are
retained with exact public/IR/canonical ownership, excluded from canonical Body,
and included once in Full; page navigation remains physical. Source extraction
and projection are local-only, bounded, and authorized against the exact PDF
bytes and configured predecessor. Disabling this single flag performs no US08
import, extraction, traversal, or serialization work and returns the configured
predecessor unchanged.

Semantic captioning for either input type never calls a remote service. When
`IMAGE_CAPTIONING_ENABLED=true`, the service uses a complete local
`HuggingFaceTB--SmolVLM-256M-Instruct` snapshot beneath
`DOCLING_ARTIFACTS_PATH` (or an already complete Hugging Face cache snapshot).
If it is absent, parsing continues without a caption and returns a warning.
Generated descriptions are marked with
`model_generated_visual_description`, their creator is retained in
`caption_source`, and they must not be treated as source OCR or factual
ground truth.

To populate the optional models in the configured directory:

```bash
.venv/bin/docling-tools models download \
  smolvlm \
  --output-dir .models/docling
```

The picture classifier is about visual category routing (for example,
photograph versus chart); it does not generate semantic descriptions. Keep
`IMAGE_CAPTIONING_ENABLED=false` when the extra VLM latency and memory are not
acceptable.

## Errors and limits

Errors use a stable envelope:

```json
{
  "error": {
    "code": "unsupported_document_type",
    "message": "Only PDF, PNG, JPEG, TIFF, and WebP documents are supported.",
    "details": {}
  }
}
```

Expected statuses are:

- `413` for upload-size, page/frame-count, or decoded-image-pixel limits.
- `415` for an unsupported extension or a declared MIME type that does not
  match the supported extension.
- `422` for an empty, malformed, corrupted, signature-mismatched, or
  decoded-format-mismatched request.
- `500` for an unexpected extraction failure.
- `503` when a required local engine is unavailable.
- `504` when document processing times out.

The endpoint currently buffers each accepted document in memory after bounded
streaming validation. Images are additionally decoded for signature, format,
dimensions, EXIF orientation, and frame validation before extraction. Keep
`MAX_UPLOAD_BYTES` aligned with the reverse proxy's body limit and request
timeout, and size `MAX_IMAGE_PIXELS` and `MAX_IMAGE_TOTAL_PIXELS` for the memory
available to each worker.

## Tests

Run the test suite from the repository root:

```bash
pytest
```

The full Docling sample test is opt-in because it loads the model:

```bash
RUN_INTEGRATION=1 pytest \
  tests/test_sample_integration.py::test_full_sample_pipeline_matches_reference_invariants
```

It checks the supplied PDF sample's physical/printed page mapping, five tables,
three signature OCR results, and later-page body content. The regular suite
also covers both API response formats, validation/error envelopes, table
geometry, OCR image count, deterministic Markdown serialization, supported
image formats, EXIF rotation, multi-frame TIFF pagination, and image limits.

The real raster suite is also opt-in because it loads the layout, table, OCR,
and picture-classification models:

```bash
RUN_IMAGE_INTEGRATION=1 pytest tests/test_image_integration.py
```

It exercises a text/form/table scan, a bar chart, a flow diagram, and a
two-frame TIFF through the public parsing pipeline. To run every PDF and image
integration regression together:

```bash
RUN_INTEGRATION=1 RUN_IMAGE_INTEGRATION=1 pytest
```

## Docker

The image installs CPU-only PyTorch wheels, Tesseract English data, and the
Docling layout, table, and picture-classifier models during the build:

```bash
docker build -t document-parse-api .
docker run --rm -p 8000:8000 document-parse-api
```

The build then creates and verifies the production release manifest described
above. The runtime starts through the digest-restoring release entry point and
reverifies that same candidate inventory before one Uvicorn worker is imported.
Directly bypassing the entry point leaves a partial manifest selection and
fails application startup closed.

The Docling converter is heavyweight,
cached once per process, and protected during conversion; adding Uvicorn
workers duplicates model memory. Scale horizontally with one worker per
container after measuring memory, CPU, and representative document latency.
The shipped image retains lazy converter construction and must keep
`PARSER_LATENCY_PREWARM_ENABLED=false`. The current enabled broker topology is
deliberately Darwin/non-root-only; this root Linux container has no approved
kernel fork-denial equivalent and therefore fails closed if that flag is set
to `true`.
