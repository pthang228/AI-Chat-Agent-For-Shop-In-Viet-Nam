import { useState, useEffect, useRef } from "react";
import { tg } from "../telegramApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

// Kết nối Telegram ĐA KHÁCH ngay trong web: dán token bot (@BotFather) → tự động.
// Mỗi bot tự đăng nhập "acc gọi" (Telethon) bằng QR để gọi điện cho chủ.
export default function TelegramConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);   // {setup_code,...} | "offline"
  const [bots, setBots] = useState([]);
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  // Đăng nhập acc gọi (QR)
  const [loginBot, setLoginBot] = useState(null);   // bot_id đang đăng nhập | null
  const [login, setLogin] = useState(null);         // {state, png, profile, error}
  const [pw, setPw] = useState("");
  const [pwBusy, setPwBusy] = useState(false);
  const poll = useRef(null);

  async function refreshBots() {
    const r = await tg.bots();
    if (r.ok && Array.isArray(r.body)) setBots(r.body);
  }

  useEffect(() => {
    tg.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshBots(); }
      else setCfg("offline");
    });
  }, []);

  // Poll trạng thái đăng nhập trong lúc mở modal QR
  useEffect(() => {
    clearInterval(poll.current);
    if (!loginBot) return;
    poll.current = setInterval(async () => {
      const { ok, body } = await tg.callerLoginStatus(loginBot);
      if (!ok || !body) return;
      setLogin(body);
      if (["done", "expired", "error", "need_password"].includes(body.state)) {
        clearInterval(poll.current);
        if (body.state === "done") {
          await refreshBots();
          setTimeout(() => setLoginBot(null), 900);
        }
      }
    }, 2000);
    return () => clearInterval(poll.current);
  }, [loginBot]);

  async function connect() {
    if (!token.trim()) return;
    setBusy(true); setMsg("");
    const r = await tg.connect(token.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(t("cn.tg_connected", { name: r.body.bot.username || r.body.bot.bot_id }));
      setToken("");
      refreshBots();
    } else {
      setMsg("❌ " + (r.body?.error || t("cn.connect_fail")));
    }
  }

  async function disconnect(bot) {
    const name = bot.username ? `@${bot.username}` : bot.bot_id;
    if (!confirm(t("cn.tg_disconnect_confirm", { name }))) return;
    await tg.removeBot(bot.bot_id);
    refreshBots();
  }

  async function toggleBot(bot) {
    await tg.botToggle(bot.bot_id, !bot.bot_enabled);
    refreshBots();
  }

  async function openLogin(botId) {
    setPw(""); setLogin({ state: "starting" }); setLoginBot(botId);
    const r = await tg.callerQrLogin(botId);
    if (r.ok && r.body) setLogin(r.body);
    else setLogin({ state: "error", error: t("cn.tg_server_unreachable") });
  }

  function closeLogin() {
    clearInterval(poll.current);
    if (login && login.state !== "done") tg.callerLogout(loginBot);  // dọn phiên dở
    setLoginBot(null); setLogin(null); setPw("");
  }

  async function sendPassword() {
    if (!pw.trim()) return;
    setPwBusy(true);
    const r = await tg.callerPassword(loginBot, pw);
    setPwBusy(false);
    if (r.ok && r.body?.ok) {
      setLogin({ state: "done", profile: r.body.profile });
      await refreshBots();
      setTimeout(() => setLoginBot(null), 900);
    } else {
      setLogin((s) => ({ ...s, state: "need_password", error: r.body?.error || t("cn.tg_wrong_password") }));
      setPw("");
    }
  }

  async function callerLogout(botId) {
    if (!confirm(t("cn.tg_caller_logout_confirm"))) return;
    await tg.callerLogout(botId);
    refreshBots();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">{t("cn.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn.tg_offline")}</div>
        <p className="hint">{t("cn.offline_run_pre")} <code>python -m app.main_telegram</code> {t("cn.offline_run_post")}</p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="telegram" size={22} /> {t("cn.tg_title")}</div>

      <GuideBox
        title={t("cn.tg_guide_title")}
        steps={[
          { t: t("cn.tg_g1_t"), d: <>{t("cn.tg_g1_d1")} <b>@BotFather</b> → {t("cn.tg_g1_d2")} <code>/newbot</code> → {t("cn.tg_g1_d3")} <b>{t("cn.tg_token_word")}</b> {t("cn.tg_g1_d4")} <code>123456:ABC…</code>{t("cn.tg_g1_d5")} <b>{t("cn.tg_connect_btn")}</b>{t("cn.tg_g1_d6")}</> },
          { t: t("cn.tg_g2_t"), d: <>{t("cn.tg_g2_d1")} <b>{t("cn.tg_reg_owner")}</b> {t("cn.tg_g2_d2")} <b>Start</b> {t("cn.tg_g2_d3")} <code>/chunha</code>{t("cn.tg_g2_d4")} <b>{t("cn.tg_g2_b")}</b> {t("cn.tg_g2_d5")}</> },
          { t: t("cn.tg_g3_t"), d: <>{t("cn.tg_g3_d1")} <b>{t("cn.tg_caller_login_btn")}</b> {t("cn.tg_g3_d2")} <b>{t("cn.tg_g3_b")}</b> {t("cn.tg_g3_d3")}</> },
        ]}
        note={
          <>
            ☎️ <b>{t("cn.tg_note_b1")}</b>, {t("cn.tg_note_d1")} <b>{t("cn.tg_note_b2")}</b> {t("cn.tg_note_d2")} <b>{t("cn.tg_note_b3")}</b> {t("cn.tg_note_d3")}
          </>
        }
      />

      <div style={{ display: "flex", gap: 8, marginTop: 6 }}>
        <input
          style={{ flex: 1 }}
          placeholder={t("cn.tg_token_ph")}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <button className="btn-primary sm" onClick={connect} disabled={busy}>
          {busy ? t("cn.connecting") : t("cn.tg_connect_btn")}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>{t("cn.tg_bots_title")}</h4>
        {bots.length === 0 ? (
          <p className="hint">{t("cn.tg_no_bots")}</p>
        ) : (
          <ul className="page-list">
            {bots.map((b) => (
              <li key={b.bot_id} className="page-row">
                <div>
                  <div className="page-name">@{b.username || b.bot_id}</div>
                  <div className="page-sub">
                    {b.owner_registered
                      ? t("cn.tg_owner_line", { name: b.owner_name || t("cn.tg_owner_registered") })
                      : t("cn.tg_no_owner")}
                  </div>
                  <div className="page-sub">
                    {b.caller_logged_in
                      ? t("cn.tg_caller_line", { name: `${b.caller_name || ""}${b.caller_username ? ` (@${b.caller_username})` : ""}` })
                      : t("cn.tg_no_caller")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (b.bot_enabled ? "" : " danger")}
                    title={b.bot_enabled ? t("cn.tg_bot_on_title") : t("cn.tg_bot_off_title")}
                    onClick={() => toggleBot(b)}
                  >
                    {b.bot_enabled ? t("cn.tg_bot_on") : t("cn.tg_bot_off")}
                  </button>
                  {!b.owner_registered && b.owner_link && (
                    <a className="btn-mini" href={b.owner_link} target="_blank" rel="noreferrer">{t("cn.tg_reg_owner")}</a>
                  )}
                  {b.caller_logged_in
                    ? <button className="btn-mini" onClick={() => callerLogout(b.bot_id)}>{t("cn.tg_caller_logout_btn")}</button>
                    : <button className="btn-mini" onClick={() => openLogin(b.bot_id)}>{t("cn.tg_caller_login_btn")}</button>}
                  {b.link && <a className="btn-mini" href={b.link} target="_blank" rel="noreferrer">{t("cn.tg_open_chat")}</a>}
                  <button className="btn-mini danger" onClick={() => disconnect(b)}>{t("cn.disconnect_btn")}</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      {loginBot && login && (
        <div className="tg-modal-overlay" onClick={closeLogin}>
          <div className="tg-modal" onClick={(e) => e.stopPropagation()}>
            <h4 style={{ marginTop: 0 }}>{t("cn.tg_modal_title")}</h4>

            {login.state === "starting" && <p className="hint">{t("cn.qr_creating")}</p>}

            {login.state === "pending" && (
              <>
                <p className="hint">
                  {t("cn.tg_pend_d1")} <b>Telegram</b> {t("cn.tg_pend_d2")} <b>{t("cn.tg_pend_b1")}</b> {t("cn.tg_pend_d3")} <b>{t("cn.tg_pend_b2")}</b>.
                </p>
                {login.png && <img src={login.png} alt="QR" style={{ width: 220, height: 220, display: "block", margin: "8px auto" }} />}
                <p className="hint" style={{ textAlign: "center" }}>{t("cn.tg_qr_auto_refresh")}</p>
              </>
            )}

            {login.state === "need_password" && (
              <>
                <p className="hint">{t("cn.tg_2fa_d1")} <b>{t("cn.tg_2fa_b")}</b>. {t("cn.tg_2fa_d2")}</p>
                <input
                  type="password"
                  style={{ width: "100%" }}
                  placeholder={t("cn.tg_2fa_ph")}
                  value={pw}
                  onChange={(e) => setPw(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendPassword()}
                />
                {login.error && <div className="status warn" style={{ marginTop: 8 }}>❌ {login.error}</div>}
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={sendPassword} disabled={pwBusy}>
                  {pwBusy ? t("cn.tg_verifying") : t("cn.tg_confirm")}
                </button>
              </>
            )}

            {login.state === "done" && (
              <div className="status ok">
                {t("cn.tg_login_done")}{login.profile?.first_name ? `: ${login.profile.first_name}` : ""}
                {login.profile?.username ? ` (@${login.profile.username})` : ""}
              </div>
            )}

            {login.state === "expired" && (
              <>
                <div className="status warn">{t("cn.tg_qr_expired")}</div>
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={() => openLogin(loginBot)}>{t("cn.tg_new_qr")}</button>
              </>
            )}

            {login.state === "error" && (
              <>
                <div className="status warn">❌ {login.error || t("cn.tg_login_error")}</div>
                <button className="btn-primary sm" style={{ marginTop: 10 }} onClick={() => openLogin(loginBot)}>{t("cn.retry")}</button>
              </>
            )}

            <button className="btn-mini" style={{ marginTop: 12 }} onClick={closeLogin}>{t("cn.close")}</button>
          </div>
        </div>
      )}
    </div>
  );
}
