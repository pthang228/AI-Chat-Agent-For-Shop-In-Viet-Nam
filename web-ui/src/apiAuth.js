// Đính Bearer token (nếu đã đăng nhập) vào MỌI request gọi các server kênh.
// Backend giờ yêu cầu token cho các endpoint quản trị (gửi tin, bật/tắt, xoá…),
// nên mọi API client kênh bọc opts qua withAuth().
import { getToken } from "./auth.js";

export function withAuth(opts = {}) {
  const token = getToken();
  if (!token) return opts;
  return { ...opts, headers: { ...(opts.headers || {}), Authorization: `Bearer ${token}` } };
}
