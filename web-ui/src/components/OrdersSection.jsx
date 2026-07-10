import { useEffect, useState } from "react";
import { ordersApi, ORDER_STATUS, NEXT_STATUS, vnd } from "../ordersApi.js";
import { loyaltyApi } from "../loyaltyApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";

/*
 * Sổ đơn hàng (mục "Đơn hàng" sidebar): bot tự tạo đơn nháp khi khách chốt
 * trong chat; chủ duyệt/đổi trạng thái 1 chạm; tới hạn hệ thống tự nhắc.
 */

// icon logo thương hiệu thật render qua <ChannelTile ch={key}/> (bỏ emoji)
const CH = {
  zalo:     { label: "Zalo",      color: "#0068ff" },
  meta:     { label: "Mess + IG", color: "#7b3fb3" },
  telegram: { label: "Telegram",  color: "#229ED9" },
  tiktok:   { label: "TikTok",    color: "#161823" },
  shopee:   { label: "Shopee",    color: "#EE4D2D" },
  zalooa:   { label: "Zalo OA",   color: "#005AE0" },
  webchat:  { label: "Website",   color: "#4F46E5" },
};
const TYPE_LABEL = { booking: "🏠 Đặt phòng/lịch", goods: "📦 Bán hàng" };

function dueBadge(o) {
  if (!o.due_at || ["done", "cancelled"].includes(o.status)) return null;
  const diff = (new Date(o.due_at) - Date.now()) / 3600000;
  if (diff < 0) return <span className="od-due late">⚠️ Quá hạn</span>;
  if (diff < 24) return <span className="od-due soon">⏰ Còn {Math.max(1, Math.round(diff))}h</span>;
  return null;
}
function fmtDue(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString("vi-VN", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export default function OrdersSection() {
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
    if (!confirm(`Huỷ đơn ${o.code}?`)) return;
    await ordersApi.update(o.id, { status: "cancelled" }); load();
  }
  async function removeOrder(o) {
    if (!confirm(`XOÁ HẲN đơn ${o.code} khỏi sổ? (thường chỉ nên Huỷ để còn lưu vết)`)) return;
    await ordersApi.remove(o.id); load();
  }

  const items = Array.isArray(data?.items) ? data.items : [];

  return (
    <div className="od">
      {/* Tóm tắt */}
      {sum && (
        <div className="od-sum">
          <div className="od-sum-card"><b>{sum.total}</b><span>Tổng đơn</span></div>
          <div className="od-sum-card"><b>{(sum.by_status.draft || 0) + (sum.by_status.awaiting_payment || 0)}</b><span>Chờ xử lý</span></div>
          <div className="od-sum-card ok"><b>{vnd(sum.revenue)}</b><span>Doanh thu (đã thanh toán)</span></div>
        </div>
      )}

      {/* Mã giảm giá */}
      <VoucherCard />

      {/* Filter + tạo */}
      <div className="od-bar">
        <div className="od-tabs">
          <button className={"od-tab" + (status === "" ? " active" : "")} onClick={() => setStatus("")}>Tất cả</button>
          {Object.entries(ORDER_STATUS).map(([k, v]) => (
            <button key={k} className={"od-tab" + (status === k ? " active" : "")}
                    style={{ "--c": v.color }} onClick={() => setStatus(k)}>
              {v.label}{sum ? ` ${sum.by_status[k] || 0}` : ""}
            </button>
          ))}
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input className="od-search" placeholder="🔍 Mã đơn / tên / SĐT…" value={q}
                 onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()} />
          <button className="btn-primary sm" onClick={() => setEditing("new")}>＋ Tạo đơn</button>
        </div>
      </div>

      <p className="cb-hint">
        Khách <b>chốt đơn trong chat</b> là bot tự tạo <b>đơn nháp</b> ở đây (kèm báo cho bạn).
        Bấm nút trạng thái để chuyển bước tiếp theo — tới ngày hẹn/gửi hàng hệ thống tự nhắc.
      </p>

      {/* Bảng đơn */}
      {data === null && <p className="hint">Đang tải sổ đơn…</p>}
      {data === "offline" && (
        <div className="empty"><p>⚠️ Chưa kết nối được máy chủ (5005) — hoặc server chưa restart bản mới.</p></div>
      )}
      {Array.isArray(data?.items) && items.length === 0 && (
        <div className="empty" style={{ padding: 30 }}>
          <p>Chưa có đơn nào{status ? " ở trạng thái này" : ""}. Khách chốt trong chat là đơn tự xuất hiện.</p>
        </div>
      )}

      {items.map((o) => {
        const st = ORDER_STATUS[o.status] || ORDER_STATUS.draft;
        const ch = CH[o.channel];
        const next = NEXT_STATUS[o.status];
        return (
          <div key={o.id} className="od-row">
            <div className="od-main">
              <div className="od-l1">
                <b className="od-code">{o.code}</b>
                <span className="od-status" style={{ "--c": st.color }}>{st.label}</span>
                {ch && <span className="ch-chip" style={{ "--c": ch.color }}>
                  <ChannelTile ch={o.channel} size={13} /> {ch.label}
                </span>}
                <span className="od-type">{TYPE_LABEL[o.order_type] || o.order_type}</span>
                {dueBadge(o)}
              </div>
              <div className="od-l2">
                <span>👤 {o.customer_name || o.user_id || "—"}</span>
                {o.phone && <span>📞 {o.phone}</span>}
                <span>🗓 {fmtDue(o.due_at)}</span>
                {o.voucher_code && (
                  <span className="od-voucher" title={`Đã giảm ${vnd(o.discount)}`}>
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
                        title="Chuyển sang bước tiếp theo">
                  → {ORDER_STATUS[next].label}
                </button>
              )}
              <button className="btn-mini" onClick={() => setEditing(o)}>Sửa</button>
              {!["done", "cancelled"].includes(o.status) && (
                <button className="btn-mini danger" onClick={() => cancelOrder(o)}>Huỷ</button>
              )}
              {["done", "cancelled"].includes(o.status) && (
                <button className="btn-mini danger" onClick={() => removeOrder(o)}>Xoá</button>
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
    if (r.ok) { setMsg("✅ Đã tạo mã " + r.body.voucher.code); setF({ code: "", kind: "amount", value: "", min_total: "", max_uses: "", expires_at: "" }); load(); }
    else setMsg("❌ " + (r.body?.error || "Tạo mã thất bại"));
  }
  async function toggle(v) { await loyaltyApi.updateVoucher(v.id, { active: v.active ? 0 : 1 }); load(); }
  async function del(v) {
    if (!confirm(`Xoá mã ${v.code}?`)) return;
    await loyaltyApi.deleteVoucher(v.id); load();
  }

  return (
    <div className="panel vc-card">
      <div className="vc-head" onClick={() => setOpen((o) => !o)}>
        <b>🎟️ Mã giảm giá</b>
        <span className="hint">Tạo mã khuyến mãi, áp vào đơn khi chốt · đơn hoàn tất tự cộng ⭐ điểm cho khách (10.000đ = 1 điểm)</span>
        <span className="btn-mini">{open ? "Thu gọn ▲" : "Mở ▼"}</span>
      </div>
      {open && (
        <div className="vc-body">
          <form className="vc-form" onSubmit={create}>
            <input style={{ width: 130 }} placeholder="MÃ (GIAM50K)" value={f.code}
                   onChange={(e) => setF((s) => ({ ...s, code: e.target.value.toUpperCase() }))} required />
            <select value={f.kind} onChange={set("kind")} style={{ width: "auto" }}>
              <option value="amount">Giảm thẳng (đ)</option>
              <option value="percent">Giảm %</option>
            </select>
            <input style={{ width: 110 }} placeholder={f.kind === "percent" ? "% (VD 10)" : "đ (VD 50000)"}
                   value={f.value} onChange={set("value")} required />
            <input style={{ width: 130 }} placeholder="Đơn tối thiểu (đ)" value={f.min_total} onChange={set("min_total")} />
            <input style={{ width: 100 }} placeholder="Số lượt (0=∞)" value={f.max_uses} onChange={set("max_uses")} />
            <input type="date" style={{ width: 140 }} title="Hạn dùng (bỏ trống = không hạn)"
                   value={f.expires_at} onChange={set("expires_at")} />
            <button className="btn-primary sm" type="submit" disabled={busy}>{busy ? "…" : "＋ Tạo mã"}</button>
          </form>
          {msg && <div className="savemsg">{msg}</div>}
          {list === null ? <p className="hint">Đang tải…</p>
            : list.length === 0 ? <p className="hint">Chưa có mã nào — tạo mã đầu tiên ở trên.</p>
            : (
              <div className="vc-list">
                {list.map((v) => (
                  <div key={v.id} className={"vc-row" + (v.active ? "" : " off")}>
                    <b className="vc-code">{v.code}</b>
                    <span>{v.kind === "percent" ? `−${v.value}%` : `−${vnd(v.value)}`}</span>
                    <span className="hint">{v.min_total ? `đơn ≥ ${vnd(v.min_total)}` : "mọi đơn"}</span>
                    <span className="hint">dùng {v.used}{v.max_uses ? `/${v.max_uses}` : ""}</span>
                    <span className="hint">{v.expires_at ? `hạn ${String(v.expires_at).slice(0, 10)}` : "không hạn"}</span>
                    <button className={"tggl sm" + (v.active ? " on" : "")} title={v.active ? "Đang bật — bấm để tắt" : "Đang tắt — bấm để bật"}
                            onClick={() => toggle(v)} />
                    <button className="btn-mini danger" onClick={() => del(v)}>Xoá</button>
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
    else alert("❌ " + (r.body?.error || "Lưu thất bại"));
  }

  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal od-modal" onClick={(e) => e.stopPropagation()} onSubmit={save}>
        <h3>{order ? `Sửa đơn ${order.code}` : "Tạo đơn mới"}</h3>
        <div className="od-form-2col">
          <div><label>Tên khách</label><input value={f.customer_name} onChange={set("customer_name")} /></div>
          <div><label>SĐT</label><input value={f.phone} onChange={set("phone")} /></div>
        </div>
        <div className="od-form-2col">
          <div>
            <label>Loại đơn</label>
            <select value={f.order_type} onChange={set("order_type")}>
              <option value="booking">🏠 Đặt phòng / lịch hẹn</option>
              <option value="goods">📦 Bán hàng (gửi đi)</option>
            </select>
          </div>
          <div>
            <label>Trạng thái</label>
            <select value={f.status} onChange={set("status")}>
              {Object.entries(ORDER_STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
        </div>
        <label>Mặt hàng / dịch vụ <span className="hint" style={{ fontWeight: 400 }}>(mỗi dòng: Tên x2 = 500000)</span></label>
        <textarea rows={3} value={f.itemsText} onChange={set("itemsText")}
                  placeholder={"Phòng 301 ca qua đêm x1 = 380000\nVáy hoa nhí size M x2 = 500000"} />
        <div className="od-form-2col">
          <div><label>Tổng tiền (VND)</label><input value={f.total} onChange={set("total")} /></div>
          <div><label>Hạn (checkin / gửi hàng)</label>
            <input type="datetime-local" value={f.due_at} onChange={set("due_at")} /></div>
        </div>
        <label>Ghi chú</label>
        <input value={f.note} onChange={set("note")} placeholder="Ca chiều · khách xin checkin sớm…" />
        {order && <VoucherApply order={order} onApplied={onSaved} />}
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Huỷ</button>
          <button type="submit" className="btn-primary sm" disabled={busy}>{busy ? "Đang lưu…" : "💾 Lưu đơn"}</button>
        </div>
      </form>
    </div>
  );
}

/* ── Áp mã giảm giá vào đơn (trong modal sửa đơn) ── */
function VoucherApply({ order, onApplied }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  if (order.voucher_code) {
    return <p className="hint" style={{ marginTop: 8 }}>
      🎟️ Đơn đã áp mã <b>{order.voucher_code}</b> (giảm {vnd(order.discount)}).</p>;
  }
  if (!["draft", "awaiting_payment"].includes(order.status)) return null;

  async function apply() {
    if (!code.trim() || busy) return;
    setBusy(true); setMsg("");
    const r = await loyaltyApi.applyToOrder(order.id, code.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) { setMsg("✅ Đã áp mã — tổng tiền mới " + vnd(r.body.order.total)); onApplied(); }
    else setMsg("❌ " + (r.body?.error || "Áp mã thất bại"));
  }

  return (
    <div style={{ marginTop: 8 }}>
      <label>🎟️ Mã giảm giá</label>
      <div style={{ display: "flex", gap: 6 }}>
        <input style={{ flex: 1 }} placeholder="VD: GIAM50K" value={code}
               onChange={(e) => setCode(e.target.value.toUpperCase())} />
        <button type="button" className="btn-mini" onClick={apply} disabled={busy || !code.trim()}>
          {busy ? "…" : "Áp mã"}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 4 }}>{msg}</div>}
    </div>
  );
}
