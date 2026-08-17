import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspace = await readFile(
  new URL("../app/clearleaf-workspace.tsx", import.meta.url),
  "utf8",
);

function sourceSection(start: string, end: string): string {
  const startIndex = workspace.indexOf(start);
  const endIndex = workspace.indexOf(end, startIndex);
  assert.notEqual(startIndex, -1, `Expected workspace source to contain ${start}`);
  assert.notEqual(endIndex, -1, `Expected workspace source to contain ${end}`);
  return workspace.slice(startIndex, endIndex);
}

test("canonical rendering cannot leak omitted legacy OCR or raw HTML", () => {
  const blockSelection = sourceSection(
    "function canonicalPageBlocks",
    "function ContentItemView",
  );
  const canonicalRenderer = sourceSection(
    "function CanonicalRenderedPage",
    "function MarkdownSource",
  );
  const tableAuthority = sourceSection(
    "function tableItemAuthority",
    "function errorForUi",
  );

  assert.match(blockSelection, /page\.full\.block_ids/);
  assert.match(blockSelection, /\.map\(\(blockId\) => blocksById\.get\(blockId\)\)/);
  assert.match(blockSelection, /block\.omission_reason == null/);
  assert.doesNotMatch(blockSelection, /page\.items|ocr_text|itemText/);

  assert.match(canonicalRenderer, /\{block\.text\}/);
  assert.match(canonicalRenderer, /style=\{\{ whiteSpace: "pre-wrap" \}\}/);
  assert.match(
    canonicalRenderer,
    /primaryElementType === "heading" && headingLevel !== null[\s\S]*?createElement\(\s*`h\$\{headingLevel\}`/,
  );
  assert.match(
    canonicalRenderer,
    /className: `parsed-heading parsed-heading-\$\{headingLevel\}`/,
  );
  assert.match(
    canonicalRenderer,
    /"data-item-type": primaryElementType/,
  );
  assert.match(
    canonicalRenderer,
    /data-item-type=\{primaryElementType\}/,
  );
  assert.doesNotMatch(
    canonicalRenderer,
    /dangerouslySetInnerHTML|block\.markdown|\.html/,
  );
  assert.equal((canonicalRenderer.match(/<ContentItemView/g) ?? []).length, 2);
  assert.match(
    canonicalRenderer,
    /if \(!tableItemAuthority\(primaryItem\)\)/,
  );
  assert.match(
    canonicalRenderer,
    /if \(primaryItem === captionedTableOwner && captionedTableLink\) \{[\s\S]*?className="captioned-table-block"[\s\S]*?\{itemText\(captionedTableLink\.caption\)\}[\s\S]*?<ContentItemView\s+item=\{primaryItem\}/,
  );
  assert.match(
    tableAuthority,
    /Object\.hasOwn\(item, "table_evidence"\)/,
  );
  assert.match(tableAuthority, /gate\?\.outcome === "canonical_table"/);
  assert.match(
    tableAuthority,
    /reasons\[0\] !== "upstream_reconciliation_unresolved"/,
  );
  assert.match(tableAuthority, /tableSupport < 0\.62/);
  assert.match(tableAuthority, /ownerIds\.length !== 0/);
  assert.match(
    canonicalRenderer,
    /return \(\s*<ContentItemView\s+key=\{block\.id\}\s+item=\{primaryItem\}\s+sourcePage=\{sourcePage\}\s+sourceSha256=\{sourceSha256\}\s*\/>\s*\);/,
  );
  assert.doesNotMatch(workspace, /dangerouslySetInnerHTML/);
});

test("one validated canonical page drives gating, source, copy, and download", () => {
  const selection = sourceSection(
    "const canonicalPresentation = useMemo",
    "const previewControlsDisabled",
  );
  const visibleOutput = sourceSection(
    "const visibleOutput = useMemo",
    "const resetPreviewScroll",
  );
  const copyOutput = sourceSection(
    "const copyOutput = async",
    "const downloadOutput",
  );
  const downloadOutput = sourceSection(
    "const downloadOutput",
    "const handleFormatKeyDown",
  );

  assert.match(selection, /readCanonicalPresentation\(result\)/);
  assert.match(
    selection,
    /findCanonicalPage\(canonicalPresentation, currentPage\)/,
  );
  assert.match(
    selection,
    /currentPageHasContent = canonicalPresentation\s*\?\s*currentCanonicalBlocks\.length > 0/,
  );

  assert.match(
    visibleOutput,
    /serializePageMarkdown\(currentPage, result\)/,
  );
  assert.match(workspace, /<MarkdownSource value=\{visibleOutput\} \/>/);
  assert.match(copyOutput, /navigator\.clipboard\.writeText\(visibleOutput\)/);
  assert.match(
    downloadOutput,
    /new Blob\(\[visibleOutput\], \{ type: mime \}\)/,
  );
  assert.match(
    workspace,
    /<CanonicalRenderedPage[\s\S]*?blocks=\{currentCanonicalBlocks\}/,
  );
});

test("an absent canonical contract retains the existing item renderer", () => {
  const legacyRenderer = sourceSection(
    "function RenderedPage",
    "function CanonicalRenderedPage",
  );

  assert.match(legacyRenderer, /page\.items/);
  assert.match(
    legacyRenderer,
    /<ContentItemView\s+key=\{item\.id\}\s+item=\{item\}\s+sourcePage=\{page\}\s+sourceSha256=\{sourceSha256\}\s*\/>/,
  );
  assert.match(
    workspace,
    /: currentPage \? \(\s*<RenderedPage\s+page=\{currentPage\}\s+sourceSha256=\{result\?\.document\.sha256 \?\? ""\}\s*\/>/,
  );
});
