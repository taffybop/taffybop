/** Validate the one public endpoint that the static build may embed.
 * @param {string | undefined} raw
 */
export function staticApiEndpoint(raw) {
  const value = raw?.trim();
  if (!value || value === "/v1/parse") return "/v1/parse";
  const message = "TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL must be an HTTPS origin or /v1/parse endpoint without credentials, query parameters, or fragments.";
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error(message);
  }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash
    || !["", "/", "/v1/parse", "/v1/parse/"].includes(url.pathname)
    || /[\s\\]/u.test(value)) {
    throw new Error(message);
  }
  return `${url.origin}/v1/parse`;
}

/** @param {string | undefined} raw */
export function staticParserDefines(raw) {
  return {
    "process.env.NEXT_PUBLIC_PARSE_API_URL": JSON.stringify(staticApiEndpoint(raw)),
    "process.env.NEXT_PUBLIC_PARSE_API_TIMEOUT_MS": "undefined",
    "process.env.NEXT_PUBLIC_PARSE_API_MAX_UPLOAD_BYTES": "undefined",
  };
}

/**
 * @param {{ schemaVersion?: number, parseApiUrl?: string } | null} build
 * @param {Record<string, string | undefined>} env
 */
export function assertStaticPublishReady(build, env) {
  if (!build || build.schemaVersion !== 1 || typeof build.parseApiUrl !== "string") {
    throw new Error("Static API build metadata is missing or invalid. Run build:static again.");
  }
  const endpoint = staticApiEndpoint(env.TAFFYBOP_STATIC_PUBLIC_PARSE_API_URL);
  if (build.parseApiUrl !== endpoint) {
    throw new Error("The static build API endpoint differs from the publication environment. Rebuild with the intended public API URL before publishing.");
  }
  if (env.TAFFYBOP_STATIC_API_GATEWAY_READY !== "1") {
    throw new Error("Static publication requires TAFFYBOP_STATIC_API_GATEWAY_READY=1 after verifying the configured API and its browser access. Deploy the unified API+UI image otherwise.");
  }
  return endpoint;
}
