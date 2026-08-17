import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(
  new URL("../app/globals.css", import.meta.url),
  "utf8",
);

test("workspace root has a definite viewport height", () => {
  const rootRule = css.match(/\.clearleaf-app\s*\{([^}]*)\}/)?.[1];
  const workspaceShellRule = css.match(
    /\.workspace-shell\s*\{([^}]*)\}/,
  )?.[1];

  assert.ok(rootRule, "Expected a .clearleaf-app CSS rule");
  assert.ok(workspaceShellRule, "Expected a .workspace-shell CSS rule");
  assert.match(rootRule, /height:\s*100vh\s*;/);
  assert.match(rootRule, /height:\s*100dvh\s*;/);
  assert.match(rootRule, /min-height:\s*0\s*;/);
  assert.match(rootRule, /grid-template-rows:\s*68px\s+minmax\(0,\s*1fr\)\s*;/);
  assert.match(
    workspaceShellRule,
    /grid-template-rows:\s*48px\s+minmax\(0,\s*1fr\)\s*;/,
  );
  assert.doesNotMatch(workspaceShellRule, /grid-template-rows:\s*auto\s+48px/);
});

test("preview and result panes retain independent scrollable content rows", () => {
  const previewRule = css.match(/\.pdf-canvas\s*\{([^}]*)\}/)?.[1];
  const imagePreviewRule = css.match(
    /\.image-page-preview\s*\{([^}]*)\}/,
  )?.[1];
  const imageRule = css.match(/\.image-preview\s*\{([^}]*)\}/)?.[1];
  const resultRule = css.match(/\.result-body\s*\{([^}]*)\}/)?.[1];

  assert.ok(previewRule, "Expected a .pdf-canvas CSS rule");
  assert.ok(imagePreviewRule, "Expected an .image-page-preview CSS rule");
  assert.ok(imageRule, "Expected an .image-preview CSS rule");
  assert.ok(resultRule, "Expected a .result-body CSS rule");
  assert.match(previewRule, /min-height:\s*0\s*;/);
  assert.match(previewRule, /overflow:\s*auto\s*;/);
  assert.match(imagePreviewRule, /min-height:\s*100%\s*;/);
  assert.match(imageRule, /height:\s*auto\s*;/);
  assert.match(imageRule, /max-width:\s*none\s*;/);
  assert.match(resultRule, /min-height:\s*0\s*;/);
  assert.match(resultRule, /overflow:\s*auto\s*;/);
});

test("complete JSON keeps a continuous result scroll with readable code rows", () => {
  const documentJsonRule = css.match(
    /\.document-json-view\s*\{([^}]*)\}/,
  )?.[1];
  const codeViewRule = css.match(/\.json-code-view\s*\{([^}]*)\}/)?.[1];
  const codeLineRule = css.match(/\.json-code-line\s*\{([^}]*)\}/)?.[1];

  assert.ok(documentJsonRule, "Expected a .document-json-view CSS rule");
  assert.ok(codeViewRule, "Expected a .json-code-view CSS rule");
  assert.ok(codeLineRule, "Expected a .json-code-line CSS rule");
  assert.match(documentJsonRule, /min-height:\s*100%\s*;/);
  assert.match(codeViewRule, /overflow-x:\s*auto\s*;/);
  assert.match(
    codeLineRule,
    /grid-template-columns:\s*48px\s+22px\s+minmax\(max-content,\s*1fr\)\s*;/,
  );
});

test("mobile layout keeps tabs, page navigation, and content in three rows", () => {
  assert.match(
    css,
    /@media\s*\(max-width:\s*900px\)[\s\S]*?\.workspace-shell\s*\{[\s\S]*?grid-template-rows:\s*48px\s+48px\s+minmax\(0,\s*1fr\)\s*;/,
  );
});

test("responsive page navigation keeps printed page identity visible", () => {
  const compactRule = css.match(
    /@media\s*\(max-width:\s*1180px\)\s*\{([\s\S]*?)\n\}/,
  )?.[1];
  const mobileRule = css.match(
    /@media\s*\(max-width:\s*620px\)\s*\{([\s\S]*?)\n\}/,
  )?.[1];

  assert.ok(compactRule, "Expected the compact workspace media query");
  assert.doesNotMatch(
    compactRule,
    /\.printed-page-label[\s\S]*?display:\s*none\s*;/,
  );
  assert.ok(mobileRule, "Expected the mobile workspace media query");
  assert.match(
    mobileRule,
    /\.workspace-pagebar\s+\.page-navigator\s*\{[\s\S]*?flex-wrap:\s*wrap\s*;/,
  );
  assert.match(
    mobileRule,
    /\.workspace-pagebar\s+\.printed-page-label\s*\{[\s\S]*?text-overflow:\s*ellipsis\s*;/,
  );
});
