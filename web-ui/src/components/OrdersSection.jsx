import { useEffect, useState } from "react";
import { ordersApi, ORDER_STATUS, NEXT_STATUS, vnd } from "../ordersApi.js";
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
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>Huỷ</button>
          <button type="submit" className="btn-primary sm" disabled={busy}>{busy ? "Đang lưu…" : "💾 Lưu đơn"}</button>
        </div>
      </form>
    </div>
  );
}
