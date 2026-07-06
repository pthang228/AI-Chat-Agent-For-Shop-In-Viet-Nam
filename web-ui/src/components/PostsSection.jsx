import { useEffect, useState } from "react";
import { meta } from "../metaApi.js";
import { posts as postsApi } from "../postsApi.js";
import { ChannelTile } from "./ChannelIcon.jsx";

/*
 * Bài viết & bình luận (Facebook + TikTok):
 *  - Danh sách bài viết của Page → bình luận từng bài
 *  - Trả lời / Ẩn-hiện / Nhắn riêng (comment → inbox) từng bình luận
 *  - Cài đặt TỰ ĐỘNG per Page: ẩn bình luận lộ SĐT (chống cướp khách),
 *    tự trả lời công khai, tự nhắn riêng kéo khách vào inbox
 * TikTok: API bình luận chỉ cấp cho app được TikTok duyệt → tab hiện ghi chú,
 * backend sẽ gắn sau khi được duyệt (giống kênh TikTok DM).
 */

function relTime(iso) {
  if (!iso) return "";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.max(1, Math.floor(diff / 60))} phút trước`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} giờ trước`;
  return `${Math.floor(diff / 86400)} ngày trước`;
}
function initials(s) { return (s || "?").trim().slice(0, 1).toUpperCase(); }

export default function PostsSection() {
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
          <p>🎬 <b>Bình luận TikTok</b></p>
          <p className="hint">
            API quản lý bình luận TikTok chỉ cấp cho ứng dụng được TikTok duyệt
            (đang trong quá trình duyệt — giống kênh TikTok DM). Ngay khi được cấp,
            mục này chạy mà bạn không phải làm lại gì.
          </p>
        </div>
      ) : pages === null ? (
        <div className="empty"><p>Đang tải…</p></div>
      ) : pages === "offline" ? (
        <div className="empty">
          <p>⚠️ Chưa kết nối được máy chủ Meta (cổng 5006).</p>
          <p className="hint">Chạy <code>start-all.bat</code> rồi tải lại trang.</p>
        </div>
      ) : pages.length === 0 ? (
        <div className="empty">
          <p>Chưa có Page Facebook nào được kết nối.</p>
          <p className="hint">Vào <b>Chatbot → app Mess + Instagram → Kết nối</b> để đăng nhập Facebook trước.</p>
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
        ? "✅ Đã lưu — Page đã đăng ký nhận bình luận (webhook feed)."
        : "✅ Đã lưu. (Chưa xác nhận được đăng ký webhook feed — bình luận mới có thể chưa đổ về, xem log.)");
    } else setMsg("❌ " + (r.body?.error || "Lưu thất bại"));
  }

  return (
    <details className="panel set-card po-settings">
      <summary>⚙️ Tự động hoá bình luận
        <span className="hint" style={{ fontWeight: 400 }}>
          {" "}— {[s.auto_hide_phone && "ẩn SĐT", s.auto_reply && "tự trả lời", s.private_reply && "nhắn riêng"]
            .filter(Boolean).join(" · ") || "đang tắt hết"}
        </span>
      </summary>

      <label className="po-opt">
        <input type="checkbox" checked={!!s.auto_hide_phone}
               onChange={(e) => set("auto_hide_phone", e.target.checked)} />
        <div>
          <b>🙈 Tự ẩn bình luận lộ số điện thoại</b>
          <div className="hint">Chống đối thủ thấy SĐT khách rồi inbox cướp khách. Khách vẫn thấy bình luận của chính họ; hệ thống báo bạn để chủ động liên hệ lại.</div>
        </div>
      </label>

      <label className="po-opt">
        <input type="checkbox" checked={!!s.auto_reply}
               onChange={(e) => set("auto_reply", e.target.checked)} />
        <div>
          <b>💬 Tự trả lời công khai dưới bình luận</b>
          <div className="hint">Dùng mẫu câu (không tốn lượt AI). Viết <code>{"{name}"}</code> để chèn tên khách.</div>
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
          <b>📩 Tự nhắn tin riêng cho người bình luận</b>
          <div className="hint">Kéo khách từ bình luận vào inbox — bot AI tiếp quản tư vấn từ đó. Meta cho phép 1 tin riêng / bình luận.</div>
        </div>
      </label>
      {s.private_reply && (
        <textarea rows={2} value={s.private_reply_text}
                  onChange={(e) => set("private_reply_text", e.target.value)} />
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 10 }}>
        <button className="btn-primary sm" onClick={save} disabled={busy}>
          {busy ? "Đang lưu…" : "Lưu cài đặt"}
        </button>
        {msg && <span className="savemsg">{msg}</span>}
      </div>
    </details>
  );
}

/* ── Bài viết + bình luận ── */
function PostsBrowser({ pageId }) {
  const [items, setItems] = useState(null);    // null=tải | mảng | "err:<msg>"
  const [sel, setSel] = useState(null);        // post đang xem

  async function load() {
    setItems(null); setSel(null);
    const r = await postsApi.list(pageId);
    if (r.ok && r.body?.items) setItems(r.body.items);
    else setItems("err:" + (r.body?.error || "Không tải được bài viết"));
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [pageId]);

  if (items === null) return <div className="empty"><p>Đang tải bài viết…</p></div>;
  if (typeof items === "string")
    return (
      <div className="empty">
        <p>⚠️ {items.slice(4)}</p>
        <p className="hint">
          Nếu lỗi quyền: vào <b>Chatbot → app Mess + Instagram → Kết nối</b>, bấm
          <b> Đăng nhập Facebook</b> lại để cấp thêm quyền đọc bài viết/bình luận
          (app xin thêm 2 quyền mới cho tính năng này).
        </p>
        <button className="btn-primary sm" onClick={load} style={{ margin: "0 auto" }}>Thử lại</button>
      </div>
    );
  if (items.length === 0)
    return <div className="empty"><p>Page chưa có bài viết nào.</p></div>;

  return (
    <div className="po-body">
      <div className="po-posts">
        <div className="convlist-head">
          <span className="hint">{items.length} bài viết</span>
          <button className="btn-ghost" onClick={load}>Làm mới</button>
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
              <div className="po-post-msg">{p.message || "(bài viết không có chữ)"}</div>
              <div className="po-post-sub">
                <span>💬 {p.comment_count}</span>
                <span>{relTime(p.created_time)}</span>
                {p.permalink_url && (
                  <a href={p.permalink_url} target="_blank" rel="noreferrer"
                     onClick={(e) => e.stopPropagation()}>Mở trên FB ↗</a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="po-comments">
        {!sel
          ? <div className="inbox-detail-empty"><h3>Chọn một bài viết</h3>
              <p className="hint">để xem và xử lý bình luận.</p></div>
          : <CommentList key={sel.id} post={sel} pageId={pageId} />}
      </div>
    </div>
  );
}

function CommentList({ post, pageId }) {
  const [items, setItems] = useState(null);
  const [openReply, setOpenReply] = useState(null);   // comment_id đang mở ô nhập
  const [text, setText] = useState("");
  const [note, setNote] = useState("");

  async function load() {
    const r = await postsApi.comments(post.id, pageId);
    if (r.ok && r.body?.items) setItems(r.body.items);
    else setItems("err:" + (r.body?.error || "Không tải được bình luận"));
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [post.id]);

  async function doAction(fn, okMsg) {
    setNote("");
    const r = await fn();
    setNote(r.ok ? okMsg : "❌ " + (r.body?.error || "Thất bại"));
    if (r.ok) { setOpenReply(null); setText(""); load(); }
  }

  if (items === null) return <div className="empty"><p>Đang tải bình luận…</p></div>;
  if (typeof items === "string") return <div className="empty"><p>⚠️ {items.slice(4)}</p></div>;
  if (items.length === 0) return <div className="empty"><p>Bài này chưa có bình luận.</p></div>;

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
              <b>{c.from_name || "Khách"}</b>
              <span className="conv-time">{relTime(c.created_time)}</span>
              {c.is_hidden && <span className="badge owner">🙈 Đã ẩn</span>}
              {c.has_phone && <span className="badge stage" style={{ color: "#c0392b" }}>⚠️ Lộ SĐT</span>}
            </div>
            <div className="po-cmt-msg">{c.message}</div>
            <div className="po-cmt-actions">
              <button className="btn-mini"
                      onClick={() => { setOpenReply(openReply === c.id ? null : c.id); setText(""); }}>
                💬 Trả lời
              </button>
              <button className="btn-mini"
                      onClick={() => doAction(
                        () => postsApi.hide(c.id, pageId, !c.is_hidden),
                        c.is_hidden ? "✅ Đã hiện lại bình luận." : "✅ Đã ẩn bình luận.")}>
                {c.is_hidden ? "👁 Hiện lại" : "🙈 Ẩn"}
              </button>
            </div>
            {openReply === c.id && (
              <div className="po-reply-box">
                <textarea rows={2} autoFocus value={text}
                          placeholder={`Trả lời ${c.from_name || "khách"}…`}
                          onChange={(e) => setText(e.target.value)} />
                <div style={{ display: "flex", gap: 6, justifyContent: "flex-end" }}>
                  <button className="btn-mini" disabled={!text.trim()}
                          onClick={() => doAction(
                            () => postsApi.privateReply(c.id, pageId, text.trim()),
                            "✅ Đã nhắn riêng cho khách (xem ở mục Hội thoại).")}>
                    📩 Nhắn riêng
                  </button>
                  <button className="btn-primary sm" disabled={!text.trim()}
                          onClick={() => doAction(
                            () => postsApi.reply(c.id, pageId, text.trim()),
                            "✅ Đã trả lời công khai.")}>
                    Trả lời công khai
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
