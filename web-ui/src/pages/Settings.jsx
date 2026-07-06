import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, isStaff, updateProfile, changePassword } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { teamApi } from "../teamApi.js";
import { IcBack, IcLogout, IcUser, IcMail, IcLock } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import BackLink from "../components/BackLink.jsx";

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

  const hostName = user?.homestay || user?.username;

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <LogoMark size={28} /> NovaChat</Link>
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

        {/* Nhân viên (team) — chỉ CHỦ shop thấy.
            Các cấu hình bot (liên hệ khẩn, tài khoản nhận tiền, lịch Google Sheets,
            câu mẫu) đã chuyển sang trang Dạy AI (ShopConfigCards.jsx). */}
        {!staff && <TeamCard />}

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
