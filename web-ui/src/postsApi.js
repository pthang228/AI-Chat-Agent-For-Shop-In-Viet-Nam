// API "Bài viết & bình luận" Facebook (meta_webhook Flask, cổng 5006) — kèm Bearer.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.meta);

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
