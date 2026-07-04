import { useState, useMemo, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { billing as billingApi } from "../billingApi.js";
import { IcLogout } from "../components/icons.jsx";
import Sidebar from "../components/Sidebar.jsx";
import OverviewCharts from "../components/OverviewCharts.jsx";
import ChatbotSection from "../components/ChatbotSection.jsx";
import InboxSection from "../components/InboxSection.jsx";

const PERIODS = [
  { key: "today", label: "Hôm nay" },
  { key: "7d",    label: "7 ngày"  },
  { key: "30d",   label: "30 ngày" },
  { key: "month", label: "Tháng"   },
  { key: "year",  label: "Năm"     },
];

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

function Kpi({ icon, label, value, accent }) {
  return (
    <div className="kpi" style={{ "--kpi": accent }}>
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        <span className="kpi-ic" style={{ background: accent }}>{icon}</span>
      </div>
      <div className="kpi-val">{value}</div>
    </div>
  );
}

const SECTION_TITLE = {
  overview:  "Tổng quan",
  chat:      "Hội thoại",
  chatbot:   "Chatbot",
  broadcast: "Tin nhắn hàng loạt",
  posts:     "Bài viết & bình luận (Facebook + TikTok)",
  stats:     "Thống kê",
};

export default function Overview() {
  const nav = useNavigate();
  const user = currentUser();
  const hostName = user?.homestay || user?.username || "";
  const [section, setSection] = useState(() => {
    // Cho phép mở thẳng 1 mục qua URL ?s=chatbot (vd nút "Về danh sách app")
    const s = new URLSearchParams(window.location.search).get("s");
    return ["overview", "chat", "chatbot", "broadcast", "posts", "stats"].includes(s) ? s : "overview";
  });
  const [collapsed, setCollapsed] = useState(false);
  const [period, setPeriod] = useState("30d");
  const [stats, setStats] = useState(null);
  const [bill, setBill] = useState(null);

  useEffect(() => {
    billingApi.me().then((r) => { if (r.ok && r.body) setBill(r.body); });
  }, []);

  const kpi = useMemo(() => {
    if (!stats) return { msg: "—", conv: "—", rate: "—" };
    const rate = stats.user_msg > 0
      ? Math.min(100, Math.round((stats.bot_msg / stats.user_msg) * 100)) + "%" : "0%";
    return { msg: stats.total_msg ?? (stats.user_msg + stats.bot_msg), conv: stats.total_conv, rate };
  }, [stats]);

  async function doLogout() {
    if (!confirm("Đăng xuất sẽ TẮT bot (ngừng tự trả lời khách) trên mọi kênh. Tiếp tục?")) return;
    await logoutAndStopBots();
    nav("/login");
  }

  return (
    <div className={"shell" + (collapsed ? " sb-collapsed" : "")}>
      <Sidebar
        active={section}
        onSelect={setSection}
        collapsed={collapsed}
        onToggle={() => setCollapsed((v) => !v)}
      />

      <div className="shell-main">
        <header className="shell-top">
          <h2 className="shell-title">{SECTION_TITLE[section]}</h2>
          <div className="shell-top-right">
            <Link to="/settings" className="user-pill" title="Cài đặt tài khoản">
              <span className="avatar">{initials(hostName)}</span>{hostName}
            </Link>
            <button className="btn-ghost" onClick={doLogout}>
              <IcLogout width={15} height={15} /> Đăng xuất
            </button>
          </div>
        </header>

        <main className="shell-body">
          {section === "overview" ? (
            <>
              {/* Banner gói dịch vụ */}
              {bill && !bill.lifetime && (
                <Link to="/billing" className={"bill-banner" + (bill.active ? (bill.on_trial ? " trial" : "") : " expired")}>
                  {bill.active
                    ? bill.on_trial
                      ? <>🎁 Đang dùng thử — còn <b>{bill.days_left}</b> ngày. <u>Xem gói dịch vụ →</u></>
                      : <>📦 Gói {bill.tier_label} · {bill.plan_label} — còn <b>{bill.days_left}</b> ngày. <u>Gia hạn →</u></>
                    : <>⛔ <b>Gói dịch vụ đã hết hạn</b> — bot đã tạm ngừng trả lời khách. <u>Gia hạn ngay →</u></>}
                </Link>
              )}

              <div className="ov-head">
                <div>
                  <div className="hello">Chào mừng trở lại, {hostName}!</div>
                  <p className="page-sub">Tổng quan hoạt động của shop</p>
                </div>
                <div className="period-bar">
                  {PERIODS.map((p) => (
                    <button key={p.key}
                            className={"period-btn" + (period === p.key ? " active" : "")}
                            onClick={() => setPeriod(p.key)}>
                      {p.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Hàng KPI */}
              <div className="kpi-row">
                <Kpi icon="✉️" label="Tổng tin nhắn"     value={kpi.msg}  accent="#4C6EF5" />
                <Kpi icon="💬" label="Tổng hội thoại"    value={kpi.conv} accent="#7C3AED" />
                <Kpi icon="🤖" label="Tỷ lệ AI trả lời"  value={kpi.rate} accent="#23a065" />
                <Kpi icon="⏱" label="Thời gian phản hồi TB" value="—" accent="#cf9536" />
              </div>

              {/* 4 biểu đồ */}
              <OverviewCharts period={period} onData={setStats} />
            </>
          ) : section === "chat" ? (
            <InboxSection />
          ) : section === "chatbot" ? (
            <ChatbotSection />
          ) : (
            <div className="ov-placeholder">
              <div className="ov-ph-ic">🚧</div>
              <h3>{SECTION_TITLE[section]}</h3>
              <p>Khu vực này đang được phát triển. Sidebar và bố cục đã sẵn sàng để gắn tính năng.</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
