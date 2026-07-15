import { useEffect, useState } from "react";
import { meta } from "../metaApi.js";
import { posts as postsApi } from "../postsApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";
import { useI18n } from "../i18n.jsx";

/*
 * Bài viết & bình luận (Facebook + TikTok):
 *  - Danh sách bài viết của Page → bình luận từng bài
 *  - Trả lời / Ẩn-hiện / Nhắn riêng (comment → inbox) từng bình luận
 *  - Cài đặt TỰ ĐỘNG per Page: ẩn bình luận lộ SĐT (chống cướp khách),
 *    tự trả lời công khai, tự nhắn riêng kéo khách vào inbox
 * TikTok: API bình luận chỉ cấp cho app được TikTok duyệt → tab hiện ghi chú,
 * backend sẽ gắn sau khi được duyệt (giống kênh TikTok DM).
 */

function relTime(iso, t) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return t("posts.min_ago", { n: Math.max(1, Math.floor(diff / 60)) });
  if (diff < 86400) return t("posts.hr_ago", { n: Math.floor(diff / 3600) });
  return t("posts.day_ago", { n: Math.floor(diff / 86400) });
}
function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }

export default function PostsSection() {
  const { t } = useI18n();
  const [platform, setPlatform] = useState("fb");
  const [pages, setPages] = useState(null);      // null=tải | [] | "offline"
  const [pageId, setPageId] = useState("");

  useEffect(() => {
    meta.pages().then((r) => {
      if (r.ok && Array.isArray(r.body)) {
        setPages(r.body);
        if (r.body.length) setPageId(r.body[0].page_id);
      } else setPages("offline");
    });
  }, []);

  return (
    <div className="po">
      <div className="po-plat-tabs">
        <button className={"po-plat" + (platform === "fb" ? " active" : "")}
                onClick={() => setPlatform("fb")}>
          <ChannelTile ch="meta" size={16} /> Facebook
        </button>
        <button className={"po-plat" + (platform === "tiktok" ? " active" : "")}
                onClick={() => setPlatform("tiktok")}>
          <ChannelTile ch="tiktok" size={16} /> TikTok
        </button>
      </div>

      {platform === "tiktok" ? (
        <div className="empty">
          <p>🎬 <b>{t("posts.tt_title")}</b></p>
          <p className="hint">{t("posts.tt_hint")}</p>
        </div>
      ) : pages === null ? (
        <div className="empty"><p>{t("team.loading")}</p></div>
      ) : pages === "offline" ? (
        <div className="empty">
          <p>{t("posts.offline")}</p>
          <p className="hint">{t("posts.offline_pre")} <code>start-all.bat</code> {t("posts.offline_post")}</p>
        </div>
      ) : pages.length === 0 ? (
        <div className="empty">
          <p>{t("posts.no_pages")}</p>
          <p className="hint">{t("posts.go_pre")} <b>{t("posts.connect_path")}</b> {t("posts.go_post")}</p>
        </div>
      ) : (
        <>
          {pages.length > 1 && (
            <div className="page-tabs">
              {pages.map((p) => (
                <button key={p.page_id}
                        className={"page-tab" + (p.page_id === pageId ? " active" : "")}
                        onClick={() => setPageId(p.page_id)}>
                  {p.name || p.page_id}
                </button>
              ))}
            </div>
          )}
          {pageId && <AutoSettings pageId={pageId} />}
          {pageId && <PostsBrowser pageId={pageId} />}
        </>
      )}
    </div>
  );
}

/* ── Cài đặt tự động hoá bình luận (per Page) ── */
function AutoSettings({ pageId }) {
  const { t } = useI18n();
  const [s, setS] = useState(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setS(null); setMsg("");
    postsApi.settingsGet(pageId).then((r) => setS(r.ok && r.body?.settings ? r.body.settings : null));
  }, [pageId]);

  if (!s) return null;
  const set = (k, v) => setS((cur) => ({ ...cur, [k]: v }));

  async function save() {
    setBusy(true); setMsg("");
    const r = await postsApi.settingsSet(pageId, s);
    setBusy(false);
    if (r.ok) {
      setMsg(r.body.feed_subscribed
        ? t("posts.saved_webhook")
        : t("posts.saved_nowebhook"));
    } else setMsg("❌ " + (r.body?.error || t("posts.save_fail")));
  }

  return (
    <details className="panel set-card po-settings">
      <summary>{t("posts.auto_title")}
        <span className="hint" style={{ fontWeight: 400 }}>
          {" "}— {[s.auto_hide_phone && t("posts.sum_hide"), s.auto_reply && t("posts.sum_reply"), s.private_reply && t("posts.sum_pm")]
            .filter(Boolean).join(" · ") || t("posts.sum_off")}
        </span>
      </summary>

      <label className="po-opt">
        <input type="checkbox" checked={!!s.auto_hide_phone}
               onChange={(e) => set("auto_hide_phone", e.target.checked)} />
        <div>
          <b>{t("posts.opt_hide")}</b>
          <div className="hint">{t("posts.opt_hide_hint")}</div>
        </div>
      </label>

      <label className="po-opt">
        <input type="checkbox" checked={!!s.auto_reply}
               onChange={(e) => set("auto_reply", e.target.checked)} />
        <div>
          <b>{t("posts.opt_reply")}</b>
          <div className="hint">{t("posts.opt_reply_hint_pre")} <code>{"{name}"}</code> {t("posts.opt_reply_hint_post")}</div>
        </div>
      </label>
      {s.auto_reply && (
        <textarea rows={2} value={s.auto_reply_text}
                  onChange={(e) => set("auto_reply_text", e.target.value)} />
      )}

      <label className="po-opt">
        <input type="checkbox" checked={!!s.private_reply}
               onChange={(e) => set("private_reply", e.target.checked)} />
        <div>
          <b>{t("posts.opt_pm")}</b>
          <div className="hint">{t("posts.opt_pm_hint")}</div>
        </div>
      </label>
      {s.private_reply && (
        <textarea rows={2} value={s.private_reply_text}
                  onChange={(e) => set("private_reply_text", e.target.value)} />
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
        <button className="btn-primary sm" onClick={save} disabled={busy}>
          {busy ? t("posts.saving") : t("posts.save_btn")}
        </button>
        {msg && <span className="savemsg">{msg}</span>}
      </div>
    </details>
  );
}

/* ── Bài viết + bình luận ── */
function PostsBrowser({ pageId }) {
  const { t } = useI18n();
  const [items, setItems] = useState(null);    // null=tải | mảng | "err:<msg>"
  const [sel, setSel] = useState(null);        // post đang xem

  async function load() {
    setItems(null); setSel(null);
    const r = await postsApi.list(pageId);
    if (r.ok && r.body?.items) setItems(r.body.items);
    else setItems("err:" + (r.body?.error || t("posts.load_posts_fail")));
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [pageId]);

  if (items === null) return <div className="empty"><p>{t("posts.loading_posts")}</p></div>;
  if (typeof items === "string")
    return (
      <div className="empty">
        <p>⚠️ {items.slice(4)}</p>
        <p className="hint">
          {t("posts.perm_pre")} <b>{t("posts.connect_path")}</b>{t("posts.perm_mid")}
          <b> {t("posts.perm_login")}</b> {t("posts.perm_post")}
        </p>
        <button className="btn-primary sm" onClick={load} style={{ margin: "0 auto" }}>{t("posts.retry")}</button>
      </div>
    );
  if (items.length === 0)
    return <div className="empty"><p>{t("posts.no_posts")}</p></div>;

  return (
    <div className="po-body">
      <div className="po-posts">
        <div className="convlist-head">
          <span className="hint">{t("posts.n_posts", { n: items.length })}</span>
          <button className="btn-ghost" onClick={load}>{t("posts.refresh")}</button>
        </div>
        {items.map((p) => (
          <div key={p.id}
               className={"po-post" + (sel?.id === p.id ? " active" : "")}
               onClick={() => setSel(p)}>
            {p.picture
              ? <img className="po-thumb" src={p.picture} alt=""
                     onError={(e) => e.currentTarget.remove()} />
              : <div className="po-thumb po-thumb-empty">📝</div>}
            <div className="po-post-main">
              <div className="po-post-msg">{p.message || t("posts.no_text")}</div>
              <div className="po-post-sub">
                <span>💬 {p.comment_count}</span>
                <span>{relTime(p.created_time, t)}</span>
                {p.permalink_url && (
                  <a href={p.permalink_url} target="_blank" rel="noreferrer"
                     onClick={(e) => e.stopPropagation()}>{t("posts.open_fb")}</a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="po-comments">
        {!sel
          ? <div className="inbox-detail-empty"><h3>{t("posts.pick_post")}</h3>
              <p className="hint">{t("posts.pick_post_hint")}</p></div>
          : <CommentList key={sel.id} post={sel} pageId={pageId} />}
      </div>
    </div>
  );
}

function CommentList({ post, pageId }) {
  const { t } = useI18n();
  const [items, setItems] = useState(null);
  const [openReply, setOpenReply] = useState(null);   // comment_id đang mở ô nhập
  const [text, setText] = useState("");
  const [note, setNote] = useState("");

  async function load() {
    const r = await postsApi.comments(post.id, pageId);
    if (r.ok && r.body?.items) setItems(r.body.items);
    else setItems("err:" + (r.body?.error || t("posts.load_cmts_fail")));
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [post.id]);

  async function doAction(fn, okMsg) {
    setNote("");
    const r = await fn();
    setNote(r.ok ? okMsg : "❌ " + (r.body?.error || t("posts.fail")));
    if (r.ok) { setOpenReply(null); setText(""); load(); }
  }

  if (items === null) return <div className="empty"><p>{t("posts.loading_cmts")}</p></div>;
  if (typeof items === "string") return <div className="empty"><p>⚠️ {items.slice(4)}</p></div>;
  if (items.length === 0) return <div className="empty"><p>{t("posts.no_cmts")}</p></div>;

  return (
    <div className="po-cmt-list">
      {note && <div className="savemsg" style={{ margin: "6px 0" }}>{note}</div>}
      {items.map((c) => (
        <div key={c.id} className={"po-cmt" + (c.is_hidden ? " hidden" : "")}>
          <div className="inbox-av" style={{ background: "#7b3fb3", width: 32, height: 32, fontSize: 13 }}>
            {initials(c.from_name)}
          </div>
          <div className="po-cmt-main">
            <div className="po-cmt-l1">
              <b>{c.from_name || t("posts.guest")}</b>
              <span className="conv-time">{relTime(c.created_time, t)}</span>
              {c.is_hidden && <span className="badge owner">{t("posts.hidden_badge")}</span>}
              {c.has_phone && <span className="badge stage" style={{ color: "#c0392b" }}>{t("posts.phone_badge")}</span>}
            </div>
            <div className="po-cmt-msg">{c.message}</div>
            <div className="po-cmt-actions">
              <button className="btn-mini"
                      onClick={() => { setOpenReply(openReply === c.id ? null : c.id); setText(""); }}>
                {t("posts.reply_btn")}
              </button>
              <button className="btn-mini"
                      onClick={() => doAction(
                        () => postsApi.hide(c.id, pageId, !c.is_hidden),
                        c.is_hidden ? t("posts.unhidden_ok") : t("posts.hidden_ok"))}>
                {c.is_hidden ? t("posts.unhide") : t("posts.hide")}
              </button>
            </div>
            {openReply === c.id && (
              <div className="po-reply-box">
                <textarea rows={2} autoFocus value={text}
                          placeholder={t("posts.reply_ph", { name: c.from_name || t("posts.guest_lc") })}
                          onChange={(e) => setText(e.target.value)} />
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <button className="btn-mini" disabled={!text.trim()}
                          onClick={() => doAction(
                            () => postsApi.privateReply(c.id, pageId, text.trim()),
                            t("posts.pm_ok"))}>
                    {t("posts.pm_btn")}
                  </button>
                  <button className="btn-primary sm" disabled={!text.trim()}
                          onClick={() => doAction(
                            () => postsApi.reply(c.id, pageId, text.trim()),
                            t("posts.reply_ok"))}>
                    {t("posts.reply_pub_btn")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
