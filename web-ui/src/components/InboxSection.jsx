import { useEffect, useMemo, useRef, useState } from "react";
import { currentUser } from "../auth.js";
import { teamApi } from "../teamApi.js";
import { getApps } from "../store.js";
import { CH_HOST } from "../apiConfig.js";
import { brain } from "../brainApi.js";
import { meta } from "../metaApi.js";
import { tg } from "../telegramApi.js";
import { shopee } from "../shopeeApi.js";
import { zalooa } from "../zaloOaApi.js";
import { webchat } from "../webchatApi.js";
import ChatSend from "./ChatSend.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";
import { sendMedia, makeOrder, assignConv, saveStyle, canned as cannedApi } from "../chatToolsApi.js";
import { useI18n } from "../i18n.jsx";

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
  shopee:   { label: "Shopee",    color: "#EE4D2D" },
  zalooa:   { label: "Zalo OA",   color: "#005AE0" },
  webchat:  { label: "Website",   color: "#4F46E5" },
};

// Bộ chuyển API theo kênh — che khác biệt tên hàm (brain.reset vs .resetConv…)
const API = {
  zalo:     { list: () => brain.conversations(),  detail: (u) => brain.conversation(u), send: (u, t) => brain.sendMessage(u, t), toggle: (u, on) => brain.toggleBot(u, on),  reset: (u) => brain.reset(u) },
  meta:     { list: () => meta.conversations(),   detail: (u) => meta.conversation(u),  send: (u, t) => meta.sendMessage(u, t),  toggle: (u, on) => meta.toggleBot(u, on),   reset: (u) => meta.resetConv(u) },
  telegram: { list: () => tg.conversations(),     detail: (u) => tg.conversation(u),    send: (u, t) => tg.sendMessage(u, t),    toggle: (u, on) => tg.toggleBot(u, on),     reset: (u) => tg.resetConv(u) },
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
  const { t } = useI18n();
  const src = avatarSrc(c, ch);
  return (
    <div className="inbox-av" style={{ background: color }}>
      {initials(displayName(c, t))}
      {src && <img src={src} alt="" loading="lazy"
                   onError={(e) => { e.currentTarget.style.display = "none"; }} />}
    </div>
  );
}

function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }
function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }
function displayName(c, t) {
  return c.name ? c.name : t("inbox.guest", { id: String(c.user_id || "").slice(-6) });
}
function relTime(iso, t) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return t("inbox.time.now");
  if (diff < 3600) return t("inbox.time.min", { n: Math.floor(diff / 60) });
  if (diff < 86400) return t("inbox.time.hr", { n: Math.floor(diff / 3600) });
  return t("inbox.time.day", { n: Math.floor(diff / 86400) });
}

export default function InboxSection() {
  const { t } = useI18n();
  const user = currentUser();
  const shopName = user?.homestay || user?.username || t("inbox.my_shop");

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
  const [styleBusy, setStyleBusy] = useState(false);
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
    if (!sel || !confirm(t("inbox.reset_confirm"))) return;
    await API[sel.ch].reset(sel.user_id);
    setSel(null); setDetail(null); loadAll();
  }

  const counts = useMemo(() => {
    const c = { all: 0, zalo: 0, meta: 0, telegram: 0, shopee: 0, zalooa: 0, webchat: 0 };
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
      (displayName(c, t).toLowerCase().includes(s)) || (c.last_msg || "").toLowerCase().includes(s));
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [convs, filter, assignFilter, q, user?.username]);

  const TABS = [["all", t("inbox.all")], ...Object.entries(CH).map(([k, v]) => [k, v.label])];

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
        <input className="inbox-search" placeholder={t("inbox.search_ph")}
               value={q} onChange={(e) => setQ(e.target.value)} />
        {mates.length > 1 && (
          <div className="inbox-assign-bar">
            {[["all", t("inbox.all")], ["mine", t("inbox.mine")], ["none", t("inbox.unassigned")]].map(([k, label]) => (
              <button key={k}
                      className={"inbox-tab" + (assignFilter === k ? " active" : "")}
                      onClick={() => setAssignFilter(k)}>{label}</button>
            ))}
          </div>
        )}

        <div className="inbox-rows">
          {convs === null && <p className="hint inbox-empty">{t("inbox.loading")}</p>}
          {convs && shown.length === 0 && (
            <div className="inbox-empty">
              <div style={{ fontSize: 34 }}>💬</div>
              <p className="hint">{filter !== "all" ? t("inbox.empty_ch", { ch: CH[filter].label }) : t("inbox.empty")}</p>
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
                    <strong>{displayName(c, t)}</strong>
                    <span className="inbox-time">{relTime(c.last_updated, t)}</span>
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
                      ? <span className="badge owner">{t("inbox.badge_owner")}</span>
                      : <span className="badge bot">{t("inbox.badge_bot")}</span>}
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
            <h3>{t("inbox.pick_title")}</h3>
            <p className="hint">{t("inbox.pick_desc")}</p>
          </div>
        ) : (
          <>
            <div className="inbox-chat-top">
              <Avatar c={detail} ch={detail._ch} color={CH[detail._ch].color} />
              <div className="inbox-chat-who">
                <strong>{displayName(detail, t)}</strong>
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
                  ? <span className="badge owner">{t("inbox.owner_handling")}</span>
                  : <span className="badge bot">{t("inbox.bot_replying")}</span>}
                {mates.length > 1 && (
                  <select className="inbox-assign-sel" title={t("inbox.assign_title")}
                          value={detail.assigned_to || ""}
                          onChange={async (e) => {
                            const r = await assignConv(sel.ch, detail.user_id, e.target.value);
                            if (r.ok) { openChat(sel.ch, detail.user_id); loadAll(); }
                          }}>
                    <option value="">{t("inbox.unassigned_opt")}</option>
                    {mates.map((m) => (
                      <option key={m.username} value={m.username}>
                        👤 {m.name || m.username}{m.role === "owner" ? t("inbox.owner_suffix") : ""}
                      </option>
                    ))}
                  </select>
                )}
                <button className="btn-mini" onClick={onToggle}>
                  {detail.owner_active ? t("inbox.bot_on") : t("inbox.bot_off")}
                </button>
                {user?.role !== "staff" && (
                  <button className="btn-mini" disabled={styleBusy}
                          title={t("inbox.style_hint")}
                          onClick={async () => {
                            setOrderMsg(""); setStyleBusy(true);
                            const r = await saveStyle(sel.ch, detail.user_id);
                            setStyleBusy(false);
                            if (r.ok && r.body?.ok) {
                              setOrderMsg(t("inbox.style_ok", { title: r.body.chunk?.title || "" }));
                            } else {
                              setOrderMsg("❌ " + (r.body?.error || t("inbox.style_fail")));
                            }
                          }}>
                    {styleBusy ? t("inbox.style_busy") : t("inbox.style_btn")}
                  </button>
                )}
                {user?.role !== "staff" && (
                  <button className="btn-mini danger" onClick={onReset}>{t("team.del")}</button>
                )}
              </div>
            </div>
            <div className="bubbles inbox-bubbles">
              {(detail.messages || []).length === 0 && <p className="hint">{t("inbox.no_msgs")}</p>}
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
                  setOrderMsg(t("inbox.order_ok", { code: r.body.order.code }));
                  return true;
                }
                setOrderMsg("❌ " + (r.body?.error || t("inbox.order_fail")));
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
