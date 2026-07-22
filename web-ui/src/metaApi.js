// Gọi server Meta (meta_webhook Flask, cổng 5006) — đã bật CORS.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.meta);

export const meta = {
  config: () => j("/meta/config"),
  pages: () => j("/meta/pages"),
  connect: (userToken) =>
    j("/meta/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userToken }),
    }),
  removePage: (pageId) =>
    j("/meta/pages/" + encodeURIComponent(pageId), { method: "DELETE" }),

  // Hội thoại khách — lọc theo từng Page (mỗi Page = data khách riêng)
  conversations: (pageId) =>
    j("/meta/conversations" + (pageId ? "?page_id=" + encodeURIComponent(pageId) : "")),
  conversation: (uid) =>
    j("/meta/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/meta/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) =>
    j("/meta/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/meta/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to) => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    return j(`/meta/stats?${p}`);
  },
};

// Quyền xin khi khách đăng nhập Facebook.
// Messenger luôn xin (chạy ngay). Quyền Instagram CHỈ thêm khi backend báo
// enable_ig=true (cờ FB_ENABLE_IG ở .env) — vì instagram_basic/
// instagram_manage_messages chỉ hợp lệ sau khi app setup sản phẩm Instagram +
// có IG Professional liên kết Page. Xin sớm → "Invalid Scopes" hỏng luôn login.
const FB_SCOPE_BASE = [
  "public_profile",
  "pages_show_list",
  "pages_messaging",
  "pages_manage_metadata",
  "business_management",   // cần để lấy Page thuộc Business Portfolio (/me/businesses)
];
const IG_SCOPE = [
  "instagram_basic",
  "instagram_manage_messages",
  "pages_read_engagement",
];
// Bài viết & bình luận: đọc bình luận + ẩn/trả lời. KHÔNG hợp lệ tới khi app Meta
// được cấu hình (use case/Advanced Access) → xin sớm báo "Invalid Scopes" và hỏng
// luôn login. Chỉ thêm khi backend báo enable_comments=true (cờ FB_ENABLE_COMMENTS).
const COMMENT_SCOPE = [
  "pages_read_user_content",
  "pages_manage_engagement",
];

// Ghép scope theo cờ enable_ig / enable_comments của backend.
export function buildScope(enableIg, enableComments) {
  return [
    ...FB_SCOPE_BASE,
    ...(enableIg ? IG_SCOPE : []),
    ...(enableComments ? COMMENT_SCOPE : []),
  ].join(",");
}

// Tương thích ngược (chỉ Messenger).
export const FB_SCOPE = FB_SCOPE_BASE.join(",");

let _sdkPromise = null;

// Nạp + khởi tạo Facebook JS SDK 1 lần, trả về window.FB.
export function loadFbSdk(appId) {
  if (_sdkPromise) return _sdkPromise;
  _sdkPromise = new Promise((resolve, reject) => {
    if (window.FB) { resolve(window.FB); return; }
    window.fbAsyncInit = function () {
      window.FB.init({ appId, cookie: true, xfbml: false, version: "v21.0" });
      resolve(window.FB);
    };
    const s = document.createElement("script");
    s.src = "https://connect.facebook.net/en_US/sdk.js";
    s.async = true; s.defer = true; s.crossOrigin = "anonymous";
    s.onerror = () => reject(new Error("Không tải được Facebook SDK"));
    document.body.appendChild(s);
  });
  return _sdkPromise;
}

// Mở popup đăng nhập Facebook → trả về user access token (ngắn hạn).
// scope tuỳ chọn (mặc định chỉ Messenger); MetaConnect truyền scope kèm IG khi bật.
export function fbLogin(FB, scope = FB_SCOPE) {
  return new Promise((resolve, reject) => {
    FB.login((res) => {
      if (res.authResponse && res.authResponse.accessToken) {
        resolve(res.authResponse.accessToken);
      } else {
        reject(new Error("Bạn đã huỷ hoặc chưa cấp quyền"));
      }
    }, { scope, return_scopes: true, auth_type: "rerequest" });
  });
}
