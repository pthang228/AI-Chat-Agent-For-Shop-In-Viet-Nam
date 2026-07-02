import { useState, useRef } from "react";

// Input gửi tin thủ công từ dashboard — dùng chung cho Zalo / Meta / Telegram.
// Props:
//   onSend(text) → Promise<bool>  (true = gửi OK, false = lỗi)
//   disabled     — khoá input (ví dụ khi bot đang bật, tùy chọn)
export default function ChatSend({ onSend, disabled = false }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [err, setErr] = useState("");
  const ref = useRef(null);

  async function send() {
    const t = text.trim();
    if (!t || sending) return;
    setSending(true); setErr("");
    const ok = await onSend(t);
    setSending(false);
    if (ok) { setText(""); ref.current?.focus(); }
    else setErr("Gửi thất bại — kiểm tra server đang chạy không.");
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="chat-input-area">
      <textarea
        ref={ref}
        className="chat-input"
        rows={2}
        placeholder="Nhập tin nhắn… (Enter gửi · Shift+Enter xuống dòng)"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        disabled={sending || disabled}
      />
      <button
        className="btn-primary sm"
        onClick={send}
        disabled={sending || disabled || !text.trim()}
      >
        {sending ? "Đang gửi…" : "Gửi ↑"}
      </button>
      {err && <div className="chat-send-err">{err}</div>}
    </div>
  );
}
