"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import ThemeToggle from "./ThemeToggle";

const REPO = "https://github.com/hemantsadhwani/yantra-research-lab";

export default function Nav() {
  const pathname = usePathname() ?? "/";
  const on = (href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));
  return (
    <nav className="appnav" aria-label="Primary">
      <Link href="/" className="logo">
        <span className="glyph sm" aria-hidden="true" />
        yantra
      </Link>
      <span className="chip acc" aria-hidden="true">
        ◆ Research bench
      </span>
      <div className="navlinks">
        <Link href="/" className={on("/") ? "on" : undefined} aria-current={on("/") ? "page" : undefined}>
          Home
        </Link>
        <Link
          href="/research-lab/"
          className={on("/research-lab") ? "on" : undefined}
          aria-current={on("/research-lab") ? "page" : undefined}
        >
          Research Lab
        </Link>
        <a href="/track-record/">Track Record</a>
        <a href={REPO}>GitHub</a>
      </div>
      <div className="navcta">
        <span className="chip paper">BACKTEST · NOT ADVICE</span>
        <ThemeToggle />
      </div>
    </nav>
  );
}
