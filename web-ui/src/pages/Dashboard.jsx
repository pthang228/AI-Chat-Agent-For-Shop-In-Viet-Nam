import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { currentUser, logout } from "../auth.js";
import { getApps, addApp, removeApp } from "../store.js";
import { brain } from "../brainApi.js";

const CHANNELS = {
  zalo: { label: "Zalo", icon: "💬", color: "#0068ff", connectUrl: "http://localhost:4000" },
  instagram: { label: "Instagram", icon: "📸", color: "#c13584", connectUrl: null },
  messenger: { label: "Messenger", icon: "✉️", color: "#0084ff", connectUrl: null },
};

export default function Dashboard() {
  const nav = useNavigate();
  const user = currentUser();
  const [apps, setApps] = useState(() => getApps(user.username));
  const [showAdd, setShowAdd] = useState(false);

  function refresh() { setApps(getApps(user.username)); }

  function doLogout() { logout(); nav("/login"); }

  function handleAdd({ name, channel }) {
    addApp(user.username, { name, channel });
    setShowAdd(false);
    refresh();
  }

  function handleRemove(id) {
    if (!confirm("Xoá app này?")) return;
    removeApp(user.username, id);
    refresh();
  }

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">🏠 Homestay Bot</div>
        <div className="user">
          <span>{user.homestay || user.username}</span>
          <button className="btn-ghost" onClick={doLogout}>Đăng xuất</button>
        </div>
      </header>

      <main className="content">
        <div className="content-head">
          <h2>Các app của bạn</h2>
          <button className="btn-primary sm" onClick={() => setShowAdd(true)}>+ Thêm app</button>
        </div>

        {apps.length === 0 ? (
          <div className="empty">
            <p>Chưa có app nào.</p>
            <button className="btn-primary" onClick={() => setShowAdd(true)}>+ Thêm app đầu tiên</button>
          </div>
        ) : (
          <div className="grid">
            {apps.map((app) => {
              const ch = CHANNELS[app.channel] || CHANNELS.zalo;
              return (
                <div
                  className="app-card clickable"
                  key={app.id}
                  onClick={() => nav(`/app/${app.id}`)}
                  title="Bấm để xem chi tiết"
                >
                  <div className="app-icon" style={{ background: ch.color }}>{ch.icon}</div>
                  <div className="app-body">
                    <div className="app-name">{app.name}</div>
                    <div className="app-ch">{ch.label}</div>
                  </div>
                  <div className="app-actions" onClick={(e) => e.stopPropagation()}>
                    <BotToggle appName={app.name} channel={app.channel} />
                    <button className="btn-mini danger" onClick={() => handleRemove(app.id)}>Xoá</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} />}
    </div>
  );
}

function BotToggle({ appName, channel }) {
  // null = đang tải, "off" = không gọi được não bộ (cổng 5005)
  const [enabled, setEnabled] = useState(null);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    if (channel !== "zalo") return;
    let alive = true;
    brain.botStatus().then((r) => {
      if (!alive) return;
      if (r.ok && r.body) setEnabled(!!r.body.enabled);
      else setOffline(true);
    });
    return () => { alive = false; };
  }, [channel]);

  async function toggle(e) {
    e.stopPropagation();
    if (busy || enabled === null) return;
    const next = !enabled;
    setBusy(true);
    const r = await brain.botToggle(next, appName);
    setBusy(false);
    if (r.ok && r.body) { setEnabled(!!r.body.enabled); setOffline(false); }
    else setOffline(true);
  }

  if (channel !== "zalo") return null;
  if (offline)
    return <span className="bot-toggle offline" title="Chưa kết nối não bộ (cổng 5005)">Bot: offline</span>;
  if (enabled === null)
    return <span className="bot-toggle loading">Bot: …</span>;

  return (
    <button
      className={"bot-toggle " + (enabled ? "on" : "off")}
      onClick={toggle}
      disabled={busy}
      title={enabled ? "Bot đang BẬT — bấm để tắt" : "Bot đang TẮT — bấm để bật"}
    >
      <span className="dot" />{enabled ? "Bot: BẬT" : "Bot: TẮT"}
    </button>
  );
}

function AddAppModal({ onClose, onAdd }) {
  const [name, setName] = useState("");
  const [channel, setChannel] = useState("zalo");

  function submit(e) {
    e.preventDefault();
    onAdd({ name, channel });
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Thêm app mới</h3>

        <label>Tên app</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="vd: Haru Zalo" autoFocus />

        <label>Kênh</label>
        <div className="ch-pick">
          {Object.entries(CHANNELS).map(([key, c]) => (
            <button
              type="button"
              key={key}
              className={"ch-opt" + (channel === key ? " active" : "")}
              onClick={() => setChannel(key)}
            >
              <span style={{ fontSize: 20 }}>{c.icon}</span> {c.label}
            </button>
          ))}
        </div>

        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Huỷ</button>
          <button type="submit" className="btn-primary sm">Thêm</button>
        </div>
      </form>
    </div>
  );
}
