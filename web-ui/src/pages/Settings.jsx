import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, updateProfile, changePassword } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { IcHome, IcBack, IcLogout, IcUser, IcMail, IcLock } from "../components/icons.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function Settings() {
  const nav = useNavigate();
  const user = currentUser();
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
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <span className="brand-mini" style={{ marginLeft: -4 }}><IcHome width={18} height={18} /></span> Homestay Bot</Link>
        </div>
        <div className="user">
          <span className="user-pill"><span className="avatar">{initials(hostName)}</span>{hostName}</span>
        </div>
      </header>

      <main className="content narrow" style={{ maxWidth: 640 }}>
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
            <label className="field-label"><IcUser width={14} height={14} /> Tên homestay</label>
            <input value={homestay} onChange={(e) => setHomestay(e.target.value)} placeholder="VD: Haru Staycation" />
          </div>
          <div className="field">
            <label className="field-label"><IcMail width={14} height={14} /> Email liên hệ</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ban@homestay.vn" />
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
