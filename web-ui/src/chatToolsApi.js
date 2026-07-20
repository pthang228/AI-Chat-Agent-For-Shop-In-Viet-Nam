// Công cụ chat: gửi ảnh/video/ghi âm, chốt đơn 1 chạm, câu trả lời mẫu.
// Mỗi kênh 1 server riêng (prefix + cổng khác nhau); canned dùng chung ở bridge 5005.
// Dùng httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient, request } from "./api/http.js";
import { CH_HOST, HOST } from "./apiConfig.js";

const BASE = CH_HOST;
const PREFIX = {
  zalo: "", meta: "/meta", telegram: "/tg",
  tiktok: "/tiktok", shopee: "/shopee", zalooa: "/zalooa", webchat: "/webchat",
};

function url(ch, path) { return (BASE[ch] || BASE.zalo) + (PREFIX[ch] ?? "") + path; }

// Gửi tệp (ảnh/video/ghi âm) — multipart; KHÔNG set Content-Type để trình duyệt tự thêm boundary
export function sendMedia(ch, uid, file, caption = "") {
  const fd = new FormData();
  fd.append("file", file, file.name || "media");
  if (caption) fd.append("caption", caption);
  return request(url(ch, `/conversations/${encodeURIComponent(uid)}/send-media`), "", {
    method: "POST", body: fd,
  });
}

// Chốt đơn 1 chạm: AI bóc hội thoại → đơn nháp trong Sổ đơn hàng
export function makeOrder(ch, uid) {
  return request(url(ch, `/conversations/${encodeURIComponent(uid)}/make-order`), "", { method: "POST" });
}

// ⭐ Lưu làm mẫu: AI bóc đoạn chat đẹp thành mẫu hội thoại (style RAG)
export function saveStyle(ch, uid) {
  return request(url(ch, `/conversations/${encodeURIComponent(uid)}/save-style`), "", { method: "POST" });
}

// Phân công hội thoại cho nhân viên (team inbox) — username rỗng = bỏ gán
export function assignConv(ch, uid, username) {
  return request(url(ch, `/conversations/${encodeURIComponent(uid)}/assign`), "", {
    method: "POST", json: { username: username || "" },
  });
}

// Câu trả lời mẫu (kho chung ở bridge 5005)
const cj = makeClient(HOST.bridge + "/canned");
export const canned = {
  list: () => cj(""),
  add: (title, content) => cj("", { method: "POST", body: JSON.stringify({ title, content }) }),
  remove: (id) => cj("/" + id, { method: "DELETE" }),
};
