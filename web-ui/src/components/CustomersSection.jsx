import { useEffect, useState } from "react";
import { customersApi } from "../customersApi.js";
import { CH_HOST } from "../apiConfig.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { vnd } from "../ordersApi.js";
import { useI18n } from "../i18n.jsx";

/*
 * CRM Khách hàng (kiểu AloChat): gộp khách từ MỌI kênh, bảng danh sách + drawer
 * chi tiết 6 tab: Thông tin (hồ sơ + nhãn + vòng đời) / Hội thoại / Đơn hàng /
 * Nhắc việc / AI ghi nhớ / Lịch sử. Kèm: phễu vòng đời (đếm theo stage), lọc
 * theo nhãn, banner gộp khách trùng SĐT, panel nhắc việc đến hạn, điểm thưởng.
 */

const PLATFORMS = [
  ["", ""], ["zalo", "Zalo"], ["zalooa", "Zalo OA"], ["meta", "Mess + IG"],
  ["telegram", "Telegram"], ["tiktok", "TikTok"], ["shopee", "Shopee"], ["webchat", "Website"],
];
const SALUTATIONS = ["", "anh", "chị", "em", "bạn", "cô", "chú", "quý khách"];
// Các field có nhãn dịch được trong tab Lịch sử → key "cust.field.<field>"
const FIELD_KEYS = ["name", "salutation", "phone", "email", "address", "note", "tags", "stage", "points", "merge"];
// Vòng đời khách — khớp customers.STAGES backend (label vi giữ cho nơi khác import; UI render qua t("cust.stage.<k>"))
export const STAGES = {
  lead:     { label: "Tiềm năng",  color: "#4C6EF5" },
  customer: { label: "Đã mua",     color: "#23a065" },
  repeat:   { label: "Khách quen", color: "#7C3AED" },
  dormant:  { label: "Ngủ đông",   color: "#8a8fa3" },
};

function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }
function relTime(iso, t) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return t("cust.rel.min", { n: Math.max(1, Math.floor(diff / 60)) });
  if (diff < 86400) return t("cust.rel.hour", { n: Math.floor(diff / 3600) });
  return t("cust.rel.day", { n: Math.floor(diff / 86400) });
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
  const { t } = useI18n();
  const s = STAGES[stage];
  if (!s) return null;
  return <span className="badge cu-stage" style={{ "--c": s.color }}>{t(`cust.stage.${stage}`)}</span>;
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
  const { t } = useI18n();
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

  if (data === null) return <div className="empty"><p>{t("cust.loading")}</p></div>;
  if (data === "offline")
    return <div className="empty"><p>{t("cust.offline")}</p></div>;

  const stages = data.stages || {};

  return (
    <div className="cu">
      {/* Nhắc việc đến hạn */}
      <FollowupPanel onOpenCustomer={(acc, uid) => setSel({ account: acc, user_id: uid })} />

      {/* Khách trùng SĐT → gợi ý gộp */}
      {dups.length > 0 && (
        <div className="cu-dupbar">
          {t("cust.dup.found")} <b>{dups.length}</b> {t("cust.dup.groups")} <b>{t("cust.dup.same_phone")}</b> {t("cust.dup.rest")}
          <button className="btn-mini" onClick={() => setShowMerge(true)}>{t("cust.dup.view_merge")}</button>
        </div>
      )}

      {/* Phễu vòng đời */}
      <div className="cu-funnel">
        <button className={"cu-fun" + (stage === "" ? " on" : "")} onClick={() => setStage("")}>
          {t("cust.all")} <b>{Object.values(stages).reduce((a, b) => a + b, 0)}</b>
        </button>
        {Object.entries(STAGES).map(([k, v]) => (
          <button key={k} className={"cu-fun" + (stage === k ? " on" : "")}
                  style={{ "--c": v.color }} onClick={() => setStage(stage === k ? "" : k)}>
            {t(`cust.stage.${k}`)} <b>{stages[k] || 0}</b>
          </button>
        ))}
      </div>

      <div className="cu-toolbar">
        <input className="inbox-search" style={{ maxWidth: 320 }}
               placeholder={t("cust.search_ph")}
               value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={platform} onChange={(e) => setPlatform(e.target.value)} style={{ width: "auto" }}>
          {PLATFORMS.map(([v, l]) => <option key={v} value={v}>{v === "" ? t("cust.platform_all") : l}</option>)}
        </select>
        <select value={tag} onChange={(e) => setTag(e.target.value)} style={{ width: "auto" }}>
          <option value="">{t("cust.all_tags")}</option>
          {allTags.map((t) => <option key={t.tag} value={t.tag}>🏷 {t.tag} ({t.count})</option>)}
        </select>
        <span className="hint" style={{ marginLeft: "auto" }}>{t("cust.count", { n: data.total })}</span>
      </div>

      {data.items.length === 0 ? (
        <div className="empty"><p>{q || tag || stage ? t("cust.empty_filter") : t("cust.empty")}</p></div>
      ) : (
        <div className="cu-table panel">
          <div className="cu-row cu-head">
            <span>{t("cust.th.customer")}</span><span>{t("cust.th.platform")}</span><span>{t("cust.th.phone")}</span>
            <span>{t("cust.th.tags")}</span><span>{t("cust.th.stage")}</span><span>{t("cust.th.activity")}</span>
          </div>
          {data.items.map((c) => (
            <div key={c.account + c.user_id} className="cu-row"
                 onClick={() => setSel({ account: c.account, user_id: c.user_id })}>
              <span className="cu-name"><Avatar c={c} size={32} />
                <b>{c.name || t("cust.guest_name", { id: String(c.user_id).slice(-6) })}</b>
                {c.merged_count > 0 && <span className="hint" title={t("cust.merged_title")}>🔗{c.merged_count + 1}</span>}
                {c.points > 0 && <span className="cu-pts" title={t("cust.field.points")}>⭐{c.points}</span>}
              </span>
              <span><span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                <ChannelTile ch={c.platform} size={13} /> {c.platform}</span></span>
              <span>{c.phone || "–"}</span>
              <span><TagChips tags={c.tags} /></span>
              <span><StageBadge stage={c.stage} /></span>
              <span className="hint">{relTime(c.last_updated, t)}</span>
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
  const { t } = useI18n();
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
        ⏰ <b>{fu.due_count}</b> {t("cust.fu.head", { n: fu.items.length })}
        <span className="btn-mini" style={{ marginLeft: "auto" }}>{open ? t("sb.collapse") : t("cust.fu.view_all")}</span>
      </div>
      {shown.map((f) => (
        <div key={f.id} className="cu-furow">
          <span className={"cu-fudue" + (f.overdue ? " late" : "")}>
            {(f.due_at || "").slice(0, 10)}</span>
          <a onClick={() => onOpenCustomer(f.account, f.user_id)}><b>{f.customer_name}</b></a>
          <span className="cu-ellip" style={{ flex: 1 }}>{f.note}</span>
          <button className="btn-mini" onClick={() => done(f.id)}>{t("cust.fu.done_btn")}</button>
        </div>
      ))}
    </div>
  );
}

/* ── Modal gộp khách trùng SĐT ── */
function MergeModal({ dups, onClose }) {
  const { t } = useI18n();
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
        setMsg("❌ " + (r.body?.error || t("cust.merge.fail"))); setBusy(false); return;
      }
    }
    setBusy(false); setChanged(true);
    setMsg(t("cust.merge.done", { n: g.customers.length, phone: g.phone }));
    setGroups((gs) => gs.filter((x) => x.phone !== g.phone));
  }

  return (
    <div className="modal-bg" onClick={() => onClose(changed)}>
      <div className="modal" style={{ maxWidth: 520 }} onClick={(e) => e.stopPropagation()}>
        <h3>{t("cust.merge.title")}</h3>
        <p className="hint" style={{ margin: "6px 0 12px" }}>
          {t("cust.merge.hint1")} <b>{t("cust.merge.primary")}</b> {t("cust.merge.hint2")}
        </p>
        {groups.length === 0 && <p className="hint">{t("cust.merge.none")}</p>}
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
                {(primary[g.phone] ?? 0) === i && <span className="badge stage">{t("cust.merge.primary")}</span>}
              </label>
            ))}
            <button className="btn-primary sm" disabled={busy} onClick={() => doMerge(g)}>
              {busy ? t("cust.merge.busy") : t("cust.merge.btn", { n: g.customers.length })}
            </button>
          </div>
        ))}
        {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
        <div className="modal-actions">
          <button className="btn-ghost" onClick={() => onClose(changed)}>{t("cust.close")}</button>
        </div>
      </div>
    </div>
  );
}

/* ── Drawer chi tiết khách ── */
function CustomerDrawer({ account, userId, onClose }) {
  const { t } = useI18n();
  const [c, setC] = useState(null);
  const [tab, setTab] = useState("info");
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await customersApi.get(account, userId);
    setC(r.ok && r.body?.ok ? r.body : "err");
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [account, userId]);

  async function doScan() {
    setMsg(t("cust.scan.busy"));
    const r = await customersApi.scan(account, userId);
    if (r.ok) {
      const { phones, emails, updated } = r.body;
      setMsg(phones.length || emails.length
        ? t("cust.scan.found", { p: phones.length, e: emails.length }) + (updated ? t("cust.scan.filled") : ".")
        : t("cust.scan.none"));
      load();
    } else setMsg(t("cust.scan.fail"));
  }

  async function adjustPoints(delta) {
    const label = delta > 0 ? t("cust.pts.add_label") : t("cust.pts.sub_label");
    const v = prompt(t("cust.pts.prompt", { label, n: c.points }), "10");
    const n = parseInt(v, 10);
    if (!n || n <= 0) return;
    const reason = prompt(t("cust.pts.reason"), delta > 0 ? t("cust.pts.reason_add") : t("cust.pts.reason_sub")) || "";
    const r = await customersApi.pointsAdjust(account, userId, delta > 0 ? n : -n, reason);
    if (r.ok) load(); else alert("❌ " + (r.body?.error || t("cust.pts.fail")));
  }

  return (
    <div className="cu-drawer-bg" onClick={onClose}>
      <div className="cu-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="cu-drawer-head">
          <h3>{t("cust.detail")}</h3>
          <button className="cs-pclose" onClick={onClose}>✕</button>
        </div>
        {c === null ? <p className="hint" style={{ padding: 20 }}>{t("team.loading")}</p>
          : c === "err" ? <p className="hint" style={{ padding: 20 }}>{t("cust.load_fail")}</p>
          : (
            <>
              <div className="cu-hero">
                <Avatar c={c} size={52} />
                <div>
                  <b style={{ fontSize: 17 }}>{c.name || t("cust.guest_name", { id: String(c.user_id).slice(-6) })}</b>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 3 }}>
                    <span className="ch-chip" style={{ "--c": "#7C3AED" }}>
                      <ChannelTile ch={c.platform} size={13} /> {c.platform}</span>
                    {(c.merged || []).map((m) => (
                      <span key={m.user_id} className="ch-chip" style={{ "--c": "#8a8fa3" }}
                            title={t("cust.merged_chip_title")}>
                        <ChannelTile ch={m.platform} size={13} /> {m.platform} 🔗</span>
                    ))}
                    <StageBadge stage={c.stage} />
                  </div>
                </div>
              </div>
              <div className="cu-stats">
                <div><b>{c.conversation_count}</b><span>{t("nav.chat")}</span></div>
                <div><b>{c.order_count}</b><span>{t("nav.orders")}</span></div>
                <div><b>{vnd(c.order_value)}</b><span>{t("cust.stat.paid")}</span></div>
                <div>
                  <b>⭐ {c.points}</b><span>{t("cust.field.points")}</span>
                  <span className="cu-ptbtns">
                    <button className="btn-mini" title={t("cust.pts.add_title")} onClick={() => adjustPoints(+1)}>＋</button>
                    <button className="btn-mini" title={t("cust.pts.sub_title")} onClick={() => adjustPoints(-1)}>−</button>
                  </span>
                </div>
              </div>
              <button className="btn-outline cu-scan" onClick={doScan}>
                {t("cust.scan.btn")}
              </button>
              {msg && <div className="savemsg" style={{ margin: "6px 16px" }}>{msg}</div>}

              <div className="tabs cu-tabs">
                {[["info", t("cust.tab.info")], ["conv", t("nav.chat")], ["orders", t("nav.orders")],
                  ["fu", t("cust.tab.fu")], ["memory", t("cust.tab.memory")], ["history", t("cust.tab.history")]].map(([k, l]) => (
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
  const { t } = useI18n();
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
    setMsg(r.ok ? t("cust.f.saved") : t("cust.f.save_fail"));
    if (r.ok) onSaved();
  }

  return (
    <div className="cu-form">
      <label>{t("cust.f.name")}
        <input value={f.name} placeholder={c.channel_name || t("cust.f.name_ph")}
               onChange={(e) => set("name", e.target.value)} />
      </label>
      <label>{t("cust.f.salutation")}
        <select value={f.salutation} onChange={(e) => set("salutation", e.target.value)}>
          {SALUTATIONS.map((s) => <option key={s} value={s}>{s || t("cust.f.salutation_none")}</option>)}
        </select>
      </label>
      <label>{t("cust.f.stage")}
        <select value={f.stage} onChange={(e) => set("stage", e.target.value)}>
          <option value="">{t("cust.f.stage_auto")}</option>
          {Object.keys(STAGES).map((k) => <option key={k} value={k}>{t(`cust.stage.${k}`)}</option>)}
        </select>
      </label>
      <label>{t("cust.f.tags")}
        <span className="cu-tagedit">
          {tags.map((t) => (
            <span key={t} className="cu-tag">
              {t} <a onClick={() => setTags((cur) => cur.filter((x) => x !== t))}>✕</a>
            </span>
          ))}
          <input value={tagInput} placeholder={t("cust.f.tag_ph")}
                 onChange={(e) => setTagInput(e.target.value)}
                 onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
                 onBlur={addTag} />
        </span>
      </label>
      <label>{t("cust.field.phone")}
        <input value={f.phone} placeholder={t("cust.f.phone_ph")} onChange={(e) => set("phone", e.target.value)} />
      </label>
      <label>{t("cust.field.email")}
        <input value={f.email} placeholder={t("cust.f.email_ph")} onChange={(e) => set("email", e.target.value)} />
      </label>
      <label>{t("cust.field.address")}
        <input value={f.address} placeholder={t("cust.f.address_ph")} onChange={(e) => set("address", e.target.value)} />
      </label>
      <label>{t("cust.field.note")}
        <textarea rows={3} value={f.note} placeholder={t("cust.f.note_ph")} onChange={(e) => set("note", e.target.value)} />
      </label>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button className="btn-primary sm" onClick={save} disabled={busy}>
          {busy ? t("cust.f.saving") : t("cust.f.save_btn")}
        </button>
        {msg && <span className="savemsg">{msg}</span>}
      </div>
    </div>
  );
}

function ConvTab({ c }) {
  const { t } = useI18n();
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
            <b>{r.platform}</b>{!r.main && <span className="hint"> {t("cust.conv.merged")}</span>}
            {r.main && <div className="hint">{t("cust.conv.meta", { n: c.message_count, rel: relTime(c.last_updated, t) })}</div>}
          </div>
          <button className="btn-mini" onClick={() => openConv(r.platform, r.user_id)}>{t("cust.conv.open")}</button>
        </div>
      ))}
    </div>
  );
}

function OrdersTab({ account, userId }) {
  const { t } = useI18n();
  const [list, setList] = useState(null);
  useEffect(() => {
    customersApi.orders(account, userId).then((r) =>
      setList(r.ok && Array.isArray(r.body) ? r.body : []));
  }, [account, userId]);
  if (list === null) return <p className="hint">{t("team.loading")}</p>;
  if (list.length === 0) return <p className="hint">{t("cust.orders.none")}</p>;
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
  const { t } = useI18n();
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
    else setMsg("❌ " + (r.body?.error || t("cust.add_fail")));
  }
  async function done(id) { await customersApi.followupDone(id); onChanged(); }
  async function del(id) { await customersApi.followupDel(id); onChanged(); }

  const list = c.followups || [];
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="cu-memory">
      <p className="hint">
        ⏰ <b>{t("cust.tab.fu")}</b> {t("cust.fu.hint")}
      </p>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        <input style={{ flex: "1 1 160px" }} placeholder={t("cust.fu.note_ph")}
               value={note} onChange={(e) => setNote(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && add()} />
        <input type="date" style={{ width: 150 }} min={today}
               value={due} onChange={(e) => setDue(e.target.value)} />
        <button className="btn-primary sm" onClick={add} disabled={busy || !note.trim() || !due}>＋</button>
      </div>
      {msg && <div className="savemsg">{msg}</div>}
      {list.length === 0
        ? <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>{t("cust.fu.none")}</p>
        : list.map((f) => (
            <div key={f.id} className="cu-mem-row">
              <span className={"cu-fudue" + (f.status === "pending" && f.due_at <= new Date().toISOString() ? " late" : "")}>
                {(f.due_at || "").slice(0, 10)}</span>
              <span style={{ flex: 1, textDecoration: f.status === "done" ? "line-through" : "none" }}>{f.note}</span>
              {f.status === "pending"
                ? <button className="btn-mini" onClick={() => done(f.id)}>{t("cust.fu.done_btn")}</button>
                : <span className="badge stage">{t("cust.fu.done_badge")}</span>}
              <button className="btn-mini danger" onClick={() => del(f.id)}>✕</button>
            </div>
          ))}
    </div>
  );
}

function MemoryTab({ c, account, userId, onChanged }) {
  const { t } = useI18n();
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function add() {
    if (!content.trim() || busy) return;
    setBusy(true);
    const r = await customersApi.memoryAdd(account, userId, content.trim());
    setBusy(false);
    if (r.ok) { setContent(""); onChanged(); }
    else setMsg("❌ " + (r.body?.error || t("cust.add_fail")));
  }
  async function aiScan() {
    if (busy) return;
    setBusy(true); setMsg(t("cust.mem.ai_busy"));
    const r = await customersApi.memoryAi(account, userId);
    setBusy(false);
    if (r.ok) {
      setMsg(r.body.added?.length ? t("cust.mem.ai_added", { n: r.body.added.length })
                                  : t("cust.mem.ai_none"));
      onChanged();
    } else setMsg("❌ " + (r.body?.error || t("cust.mem.ai_fail")));
  }
  async function del(id) {
    await customersApi.memoryDel(id); onChanged();
  }

  return (
    <div className="cu-memory">
      <p className="hint">
        🧠 <b>{t("cust.mem.title")}</b> {t("cust.mem.hint")}
      </p>
      <div style={{ display: "flex", gap: 6 }}>
        <input style={{ flex: 1 }} placeholder={t("cust.mem.ph")}
               value={content} onChange={(e) => setContent(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && add()} />
        <button className="btn-primary sm" onClick={add} disabled={busy || !content.trim()}>＋</button>
      </div>
      <button className="btn-outline cu-scan" onClick={aiScan} disabled={busy}>
        {busy ? t("cust.mem.busy") : t("cust.mem.ai_btn")}
      </button>
      {msg && <div className="savemsg">{msg}</div>}
      {(c.memory || []).length === 0
        ? <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>
            {t("cust.mem.none")}</p>
        : (c.memory || []).map((m) => (
            <div key={m.id} className="cu-mem-row">
              <span className={"badge " + (m.source === "ai" ? "bot" : "stage")}>
                {m.source === "ai" ? "🤖 AI" : t("cust.mem.manual")}</span>
              <span style={{ flex: 1 }}>{m.content}</span>
              <button className="btn-mini danger" onClick={() => del(m.id)}>✕</button>
            </div>
          ))}
    </div>
  );
}

function HistoryTab({ c }) {
  const { t } = useI18n();
  const list = c.history || [];
  if (list.length === 0) return <p className="hint" style={{ textAlign: "center", padding: "16px 0" }}>{t("cust.hist.none")}</p>;
  return (
    <div className="cu-history">
      {list.map((h, i) => (
        <div key={i} className="cu-hist-row">
          <b>{FIELD_KEYS.includes(h.field) ? t(`cust.field.${h.field}`) : h.field}</b>
          <span className="cu-ellip">{h.old_value || t("cust.hist.empty_val")} → <b>{h.new_value || t("cust.hist.empty_val")}</b></span>
          <span className="hint">{(h.created_at || "").slice(0, 16).replace("T", " ")}</span>
        </div>
      ))}
    </div>
  );
}
