import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createKnowledgePack,
  DEFAULT_PACK_OPTIONS,
  knowledgePackJsonl,
  type SourceDocument,
} from "../lib/knowledge-pack.ts";
import {
  extractBrowserDocument,
  extractBrowserDocuments,
  MAX_FILE_BYTES,
  validateKnowledgeFile,
} from "../lib/browser-extract.ts";

const source = (pages: string[], name = "guide.pdf"): SourceDocument => ({
  id: `test-${name}`,
  name,
  pages: pages.map((text, index) => ({ number: index + 1, text })),
  warnings: [],
});

test("chunk windows cover every source word, preserve order, and overlap exactly", () => {
  for (const length of [1, 39, 40, 41, 79, 80, 81, 101, 379]) {
    for (const overlap of [0, 7, 39]) {
      const words = Array.from({ length }, (_, index) => `word-${index}`);
      const pack = createKnowledgePack([source([words.join("\n")])], {
        chunkSize: 40, overlap, removeRepeatedHeaders: false,
      });
      let recovered: string[] = [];
      pack.chunks.forEach((chunk, index) => {
        const current = chunk.text.split(" ");
        assert.ok(chunk.words <= 40);
        assert.equal(chunk.words, current.length);
        if (index > 0) {
          assert.deepEqual(current.slice(0, overlap), recovered.slice(recovered.length - overlap || recovered.length));
        }
        recovered = recovered.concat(index === 0 ? current : current.slice(overlap));
      });
      assert.deepEqual(recovered, words, `length=${length}, overlap=${overlap}`);
      assert.equal(pack.stats.words, length);
    }
  }
});

test("chunks stay inside physical pages and carry stable source citations", () => {
  const documents = [source(["First page: café 🪄 naïve.", "第二页 has different content."] )];
  const pack = createKnowledgePack(documents);
  assert.deepEqual(pack.chunks.map(({ page, pageEnd, citation }) => ({ page, pageEnd, citation })), [
    { page: 1, pageEnd: 1, citation: "guide.pdf · p. 1" },
    { page: 2, pageEnd: 2, citation: "guide.pdf · p. 2" },
  ]);
  assert.deepEqual(createKnowledgePack(documents).chunks, pack.chunks);
  assert.equal(new Set(pack.chunks.map((chunk) => chunk.id)).size, 2);
  assert.match(pack.markdown, /café 🪄 naïve/u);
  assert.match(pack.markdown, /第二页/u);
});

test("repeated boundary cleanup is optional, conservative, and never erases a page", () => {
  const doc = source([
    "Company handbook\nUnique policy one\nPage 1 of 3",
    "Company handbook\nUnique policy two\nPage 2 of 3",
    "Company handbook\nUnique policy three\nPage 3 of 3",
  ]);
  const untouched = createKnowledgePack([doc]);
  assert.equal(untouched.stats.removedHeaderLines, 0);
  assert.match(untouched.markdown, /Company handbook/u);
  const cleaned = createKnowledgePack([doc], { ...DEFAULT_PACK_OPTIONS, removeRepeatedHeaders: true });
  assert.equal(cleaned.stats.removedHeaderLines, 6);
  assert.equal(cleaned.stats.words, 9);
  assert.doesNotMatch(cleaned.markdown, /Company handbook/u);
  assert.equal(cleaned.warnings.length, 1);
  assert.deepEqual(doc.pages.map((page) => page.text), [
    "Company handbook\nUnique policy one\nPage 1 of 3",
    "Company handbook\nUnique policy two\nPage 2 of 3",
    "Company handbook\nUnique policy three\nPage 3 of 3",
  ]);
  const identical = source(Array(3).fill("Only header\nOnly footer"));
  assert.equal(createKnowledgePack([identical], { ...DEFAULT_PACK_OPTIONS, removeRepeatedHeaders: true }).stats.removedHeaderLines, 0);
  const short = source(["Repeated\nBody one", "Repeated\nBody two"]);
  assert.equal(createKnowledgePack([short], { ...DEFAULT_PACK_OPTIONS, removeRepeatedHeaders: true }).stats.removedHeaderLines, 0);
});

test("JSONL is parseable and preserves quotes, newlines, and Unicode as data", () => {
  const pack = createKnowledgePack([source(['<script>alert("x")</script>\nUnicode: 日本語'], 'a"b.pdf')]);
  const rows = knowledgePackJsonl(pack).trim().split("\n").map((line) => JSON.parse(line));
  assert.equal(rows.length, 1);
  assert.equal(rows[0].text, '<script>alert("x")</script> Unicode: 日本語');
  assert.equal(rows[0].metadata.source, 'a"b.pdf');
  assert.equal(rows[0].metadata.page, 1);
  assert.equal(rows[0].metadata.words, pack.chunks[0].words);
});

test("invalid settings fail instead of looping or silently changing requested chunk sizes", () => {
  for (const chunkSize of [0, -1, 39, 1001, NaN, 40.2]) {
    assert.throws(() => createKnowledgePack([], { ...DEFAULT_PACK_OPTIONS, chunkSize }), /Chunk size/u);
  }
  for (const overlap of [-1, 180, NaN, 0.5]) {
    assert.throws(() => createKnowledgePack([], { ...DEFAULT_PACK_OPTIONS, overlap }), /Overlap/u);
  }
});

test("empty pages retain page numbering without generating invented text chunks", () => {
  const pack = createKnowledgePack([source(["", "Actual content", " \n "])]);
  assert.equal(pack.chunks.length, 1);
  assert.equal(pack.chunks[0].page, 2);
  assert.equal(pack.stats.pages, 3);
  assert.equal(pack.stats.words, 2);
  assert.match(pack.markdown, /## Page 3/u);
});

test("duplicate source IDs and invalid page numbers cannot produce ambiguous citations", () => {
  const doc = source(["Some text"]);
  assert.throws(() => createKnowledgePack([doc, doc]), /Duplicate document/u);
  assert.throws(() => createKnowledgePack([{ ...doc, pages: [{ number: 0, text: "bad" }] }]), /page numbers/u);
  assert.throws(() => createKnowledgePack([{ ...doc, pages: [doc.pages[0], doc.pages[0]] }]), /page numbers/u);
});

test("UTF-8 text imports feed real content into a downloadable knowledge pack", async () => {
  const file = new File(["Support policy\nRefunds are available for 30 days.\nContact: 日本語"], "policy.md");
  const updates: string[] = [];
  const document = await extractBrowserDocument(file, (message) => updates.push(message));
  const second = await extractBrowserDocument(file);
  assert.equal(document.id, second.id);
  assert.deepEqual(document.pages, second.pages);
  assert.equal(document.name, "policy.md");
  assert.equal(document.pages[0].text, await file.text());
  assert.ok(updates.some((message) => message.includes("policy.md")));
  const pack = createKnowledgePack([document]);
  assert.match(pack.chunks[0].text, /Refunds are available for 30 days/u);
  assert.equal(JSON.parse(knowledgePackJsonl(pack)).metadata.source, "policy.md");
});

test("import validation rejects unsupported, empty, oversized, binary, and invalid UTF-8 files", async () => {
  assert.throws(() => validateKnowledgeFile({ name: "photo.png", size: 12 }), /PDF, TXT, or Markdown/u);
  assert.throws(() => validateKnowledgeFile({ name: "empty.txt", size: 0 }), /empty/u);
  assert.throws(() => validateKnowledgeFile({ name: "huge.pdf", size: MAX_FILE_BYTES + 1 }), /20 MB/u);
  await assert.rejects(extractBrowserDocument(new File(["  \n"], "blank.txt")), /no readable text/u);
  await assert.rejects(extractBrowserDocument(new File([new Uint8Array([0xff, 0xfe, 0x01])], "bad.txt")), /UTF-8/u);
  await assert.rejects(extractBrowserDocument(new File(["text\u0000binary"], "binary.md")), /binary file/u);
  await assert.rejects(extractBrowserDocument(new File(["Not really a PDF"], "wrong.pdf")), /valid PDF header/u);
});

test("batch import enforces its documented limits before processing any file", async () => {
  await assert.rejects(extractBrowserDocuments([]), /at least one/u);
  const file = new File(["hello"], "hello.txt");
  await assert.rejects(extractBrowserDocuments(Array(11).fill(file)), /up to 10/u);
  const documents = await extractBrowserDocuments([file, new File(["world"], "world.md")]);
  assert.equal(documents.length, 2);
  assert.deepEqual(documents.map((document) => document.pages[0].text), ["hello", "world"]);
});
