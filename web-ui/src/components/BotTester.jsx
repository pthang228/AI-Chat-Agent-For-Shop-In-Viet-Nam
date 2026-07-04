import { useEffect, useRef, useState } from "react";
import { promptApi } from "../promptApi.js";
import { PHOTO_BASE } from "../photoApi.js";

/*
 * Test Bot AI — chat thử với bộ não đang dùng (AI THẬT), kèm chẩn đoán từng
 * câu: chế độ (lai/cũ), intent, các mẩu tri thức bot đã tra. KHÔNG lưu session,
 * KHÔNG gửi tới khách nào. Stateless: lịch sử giữ ở UI, gửi lên mỗi lần.
 */

const MODE_LABEL = { hybrid: "⚡ Lai", legacy: "✨ Prompt thường" };

function Diag({ d, intent }) {
  if (!d) return null;
  return (
    <div className="bt-diag">
      <span className="bt-chip">{MODE_LABEL[d.mode] || d.mode}</span>
      {intent && <span className="bt-chip">🎯 {intent}</span>}
      {d.mode === "hybrid" && (
        d.chunks?.length
          ? <span className="bt-chip bt-kb" title="Các mẩu tri thức bot đã tra cho câu này">
              📚 {d.chunks.map((c) => c.title).join(" · ")}
            </span>
          : <span className="bt-chip">📚 không tra mẩu nào</span>
      )}
      {d.system_chars && <span className="bt-chip bt-dim">{(d.system_chars / 1000).toFixed(1)}k ký tự context</span>}
    </div>
  );
}

export default function BotTester({ onClose }) {
  const [msgs, setMsgs] = useState([]);   // {role, content, debug?, intent?}
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);
  useEffect(() => {
    inputRef.current?.focus();
    function esc(e) { if (e.key === "Escape" && onClose) onClose(); }
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  async function send() {
    const t = text.trim();
    if (!t || busy) return;
    setErr(""); setText("");
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((ms) => [...ms, { role: "user", content: t }]);
    setBusy(true);
    const r = await promptApi.test(t, history);
    setBusy(false);
    if (r.ok && r.body?.reply != null) {
      setMsgs((ms) => [...ms, {
        role: "assistant", content: r.body.reply,
        debug: r.body.debug, intent: r.body.intent,
        photos: r.body.photos || [],
      }]);
    } else {
      setErr("❌ " + (r.body?.error || (r.status === 0 ? "Không kết nối được máy chủ (5005)" : "Gọi AI thất bại")));
    }
    inputRef.current?.focus();
  }

  function onKey(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  }

  return (
    <div className="bt-modal-bg" onClick={onClose}>
    <div className="bt-modal" onClick={(e) => e.stopPropagation()}>
      <div className="bt-head">
        <div className="bt-head-title">
          <b>🧪 Test Bot AI</b>
          <span className="hint">Chat thử với bộ não đang dùng — không gửi tới khách, không lưu.</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {msgs.length > 0 && (
            <button className="btn-mini" onClick={() => { setMsgs([]); setErr(""); }}>↺ Làm mới</button>
          )}
          {onClose && <button className="btn-mini" onClick={onClose}>✕ Đóng</button>}
        </div>
      </div>

      <div className="bt-body">
        {msgs.length === 0 && !busy && (
          <div className="bt-empty">
            <div style={{ fontSize: 34 }}>🤖</div>
            <p className="hint">Nhập tin nhắn như khách thật để xem bot trả lời thế nào.<br />
              Ví dụ: "giá dịch vụ sao?", "mai còn chỗ không?", "địa chỉ ở đâu?"</p>
          </div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={"bt-msg " + (m.role === "user" ? "u" : "b")}>
            <div className={"bubble " + (m.role === "user" ? "b-user" : "b-bot")}>{m.content}</div>
            {/* Ảnh bot SẼ gửi kèm (bảng giá / ảnh phòng / bộ ảnh thư viện) */}
            {m.role === "assistant" && m.photos?.length > 0 && (
              <div className="bt-photos">
                {m.photos.map((p, j) => (
                  <figure key={j} className="bt-photo">
                    <img src={PHOTO_BASE + p.url} alt={p.caption} loading="lazy" />
                    <figcaption>{p.caption}</figcaption>
                  </figure>
                ))}
              </div>
            )}
            {m.role === "assistant" && <Diag d={m.debug} intent={m.intent} />}
          </div>
        ))}
        {busy && (
          <div className="bt-msg b">
            <div className="bubble b-bot bt-typing">Bot đang nghĩ<span>.</span><span>.</span><span>.</span></div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      {err && <div className="chat-send-err" style={{ padding: "0 14px" }}>{err}</div>}

      <div className="bt-input">
        <textarea
          ref={inputRef} rows={2} className="chat-input"
          placeholder="Nhập tin thử như khách… (Enter gửi · Shift+Enter xuống dòng)"
          value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey}
          disabled={busy}
        />
        <button className="btn-primary sm" onClick={send} disabled={busy || !text.trim()}>
          {busy ? "…" : "Gửi ↑"}
        </button>
      </div>
    </div>
    </div>
  );
}
