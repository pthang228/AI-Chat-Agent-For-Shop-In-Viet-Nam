import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { forgotPassword, resetPassword } from "../auth.js";
import { IcHome, IcMail, IcLock, IcArrow, IcShield, IcBack } from "../components/icons.jsx";
import { useI18n } from "../i18n.jsx";

// Quên mật khẩu — 3 bước: nhập email nhận mã OTP → nhập mã + mật khẩu mới → xong.
export default function ForgotPassword() {
  const nav = useNavigate();
  const { t } = useI18n();
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
    if (pw !== pw2) { setErr(t("auth.fp_mismatch")); return; }
    setBusy(true);
    try { await resetPassword({ username, code, newPassword: pw }); setStep(3); }
    catch (e) { setErr(e.message); }
    finally { setBusy(false); }
  }

  return (
    <div className="auth-wrap">
      <Link to="/login" className="auth-back"><IcBack width={16} height={16} /> {t("auth.back_login")}</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">{t("auth.fp_title")}</h1>
        <p className="auth-sub">
          {step === 1 && t("auth.fp_step1")}
          {step === 2 && t("auth.fp_step2")}
          {step === 3 && t("auth.fp_step3")}
        </p>
      </div>

      {step === 1 && (
        <form className="auth-card" onSubmit={sendCode}>
          <div className="field">
            <label className="field-label">{t("auth.email")}</label>
            <div className="input-wrap">
              <span className="input-ico"><IcMail /></span>
              <input value={username} onChange={(e) => setU(e.target.value)} placeholder={t("auth.email_ph")} autoFocus />
            </div>
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn-primary" type="submit" disabled={busy || !username.trim()}>
            {busy ? t("auth.fp_sending") : t("auth.fp_send_btn")} <IcArrow width={18} height={18} />
          </button>
        </form>
      )}

      {step === 2 && (
        <form className="auth-card" onSubmit={doReset}>
          {msg && <div className="msg-ok">{msg}</div>}
          <div className="field">
            <label className="field-label">{t("auth.fp_code_label")}</label>
            <div className="input-wrap">
              <span className="input-ico"><IcShield /></span>
              <input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                     placeholder="••••••" inputMode="numeric" autoComplete="one-time-code" autoFocus />
            </div>
          </div>
          <div className="field">
            <label className="field-label">{t("set.pw_new")}</label>
            <div className="input-wrap">
              <span className="input-ico"><IcLock /></span>
              <input type="password" value={pw} onChange={(e) => setPw(e.target.value)} placeholder={t("set.pw_new_ph")} />
            </div>
          </div>
          <div className="field">
            <label className="field-label">{t("auth.fp_pw2")}</label>
            <div className="input-wrap">
              <span className="input-ico"><IcLock /></span>
              <input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} placeholder="••••••••" />
            </div>
          </div>
          {err && <div className="err">{err}</div>}
          <button className="btn-primary" type="submit" disabled={busy || code.length < 6 || !pw}>
            {busy ? t("auth.fp_resetting") : t("auth.fp_reset_btn")} <IcArrow width={18} height={18} />
          </button>
          <div className="or">{t("auth.fp_no_code")}</div>
          <button type="button" className="btn-outline" onClick={sendCode} disabled={busy}>
            {t("auth.fp_resend")}
          </button>
        </form>
      )}

      {step === 3 && (
        <div className="auth-card">
          <div className="msg-ok">{t("auth.fp_done")}</div>
          <button className="btn-primary" onClick={() => nav("/login")}>
            {t("auth.fp_back_btn")} <IcArrow width={18} height={18} />
          </button>
        </div>
      )}

      <div className="auth-foot"><IcShield width={15} height={15} /> {t("auth.fp_foot")}</div>
    </div>
  );
}
