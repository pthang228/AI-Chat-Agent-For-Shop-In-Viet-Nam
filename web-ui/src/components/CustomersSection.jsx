import { useEffect, useMemo, useState } from "react";
import { customersApi } from "../customersApi.js";
import { CH_HOST } from "../apiConfig.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { vnd } from "../ordersApi.js";

/*
 * CRM Khách hàng (kiểu AloChat): gộp khách từ MỌI kênh, bảng danh sách + drawer
 * chi tiết 5 tab: Thông tin (sửa hồ sơ) / Hội thoại / Đơn hàng / AI ghi nhớ /
 * Lịch sử thay đổi. Nút "Quét lịch sử lấy SĐT/Email" (regex, 0 tốn AI) và
 * "AI quét ghi nhớ" (AI bóc facts về khách → bot cá nhân hoá).
 */

const PLATFORMS = [
  ["", "Tất cả nền tảng"], ["zalo", "Zalo"], ["zalooa", "Zalo OA"], ["meta", "Mess + IG"],
  ["telegram", "Telegram"], ["tiktok", "TikTok"], ["shopee", "Shopee"], ["webchat", "Website"],
];
const SALUTATIONS = ["", "anh", "chị", "em", "bạn", "cô", "chú", "quý khách"];
const FIELD_LABELS = {
  name: "Tên", salutation: "Cách xưng hô", phone: "Số điện thoại",
  email: "Email", address: "Địa chỉ", note: "Ghi chú",
};

function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }
function relTime(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}
// Avatar tương đối ("/tg/avatar/x.jpg") → prefix host server kênh đó; URL đầy đủ dùng thẳng
function avatarSrc(c) {
  const a = c?.avatar || "";
  if (!a) return "";
  return a.startsWith("http") ? a : (CH_HOST[c.platform] || "") + a;
}
function Avatar({ c, size = 36 }) {
  const src = avatarSrc(c);
  return (
    <div className="inbox-av" style={{ width: size, height: size, fontSize: size * .4, background: "#7C3AED" }}>
      {initials(c.name || c.user_id)}
      {src && <img src={src} alt="" loading="lazy" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
    </div>
  );
}

export default function CustomersSection() {
  const [data, setData] = useState(null);      // null=tải | {total, items} | "offline"
  const [q, setQ] = useState("");
  const [platform, setPlatform] = useState("");
  const [sel, setSel] = useState(null);        // {account, user_id} đang mở drawer

  async function load() {
    const r = await customersApi.list({ q, platform });
    setData(r.ok && r.body ? r.body : "offline");
  }
  useEffect(() => {
    const t = setTimeout(load, q ? 300 : 0);   // debounce khi gõ tìm kiếm
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, platform]);

  if (data === null) return <div className="empty"><p>Đang tải danh sách khách…</p></div>;
  if (data === "offline")
    return <div className="empty"><p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p></div>;

  return (
    <div className="cu">
      <div className="cu-toolbar">
        <input className="inbox-search" style={{ maxWidth: 320 }}
               placeholder="🔍 Tìm theo tên, SĐT, email, địa chỉ…"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={platform} onChange={(e) => setPlatform(e.target.value)} style={{ width: "auto" }}>
          {PLATFORMS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <span className="hint" style={{ marginLeft: "auto" }}>{data.total} khách hàng</span>
      </div>

      {data.items.length === 0 ? (
        <div className="empty"><p>Chưa có khách nào{q ? " khớp tìm kiếm" : " nhắn tin"}.</p></div>
      ) : (
        <div className="cu-table panel">
          <div className="cu-row cu-head">
            <span>Khách</span><span>Nền tảng</span><span>SĐT</span>
            <span>Email</span><span>Địa chỉ</span><span>Hoạt động</span>
          </div>
          {data.items.map((c) => (
            <div key={c.account + c.user_id} className="cu-row"
                 onClick={() => setSel({ account: c.account, user_id: c.user_id })}>
              <span className="cu-name"><Avatar c={c} size={32} />
                <b>{c.name || `Khách …${String(c.user_id).slice(-6)}`}</b></span>
              <span><span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                <ChannelTile ch={c.platform} size={13} /> {c.platform}</span></span>
              <span>{c.phone || "–"}</span>
              <span className="cu-ellip">{c.email || "–"}</span>
              <span className="cu-ellip">{c.address || "–"}</span>
              <span className="hint">{relTime(c.last_updated)}</span>
            </div>
          ))}
        </div>
      )}

      {sel && <CustomerDrawer account={sel.account} userId={sel.user_id}
                              onClose={() => { setSel(null); load(); }} />}
    </div>
  );
}

/* ── Drawer chi tiết khách ── */
function CustomerDrawer({ account, userId, onClose }) {
  const [c, setC] = useState(null);
  const [tab, setTab] = useState("info");
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await customersApi.get(account, userId);
    setC(r.ok && r.body?.ok ? r.body : "err");
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [account, userId]);

  async function doScan() {
    setMsg("⏳ Đang quét hội thoại…");
    const r = await customersApi.scan(account, userId);
    if (r.ok) {
      const { phones, emails, updated } = r.body;
      setMsg(phones.length || emails.length
        ? `✅ Tìm thấy ${phones.length} SĐT, ${emails.length} email${updated ? " — đã điền vào hồ sơ." : "."}`
        : "Không tìm thấy SĐT/email trong hội thoại.");
      load();
    } else setMsg("❌ Quét thất bại.");
  }

  return (
    <div className="cu-drawer-bg" onClick={onClose}>
      <div className="cu-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="cu-drawer-head">
          <h3>Chi tiết khách hàng</h3>
          <button className="cs-pclose" onClick={onClose}>✕</button>
        </div>
        {c === null ? <p className="hint" style={{ padding: 20 }}>Đang tải…</p>
          : c === "err" ? <p className="hint" style={{ padding: 20 }}>⚠️ Không tải được khách này.</p>
          : (
            <>
              <div className="cu-hero">
                <Avatar c={c} size={52} />
                <div>
                  <b style={{ fontSize: 17 }}>{c.name || `Khách …${String(c.user_id).slice(-6)}`}</b>
                  <div><span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                    <ChannelTile ch={c.platform} size={13} /> {c.platform}</span></div>
                </div>
              </div>
              <div className="cu-stats">
                <div><b>{c.conversation_count}</b><span>Hội thoại</span></div>
                <div><b>{c.order_count}</b><span>Đơn hàng</span></div>
                <div><b>{vnd(c.order_value)}</b><span>Đã thanh toán</span></div>
              </div>
              <button className="btn-outline cu-scan" onClick={doScan}>
                🔎 Quét lịch sử lấy SĐT/Email
              </button>
              {msg && <div className="savemsg" style={{ margin: "6px 16px" }}>{msg}</div>}

              <div className="tabs cu-tabs">
                {[["info", "Thông tin"], ["conv", "Hội thoại"], ["orders", "Đơn hàng"],
                  ["memory", "AI ghi nhớ"], ["history", "Lịch sử"]].map(([k, l]) => (
                  <button key={k} className={"tab" + (tab === k ? " active" : "")}
                          onClick={() => setTab(k)}>{l}</button>
                ))}
              </div>
              <div className="cu-tab-body">
                {/* key theo giá trị profile: sau scan/save (c đổi) InfoTab remount →
                    form lấy giá trị MỚI, không giữ state cũ rỗng ghi đè SĐT vừa quét */}
                {tab === "info" && <InfoTab
                  key={`${c.name}|${c.salutation}|${c.phone}|${c.email}|${c.address}|${c.note}`}
                  c={c} account={account} userId={userId} onSaved={load} />}
                {tab === "conv" && <ConvTab c={c} />}
                {tab === "orders" && <OrdersTab account={account} userId={userId} />}
                {tab === "memory" && <MemoryTab c={c} account={account} userId={userId} onChanged={load} />}
                {tab === "history" && <HistoryTab c={c} />}
              </div>
            </>
          )}
      </div>
    </div>
  );
}

function InfoTab({ c, account, userId, onSaved }) {
  const [f, setF] = useState({
    name: c.name || "", salutation: c.salutation || "", phone: c.phone || "",
    email: c.email || "", address: c.address || "", note: c.note || "",
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k, v) => setF((cur) => ({ ...cur, [k]: v }));

  async function save() {
    if (busy) return;
    setBusy(true); setMsg("");
    const r = await customersApi.update(account, userId, f);
    setBusy(false);
    setMsg(r.ok ? "✅ Đã lưu hồ sơ." : "❌ Lưu thất bại.");
    if (r.ok) onSaved();
  }

  return (
    <div className="cu-form">
      <label>Tên khách hàng
        <input value={f.name} placeholder={c.channel_name || "Tên hiển thị"}
               onChange={(e) => set("name", e.target.value)} />
      </label>
      <label>Cách xưng hô (bot dùng khi chào khách)
        <select value={f.salutation} onChange={(e) => set("salutation", e.target.value)}>
          {SALUTATIONS.map((s) => <option key={s} value={s}>{s || "Chưa xác định"}</option>)}
        </select>
      </label>
      <label>Số điện thoại
        <input value={f.phone} placeholder="VD: 0912345678" onChange={(e) => set("phone", e.target.value)} />
      </label>
      <label>Email
        <input value={f.email} placeholder="VD: khach@gmail.com" onChange={(e) => set("email", e.target.value)} />
      </label>
      <label>Địa chỉ
        <input value={f.address} placeholder="Địa chỉ giao hàng / liên hệ" onChange={(e) => set("address", e.target.value)} />
      </label>
      <label>Ghi chú
        <textarea rows={3} value={f.note} placeholder="Ghi chú về khách hàng…" onChange={(e) => set("note", e.target.value)} />
      </label>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn-primary sm" onClick={save} disabled={busy}>
          {busy ? "Đang lưu…" : "💾 Lưu hồ sơ"}
        </button>
        {msg && <span className="savemsg">{msg}</span>}
      </div>
    </div>
  );
}

function ConvTab({ c }) {
  function openConv() {
    // InboxSection đọc hint này lúc mount để mở đúng hội thoại
    sessionStorage.setItem("hb_open_conv", JSON.stringify({ ch: c.platform, user_id: c.user_id }));
    window.location.href = "/?s=chat";
  }
  return (
    <div className="cu-conv">
      <div className="cu-conv-row">
        <ChannelTile ch={c.platform} size={30} />
        <div style={{ flex: 1 }}>
          <b>{c.platform}</b>
          <div className="hint">{c.message_count} tin nhắn · hoạt động {relTime(c.last_updated)}</div>
        </div>
        <button className="btn-mini" onClick={openConv}>↗ Xem hội thoại</button>
      </div>
    </div>
  );
}

function OrdersTab({ account, userId }) {
  const [list, setList] = useState(null);
  useEffect(() => {
    customersApi.orders(account, userId).then((r) =>
      setList(r.ok && Array.isArray(r.body) ? r.body : []));
  }, [account, userId]);
  if (list === null) return <p className="hint">Đang tải…</p>;
  if (list.length === 0) return <p className="hint">Khách chưa có đơn hàng nào.</p>;
  return (
    <div className="cu-orders">
      {list.map((o) => (
        <div key={o.id} className="cu-order-row">
          <b>{o.code}</b>
          <span className="badge stage">{o.status}</span>
          <span>{vnd(o.total)}</span>
          <span className="hint">{(o.created_at || "").slice(0, 10)}</span>
        </div>
      ))}
    </div>
  );
}

function MemoryTab({ c, account, userId, onChanged }) {
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function add() {
    if (!content.trim() || busy) return;
    setBusy(true);
    const r = await customersApi.memoryAdd(account, userId, content.trim());
    setBusy(false);
    if (r.ok) { setContent(""); onChanged(); }
    else setMsg("❌ " + (r.body?.error || "Thêm thất bại"));
  }
  async function aiScan() {
    if (busy) return;
    setBusy(true); setMsg("🤖 AI đang đọc hội thoại (vài giây)…");
    const r = await customersApi.memoryAi(account, userId);
    setBusy(false);
    if (r.ok) {
      setMsg(r.body.added?.length ? `✅ AI ghi nhớ thêm ${r.body.added.length} điều về khách.`
                                  : "AI không thấy gì mới đáng nhớ.");
      onChanged();
    } else setMsg("❌ " + (r.body?.error || "AI quét thất bại"));
  }
  async function del(id) {
    await customersApi.memoryDel(id); onChanged();
  }

  return (
    <div className="cu-memory">
      <p className="hint">
        🧠 <b>Trí nhớ AI về khách</b> — bot đọc các điều này khi trả lời để cá nhân hoá
        (xưng hô đúng, nhớ sở thích, nhu cầu cũ…).
      </p>
      <div style={{ display: "flex", gap: 6 }}>
        <input style={{ flex: 1 }} placeholder="VD: Khách thích phòng view biển, hay đặt cuối tuần…"
               value={content} onChange={(e) => setContent(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn-primary sm" onClick={add} disabled={busy || !content.trim()}>＋</button>
      </div>
      <button className="btn-outline cu-scan" onClick={aiScan} disabled={busy}>
        {busy ? "⏳ Đang xử lý…" : "🤖 AI quét hội thoại & tự ghi nhớ"}
      </button>
      {msg && <div className="savemsg">{msg}</div>}
      {(c.memory || []).length === 0
        ? <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>
            AI chưa ghi nhận thông tin nào về khách. Bấm ＋ để thêm thủ công.</p>
        : (c.memory || []).map((m) => (
            <div key={m.id} className="cu-mem-row">
              <span className={"badge " + (m.source === "ai" ? "bot" : "stage")}>
                {m.source === "ai" ? "🤖 AI" : "✍️ Tay"}</span>
              <span style={{ flex: 1 }}>{m.content}</span>
              <button className="btn-mini danger" onClick={() => del(m.id)}>✕</button>
            </div>
          ))}
    </div>
  );
}

function HistoryTab({ c }) {
  const list = c.history || [];
  if (list.length === 0) return <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>Chưa có thay đổi nào.</p>;
  return (
    <div className="cu-history">
      {list.map((h, i) => (
        <div key={i} className="cu-hist-row">
          <b>{FIELD_LABELS[h.field] || h.field}</b>
          <span className="cu-ellip">{h.old_value || "(trống)"} → <b>{h.new_value || "(trống)"}</b></span>
          <span className="hint">{(h.created_at || "").slice(0, 16).replace("T", " ")}</span>
        </div>
      ))}
    </div>
  );
}
