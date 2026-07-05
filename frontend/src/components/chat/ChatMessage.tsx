import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { UiMessage } from "@/lib/useChat";

export default function ChatMessage({ msg }: { msg: UiMessage }) {
  const isMe = msg.role === "user";

  if (isMe) {
    return (
      <div className="msg me">
        <div className="who">you</div>
        <div className="bubble">
          <span className="txt">{msg.content}</span>
        </div>
      </div>
    );
  }

  const refused = Boolean(msg.refused);
  return (
    <div className="msg">
      <div className="who" aria-hidden="true">
        ▚
      </div>
      <div className={`bubble${refused ? " refused" : ""}`}>
        <div className="md">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              // real, clickable links that open in a new tab
              a: ({ node, ...props }) => (
                <a {...props} target="_blank" rel="noopener noreferrer" />
              ),
            }}
          >
            {msg.content}
          </ReactMarkdown>
        </div>

        {msg.sources && msg.sources.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
            <span className="tag">sources</span>
            {msg.sources.map((s, i) => (
              <div
                key={i}
                style={{
                  border: "1px solid var(--line)",
                  borderRadius: 8,
                  padding: "7px 9px",
                  background: "var(--inset)",
                }}
              >
                <div
                  className="mono"
                  style={{ fontSize: 11.5, color: "var(--accent-ink)", fontWeight: 700 }}
                >
                  {s.title}
                </div>
                <div style={{ fontSize: 11.5, color: "var(--muted)", marginTop: 3 }}>
                  {s.snippet}
                </div>
              </div>
            ))}
          </div>
        )}

        {refused ? (
          <span className="verdict no">✕ refused · out-of-scope / protected</span>
        ) : msg.error ? (
          <span className="verdict no">! backend unreachable</span>
        ) : (
          <span className="verdict ok">✓ answered</span>
        )}
      </div>
    </div>
  );
}
