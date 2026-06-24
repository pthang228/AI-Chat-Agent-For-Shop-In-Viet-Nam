import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { currentUser } from "../auth.js";
import { getApps } from "../store.js";
import ZaloConnect from "../components/ZaloConnect.jsx";
import MetaConnect from "../components/MetaConnect.jsx";
import Conversations from "../components/Conversations.jsx";

const CH_LABEL = { zalo: "Zalo", instagram: "Instagram", messenger: "Messenger" };

export default function AppDetail() {
  const { id } = useParams();
  const [tab, setTab] = useState("connect");
  const user = currentUser();
  const app = getApps(user.username).find((a) => a.id === id);

  if (!app) {
    return (
      <div className="dash">
        <header className="topbar">
          <div className="brand">🏠 Homestay Bot</div>
        </header>
        <main className="content">
          <p>Không tìm thấy app. <Link to="/">← Về danh sách</Link></p>
        </main>
      </div>
    );
  }

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand"><Link to="/" style={{ textDecoration: "none" }}>← Homestay Bot</Link></div>
        <div className="user"><span>{user.homestay || user.username}</span></div>
      </header>

      <main className="content narrow">
        <div className="detail-head">
          <h2>{app.name}</h2>
          <span className="chip">{CH_LABEL[app.channel] || app.channel}</span>
        </div>

        {app.channel === "zalo" ? (
          <>
            <div className="tabs">
              <button className={"tab" + (tab === "connect" ? " active" : "")} onClick={() => setTab("connect")}>Kết nối</button>
              <button className={"tab" + (tab === "chats" ? " active" : "")} onClick={() => setTab("chats")}>Khách hàng</button>
            </div>
            <div className="card-box">
              {tab === "connect" ? <ZaloConnect /> : <Conversations />}
            </div>
          </>
        ) : (app.channel === "messenger" || app.channel === "instagram") ? (
          <>
            <div className="tabs">
              <button className={"tab" + (tab === "connect" ? " active" : "")} onClick={() => setTab("connect")}>Kết nối</button>
              <button className={"tab" + (tab === "chats" ? " active" : "")} onClick={() => setTab("chats")}>Khách hàng</button>
            </div>
            <div className="card-box">
              {tab === "connect" ? <MetaConnect /> : <Conversations />}
            </div>
          </>
        ) : (
          <div className="card-box">
            <div className="connect">
              <div className="status muted">Kênh {CH_LABEL[app.channel]} sắp có 🚧</div>
              <p className="hint">Hiện Zalo và Facebook/Instagram đã hoạt động.</p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
