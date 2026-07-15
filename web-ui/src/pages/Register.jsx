import { useState, useEffect, useRef } from "react";
import { useNavigate, Link } from "react-router-dom";
import { register, loginWithGoogle } from "../auth.js";
import { renderGoogleButton, GOOGLE_CLIENT_ID } from "../googleAuth.js";
import { IcHome, IcMail, IcLock, IcUser, IcArrow, IcShield, IcBack } from "../components/icons.jsx";
import { useI18n } from "../i18n.jsx";

export default function Register() {
  const nav = useNavigate();
  const { t } = useI18n();
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
      <Link to="/" className="auth-back"><IcBack width={16} height={16} /> {t("auth.back_home")}</Link>
      <div className="auth-head">
        <div className="brand-logo"><IcHome width={26} height={26} /></div>
        <h1 className="auth-title">{t("auth.reg_title")}</h1>
        <p className="auth-sub">{t("auth.sub")}</p>
      </div>

      <form className="auth-card" onSubmit={submit}>
        <div className="auth-tabs">
          <Link to="/login" className="auth-tab">{t("auth.login")}</Link>
          <span className="auth-tab active">{t("auth.register")}</span>
        </div>

        {GOOGLE_CLIENT_ID && (
          <>
            <div className="gbtn-wrap"><div ref={gbtn} /></div>
            <div className="or">{t("auth.or_email")}</div>
          </>
        )}

        <div className="field">
          <label className="field-label">{t("set.shop_label")}</label>
          <div className="input-wrap">
            <span className="input-ico"><IcUser /></span>
            <input value={homestay} onChange={(e) => setH(e.target.value)} placeholder={t("set.shop_ph")} autoFocus />
          </div>
        </div>

        <div className="field">
          <label className="field-label">{t("auth.email")}</label>
          <div className="input-wrap">
            <span className="input-ico"><IcMail /></span>
            <input value={username} onChange={(e) => setU(e.target.value)} placeholder={t("auth.email_ph")} />
          </div>
        </div>

        <div className="field">
          <label className="field-label">{t("auth.password")}</label>
          <div className="input-wrap">
            <span className="input-ico"><IcLock /></span>
            <input type="password" value={password} onChange={(e) => setP(e.target.value)} placeholder={t("set.pw_new_ph")} />
          </div>
        </div>

        <div className="field">
          <label className="field-label">{t("auth.promo_label")} <span style={{ fontWeight: 400, color: "var(--faint)" }}>{t("auth.promo_note")}</span></label>
          <div className="input-wrap">
            <span className="input-ico">🎁</span>
            <input value={promo} onChange={(e) => setPromo(e.target.value)} placeholder={t("auth.promo_ph")} />
          </div>
        </div>

        {err && <div className="err">{err}</div>}

        <button className="btn-primary" type="submit" disabled={busy}>
          {busy ? t("team.adding") : t("auth.create_btn")} <IcArrow width={18} height={18} />
        </button>
      </form>

      <div className="auth-foot"><IcShield width={15} height={15} /> {t("auth.foot")}</div>
    </div>
  );
}
