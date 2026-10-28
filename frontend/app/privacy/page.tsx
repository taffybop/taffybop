import Link from "next/link";
import { ArrowLeft, Layers3, ShieldCheck } from "lucide-react";
import "../landing.css";

export default function PrivacyPage() {
  return <div className="kb-marketing"><main style={{ maxWidth: 760, margin: "0 auto", padding: "55px 24px 90px" }}>
    <Link href="/" style={{ display: "inline-flex", alignItems: "center", gap: 9, marginBottom: 55, fontWeight: 700 }}><Layers3 size={22} /> TaffyBop</Link>
    <ShieldCheck size={38} style={{ color: "#37664f", marginBottom: 20 }} />
    <h1 style={{ fontSize: "clamp(32px,6vw,48px)", letterSpacing: "-1.5px", lineHeight: 1.15 }}>Your documents stay on your device.</h1>
    <p style={{ margin: "22px 0 35px", color: "#647568", lineHeight: 1.8 }}>Knowledge Studio processes your files in your browser. This page describes the current free beta, updated 27 October 2026.</p>
    {[
      ["Document processing", "PDF, Markdown, and text content is read locally. The studio does not upload your documents, send their contents to an AI model, or use them to train a model. The sample handbook is a fictional public file downloaded from this site."],
      ["Saved packs", "Saving is optional. Save pack stores extracted text, filenames, chunk settings, and a timestamp in this browser's IndexedDB. Original PDFs are not stored. Saved packs are available to anyone using the same browser profile on this device. They do not sync across devices or browsers."],
      ["Deletion and backups", "Use Saved packs to delete a saved pack, or clear this site's browser data to remove all saved packs. Deletion cannot be undone. Download Markdown or JSONL if you need a portable copy. Closing or refreshing with unsaved edits may lose those edits."],
      ["Site infrastructure", "Your browser requests application assets, including the PDF reader, from the hosting service. Hosting infrastructure may process ordinary connection information such as IP address, request path, and browser details. Application code includes no advertising pixels or third-party analytics. The hosting platform may require sign-in according to the site's sharing settings."],
      ["Review before use", "Extraction follows a PDF's embedded text order. Scans require OCR first, and tables or columns may need manual correction. Review source text and citations before using an export in your assistant. Chunk sizes are measured in words, not model tokens."],
    ].map(([heading, body]) => <section key={heading} style={{ margin: "28px 0" }}><h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 10 }}>{heading}</h2><p style={{ color: "#647568", fontSize: 14, lineHeight: 1.9 }}>{body}</p></section>)}
    <Link href="/studio" style={{ display: "inline-flex", gap: 8, alignItems: "center", marginTop: 25, color: "#2e6045", fontWeight: 600 }}><ArrowLeft size={16} /> Back to Knowledge Studio</Link>
  </main></div>;
}
