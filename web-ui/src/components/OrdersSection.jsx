import { useEffect, useState } from "react";
import { ordersApi, ORDER_STATUS, NEXT_STATUS, vnd } from "../ordersApi.js";
import { loyaltyApi } from "../loyaltyApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

/*
 * Sổ đơn hàng (mục "Đơn hàng" sidebar): bot tự tạo đơn nháp khi khách chốt
 * trong chat; chủ duyệt/đổi trạng thái 1 chạm; tới hạn hệ thống tự nhắc.
 * Label kênh/loại đơn/trạng thái: key i18n "ord.*" (i18n/campaigns.js).
 */

// icon logo thương hiệu thật render qua <ChannelTile ch={key}/> (bỏ emoji)
const CH_COLOR = {
  zalo:     "#0068ff",
  meta:     "#7b3fb3",
  telegram: "#229ED9",
  tiktok:   "#161823",
  shopee:   "#EE4D2D",
  zalooa:   "#005AE0",
  webchat:  "#4F46E5",
};
const TYPE_KEYS = ["booking", "goods"];

// label trạng thái đơn — key backend (draft/paid…) giữ nguyên, chỉ dịch label
function stLabel(t, k) {
  return ORDER_STATUS[k] ? t("ord.st." + k) : k;
}

function dueBadge(o, t) {
  if (!o.due_at || ["done", "cancelled"].includes(o.status)) return null;
  const diff = (new Date(o.due_at) - Date.now()) / 3600000;
  if (diff < 0) return <span className="od-due late">{t("ord.due_late")}</span>;
  if (diff < 24) return <span className="od-due soon">{t("ord.due_soon", { h: Math.max(1, Math.round(diff)) })}</span>;
  return null;
}
function fmtDue(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function OrdersSection() {
  const { t } = useI18n();
  const [data, setData] = useState(null);       // null | {total, items} | "offline"
  const [sum, setSum] = useState(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState(null); // order đang sửa | "new"
  const [busy, setBusy] = useState(false);

  async function load() {
    const [r, s] = await Promise.all([
      ordersApi.list({ status, q }),
      ordersApi.summary(),
    ]);
    setData(r.ok && r.body ? r.body : "offline");
    if (s.ok && s.body) setSum(s.body);
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [status]);

  async function quickNext(o) {
    const next = NEXT_STATUS[o.status];
    if (!next) return;
    setBusy(true);
    await ordersApi.update(o.id, { status: next });
    setBusy(false); load();
  }
  async function cancelOrder(o) {
    if (!confirm(t("ord.cancel_confirm", { code: o.code }))) return;
    await ordersApi.update(o.id, { status: "cancelled" }); load();
  }
  async function removeOrder(o) {
    if (!confirm(t("ord.delete_confirm", { code: o.code }))) return;
    await ordersApi.remove(o.id); load();
  }

  const items = Array.isArray(data?.items) ? data.items : [];

  return (
    <div className="od">
      {/* Tóm tắt */}
      {sum && (
        <div className="od-sum">
          <div className="od-sum-card"><b>{sum.total}</b><span>{t("ord.sum_total")}</span></div>
          <div className="od-sum-card"><b>{(sum.by_status.draft || 0) + (sum.by_status.awaiting_payment || 0)}</b><span>{t("ord.sum_pending")}</span></div>
          <div className="od-sum-card ok"><b>{vnd(sum.revenue)}</b><span>{t("ord.sum_revenue")}</span></div>
        </div>
      )}

      {/* Mã giảm giá */}
      <VoucherCard />

      {/* Filter + tạo */}
      <div className="od-bar">
        <div className="od-tabs">
          <button className={"od-tab" + (status === "" ? " active" : "")} onClick={() => setStatus("")}>{t("ord.all")}</button>
          {Object.entries(ORDER_STATUS).map(([k, v]) => (
            <button key={k} className={"od-tab" + (status === k ? " active" : "")}
                    style={{ "--c": v.color }} onClick={() => setStatus(k)}>
              {stLabel(t, k)}{sum ? ` ${sum.by_status[k] || 0}` : ""}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="od-search" placeholder={t("ord.search_ph")} value={q}
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()} />
          <button className="btn-primary sm" onClick={() => setEditing("new")}>{t("ord.new_btn")}</button>
        </div>
      </div>

      <p className="cb-hint">
        {t("ord.hint_1")}<b>{t("ord.hint_2")}</b>{t("ord.hint_3")}<b>{t("ord.hint_4")}</b>{t("ord.hint_5")}
      </p>

      {/* Bảng đơn */}
      {data === null && <p className="hint">{t("ord.loading")}</p>}
      {data === "offline" && (
        <div className="empty"><p>{t("ord.offline")}</p></div>
      )}
      {Array.isArray(data?.items) && items.length === 0 && (
        <div className="empty" style={{ padding: 30 }}>
          <p>{t("ord.empty", { filter: status ? t("ord.empty_filter") : "" })}</p>
        </div>
      )}

      {items.map((o) => {
        const st = ORDER_STATUS[o.status] || ORDER_STATUS.draft;
        const stKey = ORDER_STATUS[o.status] ? o.status : "draft";
        const chColor = CH_COLOR[o.channel];
        const next = NEXT_STATUS[o.status];
        return (
          <div key={o.id} className="od-row">
            <div className="od-main">
              <div className="od-l1">
                <b className="od-code">{o.code}</b>
                <span className="od-status" style={{ "--c": st.color }}>{t("ord.st." + stKey)}</span>
                {chColor && <span className="ch-chip" style={{ "--c": chColor }}>
                  <ChannelTile ch={o.channel} size={13} /> {t("ord.ch." + o.channel)}
                </span>}
                <span className="od-type">{TYPE_KEYS.includes(o.order_type) ? t("ord.type." + o.order_type) : o.order_type}</span>
                {dueBadge(o, t)}
              </div>
              <div className="od-l2">
                <span>👤 {o.customer_name || o.user_id || "—"}</span>
                {o.phone && <span>📞 {o.phone}</span>}
                <span>🗓 {fmtDue(o.due_at)}</span>
                {o.voucher_code && (
                  <span className="od-voucher" title={t("ord.discounted", { v: vnd(o.discount) })}>
                    🎟️ {o.voucher_code} −{vnd(o.discount)}</span>
                )}
                <b className="od-total">{vnd(o.total)}</b>
              </div>
              {o.items?.length > 0 && (
                <div className="od-items">
                  🧾 {o.items.map((i) => `${i.name} x${i.qty ?? 1}`).join(" · ")}
                </div>
              )}
              {o.note && <div className="od-note">📝 {o.note}</div>}
            </div>
            <div className="od-actions">
              {next && (
                <button className="btn-primary sm" disabled={busy} onClick={() => quickNext(o)}
                        title={t("ord.next_title")}>
                  → {stLabel(t, next)}
                </button>
              )}
              <button className="btn-mini" onClick={() => setEditing(o)}>{t("ord.edit")}</button>
              {!["done", "cancelled"].includes(o.status) && (
                <button className="btn-mini danger" onClick={() => cancelOrder(o)}>{t("ord.cancel")}</button>
              )}
              {["done", "cancelled"].includes(o.status) && (
                <button className="btn-mini danger" onClick={() => removeOrder(o)}>{t("team.del")}</button>
              )}
            </div>
          </div>
        );
      })}

      {editing && (
        <OrderModal
          order={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); load(); }}
        />
      )}
    </div>
  );
}

/* ── Card quản lý mã giảm giá (loyalty) ── */
function VoucherCard() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [list, setList] = useState(null);
  const [f, setF] = useState({ code: "", kind: "amount", value: "", min_total: "", max_uses: "", expires_at: "" });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  async function load() {
    const r = await loyaltyApi.vouchers();
    setList(r.ok && Array.isArray(r.body) ? r.body : []);
  }
  useEffect(() => { if (open && list === null) load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [open]);

  async function create(e) {
    e.preventDefault();
    if (busy) return;
    setBusy(true); setMsg("");
    const r = await loyaltyApi.createVoucher({
      code: f.code, kind: f.kind,
      value: parseInt(String(f.value).replace(/[.,]/g, ""), 10) || 0,
      min_total: parseInt(String(f.min_total).replace(/[.,]/g, ""), 10) || 0,
      max_uses: parseInt(f.max_uses, 10) || 0,
      expires_at: f.expires_at || null,
    });
    setBusy(false);
    if (r.ok) { setMsg(t("ord.vc_created", { code: r.body.voucher.code })); setF({ code: "", kind: "amount", value: "", min_total: "", max_uses: "", expires_at: "" }); load(); }
    else setMsg("❌ " + (r.body?.error || t("ord.vc_create_fail")));
  }
  async function toggle(v) { await loyaltyApi.updateVoucher(v.id, { active: v.active ? 0 : 1 }); load(); }
  async function del(v) {
    if (!confirm(t("ord.vc_del_confirm", { code: v.code }))) return;
    await loyaltyApi.deleteVoucher(v.id); load();
  }

  return (
    <div className="panel vc-card">
      <div className="vc-head" onClick={() => setOpen((o) => !o)}>
        <b>{t("ord.vc_title")}</b>
        <span className="hint">{t("ord.vc_desc")}</span>
        <span className="btn-mini">{open ? t("ord.vc_collapse") : t("ord.vc_open")}</span>
      </div>
      {open && (
        <div className="vc-body">
          <form className="vc-form" onSubmit={create}>
            <input style={{ width: 130 }} placeholder={t("ord.vc_code_ph")} value={f.code}
                   onChange={(e) => setF((s) => ({ ...s, code: e.target.value.toUpperCase() }))} required />
            <select value={f.kind} onChange={set("kind")} style={{ width: "auto" }}>
              <option value="amount">{t("ord.vc_amount")}</option>
              <option value="percent">{t("ord.vc_percent")}</option>
            </select>
            <input style={{ width: 110 }} placeholder={f.kind === "percent" ? t("ord.vc_val_pct_ph") : t("ord.vc_val_amt_ph")}
                   value={f.value} onChange={set("value")} required />
            <input style={{ width: 130 }} placeholder={t("ord.vc_min_ph")} value={f.min_total} onChange={set("min_total")} />
            <input style={{ width: 100 }} placeholder={t("ord.vc_uses_ph")} value={f.max_uses} onChange={set("max_uses")} />
            <input type="date" style={{ width: 140 }} title={t("ord.vc_exp_title")}
                   value={f.expires_at} onChange={set("expires_at")} />
            <button className="btn-primary sm" type="submit" disabled={busy}>{busy ? "…" : t("ord.vc_create")}</button>
          </form>
          {msg && <div className="savemsg">{msg}</div>}
          {list === null ? <p className="hint">{t("team.loading")}</p>
            : list.length === 0 ? <p className="hint">{t("ord.vc_none")}</p>
            : (
              <div className="vc-list">
                {list.map((v) => (
                  <div key={v.id} className={"vc-row" + (v.active ? "" : " off")}>
                    <b className="vc-code">{v.code}</b>
                    <span>{v.kind === "percent" ? `−${v.value}%` : `−${vnd(v.value)}`}</span>
                    <span className="hint">{v.min_total ? t("ord.vc_min", { v: vnd(v.min_total) }) : t("ord.vc_any")}</span>
                    <span className="hint">{t("ord.vc_used", { n: `${v.used}${v.max_uses ? `/${v.max_uses}` : ""}` })}</span>
                    <span className="hint">{v.expires_at ? t("ord.vc_exp", { d: String(v.expires_at).slice(0, 10) }) : t("ord.vc_noexp")}</span>
                    <button className={"tggl sm" + (v.active ? " on" : "")} title={v.active ? t("ord.vc_on_title") : t("ord.vc_off_title")}
                            onClick={() => toggle(v)} />
                    <button className="btn-mini danger" onClick={() => del(v)}>{t("team.del")}</button>
                  </div>
                ))}
              </div>
            )}
        </div>
      )}
    </div>
  );
}

/* ── Modal tạo/sửa đơn tay ── */
function OrderModal({ order, onClose, onSaved }) {
  const { t } = useI18n();
  const [f, setF] = useState(() => order ? {
    customer_name: order.customer_name, phone: order.phone,
    order_type: order.order_type, total: order.total,
    due_at: order.due_at ? order.due_at.slice(0, 16) : "",
    note: order.note,
    itemsText: (order.items || []).map((i) => `${i.name} x${i.qty ?? 1}${i.price ? ` = ${i.price}` : ""}`).join("\n"),
    channel: order.channel, status: order.status,
  } : {
    customer_name: "", phone: "", order_type: "booking", total: 0,
    due_at: "", note: "", itemsText: "", channel: "", status: "draft",
  });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF((s) => ({ ...s, [k]: e.target.value }));

  // "Tên x2 = 500000" mỗi dòng → items JSON
  function parseItems(text) {
    return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const m = l.match(/^(.*?)(?:\s+x(\d+))?(?:\s*=\s*([\d.,]+))?$/i);
      return {
        name: (m?.[1] || l).trim(),
        qty: parseInt(m?.[2] || "1", 10) || 1,
        price: parseInt(String(m?.[3] || "0").replace(/[.,]/g, ""), 10) || 0,
      };
    });
  }

  async function save(e) {
    e.preventDefault();
    setBusy(true);
    const payload = {
      customer_name: f.customer_name, phone: f.phone, order_type: f.order_type,
      total: parseInt(String(f.total).replace(/[.,]/g, ""), 10) || 0,
      due_at: f.due_at || null, note: f.note, channel: f.channel,
      items: parseItems(f.itemsText), status: f.status,
    };
    const r = order ? await ordersApi.update(order.id, payload) : await ordersApi.create(payload);
    setBusy(false);
    if (r.ok) onSaved();
    else alert("❌ " + (r.body?.error || t("ord.m_save_fail")));
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal od-modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h3>{order ? t("ord.m_edit", { code: order.code }) : t("ord.m_new")}</h3>
        <div className="od-form-2col">
          <div><label>{t("ord.m_name")}</label><input value={f.customer_name} onChange={set("customer_name")} /></div>
          <div><label>{t("ord.m_phone")}</label><input value={f.phone} onChange={set("phone")} /></div>
        </div>
        <div className="od-form-2col">
          <div>
            <label>{t("ord.m_type")}</label>
            <select value={f.order_type} onChange={set("order_type")}>
              <option value="booking">{t("ord.m_type_booking")}</option>
              <option value="goods">{t("ord.m_type_goods")}</option>
            </select>
          </div>
          <div>
            <label>{t("ord.m_status")}</label>
            <select value={f.status} onChange={set("status")}>
              {Object.keys(ORDER_STATUS).map((k) => <option key={k} value={k}>{stLabel(t, k)}</option>)}
            </select>
          </div>
        </div>
        <label>{t("ord.m_items")} <span className="hint" style={{ fontWeight: 400 }}>{t("ord.m_items_hint")}</span></label>
        <textarea rows={3} value={f.itemsText} onChange={set("itemsText")}
                  placeholder={t("ord.m_items_ph")} />
        <div className="od-form-2col">
          <div><label>{t("ord.m_total")}</label><input value={f.total} onChange={set("total")} /></div>
          <div><label>{t("ord.m_due")}</label>
            <input type="datetime-local" value={f.due_at} onChange={set("due_at")} /></div>
        </div>
        <label>{t("ord.m_note")}</label>
        <input value={f.note} onChange={set("note")} placeholder={t("ord.m_note_ph")} />
        {order && <VoucherApply order={order} onApplied={onSaved} />}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>{t("ord.cancel")}</button>
          <button type="submit" className="btn-primary sm" disabled={busy}>{busy ? t("ord.m_saving") : t("ord.m_save")}</button>
        </div>
      </form>
    </div>
  );
}

/* ── Áp mã giảm giá vào đơn (trong modal sửa đơn) ── */
function VoucherApply({ order, onApplied }) {
  const { t } = useI18n();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  if (order.voucher_code) {
    return <p className="hint" style={{ marginTop: 8 }}>
      {t("ord.va_applied_1")}<b>{order.voucher_code}</b>{t("ord.va_applied_2", { v: vnd(order.discount) })}</p>;
  }
  if (!["draft", "awaiting_payment"].includes(order.status)) return null;

  async function apply() {
    if (!code.trim() || busy) return;
    setBusy(true); setMsg("");
    const r = await loyaltyApi.applyToOrder(order.id, code.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) { setMsg(t("ord.va_ok", { v: vnd(r.body.order.total) })); onApplied(); }
    else setMsg("❌ " + (r.body?.error || t("ord.va_fail")));
  }

  return (
    <div style={{ marginTop: 8 }}>
      <label>{t("ord.vc_title")}</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input style={{ flex: 1 }} placeholder={t("ord.va_ph")} value={code}
               onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <button type="button" className="btn-mini" onClick={apply} disabled={busy || !code.trim()}>
          {busy ? "…" : t("ord.va_btn")}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 4 }}>{msg}</div>}
    </div>
  );
}
