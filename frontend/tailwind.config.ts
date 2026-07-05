import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ground: "var(--ground)",
        panel: "var(--panel)",
        "panel-2": "var(--panel-2)",
        inset: "var(--inset)",
        line: "var(--line)",
        "line-strong": "var(--line-strong)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-ink": "var(--accent-ink)",
        "accent-2": "var(--accent-2)",
        "on-accent": "var(--on-accent)",
        up: "var(--up)",
        down: "var(--down)",
      },
      fontFamily: {
        sans: "var(--sans)",
        mono: "var(--mono)",
      },
      maxWidth: {
        wrap: "1140px",
      },
    },
  },
  plugins: [],
};

export default config;
