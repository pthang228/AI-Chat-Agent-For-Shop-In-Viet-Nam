// Gọi server Meta (meta_webhook Flask, cổng 5006) — đã bật CORS.
const META_URL = "http://localhost:5006";

async function j(path, opts) {
  try {
    const r = await fetch(META_URL + path, opts);
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    // server Meta chưa chạy / mạng lỗi → trả về để UI hiện "offline", không treo
    return { ok: false, status: 0, body: null };
  }
}

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
};

// Quyền xin khi khách đăng nhập Facebook.
// Hiện chỉ Messenger (chạy ngay). Quyền Instagram (instagram_basic,
// instagram_manage_messages) chỉ hợp lệ SAU KHI app setup xong sản phẩm
// Instagram + tài khoản IG Professional liên kết với Page → khi đó thêm lại.
export const FB_SCOPE = [
  "public_profile",
  "pages_show_list",
  "pages_messaging",
  "pages_manage_metadata",
  "business_management",   // cần để lấy Page thuộc Business Portfolio (/me/businesses)
].join(",");

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
export function fbLogin(FB) {
  return new Promise((resolve, reject) => {
    FB.login((res) => {
      if (res.authResponse && res.authResponse.accessToken) {
        resolve(res.authResponse.accessToken);
      } else {
        reject(new Error("Bạn đã huỷ hoặc chưa cấp quyền"));
      }
    }, { scope: FB_SCOPE, return_scopes: true });
  });
}
