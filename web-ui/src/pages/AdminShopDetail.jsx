import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { currentUser, getToken } from "../auth.js";
import { HOST } from "../apiConfig.js";
import LogoMark from "../components/LogoMark.jsx";
import { useI18n } from "../i18n.jsx";

/*
 * 🛠 CHI TIẾT 1 SHOP — khu quản trị nền tảng (/admin/shop/:username).
 * READ-ONLY số liệu bán hàng: doanh thu, đơn, hoạt động, kênh — KHÔNG xem
 * nội dung chat của khách (tôn trọng riêng tư shop). Backend chốt quyền
 * ở /admin/shops/<username> (403 nếu không phải quản trị nền tảng).
 * Chuỗi hiển thị qua i18n (fragment src/i18n/admin.js, prefix "adm.").
 */

// Starter/Pro/Business là tên riêng — chỉ "trial" cần dịch
function tierLabel(tier, t) {
  const FIXED = { starter: "Starter", pro: "Pro", business: "Business" };
  if (tier === "trial") return t("adm.tier_trial");
  return FIXED[tier] || tier || "—";
}
// Trạng thái đơn — key i18n "adm.os_<status>", fallback chính status lạ
function statusLabel(st, t) {
  const KNOWN = ["draft", "awaiting_payment", "paid", "fulfilled", "done", "cancelled"];
  return KNOWN.includes(st) ? t("adm.os_" + st) : st;
}
const CH_LABEL = {
  "1": "Zalo", // sessions.account của kênh Zalo cá nhân (bridge) là "1"
  zalo: "Zalo", meta: "Messenger", instagram: "Instagram", telegram: "Telegram",
  shopee: "Shopee", zalo_oa: "Zalo OA", zalooa: "Zalo OA",
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
function Bars({ data, valueKey, labelFmt, color = "#7C3AED", emptyText }) {
  const max = Math.max(1, ...data.map((d) => d[valueKey] || 0));
  if (!data.length) return <p className="hint">{emptyText}</p>;
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
  const { t } = useI18n();
  const { username } = useParams();
  const user = currentUser();
  const [data, setData] = useState(null); // null=tải | object | "denied" | "offline" | "notfound"
  const [brain, setBrain] = useState(null); // não bot: {prompt, knowledge, photos}
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
    // Não bot (prompt + dữ liệu + ảnh) — tải song song, lỗi thì bỏ qua phần này
    try {
      const r = await fetch(HOST.bridge + "/admin/shops/" + encodeURIComponent(username) + "/brain", {
        headers: { Authorization: `Bearer ${getToken()}` },
      });
      const b = await r.json();
      if (b?.ok) setBrain(b);
    } catch { /* server cũ chưa có endpoint */ }
  }
  useEffect(() => { load(); }, [username]);

  async function post(path, body) {
    const r = await fetch(HOST.bridge + `/admin/shops/${encodeURIComponent(username)}/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify(body),
    });
    const b = await r.json().catch(() => ({}));
    if (!r.ok || !b.ok) throw new Error(b.error || t("adm.err_status", { n: r.status }));
    return b;
  }

  async function doBlock(blocked) {
    const q = blocked ? t("adm.block_confirm") : t("adm.unblock_confirm");
    if (!window.confirm(q)) return;
    setBusy("block"); setMsg("");
    try { await post("block", { blocked }); await load(); }
    catch (e) { setMsg("⚠️ " + e.message); }
    finally { setBusy(""); }
  }

  async function doPlan(action) {
    if (action === "revoke" && !window.confirm(t("adm.revoke_confirm"))) return;
    setBusy("plan"); setMsg("");
    try {
      await post("plan", action === "grant" ? { action, tier, duration } : { action });
      await load();
      setMsg(action === "grant" ? t("adm.granted") : t("adm.revoked"));
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
          <span className="adm-badge">{t("adm.badge")}</span>
        </div>
        <div className="adm-top-right">
          <span className="adm-user">{user?.homestay || user?.username}</span>
          <Link to="/admin" className="btn-ghost adm-back">{t("adm.back_list")}</Link>
        </div>
      </header>

      <main className="adm-body">
        {data === null && <p className="hint">{t("adm.loading")}</p>}
        {data === "offline" && <p className="hint">{t("adm.offline")}</p>}
        {data === "notfound" && <p className="hint">{t("adm.notfound")} <Link to="/admin">{t("adm.back")}</Link></p>}

        {d && (
          <>
            {/* Header shop */}
            <div className="adm-shop-head">
              <div>
                <h2 style={{ margin: 0 }}>{d.shop.shop_name}{d.shop.is_platform_admin ? " ⭐" : ""}</h2>
                <div className="hint">{d.shop.username} · {t("adm.registered", { d: fmtDate(d.shop.created_at) })}</div>
              </div>
              <div className="adm-shop-plan">
                {d.shop.blocked && <span className="adm-st blk">{t("adm.st_blocked")}</span>}
                {active
                  ? <span className="adm-st ok">{t("adm.st_active")}</span>
                  : <span className="adm-st off">{t("adm.st_expired")}</span>}
                <span className="adm-plan-tag">
                  {tierLabel(d.billing?.tier, t)}
                  {d.billing?.lifetime ? ` · ${t("adm.lifetime")}` : d.billing?.expires_at ? ` · ${t("adm.expires_short", { d: fmtDate(d.billing.expires_at) })}` : ""}
                </span>
              </div>
            </div>

            {/* KPI shop */}
            <div className="kpi-row">
              <Kpi label={t("adm.kpi_revenue")} value={vnd(d.orders.revenue)} accent="#23a065" icon="💰" />
              <Kpi label={t("adm.kpi_orders")} value={d.orders.total} accent="#7C3AED" icon="🧾" />
              <Kpi label={t("adm.kpi_conv")} value={d.conversations.total} accent="#4C6EF5" icon="💬" />
              <Kpi label={t("adm.kpi_ai")} value={d.billing?.ai_used || 0} accent="#cf9536" icon="🤖" />
            </div>

            {/* Hành động quản trị: cấp/thu hồi gói + chặn shop */}
            {!d.shop.is_platform_admin && (
              <div className="panel adm-panel adm-actions">
                <h3 style={{ marginTop: 0 }}>{t("adm.manage_title")}</h3>
                <div className="adm-act-row">
                  <label>{t("adm.grant_label")}</label>
                  <select value={tier} onChange={(e) => setTier(e.target.value)}>
                    <option value="starter">{t("adm.opt_starter")}</option>
                    <option value="pro">Pro</option>
                    <option value="business">{t("adm.opt_business")}</option>
                  </select>
                  <select value={duration} onChange={(e) => setDuration(e.target.value)}>
                    <option value="month">{t("adm.dur_month")}</option>
                    <option value="quarter">{t("adm.dur_quarter")}</option>
                    <option value="year">{t("adm.dur_year")}</option>
                    <option value="lifetime">{t("adm.lifetime")}</option>
                  </select>
                  <button className="btn-mini" disabled={busy === "plan"}
                          onClick={() => doPlan("grant")}>
                    {busy === "plan" ? t("adm.busy") : t("adm.grant_btn")}
                  </button>
                  <button className="btn-mini adm-danger" disabled={busy === "plan"}
                          onClick={() => doPlan("revoke")}>
                    {t("adm.revoke_btn")}
                  </button>
                  <span style={{ flex: 1 }} />
                  {d.shop.blocked ? (
                    <button className="btn-mini" disabled={busy === "block"}
                            onClick={() => doBlock(false)}>
                      {busy === "block" ? t("adm.busy") : t("adm.unblock_btn")}
                    </button>
                  ) : (
                    <button className="btn-mini adm-danger" disabled={busy === "block"}
                            onClick={() => doBlock(true)}>
                      {busy === "block" ? t("adm.busy") : t("adm.block_btn")}
                    </button>
                  )}
                </div>
                {msg && <div className="hint" style={{ marginTop: 8 }}>{msg}</div>}
              </div>
            )}

            {/* Doanh thu 30 ngày + hoạt động 14 ngày */}
            <div className="adm-2col">
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>{t("adm.rev30")}</h3>
                <Bars data={d.orders.by_day} valueKey="revenue" labelFmt={vnd} color="#23a065"
                      emptyText={t("adm.bars_empty")} />
              </div>
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>{t("adm.act14")}</h3>
                <Bars data={d.conversations.by_day} valueKey="conv"
                      labelFmt={(v) => t("adm.bars_conv", { n: v })} color="#4C6EF5"
                      emptyText={t("adm.bars_empty")} />
              </div>
            </div>

            {/* Kênh + trạng thái đơn + nhân viên */}
            <div className="adm-2col">
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>{t("adm.channels", { n: d.channels.length })}</h3>
                {d.channels.length === 0 && <p className="hint">{t("adm.no_channels")}</p>}
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
                    {t("adm.conv_by_channel")}{" "}
                    {Object.entries(d.conversations.by_channel)
                      .map(([k, v]) => `${CH_LABEL[k] || k}: ${v}`).join(" · ")}
                  </div>
                )}
                <div className="hint" style={{ marginTop: 6 }}>
                  {t("adm.last_activity")} {fmtTime(d.conversations.last_activity)}
                </div>
              </div>
              <div className="panel adm-panel">
                <h3 style={{ marginTop: 0 }}>{t("adm.orders_by_status", { v: vnd(d.billing?.balance) })}</h3>
                <div className="adm-chips">
                  {Object.entries(d.orders.by_status).map(([st, n]) => (
                    <span key={st} className="adm-chip"><em>{statusLabel(st, t)}</em>{n}</span>
                  ))}
                  {d.orders.total === 0 && <p className="hint">{t("adm.no_orders")}</p>}
                </div>
                {d.staff.length > 0 && (
                  <div className="hint" style={{ marginTop: 10 }}>
                    {t("adm.staff", { n: d.staff.length })} {d.staff.map((s) => s.name || s.username).join(", ")}
                  </div>
                )}
              </div>
            </div>

            {/* Đơn gần nhất */}
            <div className="panel adm-panel">
              <h3 style={{ marginTop: 0 }}>{t("adm.recent_orders", { n: d.orders.recent.length })}</h3>
              <div style={{ overflowX: "auto" }}>
                <table className="ad-table">
                  <thead>
                    <tr>
                      <th>{t("adm.o_code")}</th><th>{t("adm.o_cust")}</th><th>{t("adm.o_channel")}</th><th>{t("adm.o_type")}</th>
                      <th>{t("adm.o_total")}</th><th>{t("adm.o_status")}</th><th>{t("adm.o_created")}</th><th>{t("adm.o_due")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.orders.recent.map((o) => (
                      <tr key={o.code}>
                        <td><b>{o.code}</b></td>
                        <td>{o.customer_name || "—"}</td>
                        <td>{CH_LABEL[o.channel] || o.channel || "—"}</td>
                        <td>{o.order_type === "goods" ? t("adm.o_goods") : t("adm.o_booking")}</td>
                        <td>{vnd(o.total)}</td>
                        <td>{statusLabel(o.status, t)}</td>
                        <td>{fmtTime(o.created_at)}</td>
                        <td>{fmtDate(o.due_at)}</td>
                      </tr>
                    ))}
                    {d.orders.recent.length === 0 && (
                      <tr><td colSpan={8} className="hint" style={{ textAlign: "center", padding: 20 }}>
                        {t("adm.no_orders_row")}
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Não bot & dữ liệu train (read-only) */}
            {brain && (
              <>
                <div className="panel adm-panel">
                  <h3 style={{ marginTop: 0 }}>
                    {t("adm.brain_prompt")}{" "}
                    <span className="hint" style={{ fontWeight: 400 }}>
                      {brain.prompt?.source === "custom"
                        ? t("adm.brain_custom", {
                            mode: t(brain.prompt.mode === "hybrid" ? "adm.brain_hybrid" : "adm.brain_full"),
                            edited: brain.prompt.updated_at ? t("adm.brain_edited", { d: fmtTime(brain.prompt.updated_at) }) : "",
                          })
                        : t("adm.brain_default")}
                    </span>
                  </h3>
                  {brain.prompt?.prompt ? (
                    <details className="adm-fold">
                      <summary>{t("adm.brain_view", { n: (brain.prompt.prompt.length || 0).toLocaleString("vi-VN") })}</summary>
                      <pre className="adm-pre">{brain.prompt.prompt}</pre>
                    </details>
                  ) : <p className="hint">{t("adm.brain_none")}</p>}
                </div>

                <div className="panel adm-panel">
                  <h3 style={{ marginTop: 0 }}>{t("adm.kb_title", { n: brain.knowledge.length })}</h3>
                  {brain.knowledge.length === 0 && <p className="hint">{t("adm.kb_empty")}</p>}
                  {brain.knowledge.map((c) => (
                    <details key={c.id} className="adm-fold">
                      <summary>
                        {c.pinned ? "📌 " : ""}{c.title || t("adm.kb_untitled")}
                        {c.keywords.length > 0 && (
                          <span className="hint"> — {c.keywords.slice(0, 5).join(", ")}</span>
                        )}
                      </summary>
                      <pre className="adm-pre">{c.content}</pre>
                    </details>
                  ))}
                </div>

                <div className="panel adm-panel">
                  <h3 style={{ marginTop: 0 }}>{t("adm.photos_title", { n: brain.photos.length })}</h3>
                  {brain.photos.length === 0 && <p className="hint">{t("adm.photos_empty")}</p>}
                  {brain.photos.map((s) => (
                    <div key={s.slug} className="adm-photoset">
                      <div className="adm-photoset-head">
                        <b>{s.name}</b>
                        <span className="hint">
                          {t("adm.photos_count", { n: s.files.length })}{s.keywords.length > 0 ? t("adm.photos_kw", { kw: s.keywords.join(", ") }) : ""}
                        </span>
                      </div>
                      <div className="adm-photo-grid">
                        {s.files.slice(0, 12).map((f) => (
                          <a key={f} href={`${HOST.bridge}/photos/file/${s.slug}/${encodeURIComponent(f)}`}
                             target="_blank" rel="noreferrer">
                            <img src={`${HOST.bridge}/photos/file/${s.slug}/${encodeURIComponent(f)}`}
                                 alt={f} loading="lazy" />
                          </a>
                        ))}
                        {s.files.length > 12 && (
                          <span className="hint">{t("adm.photos_more", { n: s.files.length - 12 })}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
