import { useEffect, useRef, useState } from "react";
import { tg } from "../telegramApi.js";

function relTime(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)} giây trước`;
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}

// Khách hàng kênh Telegram — tách theo từng bot (mỗi homestay 1 bot).
export default function TelegramConversations() {
  const [bots, setBots] = useState(null);   // null=đang tải
  const [botId, setBotId] = useState("");    // "" = tất cả
  const [list, setList] = useState(null);
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  useEffect(() => {
    tg.bots().then((r) => {
      if (r.ok && Array.isArray(r.body)) setBots(r.body);
      else { setOffline(true); setBots([]); }
    });
  }, []);

  async function loadList() {
    const { ok, body } = await tg.conversations(botId);
    if (!ok || !Array.isArray(body)) { setOffline(true); setList([]); return; }
    setOffline(false); setList(body);
  }

  useEffect(() => {
    setSel(null); setDetail(null); setList(null);
    loadList();
    clearInterval(timer.current);
    timer.current = setInterval(loadList, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [botId]);

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await tg.conversation(uid);
    if (ok) setDetail(body);
  }
  async function onToggle() {
    if (!detail) return;
    await tg.toggleBot(detail.user_id, detail.owner_active);
    openChat(detail.user_id); loadList();
  }
  async function onReset(uid) {
    if (!confirm("Xoá toàn bộ hội thoại của khách này?")) return;
    await tg.resetConv(uid);
    setSel(null); setDetail(null); loadList();
  }

  async function onSetOwner(uid) {
    if (!confirm("Đặt người này làm CHỦ NHÀ (nhận tin nhắn báo + cuộc gọi khi khách cần)?")) return;
    const r = await tg.setOwner(uid);
    alert(r.ok ? "✅ Đã đặt làm chủ nhà." : "❌ Lỗi đặt chủ.");
  }

  if (bots === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;
  if (offline)
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Telegram (cổng 5007)</div>
        <p className="hint">Chạy <code>python -m app.main_telegram</code> rồi tải lại.</p>
      </div>
    );

  return (
    <div>
      {bots.length > 1 && (
        <div className="page-tabs">
          <button className={"page-tab" + (botId === "" ? " active" : "")} onClick={() => setBotId("")}>Tất cả</button>
          {bots.map((b) => (
            <button key={b.bot_id} className={"page-tab" + (b.bot_id === botId ? " active" : "")}
                    onClick={() => setBotId(b.bot_id)}>
              @{b.username || b.bot_id}
            </button>
          ))}
        </div>
      )}

      {sel && detail ? (
        <div className="chatview">
          <div className="chat-top">
            <button className="btn-ghost" onClick={() => { setSel(null); setDetail(null); }}>← Danh sách</button>
            <strong>…{detail.user_id.slice(-8)}</strong>
            {detail.owner_active
              ? <span className="badge owner">⛔ Chủ đang xử lý</span>
              : <span className="badge bot">🤖 Bot đang trả lời</span>}
            <div className="chat-actions">
              <button className="btn-mini" onClick={() => onSetOwner(detail.user_id)} title="Đặt người này làm chủ nhà">⭐ Đặt làm chủ</button>
              <button className="btn-mini" onClick={onToggle}>{detail.owner_active ? "▶ Bật bot" : "⏸ Tắt bot"}</button>
              <button className="btn-mini danger" onClick={() => onReset(detail.user_id)}>Xoá</button>
            </div>
          </div>
          <div className="bubbles">
            {detail.messages.length === 0 && <p className="hint">Chưa có tin nhắn.</p>}
            {detail.messages.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>{m.content}</div>
            ))}
          </div>
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">{list ? `${list.length} hội thoại` : "Đang tải…"} · tự làm mới 8s</span>
            <button className="btn-ghost" onClick={loadList}>Làm mới</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>Chưa có khách nào nhắn.</p>
          )}
          {list && list.map((c) => (
            <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
              <div className="conv-main">
                <div className="conv-line1">
                  <strong>…{c.user_id.slice(-8)}</strong>
                  {c.owner_active ? <span className="badge owner">⛔ Chủ</span> : <span className="badge bot">🤖 Bot</span>}
                  <span className="badge stage">{c.stage}</span>
                  <span className="conv-time">{relTime(c.last_updated)}</span>
                </div>
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
