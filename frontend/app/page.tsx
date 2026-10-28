import Link from "next/link";
import { ArrowRight, ArrowUpRight, Braces, FileImage, FileText, Layers3, Scan, Table2 } from "lucide-react";
import "./landing.css";

const workflow = [
  { number: "01", icon: FileImage, title: "Bring the original.", body: "Upload a PDF, scan, or image. Keep the source visible while the parsing service extracts its content.", label: "PDF · PNG · JPEG · TIFF · WebP" },
  { number: "02", icon: Table2, title: "Inspect what came back.", body: "Review returned text, tables, images, and warnings in a consistent page-by-page view. Incomplete extraction stays visible.", label: "Source → result → review" },
  { number: "03", icon: Braces, title: "Keep the exact response.", body: "Compare the structured view with the original API JSON. Copy or download the backend response without frontend normalization.", label: "Original API response" },
];

export default function Home() {
  return <div className="kb-marketing">
    <a className="km-skip" href="#main-content">Skip to content</a>
    <header className="km-nav">
      <Link className="km-brand" href="/" aria-label="TaffyBop home"><span className="km-brand-symbol"><Layers3 size={23} aria-hidden="true" /></span>TaffyBop<span className="km-brand-dot">.</span></Link>
      <nav aria-label="Main navigation"><Link href="/knowledge">Knowledge tools</Link><Link className="km-nav-cta" href="/studio">Open studio <ArrowUpRight size={16} aria-hidden="true" /></Link></nav>
    </header>
    <main id="main-content">
      <section className="km-hero" aria-labelledby="hero-heading">
        <div className="km-hero-copy">
          <div className="km-eyebrow"><span /> DOCUMENT STUDIO <span className="km-beta">PREVIEW</span></div>
          <h1 id="hero-heading">Your documents.<br /><span>The actual<br />extraction.</span></h1>
          <p className="km-hero-description">Turn PDFs and images into inspectable content. Compare source pages, structured results, and the exact API response before using your data.</p>
          <div className="km-hero-actions"><Link className="km-button km-button-primary" href="/studio">Extract a document <ArrowRight size={19} aria-hidden="true" /></Link></div>
          <p className="km-hero-assurance"><Scan size={16} aria-hidden="true" /> Files are sent to this deployment’s parsing service.</p>
        </div>
        <div className="km-workspace-preview" style={{ alignSelf: "center", width: "100%", transform: "none" }}>
          <div className="km-preview-toolbar"><div><Layers3 size={17} aria-hidden="true" /><span>A consistent review workflow</span></div></div>
          <div style={{ padding: "32px", display: "grid", gap: "28px" }}>
            {workflow.map(({ number, icon: Icon, title, body }) => <div key={number} style={{ display: "grid", gridTemplateColumns: "28px 1fr", gap: "16px" }}><Icon size={24} aria-hidden="true" /><div><h2 style={{ fontSize: "19px", margin: "0 0 8px" }}>{title}</h2><p style={{ fontSize: "14px", lineHeight: 1.7, color: "#647568", margin: 0 }}>{body}</p></div></div>)}
          </div>
        </div>
      </section>
      <section className="km-value-strip" aria-label="Product capabilities"><p>Inspect the source.<br /><strong>Understand the result.</strong></p><span><FileText size={20} aria-hidden="true" /> Text and OCR</span><span><Table2 size={20} aria-hidden="true" /> Returned tables</span><span><FileImage size={20} aria-hidden="true" /> Image evidence</span><span><Braces size={20} aria-hidden="true" /> Exact API JSON</span></section>
      <section className="km-workflow" id="workflow"><div className="km-section-heading"><div><span className="km-section-label">REVIEW BEFORE YOU RELY ON IT</span><h2>Useful evidence.<br />Clear limitations.</h2></div><p>Complex tables, faint scans, and ambiguous layouts can need review. The studio shows backend warnings and incomplete candidates alongside the source.</p></div><div className="km-step-grid">{workflow.map(({ number, icon: Icon, title, body, label }) => <article className="km-step" key={number}><div className="km-step-top"><span className="km-step-number">{number}</span><Icon size={23} aria-hidden="true" /></div><h3>{title}</h3><p>{body}</p><span className="km-step-label">{label}</span></article>)}</div></section>
      <section className="km-final-cta"><div><span className="km-section-label">ALSO AVAILABLE</span><h2>Prepare text for<br />your knowledge base.</h2><p>The separate Knowledge tools run in your browser and keep your existing saved packs.</p></div><Link className="km-button km-button-lime" href="/knowledge">Open Knowledge tools <ArrowUpRight size={21} aria-hidden="true" /></Link></section>
    </main>
    <footer className="km-footer"><Link className="km-brand" href="/">TaffyBop<span className="km-brand-dot">.</span></Link><p>Source. Extraction. Evidence.</p><Link href="/privacy">Privacy &amp; your data <ArrowUpRight size={13} aria-hidden="true" /></Link></footer>
  </div>;
}
