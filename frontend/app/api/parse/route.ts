const DEFAULT_BACKEND_URL = "http://127.0.0.1:8000";
const DEFAULT_PROXY_TIMEOUT_MS = 330_000;
const PARSE_PATH = "/v1/parse";

function runtimeValue(name: string): string | undefined {
  const processValue = process.env[name];
  return processValue?.trim() || undefined;
}

function positiveNumber(value: string | undefined, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function backendEndpoint(): string {
  const configured = runtimeValue("PARSE_API_URL") ?? DEFAULT_BACKEND_URL;
  const withoutTrailingSlash = configured.replace(/\/+$/, "");
  return withoutTrailingSlash.endsWith(PARSE_PATH)
    ? withoutTrailingSlash
    : `${withoutTrailingSlash}${PARSE_PATH}`;
}

function proxyError(
  status: number,
  code: string,
  message: string,
  details: Record<string, unknown> = {},
): Response {
  return Response.json(
    { error: { code, message, details } },
    { status, headers: { "cache-control": "no-store" } },
  );
}

/**
 * Same-origin transport for deployments where the browser cannot call the
 * parser directly. The multipart body is forwarded unchanged; successful and
 * error responses from the parser retain their status, content type, and body.
 */
export async function POST(request: Request): Promise<Response> {
  const requestUrl = new URL(request.url);
  let upstreamUrl: URL;
  try {
    upstreamUrl = new URL(backendEndpoint());
    if (!["http:", "https:"].includes(upstreamUrl.protocol)) {
      throw new TypeError("Unsupported parser URL protocol.");
    }
  } catch {
    return proxyError(
      503,
      "parse_proxy_configuration_error",
      "The frontend proxy is not configured with a valid parsing API URL.",
    );
  }

  const outputFormat = requestUrl.searchParams.get("output_format");
  if (outputFormat !== null) {
    upstreamUrl.searchParams.set("output_format", outputFormat);
  }

  const contentType = request.headers.get("content-type");
  if (!contentType) {
    return proxyError(
      400,
      "missing_content_type",
      "The document upload is missing its content type.",
    );
  }

  const controller = new AbortController();
  const timeoutMs = positiveNumber(
    runtimeValue("PARSE_API_TIMEOUT_MS"),
    DEFAULT_PROXY_TIMEOUT_MS,
  );
  const timeout = setTimeout(
    () =>
      controller.abort(
        new DOMException("Upstream request timed out.", "TimeoutError"),
      ),
    timeoutMs,
  );

  try {
    const response = await fetch(upstreamUrl, {
      method: "POST",
      headers: {
        "content-type": contentType,
        accept:
          request.headers.get("accept") ??
          (outputFormat === "markdown"
            ? "text/markdown"
            : "application/json"),
      },
      body: await request.arrayBuffer(),
      signal: controller.signal,
    });

    const headers = new Headers();
    const responseContentType = response.headers.get("content-type");
    if (responseContentType) headers.set("content-type", responseContentType);
    headers.set("cache-control", "no-store");

    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch (error) {
    if (controller.signal.aborted) {
      return proxyError(
        504,
        "document_processing_timeout",
        "The parsing service did not respond before the proxy timeout.",
        { timeout_ms: timeoutMs },
      );
    }

    return proxyError(
      502,
      "parse_service_unreachable",
      "The parsing service could not be reached.",
      { reason: error instanceof Error ? error.name : "NetworkError" },
    );
  } finally {
    clearTimeout(timeout);
  }
}
