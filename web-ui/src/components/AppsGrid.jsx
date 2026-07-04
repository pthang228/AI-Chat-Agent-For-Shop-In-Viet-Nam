import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { logout } from "../auth.js";
import { getApps, addApp, removeApp } from "../store.js";
import { brain } from "../brainApi.js";
import { IcPlus, IcSpark, IcChev } from "./icons.jsx";

export const CHANNELS = {
  zalo:      { label: "Zalo",            icon: "💬", color: "#0068ff" },
  meta:      { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  telegram:  { label: "Telegram",        icon: "✈️", color: "#229ED9" },
  tiktok:    { label: "TikTok",          icon: "🎵", color: "#161823" },
  shopee:    { label: "Shopee",          icon: "🛒", color: "#EE4D2D" },
  messenger: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  instagram: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
};
const ADD_CHANNELS = ["zalo", "meta", "telegram", "tiktok", "shopee"];

export function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }

// Kênh (app) thuộc shop nào — backend single-tenant chưa có shop_id nên map tạm
// ở localStorage. Khi có API theo shop_id thì bỏ lớp này, lọc thẳng từ server.
const APP_SHOP_KEY = "hb_app_shop";
function loadAppShop() {
  try { return JSON.parse(localStorage.getItem(APP_SHOP_KEY)) || {}; }
  catch { return {}; }
}
function saveAppShop(m) { localStorage.setItem(APP_SHOP_KEY, JSON.stringify(m)); }

/*
 * Lưới quản lý kênh (apps) của MỘT shop. Lọc theo shopId; app chưa gắn shop →
 * gán vào shop mặc định (shop đầu tiên). onStats báo tổng/đang-bật ra ngoài.
 */
export default function AppsGrid({ onStats, shopId = null, isDefaultShop = false }) {
  const nav = useNavigate();
  const [apps, setApps] = useState(null);      // null=đang tải | mảng | "offline"  (TẤT CẢ app của user)
  const [showAdd, setShowAdd] = useState(false);
  const [botMap, setBotMap] = useState({});

  const allApps = Array.isArray(apps) ? apps : [];
  // Chỉ hiện app của shop này. Không truyền shopId (tương thích cũ) → hiện tất cả.
  const appList = shopId
    ? allApps.filter((a) => loadAppShop()[a.id] === shopId)
    : allApps;
  const channels = [...new Set(appList.map((a) => botKey(a.channel)))];

  async function refresh() {
    const r = await getApps();
    if (r === "unauth") { logout(); nav("/login"); return; }
    // Shop mặc định "nhận" mọi app chưa gắn shop nào (app cũ tạo trước khi có shop)
    if (Array.isArray(r) && shopId && isDefaultShop) {
      const m = loadAppShop();
      let changed = false;
      for (const a of r) if (!m[a.id]) { m[a.id] = shopId; changed = true; }
      if (changed) saveAppShop(m);
    }
    setApps(r);
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [shopId]);

  useEffect(() => {
    channels.forEach((c) => {
      brain.botStatus(c).then((r) => {
        setBotMap((m) => ({ ...m, [c]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appList.length]);

  useEffect(() => {
    if (!onStats) return;
    const on = appList.filter((a) => botMap[botKey(a.channel)] === true).length;
    const loaded = channels.some((c) => typeof botMap[c] === "boolean");
    onStats({ total: appList.length, on: loaded ? on : null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appList.length, botMap]);

  async function handleAdd({ name, channel }) {
    try {
      const app = await addApp({ name, channel });
      if (app?.id && shopId) { const m = loadAppShop(); m[app.id] = shopId; saveAppShop(m); }
    } catch (e) { alert("❌ " + e.message); }
    setShowAdd(false); refresh();
  }
  async function handleRemove(id) {
    if (!confirm("Xoá app này?")) return;
    try { await removeApp(id); } catch (e) { alert("❌ " + e.message); }
    const m = loadAppShop(); if (m[id]) { delete m[id]; saveAppShop(m); }
    refresh();
  }
  async function toggleBot(channel) {
    const cur = botMap[channel];
    if (cur === "offline" || cur === undefined) return;
    const next = !cur;
    setBotMap((m) => ({ ...m, [channel]: next }));
    const r = await brain.botToggle(next, channel);
    setBotMap((m) => ({ ...m, [channel]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
  }

  if (apps === null) return <div className="empty"><p>Đang tải danh sách app…</p></div>;
  if (apps === "offline") return (
    <div className="empty">
      <p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p>
      <p className="hint">Chạy <code>start-all.bat</code> rồi bấm Thử lại.</p>
      <button className="btn-primary sm" onClick={refresh} style={{ margin: "0 auto" }}>Thử lại</button>
    </div>
  );
  if (appList.length === 0) return (
    <div className="empty">
      <p>Chưa có app nào. Thêm kênh đầu tiên để bắt đầu.</p>
      <button className="btn-primary sm" onClick={() => setShowAdd(true)} style={{ margin: "0 auto" }}>
        <IcPlus width={16} height={16} /> Thêm app
      </button>
      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} />}
    </div>
  );

  return (
    <>
      <div className="grid">
        {appList.map((app) => {
          const ch = CHANNELS[app.channel] || CHANNELS.zalo;
          const key = botKey(app.channel);
          const st = botMap[key];
          const on = st === true;
          const reachable = st !== undefined && st !== "offline";
          return (
            <div className="app-card clickable" key={app.id} onClick={() => nav(`/app/${app.id}`)}>
              <div className="app-top">
                <div className="app-icon" style={{ background: ch.color }}>{ch.icon}</div>
                <div className="app-titles">
                  <div className="app-name">{app.name}</div>
                  <div className="app-ch">{ch.label}</div>
                </div>
                <div className={"app-status" + (reachable ? " on" : "")}>
                  <span className="dot" />{reachable ? "Đã kết nối" : "Chưa kết nối"}
                </div>
              </div>
              <div className="ai-row" onClick={(e) => e.stopPropagation()}>
                <div className="ai-left">
                  <span className="spark"><IcSpark width={17} height={17} /></span> Trợ lý AI
                  <span className={"badge " + (on ? "bot" : "stage")}>
                    {st === "offline" ? "Offline" : st === undefined ? "…" : on ? "Đang bật" : "Đang tắt"}
                  </span>
                </div>
                <button className={"tggl" + (on ? " on" : "")}
                        disabled={st === "offline" || st === undefined}
                        onClick={() => toggleBot(key)}
                        title="Bật/tắt trợ lý AI cho kênh này" />
              </div>
              <div className="app-foot">
                <span>Quản lý & khách hàng</span>
                <span className="chev"><IcChev width={16} height={16} /></span>
              </div>
              <button className="btn-mini danger del"
                      onClick={(e) => { e.stopPropagation(); handleRemove(app.id); }}>
                Xoá
              </button>
            </div>
          );
        })}
        <div className="add-card" onClick={() => setShowAdd(true)}>
          <span className="add-plus"><IcPlus width={24} height={24} /></span>
          <h3>Thêm app</h3>
          <span className="hint">Kết nối kênh chat mới</span>
        </div>
      </div>
      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} />}
    </>
  );
}

function AddAppModal({ onClose, onAdd }) {
  const [name, setName] = useState("");
  const [channel, setChannel] = useState("zalo");
  function submit(e) { e.preventDefault(); onAdd({ name, channel }); }
  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Thêm app mới</h3>
        <label>Tên app</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Haru Zalo" autoFocus />
        <label>Kênh</label>
        <div className="ch-pick">
          {ADD_CHANNELS.map((key) => {
            const c = CHANNELS[key];
            return (
              <button type="button" key={key}
                      className={"ch-opt" + (channel === key ? " active" : "")}
                      onClick={() => setChannel(key)}>
                <span style={{ fontSize: 22 }}>{c.icon}</span> {c.label}
              </button>
            );
          })}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Huỷ</button>
          <button type="submit" className="btn-primary sm">Thêm</button>
        </div>
      </form>
    </div>
  );
}
