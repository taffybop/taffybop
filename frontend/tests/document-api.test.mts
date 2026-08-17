import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  DEFAULT_PARSE_MAX_UPLOAD_BYTES,
  DocumentApiError,
  getBrowserPreviewKind,
  getConfiguredMaxUploadBytes,
  getDocumentInputKind,
  parseJson,
  stripSupportedDocumentExtension,
  validateDocumentFile,
} from "../lib/document-api.ts";
import {
  sampleCanonicalPresentation,
  samplePage,
  sampleResult,
} from "./fixtures.mts";

const originalFetch = globalThis.fetch;
const originalMaxUploadBytes =
  process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES;

afterEach(() => {
  globalThis.fetch = originalFetch;
  if (originalMaxUploadBytes === undefined) {
    delete process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES;
  } else {
    process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES = originalMaxUploadBytes;
  }
});

const pdf = (name = "document.pdf", type = "application/pdf") =>
  new File(["%PDF-1.7"], name, { type });

const image = (
  name = "scan.png",
  type = "image/png",
  contents = "image-bytes",
) => new File([contents], name, { type });

test("upload preflight defaults to 20 MiB and honors its environment override", () => {
  delete process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES;

  assert.equal(DEFAULT_PARSE_MAX_UPLOAD_BYTES, 20 * 1024 * 1024);
  assert.equal(getConfiguredMaxUploadBytes(), DEFAULT_PARSE_MAX_UPLOAD_BYTES);

  process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES = "12345";
  assert.equal(getConfiguredMaxUploadBytes(), 12_345);

  process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES = "invalid";
  assert.equal(getConfiguredMaxUploadBytes(), DEFAULT_PARSE_MAX_UPLOAD_BYTES);
});

test("upload preflight accepts exactly 20 MiB and rejects one byte more", () => {
  const boundaryBytes = new Uint8Array(DEFAULT_PARSE_MAX_UPLOAD_BYTES);
  const atLimit = new File([boundaryBytes], "boundary.pdf", {
    type: "application/pdf",
  });
  const aboveLimit = new File([boundaryBytes, new Uint8Array(1)], "large.pdf", {
    type: "application/pdf",
  });

  assert.doesNotThrow(() => validateDocumentFile(atLimit));
  assert.throws(
    () => validateDocumentFile(aboveLimit),
    (error: unknown) => {
      assert.ok(error instanceof DocumentApiError);
      assert.equal(error.code, "upload_too_large");
      assert.deepEqual(error.details, {
        max_bytes: DEFAULT_PARSE_MAX_UPLOAD_BYTES,
        received_bytes: DEFAULT_PARSE_MAX_UPLOAD_BYTES + 1,
      });
      return true;
    },
  );
});

test("document validation accepts every supported extension and MIME pair", () => {
  const supported = [
    pdf(),
    pdf("legacy.PDF", "application/octet-stream"),
    pdf("untyped.pdf", ""),
    image("scan.png", "image/png"),
    image("photo.jpg", "image/jpeg"),
    image("photo.JPEG", "image/pjpeg"),
    image("fax.tif", "image/tiff"),
    image("fax.TIFF", "image/x-tiff"),
    image("diagram.webp", "image/webp"),
  ];

  for (const file of supported) {
    assert.doesNotThrow(() => validateDocumentFile(file));
  }
});

test("document validation rejects unsupported extensions and MIME mismatches", () => {
  assert.throws(
    () => validateDocumentFile(pdf("notes.txt", "text/plain")),
    /supported formats/i,
  );
  assert.throws(
    () => validateDocumentFile(pdf("notes.pdf", "text/plain")),
    /does not match/i,
  );
  assert.throws(
    () => validateDocumentFile(image("scan.png", "image/jpeg")),
    /does not match/i,
  );
  assert.throws(
    () => validateDocumentFile(image("scan.webp", "")),
    /does not match/i,
  );
});

test("document validation rejects empty and oversized images", () => {
  assert.throws(
    () => validateDocumentFile(new File([], "empty.png", { type: "image/png" })),
    (error: unknown) => {
      assert.ok(error instanceof DocumentApiError);
      assert.equal(error.code, "invalid_image");
      return true;
    },
  );

  assert.throws(
    () => validateDocumentFile(image("large.png", "image/png", "12345"), 4),
    (error: unknown) => {
      assert.ok(error instanceof DocumentApiError);
      assert.equal(error.code, "upload_too_large");
      return true;
    },
  );
});

test("document helpers select the correct preview and output basename", () => {
  assert.equal(getDocumentInputKind("source.pdf"), "pdf");
  assert.equal(getDocumentInputKind("scan.PNG"), "image");
  assert.equal(getBrowserPreviewKind("source.pdf"), "pdf");
  assert.equal(getBrowserPreviewKind("photo.jpeg"), "raster");
  assert.equal(getBrowserPreviewKind("multipage.tiff"), "tiff");
  assert.equal(getBrowserPreviewKind("animation.gif"), null);
  assert.equal(stripSupportedDocumentExtension("scan.tiff"), "scan");
  assert.equal(stripSupportedDocumentExtension("archive.tar"), "archive.tar");
});

test("JSON parsing posts the original PDF to a normalized direct endpoint", async () => {
  let requestUrl = "";
  let requestInit: RequestInit | undefined;
  globalThis.fetch = async (input, init) => {
    requestUrl = String(input);
    requestInit = init;
    return new Response(JSON.stringify(sampleResult()), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  const result = await parseJson(pdf(), {
    apiBaseUrl: "https://parser.example/",
  });

  assert.equal(result.schema_version, "1.0");
  assert.equal(
    requestUrl,
    "https://parser.example/v1/parse?output_format=json",
  );
  assert.equal(requestInit?.method, "POST");
  assert.deepEqual(requestInit?.headers, { accept: "application/json" });
  assert.ok(requestInit?.body instanceof FormData);
  assert.equal((requestInit.body as FormData).get("file") instanceof File, true);
});

test("JSON parsing posts an image through the unchanged API contract", async () => {
  const uploadedFiles: File[] = [];
  globalThis.fetch = async (_input, init) => {
    const body = init?.body;
    assert.ok(body instanceof FormData);
    uploadedFiles.push(body.get("file") as File);
    return new Response(JSON.stringify(sampleResult()), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };

  await parseJson(image("evidence.WEBP", "image/webp", "webp-payload"));

  const uploaded = uploadedFiles[0];
  assert.ok(uploaded instanceof File);
  assert.equal(uploaded.name, "evidence.WEBP");
  assert.equal(uploaded.type, "image/webp");
  assert.equal(await uploaded.text(), "webp-payload");
});

test("JSON parsing preserves API page matching and index fields", async () => {
  const response = sampleResult({
    document: {
      filename: "indexed.pdf",
      mime_type: "application/pdf",
      sha256: "indexed",
      page_count: 2,
    },
    pages: [
      samplePage({
        page_index: 0,
        page_number: 1,
        page_label: "cover",
        items: [
          { id: "cover", type: "text", reading_order: 1, md: "Cover" },
        ],
      }),
      samplePage({
        page_index: 1,
        page_number: 2,
        page_label: "1",
        items: [
          { id: "body", type: "text", reading_order: 1, md: "Body" },
        ],
      }),
    ],
  });

  globalThis.fetch = async () =>
    new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  const parsed = await parseJson(pdf());

  assert.equal(parsed.document.page_count, 2);
  assert.deepEqual(
    parsed.pages.map(({ page_index, page_number, page_label }) => ({
      page_index,
      page_number,
      page_label,
    })),
    [
      { page_index: 0, page_number: 1, page_label: "cover" },
      { page_index: 1, page_number: 2, page_label: "1" },
    ],
  );
});

test("JSON parsing validates and preserves a present canonical contract", async () => {
  const canonical = sampleCanonicalPresentation();
  const response = sampleResult({ canonical_presentation: canonical });
  globalThis.fetch = async () =>
    new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  const parsed = await parseJson(pdf());

  assert.deepEqual(parsed.canonical_presentation, canonical);
});

test("JSON parsing fails closed on a malformed present canonical contract", async () => {
  const canonical = {
    ...sampleCanonicalPresentation(),
    policy_id: "unsupported-policy",
  };
  const response = sampleResult({
    canonical_presentation:
      canonical as unknown as ReturnType<
        typeof sampleCanonicalPresentation
      >,
  });
  globalThis.fetch = async () =>
    new Response(JSON.stringify(response), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

  await assert.rejects(
    () => parseJson(pdf()),
    (error: unknown) => {
      assert.ok(error instanceof DocumentApiError);
      assert.equal(error.kind, "server");
      assert.equal(error.code, "invalid_canonical_presentation");
      assert.equal(error.status, 200);
      return true;
    },
  );
});

test("structured HTTP 504 responses become typed timeout errors", async () => {
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        error: {
          code: "document_processing_timeout",
          message: "Try later",
        },
      }),
      { status: 504, headers: { "content-type": "application/json" } },
    );

  await assert.rejects(
    () => parseJson(pdf()),
    (error: unknown) => {
      assert.ok(error instanceof DocumentApiError);
      assert.equal(error.kind, "timeout");
      assert.equal(error.code, "document_processing_timeout");
      assert.equal(error.status, 504);
      return true;
    },
  );
});
