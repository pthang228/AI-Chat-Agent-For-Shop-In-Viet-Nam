import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { billing, vnd } from "../billingApi.js";
import { IcHome, IcBack } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import BackLink from "../components/BackLink.jsx";
import { useI18n } from "../i18n.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

const TIER_ICON = { starter: "🌱", pro: "⭐", business: "🏢" };
const DUR_KEY = { month: "pay.dur_month", quarter: "pay.dur_quarter", year: "pay.dur_year", lifetime: "pay.dur_lifetime" };
const DEPOSIT_PRESETS = [500_000, 1_350_000, 5_000_000, 10_000_000];
const ST_KEY = { pending: "pay.st_pending", confirmed: "pay.st_confirmed", canceled: "pay.st_canceled" };

export default function Billing() {
  const nav = useNavigate();
  const { t } = useI18n();
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

  // Mô hình AI + tính theo usage khi hết quota (đồng bộ từ /billing/me)
  const [aiBusy, setAiBusy] = useState(false);
  const [usageOn, setUsageOn] = useState(false);
  const [usageLimit, setUsageLimit] = useState(200_000);
  useEffect(() => {
    if (me && typeof me === "object") {
      setUsageOn(!!me.usage_enabled);
      setUsageLimit(me.usage_limit || 200_000);
    }
  }, [me]);

  async function saveAiModel(key) {
    if (aiBusy) return;
    setMsg(""); setAiBusy(true);
    const r = await billing.setAiModel(key);
    setAiBusy(false);
    setMsg(r.ok ? t("pay.ai_changed") : "❌ " + (r.body?.error || t("pay.ai_change_fail")));
    if (r.ok) load();
  }
  async function saveUsage() {
    if (aiBusy) return;
    setMsg(""); setAiBusy(true);
    const r = await billing.setUsage(usageOn, usageLimit);
    setAiBusy(false);
    setMsg(r.ok
      ? (usageOn ? t("pay.usage_on_done", { v: vnd(usageLimit) }) : t("pay.usage_off_done"))
      : "❌ " + (r.body?.error || t("pay.save_fail")));
    if (r.ok) load();
  }

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
    const iv = setInterval(load, 10_000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deps.map((d) => d.status).join(",")]);

  async function doRedeem() {
    if (busy) return;              // chặn double-submit
    setMsg(""); setBusy(true);
    const r = await billing.redeem(promo.trim());
    setBusy(false);
    setMsg(r.ok ? t("pay.redeem_done") : "❌ " + (r.body?.error || t("pay.redeem_fail")));
    if (r.ok) { setPromo(""); load(); }
  }
  async function doDeposit() {
    setMsg(""); setBusy(true);
    const r = await billing.deposit(amount);
    setBusy(false);
    if (r.ok) { setNewDep(r.body); load(); }
    else setMsg("❌ " + (r.body?.error || t("pay.deposit_fail")));
  }
  async function doBuy(tier) {
    if (busy) return;              // chặn double-submit → trừ ví 2 lần
    const tr = me.tiers.find((x) => x.tier === tier);
    const price = tr.prices[duration];
    if (!confirm(t("pay.buy_confirm", { icon: TIER_ICON[tier], label: tr.label, dur: t(DUR_KEY[duration]), price: vnd(price) }))) return;
    setMsg(""); setBusy(true);
    const r = await billing.buy(tier, duration);
    setBusy(false);
    setMsg(r.ok ? t("pay.buy_done", { label: tr.label, dur: t(DUR_KEY[duration]) }) : "❌ " + (r.body?.error || t("pay.buy_fail")));
    if (r.ok) load();
  }

  if (me === null) return <Shell hostName={hostName}><p>{t("pay.loading")}</p></Shell>;
  if (me === "offline")
    return (
      <Shell hostName={hostName}>
        <div className="empty">
          <p>{t("pay.offline")}</p>
          <button className="btn-primary sm" onClick={load} style={{ margin: "0 auto" }}>{t("pay.retry")}</button>
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
            {me.on_trial ? t("pay.on_trial") : `${me.tier_label} · ${me.plan_label}`}
          </div>
          <div className="bill-sub">
            {me.lifetime
              ? t("pay.lifetime_note")
              : me.active
                ? t("pay.days_left", { n: me.days_left, date: expDate })
                : (expDate ? t("pay.expired_from", { date: expDate }) : t("pay.expired"))}
          </div>
        </div>
        <div className="bill-wallet">
          <div className="bill-wallet-label">{t("pay.wallet")}</div>
          <div className="bill-wallet-num">{vnd(me.balance)}</div>
        </div>
      </div>

      {/* Thanh quota lượt AI tháng này */}
      <div className="quota-box">
        <div className="quota-head">
          <span>{t("pay.quota_title")}</span>
          <b>{me.ai_used.toLocaleString("vi-VN")} / {me.ai_quota.toLocaleString("vi-VN")}</b>
        </div>
        <div className="quota-track"><div className={"quota-fill" + (usePct >= 100 ? " full" : "")} style={{ width: usePct + "%" }} /></div>
        {me.ai_left === 0 && <div className="hint" style={{ color: "var(--danger)", marginTop: 6 }}>{t("pay.quota_out")}</div>}
      </div>

      {msg && <div className="savemsg" style={{ margin: "14px 0" }}>{msg}</div>}

      {/* Mô hình AI + tính theo usage khi hết quota */}
      <div className="panel set-card" style={{ margin: "16px 0" }}>
        <h3 style={{ fontSize: 16, marginBottom: 6 }}>{t("pay.ai_title")}</h3>
        <p className="hint">{t("pay.ai_hint")}</p>
        <div style={{ overflowX: "auto", marginTop: 8 }}>
          <table className="ad-table">
            <thead>
              <tr><th></th><th>{t("pay.tbl_model")}</th><th>{t("pay.tbl_in")}</th><th>{t("pay.tbl_out")}</th></tr>
            </thead>
            <tbody>
              {(me.ai_models || []).map((m) => {
                const cur = me.ai_model ? me.ai_model === m.key : m.default;
                return (
                  <tr key={m.key} className="adm-row"
                      style={{ opacity: m.available ? 1 : 0.45, fontWeight: cur ? 600 : 400 }}
                      title={m.available ? t("pay.ai_pick") : t("pay.ai_na")}
                      onClick={() => m.available && saveAiModel(m.key)}>
                    <td>{cur ? "✅" : "○"}</td>
                    <td>{m.label}{m.default && <span className="hint"> · {t("pay.ai_default")}</span>}</td>
                    <td>{vnd(m.in_vnd)}</td>
                    <td>{vnd(m.out_vnd)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <h3 style={{ fontSize: 16, margin: "18px 0 6px" }}>{t("pay.usage_title")}</h3>
        <p className="hint">{t("pay.usage_hint")}</p>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginTop: 8 }}>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontWeight: 600, fontSize: 14, cursor: "pointer" }}>
            <input type="checkbox" checked={usageOn} onChange={(e) => setUsageOn(e.target.checked)} />
            {t("pay.usage_on")}
          </label>
          <input type="number" min={0} step={10000} style={{ width: 150 }} value={usageLimit}
                 onChange={(e) => setUsageLimit(+e.target.value || 0)} disabled={!usageOn} />
          <span className="hint">{t("pay.usage_unit")}</span>
          <button className="btn-primary sm" onClick={saveUsage} disabled={aiBusy}>
            {aiBusy ? t("pay.saving") : t("pay.save")}
          </button>
        </div>
        {me.usage_enabled && (
          <div style={{ marginTop: 10 }}>
            <div className="quota-head" style={{ fontSize: 13.5 }}>
              <span>{t("pay.usage_spent")}</span>
              <b>{vnd(me.usage_spent)} / {vnd(me.usage_limit)}</b>
            </div>
            <div className="quota-track" style={{ marginTop: 4 }}>
              <div className={"quota-fill" + (me.usage_spent >= me.usage_limit ? " full" : "")}
                   style={{ width: Math.min(100, Math.round((me.usage_spent / Math.max(1, me.usage_limit)) * 100)) + "%" }} />
            </div>
            {me.usage_spent >= me.usage_limit && (
              <div className="hint" style={{ color: "var(--danger)", marginTop: 6 }}>
                {t("pay.usage_capped")}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Mã giới thiệu */}
      {me.on_trial && !me.promo_used && me.promo_enabled && (
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 6 }}>{t("pay.promo_title")}</h3>
          <p className="hint">{t("pay.promo_hint")}</p>
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input style={{ flex: 1 }} placeholder={t("pay.promo_ph")} value={promo}
                   onChange={(e) => setPromo(e.target.value)} />
            <button className="btn-primary sm" onClick={doRedeem} disabled={busy || !promo.trim()}>{t("pay.apply")}</button>
          </div>
        </div>
      )}

      {/* Bảng giá 3 hạng × chọn thời hạn */}
      <h3 className="bill-h">{t("pay.pick_plan")}</h3>
      <div className="dur-switch">
        {me.durations.map((d) => (
          <button key={d.key} className={"dur-btn" + (duration === d.key ? " active" : "")}
                  onClick={() => setDuration(d.key)}>{t(DUR_KEY[d.key])}</button>
        ))}
      </div>
      <div className="tier-grid">
        {me.tiers.map((p) => {
          const price = p.prices[duration];              // undefined = hạng này không bán thời hạn này
          const cur = me.tier === p.tier && !me.on_trial;
          return (
            <div key={p.tier} className={"tier-card" + (p.tier === "pro" ? " hot" : "") + (cur ? " current" : "") + (price === undefined ? " na" : "")}>
              {p.tier === "pro" && <div className="plan-badge">{t("pay.popular")}</div>}
              <div className="plan-ico">{TIER_ICON[p.tier]}</div>
              <div className="plan-name">{p.label}</div>
              <div className="plan-price">{price === undefined ? "—" : vnd(price)}</div>
              <div className="plan-days">{price === undefined ? t("pay.not_avail") : t(DUR_KEY[duration])}</div>
              <ul className="tier-feats">
                <li>{t("pay.feat_quota", { n: p.quota.toLocaleString("vi-VN") })}</li>
                <li>📡 {p.channels ? t("pay.feat_channels", { n: p.channels }) : t("pay.feat_channels_all")}</li>
                <li>🤖 {t("pay.feat_unlimited")}</li>
                <li className={p.call_owner ? "" : "off"}>{p.call_owner ? "✅" : "✖"} {t("pay.feat_call")}</li>
                <li className={p.adv_stats ? "" : "off"}>{p.adv_stats ? "✅" : "✖"} {t("pay.feat_stats")}</li>
              </ul>
              {price === undefined ? (
                <button className="btn-outline sm" disabled title={t("pay.pro_only_hint")}>{t("pay.pro_only")}</button>
              ) : cur && me.lifetime ? (
                <button className="btn-outline sm" disabled>{t("pay.lifetime_cur")}</button>
              ) : (
                <button className={"btn-primary sm" + (me.balance < price ? " plan-poor" : "")}
                        onClick={() => doBuy(p.tier)} disabled={busy || me.balance < price}
                        title={me.balance < price ? t("pay.poor_hint") : cur ? t("pay.extend_hint") : ""}>
                  {me.balance < price ? t("pay.poor") : cur ? t("pay.extend") : t("pay.choose")}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Nạp tiền */}
      <h3 className="bill-h">{t("pay.deposit_title")}</h3>
      <div className="panel set-card">
        {!me.bank.configured && (
          <p className="hint" style={{ color: "var(--danger)" }}>
            {t("pay.bank_cfg1")} <code>BANK_NAME / BANK_ACCOUNT / BANK_HOLDER</code> {t("pay.bank_cfg2")} <code>.env</code> {t("pay.bank_cfg3")}
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
            {busy ? t("pay.creating") : t("pay.create_deposit")}
          </button>
        </div>

        {newDep && (
          <div className="dep-guide">
            <h4>{t("pay.transfer_title")}</h4>
            <div className="dep-row"><span>{t("pay.bank")}</span><b>{me.bank.name || t("pay.bank_unset")}</b></div>
            <div className="dep-row"><span>{t("pay.account")}</span><b>{me.bank.account || "—"}</b></div>
            <div className="dep-row"><span>{t("pay.holder")}</span><b>{me.bank.holder || "—"}</b></div>
            <div className="dep-row"><span>{t("pay.amount")}</span><b>{vnd(newDep.amount)}</b></div>
            <div className="dep-row hl"><span>{t("pay.memo")}</span><b>{newDep.code}</b></div>
            {newDep.qr && (
              <div className="dep-qr">
                <img src={newDep.qr} alt="VietQR" loading="lazy" />
                <span className="hint">{t("pay.qr_hint")}</span>
              </div>
            )}
            <p className="hint">{t("pay.transfer_hint", { code: newDep.code })}</p>
          </div>
        )}

        {deps.length > 0 && (
          <table className="bill-table">
            <thead><tr><th>{t("pay.th_code")}</th><th>{t("pay.amount")}</th><th>{t("pay.th_status")}</th><th>{t("pay.th_time")}</th></tr></thead>
            <tbody>
              {deps.map((d) => (
                <tr key={d.id}>
                  <td><code>{d.code}</code></td><td>{vnd(d.amount)}</td>
                  <td>{ST_KEY[d.status] ? t(ST_KEY[d.status]) : d.status}</td>
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
          <h3 className="bill-h">{t("pay.history")}</h3>
          <div className="panel set-card">
            <table className="bill-table">
              <tbody>
                {history.map((h, i) => (
                  <tr key={i}>
                    <td>{h.note}</td>
                    <td style={{ color: h.amount >= 0 ? "var(--ok, #4f9d6b)" : "var(--danger)", fontWeight: 700 }}>
                      {h.amount > 0 ? "+" : ""}{h.amount !== 0 ? vnd(h.amount) : ""}
                    </td>
                    <td>{new Date(h.created_at).toLocaleString("vi-VN")}</td>
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
  const { t } = useI18n();
  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <LogoMark size={28} /> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title={t("pay.account_settings")}>
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
        </div>
      </header>
      <main className="content narrow" style={{ maxWidth: 820 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">{t("pay.pay_head")}</div>
            <h1 className="page-title">{t("nav.billing")}</h1>
          </div>
        </div>
        {children}
      </main>
    </div>
  );
}
