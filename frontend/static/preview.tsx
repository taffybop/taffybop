import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import { ArrowLeft, Layers3, ShieldCheck } from "lucide-react";
import { PreviewWorkspace } from "./preview-workspace";
import Link from "./link";
import "../app/globals.css";

function subscribe(callback: () => void) {
  window.addEventListener("popstate", callback);
  return () => window.removeEventListener("popstate", callback);
}

function PreviewPrivacy() {
  return <div className="pd-workspace"><main style={{ maxWidth: 760, margin: "0 auto", padding: "55px 24px 90px" }}>
    <Link href="/" className="pd-brand" style={{ marginBottom: 55 }}><Layers3 size={22} aria-hidden="true" />TaffyBop</Link>
    <ShieldCheck size={38} aria-hidden="true" style={{ color: "#37664f", marginBottom: 20 }} />
    <h1 style={{ fontSize: "clamp(32px,6vw,44px)", lineHeight: 1.2 }}>Privacy in this UI preview</h1>
    <p style={{ marginTop: 22, color: "#647568", lineHeight: 1.8 }}>This published version shows the document workspace layout. Its upload and processing controls are disabled.</p>
    {[
      ["No document uploads or processing", "This preview does not accept, upload, process or save documents. It makes no parser or model calls and provides no generated document results or downloads."],
      ["No accounts or saved history", "There is no sign-in, document library, saved history or account sync in this preview. The Knowledge, extraction and template tools are also unavailable."],
      ["Site infrastructure", "Your browser requests the application’s public assets from the hosting service. Hosting infrastructure may record connection information such as IP address, request path and browser details. No specific hosting-log retention period is asserted here."],
    ].map(([heading, body]) => <section key={heading} style={{ marginTop: 28 }}><h2 style={{ fontSize: 20, fontWeight: 600, marginBottom: 10 }}>{heading}</h2><p style={{ color: "#647568", fontSize: 14, lineHeight: 1.9 }}>{body}</p></section>)}
    <Link href="/studio" style={{ display: "inline-flex", gap: 8, alignItems: "center", marginTop: 35, fontWeight: 600 }}><ArrowLeft size={16} aria-hidden="true" />Back to the UI preview</Link>
  </main></div>;
}

function PreviewApp() {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname.replace(/\/+$/, "") || "/", () => "/");
  if (["/", "/studio", "/documents", "/parse", "/extract", "/legacy", "/knowledge"].includes(path)) return <PreviewWorkspace />;
  if (path === "/privacy") return <PreviewPrivacy />;
  return <div className="pd-workspace"><main style={{ padding: "90px 24px", textAlign: "center" }}><h1>That page is not here.</h1><p style={{ margin: "20px 0" }}>Return to the TaffyBop UI preview.</p><Link href="/">Back to TaffyBop</Link></main></div>;
}

const root = document.getElementById("root");
if (!root) throw new Error("The application root is missing.");
createRoot(root).render(<PreviewApp />);
