import { useState, useEffect } from "react";
import { zalooa } from "../zaloOaApi.js";
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

// Kết nối Zalo OA ĐA KHÁCH trong web: dán OA ID + access token (+ refresh token
// để hệ thống TỰ GIA HẠN — token Zalo chỉ sống ~25 giờ).
export default function ZaloOAConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);   // {app_configured,...} | "offline"
  const [oas, setOas] = useState([]);
  const [token, setToken] = useState("");
  const [refresh, setRefresh] = useState("");
  const [oaId, setOaId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshOas() {
    const r = await zalooa.accounts();
    if (r.ok && Array.isArray(r.body)) setOas(r.body);
  }

  useEffect(() => {
    zalooa.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshOas(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim()) {
      setMsg(t("cn2.oa_need"));
      return;
    }
    setBusy(true); setMsg("");
    const r = await zalooa.connect(token.trim(), oaId.trim(), name.trim(), refresh.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? t("cn2.oa_verified", { name: r.body.oa.name || r.body.oa.oa_id })
        : t("cn2.oa_saved", { id: r.body.oa.oa_id }));
      setToken(""); setRefresh(""); setOaId(""); setName("");
      refreshOas();
    } else {
      setMsg("❌ " + (r.body?.error || t("cn2.connect_fail")));
    }
  }

  async function disconnect(s) {
    if (!confirm(t("cn2.oa_disc", { name: s.name || s.oa_id }))) return;
    await zalooa.removeAccount(s.oa_id);
    refreshOas();
  }

  async function toggleOa(s) {
    await zalooa.accountToggle(s.oa_id, !s.bot_enabled);
    refreshOas();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn2.offline", { name: "Zalo OA", port: 5010 })}</div>
        <p className="hint">{t("cn2.run1")} <code>python -m app.main_zalo_oa</code> {t("cn2.run2")}</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/zalooa/webhook");

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="zalooa" size={22} /> {t("cn2.oa_title")}</div>

      {/* Hướng dẫn viết cho chủ shop KHÔNG RÀNH kỹ thuật — từng bước cụ thể */}
      <GuideBox
        title={t("cn2.oa_guide_title")}
        steps={[
          { t: t("cn2.oa_s1t"), d: <>{rich(t("cn2.oa_s1d"))}</> },
          { t: t("cn2.step_need"), d: <>{rich(t("cn2.oa_s2d"))}</> },
          { t: t("cn2.step_auth"), d: <>{rich(t("cn2.oa_s3d"))}</> },
          { t: t("cn2.step_paste"), d: <>{rich(t("cn2.oa_s4d"))}</> },
          { t: t("cn2.step_owner"), d: <>{rich(t("cn2.oa_s5d"))}</> },
        ]}
        note={<>{rich(t("cn2.oa_note", { url: webhookUrl }))}</>}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder={t("cn2.oa_token_ph")}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <input
          placeholder={t("cn2.oa_refresh_ph")}
          value={refresh}
          onChange={(e) => setRefresh(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.oa_id_ph")}
            value={oaId}
            onChange={(e) => setOaId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.oa_name_ph")}
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
        <h4>{t("cn2.oa_list")}</h4>
        {oas.length === 0 ? (
          <p className="hint">{t("cn2.oa_none")}</p>
        ) : (
          <ul className="page-list">
            {oas.map((s) => (
              <li key={s.oa_id} className="page-row">
                <div>
                  <div className="page-name">{s.name || s.oa_id}</div>
                  <div className="page-sub">OA ID: {s.oa_id}</div>
                  <div className="page-sub">
                    {s.has_refresh
                      ? t("cn2.oa_refresh_on")
                      : t("cn2.oa_refresh_off")}
                  </div>
                  <div className="page-sub">
                    {s.owner_registered
                      ? t("cn2.owner", { name: s.owner_name || t("cn2.owner_reg") })
                      : t("cn2.no_owner")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button
                    className={"btn-mini" + (s.bot_enabled ? "" : " danger")}
                    title={s.bot_enabled ? t("cn2.bot_on_title") : t("cn2.bot_off_title")}
                    onClick={() => toggleOa(s)}
                  >
                    {s.bot_enabled ? t("cn2.bot_on") : t("cn2.bot_off")}
                  </button>
                  <button className="btn-mini danger" onClick={() => disconnect(s)}>{t("cn2.disconnect")}</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
