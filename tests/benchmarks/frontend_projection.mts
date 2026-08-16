import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";

import {
  findCanonicalPage,
  readCanonicalPresentation,
} from "../../frontend/lib/canonical-presentation.ts";
import {
  normalizeDocumentJson,
  serializeNormalizedDocumentJson,
} from "../../frontend/lib/normalize-document-json.ts";
import {
  serializeDocumentJson,
  serializeDocumentMarkdown,
  serializePageMarkdown,
  serializePageOutput,
} from "../../frontend/lib/serialize-output.ts";
import type { ParseResult } from "../../frontend/lib/types.ts";

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

type ProjectionOutcome<T> =
  | {
      ok: true;
      value: T;
    }
  | {
      error: {
        message: string;
        name: string;
      };
      ok: false;
    };

interface BatchProjectionInput {
  cases: Array<{
    id: string;
    payload: ParseResult;
  }>;
  schema_version: "1.0";
}

function projectionOutcome<T>(operation: () => T): ProjectionOutcome<T> {
  try {
    return { ok: true, value: operation() };
  } catch (error) {
    return {
      error: {
        message: error instanceof Error ? error.message : String(error),
        name: error instanceof Error ? error.name : "Error",
      },
      ok: false,
    };
  }
}

function isBatchProjectionInput(value: unknown): value is BatchProjectionInput {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const record = value as Record<string, unknown>;
  if (record.schema_version !== "1.0" || !Array.isArray(record.cases)) {
    return false;
  }
  return record.cases.every((entry) => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      return false;
    }
    const caseRecord = entry as Record<string, unknown>;
    return (
      typeof caseRecord.id === "string" &&
      caseRecord.id.length > 0 &&
      typeof caseRecord.payload === "object" &&
      caseRecord.payload !== null &&
      !Array.isArray(caseRecord.payload)
    );
  });
}

function batchProjection(raw: ParseResult) {
  const before = structuredClone(raw);
  const canonical = projectionOutcome(() => readCanonicalPresentation(raw));
  const canonicalPages = projectionOutcome(() => {
    const presentation = readCanonicalPresentation(raw);
    if (presentation === null) {
      return raw.pages.map(() => null);
    }
    return raw.pages.map(
      (page) =>
        findCanonicalPage(presentation, page)?.page_index ?? null,
    );
  });
  const documentMarkdown = projectionOutcome(() =>
    serializeDocumentMarkdown(raw),
  );
  const pageMarkdown = projectionOutcome(() =>
    raw.pages.map((page) => serializePageMarkdown(page, raw)),
  );
  const pageOutputMarkdown = projectionOutcome(() =>
    raw.pages.map(
      (page) => serializePageOutput(page, "markdown", raw).content,
    ),
  );
  const normalized = projectionOutcome(() => {
    const value = normalizeDocumentJson(raw);
    const serialized = JSON.parse(
      serializeNormalizedDocumentJson(raw),
    ) as unknown;
    return {
      serialized_matches_value: isDeepStrictEqual(serialized, value),
      value,
    };
  });
  const documentJsonPreserved = projectionOutcome(() =>
    isDeepStrictEqual(JSON.parse(serializeDocumentJson(raw)), raw),
  );

  return {
    canonical,
    canonical_pages: canonicalPages,
    document_json_preserved: documentJsonPreserved,
    document_markdown: documentMarkdown,
    input_unchanged: isDeepStrictEqual(raw, before),
    normalized,
    page_markdown: pageMarkdown,
    page_output_markdown: pageOutputMarkdown,
  };
}

async function runBatch(
  inputArgument: string,
  outputArgument: string,
): Promise<void> {
  const inputPath = resolve(inputArgument);
  const outputPath = resolve(outputArgument);
  const manifest = JSON.parse(await readFile(inputPath, "utf8")) as unknown;
  if (!isBatchProjectionInput(manifest)) {
    throw new Error(
      "batch input must be a 1.0 manifest with nonempty case IDs and payloads",
    );
  }
  const ids = manifest.cases.map(({ id }) => id);
  if (new Set(ids).size !== ids.length) {
    throw new Error("batch input repeats a case ID");
  }

  const output = {
    cases: manifest.cases.map(({ id, payload }) => ({
      id,
      projection: batchProjection(payload),
    })),
    node: process.version,
    schema_version: "1.0",
  };
  const serialized = JSON.stringify(output);
  await writeFile(outputPath, serialized, "utf8");
  process.stdout.write(
    JSON.stringify({
      case_count: output.cases.length,
      mode: "batch",
      node: output.node,
      output_sha256: sha256(serialized),
      output_size_bytes: Buffer.byteLength(serialized, "utf8"),
    }),
  );
}

async function runSingle(
  inputArgument: string,
  outputArgument: string,
): Promise<void> {
  const inputPath = resolve(inputArgument);
  const outputDirectory = resolve(outputArgument);
  const raw = JSON.parse(await readFile(inputPath, "utf8")) as ParseResult;
  const normalized = normalizeDocumentJson(raw);
  const normalizedJson = serializeNormalizedDocumentJson(raw);
  const markdown = serializeDocumentMarkdown(raw);
  const text = normalized.text_full;

  await Promise.all([
    writeFile(
      resolve(outputDirectory, "frontend-normalized.json"),
      normalizedJson,
      "utf8",
    ),
    writeFile(
      resolve(outputDirectory, "frontend-markdown.md"),
      markdown,
      "utf8",
    ),
    writeFile(resolve(outputDirectory, "frontend-text.txt"), text, "utf8"),
  ]);

  process.stdout.write(
    JSON.stringify({
      markdown_sha256: sha256(markdown),
      markdown_size_bytes: Buffer.byteLength(markdown, "utf8"),
      node: process.version,
      normalized_json_sha256: sha256(normalizedJson),
      normalized_json_size_bytes: Buffer.byteLength(normalizedJson, "utf8"),
      text_sha256: sha256(text),
      text_size_bytes: Buffer.byteLength(text, "utf8"),
    }),
  );
}

const arguments_ = process.argv.slice(2);
if (arguments_[0] === "--batch") {
  const [, inputArgument, outputArgument, ...unexpected] = arguments_;
  if (!inputArgument || !outputArgument || unexpected.length) {
    throw new Error(
      "usage: frontend_projection.mts --batch <manifest.json> <output.json>",
    );
  }
  await runBatch(inputArgument, outputArgument);
} else {
  const [inputArgument, outputArgument, ...unexpected] = arguments_;
  if (!inputArgument || !outputArgument || unexpected.length) {
    throw new Error(
      "usage: frontend_projection.mts <our-output.json> <output-directory>",
    );
  }
  await runSingle(inputArgument, outputArgument);
}
