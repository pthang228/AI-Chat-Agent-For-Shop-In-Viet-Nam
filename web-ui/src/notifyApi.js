// Liên hệ khẩn cấp & Thông báo — bridge 5005, chỉ CHỦ shop (owner).
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export const notifyApi = {
  get: () => j("/notify/config"),
  set: (config) => j("/notify/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  }),
};

// Gọi khẩn qua Telegram cấp SHOP (mọi kênh) — acc phụ chủ tự đăng nhập QR
// gọi acc chính khi có sự kiện mức "Gọi". Backend: /caller* (caller_api.py).
export const callerApi = {
  status: () => j("/caller"),
  qrLogin: () => j("/caller/qr-login", { method: "POST" }),
  loginStatus: () => j("/caller/login-status"),
  password: (password) => j("/caller/password", { method: "POST", json: { password } }),
  target: (handle) => j("/caller/target", { method: "POST", json: { handle } }),
  testCall: () => j("/caller/test-call", { method: "POST" }),
  logout: () => j("/caller/logout", { method: "POST" }),
};
