// Danh sách "app" (kênh bot) của user — lưu TRÊN SERVER (SQLite qua /auth/apps),
// thay localStorage hb_apps cũ. Mọi hàm giờ là async.

import { authApi } from "./authApi.js";
import { getToken } from "./auth.js";

// Trả về: mảng app | "offline" (server 5005 chưa chạy) | "unauth" (phiên hết hạn)
export async function getApps() {
  const r = await authApi.apps(getToken());
  if (r.status === 0) return "offline";
  if (r.status === 401) return "unauth";
  return Array.isArray(r.body) ? r.body : [];
}

export async function addApp({ name, channel }) {
  const r = await authApi.addApp(getToken(), { name, channel });
  if (!r.ok) throw new Error(r.body?.error || "Không thêm được app");
  return r.body.app;
}

export async function removeApp(id) {
  const r = await authApi.removeApp(getToken(), id);
  if (!r.ok) throw new Error(r.body?.error || "Không xoá được app");
  return true;
}
