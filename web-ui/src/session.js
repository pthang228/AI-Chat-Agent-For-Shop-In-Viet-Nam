import { brain } from "./brainApi.js";
import { logout } from "./auth.js";

// Đăng xuất = TẮT bot toàn cục (bot_state, mọi kênh đọc chung) rồi xoá phiên
// (logout() cũng thu hồi token trên server — best-effort).
// Nếu não bộ (5005) không chạy thì vẫn đăng xuất bình thường.
export async function logoutAndStopBots() {
  try { await brain.botToggle(false, "all"); } catch { /* ignore */ }
  logout();
}
