import { useEffect, useRef, useState } from "react";

// Bong bóng chat tư vấn DỊCH VỤ (kiểu Crisp) — góc phải dưới, mọi trang.
// Chat với bot bán hàng của NovaChat (backend /support/chat, không cần đăng nhập).

const API = "http://localhost:5005";
const STORE_KEY = "hb_support_chat";

const HELLO = {
  role: "assistant",
  content: "Xin chào anh/chị! 👋 Em là Mi — trợ lý tư vấn của NovaChat.\nAnh/chị cần tìm hiểu gì về dịch vụ ạ? (bảng giá, kết nối Zalo/Messenger, dùng thử…)",
};
const SUGGESTS = ["Giá thế nào?", "Dùng thử ra sao?", "Kết nối Zalo được không?", "Bot làm được gì?"];

function loadMsgs() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || [HELLO]; }
  catch { return [HELLO]; }
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState(loadMsgs);
  const [text, setText] = useState("");
  const [typing, setTyping] = useState(false);
  const [unread, setUnread] = useState(false);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(msgs.slice(-30)));
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [msgs, typing, open]);

  useEffect(() => { if (open) { setUnread(false); inputRef.current?.focus(); } }, [open]);

  async function send(q) {
    const content = (q ?? text).trim();
    if (!content || typing) return;
    setText("");
    const next = [...msgs, { role: "user", content }];
    setMsgs(next);
    setTyping(true);
    let reply = "Dạ mạng đang chập chờn 🙏 anh/chị thử lại giúp em nhé.";
    try {
      const r = await fetch(API + "/support/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: next.slice(-12) }),
      });
      const b = await r.json();
      if (b?.reply) reply = b.reply;
      else if (b?.error) reply = b.error;
    } catch { /* giữ reply mặc định */ }
    setTyping(false);
    setMsgs((m) => [...m, { role: "assistant", content: reply }]);
    if (!open) setUnread(true);
  }

  return (
    <>
      {/* Panel chat */}
      <div className={"cw-panel" + (open ? " open" : "")} aria-hidden={!open}>
        <div className="cw-head">
          <div className="cw-avatar">🏡</div>
          <div className="cw-head-txt">
            <div className="cw-title">NovaChat</div>
            <div className="cw-sub"><span className="cw-dot" /> Mi — tư vấn viên AI, trả lời ngay</div>
          </div>
          <button className="cw-close" onClick={() => setOpen(false)} aria-label="Đóng">✕</button>
        </div>

        <div className="cw-body" ref={bodyRef}>
          {msgs.map((m, i) => (
            <div key={i} className={"cw-msg " + (m.role === "user" ? "me" : "bot")}>
              {m.role === "assistant" && <span className="cw-msg-ava">🏡</span>}
              <div className="cw-bubble">{m.content}</div>
            </div>
          ))}
          {typing && (
            <div className="cw-msg bot">
              <span className="cw-msg-ava">🏡</span>
              <div className="cw-bubble cw-typing"><span /><span /><span /></div>
            </div>
          )}
          {msgs.length <= 1 && (
            <div className="cw-suggests">
              {SUGGESTS.map((s) => (
                <button key={s} className="cw-chip" onClick={() => send(s)}>{s}</button>
              ))}
            </div>
          )}
        </div>

        <div className="cw-foot">
          <input
            ref={inputRef}
            className="cw-input"
            placeholder="Nhập câu hỏi của bạn…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={typing}
          />
          <button className="cw-send" onClick={() => send()} disabled={typing || !text.trim()} aria-label="Gửi">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
        <div className="cw-brand">⚡ NovaChat — bot này cũng chính là sản phẩm</div>
      </div>

      {/* Bong bóng */}
      <button className={"cw-fab" + (open ? " open" : "")} onClick={() => setOpen((v) => !v)} aria-label="Chat tư vấn">
        {unread && !open && <span className="cw-badge">1</span>}
        {open ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
        ) : (
          <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.5 3 2 6.9 2 11.7c0 2.7 1.4 5.1 3.6 6.7-.1.8-.5 2.1-1.5 3.3 0 0 2.4-.3 4.3-1.6 1.1.3 2.4.5 3.6.5 5.5 0 10-3.9 10-8.9S17.5 3 12 3z"/></svg>
        )}
      </button>
    </>
  );
}
