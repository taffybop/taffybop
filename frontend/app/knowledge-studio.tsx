"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { ArrowDownToLine, ArrowLeft, ArrowRight, BookOpen, Check, CheckCircle2, ChevronDown, ChevronRight, Copy, FileText, FolderOpen, Layers3, LoaderCircle, LockKeyhole, Plus, Save, Search, Settings2, ShieldCheck, Sparkles, Trash2, Upload, X } from "lucide-react";
import { createKnowledgePack, knowledgePackJsonl, type SourceDocument } from "@/lib/knowledge-pack";
import { extractBrowserDocument, MAX_FILES, MAX_FILE_BYTES } from "@/lib/browser-extract";
import { deleteSavedPack, listSavedPacks, writeSavedPack, type SavedPack } from "@/lib/pack-storage";
import "./studio.css";

type View = "workspace" | "saved" | "guide";
type OutputTab = "chunks" | "markdown" | "jsonl";
const DEFAULT_OPTIONS = { chunkSize: 180, overlap: 30, removeRepeatedHeaders: false };
const MAX_PACK_CHARACTERS = 2_000_000;

function sourceCharacters(documents: SourceDocument[]): number {
  return documents.reduce((total, document) => total + document.pages.reduce((count, page) => count + page.text.length, 0), 0);
}

function safeSavedOptions(options: SavedPack["options"]) {
  const chunkSize = Number.isFinite(options?.chunkSize)
    ? Math.min(500, Math.max(40, Math.round(options.chunkSize / 10) * 10))
    : DEFAULT_OPTIONS.chunkSize;
  const overlap = Number.isFinite(options?.overlap)
    ? Math.min(100, Math.floor(chunkSize / 2), Math.max(0, Math.round(options.overlap)))
    : Math.min(DEFAULT_OPTIONS.overlap, Math.floor(chunkSize / 2));
  return { chunkSize, overlap, removeRepeatedHeaders: options?.removeRepeatedHeaders === true };
}

function download(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function KnowledgeStudio() {
  const [view, setView] = useState<View>("workspace");
  const [documents, setDocuments] = useState<SourceDocument[]>([]);
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [name, setName] = useState("Untitled knowledge pack");
  const [packId, setPackId] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedPack[]>([]);
  const [tab, setTab] = useState<OutputTab>("chunks");
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState("all");
  const [busy, setBusy] = useState("");
  const [errors, setErrors] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [dragging, setDragging] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const [edit, setEdit] = useState<{ id: string; page: number; text: string } | null>(null);
  const [dirty, setDirty] = useState(false);
  const [visibleChunks, setVisibleChunks] = useState(20);
  const fileRef = useRef<HTMLInputElement>(null);
  const operationLock = useRef(false);
  const appRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const modalOpen = pasteOpen || edit !== null;
  const pack = useMemo(() => createKnowledgePack(documents, options), [documents, options]);
  const jsonl = useMemo(() => knowledgePackJsonl(pack), [pack]);
  const hasContent = pack.chunks.length > 0;
  const filteredChunks = useMemo(() => pack.chunks.filter(chunk => (sourceFilter === "all" || chunk.sourceId === sourceFilter) && `${chunk.text} ${chunk.source}`.toLowerCase().includes(query.toLowerCase())), [pack.chunks, sourceFilter, query]);

  useEffect(() => { listSavedPacks().then(setSaved).catch(() => { /* Storage is optional until Save is requested. */ }); }, []);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!dirty) return;
    const preventLoss = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [dirty]);

  useEffect(() => {
    if (!modalOpen) return;
    const modal = modalRef.current;
    if (!modal) return;
    const backgrounds = Array.from(appRef.current?.querySelectorAll<HTMLElement>(".kb-sidebar, .kb-body, .kb-skip") ?? []);
    const previousInert = backgrounds.map(element => element.inert);
    const previousOverflow = document.body.style.overflow;
    backgrounds.forEach(element => { element.inert = true; });
    document.body.style.overflow = "hidden";
    const focusable = () => Array.from(modal.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex="0"]'));
    (modal.querySelector<HTMLElement>("[data-modal-autofocus]") ?? focusable()[0] ?? modal).focus();
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const items = focusable();
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) { event.preventDefault(); modal.focus(); return; }
      if (event.shiftKey && (document.activeElement === first || document.activeElement === modal)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    modal.addEventListener("keydown", trapFocus);
    return () => {
      modal.removeEventListener("keydown", trapFocus);
      backgrounds.forEach((element, index) => { element.inert = previousInert[index]; });
      document.body.style.overflow = previousOverflow;
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
    };
  }, [modalOpen]);

  const importFiles = useCallback(async (input: File[] | (() => Promise<File[]>), sample = false): Promise<boolean> => {
    if (operationLock.current) return false;
    operationLock.current = true;
    setBusy(sample ? "Opening the sample handbook…" : "Reading your sources…");
    setErrors([]);
    const failures: string[] = [];
    const additions: SourceDocument[] = [];
    try {
      const files = typeof input === "function" ? await input() : input;
      const available = MAX_FILES - documents.length;
      if (files.length > available) {
        setErrors([`A pack can contain up to ${MAX_FILES} documents. Remove a source or choose fewer files.`]);
        return false;
      }
      let characterCount = sourceCharacters(documents);
      for (const file of files) {
        if (documents.some(doc => doc.name === file.name) || additions.some(doc => doc.name === file.name)) {
          failures.push(`${file.name}: already in this pack. Rename the file or remove the existing source first.`);
          continue;
        }
        try {
          setBusy(`Reading ${file.name}…`);
          const document = await extractBrowserDocument(file, setBusy);
          const documentCharacters = sourceCharacters([document]);
          if (characterCount + documentCharacters > MAX_PACK_CHARACTERS) {
            failures.push(`${file.name}: a pack can contain up to 2 million text characters. Remove a source or split your content into separate packs.`);
            continue;
          }
          if (documents.some(doc => doc.id === document.id) || additions.some(doc => doc.id === document.id)) {
            failures.push(`${file.name}: this source is already in the pack.`);
            continue;
          }
          additions.push(document);
          characterCount += documentCharacters;
        } catch (error) { failures.push(error instanceof Error ? error.message : `Could not read ${file.name}.`); }
      }
      if (additions.length) {
        setDocuments(current => [...current, ...additions]);
        setDirty(true);
        setView("workspace");
        if (!documents.length && name === "Untitled knowledge pack") setName(sample ? "Customer support knowledge" : additions[0].name.replace(/\.[^.]+$/, ""));
        setNotice(`${additions.length} ${additions.length === 1 ? "source is" : "sources are"} ready to review.`);
      }
      setErrors(failures);
      return additions.length > 0;
    } catch (error) {
      setErrors([error instanceof Error ? error.message : "Could not read these sources."]);
      return false;
    } finally { setBusy(""); operationLock.current = false; }
  }, [documents, name]);

  async function loadSample() {
    await importFiles(async () => {
      const response = await fetch("/samples/customer-support-handbook.pdf");
      if (!response.ok) throw new Error("The sample could not be loaded. Try importing your own PDF.");
      return [new File([await response.blob()], "Customer support handbook.pdf", { type: "application/pdf" })];
    }, true);
  }

  async function savePack() {
    if (!hasContent || operationLock.current) return;
    operationLock.current = true;
    setBusy("Saving your pack…");
    try {
      const id = packId ?? crypto.randomUUID();
      await writeSavedPack({ id, name: name.trim() || "Untitled knowledge pack", documents, options, updatedAt: new Date().toISOString() });
      setPackId(id);
      setSaved(await listSavedPacks());
      setDirty(false);
      setNotice("Pack saved on this device.");
    } catch (error) { setErrors([error instanceof Error ? error.message : "Could not save this pack."]); }
    finally { setBusy(""); operationLock.current = false; }
  }

  function guardNavigation(event: MouseEvent<HTMLAnchorElement>) {
    // Opening a separate tab leaves this workspace intact.
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (operationLock.current) {
      event.preventDefault();
      setNotice("Wait for the current operation to finish before leaving.");
      return;
    }
    if (dirty && !window.confirm("Leave this workspace? Unsaved changes will be discarded. Choose Cancel to save or export first.")) {
      event.preventDefault();
    }
  }

  function showView(nextView: View) {
    if (!operationLock.current) setView(nextView);
  }

  function newPack() {
    if (operationLock.current) return;
    if (dirty && !window.confirm("Start a new pack? Unsaved changes will be discarded. Choose Cancel to save or export first.")) return;
    setDocuments([]); setPackId(null); setName("Untitled knowledge pack"); setOptions(DEFAULT_OPTIONS);
    setErrors([]); setQuery(""); setSourceFilter("all"); setDirty(false); setView("workspace"); setVisibleChunks(20);
  }

  function openSaved(item: SavedPack) {
    if (operationLock.current) return;
    if (dirty && !window.confirm("Open this saved pack? Unsaved changes to the current pack will be discarded.")) return;
    try {
      const nextOptions = safeSavedOptions(item.options);
      if (item.documents.length > MAX_FILES || sourceCharacters(item.documents) > MAX_PACK_CHARACTERS) {
        throw new Error("This saved pack exceeds the current limit of 10 sources or 2 million text characters.");
      }
      // Validate stored sources before committing them to render state.
      createKnowledgePack(item.documents, nextOptions);
      if (item.documents.some(document => document.pages.length === 0)) throw new Error("This saved pack has a source with no pages.");
      setDocuments(item.documents); setName(item.name); setPackId(item.id); setOptions(nextOptions);
      setDirty(JSON.stringify(nextOptions) !== JSON.stringify(item.options)); setErrors([]); setView("workspace"); setQuery(""); setSourceFilter("all"); setVisibleChunks(20);
      setNotice("Saved pack opened.");
    } catch (error) { setErrors([error instanceof Error ? error.message : "This saved pack could not be opened."]); }
  }

  async function removeSaved(id: string) {
    if (operationLock.current) return;
    if (!window.confirm("Delete this saved pack from this device? Download a copy first if you need a backup.")) return;
    operationLock.current = true;
    setBusy("Deleting saved pack…");
    try {
      await deleteSavedPack(id); setSaved(await listSavedPacks());
      if (packId === id) { setPackId(null); setDirty(documents.length > 0); }
      setNotice("Saved pack deleted.");
    } catch (error) { setErrors([error instanceof Error ? error.message : "Could not delete pack."]); }
    finally { setBusy(""); operationLock.current = false; }
  }

  function openPaste() {
    if (operationLock.current) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setErrors([]);
    setPasteOpen(true);
  }

  function closePaste() {
    if (!operationLock.current) setPasteOpen(false);
  }

  async function addPastedText() {
    if (operationLock.current) return;
    if (!pasteText.trim()) { setErrors(["Paste some text before adding a source."]); return; }
    if (new Blob([pasteText]).size > MAX_FILE_BYTES) { setErrors(["Pasted text must be smaller than 20 MB."]); return; }
    if (sourceCharacters(documents) + pasteText.length > MAX_PACK_CHARACTERS) {
      setErrors(["A pack can contain up to 2 million text characters. Shorten this text or start another pack."]);
      return;
    }
    const filename = (pasteName.trim() || "Pasted notes") + ".txt";
    if (await importFiles([new File([pasteText], filename, { type: "text/plain" })])) {
      setPasteOpen(false); setPasteText(""); setPasteName("");
    }
  }

  function openReview(document: SourceDocument, pageNumber: number) {
    if (operationLock.current) return;
    const page = document.pages.find(item => item.number === pageNumber);
    if (!page) return;
    returnFocusRef.current = window.document.activeElement as HTMLElement | null;
    setErrors([]);
    setEdit({ id: document.id, page: page.number, text: page.text });
  }

  function closeReview() {
    if (operationLock.current || !edit) return;
    const original = documents.find(source => source.id === edit.id)?.pages.find(page => page.number === edit.page)?.text;
    if (edit.text !== original && !window.confirm("Discard your changes to this page? Choose Cancel, then Apply changes to keep them.")) return;
    setEdit(null);
  }

  function applyReview() {
    if (operationLock.current || !edit) return;
    const original = documents.find(source => source.id === edit.id)?.pages.find(page => page.number === edit.page)?.text ?? "";
    if (sourceCharacters(documents) - original.length + edit.text.length > MAX_PACK_CHARACTERS) {
      setErrors(["A pack can contain up to 2 million text characters. Shorten this page before applying changes."]);
      return;
    }
    setDocuments(current => current.map(source => source.id === edit.id ? { ...source, pages: source.pages.map(page => page.number === edit.page ? { ...page, text: edit.text } : page) } : source));
    setDirty(true); setEdit(null); setErrors([]); setNotice("Source updated. Chunks rebuilt.");
  }

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setNotice("Copied to clipboard."); }
    catch { setErrors(["Clipboard access is unavailable. Use Download to save your content."]); }
  }

  function exportPack(format: "md" | "jsonl") {
    const basename = (name.trim() || "knowledge-pack").replace(/[^\p{L}\p{N}_-]+/gu, "-").slice(0, 80);
    download(format === "md" ? pack.markdown : jsonl, `${basename}.${format}`, format === "md" ? "text/markdown;charset=utf-8" : "application/x-ndjson;charset=utf-8");
    setNotice(`${format === "md" ? "Markdown" : "JSONL"} export downloaded.`);
  }

  return <div className="kb-app" ref={appRef}>
    <a className="kb-skip" href="#studio-main">Skip to workspace</a>
    <aside className="kb-sidebar">
      <Link className="kb-logo" href="/" onClick={guardNavigation}><span className="kb-logomark"><Layers3 size={22} /></span>TaffyBop<span className="kb-beta">BETA</span></Link>
      <div className="kb-space-label">YOUR KNOWLEDGE, READY.</div>
      <button className="kb-new" onClick={newPack} disabled={!!busy}><Plus size={17} /> New knowledge pack</button>
      <nav aria-label="Studio navigation">
        <button className={view === "workspace" ? "active" : ""} onClick={() => showView("workspace")} disabled={!!busy}><Layers3 size={18} /> Workspace <ChevronRight size={15} /></button>
        <button className={view === "saved" ? "active" : ""} onClick={() => showView("saved")} disabled={!!busy}><FolderOpen size={18} /> Saved packs <span className="kb-count">{saved.length}</span></button>
        <button className={view === "guide" ? "active" : ""} onClick={() => showView("guide")} disabled={!!busy}><BookOpen size={18} /> Quick guide</button>
      </nav>
      <div className="kb-sidebar-bottom"><div className="kb-private-card"><ShieldCheck size={22} /><strong>Your docs stay yours.</strong><p>Files are processed in your browser. No uploads. No API keys.</p><Link href="/privacy" onClick={guardNavigation}>How privacy works <ArrowRight size={13} /></Link></div><Link href="/" className="kb-back" onClick={guardNavigation}><ArrowLeft size={14} /> Back to TaffyBop</Link></div>
    </aside>
    <div className="kb-body">
      <header className="kb-topbar"><div><span>Knowledge Studio</span><ChevronRight size={13} /><strong>{view === "saved" ? "Saved packs" : view === "guide" ? "Quick guide" : "Workspace"}</strong></div><span className="kb-local"><i /> Runs on your device</span></header>
      <main id="studio-main" className="kb-main">
        {errors.length > 0 && <div className="kb-error" role="alert"><div><strong>Something needs attention</strong>{errors.map((error, index) => <p key={index}>{error}</p>)}</div><button aria-label="Dismiss errors" onClick={() => setErrors([])}><X size={18} /></button></div>}
        {view === "workspace" && <>
          <section className="kb-title-row"><div><div className="kb-eyebrow">A LITTLE PREP. BETTER ANSWERS.</div><h1>Make your knowledge useful.</h1><p>Turn documents into clean, traceable context for your AI assistant.</p></div><button className="kb-button kb-button-white" onClick={loadSample} disabled={!!busy || documents.length >= MAX_FILES}><Sparkles size={16} /> Try a sample</button></section>
          <div className="kb-workspace-grid">
            <div className="kb-input-column">
              <section className="kb-panel kb-source-panel"><div className="kb-panel-heading"><h2><span className="kb-step">01</span> Add your sources</h2><span>{documents.length}/{MAX_FILES}</span></div>
                <input ref={fileRef} type="file" multiple accept=".pdf,.txt,.md,text/plain,text/markdown,application/pdf" aria-label="Import source documents" className="kb-file-input" disabled={!!busy} onChange={event => { const files = Array.from(event.target.files ?? []); event.target.value = ""; void importFiles(files); }} />
                <div className={`kb-dropzone ${dragging ? "dragging" : ""} ${busy ? "loading" : ""}`} onDragOver={event => { event.preventDefault(); if (!busy) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (!busy) void importFiles(Array.from(event.dataTransfer.files)); }}>
                  <span className="kb-upload-icon">{busy ? <LoaderCircle className="kb-spin" size={24} /> : <Upload size={24} />}</span>
                  {busy ? <><strong aria-live="polite">{busy}</strong><span>Processing locally. Keep this tab open.</span></> : <><strong>Drop your documents here</strong><span>PDF, Markdown or plain text</span><button className="kb-button kb-button-dark" onClick={() => fileRef.current?.click()} disabled={documents.length >= MAX_FILES}>Browse files <Plus size={16} /></button><small>20 MB / file · 200 pages / PDF · 2M characters / pack</small></>}
                </div>
                <button className="kb-paste-link" onClick={openPaste} disabled={!!busy || documents.length >= MAX_FILES}>Or paste your text <ArrowRight size={14} /></button>
                {documents.length > 0 && <div className="kb-source-list">{documents.map(doc => <div className="kb-source" key={doc.id}><span className="kb-file-symbol"><FileText size={18} /></span><button className="kb-source-name" onClick={() => openReview(doc, doc.pages[0].number)} disabled={!!busy}><strong>{doc.name}</strong><span>{doc.pages.length} {doc.pages.length === 1 ? "page" : "pages"} · Review text</span></button><button className="kb-icon-button" aria-label={`Remove ${doc.name}`} disabled={!!busy} onClick={() => { setDocuments(current => current.filter(source => source.id !== doc.id)); setDirty(true); if (sourceFilter === doc.id) setSourceFilter("all"); }}><X size={15} /></button></div>)}</div>}
                <div className="kb-source-note"><LockKeyhole size={13} /><span>Text-based PDFs work best. Scans need OCR first.</span></div>
              </section>
              <section className="kb-panel kb-settings"><div className="kb-panel-heading"><h2><span className="kb-step">02</span> Shape your context</h2><Settings2 size={16} /></div>
                <label className="kb-setting-label" htmlFor="chunk-size">Chunk size <span>{options.chunkSize} words</span></label><input id="chunk-size" aria-label="Chunk size in words" type="range" min="40" max="500" step="10" value={options.chunkSize} disabled={!!busy} onChange={event => { const chunkSize = Number(event.target.value); setOptions(current => ({ ...current, chunkSize, overlap: Math.min(current.overlap, Math.floor(chunkSize / 2)) })); setDirty(true); }} /><div className="kb-range-labels"><span>Focused</span><span>More context</span></div>
                <label className="kb-setting-label" htmlFor="overlap">Overlap <span>{options.overlap} words</span></label><input id="overlap" aria-label="Overlap in words" type="range" min="0" max={Math.min(100, Math.floor(options.chunkSize / 2))} step="1" value={options.overlap} disabled={!!busy} onChange={event => { setOptions(current => ({ ...current, overlap: Number(event.target.value) })); setDirty(true); }} /><p className="kb-setting-hint">Repeats a few words between chunks to keep context connected.</p>
                <label className="kb-checkbox"><input type="checkbox" checked={options.removeRepeatedHeaders} disabled={!!busy} onChange={event => { setOptions(current => ({ ...current, removeRepeatedHeaders: event.target.checked })); setDirty(true); }} /><span>Clean repeated page headers<small>Remove recurring first and last lines. Review the result.</small></span></label>
              </section>
            </div>
            <section className="kb-panel kb-output-panel"><div className="kb-output-heading"><div><div className="kb-eyebrow">03 / REVIEW & EXPORT</div><input className="kb-pack-name" aria-label="Pack name" value={name} disabled={!!busy} maxLength={100} onChange={event => { setName(event.target.value); setDirty(true); }} /></div><button className="kb-button kb-save" onClick={savePack} disabled={!hasContent || !!busy}><Save size={16} /><span>{packId && !dirty ? "Saved" : "Save pack"}</span></button></div>
              <div className="kb-stats"><div><strong>{pack.stats.documents}</strong><span>Sources</span></div><div><strong>{pack.stats.pages}</strong><span>Pages</span></div><div><strong>{pack.stats.chunks}</strong><span>Chunks</span></div><div><strong>{pack.stats.words.toLocaleString()}</strong><span>Source words</span></div></div>
              <div className="kb-tabs" role="tablist" aria-label="Output format">{(["chunks", "markdown", "jsonl"] as const).map(item => <button id={`tab-${item}`} key={item} role="tab" aria-selected={tab === item} aria-controls="output-panel" className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "chunks" ? <Layers3 size={15} /> : <FileText size={15} />}{item === "chunks" ? "Chunks" : item === "markdown" ? "Markdown" : "JSONL"}{item === "chunks" && hasContent && <span>{pack.chunks.length}</span>}</button>)}</div>
              <div id="output-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="kb-output-content">
                {!hasContent ? <div className="kb-empty"><div className="kb-empty-art"><span /><span /><div><Layers3 size={35} /></div></div><h3>A good answer starts here.</h3><p>Add your first source to see clean text,<br />reviewable chunks, and page citations.</p><button onClick={loadSample} disabled={!!busy} className="kb-text-button">Explore with a sample <ArrowRight size={15} /></button><div className="kb-empty-pills"><span><Check size={13} /> No sign-up</span><span><Check size={13} /> No API key</span></div></div> : <>
                  {pack.warnings.length > 0 && <details className="kb-warnings"><summary>{pack.warnings.length} review {pack.warnings.length === 1 ? "note" : "notes"}<ChevronDown size={15} /></summary><ul>{pack.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></details>}
                  {tab === "chunks" ? <><div className="kb-search-row"><label><Search size={15} /><input aria-label="Search chunks" placeholder="Search your chunks…" value={query} onChange={event => { setQuery(event.target.value); setVisibleChunks(20); }} /></label><select aria-label="Filter source" value={sourceFilter} onChange={event => { setSourceFilter(event.target.value); setVisibleChunks(20); }}><option value="all">All sources</option>{documents.map(doc => <option key={doc.id} value={doc.id}>{doc.name}</option>)}</select></div><div className="kb-chunk-list">{filteredChunks.slice(0, visibleChunks).map(chunk => <article className="kb-chunk" key={chunk.id}><div className="kb-chunk-top"><span><span className="kb-chunk-dot" />{chunk.id}</span><span>{chunk.words} words<button className="kb-icon-button" aria-label={`Copy ${chunk.id}`} onClick={() => copy(chunk.text)}><Copy size={14} /></button></span></div><p>{chunk.text}</p><button className="kb-citation" onClick={() => { const doc = documents.find(item => item.id === chunk.sourceId); const page = doc?.pages.find(item => item.number === chunk.page); if (doc && page) openReview(doc, page.number); }}><FileText size={12} />{chunk.citation}<ArrowRight size={12} /></button></article>)}{filteredChunks.length === 0 && <div className="kb-no-results">No chunks match your search.</div>}{filteredChunks.length > visibleChunks && <button className="kb-button kb-button-white kb-load-more" onClick={() => setVisibleChunks(current => current + 20)}>Show more chunks ({filteredChunks.length - visibleChunks} remaining)</button>}</div></> : <div className="kb-code-view"><div><span>{tab === "markdown" ? "knowledge-pack.md" : "knowledge-pack.jsonl"}</span><button className="kb-text-button" onClick={() => copy(tab === "markdown" ? pack.markdown : jsonl)}><Copy size={14} />Copy all</button></div><pre>{tab === "markdown" ? pack.markdown : jsonl}</pre></div>}
                </>}
              </div>
              <div className="kb-export-bar"><span><ShieldCheck size={14} />{dirty ? "Unsaved · on this device" : packId ? "Saved on this device" : "Private by design"}</span><div><button className="kb-button kb-button-white" disabled={!hasContent || !!busy} onClick={() => exportPack("md")}><ArrowDownToLine size={15} />Markdown</button><button className="kb-button kb-button-dark" disabled={!hasContent || !!busy} onClick={() => exportPack("jsonl")}><ArrowDownToLine size={15} />JSONL</button></div></div>
            </section>
          </div>
          <div className="kb-bottom-note"><span><CheckCircle2 size={14} /> Built for the work before the AI.</span><span>Free beta · Files never leave your browser</span></div>
        </>}
        {view === "saved" && <section><div className="kb-title-row"><div><div className="kb-eyebrow">PICK UP WHERE YOU LEFT OFF</div><h1>Your saved packs.</h1><p>Extracted text and settings saved in this browser. Export a copy for safekeeping.</p></div><button className="kb-button kb-button-dark" onClick={newPack} disabled={!!busy}><Plus size={16} />New pack</button></div>{saved.length ? <div className="kb-saved-grid">{saved.map(item => <article className="kb-panel kb-saved-card" key={item.id}><span className="kb-file-symbol"><FolderOpen size={22} /></span><h2>{item.name}</h2><p>{item.documents.length} {item.documents.length === 1 ? "source" : "sources"} · {item.documents.reduce((total, doc) => total + doc.pages.length, 0)} pages</p><small>Saved {new Date(item.updatedAt).toLocaleString()}</small><div><button className="kb-button kb-button-white" onClick={() => openSaved(item)} disabled={!!busy}>Open pack <ArrowRight size={15} /></button><button className="kb-icon-button" aria-label={`Delete ${item.name}`} onClick={() => removeSaved(item.id)} disabled={!!busy}><Trash2 size={16} /></button></div></article>)}</div> : <div className="kb-panel kb-saved-empty"><FolderOpen size={38} /><h2>Keep your good work close.</h2><p>Build a knowledge pack, then choose Save pack to return to it here.</p><button className="kb-button kb-button-dark" onClick={() => showView("workspace")} disabled={!!busy}>Go to workspace <ArrowRight size={16} /></button></div>}</section>}
        {view === "guide" && <section className="kb-guide"><div className="kb-eyebrow">A FIVE-MINUTE HEAD START</div><h1>From documents to useful context.</h1><p className="kb-guide-lead">TaffyBop prepares source material for AI assistants and retrieval systems. It does not train a model, generate embeddings, or connect to your assistant.</p>{[
          ["1", "Bring the right sources", "Import text-based PDFs, UTF-8 text, or Markdown. Each file can be up to 20 MB; PDFs can contain up to 200 pages. A pack holds 10 sources and up to 2 million text characters. Images and scanned PDFs need OCR in another tool first."],
          ["2", "Review what was extracted", "Select a source or a citation to review and edit its page text. PDF reading order can vary, especially for tables and columns. Review notes flag empty pages and potential extraction issues; always check important information against the original."],
          ["3", "Give each chunk enough context", "Start with 180 words and 30 words of overlap. Smaller chunks suit focused FAQs; larger chunks preserve more context. Chunks stay within one source page, and overlap only applies within that page. These are word counts, not model token counts."],
          ["4", "Export to your own workflow", "Markdown includes source names and page sections. JSONL contains one chunk per line with stable identifiers, text, source filename, page numbers, and citation metadata. Import the file into your preferred system or transform the JSONL to its schema. There is no automatic integration."],
          ["5", "Save a copy you control", "Save pack keeps extracted text and settings in this browser's IndexedDB. It does not save the original PDF or sync between devices. Clearing browser data removes saved packs. Download exports for a portable copy."],
        ].map(([number, title, body]) => <article className="kb-panel" key={number}><span className="kb-step">{number}</span><div><h2>{title}</h2><p>{body}</p></div></article>)}<button className="kb-button kb-button-dark" onClick={() => showView("workspace")} disabled={!!busy}>Make a knowledge pack <ArrowRight size={16} /></button></section>}
      </main>
    </div>
    {notice && <div className="kb-toast" role="status"><CheckCircle2 size={17} />{notice}</div>}
    {pasteOpen && <div className="kb-modal-backdrop" onClick={closePaste}><section className="kb-modal" ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="paste-title" onClick={event => event.stopPropagation()} onKeyDown={event => { if (event.key === "Escape") closePaste(); }}><div className="kb-modal-heading"><div><div className="kb-eyebrow">ADD A SOURCE</div><h2 id="paste-title">Paste something useful.</h2></div><button className="kb-icon-button" aria-label="Close paste dialog" onClick={closePaste}><X size={19} /></button></div>{errors.length > 0 && <div className="kb-error" role="alert"><div>{errors.map((error, index) => <p key={index}>{error}</p>)}</div></div>}<label htmlFor="source-name">Source name</label><input id="source-name" data-modal-autofocus disabled={!!busy} placeholder="e.g. Returns policy" maxLength={100} value={pasteName} onChange={event => setPasteName(event.target.value)} /><label htmlFor="source-text">Source text</label><textarea id="source-text" disabled={!!busy} placeholder="Paste your documentation, FAQs, or notes here…" value={pasteText} onChange={event => setPasteText(event.target.value)} /><div className="kb-modal-footer"><span>Stored locally, only if you save.</span><button className="kb-button kb-button-dark" onClick={addPastedText} disabled={!pasteText.trim() || !!busy}>{busy ? "Adding…" : "Add source"} <Plus size={16} /></button></div></section></div>}
    {edit && (() => {
      const doc = documents.find(item => item.id === edit.id);
      if (!doc) return null;
      return <div className="kb-modal-backdrop" onClick={closeReview}><section className="kb-modal kb-review-modal" ref={modalRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="review-title" onClick={event => event.stopPropagation()} onKeyDown={event => { if (event.key === "Escape") closeReview(); }}><div className="kb-modal-heading"><div><div className="kb-eyebrow">REVIEW SOURCE TEXT</div><h2 id="review-title">{doc.name}</h2></div><button className="kb-icon-button" aria-label="Close source review" onClick={closeReview}><X size={19} /></button></div>{errors.length > 0 && <div className="kb-error" role="alert"><div>{errors.map((error, index) => <p key={index}>{error}</p>)}</div></div>}<div className="kb-review-toolbar"><label htmlFor="review-page">Page</label><select id="review-page" value={edit.page} onChange={event => { if (edit.text !== doc.pages.find(page => page.number === edit.page)?.text && !window.confirm("Discard edits to this page? Apply changes first to keep them.")) return; const page = doc.pages.find(item => item.number === Number(event.target.value)); if (page) setEdit({ id: doc.id, page: page.number, text: page.text }); }}>{doc.pages.map(page => <option key={page.number} value={page.number}>Page {page.number}</option>)}</select><span>{doc.pages.length} total</span></div><label className="visually-hidden" htmlFor="review-text">Extracted page text</label><textarea id="review-text" data-modal-autofocus value={edit.text} onChange={event => setEdit(current => current ? { ...current, text: event.target.value } : null)} /><div className="kb-modal-footer"><span>Edits update chunks and exports.</span><button className="kb-button kb-button-dark" onClick={applyReview}>Apply changes <Check size={16} /></button></div></section></div>;
    })()}
  </div>;
}
