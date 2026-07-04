import { useEffect, useRef, useState } from "react";

// Bong bóng chat tư vấn DỊCH VỤ (kiểu Crisp) — KÉO THẢ được + bấm ✕ để xoá.
// Chat với bot bán hàng của NovaChat (backend /support/chat, không cần đăng nhập).

const API = "http://localhost:5005";
const STORE_KEY = "hb_support_chat";
const POS_KEY = "hb_cw_pos";       // {left, top} px — vị trí đã kéo
const HIDDEN_KEY = "hb_cw_hidden"; // "1" = đã xoá bong bóng

const FAB = 58, MARGIN = 12;

const HELLO = {
  role: "assistant",
  content: "Xin chào anh/chị! 👋 Em là Mi — trợ lý tư vấn của NovaChat.\nAnh/chị cần tìm hiểu gì về dịch vụ ạ? (bảng giá, kết nối Zalo/Messenger, dùng thử…)",
};
const SUGGESTS = ["Giá thế nào?", "Dùng thử ra sao?", "Kết nối Zalo được không?", "Bot làm được gì?"];

function loadMsgs() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || [HELLO]; }
  catch { return [HELLO]; }
}
function loadPos() {
  try { return JSON.parse(localStorage.getItem(POS_KEY)) || null; }
  catch { return null; }
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState(loadMsgs);
  const [text, setText] = useState("");
  const [typing, setTyping] = useState(false);
  const [unread, setUnread] = useState(false);
  const [pos, setPos] = useState(loadPos);   // null = mặc định góc phải dưới
  const [hidden, setHidden] = useState(() => localStorage.getItem(HIDDEN_KEY) === "1");
  const bodyRef = useRef(null);
  const inputRef = useRef(null);
  const drag = useRef(null);   // {dx, dy, moved}

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

  // ── Kéo thả bong bóng ──
  function onPointerDown(e) {
    if (e.button != null && e.button !== 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    drag.current = { dx: e.clientX - rect.left, dy: e.clientY - rect.top, moved: false, sx: e.clientX, sy: e.clientY };
    try { e.currentTarget.setPointerCapture?.(e.pointerId); } catch { /* ignore */ }
  }
  function onPointerMove(e) {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(e.clientX - d.sx) + Math.abs(e.clientY - d.sy) > 4) d.moved = true;
    if (!d.moved) return;
    const left = Math.min(Math.max(e.clientX - d.dx, MARGIN), window.innerWidth - FAB - MARGIN);
    const top = Math.min(Math.max(e.clientY - d.dy, MARGIN), window.innerHeight - FAB - MARGIN);
    setPos({ left, top });
  }
  function onPointerUp(e) {
    const d = drag.current;
    drag.current = null;
    try { e.currentTarget.releasePointerCapture?.(e.pointerId); } catch { /* ignore */ }
    if (!d) return;
    if (d.moved) {
      setPos((p) => { if (p) localStorage.setItem(POS_KEY, JSON.stringify(p)); return p; });
    } else {
      setOpen((v) => !v);   // bấm (không kéo) = mở/đóng
    }
  }

  function removeBubble(e) {
    e.stopPropagation();
    if (!confirm("Ẩn bong bóng chat tư vấn?\n(Muốn hiện lại: vào Cài đặt → Hiện lại bong bóng chat, hoặc xoá dữ liệu trình duyệt.)")) return;
    localStorage.setItem(HIDDEN_KEY, "1");
    setHidden(true); setOpen(false);
  }

  if (hidden) return null;

  // Vị trí root: mặc định góc phải-dưới; đã kéo → theo toạ độ đã lưu
  const rootStyle = pos
    ? { left: pos.left, top: pos.top, right: "auto", bottom: "auto" }
    : undefined;
  // Panel mở lên/xuống, trái/phải tuỳ vị trí bong bóng để không tràn màn hình
  const cx = pos ? pos.left + FAB / 2 : window.innerWidth - 22 - FAB / 2;
  const cy = pos ? pos.top + FAB / 2 : window.innerHeight - 22 - FAB / 2;
  const dropUp = cy > window.innerHeight / 2;
  const alignRight = cx > window.innerWidth / 2;
  const panelPos = `${dropUp ? "up" : "down"} ${alignRight ? "right" : "left"}`;

  return (
    <div className="cw-root" style={rootStyle}>
      {/* Panel chat */}
      <div className={"cw-panel " + panelPos + (open ? " open" : "")} aria-hidden={!open}>
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

      {/* Bong bóng — kéo để di chuyển, bấm để mở, ✕ để xoá */}
      <div className={"cw-fab-wrap" + (open ? " open" : "")}>
        {!open && (
          <button className="cw-fab-x" onClick={removeBubble} title="Ẩn bong bóng chat" aria-label="Ẩn bong bóng">✕</button>
        )}
        <button
          className={"cw-fab" + (open ? " open" : "") + (pos ? " moved" : "")}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          title="Kéo để di chuyển · bấm để mở"
          aria-label="Chat tư vấn"
        >
          {unread && !open && <span className="cw-badge">1</span>}
          {open ? (
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
          ) : (
            <svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M12 3C6.5 3 2 6.9 2 11.7c0 2.7 1.4 5.1 3.6 6.7-.1.8-.5 2.1-1.5 3.3 0 0 2.4-.3 4.3-1.6 1.1.3 2.4.5 3.6.5 5.5 0 10-3.9 10-8.9S17.5 3 12 3z"/></svg>
          )}
        </button>
      </div>
    </div>
  );
}
