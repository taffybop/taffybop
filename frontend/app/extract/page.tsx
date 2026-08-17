import { ArrowLeft, Bell, FileOutput, Sparkles } from "lucide-react";
import Link from "next/link";

import { SiteHeader } from "../site-header";

export default function ExtractPage() {
  return (
    <div className="site-shell coming-soon-page">
      <SiteHeader />
      <main className="coming-soon-main">
        <div className="coming-soon-card">
          <div className="coming-soon-art" aria-hidden="true">
            <span className="extract-sheet extract-sheet-one" />
            <span className="extract-sheet extract-sheet-two" />
            <div className="extract-target">
              <FileOutput size={34} />
              <span>Just the good bits</span>
            </div>
            <Sparkles className="extract-spark extract-spark-one" size={22} />
            <Sparkles className="extract-spark extract-spark-two" size={16} />
          </div>
          <div className="coming-soon-copy">
            <span className="hero-kicker"><Bell size={15} /> Next up</span>
            <h1>Extract is still chasing its yarn.</h1>
            <p>
              Soon you’ll be able to pull the exact fields you need from
              familiar documents. For now, Parse can turn the whole thing into
              clean Markdown and JSON.
            </p>
            <div className="coming-soon-actions">
              <Link className="site-button site-button-primary" href="/parse">
                Use Parse instead
              </Link>
              <Link className="site-button site-button-secondary" href="/">
                <ArrowLeft aria-hidden="true" size={17} /> Back home
              </Link>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
