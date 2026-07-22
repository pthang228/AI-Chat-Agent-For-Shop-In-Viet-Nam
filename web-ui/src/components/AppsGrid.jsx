import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { logout } from "../auth.js";
import { getApps, addApp, removeApp } from "../store.js";
import { brain } from "../brainApi.js";
import { IcPlus, IcSpark, IcChev } from "./icons.jsx";
import { ChannelIcon, ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

// icon = key kênh cho <ChannelIcon/> (logo thương hiệu thật, không dùng emoji)
export const CHANNELS = {
  zalo:      { label: "Zalo",            icon: "zalo",      color: "#0068ff" },
  meta:      { label: "Mess + Instagram", icon: "meta",      color: "#7b3fb3" },
  telegram:  { label: "Telegram",        icon: "telegram",  color: "#229ED9" },
  shopee:    { label: "Shopee",          icon: "shopee",    color: "#EE4D2D" },
  zalooa:    { label: "Zalo OA",         icon: "zalooa",    color: "#005AE0" },
  webchat:   { label: "Website",         icon: "webchat",   color: "#4F46E5" },
  messenger: { label: "Mess + Instagram", icon: "meta",      color: "#7b3fb3" },
  instagram: { label: "Mess + Instagram", icon: "meta",      color: "#7b3fb3" },
};
const ADD_CHANNELS = ["zalo", "zalooa", "meta", "telegram", "shopee", "webchat"];

export function botKey(ch) { return (ch === "messenger" || ch === "instagram") ? "meta" : ch; }

/*
 * Lưới quản lý kênh (apps) của MỘT shop. Server đã lọc theo shop đang chọn
 * (header X-Shop từ http.js) — không còn lớp map localStorage hb_app_shop.
 * Mỗi shop chỉ 1 bot MỖI LOẠI kênh: modal disable kênh đã có (backend chặn 409).
 */
export default function AppsGrid({ onStats }) {
  const { t } = useI18n();
  const nav = useNavigate();
  const [apps, setApps] = useState(null);      // null=đang tải | mảng | "offline"
  const [showAdd, setShowAdd] = useState(false);
  const [botMap, setBotMap] = useState({});

  const appList = Array.isArray(apps) ? apps : [];
  const channels = [...new Set(appList.map((a) => botKey(a.channel)))];

  async function refresh() {
    const r = await getApps();
    if (r === "unauth") { logout(); nav("/login"); return; }
    setApps(r);
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  useEffect(() => {
    channels.forEach((c) => {
      brain.botStatus(c).then((r) => {
        setBotMap((m) => ({ ...m, [c]: (r.ok && r.body) ? !!r.body.enabled : "offline" }));
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appList.length]);

  useEffect(() => {
    if (!onStats) return;
    const on = appList.filter((a) => botMap[botKey(a.channel)] === true).length;
    const loaded = channels.some((c) => typeof botMap[c] === "boolean");
    onStats({ total: appList.length, on: loaded ? on : null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [appList.length, botMap]);

  async function handleAdd({ name, channel }) {
    try {
      await addApp({ name, channel });
    } catch (e) { alert("❌ " + e.message); }
    setShowAdd(false); refresh();
  }
  async function handleRemove(id) {
    if (!confirm(t("app.del_confirm"))) return;
    try { await removeApp(id); } catch (e) { alert("❌ " + e.message); }
    refresh();
  }
  async function toggleBot(channel) {
    const cur = botMap[channel];
    if (cur === "offline" || cur === undefined) return;
    const next = !cur;
    setBotMap((m) => ({ ...m, [channel]: next }));
    const r = await brain.botToggle(next, channel);
    // lỗi có message (chưa kết nối kênh / không đủ quyền) → nói rõ thay vì im lặng
    if (!r.ok && r.body?.error) alert("❌ " + r.body.error);
    setBotMap((m) => ({ ...m, [channel]: (r.ok && r.body) ? !!r.body.enabled : (r.body?.error ? cur : "offline") }));
  }

  if (apps === null) return <div className="empty"><p>{t("app.loading_list")}</p></div>;
  if (apps === "offline") return (
    <div className="empty">
      <p>{t("app.offline")}</p>
      <p className="hint">{t("app.run_cmd")} <code>start-all.bat</code> {t("app.then_retry")}</p>
      <button className="btn-primary sm" onClick={refresh} style={{ margin: "0 auto" }}>{t("app.retry")}</button>
    </div>
  );
  if (appList.length === 0) return (
    <div className="empty">
      <p>{t("app.empty")}</p>
      <button className="btn-primary sm" onClick={() => setShowAdd(true)} style={{ margin: "0 auto" }}>
        <IcPlus width={16} height={16} /> {t("app.add")}
      </button>
      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} taken={channels} />}
    </div>
  );

  return (
    <>
      <div className="grid">
        {appList.map((app) => {
          const ch = CHANNELS[app.channel] || CHANNELS.zalo;
          const key = botKey(app.channel);
          const st = botMap[key];
          const on = st === true;
          const reachable = st !== undefined && st !== "offline";
          return (
            <div className="app-card clickable" key={app.id} onClick={() => nav(`/app/${app.id}`)}>
              <div className="app-top">
                <div className="app-icon" style={{ background: ch.color }}>
                  <ChannelIcon ch={ch.icon} size={28} />
                </div>
                <div className="app-titles">
                  <div className="app-name">{app.name}</div>
                  <div className="app-ch">{ch.label}</div>
                </div>
                <div className={"app-status" + (reachable ? " on" : "")}>
                  <span className="dot" />{reachable ? t("app.connected") : t("app.not_connected")}
                </div>
              </div>
              <div className="ai-row" onClick={(e) => e.stopPropagation()}>
                <div className="ai-left">
                  <span className="spark"><IcSpark width={17} height={17} /></span> {t("app.ai_assistant")}
                  <span className={"badge " + (on ? "bot" : "stage")}>
                    {st === "offline" ? "Offline" : st === undefined ? "…" : on ? t("app.bot_on") : t("app.bot_off")}
                  </span>
                </div>
                <button className={"tggl" + (on ? " on" : "")}
                        disabled={st === "offline" || st === undefined}
                        onClick={() => toggleBot(key)}
                        title={t("app.toggle_title")} />
              </div>
              <div className="app-foot">
                <span>{t("app.manage_customers")}</span>
                <span className="chev"><IcChev width={16} height={16} /></span>
              </div>
              <button className="btn-mini danger del"
                      onClick={(e) => { e.stopPropagation(); handleRemove(app.id); }}>
                {t("app.delete")}
              </button>
            </div>
          );
        })}
        <div className="add-card" onClick={() => setShowAdd(true)}>
          <span className="add-plus"><IcPlus width={24} height={24} /></span>
          <h3>{t("app.add")}</h3>
          <span className="hint">{t("app.add_hint")}</span>
        </div>
      </div>
      {showAdd && <AddAppModal onClose={() => setShowAdd(false)} onAdd={handleAdd} taken={channels} />}
    </>
  );
}

function AddAppModal({ onClose, onAdd, taken = [] }) {
  const { t } = useI18n();
  const takenSet = new Set(taken);   // loại kênh shop ĐÃ có → mỗi shop chỉ 1 bot/loại
  const [name, setName] = useState("");
  const [channel, setChannel] = useState(ADD_CHANNELS.find((k) => !takenSet.has(k)) || "zalo");
  function submit(e) {
    e.preventDefault();
    if (takenSet.has(channel)) { alert("❌ " + t("app.ch_taken")); return; }
    onAdd({ name, channel });
  }
  return (
    <div className="modal-bg" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>{t("app.add_new")}</h3>
        <label>{t("app.name_label")}</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder={t("app.name_ph")} autoFocus />
        <label>{t("app.channel_label")}</label>
        <div className="ch-pick">
          {ADD_CHANNELS.map((key) => {
            const c = CHANNELS[key];
            const off = takenSet.has(key);
            return (
              <button type="button" key={key} disabled={off}
                      className={"ch-opt" + (channel === key ? " active" : "") + (off ? " taken" : "")}
                      title={off ? t("app.ch_taken") : undefined}
                      onClick={() => !off && setChannel(key)}>
                <ChannelTile ch={c.icon} size={30} color={c.color} /> {c.label}
              </button>
            );
          })}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-ghost" onClick={onClose}>{t("app.cancel")}</button>
          <button type="submit" className="btn-primary sm">{t("app.add_btn")}</button>
        </div>
      </form>
    </div>
  );
}
