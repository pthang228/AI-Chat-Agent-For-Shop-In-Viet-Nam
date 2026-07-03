import { useEffect, useRef, useState } from "react";
import { meta } from "../metaApi.js";
import ChatSend from "./ChatSend.jsx";

function displayName(c) {
  return c.name ? `${c.name} (…${c.user_id.slice(-6)})` : `…${c.user_id.slice(-8)}`;
}

function relTime(iso) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return `${Math.floor(diff)} giây trước`;
  if (diff < 3600) return `${Math.floor(diff / 60)} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}

// Khách hàng kênh Meta — TÁCH RIÊNG theo từng Page (mỗi khách hàng 1 danh sách).
export default function MetaConversations() {
  const [pages, setPages] = useState(null);   // null = đang tải
  const [pageId, setPageId] = useState("");    // Page đang chọn
  const [list, setList] = useState(null);
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  // Tải danh sách Page (mỗi Page là 1 "tab" khách riêng)
  useEffect(() => {
    meta.pages().then((r) => {
      if (r.ok && Array.isArray(r.body)) {
        setPages(r.body);
        if (r.body.length) setPageId(r.body[0].page_id);
      } else { setOffline(true); setPages([]); }
    });
  }, []);

  async function loadList() {
    if (!pageId) { setList([]); return; }
    const { ok, body } = await meta.conversations(pageId);
    if (!ok || !Array.isArray(body)) { setOffline(true); setList([]); return; }
    setOffline(false); setList(body);
  }

  // Đổi Page → tải lại danh sách khách của Page đó, tự làm mới 8s
  useEffect(() => {
    if (!pageId) return;
    setSel(null); setDetail(null); setList(null);
    loadList();
    clearInterval(timer.current);
    timer.current = setInterval(loadList, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageId]);

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await meta.conversation(uid);
    if (ok) setDetail(body);
  }

  async function onToggle() {
    if (!detail) return;
    await meta.toggleBot(detail.user_id, detail.owner_active); // owner_active → bật bot lại
    openChat(detail.user_id);
    loadList();
  }

  async function onReset(uid) {
    if (!confirm("Xoá toàn bộ hội thoại của khách này?")) return;
    await meta.resetConv(uid);
    setSel(null); setDetail(null);
    loadList();
  }

  if (pages === null)
    return <div className="connect"><div className="status muted">Đang tải…</div></div>;

  if (offline)
    return (
      <div className="connect">
        <div className="status warn">⚠️ Chưa kết nối được máy chủ Meta (cổng 5006)</div>
        <p className="hint">Chạy <code>python -m app.main_meta</code> rồi tải lại.</p>
      </div>
    );

  if (pages.length === 0)
    return (
      <div className="connect">
        <div className="status muted">Chưa có Page nào kết nối</div>
        <p className="hint">Vào tab <b>Kết nối</b> → Đăng nhập Facebook → chọn Page trước.</p>
      </div>
    );

  return (
    <div>
      {/* Bộ chọn Page — mỗi Page = data khách riêng */}
      {pages.length > 1 && (
        <div className="page-tabs">
          {pages.map((p) => (
            <button
              key={p.page_id}
              className={"page-tab" + (p.page_id === pageId ? " active" : "")}
              onClick={() => setPageId(p.page_id)}
            >
              {p.name || p.page_id}
            </button>
          ))}
        </div>
      )}
      {pages.length === 1 && (
        <div className="page-current">Khách của: <b>{pages[0].name || pages[0].page_id}</b></div>
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
              <button className="btn-mini" onClick={onToggle}>
                {detail.owner_active ? "▶ Bật bot" : "⏸ Tắt bot"}
              </button>
              <button className="btn-mini danger" onClick={() => onReset(detail.user_id)}>Xoá</button>
            </div>
          </div>
          <div className="bubbles">
            {detail.messages.length === 0 && <p className="hint">Chưa có tin nhắn.</p>}
            {detail.messages.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>
                {m.content}
              </div>
            ))}
          </div>
          <ChatSend onSend={async (text) => {
            const r = await meta.sendMessage(detail.user_id, text);
            if (r.ok) { openChat(detail.user_id); loadList(); }
            return r.ok;
          }} />
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">{list ? `${list.length} hội thoại` : "Đang tải…"} · tự làm mới 8s</span>
            <button className="btn-ghost" onClick={loadList}>Làm mới</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>Chưa có khách nào nhắn Page này.</p>
          )}
          {list && list.map((c) => (
            <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
              <div className="conv-main">
                <div className="conv-line1">
                  <strong>{displayName(c)}</strong>
                  {c.owner_active
                    ? <span className="badge owner">⛔ Chủ</span>
                    : <span className="badge bot">🤖 Bot</span>}
                  <span className="badge stage">{c.stage}</span>
                  <span className="conv-time">{relTime(c.last_updated)}</span>
                </div>
                {c.checkin && <div className="conv-meta">📅 {c.checkin}{c.checkout && c.checkout !== c.checkin ? ` → ${c.checkout}` : ""}</div>}
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
