import Link from "next/link";
import Image from "next/image";

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="site-brand" href="/" aria-label="TaffyBop home">
        <Image src="/taffybop-logo.png" alt="TaffyBop" width={388} height={194} priority unoptimized />
      </Link>
      <nav className="site-nav" aria-label="Main navigation">
        <Link href="/parse">Parse</Link>
        <Link href="/extract">Extract <span>Soon</span></Link>
      </nav>
      <Link className="header-cta" href="/parse">Try Parse</Link>
    </header>
  );
}
