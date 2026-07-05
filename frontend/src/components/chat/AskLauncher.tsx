"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useChat } from "@/lib/useChat";
import ChatMessage from "./ChatMessage";
import ChatComposer from "./ChatComposer";

export default function AskLauncher() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const { messages, pending, leakRate, submit } = useChat();
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [messages, open]);

  // The full chat page already hosts the assistant — no floating duplicate there.
  if (pathname === "/chat") return null;

  if (!open) {
    return (
      <button className="fab" onClick={() => setOpen(true)} aria-label="Open chat assistant">
        <span className="fdot" aria-hidden="true" />
        Ask ▚
      </button>
    );
  }

  return (
    <div className="chatpop" role="dialog" aria-label="Chat assistant">
      <div className="cp-h">
        <span>
          ▚ Ask · leak-rate {leakRate.toFixed(1)}%
        </span>
        <button onClick={() => setOpen(false)} aria-label="Close chat">
          ×
        </button>
      </div>
      <div className="cp-b" ref={bodyRef}>
        {messages.length === 0 && (
          <div className="caption" style={{ lineHeight: 1.7 }}>
            Ask about the autonomous loop, the strategies, or the guardrails. It answers from public
            docs and refuses proprietary parameters &amp; PII.{" "}
            <Link href="/chat" style={{ color: "var(--accent-ink)" }}>
              Open full view →
            </Link>
          </div>
        )}
        {messages.map((m) => (
          <ChatMessage key={m.id} msg={m} />
        ))}
        {pending && <div className="caption">▚ thinking…</div>}
      </div>
      <div className="cp-f">
        <ChatComposer onSend={submit} pending={pending} compact />
      </div>
    </div>
  );
}
