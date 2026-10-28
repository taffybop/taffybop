import { useSyncExternalStore } from "react";
import { createRoot } from "react-dom/client";
import Home from "../app/page";
import { KnowledgeStudio } from "../app/knowledge-studio";
import { BackendWorkspace } from "../app/backend-workspace";
import PrivacyPage from "../app/privacy/page";
import Link from "./link";
import "../app/globals.css";

function subscribe(callback: () => void) {
  window.addEventListener("popstate", callback);
  return () => window.removeEventListener("popstate", callback);
}

function App() {
  const path = useSyncExternalStore(subscribe, () => window.location.pathname.replace(/\/+$/, "") || "/", () => "/");
  if (path === "/") return <Home />;
  if (["/studio", "/parse", "/extract"].includes(path)) return <BackendWorkspace apiBaseUrl="/v1/parse" />;
  if (path === "/knowledge") return <KnowledgeStudio />;
  if (path === "/privacy") return <PrivacyPage />;
  return <main className="kb-marketing" style={{ padding: "90px 24px", textAlign: "center", minHeight: "100vh" }}><h1>That page is not here.</h1><p>Head back to TaffyBop to prepare your documents.</p><Link href="/">Back to TaffyBop</Link></main>;
}

const root = document.getElementById("root");
if (!root) throw new Error("The application root is missing.");
createRoot(root).render(<App />);
