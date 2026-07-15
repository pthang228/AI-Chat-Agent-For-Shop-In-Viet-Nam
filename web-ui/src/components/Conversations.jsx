import { useEffect, useRef, useState } from "react";
import { brain } from "../brainApi.js";
import ChatSend from "./ChatSend.jsx";
import { useI18n } from "../i18n.jsx";

function displayName(c) {
  const uid = String(c.user_id || "");
  return c.name ? `${c.name} (…${uid.slice(-6)})` : `…${uid.slice(-8)}`;
}

function relTime(iso, t) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return t("inbox.time.sec_ago", { n: Math.floor(diff) });
  if (diff < 3600) return t("inbox.time.min_ago", { n: Math.floor(diff / 60) });
  if (diff < 86400) return t("inbox.time.hr_ago", { n: Math.floor(diff / 3600) });
  return t("inbox.time.day_ago", { n: Math.floor(diff / 86400) });
}

export default function Conversations() {
  const { t } = useI18n();
  const [list, setList] = useState(null); // null = đang tải, [] = trống
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null); // user_id đang xem
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  async function loadList() {
    const { ok, body } = await brain.conversations();
    if (!ok || !Array.isArray(body)) { setOffline(true); setList([]); return; }
    setOffline(false);
    setList(body);
  }

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await brain.conversation(uid);
    if (ok) setDetail(body);
  }

  async function onToggle() {
    if (!detail) return;
    const botOn = detail.owner_active; // đang owner_active → bật bot lại
    await brain.toggleBot(detail.user_id, botOn);
    openChat(detail.user_id);
    loadList();
  }

  async function onReset(uid) {
    if (!confirm(t("inbox.reset_confirm"))) return;
    await brain.reset(uid);
    setSel(null); setDetail(null);
    loadList();
  }

  useEffect(() => {
    loadList();
    timer.current = setInterval(loadList, 8000);
    return () => clearInterval(timer.current);
  }, []);

  if (offline) {
    return (
      <div className="connect">
        <div className="status warn">{t("inbox.offline")}</div>
        <p className="hint">{t("inbox.run_python")}</p>
        <pre className="code">python main_node.py</pre>
        <button className="btn-primary" onClick={loadList}>{t("inbox.retry")}</button>
      </div>
    );
  }

  // ── Đang xem 1 hội thoại ──
  if (sel && detail) {
    return (
      <div className="chatview">
        <div className="chat-top">
          <button className="btn-ghost" onClick={() => { setSel(null); setDetail(null); }}>{t("inbox.back_list")}</button>
          <strong>{displayName(detail)}</strong>
          {detail.owner_active
            ? <span className="badge owner">{t("inbox.owner_handling")}</span>
            : <span className="badge bot">{t("inbox.bot_replying")}</span>}
          <div className="chat-actions">
            <button className="btn-mini" onClick={onToggle}>
              {detail.owner_active ? t("inbox.bot_on") : t("inbox.bot_off")}
            </button>
            <button className="btn-mini danger" onClick={() => onReset(detail.user_id)}>{t("team.del")}</button>
          </div>
        </div>
        <div className="bubbles">
          {detail.messages.length === 0 && <p className="hint">{t("inbox.no_msgs")}</p>}
          {detail.messages.map((m, i) => (
            <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>
              {m.content}
            </div>
          ))}
        </div>
        <ChatSend onSend={async (text) => {
          const r = await brain.sendMessage(detail.user_id, text);
          if (r.ok) { openChat(detail.user_id); loadList(); }
          return r.ok;
        }} />
      </div>
    );
  }

  // ── Danh sách hội thoại ──
  return (
    <div className="convlist">
      <div className="convlist-head">
        <span className="hint">{list ? t("inbox.n_convs", { n: list.length }) : t("team.loading")} · {t("inbox.auto_refresh")}</span>
        <button className="btn-ghost" onClick={loadList}>{t("inbox.refresh")}</button>
      </div>
      {list && list.length === 0 && <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>{t("inbox.no_customers")}</p>}
      {list && list.map((c) => (
        <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
          <div className="conv-main">
            <div className="conv-line1">
              <strong>{displayName(c)}</strong>
              {c.owner_active
                ? <span className="badge owner">{t("inbox.badge_owner")}</span>
                : <span className="badge bot">{t("inbox.badge_bot")}</span>}
              <span className="badge stage">{c.stage}</span>
              <span className="conv-time">{relTime(c.last_updated, t)}</span>
            </div>
            {c.checkin && <div className="conv-meta">📅 {c.checkin}{c.checkout && c.checkout !== c.checkin ? ` → ${c.checkout}` : ""}</div>}
            {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}
