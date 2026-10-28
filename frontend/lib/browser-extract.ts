import type { SourceDocument, SourcePage } from "./knowledge-pack";

export const MAX_FILES = 10;
export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_PDF_PAGES = 200;
export const MAX_EXTRACTED_CHARACTERS = 2_000_000;
export const KNOWLEDGE_FILE_ACCEPT = ".pdf,.txt,.md,.markdown,application/pdf,text/plain,text/markdown";

type ExtractionProgress = (message: string) => void;

export function validateKnowledgeFile(file: Pick<File, "name" | "size">): "pdf" | "text" {
  if (!/\.(pdf|txt|md|markdown)$/iu.test(file.name)) {
    throw new Error(`${file.name}: choose a PDF, TXT, or Markdown file.`);
  }
  if (file.size === 0) throw new Error(`${file.name}: this file is empty.`);
  if (file.size > MAX_FILE_BYTES) throw new Error(`${file.name}: files must be 20 MB or smaller.`);
  return /\.pdf$/iu.test(file.name) ? "pdf" : "text";
}

function ensureTextBudget(length: number, name: string): void {
  if (length > MAX_EXTRACTED_CHARACTERS) {
    throw new Error(`${name}: this document exceeds the 2 million character limit. Split it into smaller documents; no content has been truncated.`);
  }
}

async function documentId(bytes: Uint8Array, name: string): Promise<string> {
  // Include the name so two differently named sources keep their own citations.
  const nameBytes = new TextEncoder().encode(name);
  const combined = new Uint8Array(bytes.length + nameBytes.length);
  combined.set(bytes);
  combined.set(nameBytes, bytes.length);
  const digest = await crypto.subtle.digest("SHA-256", combined);
  return `doc-${Array.from(new Uint8Array(digest)).map((byte) => byte.toString(16).padStart(2, "0")).join("").slice(0, 24)}`;
}

export async function extractBrowserDocument(
  file: File,
  onProgress?: ExtractionProgress,
): Promise<SourceDocument> {
  const kind = validateKnowledgeFile(file);
  onProgress?.(`Reading ${file.name}…`);
  const bytes = new Uint8Array(await file.arrayBuffer());
  const id = await documentId(bytes, file.name);
  const warnings: string[] = [];
  if (kind === "text") {
    let text: string;
    try {
      text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    } catch {
      throw new Error(`${file.name}: save this text file as UTF-8 and try again.`);
    }
    if (/\u0000/u.test(text)) throw new Error(`${file.name}: this appears to be a binary file, not UTF-8 text.`);
    if (!text.trim()) throw new Error(`${file.name}: this file contains no readable text.`);
    ensureTextBudget(text.length, file.name);
    return { id, name: file.name, pages: [{ number: 1, text }], warnings };
  }

  if (!new TextDecoder("ascii").decode(bytes.subarray(0, 1024)).includes("%PDF-")) {
    throw new Error(`${file.name}: this file does not contain a valid PDF header.`);
  }
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
  const task = pdfjs.getDocument({
    data: bytes,
    isEvalSupported: false,
    disableFontFace: true,
    useSystemFonts: false,
    stopAtErrors: true,
  });
  try {
    const pdf = await task.promise;
    if (pdf.numPages > MAX_PDF_PAGES) {
      throw new Error(`${file.name}: PDFs may contain up to 200 pages. Split this ${pdf.numPages}-page file before importing.`);
    }
    const pages: SourcePage[] = [];
    let totalCharacters = 0;
    let emptyPages = 0;
    for (let number = 1; number <= pdf.numPages; number += 1) {
      onProgress?.(`Reading ${file.name} · page ${number} of ${pdf.numPages}…`);
      const page = await pdf.getPage(number);
      const content = await page.getTextContent();
      let text = "";
      let previousY: number | null = null;
      for (const item of content.items) {
        if (!("str" in item)) continue;
        const y = item.transform[5] as number;
        if (previousY !== null && Math.abs(previousY - y) > Math.max(item.height * 0.6, 3) && !text.endsWith("\n")) {
          text += "\n";
        }
        text += item.str;
        text += item.hasEOL ? "\n" : " ";
        previousY = y;
      }
      text = text.replace(/[ \t]+\n/gu, "\n").trim();
      totalCharacters += text.length;
      ensureTextBudget(totalCharacters, file.name);
      if (!text) emptyPages += 1;
      pages.push({ number, text });
      page.cleanup();
    }
    if (emptyPages === pages.length) {
      throw new Error(`${file.name}: no selectable text was found. This may be a scanned PDF. Run OCR first, then import a searchable PDF.`);
    }
    if (emptyPages > 0) warnings.push(`${file.name}: ${emptyPages} of ${pages.length} pages have no selectable text and produced no chunks. They may need OCR.`);
    warnings.push(`${file.name}: PDF text follows its embedded reading order. Review columns, tables, and page boundaries before importing.`);
    return { id, name: file.name, pages, warnings };
  } catch (error) {
    if (error instanceof Error && error.name === "PasswordException") {
      throw new Error(`${file.name}: this PDF is password protected. Import an unlocked copy.`);
    }
    if (error instanceof Error && /^(InvalidPDFException|MissingPDFException|UnknownErrorException)$/u.test(error.name)) {
      throw new Error(`${file.name}: this PDF could not be read. Re-export it as a searchable PDF and try again.`);
    }
    throw error;
  } finally {
    await task.destroy();
  }
}

export async function extractBrowserDocuments(
  files: readonly File[],
  onProgress?: ExtractionProgress,
): Promise<SourceDocument[]> {
  if (files.length === 0) throw new Error("Choose at least one document.");
  if (files.length > MAX_FILES) throw new Error("Import up to 10 documents at a time.");
  for (const file of files) validateKnowledgeFile(file);
  const documents: SourceDocument[] = [];
  for (const file of files) documents.push(await extractBrowserDocument(file, onProgress));
  return documents;
}
