"use client";

import { useCallback, useState } from "react";
import { sendChat } from "./chat";
import type { ChatResponse, ChatSource, ChatTurn } from "./types";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  refused?: boolean;
  sources?: ChatSource[];
  error?: boolean;
}

let counter = 0;
const nextId = () => `m${Date.now()}-${counter++}`;

export function useChat() {
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [pending, setPending] = useState(false);
  // The highest leak-rate the backend has reported this session (0 is the healthy value).
  const [leakRate, setLeakRate] = useState<number>(0);

  const submit = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || pending) return;

      const userMsg: UiMessage = { id: nextId(), role: "user", content: trimmed };
      // Build the API history from the prior conversation (before this turn).
      const history: ChatTurn[] = messages.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      setMessages((prev) => [...prev, userMsg]);
      setPending(true);

      try {
        const res: ChatResponse = await sendChat(trimmed, history);
        setLeakRate(res.leak_rate);
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content: res.answer,
            refused: res.refused,
            sources: res.sources,
          },
        ]);
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            content:
              "Couldn't reach the guardrail backend. Start it locally (default " +
              "http://localhost:8000) or set NEXT_PUBLIC_BACKEND_URL, then try again.",
            error: true,
          },
        ]);
      } finally {
        setPending(false);
      }
    },
    [messages, pending]
  );

  return { messages, pending, leakRate, submit };
}
