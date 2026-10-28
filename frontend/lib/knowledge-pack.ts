/** A deterministic, browser-safe preparation step. Sizes are whitespace-delimited words. */
export interface SourcePage {
  number: number;
  text: string;
}

export interface SourceDocument {
  id: string;
  name: string;
  pages: SourcePage[];
  warnings: string[];
}

export interface KnowledgePackOptions {
  chunkSize: number;
  overlap: number;
  removeRepeatedHeaders: boolean;
}

export interface KnowledgeChunk {
  id: string;
  text: string;
  source: string;
  sourceId: string;
  page: number;
  pageEnd: number;
  words: number;
  chars: number;
  citation: string;
}

export interface KnowledgePack {
  chunks: KnowledgeChunk[];
  markdown: string;
  stats: {
    documents: number;
    pages: number;
    words: number;
    chunks: number;
    removedHeaderLines: number;
  };
  warnings: string[];
}

export const DEFAULT_PACK_OPTIONS: KnowledgePackOptions = {
  chunkSize: 180,
  overlap: 30,
  removeRepeatedHeaders: false,
};

export function countWords(text: string): number {
  return text.match(/\S+/gu)?.length ?? 0;
}

function stableHash(value: string): string {
  let first = 2166136261;
  let second = 3339675911;
  for (let index = 0; index < value.length; index += 1) {
    const character = value.charCodeAt(index);
    first = Math.imul(first ^ character, 16777619);
    second = Math.imul(second ^ character, 2246822519);
  }
  return (first >>> 0).toString(16).padStart(8, "0") +
    (second >>> 0).toString(16).padStart(8, "0");
}

function normalizedLines(text: string): string[] {
  return text.replace(/\r\n?/gu, "\n").split("\n");
}

function boundaryKey(line: string, edge: "first" | "last"): string | null {
  const clean = line.trim().replace(/\s+/gu, " ");
  if (clean.length < 4 || clean.length > 140) return null;
  if (edge === "last" && /^page\s+\d+(?:\s+(?:of|\/)\s+\d+)?$/iu.test(clean)) {
    return "__page_number_footer__";
  }
  return clean;
}

/** Only repeated boundary lines on at least three pages can be removed. */
function cleanPageBoundaries(document: SourceDocument): {
  pages: SourcePage[];
  removed: number;
} {
  const candidates = document.pages.map((page) => {
    const lines = normalizedLines(page.text);
    const first = lines.findIndex((line) => line.trim().length > 0);
    let last = lines.length - 1;
    while (last >= 0 && !lines[last].trim()) last -= 1;
    return { page, lines, first, last };
  });
  const counts = { first: new Map<string, number>(), last: new Map<string, number>() };
  const nonemptyPages = candidates.filter(({ first }) => first >= 0).length;
  const threshold = Math.max(3, Math.ceil(nonemptyPages * 0.6));
  for (const candidate of candidates) {
    if (candidate.first < 0 || candidate.first === candidate.last) continue;
    for (const edge of ["first", "last"] as const) {
      const key = boundaryKey(candidate.lines[candidate[edge]], edge);
      if (key) counts[edge].set(key, (counts[edge].get(key) ?? 0) + 1);
    }
  }
  let removed = 0;
  const pages = candidates.map(({ page, lines, first, last }) => {
    const remove = new Set<number>();
    if (first >= 0 && first !== last) {
      for (const edge of ["first", "last"] as const) {
        const index = edge === "first" ? first : last;
        const key = boundaryKey(lines[index], edge);
        if (key && (counts[edge].get(key) ?? 0) >= threshold) remove.add(index);
      }
    }
    const cleaned = lines.filter((_, index) => !remove.has(index)).join("\n");
    // Never erase the only content of a page, even if all boundary text repeats.
    if (!cleaned.trim()) return { ...page, text: lines.join("\n") };
    removed += remove.size;
    return { ...page, text: cleaned };
  });
  return { pages, removed };
}

function markdownHeading(value: string): string {
  return value.replace(/[\r\n]+/gu, " ").replace(/[\\`*_{}\[\]<>#]/gu, "\\$&");
}

export function createKnowledgePack(
  documents: SourceDocument[],
  options: KnowledgePackOptions = DEFAULT_PACK_OPTIONS,
): KnowledgePack {
  if (!Number.isInteger(options.chunkSize) || options.chunkSize < 40 || options.chunkSize > 1000) {
    throw new Error("Chunk size must be a whole number between 40 and 1,000 words.");
  }
  if (!Number.isInteger(options.overlap) || options.overlap < 0 || options.overlap >= options.chunkSize) {
    throw new Error("Overlap must be a whole number from 0 to one less than the chunk size.");
  }
  const chunks: KnowledgeChunk[] = [];
  const markdown: string[] = [];
  const warnings: string[] = [];
  const stats = { documents: documents.length, pages: 0, words: 0, chunks: 0, removedHeaderLines: 0 };
  const documentIds = new Set<string>();
  for (const document of documents) {
    if (!document.id || !document.name || !Array.isArray(document.pages)) {
      throw new Error("Each document needs an ID, filename, and pages.");
    }
    if (documentIds.has(document.id)) throw new Error(`Duplicate document: ${document.name}.`);
    documentIds.add(document.id);
    const pageNumbers = new Set<number>();
    for (const page of document.pages) {
      if (!Number.isInteger(page.number) || page.number < 1 || pageNumbers.has(page.number) || typeof page.text !== "string") {
        throw new Error(`${document.name} has invalid or duplicate page numbers.`);
      }
      pageNumbers.add(page.number);
    }
    warnings.push(...document.warnings);
    const cleaned = options.removeRepeatedHeaders
      ? cleanPageBoundaries(document)
      : { pages: document.pages, removed: 0 };
    stats.removedHeaderLines += cleaned.removed;
    if (cleaned.removed > 0) {
      warnings.push(`${document.name}: removed ${cleaned.removed} repeated page-boundary lines. Review the result before importing.`);
    }
    markdown.push(`# ${markdownHeading(document.name)}`);
    for (const page of cleaned.pages) {
      stats.pages += 1;
      const text = page.text.replace(/\r\n?/gu, "\n").trim();
      const words = text.match(/\S+/gu) ?? [];
      stats.words += words.length;
      if (words.length === 0) {
        markdown.push(`## Page ${page.number}\n\n[No extractable text on this page.]`);
        continue;
      }
      markdown.push(`## Page ${page.number}\n\n${text}`);
      let start = 0;
      while (start < words.length) {
        const end = Math.min(start + options.chunkSize, words.length);
        const chunkText = words.slice(start, end).join(" ");
        chunks.push({
          id: `chunk-${stableHash(`${document.id}:${page.number}:${start}:${end}:${chunkText}`)}`,
          text: chunkText,
          source: document.name,
          sourceId: document.id,
          page: page.number,
          pageEnd: page.number,
          words: end - start,
          chars: chunkText.length,
          citation: `${document.name} · p. ${page.number}`,
        });
        if (end === words.length) break;
        start = end - options.overlap;
      }
    }
  }
  stats.chunks = chunks.length;
  return { chunks, markdown: markdown.join("\n\n") + (markdown.length ? "\n" : ""), stats, warnings: [...new Set(warnings)] };
}

/** One valid JSON object per line, with source metadata ready for a retrieval pipeline. */
export function knowledgePackJsonl(pack: KnowledgePack): string {
  return pack.chunks.map((chunk) => JSON.stringify({
    id: chunk.id,
    text: chunk.text,
    metadata: {
      source: chunk.source,
      source_id: chunk.sourceId,
      page: chunk.page,
      page_end: chunk.pageEnd,
      citation: chunk.citation,
      words: chunk.words,
      characters: chunk.chars,
    },
  })).join("\n") + (pack.chunks.length ? "\n" : "");
}
