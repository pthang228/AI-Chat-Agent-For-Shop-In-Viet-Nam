// API Thư viện ảnh (bridge 5005) — bộ ảnh đặt tên để bot gửi khách.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401; opts.json → body JSON,
// FormData (upload) giữ nguyên để trình duyệt tự set multipart boundary.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

export const PHOTO_BASE = HOST.bridge;

const j = makeClient(PHOTO_BASE);

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
