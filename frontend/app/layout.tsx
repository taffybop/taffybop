import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";

const title = "TaffyBop — Knowledge Studio for AI assistants";
const description =
  "Prepare better context for your AI assistant. Turn PDFs, Markdown, and text into reviewable chunks with page citations. Private, in-browser processing. Free beta.";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const forwardedHost = requestHeaders
    .get("x-forwarded-host")
    ?.split(",", 1)[0]
    .trim();
  const host = forwardedHost || requestHeaders.get("host") || "localhost:3000";
  const forwardedProtocol = requestHeaders
    .get("x-forwarded-proto")
    ?.split(",", 1)[0]
    .trim();
  const protocol =
    forwardedProtocol === "http" || forwardedProtocol === "https"
      ? forwardedProtocol
      : host.startsWith("localhost") || host.startsWith("127.0.0.1")
        ? "http"
        : "https";

  let origin = new URL("http://localhost:3000");
  try {
    origin = new URL(`${protocol}://${host}`);
  } catch {
    // Keep metadata valid if a development proxy supplies a malformed host.
  }

  const socialImage = new URL("/og-knowledge.svg", origin).toString();

  return {
    metadataBase: origin,
    title,
    description,
    icons: { icon: "/icon.svg" },
    openGraph: {
      type: "website",
      title,
      description,
      images: [
        {
          url: socialImage,
          width: 1200,
          height: 630,
          alt: "TaffyBop Knowledge Studio. Better source material. Better answers.",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [socialImage],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
