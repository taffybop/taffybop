import { AlertCircle, Download, FileText, Layers3, RefreshCw, Upload } from "lucide-react";
import Link from "./link";
import "../app/documents-workspace.css";

const unavailable = "This action is unavailable in the UI preview.";

/** Static presentation only: no document inputs, API clients or stored results. */
export function PreviewWorkspace() {
  return <div className="pd-workspace">
    <header className="pd-header">
      <Link href="/" className="pd-brand"><Layers3 size={21} aria-hidden="true" />TaffyBop</Link>
      <nav aria-label="Workspace">
        <Link href="/documents" aria-current="page">Documents</Link>
        <button disabled title={unavailable}>Extract</button>
        <button disabled title={unavailable}>Templates</button>
      </nav>
      <span className="pd-local">UI preview</span>
    </header>
    <main className="pd-layout">
      <aside className="pd-library" aria-label="Document library preview">
        <div className="pd-library-title">
          <div><p className="pd-eyebrow">WORKSPACE PREVIEW</p><h1>Documents</h1></div>
          <button className="pd-icon" aria-label="Refresh library" disabled title={unavailable}><RefreshCw size={16} aria-hidden="true" /></button>
        </div>
        <p className="pd-subtitle">Explore the document workspace layout.</p>
        <button className="pd-primary pd-upload" disabled title={unavailable}><Upload size={16} aria-hidden="true" />Upload document</button>
        <p className="pd-hint">Uploads are disabled in this preview.<br />No files are uploaded or saved.</p>
        <p className="pd-library-empty">Saved history is unavailable. No documents are stored in this preview.</p>
      </aside>
      <section className="pd-main" aria-label="Document workspace preview">
        <div className="pd-main-heading">
          <div><p className="pd-eyebrow">DOCUMENT WORKSPACE</p><h2>Your document workspace</h2></div>
          <button className="pd-secondary" disabled title={unavailable}><Download size={15} aria-hidden="true" />Original source</button>
        </div>
        <div className="pd-banner" role="status" id="preview-explanation">
          <AlertCircle size={18} aria-hidden="true" />
          <span><strong>UI preview — document actions are disabled</strong><span>Uploads, saved history, parsing, extraction and templates are unavailable in this published preview. No documents are uploaded, stored or processed.</span></span>
        </div>
        <div className="pd-run-toolbar" aria-describedby="preview-explanation">
          <label>Parsing mode<select aria-label="Parsing mode" defaultValue="" disabled><option value="">Unavailable in preview</option></select></label>
          <label className="pd-history-select">Saved run<select aria-label="Saved parsing run" defaultValue="" disabled><option value="">Saved history unavailable</option></select></label>
          <button className="pd-primary" disabled title={unavailable}>Parse document</button>
          <button className="pd-icon" aria-label="Reload document and runs" disabled title={unavailable}><RefreshCw size={16} aria-hidden="true" /></button>
        </div>
        <div className="pd-panels">
          <section className="pd-panel" aria-label="Source document preview">
            <div className="pd-panel-toolbar">
              <h3>Source document</h3>
              <label>Page<select aria-label="Source page" defaultValue="" disabled><option value="">No source document</option></select></label>
            </div>
            <div className="pd-preview">
              <div className="pd-empty"><div><FileText size={35} strokeWidth={1.3} aria-hidden="true" /><p>No source document. Uploads and source previews are unavailable in this UI preview.</p></div></div>
            </div>
          </section>
          <section className="pd-panel pd-result-panel" aria-label="Parsing results preview">
            <div className="pd-panel-toolbar">
              <div className="pd-tabs" role="tablist" aria-label="Result format">
                <button role="tab" aria-selected="true" disabled title={unavailable}>Markdown</button>
                <button role="tab" aria-selected="false" disabled title={unavailable}>Text</button>
                <button role="tab" aria-selected="false" disabled title={unavailable}>Raw JSON</button>
              </div>
              <button className="pd-icon" aria-label="Download original raw JSON" disabled title={unavailable}><Download size={16} aria-hidden="true" /></button>
            </div>
            <div className="pd-result-content"><p className="pd-empty">No parsing result. This preview does not process documents or provide result downloads.</p></div>
            <div className="pd-result-footer"><span>Empty preview · no generated or example results</span></div>
          </section>
        </div>
        <footer className="pd-footer"><span>UI preview · document processing and saved history unavailable</span><Link href="/privacy">Privacy</Link></footer>
      </section>
    </main>
  </div>;
}
