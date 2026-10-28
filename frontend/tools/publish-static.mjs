import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../../", import.meta.url));
const buildRoot = fileURLToPath(new URL("../dist-static/", import.meta.url));
const manifestPath = resolve(projectRoot, "site-manifest.json");
const fixedFiles = [
  "index.html", "404.html", "_redirects", "robots.txt", "icon.svg", "og-knowledge.svg",
  "pdf.worker.min.mjs", "studio/index.html", "privacy/index.html", "parse/index.html",
  "extract/index.html", "samples/customer-support-handbook.pdf",
];

function isPublishedPath(path) {
  return fixedFiles.includes(path) || /^assets\/[a-zA-Z0-9_-]+\.(?:js|css|woff2?|ttf|svg|png|webp)$/u.test(path);
}

function digest(content) {
  return createHash("sha256").update(content).digest("hex");
}

async function existingFile(path) {
  try {
    const stat = await lstat(path);
    if (!stat.isFile()) throw new Error(`Refusing to overwrite a non-file: ${path}`);
    return readFile(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function checkParents(path) {
  let parent = dirname(path);
  while (parent !== projectRoot.replace(new RegExp(`${sep}$`, "u"), "")) {
    if (!parent.startsWith(projectRoot)) throw new Error("Publish target escapes the project root.");
    try {
      if (!(await lstat(parent)).isDirectory()) throw new Error(`Publish parent must be a real directory: ${parent}`);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    parent = dirname(parent);
  }
}

let previousManifest = null;
const previousBytes = await existingFile(manifestPath);
if (previousBytes) {
  previousManifest = JSON.parse(previousBytes.toString("utf8"));
  if (previousManifest.schemaVersion !== 1 || !Array.isArray(previousManifest.files)
    || previousManifest.files.some(file => !isPublishedPath(file.path) || !/^[a-f0-9]{64}$/u.test(file.sha256))) {
    throw new Error("Existing site-manifest.json is not a valid TaffyBop publication manifest.");
  }
}
const previousFiles = new Map((previousManifest?.files ?? []).map(file => [file.path, file.sha256]));
const assetNames = await readdir(resolve(buildRoot, "assets"));
const files = [...fixedFiles, ...assetNames.map(name => `assets/${name}`)].sort();
if (files.some(path => !isPublishedPath(path))) throw new Error("Build contains an unsupported public asset path.");

// Prepare and validate the entire release before replacing any published files.
const release = [];
for (const path of files) {
  const source = resolve(buildRoot, path);
  const sourceStat = await lstat(source);
  if (!sourceStat.isFile()) throw new Error(`Build output must be a regular file: ${path}`);
  const content = await readFile(source);
  if (/\.(?:js|mjs|html|css)$/u.test(path)) {
    const text = content.toString("utf8");
    if (/(?:PARSE_API_URL|NEXT_PUBLIC_PARSE_API_URL|\/api\/parse|\/v1\/parse|expertmodel\.json)/u.test(text)) {
      throw new Error(`Unexpected parser configuration or private fixture reference in ${path}`);
    }
  }
  const sha256 = digest(content);
  const destination = resolve(projectRoot, path);
  await checkParents(destination);
  const existing = await existingFile(destination);
  if (existing && digest(existing) !== sha256 && digest(existing) !== previousFiles.get(path)
    && !(path === "index.html" && !previousManifest)) {
    throw new Error(`Refusing to overwrite unrecognized local changes in ${path}`);
  }
  release.push({ path, content, sha256, bytes: content.length });
}

for (const file of release) {
  const destination = resolve(projectRoot, file.path);
  await mkdir(dirname(destination), { recursive: true });
  const temporary = `${destination}.publishing-${process.pid}`;
  await writeFile(temporary, file.content);
  await rename(temporary, destination);
}
const manifest = {
  schemaVersion: 1,
  generatedBy: "frontend/tools/publish-static.mjs",
  files: release.map(({ path, sha256, bytes }) => ({ path, sha256, bytes })),
};
const temporaryManifest = `${manifestPath}.publishing-${process.pid}`;
await writeFile(temporaryManifest, JSON.stringify(manifest, null, 2) + "\n");
await rename(temporaryManifest, manifestPath);
console.log(`Published ${release.length} verified public files to the repository root.`);
console.log("Other repository files and previous assets were left unchanged.");
