import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, isStaff, updateProfile, changePassword } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { ordersApi } from "../ordersApi.js";
import { teamApi } from "../teamApi.js";
import { notifyApi } from "../notifyApi.js";
import { canned as cannedApi } from "../chatToolsApi.js";
import { IcHome, IcBack, IcLogout, IcUser, IcMail, IcLock } from "../components/icons.jsx";
import BackLink from "../components/BackLink.jsx";

/* Ngân hàng phổ biến (mã VietQR) — chọn nhanh, vẫn gõ tay được mã khác */
const BANKS = ["VCB", "TCB", "MB", "ACB", "VPB", "TPB", "BIDV", "VBA", "STB", "VIB", "SHB", "OCB", "MSB", "HDB"];

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function Settings() {
  const nav = useNavigate();
  const user = currentUser();
  const staff = isStaff(user);
  const isGoogle = user?.provider === "google" && !user?.has_password;

  const [homestay, setHomestay] = useState(user?.homestay || "");
  const [email, setEmail] = useState(user?.email || "");
  const [savedMsg, setSavedMsg] = useState("");

  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [pwMsg, setPwMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function saveProfile(e) {
    e.preventDefault();
    try { await updateProfile({ homestay, email }); setSavedMsg("✅ Đã lưu thông tin."); }
    catch (e) { setSavedMsg("❌ " + e.message); }
  }

  async function savePassword(e) {
    e.preventDefault();
    setPwMsg("");
    try { await changePassword({ oldPassword: oldPw, newPassword: newPw }); setPwMsg("✅ Đã đổi mật khẩu."); setOldPw(""); setNewPw(""); }
    catch (e) { setPwMsg("❌ " + e.message); }
  }

  async function doLogout() {
    if (!confirm("Đăng xuất sẽ TẮT bot (ngừng tự trả lời khách) trên mọi kênh. Tiếp tục?")) return;
    setBusy(true);
    await logoutAndStopBots();
    nav("/login");
  }

  // ── Tài khoản nhận tiền (QR động gửi khách khi chốt đơn) ──
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

  const hostName = user?.homestay || user?.username;

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <span className="brand-mini" style={{ marginLeft: -4 }}><IcHome width={18} height={18} /></span> NovaChat</Link>
        </div>
        <div className="user">
          <span className="user-pill"><span className="avatar">{initials(hostName)}</span>{hostName}</span>
        </div>
      </header>

      <main className="content narrow" style={{ maxWidth: 640 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">Tài khoản</div>
            <h1 className="page-title">Cài đặt</h1>
          </div>
        </div>

        {/* Hồ sơ */}
        <form className="panel set-card" onSubmit={saveProfile}>
          <div className="set-id">
            <span className="avatar lg">{initials(hostName)}</span>
            <div>
              <div className="set-name">{hostName}</div>
              <div className="set-mail"><IcMail width={13} height={13} /> {user?.email || user?.username} <span className={"prov " + (isGoogle ? "g" : "p")}>{isGoogle ? "Google" : "Email"}</span></div>
            </div>
          </div>

          <div className="field" style={{ marginTop: 16 }}>
            <label className="field-label"><IcUser width={14} height={14} /> Tên shop / thương hiệu</label>
            <input value={homestay} onChange={(e) => setHomestay(e.target.value)} placeholder="VD: Mia Spa & Nail" />
          </div>
          <div className="field">
            <label className="field-label"><IcMail width={14} height={14} /> Email liên hệ</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ban@gmail.com" />
            <p className="hint" style={{ marginTop: 6 }}>Dùng để nhận thông báo & khôi phục tài khoản sau này.</p>
          </div>
          <div className="row" style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" type="submit">Lưu thay đổi</button>
            {savedMsg && <span className="savemsg" style={{ margin: 0 }}>{savedMsg}</span>}
          </div>
        </form>

        {/* Đổi mật khẩu */}
        <form className="panel set-card" onSubmit={savePassword} style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>Mật khẩu</h3>
          {isGoogle && (
            <p className="hint">Tài khoản đăng nhập bằng <b>Google</b> — có thể đặt thêm mật khẩu để đăng nhập bằng email (bỏ trống "Mật khẩu hiện tại").</p>
          )}
          <div className="field" style={{ marginTop: 10 }}>
            <label className="field-label"><IcLock width={14} height={14} /> Mật khẩu hiện tại</label>
            <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} placeholder={isGoogle ? "(chưa có — bỏ trống)" : "••••••••"} />
          </div>
          <div className="field">
            <label className="field-label"><IcLock width={14} height={14} /> Mật khẩu mới</label>
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder="Tối thiểu 4 ký tự" />
          </div>
          <div className="row" style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" type="submit">Đổi mật khẩu</button>
            {pwMsg && <span className="savemsg" style={{ margin: 0 }}>{pwMsg}</span>}
          </div>
        </form>

        {/* Liên hệ khẩn cấp & Thông báo — chỉ CHỦ shop */}
        {!staff && <NotifyCard />}

        {/* Nhân viên (team) — chỉ CHỦ shop thấy */}
        {!staff && <TeamCard />}

        {/* Tài khoản nhận tiền — QR động (chủ shop) */}
        {!staff && (
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
        )}

        {/* Câu trả lời mẫu */}
        <CannedCard />

        {/* Bong bóng chat tư vấn */}
        <div className="panel set-card" style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>Bong bóng chat tư vấn</h3>
          <p className="hint" style={{ marginBottom: 12 }}>
            Bong bóng "Mi" ở góc màn hình có thể <b>kéo để di chuyển</b> và bấm <b>✕</b> để ẩn.
            Nếu đã ẩn, bấm nút dưới để hiện lại.
          </p>
          <button className="btn-outline" style={{ width: "auto" }}
                  onClick={() => { localStorage.removeItem("hb_cw_hidden"); localStorage.removeItem("hb_cw_pos"); alert("✅ Đã hiện lại bong bóng chat (về vị trí mặc định). Tải lại trang nếu chưa thấy."); }}>
            💬 Hiện lại bong bóng chat
          </button>
        </div>

        {/* Đăng xuất */}
        <div className="panel set-card" style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>Phiên đăng nhập</h3>
          <p className="hint" style={{ marginBottom: 12 }}>Đăng xuất sẽ <b>tắt bot trên mọi kênh</b> (ngừng tự trả lời khách) cho tới khi bạn đăng nhập và bật lại.</p>
          <button className="btn-outline" style={{ width: "auto", color: "var(--danger)", borderColor: "#ecc9c0" }} onClick={doLogout} disabled={busy}>
            <IcLogout width={16} height={16} /> {busy ? "Đang tắt bot & đăng xuất…" : "Đăng xuất & tắt bot"}
          </button>
        </div>
      </main>
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

function NotifyCard() {
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

/* 👥 Nhân viên — chủ tạo tài khoản cho nhân viên trực hộp thư.
   Nhân viên đăng nhập bằng email + mật khẩu này; chỉ thấy Hội thoại / Khách hàng /
   Đơn hàng / Thống kê — không đụng được Dạy AI, kênh, gói dịch vụ. */
function TeamCard() {
  const [list, setList] = useState(null);   // null=tải | mảng | "offline"
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function load() {
    const r = await teamApi.list();
    setList(r.ok && Array.isArray(r.body) ? r.body : "offline");
  }
  useEffect(() => { load(); }, []);

  async function add(e) {
    e.preventDefault();
    if (busy) return;
    setMsg(""); setBusy(true);
    const r = await teamApi.add(email.trim(), name.trim(), pw);
    setBusy(false);
    if (r.ok) {
      setMsg(`✅ Đã tạo tài khoản nhân viên ${email.trim()} — gửi email + mật khẩu cho họ đăng nhập.`);
      setEmail(""); setName(""); setPw(""); load();
    } else {
      setMsg("❌ " + (r.body?.error || "Không tạo được (server 5005 cần restart bản mới?)"));
    }
  }
  async function resetPw(username) {
    const p = prompt(`Mật khẩu MỚI cho ${username} (tối thiểu 4 ký tự):`);
    if (!p) return;
    const r = await teamApi.update(username, { password: p });
    setMsg(r.ok ? `✅ Đã đổi mật khẩu ${username} (phiên cũ của họ bị đăng xuất).`
                : "❌ " + (r.body?.error || "Đổi mật khẩu thất bại"));
  }
  async function del(username) {
    if (!confirm(`Xoá tài khoản nhân viên ${username}? Họ sẽ không đăng nhập được nữa.`)) return;
    const r = await teamApi.remove(username);
    if (r.ok) load();
    else setMsg("❌ " + (r.body?.error || "Xoá thất bại"));
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>👥 Nhân viên</h3>
      <p className="hint" style={{ marginBottom: 12 }}>
        Tạo tài khoản cho nhân viên <b>trực hộp thư</b>: họ đăng nhập bằng email + mật khẩu
        bạn đặt, thấy <b>Hội thoại / Khách hàng / Đơn hàng / Thống kê</b> và được phân công
        hội thoại — <b>không</b> đụng được Dạy AI, kết nối kênh, gói dịch vụ hay cài đặt thanh toán.
      </p>
      {list === "offline" ? (
        <p className="hint">⚠️ Chưa kết nối máy chủ (cổng 5005) — hoặc server cần restart bản mới.</p>
      ) : (
        <>
          <form className="bank-form" onSubmit={add} style={{ marginBottom: 10 }}>
            <div>
              <label>Email đăng nhập</label>
              <input type="email" placeholder="nhanvien@gmail.com" value={email}
                     onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <label>Tên nhân viên</label>
              <input placeholder="VD: Lan (ca sáng)" value={name}
                     onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label>Mật khẩu</label>
              <input type="text" placeholder="Tối thiểu 4 ký tự" value={pw}
                     onChange={(e) => setPw(e.target.value)} required />
            </div>
          </form>
          <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy || !email.trim() || pw.length < 4}
                  onClick={add}>
            {busy ? "Đang tạo…" : "＋ Thêm nhân viên"}
          </button>
          {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
          {list === null ? <p className="hint" style={{ marginTop: 10 }}>Đang tải…</p>
            : list.length === 0 ? <p className="hint" style={{ marginTop: 10 }}>Chưa có nhân viên nào.</p>
            : (
              <ul className="canned-list" style={{ marginTop: 12 }}>
                {list.map((m) => (
                  <li key={m.username}>
                    <div><b>{m.name || m.username}</b><span>{m.username} · nhân viên</span></div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn-mini" onClick={() => resetPw(m.username)}>Đổi mật khẩu</button>
                      <button className="btn-mini danger" onClick={() => del(m.username)}>Xoá</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
        </>
      )}
    </div>
  );
}

/* Câu trả lời mẫu — chủ soạn sẵn, khi chat bấm 💬 Mẫu để chèn nhanh */
function CannedCard() {
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
