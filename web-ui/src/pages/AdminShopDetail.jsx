import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { currentUser, getToken } from "../auth.js";
import { HOST } from "../apiConfig.js";
import LogoMark from "../components/LogoMark.jsx";

/*
 * 🛠 CHI TIẾT 1 SHOP — khu quản trị nền tảng (/admin/shop/:username).
 * READ-ONLY số liệu bán hàng: doanh thu, đơn, hoạt động, kênh — KHÔNG xem
 * nội dung chat của khách (tôn trọng riêng tư shop). Backend chốt quyền
 * ở /admin/shops/<username> (403 nếu không phải quản trị nền tảng).
 */

const TIER_LABEL = { trial: "Dùng thử", starter: "Starter", pro: "Pro", business: "Business" };
const STATUS_LABEL = {
  draft: "Nháp", awaiting_payment: "Chờ thanh toán", paid: "Đã thanh toán",
  fulfilled: "Đã giao", done: "Hoàn tất", cancelled: "Đã huỷ",
};
const CH_LABEL = {
  "1": "Zalo", // sessions.account của kênh Zalo cá nhân (bridge) là "1"
  zalo: "Zalo", meta: "Messenger", instagram: "Instagram", telegram: "Telegram",
  tiktok: "TikTok", shopee: "Shopee", zalo_oa: "Zalo OA", zalooa: "Zalo OA",
  webchat: "Website",
};
const vnd = (n) => (n || 0).toLocaleString("vi-VN") + "đ";
const fmtDate = (iso) => (iso ? iso.slice(0, 10) : "—");
const fmtTime = (iso) => (iso ? iso.slice(0, 16).replace("T", " ") : "—");

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

/** Biểu đồ cột thuần CSS — không kéo thêm thư viện chart cho 1 trang admin. */
function Bars({ data, valueKey, labelFmt, color = "#7C3AED" }) {
  const max = Math.max(1, ...data.map((d) => d[valueKey] || 0));
  if (!data.length) return <p className="hint">Chưa có dữ liệu trong khoảng này.</p>;
  return (
    <div className="adm-bars">
      {data.map((d) => (
        <div key={d.date} className="adm-bar-col" title={`${d.date}: ${labelFmt(d[valueKey] || 0)}`}>
          <div className="adm-bar" style={{
            height: `${Math.max(3, ((d[valueKey] || 0) / max) * 100)}%`,
            background: color,
          }} />
          <span className="adm-bar-day">{d.date.slice(8)}</span>
        </div>
      ))}
    </div>
  );
}

export default function AdminShopDetail() {
  const nav = useNavigate();
  const { username } = useParams();
  const user = currentUser();
  const [data, setData] = useState(null); // null=tải | object | "denied" | "offline" | "notfound"
  const [busy, setBusy] = useState("");   // "block" | "plan" | ""
  const [tier, setTier] = useState("pro");
  const [duration, setDuration] = useState("month");
  const [msg, setMsg] = useState("");

  async function load() {
    try {
      const r = await fetch(HOST.bridge + "/admin/shops/" + encodeURIComponent(username), {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      if (r.status === 403 || r.status === 401) { setData("denied"); return; }
      if (r.status === 404) { setData("notfound"); return; }
      const b = await r.json();
      setData(b?.ok ? b : "offline");
    } catch { setData("offline"); }
  }
  useEffect(() => { load(); }, [username]);

  async function post(path, body) {
    const r = await fetch(HOST.bridge + `/admin/shops/${encodeURIComponent(username)}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify(body),
    });
    const b = await r.json().catch(() => ({}));
    if (!r.ok || !b.ok) throw new Error(b.error || `Lỗi ${r.status}`);
    return b;
  }

  async function doBlock(blocked) {
    const q = blocked
      ? `CHẶN shop này? Shop + nhân viên bị đăng xuất ngay, không đăng nhập được và bot ngừng trả lời khách.`
      : `Bỏ chặn shop này? Shop đăng nhập và dùng lại bình thường.`;
    if (!window.confirm(q)) return;
    setBusy("block"); setMsg("");
    try { await post("block", { blocked }); await load(); }
    catch (e) { setMsg("⚠️ " + e.message); }
    finally { setBusy(""); }
  }

  async function doPlan(action) {
    if (action === "revoke" &&
        !window.confirm("THU HỒI gói của shop? Gói hết hạn ngay lập tức, bot ngừng trả lời.")) return;
    setBusy("plan"); setMsg("");
    try {
      await post("plan", action === "grant" ? { action, tier, duration } : { action });
      await load();
      setMsg(action === "grant" ? "✅ Đã cấp gói." : "✅ Đã thu hồi gói.");
    } catch (e) { setMsg("⚠️ " + e.message); }
    finally { setBusy(""); }
  }

  useEffect(() => { if (data === "denied") nav("/", { replace: true }); }, [data, nav]);

  const d = data && typeof data === "object" ? data : null;
  const active = useMemo(() => {
    const b = d?.billing;
    if (!b) return false;
    if (b.lifetime) return true;
    return b.expires_at ? new Date(b.expires_at) > new Date() : false;
  }, [d]);

  return (
    <div className="adm">
      <header className="adm-top">
        <div className="adm-brand">
          <LogoMark size={30} />
          <span>Nova<b>Chat</b></span>
          <span className="adm-badge">🛠 Quản trị nền tảng</span>
        </div>
        <div className="adm-top-right">
          <span className="adm-user">{user?.homestay || user?.username}</span>
          <Link to="/admin" className="btn-ghost adm-back">← Danh sách shop</Link>
        </div>
      </header>

      <main className="adm-body">
        {data === null && <p className="hint">Đang tải…</p>}
        {data === "offline" && <p className="hint">⚠️ Chưa kết nối máy chủ (5005) — hoặc server cần restart bản mới.</p>}
        {data === "notfound" && <p className="hint">Không tìm thấy shop này. <Link to="/admin">← Quay lại</Link></p>}

        {d && (
          <>
            {/* Header shop */}
            <div className="adm-shop-head">
              <div>
                <h2 style={{ margin: 0 }}>{d.shop.shop_name}{d.shop.is_platform_admin ? " ⭐" : ""}</h2>
                <div className="hint">{d.shop.username} · đăng ký {fmtDate(d.shop.created_at)}</div>
              </div>
              <div className="adm-shop-plan">
                {d.shop.blocked && <span className="adm-st blk">⛔ Bị chặn</span>}
                {active
                  ? <span className="adm-st ok">● Hoạt động</span>
                  : <span className="adm-st off">● Hết hạn</span>}
                <span className="adm-plan-tag">
                  {TIER_LABEL[d.billing?.tier] || d.billing?.tier || "—"}
                  {d.billing?.lifetime ? " · Vĩnh viễn" : d.billing?.expires_at ? ` · hết ${fmtDate(d.billing.expires_at)}` : ""}
                </span>
              </div>
            </div>

            {/* KPI shop */}
            <div className="kpi-row">
              <Kpi label="Doanh thu (đơn đã trả)" value={vnd(d.orders.revenue)} accent="#23a065" icon="💰" />
              <Kpi label="Tổng đơn hàng" value={d.orders.total} accent="#7C3AED" icon="🧾" />
              <Kpi label="Hội thoại" value={d.conversations.total} accent="#4C6EF5" icon="💬" />
              <Kpi label="Lượt AI kỳ này" value={d.billing?.ai_used || 0} accent="#cf9536" icon="🤖" />
            </div>

            {/* Hành động quản trị: cấp/thu hồi gói + chặn shop */}
            {!d.shop.is_platform_admin && (
              <div className="panel adm-panel adm-actions">
                <h3 style={{ marginTop: 0 }}>Quản trị shop</h3>
                <div className="adm-act-row">
                  <label>Cấp gói (không trừ ví):</label>
                  <select value={tier} onChange={(e) => setTier(e.target.value)}>
                    <option value="starter">Khởi đầu</option>
                    <option value="pro">Pro</option>
                    <option value="business">Chuỗi</option>
                  </select>
                  <select value={duration} onChange={(e) => setDuration(e.target.value)}>
                    <option value="month">1 tháng</option>
                    <option value="quarter">1 quý</option>
                    <option value="year">1 năm</option>
                    <option value="lifetime">Vĩnh viễn</option>
                  </select>
                  <button className="btn-mini" disabled={busy === "plan"}
                          onClick={() => doPlan("grant")}>
                    {busy === "plan" ? "Đang xử lý…" : "🎁 Cấp gói"}
                  </button>
                  <button className="btn-mini adm-danger" disabled={busy === "plan"}
                          onClick={() => doPlan("revoke")}>
                    ✂️ Thu hồi gói
                  </button>
                  <span style={{ flex: 1 }} />
                  {d.shop.blocked ? (
                    <button className="btn-mini" disabled={busy === "block"}
                            onClick={() => doBlock(false)}>
                      {busy === "block" ? "Đang xử lý…" : "✅ Bỏ chặn shop"}
                    </button>
                  ) : (
                    <button className="btn-mini adm-danger" disabled={busy === "block"}
                            onClick={() => doBlock(true)}>
                      {busy === "block" ? "Đang xử lý…" : "⛔ Chặn shop"}
                    </button>
                  )}
                </div>
                {msg && <div className="hint" style={{ marginTop: 8 }}>{msg}</div>}
              </div>
            )}

            {/* Doanh thu 30 ngày + hoạt động 14 ngày */}
            <div className="adm-2col">
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>Doanh thu 30 ngày</h3>
                <Bars data={d.orders.by_day} valueKey="revenue" labelFmt={vnd} color="#23a065" />
              </div>
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>Hội thoại có hoạt động (14 ngày)</h3>
                <Bars data={d.conversations.by_day} valueKey="conv"
                      labelFmt={(v) => `${v} hội thoại`} color="#4C6EF5" />
              </div>
            </div>

            {/* Kênh + trạng thái đơn + nhân viên */}
            <div className="adm-2col">
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>Kênh đã nối ({d.channels.length})</h3>
                {d.channels.length === 0 && <p className="hint">Shop chưa nối kênh nào.</p>}
                <div className="adm-chips">
                  {d.channels.map((c, i) => (
                    <span key={i} className="adm-chip">
                      {CH_LABEL[c.channel] || c.channel}
                      <em>{c.name}</em>
                    </span>
                  ))}
                </div>
                {Object.keys(d.conversations.by_channel).length > 0 && (
                  <div className="hint" style={{ marginTop: 10 }}>
                    Hội thoại theo kênh:{" "}
                    {Object.entries(d.conversations.by_channel)
                      .map(([k, v]) => `${CH_LABEL[k] || k}: ${v}`).join(" · ")}
                  </div>
                )}
                <div className="hint" style={{ marginTop: 6 }}>
                  Hoạt động cuối: {fmtTime(d.conversations.last_activity)}
                </div>
              </div>
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>Đơn theo trạng thái · Ví {vnd(d.billing?.balance)}</h3>
                <div className="adm-chips">
                  {Object.entries(d.orders.by_status).map(([st, n]) => (
                    <span key={st} className="adm-chip"><em>{STATUS_LABEL[st] || st}</em>{n}</span>
                  ))}
                  {d.orders.total === 0 && <p className="hint">Chưa có đơn nào.</p>}
                </div>
                {d.staff.length > 0 && (
                  <div className="hint" style={{ marginTop: 10 }}>
                    Nhân viên ({d.staff.length}): {d.staff.map((s) => s.name || s.username).join(", ")}
                  </div>
                )}
              </div>
            </div>

            {/* Đơn gần nhất */}
            <div className="panel adm-panel">
              <h3 style={{ marginTop: 0 }}>Đơn gần nhất ({d.orders.recent.length})</h3>
              <div style={{ overflowX: "auto" }}>
                <table className="ad-table">
                  <thead>
                    <tr>
                      <th>Mã</th><th>Khách</th><th>Kênh</th><th>Loại</th>
                      <th>Tổng tiền</th><th>Trạng thái</th><th>Tạo lúc</th><th>Tới hạn</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.orders.recent.map((o) => (
                      <tr key={o.code}>
                        <td><b>{o.code}</b></td>
                        <td>{o.customer_name || "—"}</td>
                        <td>{CH_LABEL[o.channel] || o.channel || "—"}</td>
                        <td>{o.order_type === "goods" ? "Bán hàng" : "Đặt chỗ"}</td>
                        <td>{vnd(o.total)}</td>
                        <td>{STATUS_LABEL[o.status] || o.status}</td>
                        <td>{fmtTime(o.created_at)}</td>
                        <td>{fmtDate(o.due_at)}</td>
                      </tr>
                    ))}
                    {d.orders.recent.length === 0 && (
                      <tr><td colSpan={8} className="hint" style={{ textAlign: "center", padding: 20 }}>
                        Shop chưa có đơn hàng nào.
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
