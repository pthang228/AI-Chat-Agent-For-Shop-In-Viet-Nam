import { useEffect, useRef, useState } from "react";
import ChatSend from "./ChatSend.jsx";
import { useI18n } from "../i18n.jsx";
import useConversationsPoll from "../hooks/useConversationsPoll.js";

/* Màn danh sách hội thoại DÙNG CHUNG cho 6 kênh (Telegram / Shopee / TikTok /
 * WebChat / Zalo OA / Meta) — trước đây là 6 file copy giống hệt nhau, mỗi lần
 * sửa UI phải sửa 6 chỗ. Khác biệt thật giữa các kênh chỉ là:
 *   - api:        client gọi server kênh (listAccounts/conversations/conversation/
 *                 toggleBot/resetConv/sendMessage + setOwner nếu kênh có)
 *   - idKey:      tên field id tài khoản (bot_id / shop_id / business_id / site_id / oa_id / page_id)
 *   - tabLabel:   cách hiện nhãn tab tài khoản (Telegram thêm "@"…)
 *   - offline*:   tên + cổng + module chạy server để hiện hướng dẫn khi offline
 *   - ownerKeys:  bộ key i18n nút "Đặt làm chủ" theo vai (home/shop/site/oa) — null = kênh không có nút này (Meta)
 *   - paged:      API có phân trang {items,total} (5 kênh) hay trả mảng thẳng (Meta)
 *   - allTab:     có tab "Tất cả" (5 kênh) hay bắt buộc chọn 1 tài khoản (Meta tự chọn Page đầu)
 *   - noAccountsKeys / currentLabelKey / showCheckin / emptyKey: các nét riêng của Meta
 */
export default function ChannelConversations({
  api,
  idKey,
  tabLabel,
  offlineName,
  offlinePort,
  runModule,
  ownerKeys = null,          // {confirm, ok, title} — key i18n cho "Đặt làm chủ"
  emptyKey = "cv.empty",
  paged = true,
  allTab = true,
  noAccountsKeys = null,     // {msg, pre, tab, post} — màn hình khi chưa nối tài khoản nào (Meta)
  currentLabelKey = null,    // key banner "Khách hàng của <X>" khi chỉ có 1 tài khoản (Meta)
  showCheckin = false,       // hiện dòng 📅 checkin/checkout trong danh sách (Meta)
}) {
  const { t } = useI18n();
  const [accounts, setAccounts] = useState(null); // null = đang tải
  const [accId, setAccId] = useState("");         // "" = tất cả (hoặc chưa chọn nếu !allTab)
  const [list, setList] = useState(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const PAGE = 50;
  const [offline, setOffline] = useState(false);
  const [sel, setSel] = useState(null);
  const [detail, setDetail] = useState(null);
  const offRef = useRef(0);   // trang hiện tại — interval chỉ tự refresh khi ở trang đầu

  // Tải danh sách tài khoản kênh 1 lần lúc mount (mỗi tài khoản = 1 tab khách riêng)
  useEffect(() => {
    api.listAccounts().then((r) => {
      if (r.ok && Array.isArray(r.body)) {
        setAccounts(r.body);
        // Kênh không có tab "Tất cả" (Meta) → tự chọn tài khoản đầu tiên
        if (!allTab && r.body.length) setAccId(r.body[0][idKey]);
      } else { setOffline(true); setAccounts([]); }
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadList(off = 0, append = false) {
    if (!allTab && !accId) { setList([]); return; }
    if (paged) {
      const { ok, body } = await api.conversations(accId, { limit: PAGE, offset: off });
      if (!ok || !body?.items) { setOffline(true); if (!append) setList([]); return; }
      setOffline(false);
      setTotal(body.total ?? 0);
      setOffset(off);
      offRef.current = off;
      setList((prev) => append ? [...(prev ?? []), ...body.items] : body.items);
    } else {
      // API kiểu cũ (Meta): trả mảng thẳng, không phân trang
      const { ok, body } = await api.conversations(accId);
      if (!ok || !Array.isArray(body)) { setOffline(true); setList([]); return; }
      setOffline(false); setList(body);
    }
  }

  // Đổi tài khoản → tải lại danh sách, tự làm mới 8s (chỉ khi đang ở trang đầu)
  useConversationsPoll((first) => {
    if (first) {
      setSel(null); setDetail(null); setList(null); setOffset(0); setTotal(0);
      loadList(0);
    } else if (offRef.current === 0) {
      loadList(0);
    }
  }, [accId], { enabled: allTab || !!accId });

  async function openChat(uid) {
    setSel(uid);
    const { ok, body } = await api.conversation(uid);
    if (ok) setDetail(body);
  }
  async function onToggle() {
    if (!detail) return;
    await api.toggleBot(detail.user_id, detail.owner_active); // owner_active → bật bot lại
    openChat(detail.user_id); loadList();
  }
  async function onReset(uid) {
    if (!confirm(t("cv.reset_confirm"))) return;
    await api.resetConv(uid);
    setSel(null); setDetail(null); loadList();
  }
  async function onSetOwner(uid) {
    if (!confirm(t(ownerKeys.confirm))) return;
    const r = await api.setOwner(uid);
    alert(r.ok ? t(ownerKeys.ok) : t("cv.set_owner_fail"));
  }

  if (accounts === null)
    return <div className="connect"><div className="status muted">{t("team.loading")}</div></div>;
  if (offline)
    return (
      <div className="connect">
        <div className="status warn">{t("cv.offline", { name: offlineName, port: offlinePort })}</div>
        <p className="hint">{t("cv.run_pre")} <code>python -m {runModule}</code> {t("cv.run_post")}</p>
      </div>
    );
  if (noAccountsKeys && accounts.length === 0)
    return (
      <div className="connect">
        <div className="status muted">{t(noAccountsKeys.msg)}</div>
        <p className="hint">{t(noAccountsKeys.pre)} <b>{t(noAccountsKeys.tab)}</b> {t(noAccountsKeys.post)}</p>
      </div>
    );

  return (
    <div>
      {accounts.length > 1 && (
        <div className="page-tabs">
          {allTab && (
            <button className={"page-tab" + (accId === "" ? " active" : "")} onClick={() => setAccId("")}>{t("cv.all")}</button>
          )}
          {accounts.map((a) => (
            <button key={a[idKey]} className={"page-tab" + (a[idKey] === accId ? " active" : "")}
                    onClick={() => setAccId(a[idKey])}>
              {tabLabel(a)}
            </button>
          ))}
        </div>
      )}
      {currentLabelKey && accounts.length === 1 && (
        <div className="page-current">{t(currentLabelKey)} <b>{tabLabel(accounts[0])}</b></div>
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
              {ownerKeys && api.setOwner && (
                <button className="btn-mini" onClick={() => onSetOwner(detail.user_id)} title={t(ownerKeys.title)}>{t("cv.set_owner_btn")}</button>
              )}
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
            const r = await api.sendMessage(detail.user_id, text);
            if (r.ok) { openChat(detail.user_id); loadList(0); }
            return r.ok;
          }} />
        </div>
      ) : (
        <div className="convlist">
          <div className="convlist-head">
            <span className="hint">
              {list
                ? (paged ? t("cv.conv_count_total", { n: list.length, total }) : t("cv.conv_count", { n: list.length }))
                : t("team.loading")} · {t("cv.auto_refresh")}
            </span>
            <button className="btn-ghost" onClick={() => loadList(0)}>{t("cv.refresh")}</button>
          </div>
          {list && list.length === 0 && (
            <p className="hint" style={{ textAlign: "center", padding: "24px 0" }}>{t(emptyKey)}</p>
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
                {showCheckin && c.checkin && (
                  <div className="conv-meta">📅 {c.checkin}{c.checkout && c.checkout !== c.checkin ? ` → ${c.checkout}` : ""}</div>
                )}
                {c.last_msg && <div className="conv-preview">💬 {c.last_msg}</div>}
              </div>
            </div>
          ))}
          {paged && list && list.length < total && (
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
