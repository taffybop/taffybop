"use client";

import { AlertCircle, Download, FileText, Layers3, Loader2, RefreshCw, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import {
  cancelProductJob, getProductConfig, getProductDocument, getProductHistory, getProductJob,
  getProductRawPreview, getProductResult, getProductSource, isProductId, isTerminalProductJob,
  listProductDocuments, productArtifactUrl, uploadProductDocument,
} from "../lib/product-api";
import type { ProductConfig, ProductDocument, ProductHistoryEntry, ProductResult } from "../lib/product-api";
import { LLAMAPARSE_ACCEPT, validateLlamaParseFile } from "../lib/llamaparse-api";
import "./documents-workspace.css";

const message = (failure: unknown) => failure instanceof Error ? failure.message : "The document request could not be completed.";
const subscribe = (callback: () => void) => { window.addEventListener("popstate", callback); return () => window.removeEventListener("popstate", callback); };
const getQuery = () => window.location.search;
const serverQuery = () => "";
const formatDate = (value: string) => new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const statusLabels: Record<string, string> = {
  queued: "Queued", submitting: "Submitting", submission_unknown: "Submission uncertain", running: "Running",
  cancel_requested: "Cancellation requested", succeeded: "Succeeded", failed: "Failed", cancelled: "Cancelled",
};
const emptyFormat: Record<string, string> = { empty: "The backend returned an empty page list.", not_returned: "This format was not returned.", unsupported: "This format is unsupported in the stored result." };

function selectResource(documentId: string, jobId?: string, replace = false) {
  const query = new URLSearchParams(); query.set("document", documentId); if (jobId) query.set("job", jobId);
  window.history[replace ? "replaceState" : "pushState"](null, "", `${window.location.pathname}?${query}`);
  window.dispatchEvent(new PopStateEvent("popstate"));
}
function savePage(content: string, filename: string, format: "markdown" | "text") {
  const url = URL.createObjectURL(new Blob([content], { type: `${format === "markdown" ? "text/markdown" : "text/plain"};charset=utf-8` }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = filename;
  document.body.appendChild(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function DocumentsWorkspace() {
  const query = useSyncExternalStore(subscribe, getQuery, serverQuery);
  const params = new URLSearchParams(query);
  const documentId = params.get("document")?.toLowerCase() ?? null;
  const requestedJobId = params.get("job")?.toLowerCase() ?? null;
  const [config, setConfig] = useState<ProductConfig | null>(null);
  const [documents, setDocuments] = useState<ProductDocument[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [libraryBusy, setLibraryBusy] = useState(true);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [document, setDocument] = useState<ProductDocument | null>(null);
  const [history, setHistory] = useState<ProductHistoryEntry[]>([]);
  const [result, setResult] = useState<ProductResult | null>(null);
  const [source, setSource] = useState<{ artifactId: string; url: string } | null>(null);
  const [sourceFailure, setSourceFailure] = useState<{ id: string; message: string } | null>(null);
  const [detailFailure, setDetailFailure] = useState<{ id: string; message: string } | null>(null);
  const [jobFailure, setJobFailure] = useState<{ id: string; message: string } | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [libraryAttempt, setLibraryAttempt] = useState(0);
  const [detailAttempt, setDetailAttempt] = useState(0);
  const [jobAttempt, setJobAttempt] = useState(0);
  const [tab, setTab] = useState<"markdown" | "text" | "raw">("markdown");
  const [pageSelection, setPageSelection] = useState<{ resultId: string; tab: string; index: number } | null>(null);
  const [sourceSelection, setSourceSelection] = useState<{ documentId: string; page: number } | null>(null);
  const [rawPreview, setRawPreview] = useState<{ artifactId: string; content: string } | null>(null);
  const [rawFailure, setRawFailure] = useState<{ id: string; message: string } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const uploadController = useRef<AbortController | null>(null);
  const libraryController = useRef<AbortController | null>(null);
  const cancelController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController(); libraryController.current = controller;
    void Promise.all([getProductConfig({ signal: controller.signal }), listProductDocuments(null, { signal: controller.signal })])
      .then(([configuration, listing]) => { if (!controller.signal.aborted) { setConfig(configuration); setDocuments(listing.documents); setNextCursor(listing.next_cursor); } })
      .catch((failure: unknown) => { if (!controller.signal.aborted) { setConfig(null); setLibraryError(message(failure)); } })
      .finally(() => { if (!controller.signal.aborted) setLibraryBusy(false); });
    return () => controller.abort();
  }, [libraryAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    cancelController.current?.abort();
    if (!documentId) return () => controller.abort();
    if (!isProductId(documentId)) return () => controller.abort();
    void Promise.all([getProductDocument(documentId, { signal: controller.signal }), getProductHistory(documentId, { signal: controller.signal })])
      .then(([saved, entries]) => { if (!controller.signal.aborted) { setDocument(saved); setHistory(entries.jobs); setDetailFailure(null); } })
      .catch((failure: unknown) => { if (!controller.signal.aborted) setDetailFailure({ id: documentId, message: message(failure) }); });
    return () => controller.abort();
  }, [documentId, detailAttempt]);

  const currentDocument = document?.id === documentId ? document : null;
  const ownedHistory = history.filter((entry) => entry.job.document_id === documentId);
  const selectedEntry = ownedHistory.find((entry) => entry.job.id === requestedJobId) ?? (!requestedJobId ? ownedHistory[0] : undefined);
  const selectedJobId = selectedEntry?.job.id;
  const currentJob = selectedEntry?.job.document_id === documentId ? selectedEntry.job : null;
  const currentResult = result && result.job_id === selectedJobId && result.document_id === documentId ? result : null;
  const sourceUrl = source?.artifactId === currentDocument?.source.id ? source?.url : null;

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    if (currentDocument) {
      void getProductSource(currentDocument.source, { signal: controller.signal }).then((blob) => {
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob); setSource({ artifactId: currentDocument.source.id, url: objectUrl }); setSourceFailure(null);
      }).catch((failure: unknown) => { if (!controller.signal.aborted) setSourceFailure({ id: currentDocument.source.id, message: message(failure) }); });
    }
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [currentDocument]);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!selectedJobId || !documentId) return () => controller.abort();
    async function poll() {
      try {
        const job = await getProductJob(selectedJobId!, { signal: controller.signal });
        if (job.document_id !== documentId) throw new Error("The saved job does not belong to this document.");
        const refreshed = await getProductHistory(documentId!, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setJobFailure(null);
        setHistory(refreshed.jobs.map((entry) => entry.job.id === job.id ? { ...entry, job } : entry));
        if (job.result_id) {
          const parsed = await getProductResult(job.result_id, { signal: controller.signal });
          if (parsed.job_id !== job.id || parsed.document_id !== documentId) throw new Error("The saved result does not match this document and job.");
          if (!controller.signal.aborted) setResult(parsed);
        }
        if (!isTerminalProductJob(job) && !controller.signal.aborted) timer = setTimeout(() => void poll(), 2_000);
      } catch (failure) { if (!controller.signal.aborted) setJobFailure({ id: selectedJobId!, message: message(failure) }); }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [documentId, selectedJobId, jobAttempt]);

  useEffect(() => {
    const controller = new AbortController();
    if (tab === "raw" && currentResult) {
      void getProductRawPreview(currentResult.raw.id, { signal: controller.signal })
        .then((value) => { if (!controller.signal.aborted) setRawPreview({ artifactId: currentResult.raw.id, content: value }); setRawFailure(null); })
        .catch((failure: unknown) => { if (!controller.signal.aborted) setRawFailure({ id: currentResult.raw.id, message: message(failure) }); });
    }
    return () => controller.abort();
  }, [tab, currentResult]);
  useEffect(() => () => { uploadController.current?.abort(); libraryController.current?.abort(); cancelController.current?.abort(); }, []);

  async function upload(file: File | undefined) {
    if (!file || uploading || !config?.uploads_enabled) return;
    const controller = new AbortController(); uploadController.current = controller;
    setUploadError(null);
    try {
      validateLlamaParseFile(file, 10 * 1024 * 1024);
      setUploading(true);
      const saved = await uploadProductDocument(file, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setDocuments((entries) => [saved, ...entries.filter((entry) => entry.id !== saved.id)]);
      selectResource(saved.id); setDetailAttempt((value) => value + 1);
    } catch (failure) { if (!controller.signal.aborted) setUploadError(message(failure)); }
    finally { if (!controller.signal.aborted) setUploading(false); if (input.current) input.current.value = ""; }
  }
  async function loadMore() {
    if (!nextCursor || libraryBusy) return;
    const controller = new AbortController(); libraryController.current?.abort(); libraryController.current = controller;
    setLibraryBusy(true); setLibraryError(null);
    try {
      const listing = await listProductDocuments(nextCursor, { signal: controller.signal });
      if (!controller.signal.aborted) {
        setDocuments((entries) => [...entries, ...listing.documents.filter((entry) => !entries.some((existing) => existing.id === entry.id))]);
        setNextCursor(listing.next_cursor);
      }
    } catch (failure) { if (!controller.signal.aborted) setLibraryError(message(failure)); }
    finally { if (!controller.signal.aborted) setLibraryBusy(false); }
  }
  async function cancel() {
    if (!currentJob || cancellingId === currentJob.id || isTerminalProductJob(currentJob)) return;
    const controller = new AbortController(); cancelController.current = controller; setCancellingId(currentJob.id); setJobFailure(null);
    try {
      const job = await cancelProductJob(currentJob.id, { signal: controller.signal });
      if (!controller.signal.aborted) { setHistory((entries) => entries.map((entry) => entry.job.id === job.id ? { ...entry, job } : entry)); setJobAttempt((value) => value + 1); }
    } catch (failure) { if (!controller.signal.aborted) setJobFailure({ id: currentJob.id, message: message(failure) }); }
    finally { setCancellingId(null); }
  }
  const cancelling = cancellingId === currentJob?.id;
  const pageIndex = pageSelection?.resultId === currentResult?.id && pageSelection?.tab === tab ? pageSelection.index : 0;
  const setPageIndex = (index: number) => setPageSelection(currentResult ? { resultId: currentResult.id, tab, index } : null);
  const sourcePage = sourceSelection?.documentId === currentDocument?.id ? sourceSelection?.page ?? 1 : 1;
  const detailError = documentId && !isProductId(documentId) ? "This saved document identifier is invalid." : detailFailure?.id === documentId ? detailFailure?.message : null;
  const sourceError = sourceFailure?.id === currentDocument?.source.id ? sourceFailure?.message : null;
  const jobError = jobFailure?.id === currentJob?.id ? jobFailure?.message : null;
  const rawError = rawFailure?.id === currentResult?.raw.id ? rawFailure?.message : null;
  function refreshLibrary() { setLibraryBusy(true); setLibraryError(null); setLibraryAttempt((value) => value + 1); }
  const section = currentResult && tab !== "raw" ? currentResult[tab] : null;
  const activePage = section?.pages[Math.min(pageIndex, Math.max(0, section.pages.length - 1))];
  const rawArtifact = currentResult?.raw ?? currentJob?.raw_response;

  return <div className="pd-workspace">
    <header className="pd-header"><Link href="/" className="pd-brand"><Layers3 size={21} aria-hidden="true" />TaffyBop</Link><nav aria-label="Workspace"><Link href="/documents" aria-current="page">Documents</Link><button disabled title="Extraction is not available yet">Extract</button><button disabled title="Templates are not available yet">Templates</button></nav><span className="pd-local">Local development</span></header>
    <main className="pd-layout">
      <aside className="pd-library" aria-label="Saved document library">
        <div className="pd-library-title"><div><p className="pd-eyebrow">YOUR WORKSPACE</p><h1>Documents</h1></div><button className="pd-icon" aria-label="Refresh library" disabled={libraryBusy} onClick={refreshLibrary}><RefreshCw size={16} /></button></div>
        <p className="pd-subtitle">Saved files and parsing history.</p>
        <input className="pd-hidden-input" type="file" ref={input} accept={LLAMAPARSE_ACCEPT} aria-label="Choose a PDF, PNG or JPEG to save" disabled={!config?.uploads_enabled || uploading} onChange={(event) => void upload(event.target.files?.[0])} />
        <button className="pd-primary pd-upload" disabled={!config?.uploads_enabled || uploading} onClick={() => input.current?.click()}>{uploading ? <Loader2 size={16} className="pd-spin" /> : <Upload size={16} />} {uploading ? "Saving document…" : "Upload document"}</button>
        <p className="pd-hint">PDF, PNG or JPEG · 10 MiB · 10 pages<br />Saving a file does not start parsing.</p>
        {uploadError && <p className="pd-error" role="alert">{uploadError}</p>}
        {libraryError && <div className="pd-error" role="alert"><p>{libraryError}</p><button className="pd-text" onClick={refreshLibrary}>Try again</button></div>}
        <div className="pd-document-list">{documents.map((entry) => <button key={entry.id} className={`pd-document ${entry.id === documentId ? "pd-document-selected" : ""}`} aria-current={entry.id === documentId ? "true" : undefined} onClick={() => selectResource(entry.id)}><FileText size={18} aria-hidden="true" /><span><strong>{entry.display_name}</strong><small>{entry.page_count} {entry.page_count === 1 ? "page" : "pages"} · {formatDate(entry.created_at)}</small></span></button>)}</div>
        {!documents.length && !libraryBusy && !libraryError && <p className="pd-library-empty">No saved documents yet.</p>}
        {libraryBusy && <p role="status" className="pd-hint">Loading library…</p>}
        {nextCursor && <button className="pd-secondary" disabled={libraryBusy} onClick={() => void loadMore()}>Load more documents</button>}
      </aside>
      <section className="pd-main" aria-label="Saved document workspace">
        <div className="pd-main-heading"><div><p className="pd-eyebrow">DOCUMENT WORKSPACE</p><h2>{currentDocument?.display_name ?? "A place for your documents"}</h2></div>{currentDocument && <a className="pd-secondary" href={productArtifactUrl(currentDocument.source.id, true)} download={currentDocument.display_name}><Download size={15} />Original source</a>}</div>
        <div className="pd-banner" role="status"><AlertCircle size={18} aria-hidden="true" /><span><strong>Live parsing is unavailable</strong><span>{config?.disabled_reason ?? "Connect to an explicitly configured local document server to save and reopen files."}</span></span></div>
        {detailError && <div className="pd-error" role="alert"><p>{detailError}</p><button className="pd-text" onClick={() => setDetailAttempt((value) => value + 1)}>Reload document</button></div>}
        {!currentDocument ? <div className="pd-welcome"><div className="pd-welcome-icon"><FileText size={35} strokeWidth={1.3} /></div><h3>{documentId && !detailError ? "Opening saved document…" : "Upload a document or open your library"}</h3><p>Keep original files, inspect saved parsing jobs and reopen their results. Files stay available after refresh.</p><span>Extraction and templates are not available yet.</span></div> : <>
          <div className="pd-run-toolbar"><label>Parsing mode<select aria-label="Parsing mode" value={currentJob?.settings.mode ?? config?.default_mode ?? "cost_effective"} disabled>{(config?.modes ?? [{ id: "cost_effective", label: "Cost-effective" }]).map((option) => <option value={option.id} key={option.id}>{option.label}</option>)}</select></label><label className="pd-history-select">Saved run<select aria-label="Saved parsing run" value={selectedJobId ?? ""} disabled={!ownedHistory.length} onChange={(event) => { selectResource(currentDocument.id, event.target.value); setPageIndex(0); }}><option value="" disabled>{ownedHistory.length ? "Select a run" : "No saved parsing runs"}</option>{ownedHistory.map((entry) => <option key={entry.job.id} value={entry.job.id}>{statusLabels[entry.job.status]} · {entry.evidence_kind === "simulation" ? "Simulation" : "Unverified"} · {entry.job.id.slice(0, 8)}</option>)}</select></label><button className="pd-primary" disabled title={config?.disabled_reason}>Parse document</button><button className="pd-icon" aria-label="Reload document and runs" onClick={() => { setDetailAttempt((value) => value + 1); setJobAttempt((value) => value + 1); }}><RefreshCw size={16} /></button></div>
          {requestedJobId && !selectedEntry && <p className="pd-error" role="alert">This run is not available in this document&apos;s saved history.</p>}
          {currentJob && <div className="pd-run-info"><div className="pd-evidence"><strong>{selectedEntry?.evidence_kind === "simulation" ? "Simulation — not a live parse" : "Unverified run — live provenance not established"}</strong><span>{statusLabels[currentJob.status]} · Job {currentJob.id}</span></div><div className="pd-usage"><span>Estimated credits: {currentJob.usage.estimated_credits ?? "Unknown"}</span><span>Actual provider credits: {currentJob.usage.actual_credits ?? "Unknown"}</span></div>{!isTerminalProductJob(currentJob) && <button className="pd-text" disabled={cancelling || Boolean(currentJob.cancellation_requested_at)} onClick={() => void cancel()}>{cancelling ? "Requesting…" : "Request cancellation"}</button>}</div>}
          {currentJob?.status === "submission_unknown" && <p className="pd-hint">Acceptance is uncertain. Capacity remains held; this job will not be resubmitted automatically.</p>}
          {currentJob?.cancellation_requested_at && !currentJob.cancellation_confirmed && !isTerminalProductJob(currentJob) && <p className="pd-hint">Cancellation has been requested. It is not confirmed until the worker records a terminal response.</p>}
          {currentJob?.error && <p className="pd-error" role="alert">{currentJob.error.message}</p>}
          {jobError && <div className="pd-error" role="alert"><span>{jobError}</span> <button className="pd-text" onClick={() => setJobAttempt((value) => value + 1)}>Check saved job</button></div>}
          <div className="pd-panels">
            <section className="pd-panel" aria-label="Source document"><div className="pd-panel-toolbar"><h3>Source document</h3><label>Page <select aria-label="Source page" value={sourcePage} onChange={(event) => setSourceSelection({ documentId: currentDocument.id, page: Number(event.target.value) })}>{Array.from({ length: currentDocument.page_count }, (_, index) => <option value={index + 1} key={index}>{index + 1}</option>)}</select><span> of {currentDocument.page_count}</span></label></div><div className="pd-preview">{sourceError ? <p className="pd-empty" role="alert">{sourceError}</p> : !sourceUrl ? <p className="pd-empty" role="status">Loading original source…</p> : currentDocument.source.media_type === "application/pdf" ? <object key={`${sourceUrl}-${sourcePage}`} data={`${sourceUrl}#page=${sourcePage}`} type="application/pdf" aria-label={`Source PDF: ${currentDocument.display_name}, page ${sourcePage}`}><p className="pd-empty">PDF preview unavailable. Use Original source to open the saved file.</p></object>
              // Private, authorized bytes are previewed locally without image optimization.
              // eslint-disable-next-line @next/next/no-img-element
              : <img src={sourceUrl} alt={`Source document: ${currentDocument.display_name}`} />}</div></section>
            <section className="pd-panel pd-result-panel" aria-label="Saved parsing result"><div className="pd-panel-toolbar"><div className="pd-tabs" role="tablist" aria-label="Result format">{([ ["markdown", "Markdown"], ["text", "Text"], ["raw", "Raw JSON"] ] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={tab === id} onClick={() => { setTab(id); setPageIndex(0); }}>{label}</button>)}</div>{rawArtifact && <a href={productArtifactUrl(rawArtifact.id, true)} className="pd-icon" download aria-label="Download original raw JSON" title="Download original raw JSON"><Download size={16} /></a>}</div>
              {section?.pages.length ? <div className="pd-page-toolbar"><label>Result page <select aria-label="Result page occurrence" value={Math.min(pageIndex, section.pages.length - 1)} onChange={(event) => setPageIndex(Number(event.target.value))}>{section.pages.map((page, index) => <option key={index} value={index}>Page {page.page_number} · entry {index + 1}</option>)}</select></label><button className="pd-text" disabled={!activePage} onClick={() => { if (activePage && tab !== "raw") savePage(activePage.content, `${currentDocument.display_name}.entry-${pageIndex + 1}.${tab === "markdown" ? "md" : "txt"}`, tab); }}>Download page</button></div> : null}
              <div className="pd-result-content" role="tabpanel" aria-label={tab === "raw" ? "Original raw JSON" : `${tab === "markdown" ? "Markdown" : "Text"} result`}>{tab === "raw" ? rawError ? <p className="pd-empty" role="alert">{rawError}</p> : rawPreview && rawPreview.artifactId === currentResult?.raw.id ? <pre>{rawPreview.content}</pre> : <p className="pd-empty">{currentResult ? "Loading original raw JSON…" : "No successful result is available. Terminal raw output can be downloaded above when present."}</p> : activePage ? <pre data-testid="result-page-content">{activePage.content}</pre> : <p className="pd-empty">{section ? emptyFormat[section.state] : currentJob && !isTerminalProductJob(currentJob) ? "Waiting for the saved job. Status checks read this app’s durable records." : "No saved parsing result. Uploading saves the original file without running a provider."}</p>}</div>
              <div className="pd-result-footer"><span>{currentResult ? "Original stored output · no corrections applied" : "Results appear only when stored by the backend"}</span>{rawArtifact && <a href={productArtifactUrl(rawArtifact.id, true)} download>Original raw JSON</a>}</div>
            </section>
          </div>
          {currentResult?.warnings.length ? <div className="pd-warnings"><strong>Backend warnings</strong><ul>{currentResult.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div> : null}
        </>}
        <footer className="pd-footer"><span>Saved locally · Provider actions remain disabled</span><Link href="/privacy">Privacy</Link></footer>
      </section>
    </main>
  </div>;
}
