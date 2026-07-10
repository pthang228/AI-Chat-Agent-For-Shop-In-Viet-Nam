import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, isStaff, updateProfile, changePassword } from "../auth.js";
import { logoutAndStopBots } from "../session.js";
import { teamApi } from "../teamApi.js";
import { IcBack, IcLogout, IcUser, IcMail, IcLock } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import BackLink from "../components/BackLink.jsx";
import { useI18n, LANGS } from "../i18n.jsx";
import { getTheme, setTheme } from "../theme.js";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function Settings() {
  const nav = useNavigate();
  const { t } = useI18n();
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
    try { await updateProfile({ homestay, email }); setSavedMsg(t("set.saved")); }
    catch (e) { setSavedMsg("❌ " + e.message); }
  }

  async function savePassword(e) {
    e.preventDefault();
    setPwMsg("");
    try { await changePassword({ oldPassword: oldPw, newPassword: newPw }); setPwMsg(t("set.pw_done")); setOldPw(""); setNewPw(""); }
    catch (e) { setPwMsg("❌ " + e.message); }
  }

  async function doLogout() {
    if (!confirm(t("logout.confirm"))) return;
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
            <div className="hello">{t("set.account")}</div>
            <h1 className="page-title">{t("set.title")}</h1>
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
            <label className="field-label"><IcUser width={14} height={14} /> {t("set.shop_label")}</label>
            <input value={homestay} onChange={(e) => setHomestay(e.target.value)} placeholder={t("set.shop_ph")} />
          </div>
          <div className="field">
            <label className="field-label"><IcMail width={14} height={14} /> {t("set.email_label")}</label>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="ban@gmail.com" />
            <p className="hint" style={{ marginTop: 6 }}>{t("set.email_hint")}</p>
          </div>
          <div className="row" style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" type="submit">{t("set.save")}</button>
            {savedMsg && <span className="savemsg" style={{ margin: 0 }}>{savedMsg}</span>}
          </div>
        </form>

        {/* Giao diện & Ngôn ngữ */}
        <AppearanceCard />

        {/* Đổi mật khẩu */}
        <form className="panel set-card" onSubmit={savePassword} style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("set.pw_title")}</h3>
          {isGoogle && (
            <p className="hint">{t("set.pw_google_hint")}</p>
          )}
          <div className="field" style={{ marginTop: 10 }}>
            <label className="field-label"><IcLock width={14} height={14} /> {t("set.pw_cur")}</label>
            <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} placeholder={isGoogle ? t("set.pw_cur_ph_google") : "••••••••"} />
          </div>
          <div className="field">
            <label className="field-label"><IcLock width={14} height={14} /> {t("set.pw_new")}</label>
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} placeholder={t("set.pw_new_ph")} />
          </div>
          <div className="row" style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 12 }}>
            <button className="btn-primary sm" type="submit">{t("set.pw_btn")}</button>
            {pwMsg && <span className="savemsg" style={{ margin: 0 }}>{pwMsg}</span>}
          </div>
        </form>

        {/* Nhân viên (team) — chỉ CHỦ shop thấy.
            Các cấu hình bot (liên hệ khẩn, tài khoản nhận tiền, lịch Google Sheets,
            câu mẫu) đã chuyển sang trang Dạy AI (ShopConfigCards.jsx). */}
        {!staff && <TeamCard />}

        {/* Bong bóng chat tư vấn */}
        <div className="panel set-card" style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("cwc.title")}</h3>
          <p className="hint" style={{ marginBottom: 12 }}>{t("cwc.desc")}</p>
          <button className="btn-outline" style={{ width: "auto" }}
                  onClick={() => { localStorage.removeItem("hb_cw_hidden"); localStorage.removeItem("hb_cw_pos"); alert(t("cwc.shown")); }}>
            {t("cwc.show")}
          </button>
        </div>

        {/* Đăng xuất */}
        <div className="panel set-card" style={{ marginTop: 16 }}>
          <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("sess.title")}</h3>
          <p className="hint" style={{ marginBottom: 12 }}>{t("sess.desc")}</p>
          <button className="btn-outline" style={{ width: "auto", color: "var(--danger)", borderColor: "#ecc9c0" }} onClick={doLogout} disabled={busy}>
            <IcLogout width={16} height={16} /> {busy ? t("sess.busy") : t("sess.btn")}
          </button>
        </div>
      </main>
    </div>
  );
}

/* 🎨 Giao diện & Ngôn ngữ — chủ đề sáng/tối (theme.js) + tiếng Việt/English (i18n.jsx).
   Cả hai lưu localStorage, áp ngay không cần tải lại trang. */
function AppearanceCard() {
  const { t, lang, setLang } = useI18n();
  const [theme, setThemeState] = useState(getTheme());

  function pickTheme(v) {
    setTheme(v);          // ghi localStorage + đặt <html data-theme>
    setThemeState(v);
  }

  const segBtn = (active) => ({
    padding: "9px 18px", borderRadius: 999, cursor: "pointer", fontFamily: "inherit",
    fontSize: 13.5, fontWeight: 600, transition: ".15s",
    border: "1px solid " + (active ? "var(--green)" : "var(--line)"),
    background: active ? "var(--green)" : "var(--card)",
    color: active ? "#fff" : "var(--ink)",
  });

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>🎨 {t("set.appearance")}</h3>
      <p className="hint" style={{ marginBottom: 14 }}>{t("set.appearance_hint")}</p>

      <div className="field">
        <label className="field-label">{t("set.theme")}</label>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" style={segBtn(theme === "light")} onClick={() => pickTheme("light")}>{t("theme.light")}</button>
          <button type="button" style={segBtn(theme === "dark")}  onClick={() => pickTheme("dark")}>{t("theme.dark")}</button>
        </div>
      </div>

      <div className="field" style={{ marginBottom: 0 }}>
        <label className="field-label">{t("set.lang")}</label>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {LANGS.map((l) => (
            <button key={l.code} type="button" style={segBtn(lang === l.code)} onClick={() => setLang(l.code)}>
              {l.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* 👥 Nhân viên — chủ tạo tài khoản cho nhân viên trực hộp thư.
   Nhân viên đăng nhập bằng email + mật khẩu này; chỉ thấy Hội thoại / Khách hàng /
   Đơn hàng / Thống kê — không đụng được Dạy AI, kênh, gói dịch vụ. */
function TeamCard() {
  const { t } = useI18n();
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
      setMsg(t("team.created", { email: email.trim() }));
      setEmail(""); setName(""); setPw(""); load();
    } else {
      setMsg("❌ " + (r.body?.error || t("team.create_fail")));
    }
  }
  async function resetPw(username) {
    const p = prompt(t("team.pw_prompt", { u: username }));
    if (!p) return;
    const r = await teamApi.update(username, { password: p });
    setMsg(r.ok ? t("team.pw_changed", { u: username })
                : "❌ " + (r.body?.error || t("team.pw_fail")));
  }
  async function del(username) {
    if (!confirm(t("team.del_confirm", { u: username }))) return;
    const r = await teamApi.remove(username);
    if (r.ok) load();
    else setMsg("❌ " + (r.body?.error || t("team.del_fail")));
  }

  return (
    <div className="panel set-card" style={{ marginTop: 16 }}>
      <h3 style={{ fontSize: 17, marginBottom: 4 }}>{t("team.title")}</h3>
      <p className="hint" style={{ marginBottom: 12 }}>{t("team.desc")}</p>
      {list === "offline" ? (
        <p className="hint">{t("team.offline")}</p>
      ) : (
        <>
          <form className="bank-form" onSubmit={add} style={{ marginBottom: 10 }}>
            <div>
              <label>{t("team.email")}</label>
              <input type="email" placeholder="nhanvien@gmail.com" value={email}
                     onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div>
              <label>{t("team.name")}</label>
              <input placeholder={t("team.name_ph")} value={name}
                     onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label>{t("team.pw")}</label>
              <input type="text" placeholder={t("set.pw_new_ph")} value={pw}
                     onChange={(e) => setPw(e.target.value)} required />
            </div>
          </form>
          <button className="btn-primary sm" style={{ width: "auto" }} disabled={busy || !email.trim() || pw.length < 4}
                  onClick={add}>
            {busy ? t("team.adding") : t("team.add")}
          </button>
          {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}
          {list === null ? <p className="hint" style={{ marginTop: 10 }}>{t("team.loading")}</p>
            : list.length === 0 ? <p className="hint" style={{ marginTop: 10 }}>{t("team.none")}</p>
            : (
              <ul className="canned-list" style={{ marginTop: 12 }}>
                {list.map((m) => (
                  <li key={m.username}>
                    <div><b>{m.name || m.username}</b><span>{m.username} · {t("team.role")}</span></div>
                    <div style={{ display: "flex", gap: 6 }}>
                      <button className="btn-mini" onClick={() => resetPw(m.username)}>{t("team.resetpw")}</button>
                      <button className="btn-mini danger" onClick={() => del(m.username)}>{t("team.del")}</button>
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
