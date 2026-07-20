// Gọi API auth thật (nằm trong bridge Flask, cổng 5005) — users/token/apps trong SQLite.
import { HOST } from "./apiConfig.js";
// httpClient chung, NHƯNG: auth:false (token được truyền TƯỜNG MINH từng hàm,
// không tự gắn) + handle401:false (ở đây 401 là kết quả bình thường — sai mật
// khẩu, mã OTP sai… — auth.js tự xử lý, không được đá về /login).
import { makeClient } from "./api/http.js";

const j = makeClient(HOST.bridge, { auth: false, handle401: false });

const json = (body, token) => ({
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: JSON.stringify(body),
});
const auth = (token, method = "GET") => ({
  method,
  headers: { Authorization: `Bearer ${token}` },
});

export const authApi = {
  register: (username, password, homestay, promo = "") =>
    j("/auth/register", json({ username, password, homestay, promo })),
  login: (username, password) =>
    j("/auth/login", json({ username, password })),
  google: (credential) =>
    j("/auth/google", json({ credential })),
  forgot: (username) =>
    j("/auth/forgot", json({ username })),
  reset: (username, code, newPassword) =>
    j("/auth/reset", json({ username, code, new_password: newPassword })),
  me: (token) => j("/auth/me", auth(token)),
  logout: (token) => j("/auth/logout", auth(token, "POST")),
  update: (token, { homestay, email }) =>
    j("/auth/update", json({ homestay, email }, token)),
  password: (token, oldPassword, newPassword) =>
    j("/auth/password", json({ old_password: oldPassword, new_password: newPassword }, token)),

  apps: (token) => j("/auth/apps", auth(token)),
  addApp: (token, { name, channel }) => j("/auth/apps", json({ name, channel }, token)),
  removeApp: (token, id) => j("/auth/apps/" + encodeURIComponent(id), auth(token, "DELETE")),
  // Model AI riêng cho 1 chatbot — model rỗng = dùng model chung của shop
  setAppAiModel: (token, id, model) =>
    j("/auth/apps/" + encodeURIComponent(id) + "/ai-model", json({ model }, token)),
};

export const OFFLINE_MSG =
  "Không kết nối được máy chủ (cổng 5005). Chạy start-all.bat (hoặc python -m app.main_node) rồi thử lại.";
