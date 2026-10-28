"use client";

import Link from "next/link";
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, ArrowDownToLine, ArrowLeft, Braces, CheckCircle2, ChevronLeft, ChevronRight, Copy, FileText, ImageIcon, Layers3, LoaderCircle, Play, Upload, X } from "lucide-react";
import { DocumentApiError, getBrowserPreviewKind, getConfiguredMaxUploadBytes, parseJsonResponse, stripSupportedDocumentExtension, SUPPORTED_DOCUMENT_ACCEPT, validateDocumentFile, type ParseJsonResponse } from "@/lib/document-api";
import { fieldText, inlineApiImage, previewTable, record, responseWarnings } from "@/lib/backend-result-view";
import { ImagePagePreview } from "./image-page-preview";
import "./backend-workspace.css";

const PdfPreview = lazy(() => import("./pdf-page-preview").then(module => ({ default: module.PdfPagePreview })));
type OutputTab = "json" | "preview" | "metadata";

function downloadBytes(bytes: Uint8Array, filename: string) {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  const url = URL.createObjectURL(new Blob([copy.buffer], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ApiItem({ value, index, fallbackType = "item" }: { value: unknown; index: number; fallbackType?: string }) {
  const item = record(value);
  if (!item) return <pre className="bw-value">{fieldText(value)}</pre>;
  const type = typeof item.type === "string" ? item.type : fallbackType;
  const isTableCandidate = type === "table_candidate";
  const table = type === "table" || isTableCandidate ? previewTable(item) : null;
  const image = inlineApiImage(item);
  const isVisual = ["image", "chart", "diagram"].includes(type);
  const text = item.value !== undefined ? fieldText(item.value) : item.text !== undefined ? fieldText(item.text) : "";
  const hasValue = item.value !== undefined || item.text !== undefined;
  return <article className="bw-item">
    <div className="bw-item-heading"><strong>{type}</strong><code>{fieldText(item.id ?? `Item ${index + 1}`)}</code>{typeof item.source === "string" && <span>Source: {item.source}</span>}</div>
    {isTableCandidate && <p className="bw-item-concerns">The API returned a table candidate, not a confirmed table. Review its rows and concerns against the original document.</p>}
    {table ? <><p className="bw-field-label">API {table.representation}{table.representation === "cells" ? " · explicit cell spans" : ""}</p>{table.note && <p className="bw-view-note">{table.note}</p>}<div className="bw-table-scroll"><table><tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map(cell => cell.header ? <th key={cell.column} rowSpan={cell.rowSpan} colSpan={cell.colSpan}>{cell.text}</th> : <td key={cell.column} rowSpan={cell.rowSpan} colSpan={cell.colSpan}>{cell.text}</td>)}</tr>)}</tbody></table></div></> : hasValue ? <><p className="bw-field-label">{item.value !== undefined ? "value" : "text"}</p><pre className="bw-value">{text}</pre>{text === "" && <p className="bw-view-note">The API returned an empty string for this field.</p>}</> : <p className="bw-view-note">No value or text field was returned. Other item fields are available below.</p>}
    {image && <figure className="bw-inline-image">{/* Only a returned inline raster asset is allowed; no remote URLs or HTML. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={image} alt={`API image asset for ${fieldText(item.id ?? type)}`} loading="lazy" /><figcaption>Inline image asset returned by the API</figcaption></figure>}
    {isVisual && !image && <p className="bw-view-note"><ImageIcon size={15} />No inline image asset was returned for this item. Inspect the original document alongside its metadata.</p>}
    {typeof item.ocr_text === "string" && item.ocr_text.length > 0 && <div><p className="bw-field-label">ocr_text</p><pre className="bw-value">{item.ocr_text}</pre></div>}
    {typeof item.md === "string" && item.md.length > 0 && <details className="bw-item-details"><summary>API Markdown field</summary><pre className="bw-value">{item.md}</pre></details>}
    {Array.isArray(item.parse_concerns) && item.parse_concerns.length > 0 && <div className="bw-item-concerns"><strong>API concerns</strong><ul>{item.parse_concerns.map((concern, concernIndex) => <li key={concernIndex}>{fieldText(concern)}</li>)}</ul></div>}
    <details className="bw-item-details"><summary>All fields for this item</summary><pre className="bw-value">{JSON.stringify(item, null, 2)}</pre></details>
  </article>;
}

export function BackendWorkspace({ apiBaseUrl }: { apiBaseUrl?: string }) {
  const [file, setFile] = useState<File | null>(null);
  const [fileUrl, setFileUrl] = useState("");
  const [response, setResponse] = useState<ParseJsonResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<{ message: string; code?: string; status?: number | null; details?: Record<string, unknown> } | null>(null);
  const [notice, setNotice] = useState("");
  const [activePage, setActivePage] = useState(0);
  const [previewPages, setPreviewPages] = useState(0);
  const [tab, setTab] = useState<OutputTab>("json");
  const [wrap, setWrap] = useState(true);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const resultPaneRef = useRef<HTMLDivElement>(null);
  const sourcePaneRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<AbortController | null>(null);
  const sampleRef = useRef<AbortController | null>(null);
  const operationRef = useRef(false);
  const maximumBytes = getConfiguredMaxUploadBytes();
  const result = response?.data ?? null;
  const pages = result?.pages ?? [];
  const selectedPage = record(pages[activePage]);
  const previewKind = file ? getBrowserPreviewKind(file) : null;
  const pageCount = result ? pages.length : previewKind === "pdf" ? previewPages : file ? 1 : 0;
  const sourcePageNumber = typeof selectedPage?.page_index === "number" && Number.isInteger(selectedPage.page_index) && selectedPage.page_index > 0 ? selectedPage.page_index : activePage + 1;
  const items = Array.isArray(selectedPage?.items) ? selectedPage.items : [];
  const detectedImages = Array.isArray(selectedPage?.detected_images) ? selectedPage.detected_images : [];
  const warnings = useMemo(() => responseWarnings(result), [result]);
  const locked = busy || loadingSample;

  useEffect(() => () => { if (fileUrl) URL.revokeObjectURL(fileUrl); }, [fileUrl]);
  useEffect(() => () => { requestRef.current?.abort(); sampleRef.current?.abort(); }, []);
  useEffect(() => {
    if (resultPaneRef.current) resultPaneRef.current.scrollTop = 0;
  }, [tab]);
  useEffect(() => {
    // Page navigation changes only the structured result, not the full JSON.
    if (tab === "preview" && resultPaneRef.current) resultPaneRef.current.scrollTop = 0;
  }, [activePage, tab]);
  useEffect(() => {
    const pane = sourcePaneRef.current;
    if (!pane) return;
    pane.scrollTop = 0;
    // PDF/image previews own an inner viewport as well as the outer pane.
    const viewport = pane.querySelector<HTMLElement>(".pdf-page-preview, .image-page-preview");
    if (viewport) viewport.scrollTop = 0;
  }, [activePage, sourcePageNumber, fileUrl]);
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 4500);
    return () => window.clearTimeout(timer);
  }, [notice]);
  useEffect(() => {
    if (!locked) return;
    const preventLoss = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", preventLoss);
    return () => window.removeEventListener("beforeunload", preventLoss);
  }, [locked]);

  function chooseFile(selected: File) {
    if (operationRef.current) return;
    try {
      validateDocumentFile(selected, maximumBytes);
      setFile(selected); setFileUrl(URL.createObjectURL(selected)); setResponse(null); setError(null); setNotice("");
      setActivePage(0); setPreviewPages(0); setTab("json");
    } catch (failure) { setError({ message: failure instanceof Error ? failure.message : "This file cannot be selected." }); }
  }

  async function parse(selected = file) {
    if (!selected || operationRef.current) return;
    operationRef.current = true;
    const controller = new AbortController();
    requestRef.current = controller;
    setBusy(true); setElapsed(0); setError(null); setResponse(null); setTab("json"); setNotice("");
    try {
      const value = await parseJsonResponse(selected, { apiBaseUrl, signal: controller.signal });
      if (controller.signal.aborted) return;
      setResponse(value); setActivePage(0); setNotice("The API response is ready.");
    } catch (failure) {
      if (failure instanceof DocumentApiError && failure.kind === "cancelled") setNotice("Request cancelled.");
      else if (failure instanceof DocumentApiError) setError({ message: failure.message, code: failure.code, status: failure.status, details: failure.details });
      else setError({ message: failure instanceof Error ? failure.message : "The request could not be completed." });
    } finally {
      if (requestRef.current === controller) { requestRef.current = null; operationRef.current = false; setBusy(false); }
    }
  }

  async function useSample() {
    if (operationRef.current) return;
    operationRef.current = true; setLoadingSample(true); setError(null);
    const controller = new AbortController(); sampleRef.current = controller;
    try {
      const sample = await fetch("/samples/customer-support-handbook.pdf", { signal: controller.signal });
      if (!sample.ok) throw new Error("The sample could not be loaded. Choose a document from your device.");
      const selected = new File([await sample.blob()], "customer-support-handbook.pdf", { type: "application/pdf" });
      operationRef.current = false;
      chooseFile(selected);
    } catch (failure) { if (!controller.signal.aborted) setError({ message: failure instanceof Error ? failure.message : "Could not load the sample." }); }
    finally { sampleRef.current = null; operationRef.current = false; setLoadingSample(false); }
  }

  async function copyResponse() {
    if (!response) return;
    try { await navigator.clipboard.writeText(response.rawText); setNotice("Original API response copied."); }
    catch { setError({ message: "Clipboard access is unavailable. Download the original JSON instead." }); }
  }

  function clear() {
    if (operationRef.current) return;
    setFile(null); setFileUrl(""); setResponse(null); setError(null); setActivePage(0); setPreviewPages(0);
  }

  return <div className="bw-app">
    <a href="#document-workspace" className="bw-skip">Skip to workspace</a>
    <header className="bw-header"><Link href="/" className="bw-brand" onClick={event => { if (operationRef.current) event.preventDefault(); }}><span><Layers3 size={22} /></span>TaffyBop<span className="bw-brand-dot">.</span></Link><nav aria-label="Document navigation"><Link href="/knowledge" onClick={event => { if (operationRef.current) event.preventDefault(); }}>Knowledge packs</Link><Link href="/" onClick={event => { if (operationRef.current) event.preventDefault(); }}><ArrowLeft size={14} />Home</Link></nav></header>
    <main id="document-workspace" className="bw-main">
      <section className="bw-title"><div><p className="bw-eyebrow">DOCUMENT WORKSPACE</p><h1>Your document. Its actual data.</h1><p>Send a PDF or image to the parser. Inspect the original response beside your source.</p></div><button className="bw-button bw-secondary" onClick={useSample} disabled={locked}>{loadingSample ? <LoaderCircle className="bw-spin" size={16} /> : <FileText size={16} />}Use sample PDF</button></section>
      <section className={`bw-upload ${dragging ? "bw-dragging" : ""}`} aria-label="Document upload" onDragOver={event => { event.preventDefault(); if (!locked) setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={event => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files.length !== 1) setError({ message: "Choose one document at a time." }); else chooseFile(event.dataTransfer.files[0]); }}>
        <input ref={inputRef} type="file" accept={SUPPORTED_DOCUMENT_ACCEPT} aria-label="Choose document" disabled={locked} onChange={event => { const selected = event.target.files?.[0]; event.target.value = ""; if (selected) chooseFile(selected); }} className="bw-file-input" />
        <div className="bw-upload-copy"><span className="bw-upload-icon">{file ? <FileText size={22} /> : <Upload size={22} />}</span><div><strong>{file?.name ?? "Drop a PDF or image here"}</strong><p>{file ? `${(file.size / 1024).toLocaleString(undefined, { maximumFractionDigits: 1 })} KB · Original file will be sent to the parsing service` : `PDF, PNG, JPEG, TIFF or WebP · Up to ${Math.round(maximumBytes / 1024 / 1024)} MB`}</p></div></div>
        <div className="bw-upload-actions"><button className="bw-button bw-secondary" onClick={() => inputRef.current?.click()} disabled={locked}>{file ? "Change file" : "Choose file"}</button>{file && <button className="bw-icon-button" aria-label="Remove document" disabled={locked} onClick={clear}><X size={17} /></button>}{busy ? <button className="bw-button bw-secondary" onClick={() => requestRef.current?.abort()}>Cancel request</button> : <button className="bw-button bw-primary" disabled={!file || locked} onClick={() => void parse()}><Play size={15} />Parse document</button>}</div>
      </section>
      {error && <section className="bw-error" role="alert"><AlertCircle size={19} /><div><strong>{error.message}</strong>{error.code && <p>{error.code}{error.status ? ` · HTTP ${error.status}` : ""}</p>}{error.details && Object.keys(error.details).length > 0 && <details><summary>API error details</summary><pre>{JSON.stringify(error.details, null, 2)}</pre></details>}</div><button className="bw-icon-button" aria-label="Dismiss error" onClick={() => setError(null)}><X size={16} /></button></section>}
      {busy && <div className="bw-progress" role="status"><LoaderCircle className="bw-spin" size={17} /><strong>Parsing document</strong><span>{elapsed}s elapsed · Waiting for the API response</span></div>}
      <div className="bw-workspace">
        <section className="bw-panel bw-source"><div className="bw-panel-heading"><h2><FileText size={17} />Original document</h2>{fileUrl && <a href={fileUrl} download={file?.name} className="bw-text-link">Download original <ArrowDownToLine size={14} /></a>}</div>
          <div ref={sourcePaneRef} className="bw-preview">{!file ? <div className="bw-empty"><FileText size={37} /><h3>Start with your source.</h3><p>The original document stays here while you inspect its parsed result.</p></div> : previewKind === "pdf" ? <Suspense fallback={<div className="bw-empty"><LoaderCircle className="bw-spin" size={24} /><p>Loading source preview…</p></div>}><PdfPreview key={fileUrl} file={file} pageNumber={Math.max(1, sourcePageNumber)} zoom={100} fitMode="width" onPageCountChange={setPreviewPages} /></Suspense> : <ImagePagePreview key={fileUrl} file={file} fileUrl={fileUrl} pageNumber={sourcePageNumber} pageCount={pageCount} previewKind={previewKind === "tiff" ? "tiff" : "raster"} zoom={100} fitMode="width" />}</div>
          <div className="bw-page-nav" aria-label="Document pages"><button className="bw-icon-button" aria-label="Previous page" disabled={activePage <= 0 || !pageCount} onClick={() => setActivePage(value => value - 1)}><ChevronLeft size={18} /></button><span>{pageCount ? `Page ${activePage + 1} of ${pageCount}` : file ? "No pages available" : "No document selected"}{selectedPage?.page_label !== undefined && <small>API page label: {fieldText(selectedPage.page_label)}</small>}</span><button className="bw-icon-button" aria-label="Next page" disabled={!pageCount || activePage >= pageCount - 1} onClick={() => setActivePage(value => value + 1)}><ChevronRight size={18} /></button></div>
        </section>
        <section className="bw-panel bw-results"><div className="bw-panel-heading"><h2><Braces size={18} />Parser response</h2>{response ? <span className="bw-response-status"><CheckCircle2 size={14} />HTTP {response.status} · {(response.rawBytes.length / 1024).toFixed(1)} KB</span> : <span className="bw-muted">No response yet</span>}</div>
          <div className="bw-tabs" role="tablist" aria-label="Result view">{(["json", "preview", "metadata"] as const).map(value => <button key={value} role="tab" id={`bw-tab-${value}`} aria-controls="bw-result-panel" aria-selected={tab === value} tabIndex={tab === value ? 0 : -1} className={tab === value ? "active" : ""} onKeyDown={event => {
            const values: OutputTab[] = ["json", "preview", "metadata"];
            const current = values.indexOf(value);
            const next = event.key === "ArrowRight" ? values[(current + 1) % values.length] : event.key === "ArrowLeft" ? values[(current + values.length - 1) % values.length] : event.key === "Home" ? values[0] : event.key === "End" ? values[values.length - 1] : null;
            if (next) { event.preventDefault(); setTab(next); document.getElementById(`bw-tab-${next}`)?.focus(); }
          }} onClick={() => setTab(value)}>{value === "json" ? "Raw API JSON" : value === "preview" ? "Structured preview" : "Metadata & warnings"}{value === "metadata" && warnings.length > 0 && <span>{warnings.length}</span>}</button>)}</div>
          <div ref={resultPaneRef} className="bw-result-content" id="bw-result-panel" role="tabpanel" aria-labelledby={`bw-tab-${tab}`}>
            {!response ? <div className="bw-empty"><Braces size={39} /><h3>{busy ? "Your parser is working." : "One response. Nothing rewritten."}</h3><p>{busy ? "The response will appear when processing completes." : "Choose a document and select Parse document. The complete API JSON will appear here."}</p></div> : tab === "json" ? <><div className="bw-result-notice"><span>Original response text · all pages and fields</span><label><input type="checkbox" checked={wrap} onChange={event => setWrap(event.target.checked)} />Wrap lines</label></div><pre className={`bw-raw-json ${wrap ? "bw-wrap" : ""}`} aria-label="Original API JSON">{response.rawText}</pre></> : tab === "metadata" ? <div className="bw-metadata"><h3>API warnings & item concerns</h3>{warnings.length ? <ul className="bw-warning-list">{warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul> : <p className="bw-view-note">The API returned no document/page warnings or item parse concerns. This is not a guarantee of extraction accuracy.</p>}<h3>Processing metadata</h3><pre className="bw-value">{JSON.stringify(result?.processing, null, 2)}</pre><h3>Document metadata</h3><pre className="bw-value">{JSON.stringify(result?.document, null, 2)}</pre><h3>Schema version</h3><pre className="bw-value">{fieldText(result?.schema_version)}</pre><p className="bw-view-note">These fields are displayed as returned. Any additional top-level fields remain in Raw API JSON.</p></div> : <div className="bw-structured"><p className="bw-preview-disclaimer">Display view of the selected API page. Tables use returned rows/cells; text is escaped. Raw API JSON and its exports remain unchanged.</p>{selectedPage ? <><div className="bw-page-info"><strong>API physical page {fieldText(selectedPage.page_index)}</strong><span>{items.length} items returned</span>{selectedPage.success === false && <span className="bw-failed">Processing unsuccessful</span>}</div>{items.length ? items.map((item, index) => <ApiItem key={index} value={item} index={index} />) : <p className="bw-view-note">The API returned no items for this page.</p>}{detectedImages.length > 0 && <section className="bw-detected"><h3>Detected image records</h3><p className="bw-view-note">Additional records returned in detected_images.</p>{detectedImages.map((item, index) => <ApiItem key={index} value={item} index={index} fallbackType="image" />)}</section>}</> : <p className="bw-view-note">No API page is available for this selection.</p>}</div>}
          </div>
          <footer className="bw-export"><span>Exports always contain the original full response.</span><div><button className="bw-button bw-secondary" disabled={!response} onClick={copyResponse}><Copy size={15} />Copy JSON</button><button className="bw-button bw-primary" disabled={!response} onClick={() => { if (response) { downloadBytes(response.rawBytes, `${stripSupportedDocumentExtension(file?.name ?? "document")}.json`); setNotice("Original API JSON downloaded."); } }}><ArrowDownToLine size={15} />Download JSON</button></div></footer>
        </section>
      </div>
      <p className="bw-footnote">Documents are processed by the parsing service. This workspace does not replace its output with browser extraction or generated content.</p>
    </main>
    {notice && <div className="bw-toast" role="status"><CheckCircle2 size={16} />{notice}</div>}
  </div>;
}
