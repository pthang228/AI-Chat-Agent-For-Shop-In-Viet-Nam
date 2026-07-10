import { useState, useMemo, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, isStaff } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { billing as billingApi } from "../billingApi.js";
import { IcLogout } from "../components/icons.jsx";
import Sidebar from "../components/Sidebar.jsx";
import OverviewCharts from "../components/OverviewCharts.jsx";
import ChatbotSection from "../components/ChatbotSection.jsx";
import InboxSection from "../components/InboxSection.jsx";
import OrdersSection from "../components/OrdersSection.jsx";
import PostsSection from "../components/PostsSection.jsx";
import CustomersSection from "../components/CustomersSection.jsx";
import BroadcastSection from "../components/BroadcastSection.jsx";
import { useI18n } from "../i18n.jsx";

const PERIODS = ["today", "7d", "30d", "month", "year"];

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
  overview:  "nav.overview",
  chat:      "nav.chat",
  customers: "nav.customers",
  chatbot:   "nav.chatbot",
  orders:    "nav.orders",
  broadcast: "nav.broadcast",
  posts:     "sec.posts_full",
  stats:     "nav.stats",
};

export default function Overview() {
  const nav = useNavigate();
  const { t } = useI18n();
  const user = currentUser();
  const staff = isStaff(user);
  const hostName = user?.homestay || user?.username || "";
  const [section, setSectionRaw] = useState(() => {
    // Cho phép mở thẳng 1 mục qua URL ?s=chatbot (vd nút "Về danh sách app")
    const s = new URLSearchParams(window.location.search).get("s");
    const valid = ["overview", "chat", "customers", "chatbot", "orders", "broadcast", "posts", "stats"];
    if (staff) { // nhân viên không có mục quản trị
      const i = valid.indexOf("chatbot"); valid.splice(i, 1);
      valid.splice(valid.indexOf("broadcast"), 1);
    }
    return valid.includes(s) ? s : "overview";
  });
  // Đổi mục ⇒ ĐỒNG BỘ vào URL (?s=) để history-back từ trang app quay về ĐÚNG
  // mục đang xem (không rơi về Tổng quan). replace: không tạo entry lịch sử thừa.
  function setSection(key) {
    setSectionRaw(key);
    nav(key === "overview" ? "/" : `/?s=${key}`, { replace: true });
  }
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
    if (!confirm(t("logout.confirm"))) return;
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
        staff={staff}
        platformAdmin={!!user?.platform_admin}
      />

      <div className="shell-main">
        <header className="shell-top">
          <h2 className="shell-title">{t(SECTION_TITLE[section])}</h2>
          <div className="shell-top-right">
            <Link to="/settings" className="user-pill" title={t("nav.settings")}>
              <span className="avatar">{initials(hostName)}</span>{hostName}
            </Link>
            <button className="btn-ghost" onClick={doLogout}>
              <IcLogout width={15} height={15} /> {t("logout")}
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
                      ? <>{t("bill.trial", { n: bill.days_left })} <u>{t("bill.trial_link")}</u></>
                      : <>{t("bill.plan", { tier: bill.tier_label, plan: bill.plan_label, n: bill.days_left })} <u>{t("bill.renew")}</u></>
                    : <><b>{t("bill.expired")}</b> <u>{t("bill.renew_now")}</u></>}
                </Link>
              )}

              <div className="ov-head">
                <div>
                  <div className="hello">{t("ov.hello", { name: hostName })}</div>
                  <p className="page-sub">{t("ov.sub")}</p>
                </div>
                <div className="period-bar">
                  {PERIODS.map((p) => (
                    <button key={p}
                            className={"period-btn" + (period === p ? " active" : "")}
                            onClick={() => setPeriod(p)}>
                      {t("period." + p)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Hàng KPI */}
              <div className="kpi-row">
                <Kpi icon="✉️" label={t("kpi.msg")}     value={kpi.msg}  accent="#4C6EF5" />
                <Kpi icon="💬" label={t("kpi.conv")}    value={kpi.conv} accent="#7C3AED" />
                <Kpi icon="🤖" label={t("kpi.rate")}    value={kpi.rate} accent="#23a065" />
                <Kpi icon="⏱" label={t("kpi.latency")} value="—" accent="#cf9536" />
              </div>

              {/* 4 biểu đồ */}
              <OverviewCharts period={period} onData={setStats} />
            </>
          ) : section === "chat" ? (
            <InboxSection />
          ) : section === "customers" ? (
            <CustomersSection />
          ) : section === "chatbot" ? (
            <ChatbotSection />
          ) : section === "orders" ? (
            <OrdersSection />
          ) : section === "broadcast" && !staff ? (
            <BroadcastSection />
          ) : section === "posts" ? (
            <PostsSection />
          ) : (
            <div className="ov-placeholder">
              <div className="ov-ph-ic">🚧</div>
              <h3>{t(SECTION_TITLE[section])}</h3>
              <p>{t("ov.placeholder")}</p>
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
