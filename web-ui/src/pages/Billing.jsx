import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { billing, vnd } from "../billingApi.js";
import { IcHome, IcBack } from "../components/icons.jsx";
import BackLink from "../components/BackLink.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

const TIER_ICON = { starter: "🌱", pro: "⭐", business: "🏢" };
const DUR_LABEL = { month: "Tháng", quarter: "Quý", year: "Năm", lifetime: "Vĩnh viễn" };
const DEPOSIT_PRESETS = [500_000, 1_350_000, 5_000_000, 10_000_000];
const ST_LABEL = { pending: "⏳ Chờ xác nhận", confirmed: "✅ Đã cộng ví", canceled: "✖ Đã huỷ" };

export default function Billing() {
  const nav = useNavigate();
  const user = currentUser();
  const hostName = user?.homestay || user?.username || "";

  const [me, setMe] = useState(null);          // null=tải | "offline" | object
  const [deps, setDeps] = useState([]);
  const [history, setHistory] = useState([]);
  const [msg, setMsg] = useState("");

  const [duration, setDuration] = useState("month");
  const [promo, setPromo] = useState("");
  const [amount, setAmount] = useState(500_000);
  const [newDep, setNewDep] = useState(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await billing.me();
    if (r.status === 0) { setMe("offline"); return; }
    if (r.status === 401) { nav("/login"); return; }
    setMe(r.body);
    billing.deposits().then((d) => Array.isArray(d.body) && setDeps(d.body));
    billing.history().then((h) => Array.isArray(h.body) && setHistory(h.body));
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  useEffect(() => {
    if (!deps.some((d) => d.status === "pending")) return;
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deps.map((d) => d.status).join(",")]);

  async function doRedeem() {
    setMsg("");
    const r = await billing.redeem(promo.trim());
    setMsg(r.ok ? "✅ Đã áp dụng mã — dùng thử 7 ngày!" : "❌ " + (r.body?.error || "Mã không đúng"));
    if (r.ok) { setPromo(""); load(); }
  }
  async function doDeposit() {
    setMsg(""); setBusy(true);
    const r = await billing.deposit(amount);
    setBusy(false);
    if (r.ok) { setNewDep(r.body); load(); }
    else setMsg("❌ " + (r.body?.error || "Không tạo được lệnh nạp"));
  }
  async function doBuy(tier) {
    const t = me.tiers.find((x) => x.tier === tier);
    const price = t.prices[duration];
    if (!confirm(`Mua ${TIER_ICON[tier]} ${t.label} · ${DUR_LABEL[duration]} giá ${vnd(price)} bằng ví?`)) return;
    setMsg("");
    const r = await billing.buy(tier, duration);
    setMsg(r.ok ? `✅ Đã kích hoạt ${t.label} · ${DUR_LABEL[duration]}!` : "❌ " + (r.body?.error || "Mua thất bại"));
    if (r.ok) load();
  }

  if (me === null) return <Shell hostName={hostName}><p>Đang tải…</p></Shell>;
  if (me === "offline")
    return (
      <Shell hostName={hostName}>
        <div className="empty">
          <p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p>
          <button className="btn-primary sm" onClick={load} style={{ margin: "0 auto" }}>Thử lại</button>
        </div>
      </Shell>
    );

  const expDate = me.expires_at ? new Date(me.expires_at).toLocaleDateString("vi-VN") : null;
  const usePct = me.ai_quota ? Math.min(100, Math.round((me.ai_used / me.ai_quota) * 100)) : 0;

  return (
    <Shell hostName={hostName}>
      {/* Trạng thái + ví + quota */}
      <div className={"bill-status" + (me.active ? "" : " expired")}>
        <div className="bill-status-main">
          <div className="bill-plan">
            {me.lifetime ? "👑 " : me.on_trial ? "🎁 " : (TIER_ICON[me.tier] || "📦") + " "}
            {me.on_trial ? "Đang dùng thử" : `${me.tier_label} · ${me.plan_label}`}
          </div>
          <div className="bill-sub">
            {me.lifetime
              ? "Dùng vĩnh viễn — không cần gia hạn."
              : me.active
                ? <>Còn <b>{me.days_left}</b> ngày (đến {expDate}).</>
                : <>⛔ ĐÃ HẾT HẠN {expDate ? `từ ${expDate}` : ""} — bot đã tạm ngừng trả lời khách.</>}
          </div>
        </div>
        <div className="bill-wallet">
          <div className="bill-wallet-label">Ví của bạn</div>
          <div className="bill-wallet-num">{vnd(me.balance)}</div>
        </div>
      </div>

      {/* Thanh quota lượt AI tháng này */}
      <div className="quota-box">
        <div className="quota-head">
          <span>Lượt AI trả lời tháng này</span>
          <b>{me.ai_used.toLocaleString("vi-VN")} / {me.ai_quota.toLocaleString("vi-VN")}</b>
        </div>
        <div className="quota-track"><div className={"quota-fill" + (usePct >= 100 ? " full" : "")} style={{ width: usePct + "%" }} /></div>
        {me.ai_left === 0 && <div className="hint" style={{ color: "var(--danger)", marginTop: 6 }}>⛔ Đã hết lượt AI tháng này — nâng hạng để mở thêm, hoặc chờ sang tháng.</div>}
      </div>

      {msg && <div className="savemsg" style={{ margin: "14px 0" }}>{msg}</div>}

      {/* Mã giới thiệu */}
      {me.on_trial && !me.promo_used && me.promo_enabled && (
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>🎁 Có mã giới thiệu?</h3>
          <p className="hint">Nhập mã để nâng thời gian dùng thử lên <b>7 ngày</b>.</p>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input style={{ flex: 1 }} placeholder="Nhập mã giới thiệu…" value={promo}
                   onChange={(e) => setPromo(e.target.value)} />
            <button className="btn-primary sm" onClick={doRedeem} disabled={!promo.trim()}>Áp dụng</button>
          </div>
        </div>
      )}

      {/* Bảng giá 3 hạng × chọn thời hạn */}
      <h3 className="bill-h">Chọn gói dịch vụ</h3>
      <div className="dur-switch">
        {me.durations.map((d) => (
          <button key={d.key} className={"dur-btn" + (duration === d.key ? " active" : "")}
                  onClick={() => setDuration(d.key)}>{DUR_LABEL[d.key]}</button>
        ))}
      </div>
      <div className="tier-grid">
        {me.tiers.map((t) => {
          const price = t.prices[duration];              // undefined = hạng này không bán thời hạn này
          const cur = me.tier === t.tier && !me.on_trial;
          return (
            <div key={t.tier} className={"tier-card" + (t.tier === "pro" ? " hot" : "") + (cur ? " current" : "") + (price === undefined ? " na" : "")}>
              {t.tier === "pro" && <div className="plan-badge">Phổ biến</div>}
              <div className="plan-ico">{TIER_ICON[t.tier]}</div>
              <div className="plan-name">{t.label}</div>
              <div className="plan-price">{price === undefined ? "—" : vnd(price)}</div>
              <div className="plan-days">{price === undefined ? "Không có gói này" : DUR_LABEL[duration]}</div>
              <ul className="tier-feats">
                <li>🤖 {t.quota.toLocaleString("vi-VN")} lượt AI/tháng</li>
                <li>📡 {t.channels ? `${t.channels} kênh` : "Tất cả kênh"}</li>
                <li>🤖 Không giới hạn số bot/page</li>
                <li className={t.call_owner ? "" : "off"}>{t.call_owner ? "✅" : "✖"} Gọi điện báo chủ</li>
                <li className={t.adv_stats ? "" : "off"}>{t.adv_stats ? "✅" : "✖"} Thống kê nâng cao</li>
              </ul>
              {price === undefined ? (
                <button className="btn-outline sm" disabled title="Muốn dùng vĩnh viễn hãy chọn Pro trở lên">Chỉ từ gói Pro</button>
              ) : cur && me.lifetime ? (
                <button className="btn-outline sm" disabled>👑 Đang dùng vĩnh viễn</button>
              ) : (
                <button className={"btn-primary sm" + (me.balance < price ? " plan-poor" : "")}
                        onClick={() => doBuy(t.tier)} disabled={me.balance < price}
                        title={me.balance < price ? "Ví chưa đủ — nạp thêm bên dưới" : cur ? "Cộng thêm thời hạn vào gói hiện tại" : ""}>
                  {me.balance < price ? "Ví chưa đủ" : cur ? "Gia hạn thêm" : "Chọn gói này"}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Nạp tiền */}
      <h3 className="bill-h">Nạp tiền vào ví</h3>
      <div className="panel set-card">
        {!me.bank.configured && (
          <p className="hint" style={{ color: "var(--danger)" }}>
            ⚠️ Chưa cấu hình tài khoản nhận tiền — admin thêm <code>BANK_NAME / BANK_ACCOUNT / BANK_HOLDER</code> vào <code>.env</code> rồi restart.
          </p>
        )}
        <div className="dep-presets">
          {DEPOSIT_PRESETS.map((v) => (
            <button key={v} className={"period-btn" + (amount === v ? " active" : "")}
                    onClick={() => setAmount(v)}>{vnd(v)}</button>
          ))}
          <input type="number" min={me.min_deposit} step={10000} value={amount}
                 onChange={(e) => setAmount(Number(e.target.value) || 0)} style={{ width: 140 }} />
          <button className="btn-primary sm" onClick={doDeposit} disabled={busy || amount < me.min_deposit}>
            {busy ? "Đang tạo…" : "Tạo lệnh nạp"}
          </button>
        </div>

        {newDep && (
          <div className="dep-guide">
            <h4>Chuyển khoản theo thông tin sau:</h4>
            <div className="dep-row"><span>Ngân hàng</span><b>{me.bank.name || "(admin chưa cấu hình)"}</b></div>
            <div className="dep-row"><span>Số tài khoản</span><b>{me.bank.account || "—"}</b></div>
            <div className="dep-row"><span>Chủ tài khoản</span><b>{me.bank.holder || "—"}</b></div>
            <div className="dep-row"><span>Số tiền</span><b>{vnd(newDep.amount)}</b></div>
            <div className="dep-row hl"><span>NỘI DUNG (bắt buộc)</span><b>{newDep.code}</b></div>
            <p className="hint">Chuyển đúng <b>nội dung {newDep.code}</b>. Sau khi admin xác nhận, tiền tự cộng vào ví — trang này tự làm mới.</p>
          </div>
        )}

        {deps.length > 0 && (
          <table className="bill-table">
            <thead><tr><th>Mã</th><th>Số tiền</th><th>Trạng thái</th><th>Lúc</th></tr></thead>
            <tbody>
              {deps.map((d) => (
                <tr key={d.id}>
                  <td><code>{d.code}</code></td><td>{vnd(d.amount)}</td>
                  <td>{ST_LABEL[d.status] || d.status}</td>
                  <td>{new Date(d.created_at).toLocaleString("vi-VN")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Lịch sử */}
      {history.length > 0 && (
        <>
          <h3 className="bill-h">Lịch sử giao dịch</h3>
          <div className="panel set-card">
            <table className="bill-table">
              <tbody>
                {history.map((t, i) => (
                  <tr key={i}>
                    <td>{t.note}</td>
                    <td style={{ color: t.amount >= 0 ? "var(--ok, #4f9d6b)" : "var(--danger)", fontWeight: 700 }}>
                      {t.amount > 0 ? "+" : ""}{t.amount !== 0 ? vnd(t.amount) : ""}
                    </td>
                    <td>{new Date(t.created_at).toLocaleString("vi-VN")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Shell>
  );
}

function Shell({ hostName, children }) {
  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <span className="brand-mini" style={{ marginLeft: -4 }}><IcHome width={18} height={18} /></span> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản">
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
        </div>
      </header>
      <main className="content narrow" style={{ maxWidth: 820 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">Thanh toán</div>
            <h1 className="page-title">Gói dịch vụ</h1>
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
