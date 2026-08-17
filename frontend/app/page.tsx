import {
  ArrowRight,
  Braces,
  Check,
  FileOutput,
  FileText,
  ScanText,
  Sparkles,
  WandSparkles,
} from "lucide-react";
import Link from "next/link";
import Image from "next/image";

import { SiteHeader } from "./site-header";

const steps = [
  {
    number: "01",
    title: "Drop a document",
    body: "Bring a PDF or image. TaffyBop keeps the original right beside the result.",
  },
  {
    number: "02",
    title: "Let it untangle",
    body: "The parser finds text, tables, reading order, and page structure without the busywork.",
  },
  {
    number: "03",
    title: "Take the clean bits",
    body: "Review page-synced Markdown or complete JSON, then copy or download what you need.",
  },
];

export default function Home() {
  return (
    <div className="site-shell">
      <SiteHeader />

      <main>
        <section className="home-hero">
          <div className="hero-copy">
            <span className="hero-kicker">
              <Sparkles aria-hidden="true" size={15} />
              Documents, nicely untangled
            </span>
            <h1>
              Messy data in.
              <span>Clean data out.</span>
            </h1>
            <p>
              TaffyBop turns tangled PDFs and images into structured content
              you can actually use—without making document work feel like a
              chore.
            </p>
            <div className="hero-actions">
              <Link className="site-button site-button-primary" href="/parse">
                Start parsing
                <ArrowRight aria-hidden="true" size={18} />
              </Link>
              <Link className="site-button site-button-secondary" href="/extract">
                Meet Extract
              </Link>
            </div>
            <div className="hero-proof" aria-label="Supported capabilities">
              <span><Check aria-hidden="true" size={14} /> PDF &amp; images</span>
              <span><Check aria-hidden="true" size={14} /> Markdown &amp; JSON</span>
              <span><Check aria-hidden="true" size={14} /> Page-by-page review</span>
            </div>
          </div>

          <div className="hero-playground" aria-label="From messy documents to clean data">
            <span className="yarn-loop yarn-loop-one" aria-hidden="true" />
            <span className="yarn-loop yarn-loop-two" aria-hidden="true" />
            <div className="messy-stack" aria-hidden="true">
              <div className="paper paper-back"><span /><span /><span /></div>
              <div className="paper paper-middle"><span /><span /><span /></div>
              <div className="paper paper-front">
                <FileText size={24} />
                <strong>quarterly-report.pdf</strong>
                <small>32 pages · tables · scans</small>
              </div>
            </div>
            <div className="transform-pill" aria-hidden="true">
              <WandSparkles size={18} />
              untangling
            </div>
            <div className="clean-card" aria-hidden="true">
              <div className="clean-card-top">
                <span><Braces size={17} /> structured.json</span>
                <Check size={16} />
              </div>
              <div className="code-row"><i>title</i><b>Quarterly report</b></div>
              <div className="code-row"><i>tables</i><b>12 found</b></div>
              <div className="code-row"><i>pages</i><b>32 synced</b></div>
              <div className="clean-progress"><span /></div>
            </div>
            <div className="hero-cat-badge">
              <Image src="/taffybop-logo.png" alt="" width={276} height={138} unoptimized />
            </div>
          </div>
        </section>

        <section className="tool-section" id="tools" aria-labelledby="tool-title">
          <div className="section-heading">
            <span className="section-kicker">Pick your tool</span>
            <h2 id="tool-title">What are we untangling today?</h2>
            <p>Two focused tools. No maze of menus.</p>
          </div>

          <div className="tool-grid">
            <Link className="tool-card tool-card-live" href="/parse">
              <div className="tool-icon"><ScanText aria-hidden="true" size={28} /></div>
              <span className="tool-status">Ready to go</span>
              <h3>Parse</h3>
              <p>
                Turn whole documents into faithful Markdown and complete JSON,
                with the original and result kept in sync.
              </p>
              <span className="tool-link">Open Parse <ArrowRight aria-hidden="true" size={17} /></span>
            </Link>

            <Link className="tool-card tool-card-soon" href="/extract">
              <div className="tool-icon"><FileOutput aria-hidden="true" size={28} /></div>
              <span className="tool-status">Coming soon</span>
              <h3>Extract</h3>
              <p>
                Pull just the fields you care about from repeatable document
                types. A smaller output for a sharper job.
              </p>
              <span className="tool-link">Take a peek <ArrowRight aria-hidden="true" size={17} /></span>
            </Link>
          </div>
        </section>

        <section className="how-section" aria-labelledby="how-title">
          <div className="how-intro">
            <span className="section-kicker">How it bops</span>
            <h2 id="how-title">From file to useful, in one calm little flow.</h2>
          </div>
          <ol className="step-list">
            {steps.map((step) => (
              <li key={step.number}>
                <span>{step.number}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section className="final-cta">
          <div>
            <span className="section-kicker">Ready when you are</span>
            <h2>Give that messy document a little bop.</h2>
          </div>
          <Link className="site-button site-button-dark" href="/parse">
            Parse a document <ArrowRight aria-hidden="true" size={18} />
          </Link>
        </section>
      </main>

      <footer className="site-footer">
        <Image src="/taffybop-logo.png" alt="TaffyBop" width={380} height={190} unoptimized />
        <p>Messy data in. Clean data out.</p>
        <span>Built for documents that refuse to sit still.</span>
      </footer>
    </div>
  );
}
