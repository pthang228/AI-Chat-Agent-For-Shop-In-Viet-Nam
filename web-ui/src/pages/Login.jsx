import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { login, register, loginWithGoogle } from "../auth.js";
import { renderGoogleButton, GOOGLE_CLIENT_ID } from "../googleAuth.js";
import { IcHome, IcMail, IcLock, IcArrow, IcSpark, IcShield, IcBack } from "../components/icons.jsx";

export default function Login() {
  const nav = useNavigate();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [remember, setRemember] = useState(true);
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
    try { await login({ username, password, remember }); nav("/"); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function demo() {
    setErr(""); setBusy(true);
    try {
      await login({ username: "demo@homestay.vn", password: "demo1234", remember: true });
    } catch {
      try { await register({ username: "demo@homestay.vn", password: "demo1234", homestay: "Shop Demo", remember: true }); }
      catch (e) { setErr(e.message); setBusy(false); return; }
    }
    setBusy(false);
    nav("/");
  }

  return (
    <div className="auth-wrap">
      <Link to="/" className="auth-back"><IcBack width={16} height={16} /> Về trang chủ</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">Chào mừng trở lại</h1>
        <p className="auth-sub">Trợ lý chăm sóc khách tự động cho shop của bạn — kết nối Zalo, Messenger, Instagram và Telegram chỉ trong vài chạm.</p>
      </div>

      <form className="auth-card" onSubmit={submit}>
        <div className="auth-tabs">
          <span className="auth-tab active">Đăng nhập</span>
          <Link to="/register" className="auth-tab">Đăng ký</Link>
        </div>

        {GOOGLE_CLIENT_ID ? (
          <div className="gbtn-wrap"><div ref={gbtn} /></div>
        ) : (
          <button type="button" className="btn-outline gbtn-fallback" disabled title="Cấu hình VITE_GOOGLE_CLIENT_ID để bật">
            <GoogleG /> Đăng nhập với Google (chưa cấu hình)
          </button>
        )}
        <div className="or">hoặc dùng email</div>

        <div className="field">
          <label className="field-label">Email</label>
          <div className="input-wrap">
            <span className="input-ico"><IcMail /></span>
            <input value={username} onChange={(e) => setU(e.target.value)} placeholder="ban@gmail.com" autoFocus />
          </div>
        </div>

        <div className="field">
          <label className="field-label">Mật khẩu</label>
          <div className="input-wrap">
            <span className="input-ico"><IcLock /></span>
            <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="••••••••" />
          </div>
        </div>

        <div className="auth-row">
          <label className="remember"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> Ghi nhớ đăng nhập</label>
          <Link to="/forgot" className="auth-link">Quên mật khẩu?</Link>
        </div>

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? "Đang đăng nhập…" : "Đăng nhập"} <IcArrow width={18} height={18} />
        </button>

        <div className="or">hoặc</div>

        <button type="button" className="btn-outline" onClick={demo} disabled={busy}>
          <IcSpark width={18} height={18} style={{ color: "var(--gold)" }} /> Dùng thử nhanh với tài khoản demo
        </button>
      </form>

      <div className="auth-foot"><IcShield width={15} height={15} /> Bảo mật chuẩn ngân hàng · Dữ liệu khách được mã hoá</div>
    </div>
  );
}

export function GoogleG() {
  return (
    <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden>
      <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.8 6.1C12.2 13.2 17.6 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.1 5.3-4.6 7l7.1 5.5c4.2-3.9 6.6-9.6 6.6-17z" />
      <path fill="#FBBC05" d="M10.4 28.3c-.5-1.4-.8-2.9-.8-4.3s.3-3 .8-4.3l-7.8-6.1C.9 16.6 0 20.2 0 24s.9 7.4 2.6 10.4l7.8-6.1z" />
      <path fill="#34A853" d="M24 48c6.2 0 11.5-2 15.3-5.5l-7.1-5.5c-2 1.4-4.6 2.2-8.2 2.2-6.4 0-11.8-3.7-13.6-9.8l-7.8 6.1C6.5 42.6 14.6 48 24 48z" />
    </svg>
  );
}
