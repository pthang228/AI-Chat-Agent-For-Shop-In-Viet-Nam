import { useEffect, useMemo, useRef, useState } from "react";
import { currentUser } from "../auth.js";
import { teamApi } from "../teamApi.js";
import { getApps } from "../store.js";
import { CH_HOST } from "../apiConfig.js";
import { brain } from "../brainApi.js";
import { meta } from "../metaApi.js";
import { tg } from "../telegramApi.js";
import { tiktok } from "../tiktokApi.js";
import { shopee } from "../shopeeApi.js";
import { zalooa } from "../zaloOaApi.js";
import { webchat } from "../webchatApi.js";
import ChatSend from "./ChatSend.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";
import { sendMedia, makeOrder, assignConv, canned as cannedApi } from "../chatToolsApi.js";

/*
 * Hộp thư hợp nhất (như AloChat): gộp hội thoại từ CẢ 4 kênh về 1 chỗ, mỗi
 * hội thoại ghi rõ KÊNH / APP / SHOP + lọc theo kênh + tìm kiếm. Cột phải xem
 * & nhắn tay. Dùng lại đúng API từng kênh (list/detail/send/toggle/reset).
 */

// icon logo thương hiệu thật render qua <ChannelTile ch={key}/> (bỏ emoji)
const CH = {
  zalo:     { label: "Zalo",      color: "#0068ff" },
  meta:     { label: "Mess + IG", color: "#7b3fb3" },
  telegram: { label: "Telegram",  color: "#229ED9" },
  tiktok:   { label: "TikTok",    color: "#161823" },
  shopee:   { label: "Shopee",    color: "#EE4D2D" },
  zalooa:   { label: "Zalo OA",   color: "#005AE0" },
  webchat:  { label: "Website",   color: "#4F46E5" },
};

// Bộ chuyển API theo kênh — che khác biệt tên hàm (brain.reset vs .resetConv…)
const API = {
  zalo:     { list: () => brain.conversations(),  detail: (u) => brain.conversation(u), send: (u, t) => brain.sendMessage(u, t), toggle: (u, on) => brain.toggleBot(u, on),  reset: (u) => brain.reset(u) },
  meta:     { list: () => meta.conversations(),   detail: (u) => meta.conversation(u),  send: (u, t) => meta.sendMessage(u, t),  toggle: (u, on) => meta.toggleBot(u, on),   reset: (u) => meta.resetConv(u) },
  telegram: { list: () => tg.conversations(),     detail: (u) => tg.conversation(u),    send: (u, t) => tg.sendMessage(u, t),    toggle: (u, on) => tg.toggleBot(u, on),     reset: (u) => tg.resetConv(u) },
  tiktok:   { list: () => tiktok.conversations(), detail: (u) => tiktok.conversation(u),send: (u, t) => tiktok.sendMessage(u, t),toggle: (u, on) => tiktok.toggleBot(u, on), reset: (u) => tiktok.resetConv(u) },
  shopee:   { list: () => shopee.conversations(), detail: (u) => shopee.conversation(u),send: (u, t) => shopee.sendMessage(u, t),toggle: (u, on) => shopee.toggleBot(u, on), reset: (u) => shopee.resetConv(u) },
  zalooa:   { list: () => zalooa.conversations(), detail: (u) => zalooa.conversation(u),send: (u, t) => zalooa.sendMessage(u, t),toggle: (u, on) => zalooa.toggleBot(u, on), reset: (u) => zalooa.resetConv(u) },
  webchat:  { list: () => webchat.conversations(), detail: (u) => webchat.conversation(u),send: (u, t) => webchat.sendMessage(u, t),toggle: (u, on) => webchat.toggleBot(u, on), reset: (u) => webchat.resetConv(u) },
};

// Avatar tương đối ("/tg/avatar/x.jpg") → prefix host của server kênh đó;
// URL đầy đủ (CDN Meta/Zalo) → dùng thẳng.
const API_BASE = CH_HOST;
function avatarSrc(c, ch) {
  const a = c?.avatar || "";
  if (!a) return "";
  return a.startsWith("http") ? a : (API_BASE[ch] || "") + a;
}

// Ảnh đại diện THẬT của khách (kênh cung cấp); không có/lỗi tải → chữ cái đầu như cũ
function Avatar({ c, ch, color }) {
  const src = avatarSrc(c, ch);
  return (
    <div className="inbox-av" style={{ background: color }}>
      {initials(displayName(c))}
      {src && <img src={src} alt="" loading="lazy"
                   onError={(e) => { e.currentTarget.style.display = "none"; }} />}
    </div>
  );
}

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
  const [mates, setMates] = useState([]);       // thành viên workspace (phân công)
  const [assignFilter, setAssignFilter] = useState("all"); // all | mine | none
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);         // {ch, user_id}
  const [detail, setDetail] = useState(null);
  const [canned, setCanned] = useState([]);
  const [orderMsg, setOrderMsg] = useState("");
  const timer = useRef(null);

  // Câu trả lời mẫu (kho chung ở bridge 5005)
  useEffect(() => {
    cannedApi.list().then((r) => { if (r.ok && Array.isArray(r.body)) setCanned(r.body); });
  }, []);

  // Thành viên team (chủ + nhân viên) — dropdown phân công hội thoại
  useEffect(() => {
    teamApi.teammates().then((r) => { if (r.ok && Array.isArray(r.body)) setMates(r.body); });
  }, []);
  const mateName = (username) => {
    const m = mates.find((x) => x.username === username);
    return m ? (m.name || m.username) : username;
  };

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
    // Mở thẳng 1 hội thoại nếu được trỏ tới (nút "Xem hội thoại" ở mục Khách hàng)
    try {
      const hint = JSON.parse(sessionStorage.getItem("hb_open_conv") || "null");
      if (hint?.ch && hint?.user_id) {
        sessionStorage.removeItem("hb_open_conv");
        openChat(hint.ch, hint.user_id);
      }
    } catch { /* ignore */ }
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    const c = { all: 0, zalo: 0, meta: 0, telegram: 0, tiktok: 0, shopee: 0, zalooa: 0, webchat: 0 };
    for (const x of convs || []) { c.all++; c[x._ch] = (c[x._ch] || 0) + 1; }
    return c;
  }, [convs]);

  const shown = useMemo(() => {
    let list = convs || [];
    if (filter !== "all") list = list.filter((c) => c._ch === filter);
    if (assignFilter === "mine") list = list.filter((c) => c.assigned_to === user?.username);
    if (assignFilter === "none") list = list.filter((c) => !c.assigned_to);
    const s = q.trim().toLowerCase();
    if (s) list = list.filter((c) =>
      (displayName(c).toLowerCase().includes(s)) || (c.last_msg || "").toLowerCase().includes(s));
    return list;
  }, [convs, filter, assignFilter, q, user?.username]);

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
              {k !== "all" && <ChannelTile ch={k} size={16} />}{label}
              <span className="inbox-tab-n">{counts[k] || 0}</span>
            </button>
          ))}
        </div>
        <input className="inbox-search" placeholder="🔍 Tìm khách hàng, tin nhắn…"
               value={q} onChange={(e) => setQ(e.target.value)} />
        {mates.length > 1 && (
          <div className="inbox-assign-bar">
            {[["all", "Tất cả"], ["mine", "👤 Của tôi"], ["none", "Chưa phân công"]].map(([k, label]) => (
              <button key={k}
                      className={"inbox-tab" + (assignFilter === k ? " active" : "")}
                      onClick={() => setAssignFilter(k)}>{label}</button>
            ))}
          </div>
        )}

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
                <Avatar c={c} ch={c._ch} color={ch.color} />
                <div className="inbox-row-main">
                  <div className="inbox-row-l1">
                    <strong>{displayName(c)}</strong>
                    <span className="inbox-time">{relTime(c.last_updated)}</span>
                  </div>
                  <div className="inbox-row-tags">
                    <span className="ch-chip" style={{ "--c": ch.color }}>
                      <ChannelTile ch={c._ch} size={13} /> {ch.label}
                    </span>
                    <span className="inbox-app">{appMap[c._ch] || ch.label}</span>
                    <span className="inbox-shop">🏬 {shopName}</span>
                  </div>
                  {c.last_msg && <div className="inbox-preview">{c.last_msg}</div>}
                  <div className="inbox-row-badges">
                    {c.owner_active
                      ? <span className="badge owner">⛔ Chủ</span>
                      : <span className="badge bot">🤖 Bot</span>}
                    {c.stage && <span className="badge stage">{c.stage}</span>}
                    {c.assigned_to && <span className="badge assignee">👤 {mateName(c.assigned_to)}</span>}
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
            <p className="hint">Hội thoại từ mọi kênh (Zalo · Zalo OA · Mess+IG · Telegram · TikTok · Shopee) gộp về đây.</p>
          </div>
        ) : (
          <>
            <div className="inbox-chat-top">
              <Avatar c={detail} ch={detail._ch} color={CH[detail._ch].color} />
              <div className="inbox-chat-who">
                <strong>{displayName(detail)}</strong>
                <div className="inbox-chat-sub">
                  <span className="ch-chip" style={{ "--c": CH[detail._ch].color }}>
                    <ChannelTile ch={detail._ch} size={13} /> {CH[detail._ch].label}
                  </span>
                  <span className="inbox-app">{appMap[detail._ch] || CH[detail._ch].label}</span>
                  <span className="inbox-shop">🏬 {shopName}</span>
                </div>
              </div>
              <div className="inbox-chat-actions">
                {detail.owner_active
                  ? <span className="badge owner">⛔ Chủ đang xử lý</span>
                  : <span className="badge bot">🤖 Bot đang trả lời</span>}
                {mates.length > 1 && (
                  <select className="inbox-assign-sel" title="Phân công hội thoại cho nhân viên"
                          value={detail.assigned_to || ""}
                          onChange={async (e) => {
                            const r = await assignConv(sel.ch, detail.user_id, e.target.value);
                            if (r.ok) { openChat(sel.ch, detail.user_id); loadAll(); }
                          }}>
                    <option value="">— Chưa phân công —</option>
                    {mates.map((m) => (
                      <option key={m.username} value={m.username}>
                        👤 {m.name || m.username}{m.role === "owner" ? " (chủ)" : ""}
                      </option>
                    ))}
                  </select>
                )}
                <button className="btn-mini" onClick={onToggle}>
                  {detail.owner_active ? "▶ Bật bot" : "⏸ Tắt bot"}
                </button>
                {user?.role !== "staff" && (
                  <button className="btn-mini danger" onClick={onReset}>Xoá</button>
                )}
              </div>
            </div>
            <div className="bubbles inbox-bubbles">
              {(detail.messages || []).length === 0 && <p className="hint">Chưa có tin nhắn.</p>}
              {(detail.messages || []).map((m, i) => (
                <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>{m.content}</div>
              ))}
            </div>
            {orderMsg && <div className="savemsg" style={{ margin: "0 16px 6px" }}>{orderMsg}</div>}
            <ChatSend
              onSend={async (text) => {
                const r = await API[sel.ch].send(detail.user_id, text);
                if (r.ok) { openChat(sel.ch, detail.user_id); loadAll(); }
                return r.ok;
              }}
              onSendMedia={async (file, caption) => {
                const r = await sendMedia(sel.ch, detail.user_id, file, caption);
                if (r.ok && r.body?.ok) { openChat(sel.ch, detail.user_id); loadAll(); return true; }
                return false;
              }}
              onAction={async (key) => {
                if (key !== "make_order") return false;
                setOrderMsg("");
                const r = await makeOrder(sel.ch, detail.user_id);
                if (r.ok && r.body?.ok) {
                  setOrderMsg(`✅ Đã tạo đơn nháp ${r.body.order.code} — mở mục Đơn hàng để duyệt.`);
                  return true;
                }
                setOrderMsg("❌ " + (r.body?.error || "Không tạo được đơn"));
                return false;
              }}
              canned={canned}
            />
          </>
        )}
      </div>
    </div>
  );
}
