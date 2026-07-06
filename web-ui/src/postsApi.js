// API "Bài viết & bình luận" Facebook (meta_webhook Flask, cổng 5006) — kèm Bearer.
import { withAuth } from "./apiAuth.js";
import { HOST } from "./apiConfig.js";
const URL = HOST.meta;

async function j(path, opts) {
  try {
    const r = await fetch(URL + path, withAuth(opts));
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };   // server 5006 chưa chạy → offline
  }
}

const json = (body) => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const posts = {
  list: (pageId) => j("/posts?page_id=" + encodeURIComponent(pageId)),
  comments: (postId, pageId) =>
    j(`/posts/${encodeURIComponent(postId)}/comments?page_id=${encodeURIComponent(pageId)}`),
  reply: (commentId, pageId, message) =>
    j(`/comments/${encodeURIComponent(commentId)}/reply`, json({ page_id: pageId, message })),
  hide: (commentId, pageId, hidden) =>
    j(`/comments/${encodeURIComponent(commentId)}/hide`, json({ page_id: pageId, hidden })),
  privateReply: (commentId, pageId, message) =>
    j(`/comments/${encodeURIComponent(commentId)}/private-reply`, json({ page_id: pageId, message })),
  settingsGet: (pageId) => j("/posts/settings?page_id=" + encodeURIComponent(pageId)),
  settingsSet: (pageId, settings) => j("/posts/settings", json({ page_id: pageId, ...settings })),
};
