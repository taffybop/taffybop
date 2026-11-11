import Link from "next/link";
import { ArrowLeft, Layers3, ShieldCheck } from "lucide-react";
import "../landing.css";

export default function PrivacyPage() {
  return <div className="kb-marketing"><main style={{ maxWidth: 760, margin: "0 auto", padding: "55px 24px 90px" }}>
    <Link href="/" style={{ display: "inline-flex", alignItems: "center", gap: 9, marginBottom: 55, fontWeight: 700 }}><Layers3 size={22} /> TaffyBop</Link>
    <ShieldCheck size={38} style={{ color: "#37664f", marginBottom: 20 }} />
    <h1 style={{ fontSize: "clamp(32px,6vw,48px)", letterSpacing: "-1.5px", lineHeight: 1.15 }}>Know where your documents are processed.</h1>
    <p style={{ margin: "22px 0 35px", color: "#647568", lineHeight: 1.8 }}>The parsing workspace sends documents to LlamaCloud. The separate Knowledge tools process text locally. Updated 4 November 2026.</p>
    {[
      ["Parsing uploads", "When you choose Parse document, your PDF or image goes to this app’s Python backend and then to LlamaCloud for processing using the selected mode. LlamaCloud’s service terms and retention policies apply. The key stays on the server. Markdown, text and raw JSON come from the provider response; the app does not rewrite parsed content."],
      ["Current extraction session", "The selected file and API result remain in the workspace while the page is open. This preview has no cloud document library or account sync. Download the API response before closing or reloading. Backend and hosting infrastructure can generate operational logs; deployment-specific retention must be established before using confidential production documents."],
      ["Knowledge tools and saved packs", "The separate /knowledge workspace reads PDF, Markdown, and text locally in your browser. Save pack stores extracted text, filenames, chunk settings, and a timestamp in IndexedDB. Original PDFs are not stored there. Packs are available to anyone using the same browser profile and do not sync across devices."],
      ["Deletion and backups", "Use Saved packs in Knowledge tools, or clear this site’s browser data, to remove locally saved packs. Download a backup first if needed. Document Studio’s current result is cleared when you reset the workspace or close the page."],
      ["Site infrastructure", "Your browser requests application assets from the hosting service. Hosting infrastructure may process connection information such as IP address, request path, and browser details. The application includes no advertising pixels or third-party analytics."],
      ["Review before use", "Parsing can omit or misread content, including tables and formulas. Compare the result with the source before relying on it. Raw JSON records what the provider returned; a completed job is not an accuracy guarantee. Stopping polling or closing the page does not cancel a job or delete the provider’s copy."],
    ].map(([heading, body]) => <section key={heading} style={{ margin: "28px 0" }}><h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 10 }}>{heading}</h2><p style={{ color: "#647568", fontSize: 14, lineHeight: 1.9 }}>{body}</p></section>)}
    <Link href="/studio" style={{ display: "inline-flex", gap: 8, alignItems: "center", marginTop: 25, color: "#2e6045", fontWeight: 600 }}><ArrowLeft size={16} /> Back to Document Studio</Link>
  </main></div>;
}
