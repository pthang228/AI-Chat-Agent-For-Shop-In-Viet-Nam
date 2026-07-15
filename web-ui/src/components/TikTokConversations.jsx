import { useEffect, useRef, useState } from "react";
import { tiktok } from "../tiktokApi.js";
import ChatSend from "./ChatSend.jsx";
import { useI18n } from "../i18n.jsx";

function displayName(c) {
  const uid = String(c.user_id || "");
  return c.name ? `${c.name} (…${uid.slice(-6)})` : `…${uid.slice(-8)}`;
}

function relTime(iso, t) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return t("cv.time_sec", { n: Math.floor(diff) });
  if (diff < 3600) return t("cv.time_min", { n: Math.floor(diff / 60) });
  if (diff < 86400) return t("cv.time_hour", { n: Math.floor(diff / 3600) });
  return t("cv.time_day", { n: Math.floor(diff / 86400) });
}

// Khách hàng kênh TikTok — tách theo từng account (mỗi khách hàng 1 account).
export default function TikTokConversations() {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState(null);   // null=đang tải
  const [bizId, setBizId] = useState("");           // "" = tất cả
  const [list, setList] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const PAGE = 50;
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);
  const offRef = useRef(0);   // trang hiện tại — interval chỉ tự refresh khi ở trang đầu

  useEffect(() => {
    tiktok.accounts().then((r) => {
      if (r.ok && Array.isArray(r.body)) setAccounts(r.body);
      else { setOffline(true); setAccounts([]); }
    });
  }, []);

  async function loadList(off = 0, append = false) {
    const { ok, body } = await tiktok.conversations(bizId, { limit: PAGE, offset: off });
    if (!ok || !body?.items) { setOffline(true); if (!append) setList([]); return; }
    setOffline(false);
    setTotal(body.total ?? 0);
    setOffset(off);
    offRef.current = off;
    setList((prev) => append ? [...(prev ?? []), ...body.items] : body.items);
  }

  useEffect(() => {
    setSel(null); setDetail(null); setList(null); setOffset(0); setTotal(0);
    loadList(0);
    clearInterval(timer.current);
    timer.current = setInterval(() => { if (offRef.current === 0) loadList(0); }, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bizId]);

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await tiktok.conversation(uid);
    if (ok) setDetail(body);
  }
  async function onToggle() {
    if (!detail) return;
    await tiktok.toggleBot(detail.user_id, detail.owner_active);
    openChat(detail.user_id); loadList();
  }
  async function onReset(uid) {
    if (!confirm(t("cv.reset_confirm"))) return;
    await tiktok.resetConv(uid);
    setSel(null); setDetail(null); loadList();
  }
  async function onSetOwner(uid) {
    if (!confirm(t("cv.set_owner_confirm_home"))) return;
    const r = await tiktok.setOwner(uid);
    alert(r.ok ? t("cv.set_owner_ok_home") : t("cv.set_owner_fail"));
  }

  if (accounts === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;
  if (offline)
    return (
      <div className="connect">
        <div className="status warn">{t("cv.offline", { name: "TikTok", port: 5008 })}</div>
        <p className="hint">{t("cv.run_pre")} <code>python -m app.main_tiktok</code> {t("cv.run_post")}</p>
      </div>
    );

  return (
    <div>
      {accounts.length > 1 && (
        <div className="page-tabs">
          <button className={"page-tab" + (bizId === "" ? " active" : "")} onClick={() => setBizId("")}>{t("cv.all")}</button>
          {accounts.map((a) => (
            <button key={a.business_id} className={"page-tab" + (a.business_id === bizId ? " active" : "")}
                    onClick={() => setBizId(a.business_id)}>
              {a.name || a.username || a.business_id}
            </button>
          ))}
        </div>
      )}

      {sel && detail ? (
        <div className="chatview">
          <div className="chat-top">
            <button className="btn-ghost" onClick={() => { setSel(null); setDetail(null); }}>{t("cv.back_list")}</button>
            <strong>{displayName(detail)}</strong>
            {detail.owner_active
              ? <span className="badge owner">{t("cv.owner_handling")}</span>
              : <span className="badge bot">{t("cv.bot_replying")}</span>}
            <div className="chat-actions">
              <button className="btn-mini" onClick={() => onSetOwner(detail.user_id)} title={t("cv.set_owner_title_home")}>{t("cv.set_owner_btn")}</button>
              <button className="btn-mini" onClick={onToggle}>{detail.owner_active ? t("cv.bot_on") : t("cv.bot_off")}</button>
              <button className="btn-mini danger" onClick={() => onReset(detail.user_id)}>{t("team.del")}</button>
            </div>
          </div>
          <div className="bubbles">
            {detail.messages.length === 0 && <p className="hint">{t("cv.no_messages")}</p>}
            {detail.messages.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>{m.content}</div>
            ))}
          </div>
          <ChatSend onSend={async (text) => {
            const r = await tiktok.sendMessage(detail.user_id, text);
            if (r.ok) { openChat(detail.user_id); loadList(0); }
            return r.ok;
          }} />
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">
              {list ? t("cv.conv_count_total", { n: list.length, total }) : t("team.loading")} · {t("cv.auto_refresh")}
            </span>
            <button className="btn-ghost" onClick={() => loadList(0)}>{t("cv.refresh")}</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>{t("cv.empty")}</p>
          )}
          {list && list.map((c) => (
            <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
              <div className="conv-main">
                <div className="conv-line1">
                  <strong>{displayName(c)}</strong>
                  {c.owner_active ? <span className="badge owner">{t("cv.badge_owner")}</span> : <span className="badge bot">{t("cv.badge_bot")}</span>}
                  <span className="badge stage">{c.stage}</span>
                  <span className="conv-time">{relTime(c.last_updated, t)}</span>
                </div>
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
          {list && list.length < total && (
            <div style={{ textAlign: "center", padding: "12px 0" }}>
              <button className="btn-ghost" onClick={() => loadList(offset + PAGE, true)}>
                {t("cv.load_more", { n: total - list.length })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
