import { useEffect, useState } from "react";
import { customersApi } from "../customersApi.js";
import { CH_HOST } from "../apiConfig.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { vnd } from "../ordersApi.js";

/*
 * CRM Khách hàng (kiểu AloChat): gộp khách từ MỌI kênh, bảng danh sách + drawer
 * chi tiết 6 tab: Thông tin (hồ sơ + nhãn + vòng đời) / Hội thoại / Đơn hàng /
 * Nhắc việc / AI ghi nhớ / Lịch sử. Kèm: phễu vòng đời (đếm theo stage), lọc
 * theo nhãn, banner gộp khách trùng SĐT, panel nhắc việc đến hạn, điểm thưởng.
 */

const PLATFORMS = [
  ["", "Tất cả nền tảng"], ["zalo", "Zalo"], ["zalooa", "Zalo OA"], ["meta", "Mess + IG"],
  ["telegram", "Telegram"], ["tiktok", "TikTok"], ["shopee", "Shopee"], ["webchat", "Website"],
];
const SALUTATIONS = ["", "anh", "chị", "em", "bạn", "cô", "chú", "quý khách"];
const FIELD_LABELS = {
  name: "Tên", salutation: "Cách xưng hô", phone: "Số điện thoại",
  email: "Email", address: "Địa chỉ", note: "Ghi chú",
  tags: "Nhãn", stage: "Vòng đời", points: "Điểm thưởng", merge: "Gộp hồ sơ",
};
// Vòng đời khách — khớp customers.STAGES backend
export const STAGES = {
  lead:     { label: "Tiềm năng",  color: "#4C6EF5" },
  customer: { label: "Đã mua",     color: "#23a065" },
  repeat:   { label: "Khách quen", color: "#7C3AED" },
  dormant:  { label: "Ngủ đông",   color: "#8a8fa3" },
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
function StageBadge({ stage }) {
  const s = STAGES[stage];
  if (!s) return null;
  return <span className="badge cu-stage" style={{ "--c": s.color }}>{s.label}</span>;
}
function TagChips({ tags, max = 3 }) {
  const list = tags || [];
  if (!list.length) return <span className="hint">–</span>;
  return (
    <span className="cu-tags">
      {list.slice(0, max).map((t) => <span key={t} className="cu-tag">{t}</span>)}
      {list.length > max && <span className="hint">+{list.length - max}</span>}
    </span>
  );
}

export default function CustomersSection() {
  const [data, setData] = useState(null);      // null=tải | {total, items, stages} | "offline"
  const [q, setQ] = useState("");
  const [platform, setPlatform] = useState("");
  const [stage, setStage] = useState("");
  const [tag, setTag] = useState("");
  const [allTags, setAllTags] = useState([]);
  const [dups, setDups] = useState([]);        // nhóm khách trùng SĐT
  const [showMerge, setShowMerge] = useState(false);
  const [sel, setSel] = useState(null);        // {account, user_id} đang mở drawer

  async function load() {
    const r = await customersApi.list({ q, platform, tag, stage });
    setData(r.ok && r.body ? r.body : "offline");
  }
  async function loadSide() {
    const [t, d] = await Promise.all([customersApi.tags(), customersApi.duplicates()]);
    if (t.ok && Array.isArray(t.body)) setAllTags(t.body);
    if (d.ok && Array.isArray(d.body)) setDups(d.body);
  }
  useEffect(() => {
    const t = setTimeout(load, q ? 300 : 0);   // debounce khi gõ tìm kiếm
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, platform, tag, stage]);
  useEffect(() => { loadSide(); }, []);

  if (data === null) return <div className="empty"><p>Đang tải danh sách khách…</p></div>;
  if (data === "offline")
    return <div className="empty"><p>⚠️ Chưa kết nối được máy chủ (cổng 5005) — hoặc server cần restart bản mới.</p></div>;

  const stages = data.stages || {};

  return (
    <div className="cu">
      {/* Nhắc việc đến hạn */}
      <FollowupPanel onOpenCustomer={(acc, uid) => setSel({ account: acc, user_id: uid })} />

      {/* Khách trùng SĐT → gợi ý gộp */}
      {dups.length > 0 && (
        <div className="cu-dupbar">
          🔗 Phát hiện <b>{dups.length}</b> nhóm khách <b>trùng SĐT</b> trên nhiều kênh —
          gộp lại để đơn hàng, điểm và ghi nhớ dồn về một hồ sơ.
          <button className="btn-mini" onClick={() => setShowMerge(true)}>Xem & gộp</button>
        </div>
      )}

      {/* Phễu vòng đời */}
      <div className="cu-funnel">
        <button className={"cu-fun" + (stage === "" ? " on" : "")} onClick={() => setStage("")}>
          Tất cả <b>{Object.values(stages).reduce((a, b) => a + b, 0)}</b>
        </button>
        {Object.entries(STAGES).map(([k, v]) => (
          <button key={k} className={"cu-fun" + (stage === k ? " on" : "")}
                  style={{ "--c": v.color }} onClick={() => setStage(stage === k ? "" : k)}>
            {v.label} <b>{stages[k] || 0}</b>
          </button>
        ))}
      </div>

      <div className="cu-toolbar">
        <input className="inbox-search" style={{ maxWidth: 320 }}
               placeholder="🔍 Tìm theo tên, SĐT, email, địa chỉ…"
               value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={platform} onChange={(e) => setPlatform(e.target.value)} style={{ width: "auto" }}>
          {PLATFORMS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select value={tag} onChange={(e) => setTag(e.target.value)} style={{ width: "auto" }}>
          <option value="">Tất cả nhãn</option>
          {allTags.map((t) => <option key={t.tag} value={t.tag}>🏷 {t.tag} ({t.count})</option>)}
        </select>
        <span className="hint" style={{ marginLeft: "auto" }}>{data.total} khách hàng</span>
      </div>

      {data.items.length === 0 ? (
        <div className="empty"><p>Chưa có khách nào{q || tag || stage ? " khớp bộ lọc" : " nhắn tin"}.</p></div>
      ) : (
        <div className="cu-table panel">
          <div className="cu-row cu-head">
            <span>Khách</span><span>Nền tảng</span><span>SĐT</span>
            <span>Nhãn</span><span>Vòng đời</span><span>Hoạt động</span>
          </div>
          {data.items.map((c) => (
            <div key={c.account + c.user_id} className="cu-row"
                 onClick={() => setSel({ account: c.account, user_id: c.user_id })}>
              <span className="cu-name"><Avatar c={c} size={32} />
                <b>{c.name || `Khách …${String(c.user_id).slice(-6)}`}</b>
                {c.merged_count > 0 && <span className="hint" title="Đã gộp thêm hội thoại kênh khác">🔗{c.merged_count + 1}</span>}
                {c.points > 0 && <span className="cu-pts" title="Điểm thưởng">⭐{c.points}</span>}
              </span>
              <span><span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                <ChannelTile ch={c.platform} size={13} /> {c.platform}</span></span>
              <span>{c.phone || "–"}</span>
              <span><TagChips tags={c.tags} /></span>
              <span><StageBadge stage={c.stage} /></span>
              <span className="hint">{relTime(c.last_updated)}</span>
            </div>
          ))}
        </div>
      )}

      {showMerge && <MergeModal dups={dups} onClose={(changed) => {
        setShowMerge(false);
        if (changed) { load(); loadSide(); }
      }} />}
      {sel && <CustomerDrawer account={sel.account} userId={sel.user_id}
                              onClose={() => { setSel(null); load(); loadSide(); }} />}
    </div>
  );
}

/* ── Panel nhắc việc đến hạn (đầu trang CRM) ── */
function FollowupPanel({ onOpenCustomer }) {
  const [fu, setFu] = useState(null);
  const [open, setOpen] = useState(false);

  async function load() {
    const r = await customersApi.followups();
    if (r.ok && r.body) setFu(r.body);
  }
  useEffect(() => { load(); }, []);

  if (!fu || fu.items.length === 0) return null;
  const shown = open ? fu.items : fu.items.filter((i) => i.overdue).slice(0, 5);

  async function done(id) { await customersApi.followupDone(id); load(); }

  return (
    <div className={"cu-fupanel" + (fu.due_count ? " hot" : "")}>
      <div className="cu-fuhead" onClick={() => setOpen((v) => !v)}>
        ⏰ <b>{fu.due_count}</b> việc đến hạn · {fu.items.length} việc đang chờ
        <span className="btn-mini" style={{ marginLeft: "auto" }}>{open ? "Thu gọn" : "Xem tất cả"}</span>
      </div>
      {shown.map((f) => (
        <div key={f.id} className="cu-furow">
          <span className={"cu-fudue" + (f.overdue ? " late" : "")}>
            {(f.due_at || "").slice(0, 10)}</span>
          <a onClick={() => onOpenCustomer(f.account, f.user_id)}><b>{f.customer_name}</b></a>
          <span className="cu-ellip" style={{ flex: 1 }}>{f.note}</span>
          <button className="btn-mini" onClick={() => done(f.id)}>✓ Xong</button>
        </div>
      ))}
    </div>
  );
}

/* ── Modal gộp khách trùng SĐT ── */
function MergeModal({ dups, onClose }) {
  const [groups, setGroups] = useState(dups);
  const [primary, setPrimary] = useState({});   // phone → index hồ sơ chính
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [changed, setChanged] = useState(false);

  async function doMerge(g) {
    const pi = primary[g.phone] ?? 0;
    const prim = g.customers[pi];
    if (busy) return;
    setBusy(true); setMsg("");
    for (const dup of g.customers.filter((_, i) => i !== pi)) {
      const r = await customersApi.merge(
        { account: prim.account, user_id: prim.user_id },
        { account: dup.account, user_id: dup.user_id });
      if (!r.ok) {
        setMsg("❌ " + (r.body?.error || "Gộp thất bại")); setBusy(false); return;
      }
    }
    setBusy(false); setChanged(true);
    setMsg(`✅ Đã gộp ${g.customers.length} hồ sơ (SĐT ${g.phone}).`);
    setGroups((gs) => gs.filter((x) => x.phone !== g.phone));
  }

  return (
    <div className="modal-bg" onClick={() => onClose(changed)}>
      <div className="modal" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <h3>🔗 Gộp khách trùng SĐT</h3>
        <p className="hint" style={{ margin: "6px 0 12px" }}>
          Chọn <b>hồ sơ chính</b> cho mỗi nhóm — thông tin, nhãn, điểm, ghi nhớ và đơn hàng
          của các hồ sơ kia sẽ dồn về đó. Hội thoại từng kênh vẫn giữ nguyên trong Hộp thư.
        </p>
        {groups.length === 0 && <p className="hint">🎉 Không còn nhóm trùng nào.</p>}
        {groups.map((g) => (
          <div key={g.phone} className="cu-dupgroup">
            <div className="cu-dupphone">📞 {g.phone}</div>
            {g.customers.map((c, i) => (
              <label key={c.account + c.user_id} className="cu-dupopt">
                <input type="radio" name={"prim-" + g.phone}
                       checked={(primary[g.phone] ?? 0) === i}
                       onChange={() => setPrimary((p) => ({ ...p, [g.phone]: i }))} />
                <ChannelTile ch={c.platform} size={16} />
                <b>{c.name}</b>
                <span className="hint">{c.platform}</span>
                {(primary[g.phone] ?? 0) === i && <span className="badge stage">hồ sơ chính</span>}
              </label>
            ))}
            <button className="btn-primary sm" disabled={busy} onClick={() => doMerge(g)}>
              {busy ? "Đang gộp…" : `Gộp ${g.customers.length} hồ sơ`}
            </button>
          </div>
        ))}
        {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={() => onClose(changed)}>Đóng</button>
        </div>
      </div>
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

  async function adjustPoints(delta) {
    const label = delta > 0 ? "CỘNG" : "TRỪ";
    const v = prompt(`Số điểm muốn ${label} (hiện có ${c.points}):`, "10");
    const n = parseInt(v, 10);
    if (!n || n <= 0) return;
    const reason = prompt("Lý do (hiện trong Lịch sử):", delta > 0 ? "thưởng thêm" : "đổi điểm lấy ưu đãi") || "";
    const r = await customersApi.pointsAdjust(account, userId, delta > 0 ? n : -n, reason);
    if (r.ok) load(); else alert("❌ " + (r.body?.error || "Chỉnh điểm thất bại"));
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
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 3 }}>
                    <span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                      <ChannelTile ch={c.platform} size={13} /> {c.platform}</span>
                    {(c.merged || []).map((m) => (
                      <span key={m.user_id} className="ch-chip" style={{ "--c": "#8a8fa3" }}
                            title="Hội thoại kênh khác đã gộp vào hồ sơ này">
                        <ChannelTile ch={m.platform} size={13} /> {m.platform} 🔗</span>
                    ))}
                    <StageBadge stage={c.stage} />
                  </div>
                </div>
              </div>
              <div className="cu-stats">
                <div><b>{c.conversation_count}</b><span>Hội thoại</span></div>
                <div><b>{c.order_count}</b><span>Đơn hàng</span></div>
                <div><b>{vnd(c.order_value)}</b><span>Đã thanh toán</span></div>
                <div>
                  <b>⭐ {c.points}</b><span>Điểm thưởng</span>
                  <span className="cu-ptbtns">
                    <button className="btn-mini" title="Cộng điểm" onClick={() => adjustPoints(+1)}>＋</button>
                    <button className="btn-mini" title="Trừ điểm (đổi ưu đãi)" onClick={() => adjustPoints(-1)}>−</button>
                  </span>
                </div>
              </div>
              <button className="btn-outline cu-scan" onClick={doScan}>
                🔎 Quét lịch sử lấy SĐT/Email
              </button>
              {msg && <div className="savemsg" style={{ margin: "6px 16px" }}>{msg}</div>}

              <div className="tabs cu-tabs">
                {[["info", "Thông tin"], ["conv", "Hội thoại"], ["orders", "Đơn hàng"],
                  ["fu", "Nhắc việc"], ["memory", "AI ghi nhớ"], ["history", "Lịch sử"]].map(([k, l]) => (
                  <button key={k} className={"tab" + (tab === k ? " active" : "")}
                          onClick={() => setTab(k)}>{l}</button>
                ))}
              </div>
              <div className="cu-tab-body">
                {/* key theo giá trị profile: sau scan/save (c đổi) InfoTab remount →
                    form lấy giá trị MỚI, không giữ state cũ rỗng ghi đè SĐT vừa quét */}
                {tab === "info" && <InfoTab
                  key={`${c.name}|${c.salutation}|${c.phone}|${c.email}|${c.address}|${c.note}|${(c.tags || []).join(",")}|${c.stage_manual ? c.stage : ""}`}
                  c={c} account={account} userId={userId} onSaved={load} />}
                {tab === "conv" && <ConvTab c={c} />}
                {tab === "orders" && <OrdersTab account={account} userId={userId} />}
                {tab === "fu" && <FollowupTab c={c} account={account} userId={userId} onChanged={load} />}
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
    stage: c.stage_manual ? c.stage : "",
  });
  const [tags, setTags] = useState(c.tags || []);
  const [tagInput, setTagInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (k, v) => setF((cur) => ({ ...cur, [k]: v }));

  function addTag() {
    const t = tagInput.trim();
    if (t && !tags.some((x) => x.toLowerCase() === t.toLowerCase()))
      setTags((cur) => [...cur, t]);
    setTagInput("");
  }

  async function save() {
    if (busy) return;
    setBusy(true); setMsg("");
    const r = await customersApi.update(account, userId, { ...f, tags });
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
      <label>Vòng đời khách
        <select value={f.stage} onChange={(e) => set("stage", e.target.value)}>
          <option value="">Tự động (theo đơn hàng & hoạt động)</option>
          {Object.entries(STAGES).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
      </label>
      <label>Nhãn (VIP, khách sỉ, quan tâm sản phẩm X…)
        <span className="cu-tagedit">
          {tags.map((t) => (
            <span key={t} className="cu-tag">
              {t} <a onClick={() => setTags((cur) => cur.filter((x) => x !== t))}>✕</a>
            </span>
          ))}
          <input value={tagInput} placeholder="+ nhãn, Enter để thêm"
                 onChange={(e) => setTagInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
                 onBlur={addTag} />
        </span>
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
  function openConv(platform, userId) {
    // InboxSection đọc hint này lúc mount để mở đúng hội thoại
    sessionStorage.setItem("hb_open_conv", JSON.stringify({ ch: platform, user_id: userId }));
    window.location.href = "/?s=chat";
  }
  const rows = [{ platform: c.platform, user_id: c.user_id, main: true }, ...(c.merged || [])];
  return (
    <div className="cu-conv">
      {rows.map((r) => (
        <div key={r.user_id} className="cu-conv-row">
          <ChannelTile ch={r.platform} size={30} />
          <div style={{ flex: 1 }}>
            <b>{r.platform}</b>{!r.main && <span className="hint"> · đã gộp 🔗</span>}
            {r.main && <div className="hint">{c.message_count} tin nhắn · hoạt động {relTime(c.last_updated)}</div>}
          </div>
          <button className="btn-mini" onClick={() => openConv(r.platform, r.user_id)}>↗ Xem hội thoại</button>
        </div>
      ))}
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

/* ── Tab nhắc việc của 1 khách ── */
function FollowupTab({ c, account, userId, onChanged }) {
  const [note, setNote] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function add() {
    if (!note.trim() || !due || busy) return;
    setBusy(true); setMsg("");
    const r = await customersApi.followupAdd(account, userId, note.trim(), due);
    setBusy(false);
    if (r.ok) { setNote(""); setDue(""); onChanged(); }
    else setMsg("❌ " + (r.body?.error || "Thêm thất bại"));
  }
  async function done(id) { await customersApi.followupDone(id); onChanged(); }
  async function del(id) { await customersApi.followupDel(id); onChanged(); }

  const list = c.followups || [];
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="cu-memory">
      <p className="hint">
        ⏰ <b>Nhắc việc</b> — hẹn chăm lại khách (hỏi giá chưa chốt, gọi lại, báo hàng về…).
        Việc đến hạn nổi lên đầu trang Khách hàng.
      </p>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <input style={{ flex: "1 1 160px" }} placeholder="VD: Gọi lại chốt phòng 301…"
               value={note} onChange={(e) => setNote(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && add()} />
        <input type="date" style={{ width: 150 }} min={today}
               value={due} onChange={(e) => setDue(e.target.value)} />
        <button className="btn-primary sm" onClick={add} disabled={busy || !note.trim() || !due}>＋</button>
      </div>
      {msg && <div className="savemsg">{msg}</div>}
      {list.length === 0
        ? <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>Chưa có nhắc việc nào cho khách này.</p>
        : list.map((f) => (
            <div key={f.id} className="cu-mem-row">
              <span className={"cu-fudue" + (f.status === "pending" && f.due_at <= new Date().toISOString() ? " late" : "")}>
                {(f.due_at || "").slice(0, 10)}</span>
              <span style={{ flex: 1, textDecoration: f.status === "done" ? "line-through" : "none" }}>{f.note}</span>
              {f.status === "pending"
                ? <button className="btn-mini" onClick={() => done(f.id)}>✓ Xong</button>
                : <span className="badge stage">✓ xong</span>}
              <button className="btn-mini danger" onClick={() => del(f.id)}>✕</button>
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
