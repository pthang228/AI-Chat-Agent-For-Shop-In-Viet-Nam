import { useEffect, useRef, useState } from "react";
import { tiktok } from "../tiktokApi.js";
import ChatSend from "./ChatSend.jsx";

function displayName(c) {
  const uid = String(c.user_id || "");
  return c.name ? `${c.name} (…${uid.slice(-6)})` : `…${uid.slice(-8)}`;
}

function relTime(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)} giây trước`;
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}

// Khách hàng kênh TikTok — tách theo từng account (mỗi khách hàng 1 account).
export default function TikTokConversations() {
  const [accounts, setAccounts] = useState(null);   // null=đang tải
  const [bizId, setBizId] = useState("");           // "" = tất cả
  const [list, setList] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const PAGE = 50;
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);
  const offRef = useRef(0);   // trang hiện tại — interval chỉ tự refresh khi ở trang đầu

  useEffect(() => {
    tiktok.accounts().then((r) => {
      if (r.ok && Array.isArray(r.body)) setAccounts(r.body);
      else { setOffline(true); setAccounts([]); }
    });
  }, []);

  async function loadList(off = 0, append = false) {
    const { ok, body } = await tiktok.conversations(bizId, { limit: PAGE, offset: off });
    if (!ok || !body?.items) { setOffline(true); if (!append) setList([]); return; }
    setOffline(false);
    setTotal(body.total ?? 0);
    setOffset(off);
    offRef.current = off;
    setList((prev) => append ? [...(prev ?? []), ...body.items] : body.items);
  }

  useEffect(() => {
    setSel(null); setDetail(null); setList(null); setOffset(0); setTotal(0);
    loadList(0);
    clearInterval(timer.current);
    timer.current = setInterval(() => { if (offRef.current === 0) loadList(0); }, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bizId]);

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await tiktok.conversation(uid);
    if (ok) setDetail(body);
  }
  async function onToggle() {
    if (!detail) return;
    await tiktok.toggleBot(detail.user_id, detail.owner_active);
    openChat(detail.user_id); loadList();
  }
  async function onReset(uid) {
    if (!confirm("Xoá toàn bộ hội thoại của khách này?")) return;
    await tiktok.resetConv(uid);
    setSel(null); setDetail(null); loadList();
  }
  async function onSetOwner(uid) {
    if (!confirm("Đặt người này làm CHỦ NHÀ (nhận tin nhắn báo khi khách cần)?")) return;
    const r = await tiktok.setOwner(uid);
    alert(r.ok ? "✅ Đã đặt làm chủ nhà." : "❌ Lỗi đặt chủ.");
  }

  if (accounts === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;
  if (offline)
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ TikTok (cổng 5008)</div>
        <p className="hint">Chạy <code>python -m app.main_tiktok</code> rồi tải lại.</p>
      </div>
    );

  return (
    <div>
      {accounts.length > 1 && (
        <div className="page-tabs">
          <button className={"page-tab" + (bizId === "" ? " active" : "")} onClick={() => setBizId("")}>Tất cả</button>
          {accounts.map((a) => (
            <button key={a.business_id} className={"page-tab" + (a.business_id === bizId ? " active" : "")}
                    onClick={() => setBizId(a.business_id)}>
              {a.name || a.username || a.business_id}
            </button>
          ))}
        </div>
      )}

      {sel && detail ? (
        <div className="chatview">
          <div className="chat-top">
            <button className="btn-ghost" onClick={() => { setSel(null); setDetail(null); }}>← Danh sách</button>
            <strong>{displayName(detail)}</strong>
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
          <ChatSend onSend={async (text) => {
            const r = await tiktok.sendMessage(detail.user_id, text);
            if (r.ok) { openChat(detail.user_id); loadList(0); }
            return r.ok;
          }} />
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">
              {list ? `${list.length}/${total} hội thoại` : "Đang tải…"} · tự làm mới 8s
            </span>
            <button className="btn-ghost" onClick={() => loadList(0)}>Làm mới</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>Chưa có khách nào nhắn.</p>
          )}
          {list && list.map((c) => (
            <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
              <div className="conv-main">
                <div className="conv-line1">
                  <strong>{displayName(c)}</strong>
                  {c.owner_active ? <span className="badge owner">⛔ Chủ</span> : <span className="badge bot">🤖 Bot</span>}
                  <span className="badge stage">{c.stage}</span>
                  <span className="conv-time">{relTime(c.last_updated)}</span>
                </div>
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
          {list && list.length < total && (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <button className="btn-ghost" onClick={() => loadList(offset + PAGE, true)}>
                Tải thêm ({total - list.length} còn lại)
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
