import type {
  ApiErrorResponse,
  DocumentApiErrorKind,
  ParseOutputFormat,
  ParseResponseFor,
  ParseResult,
} from "@/lib/types";
import { readCanonicalPresentation } from "./canonical-presentation.ts";

export const DEFAULT_PARSE_TIMEOUT_MS = 330_000;
export const DEFAULT_PARSE_MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
export const PARSE_PROXY_ENDPOINT = "/api/parse";
export const SUPPORTED_DOCUMENT_ACCEPT = [
  ".pdf",
  ".png",
  ".jpg",
  ".jpeg",
  ".tif",
  ".tiff",
  ".webp",
  "application/pdf",
  "image/png",
  "image/jpeg",
  "image/tiff",
  "image/webp",
].join(",");
const PARSE_PATH = "/v1/parse";

export type DocumentInputKind = "pdf" | "image";
export type BrowserPreviewKind = "pdf" | "raster" | "tiff";

interface SupportedDocumentType {
  kind: DocumentInputKind;
  preview: BrowserPreviewKind;
  mediaTypes: ReadonlySet<string>;
}

const PDF_MEDIA_TYPES = new Set([
  "",
  "application/pdf",
  "application/x-pdf",
  "application/octet-stream",
  "binary/octet-stream",
]);

const JPEG_MEDIA_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/pjpeg",
]);

const TIFF_MEDIA_TYPES = new Set(["image/tiff", "image/x-tiff"]);

const SUPPORTED_DOCUMENT_TYPES: Readonly<
  Record<string, SupportedDocumentType>
> = {
  ".pdf": {
    kind: "pdf",
    preview: "pdf",
    mediaTypes: PDF_MEDIA_TYPES,
  },
  ".png": {
    kind: "image",
    preview: "raster",
    mediaTypes: new Set(["image/png"]),
  },
  ".jpg": {
    kind: "image",
    preview: "raster",
    mediaTypes: JPEG_MEDIA_TYPES,
  },
  ".jpeg": {
    kind: "image",
    preview: "raster",
    mediaTypes: JPEG_MEDIA_TYPES,
  },
  ".tif": {
    kind: "image",
    preview: "tiff",
    mediaTypes: TIFF_MEDIA_TYPES,
  },
  ".tiff": {
    kind: "image",
    preview: "tiff",
    mediaTypes: TIFF_MEDIA_TYPES,
  },
  ".webp": {
    kind: "image",
    preview: "raster",
    mediaTypes: new Set(["image/webp"]),
  },
};

export const SUPPORTED_DOCUMENT_FORMATS =
  "PDF, PNG, JPEG, TIFF, and WebP";

export interface ParseRequestOptions {
  /**
   * Overrides the configured API base. Pass an origin/base URL or the complete
   * `/v1/parse` endpoint. Omit it to use NEXT_PUBLIC_PARSE_API_URL, then the
   * same-origin `/api/parse` proxy as a fallback.
   */
  apiBaseUrl?: string;
  timeoutMs?: number;
  maxUploadBytes?: number;
  signal?: AbortSignal;
}

export type DocumentApiClientOptions = Omit<ParseRequestOptions, "signal">;

export interface ParseBundle {
  /** Starts immediately so JSON can render as soon as it is available. */
  json: Promise<ParseResult>;
  /**
   * Starts an independent, memoized Markdown request on first use. A Markdown
   * failure never changes the state of the JSON promise.
   */
  markdown: () => Promise<string>;
}

export interface DocumentApiClient {
  parseJson(file: File, options?: ParseRequestOptions): Promise<ParseResult>;
  parseMarkdown(file: File, options?: ParseRequestOptions): Promise<string>;
  createParseBundle(file: File, options?: ParseRequestOptions): ParseBundle;
}

export class DocumentApiError extends Error {
  readonly kind: DocumentApiErrorKind;
  readonly code: string;
  readonly status: number | null;
  readonly details: Record<string, unknown>;

  constructor(
    kind: DocumentApiErrorKind,
    code: string,
    message: string,
    options: {
      status?: number | null;
      details?: Record<string, unknown>;
      cause?: unknown;
    } = {},
  ) {
    super(message, { cause: options.cause });
    this.name = "DocumentApiError";
    this.kind = kind;
    this.code = code;
    this.status = options.status ?? null;
    this.details = options.details ?? {};
  }
}

function readPositiveNumber(value: string | undefined, fallback: number): number {
  if (!value?.trim()) return fallback;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function configuredDirectApiUrl(): string {
  return process.env.NEXT_PUBLIC_PARSE_API_URL?.trim() ?? "";
}

function configuredTimeoutMs(): number {
  return readPositiveNumber(
    process.env.NEXT_PUBLIC_PARSE_API_TIMEOUT_MS,
    DEFAULT_PARSE_TIMEOUT_MS,
  );
}

export function getConfiguredMaxUploadBytes(): number {
  return readPositiveNumber(
    process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES,
    DEFAULT_PARSE_MAX_UPLOAD_BYTES,
  );
}

function parseEndpoint(apiBaseUrl?: string): string {
  const configured = apiBaseUrl?.trim() || configuredDirectApiUrl();
  if (!configured) return PARSE_PROXY_ENDPOINT;

  const withoutTrailingSlash = configured.replace(/\/+$/, "");
  return withoutTrailingSlash.endsWith(PARSE_PATH)
    ? withoutTrailingSlash
    : `${withoutTrailingSlash}${PARSE_PATH}`;
}

function appendOutputFormat(
  endpoint: string,
  outputFormat: ParseOutputFormat,
): string {
  const separator = endpoint.includes("?") ? "&" : "?";
  return `${endpoint}${separator}output_format=${encodeURIComponent(outputFormat)}`;
}

export function getParseApiLabel(apiBaseUrl?: string): string {
  const configured = apiBaseUrl?.trim() || configuredDirectApiUrl();
  if (!configured) return "Same-origin API proxy";

  try {
    const url = new URL(configured, "http://frontend.local");
    return url.origin === "http://frontend.local"
      ? configured
      : url.host;
  } catch {
    return configured;
  }
}

function fileExtension(filename: string): string {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

export function getDocumentInputKind(
  fileOrName: File | string,
): DocumentInputKind | null {
  const filename =
    typeof fileOrName === "string" ? fileOrName : fileOrName.name;
  return SUPPORTED_DOCUMENT_TYPES[fileExtension(filename)]?.kind ?? null;
}

export function getBrowserPreviewKind(
  fileOrName: File | string,
): BrowserPreviewKind | null {
  const filename =
    typeof fileOrName === "string" ? fileOrName : fileOrName.name;
  return SUPPORTED_DOCUMENT_TYPES[fileExtension(filename)]?.preview ?? null;
}

export function stripSupportedDocumentExtension(filename: string): string {
  const extension = fileExtension(filename);
  return extension in SUPPORTED_DOCUMENT_TYPES
    ? filename.slice(0, -extension.length)
    : filename;
}

export function validateDocumentFile(
  file: File,
  maxUploadBytes = getConfiguredMaxUploadBytes(),
): void {
  if (!Number.isFinite(maxUploadBytes) || maxUploadBytes <= 0) {
    throw new DocumentApiError(
      "configuration",
      "invalid_upload_limit",
      "The document upload limit must be greater than zero.",
    );
  }

  if (!(file instanceof File)) {
    throw new DocumentApiError(
      "validation",
      "file_required",
      "Choose a document to parse.",
    );
  }

  const extension = fileExtension(file.name);
  const documentType = SUPPORTED_DOCUMENT_TYPES[extension];
  if (!documentType) {
    throw new DocumentApiError(
      "validation",
      "unsupported_document_type",
      `Supported formats are ${SUPPORTED_DOCUMENT_FORMATS}.`,
      {
        details: {
          filename: file.name,
          supported_extensions: Object.keys(SUPPORTED_DOCUMENT_TYPES),
        },
      },
    );
  }

  const mediaType = file.type.split(";", 1)[0].trim().toLowerCase();
  if (!documentType.mediaTypes.has(mediaType)) {
    throw new DocumentApiError(
      "validation",
      "unsupported_document_type",
      `The file type does not match its ${extension} extension.`,
      {
        details: {
          filename: file.name,
          content_type: mediaType || null,
          supported_content_types: [...documentType.mediaTypes].filter(Boolean),
        },
      },
    );
  }

  if (file.size === 0) {
    throw new DocumentApiError(
      "validation",
      documentType.kind === "pdf" ? "invalid_pdf" : "invalid_image",
      "The selected document is empty.",
      { details: { size_bytes: 0 } },
    );
  }

  if (file.size > maxUploadBytes) {
    throw new DocumentApiError(
      "validation",
      "upload_too_large",
      "The selected document exceeds the upload size limit.",
      {
        details: {
          max_bytes: maxUploadBytes,
          received_bytes: file.size,
        },
      },
    );
  }
}

/**
 * Compatibility alias for existing imports. Validation now accepts every
 * document format supported by the parser.
 */
export const validatePdfFile = validateDocumentFile;

function isApiErrorResponse(value: unknown): value is ApiErrorResponse {
  if (!value || typeof value !== "object") return false;
  const error = (value as { error?: unknown }).error;
  if (!error || typeof error !== "object") return false;
  const candidate = error as { code?: unknown; message?: unknown };
  return (
    typeof candidate.code === "string" &&
    typeof candidate.message === "string"
  );
}

function isParseResult(value: unknown): value is ParseResult {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<ParseResult>;
  return (
    typeof candidate.schema_version === "string" &&
    !!candidate.document &&
    typeof candidate.document === "object" &&
    Array.isArray(candidate.pages) &&
    !!candidate.processing &&
    typeof candidate.processing === "object"
  );
}

function errorKindForStatus(
  status: number,
  code?: string,
): DocumentApiErrorKind {
  if (status === 408 || status === 504 || code?.includes("timeout")) {
    return "timeout";
  }
  return status >= 400 && status < 500 ? "validation" : "server";
}

async function errorFromResponse(response: Response): Promise<DocumentApiError> {
  let payload: unknown;
  let rawBody = "";

  try {
    rawBody = await response.text();
    payload = rawBody ? JSON.parse(rawBody) : undefined;
  } catch {
    payload = undefined;
  }

  if (isApiErrorResponse(payload)) {
    return new DocumentApiError(
      errorKindForStatus(response.status, payload.error.code),
      payload.error.code,
      payload.error.message,
      {
        status: response.status,
        details: payload.error.details ?? {},
      },
    );
  }

  return new DocumentApiError(
    errorKindForStatus(response.status),
    `http_${response.status}`,
    response.status >= 500
      ? "The parsing service could not process the document."
      : "The document request was rejected.",
    {
      status: response.status,
      details: {
        content_type: response.headers.get("content-type") ?? "unknown",
      },
    },
  );
}

function linkedAbortController(
  callerSignal: AbortSignal | undefined,
  timeoutMs: number,
): {
  controller: AbortController;
  didTimeout: () => boolean;
  dispose: () => void;
} {
  const controller = new AbortController();
  let timedOut = false;

  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) {
    abortFromCaller();
  } else {
    callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Request timed out.", "TimeoutError"));
  }, timeoutMs);

  return {
    controller,
    didTimeout: () => timedOut,
    dispose: () => {
      clearTimeout(timeout);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    },
  };
}

async function requestParse<Format extends ParseOutputFormat>(
  file: File,
  outputFormat: Format,
  options: ParseRequestOptions = {},
): Promise<ParseResponseFor<Format>> {
  const timeoutMs = options.timeoutMs ?? configuredTimeoutMs();
  const maxUploadBytes =
    options.maxUploadBytes ?? getConfiguredMaxUploadBytes();

  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
    throw new DocumentApiError(
      "configuration",
      "invalid_timeout",
      "The document API timeout must be greater than zero.",
    );
  }
  if (!Number.isFinite(maxUploadBytes) || maxUploadBytes <= 0) {
    throw new DocumentApiError(
      "configuration",
      "invalid_upload_limit",
      "The document upload limit must be greater than zero.",
    );
  }

  validateDocumentFile(file, maxUploadBytes);

  if (options.signal?.aborted) {
    throw new DocumentApiError(
      "cancelled",
      "request_cancelled",
      "Document parsing was cancelled.",
    );
  }

  const form = new FormData();
  form.append("file", file, file.name);
  const abort = linkedAbortController(options.signal, timeoutMs);

  try {
    const response = await fetch(
      appendOutputFormat(parseEndpoint(options.apiBaseUrl), outputFormat),
      {
        method: "POST",
        headers: {
          accept:
            outputFormat === "json" ? "application/json" : "text/markdown",
        },
        body: form,
        signal: abort.controller.signal,
      },
    );

    if (!response.ok) throw await errorFromResponse(response);

    const body = await response.text();
    if (!body.trim()) {
      throw new DocumentApiError(
        "empty",
        "empty_response",
        "The parsing service returned an empty response.",
        { status: response.status },
      );
    }

    if (outputFormat === "markdown") {
      return body as ParseResponseFor<Format>;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(body);
    } catch (cause) {
      throw new DocumentApiError(
        "server",
        "invalid_json_response",
        "The parsing service returned invalid JSON.",
        { status: response.status, cause },
      );
    }

    if (!isParseResult(parsed)) {
      throw new DocumentApiError(
        "server",
        "invalid_parse_response",
        "The parsing service returned an unexpected JSON structure.",
        { status: response.status },
      );
    }
    if (parsed.pages.length === 0) {
      throw new DocumentApiError(
        "empty",
        "empty_parse_result",
        "No document pages were returned by the parsing service.",
        { status: response.status },
      );
    }
    try {
      readCanonicalPresentation(parsed);
    } catch (cause) {
      throw new DocumentApiError(
        "server",
        "invalid_canonical_presentation",
        "The parsing service returned an invalid canonical presentation.",
        { status: response.status, cause },
      );
    }

    return parsed as ParseResponseFor<Format>;
  } catch (error) {
    if (error instanceof DocumentApiError) throw error;

    if (abort.didTimeout()) {
      throw new DocumentApiError(
        "timeout",
        "request_timeout",
        "Document parsing took longer than the configured timeout.",
        { cause: error, details: { timeout_ms: timeoutMs } },
      );
    }

    if (options.signal?.aborted) {
      throw new DocumentApiError(
        "cancelled",
        "request_cancelled",
        "Document parsing was cancelled.",
        { cause: error },
      );
    }

    throw new DocumentApiError(
      "network",
      "network_error",
      "The parsing service could not be reached.",
      { cause: error },
    );
  } finally {
    abort.dispose();
  }
}

export function parseJson(
  file: File,
  options?: ParseRequestOptions,
): Promise<ParseResult> {
  return requestParse(file, "json", options);
}

export function parseMarkdown(
  file: File,
  options?: ParseRequestOptions,
): Promise<string> {
  return requestParse(file, "markdown", options);
}

export function parseDocument<Format extends ParseOutputFormat>(
  file: File,
  outputFormat: Format,
  options?: ParseRequestOptions,
): Promise<ParseResponseFor<Format>> {
  return requestParse(file, outputFormat, options);
}

export function createParseBundle(
  file: File,
  options?: ParseRequestOptions,
): ParseBundle {
  const json = parseJson(file, options);
  let markdownRequest: Promise<string> | undefined;

  return {
    json,
    markdown: () => {
      markdownRequest ??= parseMarkdown(file, options);
      return markdownRequest;
    },
  };
}

function mergeOptions(
  defaults: DocumentApiClientOptions,
  options: ParseRequestOptions = {},
): ParseRequestOptions {
  return {
    ...defaults,
    ...options,
    signal: options.signal,
  };
}

export function createDocumentApiClient(
  defaults: DocumentApiClientOptions = {},
): DocumentApiClient {
  return {
    parseJson: (file, options) =>
      parseJson(file, mergeOptions(defaults, options)),
    parseMarkdown: (file, options) =>
      parseMarkdown(file, mergeOptions(defaults, options)),
    createParseBundle: (file, options) =>
      createParseBundle(file, mergeOptions(defaults, options)),
  };
}

export const documentApi = createDocumentApiClient();
