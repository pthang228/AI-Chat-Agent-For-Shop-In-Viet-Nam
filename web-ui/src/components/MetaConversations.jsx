import { useEffect, useRef, useState } from "react";
import { meta } from "../metaApi.js";
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

// Khách hàng kênh Meta — TÁCH RIÊNG theo từng Page (mỗi khách hàng 1 danh sách).
export default function MetaConversations() {
  const { t } = useI18n();
  const [pages, setPages] = useState(null);   // null = đang tải
  const [pageId, setPageId] = useState("");    // Page đang chọn
  const [list, setList] = useState(null);
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const timer = useRef(null);

  // Tải danh sách Page (mỗi Page là 1 "tab" khách riêng)
  useEffect(() => {
    meta.pages().then((r) => {
      if (r.ok && Array.isArray(r.body)) {
        setPages(r.body);
        if (r.body.length) setPageId(r.body[0].page_id);
      } else { setOffline(true); setPages([]); }
    });
  }, []);

  async function loadList() {
    if (!pageId) { setList([]); return; }
    const { ok, body } = await meta.conversations(pageId);
    if (!ok || !Array.isArray(body)) { setOffline(true); setList([]); return; }
    setOffline(false); setList(body);
  }

  // Đổi Page → tải lại danh sách khách của Page đó, tự làm mới 8s
  useEffect(() => {
    if (!pageId) return;
    setSel(null); setDetail(null); setList(null);
    loadList();
    clearInterval(timer.current);
    timer.current = setInterval(loadList, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageId]);

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await meta.conversation(uid);
    if (ok) setDetail(body);
  }

  async function onToggle() {
    if (!detail) return;
    await meta.toggleBot(detail.user_id, detail.owner_active); // owner_active → bật bot lại
    openChat(detail.user_id);
    loadList();
  }

  async function onReset(uid) {
    if (!confirm(t("cv.reset_confirm"))) return;
    await meta.resetConv(uid);
    setSel(null); setDetail(null);
    loadList();
  }

  if (pages === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;

  if (offline)
    return (
      <div className="connect">
        <div className="status warn">{t("cv.offline", { name: "Meta", port: 5006 })}</div>
        <p className="hint">{t("cv.run_pre")} <code>python -m app.main_meta</code> {t("cv.run_post")}</p>
      </div>
    );

  if (pages.length === 0)
    return (
      <div className="connect">
        <div className="status muted">{t("cv.meta_no_pages")}</div>
        <p className="hint">{t("cv.meta_hint_pre")} <b>{t("cv.meta_hint_tab")}</b> {t("cv.meta_hint_post")}</p>
      </div>
    );

  return (
    <div>
      {/* Bộ chọn Page — mỗi Page = data khách riêng */}
      {pages.length > 1 && (
        <div className="page-tabs">
          {pages.map((p) => (
            <button
              key={p.page_id}
              className={"page-tab" + (p.page_id === pageId ? " active" : "")}
              onClick={() => setPageId(p.page_id)}
            >
              {p.name || p.page_id}
            </button>
          ))}
        </div>
      )}
      {pages.length === 1 && (
        <div className="page-current">{t("cv.meta_customers_of")} <b>{pages[0].name || pages[0].page_id}</b></div>
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
              <button className="btn-mini" onClick={onToggle}>
                {detail.owner_active ? t("cv.bot_on") : t("cv.bot_off")}
              </button>
              <button className="btn-mini danger" onClick={() => onReset(detail.user_id)}>{t("team.del")}</button>
            </div>
          </div>
          <div className="bubbles">
            {detail.messages.length === 0 && <p className="hint">{t("cv.no_messages")}</p>}
            {detail.messages.map((m, i) => (
              <div key={i} className={"bubble " + (m.role === "assistant" ? "b-bot" : "b-user")}>
                {m.content}
              </div>
            ))}
          </div>
          <ChatSend onSend={async (text) => {
            const r = await meta.sendMessage(detail.user_id, text);
            if (r.ok) { openChat(detail.user_id); loadList(); }
            return r.ok;
          }} />
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">{list ? t("cv.conv_count", { n: list.length }) : t("team.loading")} · {t("cv.auto_refresh")}</span>
            <button className="btn-ghost" onClick={loadList}>{t("cv.refresh")}</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>{t("cv.meta_empty")}</p>
          )}
          {list && list.map((c) => (
            <div className="convrow" key={c.user_id} onClick={() => openChat(c.user_id)}>
              <div className="conv-main">
                <div className="conv-line1">
                  <strong>{displayName(c)}</strong>
                  {c.owner_active
                    ? <span className="badge owner">{t("cv.badge_owner")}</span>
                    : <span className="badge bot">{t("cv.badge_bot")}</span>}
                  <span className="badge stage">{c.stage}</span>
                  <span className="conv-time">{relTime(c.last_updated, t)}</span>
                </div>
                {c.checkin && <div className="conv-meta">📅 {c.checkin}{c.checkout && c.checkout !== c.checkin ? ` → ${c.checkout}` : ""}</div>}
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
