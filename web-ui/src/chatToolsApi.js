// Công cụ chat: gửi ảnh/video/ghi âm, chốt đơn 1 chạm, câu trả lời mẫu.
// Mỗi kênh 1 server riêng (prefix + cổng khác nhau); canned dùng chung ở bridge 5005.
import { getToken } from "./auth.js";
import { CH_HOST, HOST } from "./apiConfig.js";

const BASE = CH_HOST;
const PREFIX = {
  zalo: "", meta: "/meta", telegram: "/tg",
  tiktok: "/tiktok", shopee: "/shopee", zalooa: "/zalooa", webchat: "/webchat",
};

function url(ch, path) { return (BASE[ch] || BASE.zalo) + (PREFIX[ch] ?? "") + path; }

// Gửi tệp (ảnh/video/ghi âm) — multipart; KHÔNG set Content-Type để trình duyệt tự thêm boundary
export async function sendMedia(ch, uid, file, caption = "") {
  const fd = new FormData();
  fd.append("file", file, file.name || "media");
  if (caption) fd.append("caption", caption);
  try {
    const r = await fetch(url(ch, `/conversations/${encodeURIComponent(uid)}/send-media`), {
      method: "POST", headers: { Authorization: `Bearer ${getToken()}` }, body: fd,
    });
    let b = null; try { b = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body: b };
  } catch { return { ok: false, status: 0, body: null }; }
}

// Chốt đơn 1 chạm: AI bóc hội thoại → đơn nháp trong Sổ đơn hàng
export async function makeOrder(ch, uid) {
  try {
    const r = await fetch(url(ch, `/conversations/${encodeURIComponent(uid)}/make-order`), {
      method: "POST", headers: { Authorization: `Bearer ${getToken()}` },
    });
    let b = null; try { b = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body: b };
  } catch { return { ok: false, status: 0, body: null }; }
}

// Phân công hội thoại cho nhân viên (team inbox) — username rỗng = bỏ gán
export async function assignConv(ch, uid, username) {
  try {
    const r = await fetch(url(ch, `/conversations/${encodeURIComponent(uid)}/assign`), {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
      body: JSON.stringify({ username: username || "" }),
    });
    let b = null; try { b = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body: b };
  } catch { return { ok: false, status: 0, body: null }; }
}

// Câu trả lời mẫu (kho chung ở bridge 5005)
const CANNED = HOST.bridge + "/canned";
async function cj(path, opts = {}) {
  try {
    const r = await fetch(CANNED + path, {
      ...opts,
      headers: { Authorization: `Bearer ${getToken()}`, ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) },
    });
    let b = null; try { b = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body: b };
  } catch { return { ok: false, status: 0, body: null }; }
}
export const canned = {
  list: () => cj(""),
  add: (title, content) => cj("", { method: "POST", body: JSON.stringify({ title, content }) }),
  remove: (id) => cj("/" + id, { method: "DELETE" }),
};
