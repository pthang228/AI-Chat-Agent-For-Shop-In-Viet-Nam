import { useState, useEffect } from "react";
import { webchat } from "../webchatApi.js";
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

/*
 * Kết nối kênh Website — KHÔNG token, KHÔNG chờ duyệt: tạo site → nhận mã nhúng
 * 1 dòng <script> → chủ shop dán vào website của họ là bong bóng chat hiện ngay.
 */
export default function WebChatConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);   // {public_base_url,...} | "offline"
  const [sites, setSites] = useState([]);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [copied, setCopied] = useState("");   // site_id vừa copy

  async function refreshSites() {
    const r = await webchat.sites();
    if (r.ok && Array.isArray(r.body)) setSites(r.body);
  }

  useEffect(() => {
    webchat.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshSites(); }
      else setCfg("offline");
    });
  }, []);

  async function createSite() {
    setBusy(true); setMsg("");
    const r = await webchat.createSite(name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(t("cn2.web_created", { name: r.body.site.name }));
      setName("");
      refreshSites();
    } else {
      setMsg("❌ " + (r.body?.error || t("cn2.web_create_fail")));
    }
  }

  async function copySnippet(s) {
    try {
      await navigator.clipboard.writeText(s.snippet);
      setCopied(s.site_id);
      setTimeout(() => setCopied(""), 2000);
    } catch {
      prompt(t("cn2.web_copy_manual"), s.snippet);
    }
  }

  async function removeSite(s) {
    if (!confirm(t("cn2.web_del_confirm", { name: s.name || s.site_id }))) return;
    await webchat.removeSite(s.site_id);
    refreshSites();
  }

  async function toggleSite(s) {
    await webchat.siteToggle(s.site_id, !s.bot_enabled);
    refreshSites();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn2.offline", { name: "Webchat", port: 5011 })}</div>
        <p className="hint">{t("cn2.run1")} <code>python -m app.main_webchat</code> {t("cn2.run2")}</p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="webchat" size={22} /> {t("cn2.web_title")}</div>

      {/* Hướng dẫn cho chủ shop KHÔNG RÀNH kỹ thuật */}
      <GuideBox
        title={t("cn2.web_guide_title")}
        steps={[
          { t: t("cn2.web_s1t"), d: <>{rich(t("cn2.web_s1d"))}</> },
          { t: t("cn2.web_s2t"), d: <>{rich(t("cn2.web_s2d"))}</> },
          { t: t("cn2.web_s3t"), d: <>{rich(t("cn2.web_s3d"))}</> },
          { t: t("cn2.web_s4t"), d: <>{rich(t("cn2.web_s4d"))}</> },
          { t: t("cn2.web_s5t"), d: <>{rich(t("cn2.web_s5d"))}</> },
        ]}
        note={<>{rich(t("cn2.web_note", { url: cfg.public_base_url || t("cn2.web_nourl") }))}</>}
      />

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 6 }}>
        <input
          style={{ flex: 1, minWidth: 200 }}
          placeholder={t("cn2.web_name_ph")}
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <button className="btn-primary sm" onClick={createSite} disabled={busy}>
          {busy ? t("team.adding") : t("cn2.web_create")}
        </button>
      </div>
      {msg && <div className="savemsg" style={{ marginTop: 8 }}>{msg}</div>}

      <div className="pages" style={{ marginTop: 14 }}>
        <h4>{t("cn2.web_sites")}</h4>
        {sites.length === 0 ? (
          <p className="hint">{t("cn2.web_none")}</p>
        ) : (
          <ul className="page-list">
            {sites.map((s) => (
              <li key={s.site_id} className="page-row">
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="page-name">{s.name || s.site_id}</div>
                  <div className="page-sub">{t("cn2.web_site_code", { id: s.site_id })}</div>
                  <div className="page-sub" style={{ wordBreak: "break-all" }}>
                    <code style={{ fontSize: 11 }}>{s.snippet}</code>
                  </div>
                  <div className="page-sub">
                    {s.owner_registered
                      ? t("cn2.owner", { name: s.owner_name || t("cn2.owner_reg") })
                      : t("cn2.no_owner")}
                  </div>
                </div>
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", justifyContent: "flex-end" }}>
                  <button className="btn-mini" onClick={() => copySnippet(s)}>
                    {copied === s.site_id ? t("cn2.web_copied") : t("cn2.web_copy")}
                  </button>
                  <button
                    className={"btn-mini" + (s.bot_enabled ? "" : " danger")}
                    title={s.bot_enabled ? t("cn2.bot_on_title") : t("cn2.bot_off_title")}
                    onClick={() => toggleSite(s)}
                  >
                    {s.bot_enabled ? t("cn2.bot_on") : t("cn2.bot_off")}
                  </button>
                  <button className="btn-mini danger" onClick={() => removeSite(s)}>{t("team.del")}</button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
