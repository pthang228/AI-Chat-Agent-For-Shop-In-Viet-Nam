/* Các card cấu hình bot của shop — dùng ở trang Dạy AI (PromptBuilder).
   Move nguyên từ Settings.jsx: NotifyCard, BankCard (bóc từ JSX inline),
   SheetsCard, CannedCard. Logic giữ y nguyên. */
import { useState, useEffect } from "react";
import { getToken } from "../auth.js";
import { HOST } from "../apiConfig.js";
import { ordersApi } from "../ordersApi.js";
import { notifyApi } from "../notifyApi.js";
import { canned as cannedApi } from "../chatToolsApi.js";

/* Ngân hàng phổ biến (mã VietQR) — chọn nhanh, vẫn gõ tay được mã khác */
const BANKS = ["VCB", "TCB", "MB", "ACB", "VPB", "TPB", "BIDV", "VBA", "STB", "VIB", "SHB", "OCB", "MSB", "HDB"];

/* 💳 Tài khoản nhận tiền — QR động gửi khách khi chốt đơn */
export function BankCard() {
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
      setBankMsg("✅ Đã lưu — khách chốt đơn là bot tự gửi QR này (kèm số tiền + mã đơn).");
      setSampleQr(r.body.sample_qr || "");
    } else {
      setBankMsg("❌ " + (r.body?.error || "Lưu thất bại — server 5005 cần restart bản mới?"));
    }
  }

  return (
    <form className="panel set-card" style={{ marginTop: 16 }} onSubmit={saveBank}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>💳 Tài khoản nhận tiền (QR tự động)</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        Khai tài khoản ngân hàng → khách <b>chốt đơn trong chat</b> là bot tự gửi
        <b> mã QR chuyển khoản</b> (nhúng sẵn số tiền + mã đơn). Kết nối thêm SePay/Casso
        thì tiền vào là đơn <b>tự chuyển "Đã thanh toán"</b>, không cần bạn kiểm tra tay.
      </p>
      <div className="bank-form">
        <div>
          <label>Ngân hàng (mã VietQR)</label>
          <input list="bank-list" placeholder="VD: MB, VCB, TCB…"
                 value={bank.bank_code} onChange={setB("bank_code")} />
          <datalist id="bank-list">
            {BANKS.map((b) => <option key={b} value={b} />)}
          </datalist>
        </div>
        <div>
          <label>Số tài khoản</label>
          <input placeholder="VD: 0901234567" value={bank.bank_account} onChange={setB("bank_account")} />
        </div>
        <div>
          <label>Tên chủ tài khoản</label>
          <input placeholder="VD: NGUYEN VAN A" value={bank.bank_holder} onChange={setB("bank_holder")} />
        </div>
      </div>
      {sampleQr && (
        <div className="bank-preview">
          <img src={sampleQr} alt="QR mẫu" loading="lazy" />
          <span className="hint">QR mẫu (100.000đ · nội dung DH0000) — khách sẽ nhận dạng này với số tiền + mã đơn thật.</span>
        </div>
      )}
      <button className="btn-primary sm" type="submit" style={{ marginTop: 10 }}>💾 Lưu tài khoản</button>
      {bankMsg && <div className="savemsg" style={{ marginTop: 8 }}>{bankMsg}</div>}
    </form>
  );
}

/* 📅 Lịch đặt chỗ (Google Sheets) — shop dán LINK sheet lịch phòng của mình,
   hệ thống tự bóc sheet ID; bot tra lịch trống theo sheet CỦA SHOP khi khách hỏi
   "ngày X còn phòng không". Cần share sheet (Viewer) cho email service account. */
export function SheetsCard() {
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
      if (!b.ok) { setMsg("❌ " + (b.error || "Thêm thất bại")); return; }
      setName(""); setLink("");
      setMsg("✅ Đã thêm! Nhớ share sheet (quyền Người xem) cho email bên trên nha.");
      await load();
    } catch { setMsg("❌ Chưa kết nối máy chủ (5005)"); }
    finally { setBusy(false); }
  }

  async function del(id) {
    if (!confirm("Xoá sheet này? Bot sẽ không tra lịch từ sheet này nữa.")) return;
    await fetch(HOST.bridge + `/sheets/${id}`, { method: "DELETE", headers: H });
    await load();
  }

  const d = data && typeof data === "object" ? data : null;
  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>📅 Lịch đặt chỗ (Google Sheets)</h3>
      <p className="hint" style={{ marginBottom: 10 }}>
        Dán link Google Sheet lịch phòng của shop → khách hỏi <b>"ngày X còn phòng không"</b> là
        bot tự tra sheet và trả lời. Cấu trúc sheet: <b>hàng 1</b> tên phòng (gộp ô), <b>hàng 2</b> ca
        giờ (vd 12h-16h), <b>hàng 3+</b> mỗi dòng 1 ngày (cột B ngày dd/mm/yyyy, các ô ghi
        "Trống" hoặc "Đã đặt"); mỗi tháng 1 tab tên "Lịch tháng 7/2026".
      </p>
      {data === null && <p className="hint">Đang tải…</p>}
      {data === "offline" && <p className="hint">⚠️ Chưa kết nối máy chủ (5005) — hoặc server cần restart bản mới.</p>}
      {d && (
        <>
          {d.service_email ? (
            <p className="hint" style={{ marginBottom: 10 }}>
              <b>Bước 1:</b> trong Google Sheet bấm <b>Share</b> → thêm email này (quyền <b>Người xem</b>):{" "}
              <code style={{ wordBreak: "break-all" }}>{d.service_email}</code>{" "}
              <button type="button" className="btn-mini"
                      onClick={() => { navigator.clipboard?.writeText(d.service_email); setMsg("✅ Đã copy email."); }}>
                📋 Copy
              </button>
            </p>
          ) : (
            <p className="hint" style={{ marginBottom: 10 }}>
              ⚠️ Máy chủ chưa cấu hình Google service account — tính năng tra lịch chưa hoạt động, liên hệ quản trị NovaChat.
            </p>
          )}
          <form onSubmit={add} style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input style={{ flex: "0 0 160px" }} placeholder="Tên chi nhánh (vd: Cơ sở 1)"
                   value={name} onChange={(e) => setName(e.target.value)} />
            <input style={{ flex: 1, minWidth: 220 }}
                   placeholder="Dán link Google Sheet (https://docs.google.com/spreadsheets/d/…)"
                   value={link} onChange={(e) => setLink(e.target.value)} />
            <button className="btn-primary sm" type="submit" disabled={busy || !link.trim()}>
              {busy ? "Đang thêm…" : "＋ Thêm"}
            </button>
          </form>
          {d.sheets.length > 0 && (
            <div style={{ marginTop: 12 }}>
              {d.sheets.map((s) => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "7px 0", borderTop: "1px solid var(--line)" }}>
                  <b style={{ fontSize: 14 }}>{s.name}</b>
                  <span className="hint" style={{ flex: 1, wordBreak: "break-all" }}>ID: {s.sheet_id}</span>
                  <button type="button" className="btn-mini" style={{ color: "var(--danger)" }}
                          onClick={() => del(s.id)}>Xoá</button>
                </div>
              ))}
            </div>
          )}
          {d.sheets.length === 0 && (
            <p className="hint" style={{ marginTop: 10 }}>
              Chưa có sheet nào — khách hỏi lịch bot sẽ ghi nhận và báo bạn tự xác nhận.
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
const SHARE_LABELS = {
  off:      "Không bao giờ đưa số cho khách",
  strict:   "Chỉ khi khách hỏi thẳng (xin số / gặp chủ)",
  ask:      "Khi khách xin gặp người HOẶC bot bí",
  greeting: "Luôn kèm ở tin chào đầu tiên",
};
const EVENT_MODE_LABELS = {
  off:    "Không báo",
  notify: "Chỉ nhắn tin",
  call:   "Nhắn + Gọi điện",
};

export function NotifyCard() {
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
    if (r.ok && r.body?.ok) { setCfg(r.body.config); setMsg("✅ Đã lưu cấu hình thông báo."); }
    else setMsg("❌ " + (r.body?.error || "Lưu thất bại (server 5005 cần restart bản mới?)"));
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>📞 Liên hệ khẩn cấp & Thông báo</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        Thay cho việc bot tự gọi điện mỗi lần có khách (không kham nổi khi đông khách).
        Đặt <b>số liên hệ khẩn</b> để khách chủ động gọi khi cần gấp, và chọn <b>khi nào
        hệ thống báo/gọi bạn</b> cho từng loại việc.
      </p>
      {cfg === "offline" ? (
        <p className="hint">⚠️ Chưa kết nối máy chủ (cổng 5005) — hoặc server cần restart bản mới.</p>
      ) : cfg === null ? (
        <p className="hint">Đang tải…</p>
      ) : (
        <>
          {/* Liên hệ khẩn cho khách */}
          <div className="bank-form">
            <div>
              <label>Số điện thoại khẩn</label>
              <input placeholder="VD: 0901234567" value={cfg.emergency_phone} onChange={setField("emergency_phone")} />
            </div>
            <div>
              <label>Zalo (SĐT/link)</label>
              <input placeholder="VD: 0901234567" value={cfg.emergency_zalo} onChange={setField("emergency_zalo")} />
            </div>
            <div>
              <label>Telegram (@username)</label>
              <input placeholder="VD: @tenshop" value={cfg.emergency_tele} onChange={setField("emergency_tele")} />
            </div>
          </div>
          <div className="field" style={{ marginTop: 10 }}>
            <label className="field-label">Khi nào bot đưa số này cho khách?</label>
            <div className="nt-modes">
              {(modes.length ? modes : ["off", "strict", "ask", "greeting"]).map((m) => (
                <label key={m} className={"nt-radio" + (cfg.share_mode === m ? " on" : "")}>
                  <input type="radio" name="share_mode" checked={cfg.share_mode === m}
                         onChange={() => setCfg((c) => ({ ...c, share_mode: m }))} />
                  <span>{SHARE_LABELS[m] || m}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Quy tắc báo chủ theo sự kiện */}
          <label className="field-label" style={{ marginTop: 14, display: "block" }}>
            Khi nào báo/gọi bạn?
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
                      {EVENT_MODE_LABELS[v]}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <p className="hint" style={{ marginTop: 8 }}>
            💡 <b>Chỉ nhắn tin</b> = bot gửi thông báo qua kênh của bạn (Telegram = tin bot,
            tức thì & miễn phí). <b>Gọi điện</b> chỉ nên bật cho việc thật khẩn.
          </p>

          <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy} onClick={save}>
              {busy ? "Đang lưu…" : "💾 Lưu cấu hình"}
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
    if (!confirm("Xoá câu mẫu này?")) return;
    await cannedApi.remove(id); load();
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>💬 Câu trả lời mẫu</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        Soạn sẵn các câu hay dùng. Khi trả lời khách trong <b>Hội thoại</b>, bấm <b>💬 Mẫu</b> để chèn nhanh vào ô nhập.
      </p>
      {list === "offline" ? (
        <p className="hint">⚠️ Chưa kết nối máy chủ (cổng 5005).</p>
      ) : (
        <>
          <form className="bank-form" onSubmit={add} style={{ marginBottom: 10 }}>
            <input placeholder="Nhãn ngắn (VD: Chào khách)" value={title} onChange={(e) => setTitle(e.target.value)} />
            <textarea rows={2} placeholder="Nội dung câu trả lời…" value={content} onChange={(e) => setContent(e.target.value)} />
            <button className="btn-primary sm" type="submit" disabled={busy || !content.trim()} style={{ width: "auto" }}>
              {busy ? "Đang lưu…" : "＋ Thêm câu mẫu"}
            </button>
          </form>
          {list === null ? <p className="hint">Đang tải…</p>
            : list.length === 0 ? <p className="hint">Chưa có câu mẫu nào.</p>
            : (
              <ul className="canned-list">
                {list.map((c) => (
                  <li key={c.id}>
                    <div><b>{c.title}</b><span>{c.content}</span></div>
                    <button className="btn-mini danger" onClick={() => del(c.id)}>Xoá</button>
                  </li>
                ))}
              </ul>
            )}
        </>
      )}
    </div>
  );
}
