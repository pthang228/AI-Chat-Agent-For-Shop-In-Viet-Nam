import { useState, useEffect } from "react";
import { shopee } from "../shopeeApi.js";
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

// Kết nối Shopee ĐA KHÁCH trong web: dán Shop ID + access token (shop đã uỷ quyền
// cho app của NovaChat trên Shopee Open Platform).
export default function ShopeeConnect() {
  const { t } = useI18n();
  const [cfg, setCfg] = useState(null);   // {partner_configured,...} | "offline"
  const [shops, setShops] = useState([]);
  const [token, setToken] = useState("");
  const [shopId, setShopId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function refreshShops() {
    const r = await shopee.shops();
    if (r.ok && Array.isArray(r.body)) setShops(r.body);
  }

  useEffect(() => {
    shopee.config().then((r) => {
      if (r.ok && r.body) { setCfg(r.body); refreshShops(); }
      else setCfg("offline");
    });
  }, []);

  async function connect() {
    if (!token.trim() || !shopId.trim()) {
      setMsg(t("cn2.shopee_need"));
      return;
    }
    setBusy(true); setMsg("");
    const r = await shopee.connect(token.trim(), shopId.trim(), name.trim());
    setBusy(false);
    if (r.ok && r.body?.ok) {
      setMsg(r.body.verified
        ? t("cn2.shopee_verified", { name: r.body.shop.name || r.body.shop.shop_id })
        : t("cn2.shopee_saved", { id: r.body.shop.shop_id }));
      setToken(""); setShopId(""); setName("");
      refreshShops();
    } else {
      setMsg("❌ " + (r.body?.error || t("cn2.connect_fail")));
    }
  }

  async function disconnect(s) {
    if (!confirm(t("cn2.shopee_disc", { name: s.name || s.shop_id }))) return;
    await shopee.removeShop(s.shop_id);
    refreshShops();
  }

  async function toggleShop(s) {
    await shopee.shopToggle(s.shop_id, !s.bot_enabled);
    refreshShops();
  }

  if (cfg === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;

  if (cfg === "offline")
    return (
      <div className="connect">
        <div className="status warn">{t("cn2.offline", { name: "Shopee", port: 5009 })}</div>
        <p className="hint">{t("cn2.run1")} <code>python -m app.main_shopee</code> {t("cn2.run2")}</p>
      </div>
    );

  const webhookUrl = (cfg.public_base_url || "<PUBLIC_BASE_URL>") + (cfg.webhook_path || "/shopee/webhook");

  return (
    <div className="connect">
      <div className="status ok"><ChannelTile ch="shopee" size={22} /> {t("cn2.connect_title", { ch: "Shopee" })}</div>

      {/* Hướng dẫn viết cho chủ shop KHÔNG RÀNH kỹ thuật — từng bước cụ thể */}
      <GuideBox
        title={t("cn2.shopee_guide_title")}
        steps={[
          { t: t("cn2.shopee_s1t"), d: <>{rich(t("cn2.shopee_s1d"))}</> },
          { t: t("cn2.step_need"), d: <>{rich(t("cn2.shopee_s2d"))}</> },
          { t: t("cn2.step_auth"), d: <>{rich(t("cn2.shopee_s3d"))}</> },
          { t: t("cn2.step_paste"), d: <>{rich(t("cn2.shopee_s4d"))}</> },
          { t: t("cn2.step_owner"), d: <>{rich(t("cn2.shopee_s5d"))}</> },
        ]}
        note={<>{rich(t("cn2.shopee_note", { url: webhookUrl }))}</>}
      />

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
        <input
          placeholder={t("cn2.shopee_token_ph")}
          value={token}
          onChange={(e) => setToken(e.target.value)}
        />
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.shopee_shopid_ph")}
            value={shopId}
            onChange={(e) => setShopId(e.target.value)}
          />
          <input
            style={{ flex: 1, minWidth: 160 }}
            placeholder={t("cn2.shopee_name_ph")}
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
        <h4>{t("cn2.shopee_list")}</h4>
        {shops.length === 0 ? (
          <p className="hint">{t("cn2.shopee_none")}</p>
        ) : (
          <ul className="page-list">
            {shops.map((s) => (
              <li key={s.shop_id} className="page-row">
                <div>
                  <div className="page-name">{s.name || s.shop_id}</div>
                  <div className="page-sub">Shop ID: {s.shop_id}</div>
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
                    onClick={() => toggleShop(s)}
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
