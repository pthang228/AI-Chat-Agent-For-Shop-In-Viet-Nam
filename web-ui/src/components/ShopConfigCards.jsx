/* Các card cấu hình bot của shop — dùng ở trang Dạy AI (PromptBuilder).
   Move nguyên từ Settings.jsx: NotifyCard, BankCard (bóc từ JSX inline),
   SheetsCard, CannedCard. Logic giữ y nguyên. */
import { useState, useEffect } from "react";
import { getToken } from "../auth.js";
import { HOST } from "../apiConfig.js";
import { ordersApi } from "../ordersApi.js";
import { notifyApi } from "../notifyApi.js";
import { canned as cannedApi } from "../chatToolsApi.js";
import { useI18n } from "../i18n.jsx";

/* Ngân hàng phổ biến (mã theo chuẩn VietQR img.vietqr.io) + tên hiển thị.
   Datalist chỉ là gợi ý — gõ tay mã khác ngoài danh sách vẫn được. */
const BANKS = [
  ["VCB", "Vietcombank"],
  ["TCB", "Techcombank"],
  ["MB", "MB Bank (Quân đội)"],
  ["ACB", "ACB (Á Châu)"],
  ["VPB", "VPBank"],
  ["TPB", "TPBank"],
  ["BIDV", "BIDV"],
  ["ICB", "VietinBank"],
  ["VBA", "Agribank"],
  ["STB", "Sacombank"],
  ["VIB", "VIB"],
  ["SHB", "SHB"],
  ["OCB", "OCB (Phương Đông)"],
  ["MSB", "MSB (Hàng Hải)"],
  ["HDB", "HDBank"],
  ["EIB", "Eximbank"],
  ["SEAB", "SeABank"],
  ["LPB", "LPBank (Bưu điện Liên Việt)"],
  ["NAB", "Nam Á Bank"],
  ["BAB", "Bắc Á Bank"],
  ["ABB", "ABBANK (An Bình)"],
  ["VAB", "VietABank"],
  ["KLB", "KienlongBank"],
  ["PGB", "PGBank"],
  ["SGICB", "SaigonBank"],
  ["CAKE", "CAKE by VPBank"],
  ["TIMO", "Timo"],
];

/* 💳 Tài khoản nhận tiền — QR động gửi khách khi chốt đơn */
export function BankCard() {
  const { t } = useI18n();
  const [bank, setBank] = useState({ bank_code: "", bank_account: "", bank_holder: "" });
  const [sampleQr, setSampleQr] = useState("");
  const [bankMsg, setBankMsg] = useState("");
  useEffect(() => {
    ordersApi.bankGet().then((r) => {
      if (r.ok && r.body?.bank) { setBank(r.body.bank); setSampleQr(r.body.sample_qr || ""); }
    });
  }, []);
  const setB = (k) => (e) => setBank((b) => ({ ...b, [k]: e.target.value }));
  async function saveBank(e) {
    e.preventDefault();
    setBankMsg("");
    const r = await ordersApi.bankSet(bank);
    if (r.ok) {
      setBankMsg(t("scfg.bank_saved"));
      setSampleQr(r.body.sample_qr || "");
    } else {
      setBankMsg("❌ " + (r.body?.error || t("scfg.bank_save_fail")));
    }
  }

  return (
    <form className="panel set-card" style={{ marginTop: 16 }} onSubmit={saveBank}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("scfg.bank_title")}</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        {t("scfg.bank_hint_p1")} <b>{t("scfg.bank_hint_b1")}</b> {t("scfg.bank_hint_p2")}
        <b> {t("scfg.bank_hint_b2")}</b> {t("scfg.bank_hint_p3")}
        <b> {t("scfg.bank_hint_b3")}</b>{t("scfg.bank_hint_p4")}
      </p>
      <div className="bank-form">
        <div>
          <label>{t("scfg.bank_code_lbl")}</label>
          <input list="bank-list" placeholder={t("scfg.bank_code_ph")}
                 value={bank.bank_code} onChange={setB("bank_code")} />
          <datalist id="bank-list">
            {BANKS.map(([code, name]) => <option key={code} value={code}>{name}</option>)}
          </datalist>
        </div>
        <div>
          <label>{t("scfg.bank_acc_lbl")}</label>
          <input placeholder={t("scfg.bank_acc_ph")} value={bank.bank_account} onChange={setB("bank_account")} />
        </div>
        <div>
          <label>{t("scfg.bank_holder_lbl")}</label>
          <input placeholder={t("scfg.bank_holder_ph")} value={bank.bank_holder} onChange={setB("bank_holder")} />
        </div>
      </div>
      {sampleQr && (
        <div className="bank-preview">
          <img src={sampleQr} alt={t("scfg.qr_alt")} loading="lazy" />
          <span className="hint">{t("scfg.qr_hint")}</span>
        </div>
      )}
      <button className="btn-primary sm" type="submit" style={{ marginTop: 10 }}>{t("scfg.bank_save_btn")}</button>
      {bankMsg && <div className="savemsg" style={{ marginTop: 8 }}>{bankMsg}</div>}
    </form>
  );
}

/* 📅 Lịch đặt chỗ (Google Sheets) — shop dán LINK sheet lịch phòng của mình,
   hệ thống tự bóc sheet ID; bot tra lịch trống theo sheet CỦA SHOP khi khách hỏi
   "ngày X còn phòng không". Cần share sheet (Viewer) cho email service account. */
export function SheetsCard() {
  const { t } = useI18n();
  const [data, setData] = useState(null);   // null=tải | {sheets,...} | "offline"
  const [name, setName] = useState("");
  const [link, setLink] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  const H = { Authorization: `Bearer ${getToken()}` };
  async function load() {
    try {
      const r = await fetch(HOST.bridge + "/sheets", { headers: H });
      const b = await r.json();
      setData(b?.ok ? b : "offline");
    } catch { setData("offline"); }
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    setMsg(""); setBusy(true);
    try {
      const r = await fetch(HOST.bridge + "/sheets", {
        method: "POST",
        headers: { ...H, "Content-Type": "application/json" },
        body: JSON.stringify({ name, link }),
      });
      const b = await r.json();
      if (!b.ok) { setMsg("❌ " + (b.error || t("scfg.sheet_add_fail"))); return; }
      setName(""); setLink("");
      setMsg(t("scfg.sheet_added"));
      await load();
    } catch { setMsg(t("scfg.sheet_offline")); }
    finally { setBusy(false); }
  }

  async function del(id) {
    if (!confirm(t("scfg.sheet_del_confirm"))) return;
    await fetch(HOST.bridge + `/sheets/${id}`, { method: "DELETE", headers: H });
    await load();
  }

  const d = data && typeof data === "object" ? data : null;
  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("scfg.sheet_title")}</h3>
      <p className="hint" style={{ marginBottom: 10 }}>
        {t("scfg.sheet_hint_p1")} <b>{t("scfg.sheet_hint_b1")}</b> {t("scfg.sheet_hint_p2")}{" "}
        <b>{t("scfg.sheet_hint_b2")}</b> {t("scfg.sheet_hint_p3")}{" "}
        <b>{t("scfg.sheet_hint_b3")}</b> {t("scfg.sheet_hint_p4")}{" "}
        <b>{t("scfg.sheet_hint_b4")}</b> {t("scfg.sheet_hint_p5")}
      </p>
      {data === null && <p className="hint">{t("team.loading")}</p>}
      {data === "offline" && <p className="hint">{t("scfg.offline_5005")}</p>}
      {d && (
        <>
          {d.service_email ? (
            <p className="hint" style={{ marginBottom: 10 }}>
              <b>{t("scfg.step1_b")}</b> {t("scfg.step1_p1")} <b>Share</b> {t("scfg.step1_p2")} <b>{t("scfg.viewer")}</b>{t("scfg.step1_p3")}{" "}
              <code style={{ wordBreak: "break-all" }}>{d.service_email}</code>{" "}
              <button type="button" className="btn-mini"
                      onClick={() => { navigator.clipboard?.writeText(d.service_email); setMsg(t("scfg.copied")); }}>
                {t("scfg.copy_btn")}
              </button>
            </p>
          ) : (
            <p className="hint" style={{ marginBottom: 10 }}>
              {t("scfg.no_sa")}
            </p>
          )}
          <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input style={{ flex: "0 0 160px" }} placeholder={t("scfg.branch_ph")}
                   value={name} onChange={(e) => setName(e.target.value)} />
            <input style={{ flex: 1, minWidth: 220 }}
                   placeholder={t("scfg.link_ph")}
                   value={link} onChange={(e) => setLink(e.target.value)} />
            <button className="btn-primary sm" type="submit" disabled={busy || !link.trim()}>
              {busy ? t("scfg.adding") : t("scfg.add_btn")}
            </button>
          </form>
          {d.sheets.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {d.sheets.map((s) => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line)" }}>
                  <b style={{ fontSize: 14 }}>{s.name}</b>
                  <span className="hint" style={{ flex: 1, wordBreak: "break-all" }}>ID: {s.sheet_id}</span>
                  <button type="button" className="btn-mini" style={{ color: "var(--danger)" }}
                          onClick={() => del(s.id)}>{t("team.del")}</button>
                </div>
              ))}
            </div>
          )}
          {d.sheets.length === 0 && (
            <p className="hint" style={{ marginTop: 10 }}>
              {t("scfg.no_sheets")}
            </p>
          )}
        </>
      )}
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
    </div>
  );
}

/* 📞 Liên hệ khẩn cấp & Thông báo — thay cơ chế bot tự gọi điện chủ (không scale).
   (1) SĐT/Zalo/Telegram để KHÁCH chủ động gọi khi cần gấp + chọn khi nào bot đưa số.
   (2) Với mỗi loại sự kiện, chủ chọn: không báo / chỉ nhắn tin / nhắn + gọi. */
const SHARE_KEYS = {
  off:      "scfg.share_off",
  strict:   "scfg.share_strict",
  ask:      "scfg.share_ask",
  greeting: "scfg.share_greeting",
};
const EVENT_MODE_KEYS = {
  off:    "scfg.ev_off",
  notify: "scfg.ev_notify",
  call:   "scfg.ev_call",
};

export function NotifyCard() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);        // null=tải | object | "offline"
  const [meta, setMeta] = useState({});        // event key → nhãn
  const [modes, setModes] = useState([]);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    notifyApi.get().then((r) => {
      if (r.ok && r.body?.ok) { setCfg(r.body.config); setMeta(r.body.events_meta || {}); setModes(r.body.share_modes || []); }
      else setCfg("offline");
    });
  }, []);

  const setField = (k) => (e) => setCfg((c) => ({ ...c, [k]: e.target.value }));
  const setEvent = (k, v) => setCfg((c) => ({ ...c, events: { ...c.events, [k]: v } }));

  async function save() {
    if (busy) return;
    setMsg(""); setBusy(true);
    const r = await notifyApi.set(cfg);
    setBusy(false);
    if (r.ok && r.body?.ok) { setCfg(r.body.config); setMsg(t("scfg.notify_saved")); }
    else setMsg("❌ " + (r.body?.error || t("scfg.notify_save_fail")));
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("scfg.notify_title")}</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        {t("scfg.notify_hint_p1")} <b>{t("scfg.notify_hint_b1")}</b> {t("scfg.notify_hint_p2")} <b>{t("scfg.notify_hint_b2")}</b> {t("scfg.notify_hint_p3")}
      </p>
      {cfg === "offline" ? (
        <p className="hint">{t("team.offline")}</p>
      ) : cfg === null ? (
        <p className="hint">{t("team.loading")}</p>
      ) : (
        <>
          {/* Liên hệ khẩn cho khách */}
          <div className="bank-form">
            <div>
              <label>{t("scfg.em_phone")}</label>
              <input placeholder={t("scfg.bank_acc_ph")} value={cfg.emergency_phone} onChange={setField("emergency_phone")} />
            </div>
            <div>
              <label>{t("scfg.em_zalo")}</label>
              <input placeholder={t("scfg.bank_acc_ph")} value={cfg.emergency_zalo} onChange={setField("emergency_zalo")} />
            </div>
            <div>
              <label>{t("scfg.em_tele")}</label>
              <input placeholder={t("scfg.em_tele_ph")} value={cfg.emergency_tele} onChange={setField("emergency_tele")} />
            </div>
          </div>
          <div className="field" style={{ marginTop: 10 }}>
            <label className="field-label">{t("scfg.share_when")}</label>
            <div className="nt-modes">
              {(modes.length ? modes : ["off", "strict", "ask", "greeting"]).map((m) => (
                <label key={m} className={"nt-radio" + (cfg.share_mode === m ? " on" : "")}>
                  <input type="radio" name="share_mode" checked={cfg.share_mode === m}
                         onChange={() => setCfg((c) => ({ ...c, share_mode: m }))} />
                  <span>{SHARE_KEYS[m] ? t(SHARE_KEYS[m]) : m}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Quy tắc báo chủ theo sự kiện */}
          <label className="field-label" style={{ marginTop: 14, display: "block" }}>
            {t("scfg.notify_when")}
          </label>
          <div className="nt-events">
            {Object.entries(meta).map(([k, label]) => (
              <div key={k} className="nt-event">
                <span className="nt-event-lbl">{label}</span>
                <div className="nt-event-modes">
                  {["off", "notify", "call"].map((v) => (
                    <button key={v} type="button"
                            className={"nt-chip" + ((cfg.events?.[k] || "notify") === v ? " on" : "")}
                            onClick={() => setEvent(k, v)}>
                      {t(EVENT_MODE_KEYS[v])}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 8 }}>
            💡 <b>{t("scfg.ev_notify")}</b> {t("scfg.notify_tip_p1")} <b>{t("scfg.call_word")}</b> {t("scfg.notify_tip_p2")}
          </p>

          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy} onClick={save}>
              {busy ? t("scfg.saving") : t("scfg.save_cfg_btn")}
            </button>
            {msg && <span className="savemsg" style={{ margin: 0 }}>{msg}</span>}
          </div>
        </>
      )}
    </div>
  );
}

/* Câu trả lời mẫu — chủ soạn sẵn, khi chat bấm 💬 Mẫu để chèn nhanh */
export function CannedCard() {
  const { t } = useI18n();
  const [list, setList] = useState(null);   // null=tải | mảng | "offline"
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await cannedApi.list();
    setList(r.ok && Array.isArray(r.body) ? r.body : "offline");
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    if (!content.trim() || busy) return;
    setBusy(true);
    const r = await cannedApi.add(title.trim(), content.trim());
    setBusy(false);
    if (r.ok) { setTitle(""); setContent(""); load(); }
  }
  async function del(id) {
    if (!confirm(t("scfg.canned_del_confirm"))) return;
    await cannedApi.remove(id); load();
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("scfg.canned_title")}</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        {t("scfg.canned_hint_p1")} <b>{t("nav.chat")}</b>{t("scfg.canned_hint_p2")} <b>{t("scfg.canned_tpl_btn")}</b> {t("scfg.canned_hint_p3")}
      </p>
      {list === "offline" ? (
        <p className="hint">{t("scfg.offline_short")}</p>
      ) : (
        <>
          <form className="bank-form" onSubmit={add} style={{ marginBottom: 10 }}>
            <input placeholder={t("scfg.canned_label_ph")} value={title} onChange={(e) => setTitle(e.target.value)} />
            <textarea rows={2} placeholder={t("scfg.canned_content_ph")} value={content} onChange={(e) => setContent(e.target.value)} />
            <button className="btn-primary sm" type="submit" disabled={busy || !content.trim()} style={{ width: "auto" }}>
              {busy ? t("scfg.saving") : t("scfg.canned_add_btn")}
            </button>
          </form>
          {list === null ? <p className="hint">{t("team.loading")}</p>
            : list.length === 0 ? <p className="hint">{t("scfg.canned_none")}</p>
            : (
              <ul className="canned-list">
                {list.map((c) => (
                  <li key={c.id}>
                    <div><b>{c.title}</b><span>{c.content}</span></div>
                    <button className="btn-mini danger" onClick={() => del(c.id)}>{t("team.del")}</button>
                  </li>
                ))}
              </ul>
            )}
        </>
      )}
    </div>
  );
}
