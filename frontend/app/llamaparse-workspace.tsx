"use client";

import { AlertCircle, ArrowRight, Check, ChevronDown, Copy, Download, FileText, Layers3, Loader2, RefreshCw, Square, Upload, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  createLlamaParseJob, getLlamaParseConfig, getLlamaParseJobError, getLlamaParsePages,
  getLlamaParseStatus, LLAMAPARSE_ACCEPT, LlamaParseApiError, pollLlamaParseJob, validateLlamaParseFile,
} from "../lib/llamaparse-api";
import type { LlamaParseConfig, LlamaParseJob, LlamaParseMode, LlamaParseResponse } from "../lib/llamaparse-api";
import "./llamaparse-workspace.css";

type Phase = "idle" | "uploading" | "waiting" | "paused" | "check_error" | "complete" | "failed" | "submit_error";
type Tab = "markdown" | "text" | "raw";
interface SubmittedJob extends LlamaParseJob { filename: string; modeDetails: LlamaParseMode }
const tabs: { id: Tab; label: string }[] = [{ id: "markdown", label: "Markdown" }, { id: "text", label: "Text" }, { id: "raw", label: "Raw JSON" }];
const message = (error: unknown) => error instanceof Error ? error.message : "Something went wrong. Please try again.";
const sizeLabel = (bytes: number) => bytes >= 1024 * 1024 ? `${(bytes / (1024 * 1024)).toFixed(1).replace(/\.0$/, "")} MB` : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;

function saveFile(contents: string | Uint8Array, filename: string, type: string) {
  const part = typeof contents === "string" ? contents : new Uint8Array(contents).buffer;
  const url = URL.createObjectURL(new Blob([part], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

export function LlamaParseWorkspace() {
  const [config, setConfig] = useState<LlamaParseConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [configAttempt, setConfigAttempt] = useState(0);
  const [source, setSource] = useState<{ file: File; url: string } | null>(null);
  const [mode, setMode] = useState("cost_effective");
  const [phase, setPhase] = useState<Phase>("idle");
  const [job, setJob] = useState<SubmittedJob | null>(null);
  const [response, setResponse] = useState<LlamaParseResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("markdown");
  const [pageIndex, setPageIndex] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const busy = phase === "uploading" || phase === "waiting";
  const hasUnfinishedJob = Boolean(job) && (phase === "paused" || phase === "check_error");

  useEffect(() => {
    const controller = new AbortController();
    void getLlamaParseConfig({ signal: controller.signal }).then((value) => {
      if (controller.signal.aborted) return;
      setConfig(value);
      setMode(value.default_mode);
      setConfigError(null);
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setConfigError(message(failure));
    });
    return () => controller.abort();
  }, [configAttempt]);

  useEffect(() => () => { if (source) URL.revokeObjectURL(source.url); }, [source]);
  useEffect(() => () => { generation.current += 1; activeRequest.current?.abort(); }, []);

  function clearResult() {
    generation.current += 1;
    activeRequest.current?.abort();
    setJob(null);
    setResponse(null);
    setError(null);
    setNotice(null);
    setPhase("idle");
    setPageIndex(0);
  }

  function chooseFile(file: File | undefined) {
    if (!file || busy || !config) return;
    clearResult();
    try {
      validateLlamaParseFile(file, config.max_upload_bytes);
      setSource({ file, url: URL.createObjectURL(file) });
    } catch (failure) {
      setSource(null);
      setError(message(failure));
    }
    if (inputRef.current) inputRef.current.value = "";
  }

  async function checkJob(existing: SubmittedJob, sequence: number) {
    const controller = new AbortController();
    activeRequest.current = controller;
    setPhase("waiting");
    setError(null);
    setNotice(null);
    try {
      const result = await pollLlamaParseJob(existing.job_id, {
        signal: controller.signal,
        onResponse: (value) => { if (generation.current === sequence) setResponse(value); },
      });
      if (generation.current !== sequence) return;
      const status = getLlamaParseStatus(result.data);
      setPhase(status === "COMPLETED" ? "complete" : "failed");
      if (status !== "COMPLETED") setError(getLlamaParseJobError(result.data) ?? (status === "CANCELLED" ? "LlamaParse reports that this job was cancelled." : "LlamaParse could not parse this document."));
    } catch (failure) {
      if (generation.current !== sequence || controller.signal.aborted) return;
      setPhase("check_error");
      setError(message(failure));
    }
  }

  async function parse() {
    if (!source || !config?.configured || config.submission_enabled === false || busy || hasUnfinishedJob) return;
    const selectedMode = config.modes.find((value) => value.id === mode);
    if (!selectedMode) return;
    clearResult();
    const sequence = generation.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    setPhase("uploading");
    let accepted: LlamaParseJob;
    try {
      accepted = await createLlamaParseJob(source.file, mode, config, { signal: controller.signal });
    } catch (failure) {
      if (generation.current !== sequence) return;
      setPhase("submit_error");
      const uncertain = failure instanceof LlamaParseApiError && ["network_error", "request_timeout"].includes(failure.code);
      setError(`${message(failure)}${uncertain ? " If the upload reached the provider, it may still use credits. No automatic resubmission was made." : ""}`);
      return;
    }
    if (generation.current !== sequence) return;
    const submitted = { ...accepted, filename: source.file.name, modeDetails: selectedMode };
    setJob(submitted);
    await checkJob(submitted, sequence);
  }

  function stopWaiting() {
    generation.current += 1;
    activeRequest.current?.abort();
    setPhase("paused");
    setError(null);
    setNotice(null);
  }

  const format = response && tab !== "raw" ? getLlamaParsePages(response.data, tab) : null;
  const currentPage = format?.pages[Math.min(pageIndex, Math.max(0, format.pages.length - 1))];
  const content = response && tab === "raw" ? response.rawText : phase === "complete" ? currentPage?.content : undefined;
  const formatName = tab === "markdown" ? "Markdown" : "text";
  const filenameBase = (job?.filename ?? "document").replace(/\.(pdf|png|jpe?g)$/i, "");
  const pageSuffix = (format?.pages.length ?? 0) > 1 && currentPage ? `.page-${currentPage.pageNumber}` : "";

  async function copy() {
    if (content === undefined) return;
    const sequence = generation.current;
    try {
      await navigator.clipboard.writeText(content);
      if (generation.current === sequence) setNotice("Copied to clipboard.");
    } catch {
      if (generation.current === sequence) setNotice("Clipboard access is unavailable. Use Download to save the result.");
    }
  }

  function download() {
    if (!response || content === undefined) return;
    if (tab === "raw") saveFile(response.rawBytes, `${filenameBase}.json`, response.contentType);
    else saveFile(content, `${filenameBase}${pageSuffix}.${tab === "markdown" ? "md" : "txt"}`, `${tab === "markdown" ? "text/markdown" : "text/plain"};charset=utf-8`);
    setNotice("Download started.");
  }

  const progressText = phase === "uploading" ? "Uploading to LlamaParse…"
    : phase === "waiting" ? "Waiting for the result from LlamaParse…"
      : phase === "paused" ? "Waiting stopped on this device. The provider job may still be running."
        : phase === "check_error" ? "Status check interrupted. Check this job again without uploading it again."
          : phase === "complete" ? "Parsing complete" : phase === "failed" ? "Provider job ended" : null;

  return (
    <div className="lp-workspace">
      <header className="lp-header">
        <Link className="lp-brand" href="/" aria-label="TaffyBop home"><span><Layers3 size={20} aria-hidden="true" /></span>TaffyBop</Link>
        <span className="lp-provider"><span aria-hidden="true" /> Powered by LlamaParse</span>
      </header>
      <main className="lp-main">
        <div className="lp-intro"><p className="lp-eyebrow">DOCUMENT PARSING, SIMPLIFIED</p><h1>Your document.<br className="lp-mobile-break" /> Ready to use.</h1><p>Turn PDFs and images into Markdown, text and JSON.</p></div>

        {!config && <div className={`lp-banner ${configError ? "lp-banner-error" : ""}`} role={configError ? "alert" : "status"}>
          {configError ? <AlertCircle size={18} aria-hidden="true" /> : <Loader2 size={18} className="lp-spin" aria-hidden="true" />}
          <span>{configError ?? "Connecting to the parsing server…"}</span>
          {configError && <button className="lp-text-button" onClick={() => { setConfigError(null); setConfigAttempt((value) => value + 1); }}>Try again</button>}
        </div>}
        {config?.submission_enabled === false
          ? <div className="lp-banner lp-banner-setup" role="status"><AlertCircle size={20} aria-hidden="true" /><strong>Parsing is unavailable in this session</strong></div>
          : config && !config.configured && <div className="lp-banner lp-banner-setup" role="status"><AlertCircle size={20} aria-hidden="true" /><div><strong>LlamaCloud key not configured on the server</strong><p>Add the key in the server environment, then reload this page. Your key stays on the server.</p></div></div>}

        <section className="lp-setup" aria-label="Prepare document">
          <div className="lp-upload-section">
            <div className="lp-section-label"><span>01</span><h2>Choose a document</h2></div>
            <input ref={inputRef} className="lp-file-input" type="file" accept={LLAMAPARSE_ACCEPT} disabled={busy || !config} onChange={(event) => chooseFile(event.target.files?.[0])} aria-label="Choose a PDF, PNG or JPEG" />
            <div className={`lp-upload ${dragging ? "lp-upload-active" : ""} ${source ? "lp-upload-selected" : ""}`}
              onDragOver={(event) => { event.preventDefault(); if (!busy && config) setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => { event.preventDefault(); setDragging(false); if (event.dataTransfer.files.length > 1) { if (!busy) setError("Choose one document at a time."); return; } chooseFile(event.dataTransfer.files[0]); }}>
              <span className="lp-upload-icon">{source ? <FileText size={25} aria-hidden="true" /> : <Upload size={25} aria-hidden="true" />}</span>
              {source ? <><strong className="lp-filename">{source.file.name}</strong><span>{sizeLabel(source.file.size)} · Ready to parse</span></> : <><strong>Drop your document here</strong><span>PDF, PNG or JPEG{config ? ` · Up to ${sizeLabel(config.max_upload_bytes)}` : ""}</span></>}
              <div className="lp-upload-actions"><button className="lp-secondary" disabled={busy || !config} onClick={() => inputRef.current?.click()}>{source ? "Choose another file" : "Browse files"}</button>{source && <button className="lp-icon-button" disabled={busy} onClick={() => { clearResult(); setSource(null); }} aria-label="Remove selected file"><X size={17} /></button>}</div>
            </div>
            <p className="lp-source-note">Files are sent to LlamaCloud for processing.{config ? ` Maximum ${config.max_pages} pages per document.` : ""}</p>
          </div>
          <div className="lp-mode-section">
            <div className="lp-section-label"><span>02</span><h2>Choose a parsing mode</h2></div>
            <fieldset className="lp-modes" disabled={busy || !config}><legend className="lp-sr-only">Parsing mode</legend>
              {config?.modes.map((option) => <label className={`lp-mode ${mode === option.id ? "lp-mode-selected" : ""}`} key={option.id}>
                <input type="radio" name="llamaparse-mode" value={option.id} checked={mode === option.id} onChange={() => { clearResult(); setMode(option.id); }} />
                <span className="lp-mode-copy"><strong>{option.label}</strong><span>{option.description}</span></span>
                <span className="lp-credits"><strong>{option.credits_per_page}</strong><span>credits / page</span></span>
              </label>)}
              {!config && <div className="lp-mode-placeholder">Parsing modes will appear when the server is available.</div>}
            </fieldset>
            <div className="lp-parse-row"><p>Credits are usage estimates.<br />Your account balance is not shown here.</p><button className="lp-primary" disabled={!source || !config?.configured || config.submission_enabled === false || busy || hasUnfinishedJob || !config.modes.some((option) => option.id === mode)} title={hasUnfinishedJob ? "Check the existing job below to avoid submitting it again." : undefined} onClick={() => void parse()}>{busy ? <><Loader2 size={18} className="lp-spin" aria-hidden="true" />{phase === "uploading" ? "Uploading" : "Parsing"}</> : <>Parse document <ArrowRight size={18} aria-hidden="true" /></>}</button></div>
          </div>
        </section>

        {error && <div className="lp-banner lp-banner-error" role="alert"><AlertCircle size={19} aria-hidden="true" /><span>{error}</span></div>}
        {progressText && <div className={`lp-progress ${phase === "complete" ? "lp-progress-complete" : ""}`} role="status" aria-live="polite">
          <div>{busy ? <Loader2 className="lp-spin" size={18} aria-hidden="true" /> : phase === "complete" ? <Check size={18} aria-hidden="true" /> : <FileText size={18} aria-hidden="true" />}<span>{progressText}</span></div>
          {phase === "waiting" && <button className="lp-text-button" onClick={stopWaiting}><Square size={13} aria-hidden="true" /> Stop waiting</button>}
          {(phase === "paused" || phase === "check_error") && job && <button className="lp-text-button" onClick={() => { generation.current += 1; void checkJob(job, generation.current); }}><RefreshCw size={15} aria-hidden="true" /> Check existing job</button>}
        </div>}
        {job && <p className="lp-job-detail">{job.modeDetails.label} · {job.page_count === null ? "Page count not returned" : `${job.page_count} ${job.page_count === 1 ? "page" : "pages"}`} · {job.estimated_credits === null ? "Credit estimate not returned" : `${job.estimated_credits} estimated credits`}<span>Job {job.job_id}</span></p>}

        <section className="lp-results" aria-label="Document and parsing result">
          <div className="lp-source-panel"><div className="lp-panel-title"><FileText size={16} aria-hidden="true" /><h2>Source document</h2><span>{source ? source.file.name.split(".").pop()?.toUpperCase() : "PREVIEW"}</span></div>
            <div className="lp-source-preview">
              {!source ? <div className="lp-empty"><div className="lp-paper-icon"><FileText size={31} strokeWidth={1.3} aria-hidden="true" /></div><strong>A document is all you need</strong><p>Choose a file above to preview it here.</p></div>
                : /\.pdf$/i.test(source.file.name) ? <object data={source.url} type="application/pdf" aria-label={`Source PDF: ${source.file.name}`}><div className="lp-empty"><strong>PDF preview unavailable</strong><a href={source.url} target="_blank" rel="noreferrer">Open the selected PDF</a></div></object>
                  // The object URL is the user's local file; no image optimization or upload is needed.
                  // eslint-disable-next-line @next/next/no-img-element
                  : <img src={source.url} alt={`Source document: ${source.file.name}`} />}
            </div>
          </div>
          <div className="lp-result-panel">
            <div className="lp-result-toolbar"><div className="lp-tabs" role="tablist" aria-label="Result format">{tabs.map((item, index) => <button key={item.id} id={`lp-tab-${item.id}`} role="tab" type="button" aria-selected={tab === item.id} aria-controls="lp-result-content" tabIndex={tab === item.id ? 0 : -1} onClick={() => { setTab(item.id); setPageIndex(0); setNotice(null); }} onKeyDown={(event) => {
              let target: number | null = null;
              if (event.key === "ArrowRight") target = (index + 1) % tabs.length;
              if (event.key === "ArrowLeft") target = (index + tabs.length - 1) % tabs.length;
              if (event.key === "Home") target = 0;
              if (event.key === "End") target = tabs.length - 1;
              if (target !== null) { event.preventDefault(); setTab(tabs[target].id); setPageIndex(0); setNotice(null); document.getElementById(`lp-tab-${tabs[target].id}`)?.focus(); }
            }}>{item.label}</button>)}</div><div className="lp-result-actions"><button className="lp-icon-button" aria-label={`Copy ${tab === "raw" ? "raw JSON" : formatName}`} title="Copy result" disabled={content === undefined} onClick={() => void copy()}><Copy size={16} aria-hidden="true" /></button><button className="lp-icon-button" aria-label={`Download ${tab === "raw" ? "raw JSON" : formatName}`} title="Download result" disabled={content === undefined} onClick={download}><Download size={16} aria-hidden="true" /></button></div></div>
            {phase === "complete" && format?.kind === "available" && <div className="lp-page-row"><label htmlFor="lp-result-page">Provider page</label><span className="lp-select-wrap"><select id="lp-result-page" value={Math.min(pageIndex, format.pages.length - 1)} onChange={(event) => { setPageIndex(Number(event.target.value)); setNotice(null); }}>{format.pages.map((page, index) => <option key={index} value={index}>Page {page.pageNumber}</option>)}</select><ChevronDown size={13} aria-hidden="true" /></span><span>Exact returned {formatName}</span></div>}
            <div id="lp-result-content" className="lp-result-content" role="tabpanel" aria-labelledby={`lp-tab-${tab}`} tabIndex={0}>
              {content !== undefined ? content.length > 0 ? <pre>{content}</pre> : <div className="lp-empty"><strong>Empty {formatName} page</strong><p>The provider returned an empty string for this page.</p></div>
                : phase === "complete" ? <div className="lp-empty"><FileText size={28} strokeWidth={1.4} aria-hidden="true" /><strong>{format?.kind === "unsupported" ? "Unrecognized format" : `${tab === "raw" ? "JSON" : formatName === "text" ? "Text" : "Markdown"} not returned`}</strong><p>{format?.kind === "unsupported" ? "This output cannot be displayed as pages. The original response is available in Raw JSON." : "LlamaParse did not return pages in this format. Check the other tabs or the raw response."}</p></div>
                  : <div className="lp-empty"><div className="lp-result-symbol" aria-hidden="true">{tab === "raw" ? "{ }" : tab === "markdown" ? "M↓" : "Aa"}</div><strong>{busy ? "Your result is on its way" : "The result will appear here"}</strong><p>{busy ? "We’re checking the provider’s job status. You can stop waiting without cancelling the job." : "Parse a document to see the output returned by LlamaParse."}</p></div>}
            </div>
            <div className="lp-result-footer"><span>{tab === "raw" ? "Original API response · no reformatting" : "Copy and download the selected page · no added separators"}</span><span role="status" aria-live="polite">{notice}</span></div>
          </div>
        </section>
        <footer className="lp-footer"><span>TaffyBop · Simple tools for useful documents.</span><span>Cloud processing by LlamaParse</span></footer>
      </main>
    </div>
  );
}

export default LlamaParseWorkspace;
