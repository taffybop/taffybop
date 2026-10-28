import Link from "next/link";

export default function NotFound() {
  return <main style={{ minHeight: "100vh", display: "grid", placeContent: "center", textAlign: "center", padding: 30, background: "#f5f6f2", color: "#203e36" }}><p style={{ letterSpacing: 3, fontSize: 12 }}>TAFFYBOP / 404</p><h1 style={{ fontSize: 36, margin: "20px 0 10px" }}>This page wandered off.</h1><p style={{ color: "#73806d", marginBottom: 24 }}>Your knowledge workspace is right here.</p><Link href="/studio" style={{ background: "#244b3e", color: "white", padding: "13px 20px", borderRadius: 6 }}>Open Knowledge Studio</Link></main>;
}
