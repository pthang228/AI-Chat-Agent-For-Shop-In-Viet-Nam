// API Thư viện ảnh (bridge 5005) — bộ ảnh đặt tên để bot gửi khách.
import { getToken } from "./auth.js";

export const PHOTO_BASE = "http://localhost:5005";

async function j(path, opts = {}) {
  try {
    const r = await fetch(PHOTO_BASE + path, {
      ...opts,
      headers: {
        ...(opts.json ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${getToken()}`,
        ...(opts.headers || {}),
      },
      body: opts.json ? JSON.stringify(opts.json) : opts.body,
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export const photoApi = {
  sets: () => j("/photos/sets"),
  createSet: (name, keywords) => j("/photos/sets", { method: "POST", json: { name, keywords } }),
  updateKeywords: (slug, keywords) =>
    j(`/photos/sets/${encodeURIComponent(slug)}/keywords`, { method: "POST", json: { keywords } }),
  deleteSet: (slug) => j(`/photos/sets/${encodeURIComponent(slug)}`, { method: "DELETE" }),
  // upload nhiều file (multipart — KHÔNG set Content-Type, browser tự thêm boundary)
  upload: (slug, files) => {
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    return j(`/photos/sets/${encodeURIComponent(slug)}/upload`, { method: "POST", body: fd });
  },
  removeFile: (slug, name) =>
    j(`/photos/sets/${encodeURIComponent(slug)}/files/${encodeURIComponent(name)}`, { method: "DELETE" }),
  fileUrl: (slug, name) =>
    `${PHOTO_BASE}/photos/file/${encodeURIComponent(slug)}/${encodeURIComponent(name)}`,
};
