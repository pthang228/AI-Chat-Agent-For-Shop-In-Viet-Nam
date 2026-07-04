import { useEffect, useMemo, useRef, useState } from "react";
import { currentUser } from "../auth.js";
import { getApps } from "../store.js";
import { brain } from "../brainApi.js";
import { meta } from "../metaApi.js";
import { tg } from "../telegramApi.js";
import { tiktok } from "../tiktokApi.js";
import { shopee } from "../shopeeApi.js";
import ChatSend from "./ChatSend.jsx";

/*
 * Hộp thư hợp nhất (như AloChat): gộp hội thoại từ CẢ 4 kênh về 1 chỗ, mỗi
 * hội thoại ghi rõ KÊNH / APP / SHOP + lọc theo kênh + tìm kiếm. Cột phải xem
 * & nhắn tay. Dùng lại đúng API từng kênh (list/detail/send/toggle/reset).
 */

const CH = {
  zalo:     { label: "Zalo",      icon: "💬", color: "#0068ff" },
  meta:     { label: "Mess + IG", icon: "✉️", color: "#7b3fb3" },
  telegram: { label: "Telegram",  icon: "✈️", color: "#229ED9" },
  tiktok:   { label: "TikTok",    icon: "🎵", color: "#161823" },
  shopee:   { label: "Shopee",    icon: "🛒", color: "#EE4D2D" },
};

// Bộ chuyển API theo kênh — che khác biệt tên hàm (brain.reset vs .resetConv…)
const API = {
  zalo:     { list: () => brain.conversations(),  detail: (u) => brain.conversation(u), send: (u, t) => brain.sendMessage(u, t), toggle: (u, on) => brain.toggleBot(u, on),  reset: (u) => brain.reset(u) },
  meta:     { list: () => meta.conversations(),   detail: (u) => meta.conversation(u),  send: (u, t) => meta.sendMessage(u, t),  toggle: (u, on) => meta.toggleBot(u, on),   reset: (u) => meta.resetConv(u) },
  telegram: { list: () => tg.conversations(),     detail: (u) => tg.conversation(u),    send: (u, t) => tg.sendMessage(u, t),    toggle: (u, on) => tg.toggleBot(u, on),     reset: (u) => tg.resetConv(u) },
  tiktok:   { list: () => tiktok.conversations(), detail: (u) => tiktok.conversation(u),send: (u, t) => tiktok.sendMessage(u, t),toggle: (u, on) => tiktok.toggleBot(u, on), reset: (u) => tiktok.resetConv(u) },
  shopee:   { list: () => shopee.conversations(), detail: (u) => shopee.conversation(u),send: (u, t) => shopee.sendMessage(u, t),toggle: (u, on) => shopee.toggleBot(u, on), reset: (u) => shopee.resetConv(u) },
};

function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }
function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }
function displayName(c) {
  return c.name ? c.name : `Khách …${String(c.user_id || "").slice(-6)}`;
}
function relTime(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "vừa xong";
  if (diff < 3600) return `${Math.floor(diff / 60)} phút`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ`;
  return `${Math.floor(diff / 86400)} ngày`;
}

export default function InboxSection() {
  const user = currentUser();
  const shopName = user?.homestay || user?.username || "Shop của tôi";

  const [convs, setConvs] = useState(null);     // null = đang tải
  const [appMap, setAppMap] = useState({});     // kênh → tên app
  const [filter, setFilter] = useState("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);         // {ch, user_id}
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  // Map kênh → tên app (để ghi "app nào")
  useEffect(() => {
    getApps().then((r) => {
      if (!Array.isArray(r)) return;
      const m = {};
      for (const a of r) { const k = botKey(a.channel); if (!m[k]) m[k] = a.name; }
      setAppMap(m);
    });
  }, []);

  async function loadAll() {
    const entries = Object.keys(API);
    const results = await Promise.all(entries.map((ch) => API[ch].list()));
    const merged = [];
    results.forEach((r, i) => {
      const ch = entries[i];
      // bridge/meta trả MẢNG; tg/tiktok/shopee trả {total, items} (pagination)
      const arr = r && r.ok
        ? (Array.isArray(r.body) ? r.body : (r.body?.items || []))
        : [];
      for (const c of arr) merged.push({ ...c, _ch: ch });
    });
    merged.sort((a, b) => new Date(b.last_updated || 0) - new Date(a.last_updated || 0));
    setConvs(merged);
  }

  useEffect(() => {
    loadAll();
    timer.current = setInterval(loadAll, 10000);
    return () => clearInterval(timer.current);
  }, []);

  async function openChat(ch, uid) {
    setSel({ ch, user_id: uid });
    const r = await API[ch].detail(uid);
    if (r.ok) setDetail({ ...r.body, _ch: ch });
  }
  async function onToggle() {
    if (!sel || !detail) return;
    await API[sel.ch].toggle(detail.user_id, detail.owner_active); // owner_active → bật lại bot
    openChat(sel.ch, detail.user_id); loadAll();
  }
  async function onReset() {
    if (!sel || !confirm("Xoá toàn bộ hội thoại của khách này?")) return;
    await API[sel.ch].reset(sel.user_id);
    setSel(null); setDetail(null); loadAll();
  }

  const counts = useMemo(() => {
    const c = { all: 0, zalo: 0, meta: 0, telegram: 0, tiktok: 0, shopee: 0 };
    for (const x of convs || []) { c.all++; c[x._ch] = (c[x._ch] || 0) + 1; }
    return c;
  }, [convs]);

  const shown = useMemo(() => {
    let list = convs || [];
    if (filter !== "all") list = list.filter((c) => c._ch === filter);
    const s = q.trim().toLowerCase();
    if (s) list = list.filter((c) =>
      (displayName(c).toLowerCase().includes(s)) || (c.last_msg || "").toLowerCase().includes(s));
    return list;
  }, [convs, filter, q]);

  const TABS = [["all", "Tất cả"], ...Object.entries(CH).map(([k, v]) => [k, v.label])];

  return (
    <div className="inbox">
      {/* ── Cột trái: danh sách ── */}
      <div className="inbox-list">
        <div className="inbox-tabs">
          {TABS.map(([k, label]) => (
            <button key={k}
                    className={"inbox-tab" + (filter === k ? " active" : "")}
                    onClick={() => setFilter(k)}>
              {k !== "all" && <span>{CH[k].icon}</span>}{label}
              <span className="inbox-tab-n">{counts[k] || 0}</span>
            </button>
          ))}
        </div>
        <input className="inbox-search" placeholder="🔍 Tìm khách hàng, tin nhắn…"
               value={q} onChange={(e) => setQ(e.target.value)} />

        <div className="inbox-rows">
          {convs === null && <p className="hint inbox-empty">Đang tải hội thoại…</p>}
          {convs && shown.length === 0 && (
            <div className="inbox-empty">
              <div style={{ fontSize: 34 }}>💬</div>
              <p className="hint">Chưa có hội thoại{filter !== "all" ? ` ở ${CH[filter].label}` : ""}.</p>
            </div>
          )}
          {shown.map((c) => {
            const ch = CH[c._ch];
            const active = sel && sel.ch === c._ch && sel.user_id === c.user_id;
            return (
              <div key={c._ch + c.user_id}
                   className={"inbox-row" + (active ? " active" : "")}
                   onClick={() => openChat(c._ch, c.user_id)}>
                <div className="inbox-av" style={{ background: ch.color }}>{initials(displayName(c))}</div>
                <div className="inbox-row-main">
                  <div className="inbox-row-l1">
                    <strong>{displayName(c)}</strong>
                    <span className="inbox-time">{relTime(c.last_updated)}</span>
                  </div>
                  <div className="inbox-row-tags">
                    <span className="ch-chip" style={{ "--c": ch.color }}>{ch.icon} {ch.label}</span>
                    <span className="inbox-app">{appMap[c._ch] || ch.label}</span>
                    <span className="inbox-shop">🏬 {shopName}</span>
                  </div>
                  {c.last_msg && <div className="inbox-preview">{c.last_msg}</div>}
                  <div className="inbox-row-badges">
                    {c.owner_active
                      ? <span className="badge owner">⛔ Chủ</span>
                      : <span className="badge bot">🤖 Bot</span>}
                    {c.stage && <span className="badge stage">{c.stage}</span>}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Cột phải: chi tiết ── */}
      <div className="inbox-detail">
        {!sel || !detail ? (
          <div className="inbox-detail-empty">
            <div style={{ fontSize: 46, opacity: .4 }}>💬</div>
            <h3>Chọn một hội thoại</h3>
            <p className="hint">Hội thoại từ mọi kênh (Zalo · Mess+IG · Telegram · TikTok) gộp về đây.</p>
          </div>
        ) : (
          <>
            <div className="inbox-chat-top">
              <div className="inbox-av" style={{ background: CH[detail._ch].color }}>{initials(displayName(detail))}</div>
              <div className="inbox-chat-who">
                <strong>{displayName(detail)}</strong>
                <div className="inbox-chat-sub">
                  <span className="ch-chip" style={{ "--c": CH[detail._ch].color }}>
                    {CH[detail._ch].icon} {CH[detail._ch].label}
                  </span>
                  <span className="inbox-app">{appMap[detail._ch] || CH[detail._ch].label}</span>
                  <span className="inbox-shop">🏬 {shopName}</span>
                </div>
              </div>
              <div className="inbox-chat-actions">
                {detail.owner_active
                  ? <span className="badge owner">⛔ Chủ đang xử lý</span>
                  : <span className="badge bot">🤖 Bot đang trả lời</span>}
                <button className="btn-mini" onClick={onToggle}>
                  {detail.owner_active ? "▶ Bật bot" : "⏸ Tắt bot"}
                </button>
                <button className="btn-mini danger" onClick={onReset}>Xoá</button>
              </div>
            </div>
            <div className="bubbles inbox-bubbles">
              {(detail.messages || []).length === 0 && <p className="hint">Chưa có tin nhắn.</p>}
              {(detail.messages || []).map((m, i) => (
                <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>{m.content}</div>
              ))}
            </div>
            <ChatSend onSend={async (text) => {
              const r = await API[sel.ch].send(detail.user_id, text);
              if (r.ok) { openChat(sel.ch, detail.user_id); loadAll(); }
              return r.ok;
            }} />
          </>
        )}
      </div>
    </div>
  );
}
