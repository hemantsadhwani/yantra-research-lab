"use client";

import { useState } from "react";

interface Props {
  onSend: (text: string) => void;
  pending: boolean;
  placeholder?: string;
  compact?: boolean;
}

export default function ChatComposer({ onSend, pending, placeholder, compact }: Props) {
  const [value, setValue] = useState("");

  function submit() {
    if (!value.trim() || pending) return;
    onSend(value);
    setValue("");
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div style={{ display: "flex", gap: 8, alignItems: "flex-end", width: "100%" }}>
      <textarea
        className="chatinput"
        rows={compact ? 1 : 2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder={placeholder ?? "Ask about the platform…"}
        aria-label="Message"
        style={compact ? { fontSize: 12 } : undefined}
      />
      <button
        className="btn pri"
        onClick={submit}
        disabled={pending || !value.trim()}
        aria-label="Send message"
      >
        {pending ? "…" : "Send"}
      </button>
    </div>
  );
}
