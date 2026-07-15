import { useState, useEffect } from "react";
import { meta, loadFbSdk, fbLogin, buildScope } from "../metaApi.js";
import GuideBox from "./GuideBox.jsx";
import { ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

// Màn "Kết nối Facebook" cho 1 app kênh Messenger/Instagram.
// Khách bấm đăng nhập FB → chọn Page → backend lưu token + subscribe webhook.
export default function MetaConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);       // {app_id, configured} | "offline"
  const [pages, setPages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshPages() {
    const r = await meta.pages();
    if (r.ok && Array.isArray(r.body)) setPages(r.body);
  }

  useEffect(() => {
    let alive = true;
    meta.config().then((r) => {
      if (!alive) return;
      if (r.ok && r.body) { setCfg(r.body); refreshPages(); }
      else setCfg("offline");
    });
    return () => { alive = false; };
  }, []);

  async function connect() {
    setMsg(""); setBusy(true);
    try {
      const FB = await loadFbSdk(cfg.app_id);
      const userToken = await fbLogin(FB, buildScope(cfg.enable_ig));
      const r = await meta.connect(userToken);
      if (r.ok && r.body?.ok) {
        const n = r.body.pages?.length || 0;
        setMsg(t("cn.meta_connected_n", { n }) + (r.body.pages?.some(p => !p.subscribed) ? " " + t("cn.meta_sub_warn") : ""));
        await refreshPages();
      } else {
        setMsg("❌ " + (r.body?.error || t("cn.connect_fail")));
      }
    } catch (e) {
      setMsg("❌ " + e.message);
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(pageId) {
    if (!confirm(t("cn.meta_disconnect_confirm"))) return;
    await meta.removePage(pageId);
    refreshPages();
  }

  if (cfg === null) return <div className="connect"><div className="status muted">{t("cn.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn.meta_offline")}</div>
        <p className="hint">{t("cn.offline_run_pre")} <code>python scripts/run_meta.py</code> {t("cn.offline_run_post")}</p>
      </div>
    );

  if (!cfg.configured)
    return (
      <div className="connect">
        <div className="status warn">{t("cn.meta_not_configured")}</div>
        <p className="hint">
          {t("cn.meta_cfg_1")} <code>FB_APP_ID</code> {t("cn.meta_cfg_2")} <code>FB_APP_SECRET</code> {t("cn.meta_cfg_3")} <code>.env</code> {t("cn.meta_cfg_4")}
        </p>
      </div>
    );

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="meta" size={22} /> {t("cn.meta_title")}{cfg.enable_ig ? " / Instagram" : ""}</div>

      <GuideBox
        title={t("cn.meta_guide_title")}
        steps={[
          { t: t("cn.meta_g1_t"), d: <>{t("cn.meta_g1_d1")} <b>{t("cn.meta_login_btn")}</b> {t("cn.meta_g1_d2")} <b>{t("cn.meta_g1_b2")}</b>{t("cn.meta_g1_d3")}</> },
          { t: t("cn.meta_g2_t"), d: <>{t("cn.meta_g2_d1")}{cfg.enable_ig ? " " + t("cn.meta_g2_ig") : ""}. {t("cn.meta_g2_d2")} <b>{t("cn.meta_g2_b")}</b> {t("cn.meta_g2_d3")}</> },
          { t: t("cn.meta_g3_t"), d: <>{t("cn.meta_g3_d")} <b>{t("cn.tab_customers")}</b>.</> },
        ]}
        note={<>{t("cn.meta_note")}</>}
      />
      {!cfg.enable_ig && (
        <p className="hint">
          {t("cn.meta_ig_off1")} <b>{t("cn.meta_ig_off_b")}</b>. {t("cn.meta_ig_off2")} <code>FB_ENABLE_IG=true</code> {t("cn.meta_ig_off3")} <code>.env</code> {t("cn.meta_ig_off4")}
        </p>
      )}

      <button className="btn-fb" onClick={connect} disabled={busy}>
        <span className="fb-ico">f</span>{busy ? t("cn.connecting") : t("cn.meta_login_btn")}
      </button>
      {msg && <div className="savemsg" style={{ marginTop: 10 }}>{msg}</div>}

      <div className="pages">
        <h4>{t("cn.meta_pages_title")}</h4>
        {pages.length === 0 ? (
          <p className="hint">{t("cn.meta_no_pages")}</p>
        ) : (
          <ul className="page-list">
            {pages.map((p) => (
              <li key={p.page_id} className="page-row">
                <div>
                  <div className="page-name">{p.name || p.page_id}</div>
                  <div className="page-sub">
                    Messenger {p.has_ig ? `· Instagram @${p.ig_username || ""}` : ""}
                  </div>
                </div>
                <button className="btn-mini danger" onClick={() => disconnect(p.page_id)}>{t("cn.disconnect_btn")}</button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
