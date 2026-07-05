"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import ThemeToggle from "./ThemeToggle";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/strategies", label: "Strategies" },
  { href: "/research-lab", label: "Research Lab" },
  { href: "/ops", label: "Live Ops" },
  { href: "/chat", label: "Ask" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <nav className="appnav" aria-label="Primary">
      <Link href="/" className="logo">
        <span className="glyph sm" aria-hidden="true" />
        yantra
      </Link>
      <span className="chip acc" aria-hidden="true">
        ◆ Options
      </span>
      <div className="navlinks">
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              className={active ? "on" : undefined}
              aria-current={active ? "page" : undefined}
            >
              {l.label}
            </Link>
          );
        })}
      </div>
      <div className="navcta">
        <span className="chip paper">ALL PAPER / SIMULATED</span>
        <ThemeToggle />
      </div>
    </nav>
  );
}
