import { useState, useEffect } from "react";
import { useNavigate, Link } from "react-router-dom";
import { currentUser } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { getApps, addApp, removeApp } from "../store.js";
import { brain } from "../brainApi.js";
import { IcHome, IcLogout, IcPlus, IcSpark, IcChev } from "../components/icons.jsx";

const CHANNELS = {
  zalo: { label: "Zalo", icon: "💬", color: "#0068ff" },
  meta: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  telegram: { label: "Telegram", icon: "✈️", color: "#229ED9" },
  messenger: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
  instagram: { label: "Mess + Instagram", icon: "✉️", color: "#7b3fb3" },
};
const ADD_CHANNELS = ["zalo", "meta", "telegram"];

// Khoá trạng thái bot theo KÊNH (messenger/instagram đều là 1 backend "meta").
function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function Dashboard() {
  const nav = useNavigate();
  const user = currentUser();
  const [apps, setApps] = useState(() => getApps(user.username));
  const [showAdd, setShowAdd] = useState(false);
  const [botMap, setBotMap] = useState({});   // kênh -> true | false | "offline" | undefined(đang tải)

  const channels = [...new Set(apps.map((a) => botKey(a.channel)))];

  useEffect(() => {
    channels.forEach((c) => {
      brain.botStatus(c).then((r) => {
        setBotMap((m) => ({ ...m, [c]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps.length]);

  function refresh() { setApps(getApps(user.username)); }
  async function doLogout() {
    if (!confirm("Đăng xuất sẽ TẮT bot (ngừng tự trả lời khách) trên mọi kênh. Tiếp tục?")) return;
    await logoutAndStopBots();
    nav("/login");
  }
  function handleAdd({ name, channel }) { addApp(user.username, { name, channel }); setShowAdd(false); refresh(); }
  function handleRemove(id) { if (confirm("Xoá app này?")) { removeApp(user.username, id); refresh(); } }

  async function toggleBot(channel) {
    const cur = botMap[channel];
    if (cur === "offline" || cur === undefined) return;
    const next = !cur;
    setBotMap((m) => ({ ...m, [channel]: next }));
    const r = await brain.botToggle(next, channel);
    setBotMap((m) => ({ ...m, [channel]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
  }

  const onCount = apps.filter((a) => botMap[botKey(a.channel)] === true).length;
  const statLoaded = channels.some((c) => typeof botMap[c] === "boolean");
  const hostName = user.homestay || user.username;

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand"><span className="brand-mini"><IcHome width={20} height={20} /></span> Homestay Bot</div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản"><span className="avatar">{initials(hostName)}</span>{hostName}</Link>
          <button className="btn-ghost" onClick={doLogout}><IcLogout width={15} height={15} /> Đăng xuất</button>
        </div>
      </header>

      <main className="content">
        <div className="dash-head">
          <div>
            <div className="hello">Xin chào, {hostName}</div>
            <h1 className="page-title">Các app của bạn</h1>
            <p className="page-sub">Mỗi app là một kênh chat được kết nối. Bật trợ lý AI để tự động trả lời khách, hoặc mở để xem hội thoại.</p>
          </div>
          <div className="stats">
            <div className="stat-card"><div className="stat-num">{apps.length}</div><div className="stat-label">Kênh kết nối</div></div>
            <div className="stat-card"><div className="stat-num">{statLoaded ? onCount : "—"}</div><div className="stat-label">Trợ lý đang bật</div></div>
          </div>
        </div>

        {apps.length === 0 ? (
          <div className="empty">
            <p>Chưa có app nào. Thêm kênh đầu tiên để bắt đầu.</p>
            <button className="btn-primary sm" onClick={() => setShowAdd(true)} style={{ margin: "0 auto" }}><IcPlus width={16} height={16} /> Thêm app</button>
          </div>
        ) : (
          <div className="grid">
            {apps.map((app) => {
              const ch = CHANNELS[app.channel] || CHANNELS.zalo;
              const key = botKey(app.channel);
              const st = botMap[key];                          // undefined=tải, bool, "offline"
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
                    <button
                      className={"tggl" + (on ? " on" : "")}
                      disabled={st === "offline" || st === undefined}
                      onClick={() => toggleBot(key)}
                      title="Bật/tắt trợ lý AI cho kênh này"
                    />
                  </div>

                  <div className="app-foot">
                    <span>Quản lý & khách hàng</span><span className="chev"><IcChev width={16} height={16} /></span>
                  </div>
                  <button className="btn-mini danger del" onClick={(e) => { e.stopPropagation(); handleRemove(app.id); }}>Xoá</button>
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
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="VD: Haru Zalo" autoFocus />
        <label>Kênh</label>
        <div className="ch-pick">
          {ADD_CHANNELS.map((key) => {
            const c = CHANNELS[key];
            return (
              <button type="button" key={key} className={"ch-opt" + (channel === key ? " active" : "")} onClick={() => setChannel(key)}>
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
