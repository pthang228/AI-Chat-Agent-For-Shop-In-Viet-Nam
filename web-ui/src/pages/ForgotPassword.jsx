import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { forgotPassword, resetPassword } from "../auth.js";
import { IcHome, IcMail, IcLock, IcArrow, IcShield, IcBack } from "../components/icons.jsx";

// Quên mật khẩu — 3 bước: nhập email nhận mã OTP → nhập mã + mật khẩu mới → xong.
export default function ForgotPassword() {
  const nav = useNavigate();
  const [step, setStep] = useState(1);
  const [username, setU] = useState("");
  const [code, setCode] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function sendCode(e) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try { setMsg(await forgotPassword(username)); setStep(2); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  async function doReset(e) {
    e.preventDefault();
    setErr("");
    if (pw !== pw2) { setErr("Mật khẩu nhập lại không khớp"); return; }
    setBusy(true);
    try { await resetPassword({ username, code, newPassword: pw }); setStep(3); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="auth-wrap">
      <Link to="/login" className="auth-back"><IcBack width={16} height={16} /> Về đăng nhập</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">Quên mật khẩu</h1>
        <p className="auth-sub">
          {step === 1 && "Nhập email tài khoản — chúng tôi sẽ gửi mã xác nhận 6 số về hộp thư của bạn."}
          {step === 2 && "Nhập mã 6 số trong email vừa nhận và đặt mật khẩu mới."}
          {step === 3 && "Xong! Mật khẩu đã được đổi."}
        </p>
      </div>

      {step === 1 && (
        <form className="auth-card" onSubmit={sendCode}>
          <div className="field">
            <label className="field-label">Email</label>
            <div className="input-wrap">
              <span className="input-ico"><IcMail /></span>
              <input value={username} onChange={(e) => setU(e.target.value)} placeholder="ban@gmail.com" autoFocus />
            </div>
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn-primary" type="submit" disabled={busy || !username.trim()}>
            {busy ? "Đang gửi mã…" : "Gửi mã về email"} <IcArrow width={18} height={18} />
          </button>
        </form>
      )}

      {step === 2 && (
        <form className="auth-card" onSubmit={doReset}>
          {msg && <div className="msg-ok">{msg}</div>}
          <div className="field">
            <label className="field-label">Mã xác nhận (6 số)</label>
            <div className="input-wrap">
              <span className="input-ico"><IcShield /></span>
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                     placeholder="••••••" inputMode="numeric" autoComplete="one-time-code" autoFocus />
            </div>
          </div>
          <div className="field">
            <label className="field-label">Mật khẩu mới</label>
            <div className="input-wrap">
              <span className="input-ico"><IcLock /></span>
              <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder="Tối thiểu 4 ký tự" />
            </div>
          </div>
          <div className="field">
            <label className="field-label">Nhập lại mật khẩu mới</label>
            <div className="input-wrap">
              <span className="input-ico"><IcLock /></span>
              <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} placeholder="••••••••" />
            </div>
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn-primary" type="submit" disabled={busy || code.length < 6 || !pw}>
            {busy ? "Đang đặt lại…" : "Đặt mật khẩu mới"} <IcArrow width={18} height={18} />
          </button>
          <div className="or">chưa nhận được mã?</div>
          <button type="button" className="btn-outline" onClick={sendCode} disabled={busy}>
            Gửi lại mã
          </button>
        </form>
      )}

      {step === 3 && (
        <div className="auth-card">
          <div className="msg-ok">✅ Mật khẩu đã được đặt lại. Mọi thiết bị đang đăng nhập đã bị đăng xuất — hãy đăng nhập lại bằng mật khẩu mới.</div>
          <button className="btn-primary" onClick={() => nav("/login")}>
            Về trang đăng nhập <IcArrow width={18} height={18} />
          </button>
        </div>
      )}

      <div className="auth-foot"><IcShield width={15} height={15} /> Mã chỉ có hiệu lực 15 phút · Không chia sẻ mã cho bất kỳ ai</div>
    </div>
  );
}
