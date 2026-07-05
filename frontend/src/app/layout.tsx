import type { Metadata } from "next";
import "./globals.css";
import Ticker from "@/components/Ticker";
import Nav from "@/components/Nav";
import Footer from "@/components/Footer";
import AskLauncher from "@/components/chat/AskLauncher";

export const metadata: Metadata = {
  title: "yantra-research-lab — autonomous strategy research (paper/simulated)",
  description:
    "Signal Desk: an autonomous quant-research loop — propose, backtest, judge, rank, remember — bounded by a budget with a human approval gate. ALL PAPER / SIMULATED. Educational, not investment advice.",
};

// Set the theme before paint to avoid a flash of the wrong theme.
const THEME_INIT = `(function(){try{var t=localStorage.getItem('yrl-theme');if(t==='light'||t==='dark'){document.documentElement.setAttribute('data-theme',t);}}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <Ticker />
        <div className="wrap">
          <Nav />
          <main>{children}</main>
          <Footer />
        </div>
        <AskLauncher />
      </body>
    </html>
  );
}
