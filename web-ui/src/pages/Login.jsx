import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { login, register, loginWithGoogle } from "../auth.js";
import { renderGoogleButton, GOOGLE_CLIENT_ID } from "../googleAuth.js";
import { IcHome, IcMail, IcLock, IcArrow, IcSpark, IcShield, IcBack } from "../components/icons.jsx";
import { useI18n } from "../i18n.jsx";

export default function Login() {
  const nav = useNavigate();
  const { t } = useI18n();
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
      <Link to="/" className="auth-back"><IcBack width={16} height={16} /> {t("auth.back_home")}</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">{t("auth.login_title")}</h1>
        <p className="auth-sub">{t("auth.sub")}</p>
      </div>

      <form className="auth-card" onSubmit={submit}>
        <div className="auth-tabs">
          <span className="auth-tab active">{t("auth.login")}</span>
          <Link to="/register" className="auth-tab">{t("auth.register")}</Link>
        </div>

        {GOOGLE_CLIENT_ID && (
          <>
            <div className="gbtn-wrap"><div ref={gbtn} /></div>
            <div className="or">{t("auth.or_email")}</div>
          </>
        )}

        <div className="field">
          <label className="field-label">{t("auth.email")}</label>
          <div className="input-wrap">
            <span className="input-ico"><IcMail /></span>
            <input value={username} onChange={(e) => setU(e.target.value)} placeholder={t("auth.email_ph")} autoFocus />
          </div>
        </div>

        <div className="field">
          <label className="field-label">{t("auth.password")}</label>
          <div className="input-wrap">
            <span className="input-ico"><IcLock /></span>
            <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder="••••••••" />
          </div>
        </div>

        <div className="auth-row">
          <label className="remember"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> {t("auth.remember")}</label>
          <Link to="/forgot" className="auth-link">{t("auth.forgot_link")}</Link>
        </div>

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? t("auth.logging_in") : t("auth.login")} <IcArrow width={18} height={18} />
        </button>

        <div className="or">{t("auth.or")}</div>

        <button type="button" className="btn-outline" onClick={demo} disabled={busy}>
          <IcSpark width={18} height={18} style={{ color: "var(--gold)" }} /> {t("auth.demo_btn")}
        </button>
      </form>

      <div className="auth-foot"><IcShield width={15} height={15} /> {t("auth.foot")}</div>
    </div>
  );
}
