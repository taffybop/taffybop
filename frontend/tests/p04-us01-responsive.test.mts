import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [css, workspace, tableSemantics] = await Promise.all([
  readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  readFile(
    new URL("../app/clearleaf-workspace.tsx", import.meta.url),
    "utf8",
  ),
  readFile(new URL("../lib/table-semantics.ts", import.meta.url), "utf8"),
]);

function bracedBlock(source: string, marker: string): string {
  const markerIndex = source.indexOf(marker);
  assert.notEqual(markerIndex, -1, `Expected source to contain ${marker}`);
  const openingBrace = source.indexOf("{", markerIndex + marker.length);
  assert.notEqual(openingBrace, -1, `Expected ${marker} to open a block`);
  let depth = 0;
  for (let index = openingBrace; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(openingBrace + 1, index);
    }
  }
  assert.fail(`Expected ${marker} to close its block`);
}

function cssRule(source: string, selector: string): string {
  let fromIndex = 0;
  while (fromIndex < source.length) {
    const selectorIndex = source.indexOf(selector, fromIndex);
    assert.notEqual(selectorIndex, -1, `Expected CSS rule for ${selector}`);
    let afterIndex = selectorIndex + selector.length;
    while (afterIndex < source.length && /\s/u.test(source[afterIndex] ?? "")) {
      afterIndex += 1;
    }
    const following = source[afterIndex];
    const lineStart = source.lastIndexOf("\n", selectorIndex) + 1;
    const beginsSelector = source.slice(lineStart, selectorIndex).trim() === "";
    const endsSelector = following === "{" || following === ",";
    if (beginsSelector && endsSelector) {
      return bracedBlock(source.slice(selectorIndex), selector);
    }
    fromIndex = selectorIndex + selector.length;
  }
  assert.fail(`Expected CSS rule for ${selector}`);
}

function sourceSection(start: string, end: string): string {
  const startIndex = workspace.indexOf(start);
  const endIndex = workspace.indexOf(end, startIndex + start.length);
  assert.notEqual(startIndex, -1, `Expected workspace source to contain ${start}`);
  assert.notEqual(endIndex, -1, `Expected workspace source to contain ${end}`);
  return workspace.slice(startIndex, endIndex);
}

const compact = bracedBlock(css, "@media (max-width: 1180px)");
const tablet = bracedBlock(css, "@media (max-width: 900px)");
const mobile = bracedBlock(css, "@media (max-width: 620px)");
const reducedMotion = bracedBlock(
  css,
  "@media (prefers-reduced-motion: reduce)",
);
const tableRenderer = sourceSection(
  "  const tableAuthority = tableItemAuthority(item);",
  '  if (type === "list") {',
);

test("desktop bounds the application and pane rows to the dynamic viewport", () => {
  const root = cssRule(css, ".clearleaf-app");
  const main = cssRule(css, ".app-main");
  const shell = cssRule(css, ".workspace-shell");
  const panel = cssRule(css, ".workspace-panel");
  const resultPanel = cssRule(css, ".result-panel");

  assert.match(root, /height:\s*100vh\s*;/u);
  assert.match(root, /height:\s*100dvh\s*;/u);
  assert.match(root, /min-height:\s*0\s*;/u);
  assert.match(root, /overflow:\s*hidden\s*;/u);
  assert.match(main, /min-height:\s*0\s*;/u);
  assert.match(main, /overflow:\s*hidden\s*;/u);
  assert.match(shell, /grid-template-rows:\s*48px\s+minmax\(0,\s*1fr\)\s*;/u);
  assert.match(shell, /overflow:\s*hidden\s*;/u);
  assert.match(panel, /grid-template-rows:\s*62px\s+minmax\(0,\s*1fr\)\s+40px\s*;/u);
  assert.match(
    resultPanel,
    /grid-template-rows:\s*62px\s+auto\s+minmax\(0,\s*1fr\)\s+40px\s*;/u,
  );
});

test("desktop split tracks cannot force either pane beyond the viewport", () => {
  const split = cssRule(css, ".workspace");
  const panel = cssRule(css, ".workspace-panel");

  assert.match(split, /--workspace-split:\s*52%\s*;/u);
  assert.match(
    split,
    /grid-template-columns:\s*minmax\(0,\s*var\(--workspace-split\)\)\s*9px\s*minmax\(0,\s*calc\(100%\s*-\s*var\(--workspace-split\)\s*-\s*9px\)\)\s*;/u,
  );
  assert.match(panel, /min-width:\s*0\s*;/u);
  assert.match(panel, /min-height:\s*0\s*;/u);
});

test("preview and results retain independent two-axis scrolling", () => {
  const preview = cssRule(css, ".pdf-canvas");
  const results = cssRule(css, ".result-body");

  for (const rule of [preview, results]) {
    assert.match(rule, /min-height:\s*0\s*;/u);
    assert.match(rule, /overflow:\s*auto\s*;/u);
    assert.match(rule, /overscroll-behavior:\s*contain\s*;/u);
  }
  assert.match(preview, /min-width:\s*0\s*;/u);
});

test("wide tables are horizontally contained by their own wrapper", () => {
  const wrapper = cssRule(css, ".parsed-table-wrap");

  assert.match(wrapper, /max-width:\s*100%\s*;/u);
  assert.match(wrapper, /overflow-x:\s*auto\s*;/u);
  assert.doesNotMatch(wrapper, /overflow(?:-x)?:\s*(?:hidden|clip)\s*;/u);
});

test("dense tables preserve a readable intrinsic width inside containment", () => {
  const table = cssRule(css, ".parsed-table");

  assert.match(table, /width:\s*100%\s*;/u);
  assert.match(table, /min-width:\s*520px\s*;/u);
  assert.match(table, /border-collapse:\s*collapse\s*;/u);
  assert.match(table, /font-size:\s*13px\s*;/u);
});

test("explicit line breaks and ordinary wrapping survive in every table path", () => {
  const cells = cssRule(css, ".parsed-table th");

  assert.match(cells, /white-space:\s*pre-line\s*;/u);
  assert.match(
    tableRenderer,
    /style=\{\{\s*whiteSpace:\s*"pre-wrap"\s*\}\}/u,
  );
  assert.doesNotMatch(cells, /white-space:\s*nowrap\s*;/u);
});

test("table cells remain top-aligned and legible when rows grow", () => {
  const cells = cssRule(css, ".parsed-table th");

  assert.match(cells, /padding:\s*11px\s+13px\s*;/u);
  assert.match(cells, /line-height:\s*1\.45\s*;/u);
  assert.match(cells, /text-align:\s*left\s*;/u);
  assert.match(cells, /vertical-align:\s*top\s*;/u);
});

test("1180px compacts secondary labels without hiding table content", () => {
  const compactLabels = cssRule(compact, ".header-file em");
  const action = cssRule(compact, ".action-with-label");

  assert.match(compactLabels, /display:\s*none\s*;/u);
  assert.match(action, /width:\s*34px\s*;/u);
  assert.match(action, /padding:\s*0\s*;/u);
  assert.doesNotMatch(compact, /\.parsed-table(?:-wrap)?[^}]*display:\s*none/u);
});

test("900px exposes the two mobile pane tabs", () => {
  const tabs = cssRule(tablet, ".mobile-view-tabs");

  assert.match(tabs, /display:\s*grid\s*;/u);
  assert.match(tabs, /height:\s*48px\s*;/u);
  assert.match(tabs, /grid-template-columns:\s*1fr\s+1fr\s*;/u);
});

test("900px shows only the selected pane and removes the splitter", () => {
  const workspaceRule = cssRule(tablet, ".workspace");
  const inactivePanel = cssRule(tablet, ".workspace-panel");
  const activePanel = cssRule(tablet, ".workspace-panel.mobile-active");
  const divider = cssRule(tablet, ".panel-divider");

  assert.match(workspaceRule, /display:\s*block\s*;/u);
  assert.match(inactivePanel, /display:\s*none\s*;/u);
  assert.match(activePanel, /display:\s*grid\s*;/u);
  assert.match(divider, /display:\s*none\s*;/u);
});

test("900px keeps tabs, page identity, and active pane in bounded rows", () => {
  const shell = cssRule(tablet, ".workspace-shell");

  assert.match(
    shell,
    /grid-template-rows:\s*48px\s+48px\s+minmax\(0,\s*1fr\)\s*;/u,
  );
});

test("620px stacks navigation while preserving printed-page identity", () => {
  const pagebar = cssRule(mobile, ".workspace-pagebar");
  const navigator = cssRule(mobile, ".workspace-pagebar .page-navigator");
  const printedLabel = cssRule(
    mobile,
    ".workspace-pagebar .printed-page-label",
  );

  assert.match(pagebar, /grid-template-columns:\s*1fr\s*;/u);
  assert.match(navigator, /max-width:\s*100%\s*;/u);
  assert.match(navigator, /flex-wrap:\s*wrap\s*;/u);
  assert.match(printedLabel, /max-width:\s*100%\s*;/u);
  assert.match(printedLabel, /text-overflow:\s*ellipsis\s*;/u);
  assert.doesNotMatch(printedLabel, /display:\s*none\s*;/u);
});

test("620px gives rendered output safe gutters without widening tables", () => {
  const renderedPage = cssRule(mobile, ".rendered-page");
  const wrapper = cssRule(css, ".parsed-table-wrap");

  assert.match(renderedPage, /width:\s*min\(100%\s*-\s*32px,\s*820px\)\s*;/u);
  assert.match(renderedPage, /padding-top:\s*28px\s*;/u);
  assert.match(wrapper, /max-width:\s*100%\s*;/u);
  assert.match(wrapper, /overflow-x:\s*auto\s*;/u);
});

test("mobile pane controls are a state-bound accessible tablist", () => {
  const tabs = sourceSection(
    '<div className="mobile-view-tabs"',
    '<div className="workspace-pagebar">',
  );

  assert.match(tabs, /role="tablist"\s+aria-label="Workspace pane"/u);
  assert.equal((tabs.match(/role="tab"/gu) ?? []).length, 2);
  assert.match(tabs, /aria-selected=\{mobilePane === "document"\}/u);
  assert.match(tabs, /onClick=\{\(\) => setMobilePane\("document"\)\}/u);
  assert.match(tabs, /aria-selected=\{mobilePane === "results"\}/u);
  assert.match(tabs, /onClick=\{\(\) => setMobilePane\("results"\)\}/u);
});

test("result-format tabs expose ownership, selection, and keyboard switching", () => {
  const tabs = sourceSection(
    '<div className="format-tabs"',
    '<div className="toolbar-actions result-actions">',
  );
  const keyboard = sourceSection(
    "const handleFormatKeyDown",
    "const selectFormat",
  );

  assert.match(tabs, /role="tablist"\s+aria-label="Result format"/u);
  assert.equal((tabs.match(/role="tab"/gu) ?? []).length, 2);
  assert.equal((tabs.match(/aria-controls="result-tabpanel"/gu) ?? []).length, 2);
  assert.match(tabs, /tabIndex=\{format === "markdown" \? 0 : -1\}/u);
  assert.match(tabs, /tabIndex=\{format === "json" \? 0 : -1\}/u);
  assert.match(keyboard, /\["ArrowLeft", "ArrowRight"\]\.includes\(event\.key\)/u);
  assert.match(keyboard, /document\.getElementById\(`format-tab-\$\{nextFormat\}`\)\?\.focus\(\)/u);
});

test("page navigation announces physical and printed identities", () => {
  const navigator = sourceSection(
    "function PageNavigator",
    "export function TaffyBopWorkspace",
  );

  assert.match(navigator, /<nav className="page-navigator" aria-label="Document pages">/u);
  assert.match(navigator, /className="page-readout" aria-live="polite"/u);
  assert.match(navigator, /min=\{1\}/u);
  assert.match(navigator, /max=\{pageCount\}/u);
  assert.match(navigator, /aria-label="Current page number"/u);
  assert.match(navigator, /Printed <bdi dir="auto">\{displayLabel\}<\/bdi>/u);
});

test("validated tables retain policy identity and structural row groups", () => {
  const trusted = tableRenderer.slice(
    tableRenderer.indexOf("const tableSemantics ="),
    tableRenderer.indexOf("const rows = item.rows ?? []"),
  );

  assert.match(workspace, /import \{ readTableSemantics \} from "@\/lib\/table-semantics";/u);
  assert.match(trusted, /readTableSemantics\(item, tableContext\)/u);
  assert.match(trusted, /data-table-policy=\{tableSemantics\.policyId\}/u);
  assert.match(trusted, /data-table-id=\{tableSemantics\.tableId\}/u);
  assert.match(trusted, /<table className="parsed-table">/u);
  assert.match(trusted, /<thead>/u);
  assert.match(trusted, /<tbody>/u);
  assert.match(tableSemantics, /policyId:\s*"p04-table-evidence-v1"/u);
});

test("validated table cells preserve header scope, spans, and stable identity", () => {
  const trusted = tableRenderer.slice(
    tableRenderer.indexOf("const renderSemanticCell"),
    tableRenderer.indexOf("const headerRows"),
  );

  assert.match(trusted, /cell\.columnHeader \|\| cell\.rowHeader \? "th" : "td"/u);
  assert.match(trusted, /cell\.columnHeader\s*\? "col"\s*:\s*cell\.rowHeader\s*\? "row"/u);
  assert.match(trusted, /colSpan=\{cell\.colSpan\}/u);
  assert.match(trusted, /rowSpan=\{cell\.rowSpan\}/u);
  assert.match(trusted, /data-cell-id=\{cell\.id\}/u);
  assert.match(trusted, /data-source=\{cell\.source\}/u);
  assert.match(trusted, /\{cell\.text\}/u);
});

test("predecessor fallback remains a semantic table instead of flattened prose", () => {
  const fallback = tableRenderer.slice(
    tableRenderer.indexOf("const rows = item.rows ?? []"),
  );

  assert.match(fallback, /if \(!rows\.length\) return null/u);
  assert.match(fallback, /<table className="parsed-table">/u);
  assert.match(fallback, /<thead>[\s\S]*?<th/u);
  assert.match(fallback, /<tbody>[\s\S]*?<td/u);
  assert.match(fallback, /const bodyStart = hasSpanningTitle \? 2 : 1/u);
  assert.match(fallback, /rows\.slice\(bodyStart\)\.map/u);
  assert.match(fallback, /<th colSpan=\{columnCount\}>\{rows\[0\]\[0\]\}<\/th>/u);
  assert.doesNotMatch(fallback, /item\.(?:html|md|csv)/u);
});

test("hostile cell text stays inert React text in both table paths", () => {
  assert.match(tableRenderer, /\{cell\.text\}/u);
  assert.match(tableRenderer, /\? renderValidatedTextRunOverlay\([\s\S]*?\) \?\? cell\s*:\s*cell/u);
  assert.doesNotMatch(tableRenderer, /dangerouslySetInnerHTML/u);
  assert.doesNotMatch(tableRenderer, /(?:innerHTML|outerHTML)\s*=/u);
  assert.doesNotMatch(tableRenderer, /tableSemantics\.(?:html|markdown|csv)/u);
});

test("copy and download export the same serializer-owned output, not responsive DOM", () => {
  const visible = sourceSection(
    "const visibleOutput = useMemo",
    "const resetPreviewScroll",
  );
  const exports = sourceSection(
    "const copyOutput = async",
    "const handleFormatKeyDown",
  );

  assert.match(visible, /if \(format === "json"\) return documentJsonOutput/u);
  assert.match(visible, /serializePageMarkdown\(currentPage, result/u);
  assert.match(exports, /navigator\.clipboard\.writeText\(visibleOutput\)/u);
  assert.match(exports, /new Blob\(\[visibleOutput\], \{ type: mime \}\)/u);
  assert.match(exports, /format === "json"\s*\? "application\/json"\s*:\s*"text\/markdown;charset=utf-8"/u);
  assert.doesNotMatch(exports, /innerHTML|outerHTML|querySelector/u);
});

test("reduced-motion users keep immediate scrolling and bounded animation", () => {
  assert.match(reducedMotion, /scroll-behavior:\s*auto\s*!important\s*;/u);
  assert.match(reducedMotion, /animation-duration:\s*0\.01ms\s*!important\s*;/u);
  assert.match(reducedMotion, /animation-iteration-count:\s*1\s*!important\s*;/u);
  assert.match(reducedMotion, /transition-duration:\s*0\.01ms\s*!important\s*;/u);
});
