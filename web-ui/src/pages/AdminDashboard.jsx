import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { HOST } from "../apiConfig.js";
import { getToken } from "../auth.js";
import LogoMark from "../components/LogoMark.jsx";
import { useI18n } from "../i18n.jsx";

/*
 * 🛠 DASHBOARD QUẢN TRỊ NỀN TẢNG — trang RIÊNG cho chủ nền tảng (route /admin),
 * tách khỏi dashboard shop. Xem toàn bộ shop: gói, hạn, mức dùng, hoạt động.
 * Backend chốt quyền thật ở /admin/shops (403 nếu không phải chủ nền tảng).
 * Chuỗi hiển thị qua i18n (fragment src/i18n/admin.js, prefix "adm.").
 */

// Starter/Pro/Business là tên riêng — chỉ "trial" cần dịch
function tierLabel(tier, t) {
  const FIXED = { starter: "Starter", pro: "Pro", business: "Business" };
  if (tier === "trial") return t("adm.tier_trial");
  return FIXED[tier] || tier || "—";
}
const vnd = (n) => (n || 0).toLocaleString("vi-VN") + "đ";

function fmtDate(iso) { return iso ? iso.slice(0, 10) : "—"; }
function fmtTime(iso) { return iso ? iso.slice(0, 16).replace("T", " ") : "—"; }

function Kpi({ label, value, accent, icon }) {
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

export default function AdminDashboard() {
  const nav = useNavigate();
  const { t } = useI18n();
  const user = currentUser();
  const [data, setData] = useState(null);   // null=tải | {shops} | "denied" | "offline"
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);

  async function load() {
    setLoading(true);
    try {
      const r = await fetch(HOST.bridge + "/admin/shops", {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (r.status === 403 || r.status === 401) { setData("denied"); return; }
      const b = await r.json();
      setData(b?.ok ? b : "offline");
    } catch { setData("offline"); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);

  // Không phải chủ nền tảng → đẩy về dashboard thường
  useEffect(() => { if (data === "denied") nav("/", { replace: true }); }, [data, nav]);

  const shops = Array.isArray(data?.shops) ? data.shops : [];
  const kpi = useMemo(() => ({
    total: shops.length,
    active: shops.filter((s) => s.active).length,
    convs: shops.reduce((a, s) => a + (s.conversations || 0), 0),
    ai: shops.reduce((a, s) => a + (s.ai_used || 0), 0),
  }), [shops]);

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return shops;
    return shops.filter((x) =>
      (x.shop_name || "").toLowerCase().includes(s) ||
      (x.username || "").toLowerCase().includes(s));
  }, [shops, q]);

  return (
    <div className="adm">
      {/* Topbar riêng của khu quản trị */}
      <header className="adm-top">
        <div className="adm-brand">
          <LogoMark size={30} />
          <span>Nova<b>Chat</b></span>
          <span className="adm-badge">{t("adm.badge")}</span>
        </div>
        <div className="adm-top-right">
          <span className="adm-user">{user?.homestay || user?.username}</span>
          <Link to="/" className="btn-ghost adm-back">{t("adm.back_dash")}</Link>
        </div>
      </header>

      <main className="adm-body">
        {data === null && <p className="hint">{t("adm.loading")}</p>}
        {data === "offline" && (
          <p className="hint">{t("adm.offline")}</p>
        )}

        {Array.isArray(shops) && data && typeof data === "object" && (
          <>
            {/* KPI nền tảng */}
            <div className="kpi-row">
              <Kpi label={t("adm.kpi_shops")}  value={kpi.total}  accent="#7C3AED" icon="🏬" />
              <Kpi label={t("adm.kpi_active")} value={kpi.active} accent="#23a065" icon="✅" />
              <Kpi label={t("adm.kpi_convs")}  value={kpi.convs}  accent="#4C6EF5" icon="💬" />
              <Kpi label={t("adm.kpi_ai")}     value={kpi.ai}     accent="#cf9536" icon="🤖" />
            </div>

            {/* Bảng shop */}
            <div className="panel adm-panel">
              <div className="adm-toolbar">
                <h3>{t("adm.list_title", { n: shown.length })}</h3>
                <input className="adm-search" placeholder={t("adm.search_ph")}
                       value={q} onChange={(e) => setQ(e.target.value)} />
                <button className="btn-mini" onClick={load} disabled={loading}>
                  {loading ? t("adm.loading") : t("adm.refresh")}
                </button>
              </div>

              <div style={{ overflowX: "auto" }}>
                <table className="ad-table">
                  <thead>
                    <tr>
                      <th>{t("adm.th_shop")}</th><th>{t("adm.th_tier")}</th><th>{t("adm.th_status")}</th><th>{t("adm.th_expires")}</th>
                      <th>{t("adm.th_wallet")}</th><th>{t("adm.th_ai")}</th><th>{t("adm.th_conv")}</th><th>{t("adm.th_orders")}</th>
                      <th>{t("adm.th_staff")}</th><th>{t("adm.th_last")}</th><th>{t("adm.th_created")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((s) => (
                      <tr key={s.username} className="adm-row"
                          title={t("adm.row_view")}
                          onClick={() => nav(`/admin/shop/${encodeURIComponent(s.username)}`)}>
                        <td>
                          <b>{s.shop_name}</b>{s.is_platform_admin ? " ⭐" : ""}
                          <div className="hint" style={{ fontSize: 12 }}>{s.username}</div>
                        </td>
                        <td>{tierLabel(s.tier, t)}</td>
                        <td>
                          {s.blocked
                            ? <span className="adm-st blk">{t("adm.st_blocked")}</span>
                            : s.active
                              ? <span className="adm-st ok">{t("adm.st_active")}</span>
                              : <span className="adm-st off">{t("adm.st_expired")}</span>}
                        </td>
                        <td>{s.lifetime ? t("adm.lifetime") : fmtDate(s.expires_at)}</td>
                        <td>{vnd(s.balance)}</td>
                        <td>{s.ai_used}</td>
                        <td>{s.conversations}</td>
                        <td>{s.orders}</td>
                        <td>{s.staff_count}</td>
                        <td>{fmtTime(s.last_activity)}</td>
                        <td>{fmtDate(s.created_at)}</td>
                      </tr>
                    ))}
                    {shown.length === 0 && (
                      <tr><td colSpan={11} className="hint" style={{ textAlign: "center", padding: 20 }}>
                        {t("adm.no_match")}
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
