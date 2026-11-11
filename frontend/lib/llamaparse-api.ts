/** Same-origin client for the server-owned LlamaCloud integration. */
export const LLAMAPARSE_ACCEPT = ".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg";
export const LLAMAPARSE_MAX_RESPONSE_BYTES = 64 * 1024 * 1024;

export interface LlamaParseMode {
  id: string;
  label: string;
  description: string;
  credits_per_page: number;
}

export interface LlamaParseConfig {
  configured: boolean;
  submission_enabled?: boolean;
  modes: LlamaParseMode[];
  default_mode: string;
  max_upload_bytes: number;
  max_pages: number;
}

export interface LlamaParseJob {
  job_id: string;
  mode: string;
  status: string;
  estimated_credits: number | null;
  page_count: number | null;
}

export type LlamaParseStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type LlamaParseFormat = "markdown" | "text";
export interface LlamaParseResponse {
  data: Record<string, unknown>;
  rawText: string;
  rawBytes: Uint8Array;
  contentType: string;
}

export interface LlamaParsePage {
  pageNumber: number;
  /** Exact provider string. Never trimmed, rendered back to text, or reconstructed. */
  content: string;
}

export type LlamaParsePageResult = {
  kind: "available" | "not_returned" | "empty" | "unsupported";
  pages: LlamaParsePage[];
};

interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  maxResponseBytes?: number;
}

export class LlamaParseApiError extends Error {
  readonly code: string;
  readonly status: number | null;

  constructor(code: string, message: string, status: number | null = null) {
    super(message);
    this.name = "LlamaParseApiError";
    this.code = code;
    this.status = status;
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function positiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function nonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function nonemptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

async function responseBytes(response: Response, limit: number): Promise<Uint8Array> {
  if (!positiveInteger(limit)) throw new LlamaParseApiError("invalid_limit", "Invalid response byte limit.");
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > limit) {
    await response.body?.cancel().catch(() => undefined);
    throw new LlamaParseApiError("response_too_large", "The result is too large to open in this browser.", response.status);
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      size += next.value.byteLength;
      if (size > limit) {
        await reader.cancel().catch(() => undefined);
        throw new LlamaParseApiError("response_too_large", "The result is too large to open in this browser.", response.status);
      }
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes;
}

async function request(path: string, init: RequestInit, options: RequestOptions = {}): Promise<LlamaParseResponse & { status: number }> {
  if (options.signal?.aborted) throw new DOMException("Stopped waiting locally.", "AbortError");
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort(options.signal?.reason);
  if (options.signal?.aborted) abort();
  else options.signal?.addEventListener("abort", abort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, options.timeoutMs ?? 30_000);
  try {
    const response = await fetch(path, {
      ...init,
      headers: { accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    const rawBytes = await responseBytes(response, options.maxResponseBytes ?? LLAMAPARSE_MAX_RESPONSE_BYTES);
    let rawText = "";
    let data: unknown;
    try {
      // ignoreBOM preserves the BOM in rawText; only the JSON parser ignores it.
      rawText = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(rawBytes);
      data = JSON.parse(rawText.replace(/^\uFEFF/, ""));
    } catch {
      throw new LlamaParseApiError("invalid_response", response.ok
        ? "The server returned an unreadable JSON response."
        : `The server could not complete this request (HTTP ${response.status}).`, response.status);
    }
    if (!response.ok) {
      const error = record(data) && record(data.error) ? data.error : null;
      throw new LlamaParseApiError(
        error && nonemptyString(error.code) ? error.code : "request_failed",
        error && nonemptyString(error.message) ? error.message : `Request failed (HTTP ${response.status}).`,
        response.status,
      );
    }
    if (!record(data)) throw new LlamaParseApiError("invalid_response", "The server returned an unsupported JSON response.", response.status);
    return { data, rawText, rawBytes, contentType: response.headers.get("content-type") ?? "application/json", status: response.status };
  } catch (error) {
    if (options.signal?.aborted) throw new DOMException("Stopped waiting locally.", "AbortError");
    if (timedOut) throw new LlamaParseApiError("request_timeout", "The server took too long to respond. The provider job may still be running.");
    if (error instanceof LlamaParseApiError) throw error;
    throw new LlamaParseApiError("network_error", "Could not reach the parsing server. Check your connection and try again.");
  } finally {
    clearTimeout(timeout);
    options.signal?.removeEventListener("abort", abort);
  }
}

export async function getLlamaParseConfig(options?: RequestOptions): Promise<LlamaParseConfig> {
  const { data } = await request("/v1/llamaparse/config", { method: "GET" }, options);
  const modes = data.modes;
  if (typeof data.configured !== "boolean"
    || (data.submission_enabled !== undefined && typeof data.submission_enabled !== "boolean")
    || !Array.isArray(modes) || modes.length === 0
    || !positiveInteger(data.max_upload_bytes) || !positiveInteger(data.max_pages)
    || !nonemptyString(data.default_mode)
    || modes.some((mode: unknown) => !record(mode) || !nonemptyString(mode.id)
      || !nonemptyString(mode.label) || typeof mode.description !== "string" || !positiveInteger(mode.credits_per_page))) {
    throw new LlamaParseApiError("invalid_config", "The server returned an unsupported parsing configuration.");
  }
  const ids = modes.map((mode: LlamaParseMode) => mode.id);
  if (new Set(ids).size !== ids.length || !ids.includes(data.default_mode)) {
    throw new LlamaParseApiError("invalid_config", "The server's parsing modes are inconsistent.");
  }
  return data as unknown as LlamaParseConfig;
}

export function validateLlamaParseFile(file: File, maxBytes: number): void {
  const extension = file.name.split(".").pop()?.toLowerCase();
  const allowed: Record<string, string[]> = {
    pdf: ["application/pdf"],
    png: ["image/png"],
    jpg: ["image/jpeg"],
    jpeg: ["image/jpeg"],
  };
  if (!extension || !allowed[extension]
    || (file.type && file.type !== "application/octet-stream" && !allowed[extension].includes(file.type))) {
    throw new LlamaParseApiError("unsupported_file", "Choose a PDF, PNG or JPEG file.");
  }
  if (file.size === 0) throw new LlamaParseApiError("empty_file", "This file is empty. Choose another file.");
  if (!positiveInteger(maxBytes) || file.size > maxBytes) {
    throw new LlamaParseApiError("upload_too_large", "This file exceeds the server's upload limit.");
  }
}

export async function createLlamaParseJob(file: File, mode: string, config: LlamaParseConfig, options?: RequestOptions): Promise<LlamaParseJob> {
  if (config.submission_enabled === false) throw new LlamaParseApiError("submission_unavailable", "Parsing is unavailable in this session");
  if (!config.configured) throw new LlamaParseApiError("not_configured", "LlamaCloud key not configured on the server");
  if (!config.modes.some((candidate) => candidate.id === mode)) throw new LlamaParseApiError("unsupported_mode", "Choose a parsing mode offered by this server.");
  validateLlamaParseFile(file, config.max_upload_bytes);
  const body = new FormData();
  body.set("file", file);
  body.set("mode", mode);
  const { data, status } = await request("/v1/llamaparse/jobs", { method: "POST", body }, { timeoutMs: 160_000, ...options });
  if (status !== 202 || !nonemptyString(data.job_id) || data.mode !== mode || !nonemptyString(data.status)
    || !(data.estimated_credits === null || nonnegativeNumber(data.estimated_credits))
    || !(data.page_count === null || positiveInteger(data.page_count))) {
    throw new LlamaParseApiError("invalid_job", "The server did not return a usable job receipt. A provider job may have been created; submitting again may use more credits.", status);
  }
  return data as unknown as LlamaParseJob;
}

export function getLlamaParseStatus(data: Record<string, unknown>): LlamaParseStatus {
  const status = record(data.job) ? data.job.status : undefined;
  if (status === "PENDING" || status === "RUNNING" || status === "COMPLETED" || status === "FAILED" || status === "CANCELLED") return status;
  throw new LlamaParseApiError("unsupported_job_status", "The provider returned an unsupported job status. The raw response is available.");
}

export function getLlamaParseJobError(data: Record<string, unknown>): string | null {
  return record(data.job) && nonemptyString(data.job.error_message) ? data.job.error_message : null;
}

export async function getLlamaParseJob(jobId: string, options?: RequestOptions): Promise<LlamaParseResponse> {
  if (!nonemptyString(jobId)) throw new LlamaParseApiError("invalid_job_id", "No existing job is available to check.");
  return request(`/v1/llamaparse/jobs/${encodeURIComponent(jobId)}`, { method: "GET" }, options);
}

function wait(milliseconds: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Stopped waiting locally.", "AbortError")); return; }
    const abort = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Stopped waiting locally.", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** GET-only polling. Failures propagate so the UI can retry this same job. */
export async function pollLlamaParseJob(jobId: string, options: RequestOptions & {
  intervalMs?: number;
  onResponse?: (response: LlamaParseResponse) => void;
} = {}): Promise<LlamaParseResponse> {
  while (true) {
    const response = await getLlamaParseJob(jobId, options);
    options.onResponse?.(response);
    const status = getLlamaParseStatus(response.data);
    if (status !== "PENDING" && status !== "RUNNING") return response;
    await wait(options.intervalMs ?? 2_000, options.signal);
  }
}

export function getLlamaParsePages(data: Record<string, unknown>, format: LlamaParseFormat): LlamaParsePageResult {
  const output = data[format];
  if (output === undefined || output === null) return { kind: "not_returned", pages: [] };
  if (!record(output) || !Array.isArray(output.pages)) return { kind: "unsupported", pages: [] };
  if (output.pages.length === 0) return { kind: "empty", pages: [] };
  const pages: LlamaParsePage[] = [];
  for (const page of output.pages) {
    if (!record(page) || !positiveInteger(page.page_number) || typeof page[format] !== "string") {
      return { kind: "unsupported", pages: [] };
    }
    pages.push({ pageNumber: page.page_number, content: page[format] as string });
  }
  return { kind: "available", pages };
}
