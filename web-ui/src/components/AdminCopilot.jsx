import { useEffect, useRef, useState } from "react";
import { copilotApi } from "../copilotApi.js";

/*
 * Trợ lý QUẢN TRỊ (copilot) — bong bóng nổi cho CHỦ SHOP đã đăng nhập.
 * Khác "Mi" (ChatWidget, tư vấn khách lạ trên landing): con này đọc trạng thái
 * THẬT của tài khoản + làm giúp việc an toàn (bật/tắt bot, tạo câu mẫu) có XÁC
 * NHẬN, và gợi ý mở đúng trang. Dùng chung khung .cw-* nhưng tông tím + icon bot.
 */

const STORE_KEY = "hb_copilot_chat";
const HELLO = {
  role: "assistant",
  content: "Chào anh/chị! 🤖 Em là Trợ lý NovaChat.\nEm giúp anh/chị cài đặt & vận hành: kết nối kênh, bật/tắt bot, dạy AI, xem tình hình shop… Anh/chị cần gì ạ?",
};
const SUGGESTS = ["Tình hình shop thế nào?", "Kết nối Zalo sao?", "Tắt bot Telegram giúp em", "Dạy AI ở đâu?"];

function loadMsgs() {
  try { return JSON.parse(sessionStorage.getItem(STORE_KEY)) || [HELLO]; }
  catch { return [HELLO]; }
}

const BotIcon = (p) => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" {...p}>
    <rect x="4" y="8" width="16" height="11" rx="2.5" /><path d="M12 8V4M8 3h8M8.5 13h.01M15.5 13h.01M9 16.5h6" />
  </svg>
);

export default function AdminCopilot() {
  const [open, setOpen] = useState(false);
  // Hạng trợ lý do BACKEND quyết theo gói: "basic" (chưa đăng ký) / "premium" (có gói)
  const [mode, setMode] = useState(() => sessionStorage.getItem("hb_copilot_mode") || "");
  const [msgs, setMsgs] = useState(loadMsgs);   // {role, content, navigate?, pending?}
  const [text, setText] = useState("");
  const [typing, setTyping] = useState(false);
  const bodyRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(msgs.slice(-30)));
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [msgs, typing, open]);
  useEffect(() => { if (open) inputRef.current?.focus(); }, [open]);

  async function send(q) {
    const content = (q ?? text).trim();
    if (!content || typing) return;
    setText("");
    const hist = msgs.filter((m) => m.role === "user" || m.role === "assistant")
                     .map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content }]);
    setTyping(true);
    const r = await copilotApi.chat(content, hist.slice(-10));
    setTyping(false);
    if (r.ok && r.body?.ok) {
      if (r.body.mode) { setMode(r.body.mode); sessionStorage.setItem("hb_copilot_mode", r.body.mode); }
      setMsgs((m) => [...m, {
        role: "assistant", content: r.body.reply,
        navigate: r.body.navigate || [], pending: r.body.pending_action || null,
      }]);
    } else {
      setMsgs((m) => [...m, { role: "assistant",
        content: r.status === 401 ? "Phiên đăng nhập hết hạn — anh/chị đăng nhập lại giúp em nhé."
          : "Dạ em đang quá tải chút 🙏 anh/chị thử lại sau giây lát ạ." }]);
    }
  }

  async function confirm(mi, action) {
    setTyping(true);
    const r = await copilotApi.confirm(action.name, action.args, action.sig);
    setTyping(false);
    // gỡ pending khỏi tin đó + thêm kết quả
    setMsgs((m) => m.map((x, i) => i === mi ? { ...x, pending: null, done: true } : x)
                    .concat([{ role: "assistant",
                               content: (r.body?.ok ? "✅ " : "⚠️ ") + (r.body?.message || "Đã xử lý.") }]));
  }
  function cancel(mi) {
    setMsgs((m) => m.map((x, i) => i === mi ? { ...x, pending: null } : x));
  }
  function go(to) { window.location.href = to; }

  return (
    <div className="cw-root co-root">
      <div className={"cw-panel up right co-panel" + (open ? " open" : "")} aria-hidden={!open}>
        <div className="cw-head co-head">
          <div className="cw-avatar co-avatar"><BotIcon /></div>
          <div className="cw-head-txt">
            <div className="cw-title">Trợ lý NovaChat{mode === "premium" ? " ✦" : ""}</div>
            <div className="cw-sub"><span className="cw-dot" /> {mode === "basic"
              ? "Bản cơ bản — đăng ký gói để mở trợ lý chuyên sâu"
              : "Giúp anh/chị cài đặt & quản lý"}</div>
          </div>
          <button className="cw-close" onClick={() => setOpen(false)} aria-label="Đóng">✕</button>
        </div>

        <div className="cw-body" ref={bodyRef}>
          {msgs.map((m, i) => (
            <div key={i} className={"cw-msg " + (m.role === "user" ? "me" : "bot")}>
              {m.role === "assistant" && <span className="cw-msg-ava co-msg-ava"><BotIcon width={14} height={14} /></span>}
              <div style={{ maxWidth: "82%" }}>
                <div className="cw-bubble">{m.content}</div>
                {(m.navigate || []).length > 0 && (
                  <div className="co-navs">
                    {m.navigate.map((n, k) => (
                      <button key={k} className="co-nav" onClick={() => go(n.to)}>{n.label} ↗</button>
                    ))}
                  </div>
                )}
                {m.pending && (
                  <div className="co-action">
                    <button className="co-confirm" onClick={() => confirm(i, m.pending)}>✅ {m.pending.label}</button>
                    <button className="co-cancel" onClick={() => cancel(i)}>Huỷ</button>
                  </div>
                )}
              </div>
            </div>
          ))}
          {typing && (
            <div className="cw-msg bot">
              <span className="cw-msg-ava co-msg-ava"><BotIcon width={14} height={14} /></span>
              <div className="cw-bubble cw-typing"><span /><span /><span /></div>
            </div>
          )}
          {msgs.length <= 1 && (
            <div className="cw-suggests">
              {SUGGESTS.map((s) => <button key={s} className="cw-chip" onClick={() => send(s)}>{s}</button>)}
            </div>
          )}
        </div>

        <div className="cw-foot">
          <input ref={inputRef} className="cw-input" placeholder="Hỏi hoặc nhờ em làm gì đó…"
                 value={text} onChange={(e) => setText(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && send()} disabled={typing} />
          <button className="cw-send co-send" onClick={() => send()} disabled={typing || !text.trim()} aria-label="Gửi">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>

      <div className={"cw-fab-wrap" + (open ? " open" : "")}>
        <button className={"cw-fab co-fab" + (open ? " open" : "")} onClick={() => setOpen((v) => !v)}
                title="Trợ lý quản trị" aria-label="Trợ lý quản trị">
          {open
            ? <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><line x1="6" y1="6" x2="18" y2="18" /><line x1="18" y1="6" x2="6" y2="18" /></svg>
            : <BotIcon width={26} height={26} />}
        </button>
      </div>
    </div>
  );
}
