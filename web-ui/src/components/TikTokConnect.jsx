import { useState, useEffect } from "react";
import { tiktok } from "../tiktokApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

// Mini-markdown → JSX: **đậm**, *nghiêng*, `code` (giữ định dạng trong chuỗi dịch)
function rich(s) {
  return String(s).split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <b key={i}>{p.slice(2, -2)}</b>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <i key={i}>{p.slice(1, -1)}</i>;
    return p;
  });
}

// Kết nối TikTok ĐA KHÁCH trong web: dán access token TikTok Business + business ID.
export default function TikTokConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);   // {verify_token,...} | "offline"
  const [accounts, setAccounts] = useState([]);
  const [token, setToken] = useState("");
  const [bizId, setBizId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshAccounts() {
    const r = await tiktok.accounts();
    if (r.ok && Array.isArray(r.body)) setAccounts(r.body);
  }

  useEffect(() => {
    tiktok.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshAccounts(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim() || !bizId.trim()) {
      setMsg(t("cn2.tiktok_need"));
      return;
    }
    setBusy(true); setMsg("");
    const r = await tiktok.connect(token.trim(), bizId.trim(), name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? t("cn2.tiktok_verified", { name: r.body.account.name || r.body.account.business_id })
        : t("cn2.tiktok_saved", { id: r.body.account.business_id }));
      setToken(""); setBizId(""); setName("");
      refreshAccounts();
    } else {
      setMsg("❌ " + (r.body?.error || t("cn2.connect_fail")));
    }
  }

  async function disconnect(a) {
    if (!confirm(t("cn2.tiktok_disc", { name: a.name || a.business_id }))) return;
    await tiktok.removeAccount(a.business_id);
    refreshAccounts();
  }

  async function toggleAccount(a) {
    await tiktok.accountToggle(a.business_id, !a.bot_enabled);
    refreshAccounts();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn2.offline", { name: "TikTok", port: 5008 })}</div>
        <p className="hint">{t("cn2.run1")} <code>python -m app.main_tiktok</code> {t("cn2.run2")}</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/tiktok/webhook");

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="tiktok" size={22} /> {t("cn2.connect_title", { ch: "TikTok" })}</div>

      <GuideBox
        title={t("cn2.tiktok_guide_title")}
        steps={[
          { t: t("cn2.tiktok_s1t"), d: <>{rich(t("cn2.tiktok_s1d"))}</> },
          { t: t("cn2.tiktok_s2t"), d: <>{rich(t("cn2.tiktok_s2d"))}</> },
          { t: t("cn2.tiktok_s3t"), d: <>{rich(t("cn2.tiktok_s3d", { url: webhookUrl, vt: cfg.verify_token || "" }))}</> },
          { t: t("cn2.tiktok_s4t"), d: <>{rich(t("cn2.tiktok_s4d"))}</> },
        ]}
        note={<>{rich(t("cn2.tiktok_note"))}</>}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder={t("cn2.tiktok_token_ph")}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.tiktok_bizid_ph")}
            value={bizId}
            onChange={(e) => setBizId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.tiktok_name_ph")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button className="btn-primary sm" onClick={connect} disabled={busy}>
            {busy ? t("cn2.connecting") : t("cn2.connect")}
          </button>
        </div>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>{t("cn2.tiktok_list")}</h4>
        {accounts.length === 0 ? (
          <p className="hint">{t("cn2.tiktok_none")}</p>
        ) : (
          <ul className="page-list">
            {accounts.map((a) => (
              <li key={a.business_id} className="page-row">
                <div>
                  <div className="page-name">
                    {a.name || a.username || a.business_id}
                    {a.username && ` (@${a.username})`}
                  </div>
                  <div className="page-sub">Business ID: {a.business_id}</div>
                  <div className="page-sub">
                    {a.owner_registered
                      ? t("cn2.owner", { name: a.owner_name || t("cn2.owner_reg") })
                      : t("cn2.no_owner")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (a.bot_enabled ? "" : " danger")}
                    title={a.bot_enabled ? t("cn2.bot_on_title") : t("cn2.bot_off_title")}
                    onClick={() => toggleAccount(a)}
                  >
                    {a.bot_enabled ? t("cn2.bot_on") : t("cn2.bot_off")}
                  </button>
                  <button className="btn-mini danger" onClick={() => disconnect(a)}>{t("cn2.disconnect")}</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
