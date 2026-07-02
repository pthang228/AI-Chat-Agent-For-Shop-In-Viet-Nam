import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { currentUser, logout } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { getApps, addApp, removeApp } from "../store.js";
import { brain } from "../brainApi.js";
import { billing as billingApi } from "../billingApi.js";
import { IcHome, IcLogout, IcPlus, IcSpark, IcChev } from "../components/icons.jsx";
import StatsPanel from "../components/StatsPanel.jsx";

const CHANNELS = {
  zalo:      { label: "Zalo",           icon: "💬", color: "#0068ff" },
  meta:      { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  telegram:  { label: "Telegram",        icon: "✈️", color: "#229ED9" },
  tiktok:    { label: "TikTok",          icon: "🎵", color: "#161823" },
  messenger: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  instagram: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
};
const ADD_CHANNELS = ["zalo", "meta", "telegram", "tiktok"];

function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }
function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

// Icon SVG thống kê
function IcChart() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4"  />
      <line x1="6"  y1="20" x2="6"  y2="14" />
    </svg>
  );
}

export default function Dashboard() {
  const nav = useNavigate();
  const user = currentUser();
  const [apps, setApps] = useState(null);        // null=đang tải | mảng | "offline"
  const [showAdd, setShowAdd] = useState(false);
  const [showStats, setShowStats] = useState(false);
  const [botMap, setBotMap] = useState({});
  const [bill, setBill] = useState(null);        // trạng thái gói dịch vụ

  useEffect(() => {
    billingApi.me().then((r) => { if (r.ok && r.body) setBill(r.body); });
  }, []);

  const appList = Array.isArray(apps) ? apps : [];
  const channels = [...new Set(appList.map((a) => botKey(a.channel)))];

  async function refresh() {
    const r = await getApps();
    if (r === "unauth") { logout(); nav("/login"); return; }   // phiên hết hạn
    setApps(r);
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  useEffect(() => {
    channels.forEach((c) => {
      brain.botStatus(c).then((r) => {
        setBotMap((m) => ({ ...m, [c]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appList.length]);

  async function doLogout() {
    if (!confirm("Đăng xuất sẽ TẮT bot (ngừng tự trả lời khách) trên mọi kênh. Tiếp tục?")) return;
    await logoutAndStopBots();
    nav("/login");
  }
  async function handleAdd({ name, channel }) {
    try { await addApp({ name, channel }); } catch (e) { alert("❌ " + e.message); }
    setShowAdd(false); refresh();
  }
  async function handleRemove(id) {
    if (!confirm("Xoá app này?")) return;
    try { await removeApp(id); } catch (e) { alert("❌ " + e.message); }
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

  const onCount = appList.filter((a) => botMap[botKey(a.channel)] === true).length;
  const statLoaded = channels.some((c) => typeof botMap[c] === "boolean");
  const hostName = user?.homestay || user?.username || "";

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand"><span className="brand-mini"><IcHome width={20} height={20} /></span> Homestay Bot</div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản">
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
          <button className="btn-ghost" onClick={doLogout}><IcLogout width={15} height={15} /> Đăng xuất</button>
        </div>
      </header>

      <main className="content">
        {/* Banner gói dịch vụ */}
        {bill && !bill.lifetime && (
          <Link to="/billing" className={"bill-banner" + (bill.active ? (bill.on_trial ? " trial" : "") : " expired")}>
            {bill.active
              ? bill.on_trial
                ? <>🎁 Đang dùng thử — còn <b>{bill.days_left}</b> ngày. <u>Xem gói dịch vụ →</u></>
                : <>📦 {bill.plan_label} — còn <b>{bill.days_left}</b> ngày. <u>Gia hạn →</u></>
              : <>⛔ <b>Gói dịch vụ đã hết hạn</b> — bot đã tạm ngừng trả lời khách. <u>Gia hạn ngay →</u></>}
          </Link>
        )}

        {/* Heading + stat chips + stats icon button */}
        <div className="dash-head">
          <div>
            <div className="hello">Xin chào, {hostName}</div>
            <h1 className="page-title">Các app của bạn</h1>
            <p className="page-sub">Mỗi app là một kênh chat được kết nối. Bật trợ lý AI để tự động trả lời khách.</p>
          </div>
          <div className="dash-head-right">
            <div className="stats">
              <div className="stat-card">
                <div className="stat-num">{apps === null ? "…" : appList.length}</div>
                <div className="stat-label">Kênh kết nối</div>
              </div>
              <div className="stat-card">
                <div className="stat-num">{statLoaded ? onCount : "—"}</div>
                <div className="stat-label">Trợ lý đang bật</div>
              </div>
            </div>
            {appList.length > 0 && (
              <button
                className={"stats-icon-btn" + (showStats ? " active" : "")}
                onClick={() => setShowStats((v) => !v)}
                title={showStats ? "Ẩn thống kê" : "Xem thống kê"}>
                <IcChart />
                <span>Thống kê</span>
              </button>
            )}
          </div>
        </div>

        {/* Split layout: apps | stats panel */}
        <div className={"dash-body" + (showStats ? " with-stats" : "")}>
          {/* Apps col */}
          <div className="dash-apps-col">
            {apps === null ? (
              <div className="empty"><p>Đang tải danh sách app…</p></div>
            ) : apps === "offline" ? (
              <div className="empty">
                <p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p>
                <p className="hint">Chạy <code>start-all.bat</code> (hoặc <code>python -m app.main_node</code>) rồi bấm Thử lại.</p>
                <button className="btn-primary sm" onClick={refresh} style={{ margin: "0 auto" }}>Thử lại</button>
              </div>
            ) : appList.length === 0 ? (
              <div className="empty">
                <p>Chưa có app nào. Thêm kênh đầu tiên để bắt đầu.</p>
                <button className="btn-primary sm" onClick={() => setShowAdd(true)}
                        style={{ margin: "0 auto" }}>
                  <IcPlus width={16} height={16} /> Thêm app
                </button>
              </div>
            ) : (
              <div className="grid">
                {appList.map((app) => {
                  const ch = CHANNELS[app.channel] || CHANNELS.zalo;
                  const key = botKey(app.channel);
                  const st = botMap[key];
                  const on = st === true;
                  const reachable = st !== undefined && st !== "offline";
                  return (
                    <div className="app-card clickable" key={app.id}
                         onClick={() => nav(`/app/${app.id}`)}>
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
                        <button
                          className={"tggl" + (on ? " on" : "")}
                          disabled={st === "offline" || st === undefined}
                          onClick={() => toggleBot(key)}
                          title="Bật/tắt trợ lý AI cho kênh này"
                        />
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
            )}
          </div>

          {/* Stats panel — slide in from right */}
          {showStats && (
            <aside className="dash-stats-aside">
              <StatsPanel channel="all" onClose={() => setShowStats(false)} />
            </aside>
          )}
        </div>
      </main>

      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} />}
    </div>
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
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="VD: Haru Zalo" autoFocus />
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
