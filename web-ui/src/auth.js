// Auth THẬT qua API (bridge 5005, users/token trong SQLite) — thay localStorage cũ.
// Token phiên lưu ở localStorage (ghi nhớ) hoặc sessionStorage (mất khi đóng tab);
// thông tin user được cache cùng chỗ để currentUser() dùng ĐỒNG BỘ như cũ.
// Tài khoản/app cũ trong localStorage (hb_users/hb_apps) được TỰ CHUYỂN lên server
// ở lần đăng nhập đầu tiên.

import { authApi, OFFLINE_MSG } from "./authApi.js";
// Token/phiên gom về 1 chỗ trong api/http.js (httpClient chung) — auth.js chỉ
// re-export getToken để các nơi import cũ (chatToolsApi, pages…) không phải sửa.
import { getToken, clearSession, TOKEN_KEY, USER_KEY } from "./api/http.js";

export { getToken };

const LEGACY_USERS_KEY = "hb_users";
const LEGACY_APPS_KEY = "hb_apps";

function setSession(token, user, remember) {
  clearSession();
  const s = remember ? localStorage : sessionStorage;
  s.setItem(TOKEN_KEY, token);
  s.setItem(USER_KEY, JSON.stringify(user));
}

export function currentUser() {
  const raw = localStorage.getItem(USER_KEY) || sessionStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// Vai trò team: chủ (owner — mặc định, acc cũ chưa có role) hay nhân viên (staff).
// Nhân viên chỉ thấy Hộp thư / Khách hàng / Đơn hàng / Thống kê.
export function isStaff(user) {
  return (user || currentUser())?.role === "staff";
}

function cacheUser(user) {
  const s = localStorage.getItem(TOKEN_KEY) ? localStorage : sessionStorage;
  s.setItem(USER_KEY, JSON.stringify(user));
}

function fail(r, fallback = "Có lỗi xảy ra") {
  throw new Error(r.status === 0 ? OFFLINE_MSG : (r.body?.error || fallback));
}

// ── Migrate dữ liệu localStorage kiểu cũ lên server (chạy 1 lần/user) ──

function legacyUser(username) {
  try {
    const users = JSON.parse(localStorage.getItem(LEGACY_USERS_KEY)) || {};
    return users[(username || "").trim().toLowerCase()] || null;
  } catch { return null; }
}

async function migrateLegacyApps(username, token) {
  try {
    const all = JSON.parse(localStorage.getItem(LEGACY_APPS_KEY)) || {};
    const apps = all[username] || [];
    if (!apps.length) return;
    for (const a of apps) {
      await authApi.addApp(token, { name: a.name, channel: a.channel });  // server tự chống trùng
    }
    delete all[username];
    localStorage.setItem(LEGACY_APPS_KEY, JSON.stringify(all));
  } catch { /* best-effort */ }
}

// ── API công khai (giữ tên hàm cũ, giờ là async) ───────────────────

export async function register({ username, password, homestay, promo = "", remember = true }) {
  username = (username || "").trim().toLowerCase();
  const r = await authApi.register(username, password, homestay || "", promo || "");
  if (!r.ok) fail(r, "Đăng ký thất bại");
  setSession(r.body.token, r.body.user, remember);
  await migrateLegacyApps(username, r.body.token);
  return r.body.user;
}

export async function login({ username, password, remember = true }) {
  username = (username || "").trim().toLowerCase();
  let r = await authApi.login(username, password);
  // Tài khoản kiểu cũ (localStorage) chưa có trên server → tự chuyển lên
  if (!r.ok && r.body?.code === "not_found") {
    const legacy = legacyUser(username);
    if (legacy && legacy.password === password) {
      r = await authApi.register(username, password, legacy.homestay || "");
    }
  }
  if (!r.ok) fail(r, "Sai email hoặc mật khẩu");
  setSession(r.body.token, r.body.user, remember);
  await migrateLegacyApps(username, r.body.token);
  return r.body.user;
}

// Đăng nhập Google: gửi credential (id_token) cho server xác thực với Google.
export async function loginWithGoogle({ credential }) {
  const r = await authApi.google(credential);
  if (!r.ok) fail(r, "Đăng nhập Google thất bại");
  setSession(r.body.token, r.body.user, true);
  await migrateLegacyApps(r.body.user.username, r.body.token);
  return r.body.user;
}

export async function updateProfile({ homestay, email }) {
  const r = await authApi.update(getToken(), { homestay, email });
  if (!r.ok) fail(r, "Lưu thất bại");
  cacheUser(r.body.user);
  return r.body.user;
}

// Quên mật khẩu: gửi mã OTP 6 số về email (server trả câu chung chung chống dò tài khoản).
export async function forgotPassword(username) {
  const r = await authApi.forgot((username || "").trim().toLowerCase());
  if (!r.ok) fail(r, "Không gửi được mã — thử lại sau");
  return r.body?.message || "Đã gửi mã về email của bạn (hiệu lực 15 phút).";
}

// Đặt mật khẩu mới bằng mã OTP — thành công thì mọi phiên cũ bị huỷ, đăng nhập lại.
export async function resetPassword({ username, code, newPassword }) {
  const r = await authApi.reset((username || "").trim().toLowerCase(), code, newPassword);
  if (!r.ok) fail(r, "Đặt lại mật khẩu thất bại");
  return true;
}

export async function changePassword({ oldPassword, newPassword }) {
  const r = await authApi.password(getToken(), oldPassword, newPassword);
  if (!r.ok) fail(r, "Đổi mật khẩu thất bại");
  return true;
}

// Làm mới thông tin user từ server (gọi lúc vào Dashboard — bắt phiên hết hạn).
export async function refreshUser() {
  const token = getToken();
  if (!token) return null;
  const r = await authApi.me(token);
  if (r.status === 401) { clearSession(); return null; }   // token hết hạn
  if (r.ok && r.body?.user) { cacheUser(r.body.user); return r.body.user; }
  return currentUser();   // offline → dùng cache
}

export function logout() {
  const token = getToken();
  if (token) authApi.logout(token);   // best-effort, không chờ
  clearSession();
}
