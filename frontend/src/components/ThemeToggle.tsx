"use client";

import { useEffect, useState } from "react";

type Theme = "dark" | "light";

function resolveInitial(): Theme {
  if (typeof document === "undefined") return "dark";
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "light" || attr === "dark") return attr;
  const prefersLight =
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-color-scheme: light)").matches;
  return prefersLight ? "light" : "dark";
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setTheme(resolveInitial());
    setMounted(true);
  }, []);

  function toggle() {
    const next: Theme = theme === "light" ? "dark" : "light";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("yrl-theme", next);
    } catch {
      /* ignore storage errors */
    }
  }

  return (
    <button
      className="themebtn"
      onClick={toggle}
      aria-label="Toggle color theme"
      title="Toggle color theme"
      suppressHydrationWarning
    >
      ◑ {mounted ? (theme === "light" ? "dark" : "light") : "theme"}
    </button>
  );
}
