import { useState, useEffect } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { getApps } from "../store.js";
import { brain } from "../brainApi.js";
import ZaloConnect from "../components/ZaloConnect.jsx";
import MetaConnect from "../components/MetaConnect.jsx";
import MetaConversations from "../components/MetaConversations.jsx";
import Conversations from "../components/Conversations.jsx";
import TelegramConnect from "../components/TelegramConnect.jsx";
import TelegramConversations from "../components/TelegramConversations.jsx";
import TikTokConnect from "../components/TikTokConnect.jsx";
import TikTokConversations from "../components/TikTokConversations.jsx";
import ShopeeConnect from "../components/ShopeeConnect.jsx";
import ShopeeConversations from "../components/ShopeeConversations.jsx";
import { IcHome, IcBack, IcLogout, IcSpark } from "../components/icons.jsx";
import StatsPanel from "../components/StatsPanel.jsx";
import BackLink from "../components/BackLink.jsx";

const CH_LABEL = { zalo: "Zalo", meta: "Mess + Instagram", messenger: "Mess + Instagram", instagram: "Mess + Instagram", telegram: "Telegram", tiktok: "TikTok", shopee: "Shopee" };
const CH_CHIP = { zalo: "zalo", meta: "meta", messenger: "meta", instagram: "meta", telegram: "telegram", tiktok: "tiktok", shopee: "shopee" };
const isMeta = (ch) => ch === "meta" || ch === "messenger" || ch === "instagram";
const botKey = (ch) => (ch === "messenger" || ch === "instagram") ? "meta" : ch;

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function AppDetail() {
  const { id } = useParams();
  const nav = useNavigate();
  const [tab, setTab] = useState("connect");
  const user = currentUser();
  const [app, setApp] = useState(undefined);   // undefined=đang tải | null=không thấy | object
  const hostName = user?.homestay || user?.username || "";

  useEffect(() => {
    getApps().then((r) => {
      if (Array.isArray(r)) setApp(r.find((a) => a.id === id) || null);
      else setApp(null);   // offline/unauth → coi như không thấy, có link về danh sách
    });
  }, [id]);

  if (app === undefined) {
    return (
      <div className="dash">
        <header className="topbar"><div className="brand"><span className="brand-mini"><IcHome width={20} height={20} /></span> NovaChat</div></header>
        <main className="content"><p>Đang tải…</p></main>
      </div>
    );
  }
  if (!app) {
    return (
      <div className="dash">
        <header className="topbar"><div className="brand"><span className="brand-mini"><IcHome width={20} height={20} /></span> NovaChat</div></header>
        <main className="content"><p>Không tìm thấy app (hoặc máy chủ 5005 chưa chạy). <Link to="/">← Về danh sách</Link></p></main>
      </div>
    );
  }

  const Connect = app.channel === "zalo" ? ZaloConnect
    : isMeta(app.channel) ? MetaConnect
    : app.channel === "tiktok" ? TikTokConnect
    : app.channel === "shopee" ? ShopeeConnect
    : TelegramConnect;
  const Chats = app.channel === "zalo" ? Conversations
    : isMeta(app.channel) ? MetaConversations
    : app.channel === "tiktok" ? TikTokConversations
    : app.channel === "shopee" ? ShopeeConversations
    : TelegramConversations;
  const statsChannel = app.channel === "zalo" ? "zalo"
    : isMeta(app.channel) ? "meta"
    : app.channel === "tiktok" ? "tiktok"
    : app.channel === "shopee" ? "shopee"
    : "telegram";

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <span className="brand-mini" style={{ marginLeft: -4 }}><IcHome width={18} height={18} /></span> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản"><span className="avatar">{initials(hostName)}</span>{hostName}</Link>
          <button className="btn-ghost" onClick={async () => { if (confirm("Đăng xuất sẽ TẮT bot trên mọi kênh. Tiếp tục?")) { await logoutAndStopBots(); nav("/login"); } }}><IcLogout width={15} height={15} /> Đăng xuất</button>
        </div>
      </header>

      <main className="content narrow">
        <BackLink to="/?s=chatbot" label="Về danh sách app" />
        <div className="detail-bar">
          <div className="detail-titles">
            <h2 className="detail-title">{app.name}</h2>
            <span className={"chip " + (CH_CHIP[app.channel] || "")}>{CH_LABEL[app.channel] || app.channel}</span>
          </div>
          <AiCard channel={app.channel} />
        </div>

        <div className="tabs">
          <button className={"tab" + (tab === "connect" ? " active" : "")} onClick={() => setTab("connect")}>Kết nối</button>
          <button className={"tab" + (tab === "chats" ? " active" : "")} onClick={() => setTab("chats")}>Khách hàng</button>
          <button className={"tab" + (tab === "stats" ? " active" : "")} onClick={() => setTab("stats")}>Thống kê</button>
        </div>

        <div className="card-box">
          {tab === "connect" && <Connect />}
          {tab === "chats" && <Chats />}
          {tab === "stats" && <StatsPanel channel={statsChannel} />}
        </div>
      </main>
    </div>
  );
}

function AiCard({ channel }) {
  const key = botKey(channel);
  const [enabled, setEnabled] = useState(null);   // null | bool | "offline"

  useEffect(() => {
    brain.botStatus(key).then((r) => setEnabled(r.ok && r.body ? !!r.body.enabled : "offline"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  async function toggle() {
    if (enabled === "offline" || enabled === null) return;
    const next = !enabled; setEnabled(next);
    const r = await brain.botToggle(next, key);
    setEnabled(r.ok && r.body ? !!r.body.enabled : "offline");
  }

  const label = enabled === "offline" ? "Offline" : enabled === null ? "…" : enabled ? "BẬT" : "TẮT";
  return (
    <div className="ai-card">
      <IcSpark width={17} height={17} style={{ color: "var(--gold)" }} /> Trợ lý AI
      <button className={"tggl" + (enabled === true ? " on" : "")} disabled={enabled === "offline" || enabled === null} onClick={toggle} />
      <span className={"state" + (enabled === true ? "" : " off")}>{label}</span>
    </div>
  );
}
