#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  mkdir,
  readFile,
  readdir,
  rename,
  writeFile,
} from "node:fs/promises";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { runnerImport } from "vite";

const FRONTEND_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SCHEMA_VERSION = "clearleaf-rendered-ui-capture-v1";
const CONTRACT_PATH = "app/rendered-page-capture.tsx";

function usage() {
  return [
    "Usage:",
    "  node tools/capture-rendered-ui.mjs --run-dir <service-artifact-root>",
    "      [--case <case-id>]... [--view body|full]",
    "",
    "Each case directory must contain response.json. Captures are written to",
    "<case-id>/pages/page-<N>/rendered-dom.json with a deterministic manifest",
    "at <case-id>/rendered-capture.json.",
  ].join("\n");
}

export function parseArguments(argv) {
  let runDir = null;
  let view = "body";
  const cases = [];
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--run-dir") runDir = argv[++index] ?? null;
    else if (argument === "--case") cases.push(argv[++index] ?? "");
    else if (argument === "--view") view = argv[++index] ?? "";
    else if (argument === "--help" || argument === "-h") {
      return { help: true, runDir: null, view: "body", cases: [] };
    } else {
      throw new Error(`Unsupported argument: ${argument}`);
    }
  }
  if (!runDir) throw new Error("--run-dir is required");
  if (view !== "body" && view !== "full") {
    throw new Error("--view must be body or full");
  }
  if (cases.some((caseId) => !/^[a-z0-9][a-z0-9-]*$/u.test(caseId))) {
    throw new Error("--case values must be non-empty lowercase case IDs");
  }
  return {
    help: false,
    runDir: resolve(runDir),
    view,
    cases: [...new Set(cases)].sort(),
  };
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function decodeHtmlEntities(value) {
  const named = new Map([
    ["amp", "&"],
    ["apos", "'"],
    ["gt", ">"],
    ["lt", "<"],
    ["quot", '"'],
  ]);
  return value.replace(
    /&(?:#(\d+)|#x([0-9a-f]+)|([a-z]+));/giu,
    (entity, decimal, hexadecimal, name) => {
      if (decimal) return String.fromCodePoint(Number.parseInt(decimal, 10));
      if (hexadecimal) {
        return String.fromCodePoint(Number.parseInt(hexadecimal, 16));
      }
      return named.get(String(name).toLowerCase()) ?? entity;
    },
  );
}

/** A deterministic text projection for human inspection; analyzers use html. */
export function visibleTextFromHtml(html) {
  const projected = html
    .replace(/<svg\b[\s\S]*?<\/svg>/giu, "")
    .replace(/<br\s*\/?>/giu, "\n")
    .replace(/<\/(?:th|td)>/giu, "\t")
    .replace(/<\/tr>/giu, "\n")
    .replace(/<\/(?:p|h[1-6]|pre|figcaption|li|table|figure)>/giu, "\n\n")
    .replace(/<[^>]*>/gu, "");
  return decodeHtmlEntities(projected)
    .replace(/[ \f\v]+\t/gu, "\t")
    .replace(/\t+(?=\n)/gu, "")
    .replace(/[ \t]+\n/gu, "\n")
    .replace(/\n{3,}/gu, "\n\n")
    .trim();
}

async function atomicJson(path, payload) {
  const serialized = `${JSON.stringify(payload, null, 2)}\n`;
  const temporary = `${path}.tmp`;
  await writeFile(temporary, serialized, "utf8");
  await rename(temporary, path);
  return serialized;
}

async function caseIds(runDir, requested) {
  if (requested.length) return requested;
  const entries = await readdir(runDir, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
}

function physicalPageCount(result) {
  const declared = Number(result?.document?.page_count);
  if (!Number.isSafeInteger(declared) || declared < 1) {
    throw new Error("response.json document.page_count must be a positive integer");
  }
  return declared;
}

async function captureCase({ caseDir, caseId, component, view }) {
  const responsePath = join(caseDir, "response.json");
  const responseBytes = await readFile(responsePath);
  const result = JSON.parse(responseBytes.toString("utf8"));
  const pageCount = physicalPageCount(result);
  const pages = [];

  for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
    const html = renderToStaticMarkup(
      createElement(component, {
        result,
        pageNumber,
        pagePresentationView: view,
      }),
    );
    const payload = {
      page_number: pageNumber,
      html,
      text: visibleTextFromHtml(html),
    };
    const outputDir = join(caseDir, "pages", `page-${pageNumber}`);
    await mkdir(outputDir, { recursive: true });
    const serialized = await atomicJson(
      join(outputDir, "rendered-dom.json"),
      payload,
    );
    pages.push({
      page_number: pageNumber,
      artifact: `pages/page-${pageNumber}/rendered-dom.json`,
      artifact_sha256: sha256(serialized),
      html_sha256: sha256(html),
      text_sha256: sha256(payload.text),
    });
  }

  await atomicJson(join(caseDir, "rendered-capture.json"), {
    schema_version: SCHEMA_VERSION,
    case_id: caseId,
    renderer: "ClearleafWorkspace/RenderedPageCapture",
    renderer_contract: CONTRACT_PATH,
    presentation_view: view,
    source_response: basename(responsePath),
    source_response_sha256: sha256(responseBytes),
    page_count: pageCount,
    pages,
  });

  return { caseId, pageCount };
}

export async function captureRenderedUi(options) {
  const imported = await runnerImport(resolve(FRONTEND_ROOT, CONTRACT_PATH), {
    root: FRONTEND_ROOT,
    resolve: { alias: { "@": FRONTEND_ROOT } },
    logLevel: "error",
  });
  if (typeof imported.module.RenderedPageCapture !== "function") {
    throw new Error(`${CONTRACT_PATH} does not export RenderedPageCapture`);
  }
  const selectedCases = await caseIds(options.runDir, options.cases);
  const captures = [];
  for (const caseId of selectedCases) {
    captures.push(
      await captureCase({
        caseDir: join(options.runDir, caseId),
        caseId,
        component: imported.module.RenderedPageCapture,
        view: options.view,
      }),
    );
  }
  return captures;
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  if (options.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  const captures = await captureRenderedUi(options);
  const pages = captures.reduce(
    (total, capture) => total + capture.pageCount,
    0,
  );
  process.stdout.write(
    `Captured ${pages} page${pages === 1 ? "" : "s"} across ${captures.length} case${captures.length === 1 ? "" : "s"}.\n`,
  );
}

if (resolve(process.argv[1] ?? "") === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    process.stderr.write(
      `${error instanceof Error ? error.message : String(error)}\n`,
    );
    process.exitCode = 1;
  });
}
