import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { HOST } from "../apiConfig.js";
import { getToken } from "../auth.js";
import LogoMark from "../components/LogoMark.jsx";

/*
 * 🛠 DASHBOARD QUẢN TRỊ NỀN TẢNG — trang RIÊNG cho chủ nền tảng (route /admin),
 * tách khỏi dashboard shop. Xem toàn bộ shop: gói, hạn, mức dùng, hoạt động.
 * Backend chốt quyền thật ở /admin/shops (403 nếu không phải chủ nền tảng).
 */

const TIER_LABEL = { trial: "Dùng thử", starter: "Starter", pro: "Pro", business: "Business" };
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
          <span className="adm-badge">🛠 Quản trị nền tảng</span>
        </div>
        <div className="adm-top-right">
          <span className="adm-user">{user?.homestay || user?.username}</span>
          <Link to="/" className="btn-ghost adm-back">← Về dashboard shop</Link>
        </div>
      </header>

      <main className="adm-body">
        {data === null && <p className="hint">Đang tải…</p>}
        {data === "offline" && (
          <p className="hint">⚠️ Chưa kết nối máy chủ (5005) — hoặc server cần restart bản mới.</p>
        )}

        {Array.isArray(shops) && data && typeof data === "object" && (
          <>
            {/* KPI nền tảng */}
            <div className="kpi-row">
              <Kpi label="Tổng shop"        value={kpi.total}  accent="#7C3AED" icon="🏬" />
              <Kpi label="Gói còn hiệu lực" value={kpi.active} accent="#23a065" icon="✅" />
              <Kpi label="Tổng hội thoại"   value={kpi.convs}  accent="#4C6EF5" icon="💬" />
              <Kpi label="Lượt AI kỳ này"   value={kpi.ai}     accent="#cf9536" icon="🤖" />
            </div>

            {/* Bảng shop */}
            <div className="panel adm-panel">
              <div className="adm-toolbar">
                <h3>Danh sách shop ({shown.length})</h3>
                <input className="adm-search" placeholder="🔍 Tìm tên shop / email…"
                       value={q} onChange={(e) => setQ(e.target.value)} />
                <button className="btn-mini" onClick={load} disabled={loading}>
                  {loading ? "Đang tải…" : "↻ Làm mới"}
                </button>
              </div>

              <div style={{ overflowX: "auto" }}>
                <table className="ad-table">
                  <thead>
                    <tr>
                      <th>Shop</th><th>Gói</th><th>Trạng thái</th><th>Hết hạn</th>
                      <th>Ví</th><th>Lượt AI</th><th>Hội thoại</th><th>Đơn</th>
                      <th>NV</th><th>Hoạt động cuối</th><th>Đăng ký</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((s) => (
                      <tr key={s.username} className="adm-row"
                          title="Xem chi tiết shop"
                          onClick={() => nav(`/admin/shop/${encodeURIComponent(s.username)}`)}>
                        <td>
                          <b>{s.shop_name}</b>{s.is_platform_admin ? " ⭐" : ""}
                          <div className="hint" style={{ fontSize: 12 }}>{s.username}</div>
                        </td>
                        <td>{TIER_LABEL[s.tier] || s.tier || "—"}</td>
                        <td>
                          {s.blocked
                            ? <span className="adm-st blk">⛔ Bị chặn</span>
                            : s.active
                              ? <span className="adm-st ok">● Hoạt động</span>
                              : <span className="adm-st off">● Hết hạn</span>}
                        </td>
                        <td>{s.lifetime ? "Vĩnh viễn" : fmtDate(s.expires_at)}</td>
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
                        Không có shop nào khớp tìm kiếm.
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
