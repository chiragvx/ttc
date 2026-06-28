import { useRef, useState } from "react";

export function Composer({
  streaming,
  noKey,
  onSend,
  onStop,
}: {
  streaming: boolean;
  noKey: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const grow = () => {
    const el = ref.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 140) + "px";
    }
  };

  const submit = () => {
    const t = text.trim();
    if (!t || streaming) return;
    onSend(t);
    setText("");
    requestAnimationFrame(grow);
  };

  return (
    <div style={{ borderTop: "1px solid #30363d", padding: "10px 0 2px" }}>
      {noKey && (
        <div style={{ fontSize: 11, color: "#d29922", marginBottom: 6 }}>
          No LLM configured — add an OpenRouter key in ⚙ settings to chat.
        </div>
      )}
      <div style={{ display: "flex", gap: 6, alignItems: "flex-end" }}>
        <textarea
          ref={ref}
          value={text}
          rows={1}
          placeholder='Ask or instruct… e.g. "make the skin 3 mm"'
          onChange={(e) => {
            setText(e.target.value);
            grow();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          style={{
            flex: 1, resize: "none", padding: "8px 10px", background: "#161b22", border: "1px solid #30363d",
            borderRadius: 8, color: "#e6edf3", fontSize: 13, lineHeight: 1.4, fontFamily: "inherit", maxHeight: 140,
          }}
        />
        {streaming ? (
          <button onClick={onStop} style={{ ...btn, background: "#21262d", color: "#e6edf3", border: "1px solid #30363d" }}>
            Stop
          </button>
        ) : (
          <button onClick={submit} style={{ ...btn, background: "#1f6feb", color: "#fff", border: "none" }}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}

const btn: React.CSSProperties = { borderRadius: 8, padding: "8px 14px", cursor: "pointer", fontSize: 13, height: 36 };
