import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronRight, Download, FileText, Layers3, LockKeyhole, SlidersHorizontal, Split } from "lucide-react";
import "./landing.css";

const workflow = [
  { number: "01", icon: FileText, title: "Bring your source material.", body: "Add a text-based PDF, Markdown, or text file. Your document is read right in your browser.", label: "PDF · TXT · MD" },
  { number: "02", icon: SlidersHorizontal, title: "Make every passage useful.", body: "Review and edit the extracted text. Adjust chunk size and overlap, then inspect exactly what goes into each chunk.", label: "Review → edit → preview" },
  { number: "03", icon: Download, title: "Take it to your AI stack.", body: "Download readable Markdown or structured JSONL with source references. Save your workspace on this device to return later.", label: "Your content. Your workflow." },
];
const questions = [
  { question: "Who is Knowledge Studio for?", answer: "Builders preparing handbooks, product guides, FAQs, and reference documents for AI assistants. It gives you a place to inspect and improve the source text before you add it to a knowledge base." },
  { question: "Does my document leave my browser?", answer: "No. Knowledge Studio reads and processes your files on your device. Saved workspaces stay in this browser; they are not synced to a cloud account. You can download your output and delete a saved workspace at any time." },
  { question: "Can I use scanned PDFs or complicated tables?", answer: "Start with PDFs that contain selectable text, or use TXT and Markdown files. This studio does not run OCR on scanned pages. Complex columns and tables may need manual editing, so always review the extracted text before exporting." },
  { question: "What can I do with the exports?", answer: "Use Markdown as a readable source document, or JSONL in your own retrieval pipeline. Each chunk includes source references. Your destination may have its own import format; this tool does not automatically connect to or publish into another service." },
  { question: "Is it free to use?", answer: "Yes. The beta is free and requires no sign-up or API key. There is no subscription or payment step. Processing and saved workspaces use your own browser." },
];

export default function Home() {
  return <div className="kb-marketing">
    <a className="km-skip" href="#main-content">Skip to content</a>
    <header className="km-nav">
      <Link className="km-brand" href="/" aria-label="TaffyBop home"><span className="km-brand-symbol"><Layers3 size={23} strokeWidth={1.8} aria-hidden="true" /></span>TaffyBop<span className="km-brand-dot">.</span></Link>
      <nav aria-label="Main navigation"><a href="#workflow">How it works</a><a href="#faq">Questions</a><Link className="km-nav-cta" href="/studio">Open studio <ArrowUpRight size={16} aria-hidden="true" /></Link></nav>
    </header>
    <main id="main-content">
      <section className="km-hero" aria-labelledby="hero-heading">
        <div className="km-hero-copy">
          <div className="km-eyebrow"><span /> KNOWLEDGE STUDIO <span className="km-beta">FREE BETA</span></div>
          <h1 id="hero-heading">Give your AI<br />better <span>source<br className="km-desktop-break" /> material.</span></h1>
          <p className="km-hero-description">Turn your documents into clear, reviewable knowledge. Clean up the text, shape your chunks, and export with every source in place.</p>
          <div className="km-hero-actions"><Link className="km-button km-button-primary" href="/studio">Prepare a document <ArrowRight size={19} aria-hidden="true" /></Link><a className="km-text-link" href="#workflow">See the workflow <ArrowDown size={16} aria-hidden="true" /></a></div>
          <div className="km-hero-assurance"><LockKeyhole size={14} aria-hidden="true" /> On your device. No sign-up. No API key.</div>
        </div>
        <div className="km-hero-visual" aria-label="Illustrative preview of a document split into source-linked chunks">
          <div className="km-visual-orbit" aria-hidden="true" />
          <div className="km-workspace-preview">
            <div className="km-preview-toolbar"><div><Layers3 size={17} aria-hidden="true" /><span>Knowledge Studio</span></div><span className="km-preview-example">EXAMPLE</span></div>
            <div className="km-preview-content">
              <div className="km-source-heading"><span className="km-file-icon"><FileText size={19} aria-hidden="true" /></span><div><strong>team-handbook.pdf</strong><small>Source document</small></div><CheckCheck size={18} aria-hidden="true" /></div>
              <div className="km-source-paper"><span className="km-paper-label">SOURCE / PAGE 3</span><h2>A good start,<br />for every teammate.</h2><p>We believe the best work starts with clarity. Your first week is a chance to get to know the team, ask questions, and find your rhythm.</p><div className="km-paper-highlight">New starters get a dedicated onboarding buddy. Your buddy is your first point of contact for day-to-day questions.</div><div className="km-paper-lines" aria-hidden="true"><span /><span /></div></div>
              <div className="km-preview-transform"><span /><div><Split size={14} aria-hidden="true" /> Review. Refine. Split.</div><span /></div>
              <div className="km-chunk-preview"><div className="km-chunk-top"><strong><span /> CHUNK 003</strong><span>PAGE 3 <ChevronRight size={12} aria-hidden="true" /></span></div><p>New starters get a dedicated onboarding buddy. Your buddy is your first point of contact for day-to-day questions.</p><div className="km-chunk-bottom"><span><FileText size={12} aria-hidden="true" /> team-handbook.pdf</span><span>Source attached <Check size={12} aria-hidden="true" /></span></div></div>
            </div>
          </div>
          <div className="km-export-chip"><span><Check size={17} aria-hidden="true" /></span><div><strong>Ready for your next step</strong><small>Markdown + JSONL exports</small></div><ArrowUpRight size={18} aria-hidden="true" /></div>
          <span className="km-visual-caption">A LITTLE PREPARATION. A CLEARER START.</span>
        </div>
      </section>
      <section className="km-value-strip" aria-label="Product capabilities"><p>Good answers start<br /><strong>with good inputs.</strong></p><span><FileText size={20} aria-hidden="true" /> Editable source text</span><span><Split size={20} aria-hidden="true" /> Adjustable chunks</span><span><Layers3 size={20} aria-hidden="true" /> Source references</span><span><LockKeyhole size={20} aria-hidden="true" /> Local processing</span></section>
      <section className="km-workflow" id="workflow" aria-labelledby="workflow-heading"><div className="km-section-heading"><div><span className="km-section-label">A SMALL TOOL. A USEFUL STEP.</span><h2 id="workflow-heading">From scattered documents<br />to considered knowledge.</h2></div><p>For the handbooks, help articles, and reference guides behind your next AI assistant.</p></div><div className="km-step-grid">{workflow.map(({ number, icon: Icon, title, body, label }) => <article className="km-step" key={number}><div className="km-step-top"><span className="km-step-number">{number}</span><Icon size={23} strokeWidth={1.5} aria-hidden="true" /></div><h3>{title}</h3><p>{body}</p><span className="km-step-label">{label}</span></article>)}</div></section>
      <section className="km-control-section" aria-labelledby="control-heading"><div className="km-control-illustration" aria-hidden="true"><div className="km-control-caption"><SlidersHorizontal size={16} /> MAKE IT FIT</div><div className="km-slider-title"><span>Chunk size</span><strong>250 <small>words</small></strong></div><div className="km-static-slider"><span /><i /></div><div className="km-slider-title"><span>Overlap</span><strong>30 <small>words</small></strong></div><div className="km-static-slider km-static-slider-short"><span /><i /></div><div className="km-control-note"><Check size={15} /> Preview the result before you export.</div></div><div className="km-control-copy"><span className="km-section-label">YOU KNOW YOUR CONTENT BEST</span><h2 id="control-heading">A little more control.<br />A lot less guesswork.</h2><p>Keep the passages that matter. Fix an awkward line break. Give a chunk enough context to stand on its own. Everything is visible, editable, and yours to take with you.</p><Link className="km-text-link" href="/studio">Find your starting point <ArrowRight size={17} aria-hidden="true" /></Link></div></section>
      <section className="km-faq" id="faq" aria-labelledby="faq-heading"><div><span className="km-section-label">BEFORE YOU BEGIN</span><h2 id="faq-heading">A few good<br />questions.</h2><p>Simple tools should come<br />with clear expectations.</p></div><div className="km-faq-list">{questions.map(({ question, answer }) => <details key={question}><summary>{question}<span className="km-faq-plus" aria-hidden="true" /></summary><p>{answer}</p></details>)}</div></section>
      <section className="km-final-cta" aria-labelledby="cta-heading"><div><span className="km-section-label">MAKE SOMETHING USEFUL</span><h2 id="cta-heading">Your knowledge deserves<br />a good starting point.</h2><p>Open the studio and try a sample, or bring your own document.</p></div><Link className="km-button km-button-lime" href="/studio">Let’s prepare it <ArrowUpRight size={21} aria-hidden="true" /></Link></section>
    </main>
    <footer className="km-footer"><Link className="km-brand" href="/"><span className="km-brand-symbol"><Layers3 size={20} aria-hidden="true" /></span>TaffyBop<span className="km-brand-dot">.</span></Link><p>Better source material. Better beginnings.</p><Link href="/privacy">Privacy &amp; your data <ArrowUpRight size={13} aria-hidden="true" /></Link></footer>
  </div>;
}
