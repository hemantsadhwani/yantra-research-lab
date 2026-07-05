import type { ChatRequest, ChatResponse, ChatTurn } from "./types";

export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000";

export const CHAT_ENDPOINT = `${BACKEND_URL}/api/chat`;

/**
 * POSTs a message + prior history to the guardrail chatbot backend.
 * Request:  { message, history }
 * Response: { answer, refused, sources: [{title, snippet}], leak_rate }
 */
export async function sendChat(
  message: string,
  history: ChatTurn[],
  signal?: AbortSignal
): Promise<ChatResponse> {
  const body: ChatRequest = { message, history };

  const res = await fetch(CHAT_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    throw new Error(`Backend responded ${res.status} ${res.statusText}`);
  }

  const data = (await res.json()) as Partial<ChatResponse>;

  // Defensive normalisation so the UI never crashes on a partial payload.
  return {
    answer: typeof data.answer === "string" ? data.answer : "",
    refused: Boolean(data.refused),
    sources: Array.isArray(data.sources) ? data.sources : [],
    leak_rate: typeof data.leak_rate === "number" ? data.leak_rate : 0,
  };
}
