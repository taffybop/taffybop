/** Same-origin, owner-scoped durable product API. No owner or provider key is sent by the browser. */
export type ProductMode = "fast" | "cost_effective" | "agentic";
export interface ProductConfig {
  schema_version: "2.0";
  enabled: true;
  identity_mode: "local_development";
  uploads_enabled: boolean;
  parse_enabled: false;
  disabled_reason: string;
  default_mode: ProductMode;
  modes: { id: ProductMode; label: string }[];
}
export interface ProductArtifact { id: string; sha256: string; size_bytes: number; media_type: string }
export interface ProductDocument {
  schema_version: "2.0"; id: string; display_name: string; page_count: number;
  created_at: string; expires_at: string | null; state: "active"; source: ProductArtifact;
}
export interface ProductSettings { provider: string; adapter_version: string; mode: ProductMode; requested_version: string; max_pages: number }
export interface ProductUsage { estimated_credits: string | null; estimate_price_version: string | null; actual_credits: string | null; reconciliation: "pending" | "observed" | "unavailable" }
export type ProductJobStatus = "queued" | "submitting" | "submission_unknown" | "running" | "cancel_requested" | "succeeded" | "failed" | "cancelled";
export interface ProductJob {
  schema_version: "2.0"; id: string; document_id: string; status: ProductJobStatus; settings: ProductSettings;
  created_at: string; updated_at: string; result_id: string | null; raw_response: ProductArtifact | null;
  cancellation_requested_at: string | null; cancellation_confirmed: boolean; usage: ProductUsage; error: { code: string; message: string } | null;
}
export interface ProductPage { page_number: number; content: string }
export interface ProductSection { state: "available" | "empty" | "not_returned" | "unsupported"; pages: ProductPage[] }
export interface ProductResult {
  schema_version: "2.0"; id: string; document_id: string; job_id: string; settings: ProductSettings;
  provider_version: string | null; raw: ProductArtifact; markdown: ProductSection; text: ProductSection;
  warnings: string[]; usage: ProductUsage;
}
export interface ProductHistoryEntry { job: ProductJob; evidence_kind: "simulation" | "unverified" }
export interface ProductDocumentList { schema_version: "2.0"; documents: ProductDocument[]; next_cursor: string | null }
export interface ProductHistory { schema_version: "2.0"; jobs: ProductHistoryEntry[] }
export interface ProductRequestOptions { signal?: AbortSignal; timeoutMs?: number }

export class ProductApiError extends Error {
  readonly code: string;
  readonly status: number | null;
  constructor(code: string, message: string, status: number | null = null) {
    super(message); this.name = "ProductApiError"; this.code = code; this.status = status;
  }
}
const object = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
export const isProductId = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const positive = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const versioned = (value: unknown): value is Record<string, unknown> => object(value) && value.schema_version === "2.0";
const mode = (value: unknown): value is ProductMode => ["fast", "cost_effective", "agentic"].includes(value as string);
const decimal = (value: unknown) => value === null || typeof value === "string" && /^\d+(\.\d+)?([Ee][+-]?\d+)?$/.test(value);
const usage = (value: unknown) => object(value) && decimal(value.estimated_credits) && decimal(value.actual_credits)
  && ["pending", "observed", "unavailable"].includes(value.reconciliation as string)
  && ((value.reconciliation === "observed") === (value.actual_credits !== null));
const settings = (value: unknown) => object(value) && mode(value.mode) && text(value.requested_version) && positive(value.max_pages);
const artifact = (value: unknown) => object(value) && isProductId(value.id) && typeof value.sha256 === "string"
  && /^[a-f0-9]{64}$/.test(value.sha256) && positive(value.size_bytes)
  && ["application/pdf", "image/png", "image/jpeg", "application/json"].includes(value.media_type as string);
const documentModel = (value: unknown): value is ProductDocument => versioned(value) && isProductId(value.id)
  && text(value.display_name) && positive(value.page_count) && text(value.created_at) && value.state === "active" && artifact(value.source);
const jobStatuses = new Set(["queued", "submitting", "submission_unknown", "running", "cancel_requested", "succeeded", "failed", "cancelled"]);
export function isTerminalProductJob(job: ProductJob): boolean { return ["succeeded", "failed", "cancelled"].includes(job.status); }
const jobModel = (value: unknown): value is ProductJob => versioned(value) && isProductId(value.id) && isProductId(value.document_id)
  && jobStatuses.has(value.status as string) && settings(value.settings) && usage(value.usage)
  && (value.result_id === null || isProductId(value.result_id)) && ((value.status === "succeeded") === (value.result_id !== null))
  && (value.raw_response === null || artifact(value.raw_response)) && typeof value.cancellation_confirmed === "boolean"
  && (value.cancellation_requested_at === null || text(value.cancellation_requested_at))
  && (value.error === null || object(value.error) && text(value.error.code) && text(value.error.message));
const section = (value: unknown): value is ProductSection => object(value)
  && ["available", "empty", "not_returned", "unsupported"].includes(value.state as string)
  && Array.isArray(value.pages) && (value.state === "available" ? value.pages.length > 0 : value.pages.length === 0)
  && value.pages.every((page) => object(page) && positive(page.page_number) && typeof page.content === "string");

function invalid(): never { throw new ProductApiError("invalid_response", "The document server returned an unsupported response."); }
function resourcePath(id: string): string { if (!isProductId(id)) throw new ProductApiError("invalid_id", "This saved resource identifier is invalid."); return id.toLowerCase(); }

async function boundedBytes(response: Response, maximum: number): Promise<Uint8Array> {
  if (Number(response.headers.get("content-length")) > maximum) {
    await response.body?.cancel();
    throw new ProductApiError("response_too_large", "This result is too large to open in the browser. Download the original instead.");
  }
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      size += part.value.byteLength;
      if (size > maximum) {
        await reader.cancel();
        throw new ProductApiError("response_too_large", "This result is too large to open in the browser. Download the original instead.");
      }
      parts.push(part.value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { bytes.set(part, offset); offset += part.byteLength; }
  return bytes;
}

async function request(path: string, init: RequestInit = {}, options: ProductRequestOptions = {}, maximum = 64 * 1024 * 1024): Promise<{ bytes: Uint8Array; response: Response }> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) throw new DOMException("Request stopped.", "AbortError");
  options.signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, options.timeoutMs ?? 30_000);
  try {
    const response = await fetch(path, { ...init, cache: "no-store", credentials: "same-origin", signal: controller.signal });
    const bytes = await boundedBytes(response, maximum);
    if (!response.ok) {
      let data: unknown;
      try { data = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { /* Fixed fallback below. */ }
      const detail = object(data) && object(data.error) ? data.error : null;
      throw new ProductApiError(detail && text(detail.code) ? detail.code : "request_failed",
        detail && text(detail.message) ? detail.message : `The document request failed (HTTP ${response.status}).`, response.status);
    }
    return { response, bytes };
  } catch (failure) {
    if (options.signal?.aborted) throw new DOMException("Request stopped.", "AbortError");
    if (timedOut) throw new ProductApiError("request_timeout", "The document server took too long to respond. Check the library before uploading again.");
    if (failure instanceof ProductApiError) throw failure;
    throw new ProductApiError("network_error", "Could not reach the document server. Check the library before uploading again.");
  } finally { clearTimeout(timer); options.signal?.removeEventListener("abort", abort); }
}
async function json(path: string, init: RequestInit = {}, options?: ProductRequestOptions): Promise<unknown> {
  const { bytes } = await request(path, { ...init, headers: { accept: "application/json", ...init.headers } }, options);
  try { return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)); } catch { return invalid(); }
}
export async function getProductConfig(options?: ProductRequestOptions): Promise<ProductConfig> {
  const value = await json("/v2/config", {}, options);
  if (!versioned(value) || value.enabled !== true || value.identity_mode !== "local_development"
    || typeof value.uploads_enabled !== "boolean" || value.parse_enabled !== false || !text(value.disabled_reason)
    || !mode(value.default_mode) || !Array.isArray(value.modes) || !value.modes.length
    || value.modes.some((entry) => !object(entry) || !mode(entry.id) || !text(entry.label))
    || new Set(value.modes.map((entry) => entry.id)).size !== value.modes.length
    || !value.modes.some((entry) => entry.id === value.default_mode)) invalid();
  return value as unknown as ProductConfig;
}
export async function listProductDocuments(cursor: string | null = null, options?: ProductRequestOptions): Promise<ProductDocumentList> {
  const value = await json(`/v2/documents?limit=25${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`, {}, options);
  if (!versioned(value) || !Array.isArray(value.documents) || !value.documents.every(documentModel)
    || !(value.next_cursor === null || text(value.next_cursor))) invalid();
  return value as unknown as ProductDocumentList;
}
export async function getProductDocument(id: string, options?: ProductRequestOptions): Promise<ProductDocument> {
  const value = await json(`/v2/documents/${resourcePath(id)}`, {}, options);
  if (!documentModel(value) || value.id !== id.toLowerCase()) invalid();
  return value;
}
export async function uploadProductDocument(file: File, options?: ProductRequestOptions): Promise<ProductDocument> {
  const body = new FormData(); body.set("file", file);
  const value = await json("/v2/documents", { method: "POST", body }, { timeoutMs: 70_000, ...options });
  if (!documentModel(value)) invalid();
  return value;
}
export async function getProductHistory(id: string, options?: ProductRequestOptions): Promise<ProductHistory> {
  const value = await json(`/v2/documents/${resourcePath(id)}/jobs`, {}, options);
  if (!versioned(value) || !Array.isArray(value.jobs) || !value.jobs.every((entry) => object(entry)
    && jobModel(entry.job) && entry.job.document_id === id.toLowerCase() && ["simulation", "unverified"].includes(entry.evidence_kind as string))) invalid();
  return value as unknown as ProductHistory;
}
export async function getProductJob(id: string, options?: ProductRequestOptions): Promise<ProductJob> {
  const value = await json(`/v2/jobs/${resourcePath(id)}`, {}, options);
  if (!jobModel(value) || value.id !== id.toLowerCase()) invalid();
  return value;
}
export async function cancelProductJob(id: string, options?: ProductRequestOptions): Promise<ProductJob> {
  const value = await json(`/v2/jobs/${resourcePath(id)}/cancel`, { method: "POST" }, options);
  if (!jobModel(value) || value.id !== id.toLowerCase()) invalid();
  return value;
}
export async function getProductResult(id: string, options?: ProductRequestOptions): Promise<ProductResult> {
  const value = await json(`/v2/parse-results/${resourcePath(id)}`, {}, options);
  if (!versioned(value) || value.id !== id.toLowerCase() || !isProductId(value.document_id) || !isProductId(value.job_id)
    || !artifact(value.raw) || !settings(value.settings) || !section(value.markdown) || !section(value.text)
    || !Array.isArray(value.warnings) || value.warnings.some((entry) => typeof entry !== "string") || !usage(value.usage)
    || !(value.provider_version === null || text(value.provider_version))) invalid();
  return value as unknown as ProductResult;
}
export function productArtifactUrl(id: string, download = false): string {
  return `/v2/artifacts/${resourcePath(id)}/content${download ? "?download=1" : ""}`;
}
export async function getProductRawPreview(id: string, options?: ProductRequestOptions): Promise<string> {
  const { bytes } = await request(productArtifactUrl(id), {}, options, 1024 * 1024);
  try { return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes); } catch { return invalid(); }
}
export async function getProductSource(source: ProductArtifact, options?: ProductRequestOptions): Promise<Blob> {
  const { bytes } = await request(productArtifactUrl(source.id), {}, options, 10 * 1024 * 1024);
  if (bytes.byteLength !== source.size_bytes) invalid();
  const digest = await crypto.subtle.digest("SHA-256", new Uint8Array(bytes).buffer);
  if (Array.from(new Uint8Array(digest), (part) => part.toString(16).padStart(2, "0")).join("") !== source.sha256) invalid();
  return new Blob([new Uint8Array(bytes).buffer], { type: source.media_type });
}
