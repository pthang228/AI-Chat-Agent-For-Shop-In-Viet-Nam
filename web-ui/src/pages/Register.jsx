import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { register, loginWithGoogle } from "../auth.js";
import { renderGoogleButton, GOOGLE_CLIENT_ID } from "../googleAuth.js";
import { GoogleG } from "./Login.jsx";
import { IcHome, IcMail, IcLock, IcUser, IcArrow, IcShield, IcBack } from "../components/icons.jsx";

export default function Register() {
  const nav = useNavigate();
  const [homestay, setH] = useState("");
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [promo, setPromo] = useState("");
  const [err, setErr] = useState("");
  const gbtn = useRef(null);

  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (GOOGLE_CLIENT_ID && gbtn.current) {
      renderGoogleButton(gbtn.current, async (u) => {
        try { await loginWithGoogle(u); nav("/"); } catch (e) { setErr(e.message); }
      }).catch(() => {});
    }
  }, []);

  async function submit(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try { await register({ username, password, homestay, promo }); nav("/"); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="auth-wrap">
      <Link to="/" className="auth-back"><IcBack width={16} height={16} /> Về trang chủ</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">Tạo tài khoản mới</h1>
        <p className="auth-sub">Trợ lý chăm sóc khách tự động cho shop của bạn — kết nối Zalo, Messenger, Instagram và Telegram chỉ trong vài chạm.</p>
      </div>

      <form className="auth-card" onSubmit={submit}>
        <div className="auth-tabs">
          <Link to="/login" className="auth-tab">Đăng nhập</Link>
          <span className="auth-tab active">Đăng ký</span>
        </div>

        {GOOGLE_CLIENT_ID ? (
          <div className="gbtn-wrap"><div ref={gbtn} /></div>
        ) : (
          <button type="button" className="btn-outline gbtn-fallback" disabled title="Cấu hình VITE_GOOGLE_CLIENT_ID để bật">
            <GoogleG /> Đăng ký với Google (chưa cấu hình)
          </button>
        )}
        <div className="or">hoặc dùng email</div>

        <div className="field">
          <label className="field-label">Tên shop / thương hiệu</label>
          <div className="input-wrap">
            <span className="input-ico"><IcUser /></span>
            <input value={homestay} onChange={(e) => setH(e.target.value)} placeholder="VD: Mia Spa & Nail" autoFocus />
          </div>
        </div>

        <div className="field">
          <label className="field-label">Email</label>
          <div className="input-wrap">
            <span className="input-ico"><IcMail /></span>
            <input value={username} onChange={(e) => setU(e.target.value)} placeholder="ban@gmail.com" />
          </div>
        </div>

        <div className="field">
          <label className="field-label">Mật khẩu</label>
          <div className="input-wrap">
            <span className="input-ico"><IcLock /></span>
            <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="Tối thiểu 4 ký tự" />
          </div>
        </div>

        <div className="field">
          <label className="field-label">Mã giới thiệu <span style={{ fontWeight: 400, color: "var(--faint)" }}>(nếu có — tặng 7 ngày dùng thử)</span></label>
          <div className="input-wrap">
            <span className="input-ico">🎁</span>
            <input value={promo} onChange={(e) => setPromo(e.target.value)} placeholder="Không bắt buộc" />
          </div>
        </div>

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? "Đang tạo…" : "Tạo tài khoản"} <IcArrow width={18} height={18} />
        </button>
      </form>

      <div className="auth-foot"><IcShield width={15} height={15} /> Bảo mật chuẩn ngân hàng · Dữ liệu khách được mã hoá</div>
    </div>
  );
}
