// Gọi Node service Zalo (zca-js) — MULTI-ACCOUNT: mỗi shop 1 acc riêng.
// Mọi hàm nhận acc (mặc định "default" = acc chủ nền tảng, tương thích cũ).
// Acc của shop lấy từ bridge /zalo/my-account (myAccount() bên dưới).
import { HOST } from "./apiConfig.js";
import { withAuth } from "./apiAuth.js";

const NODE_URL = HOST.node;

async function j(path, opts) {
  const r = await fetch(NODE_URL + path, opts);
  // 400/409 là trạng thái hợp lệ (chưa chọn nhóm / chưa đăng nhập) — vẫn trả body
  let body = {};
  try { body = await r.json(); } catch { /* ignore */ }
  return { ok: r.ok, status: r.status, body };
}

const q = (acc) => "?acc=" + encodeURIComponent(acc || "default");
const json = (body) => ({
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const zalo = {
  // Acc Zalo của shop đang đăng nhập (bridge cấp; chủ nền tảng = "default")
  myAccount: async () => {
    try {
      const r = await fetch(HOST.bridge + "/zalo/my-account", withAuth());
      let body = {};
      try { body = await r.json(); } catch { /* ignore */ }
      return { ok: r.ok, status: r.status, body };
    } catch { return { ok: false, status: 0, body: {} }; }
  },

  status: (acc) => j("/status" + q(acc)),
  startQR: (acc) => j("/login/qr", json({ acc: acc || "default" })),
  groups: (acc) => j("/groups" + q(acc)),
  getConfig: (acc) => j("/config" + q(acc)),
  saveGroup: (ownerGroupId, acc) =>
    j("/config", json({ acc: acc || "default", ownerGroupId })),
  logout: (acc) => j("/logout", json({ acc: acc || "default" })),          // đổi tài khoản (cần quét lại)
  disconnect: (acc) => j("/disconnect", json({ acc: acc || "default" })),  // tạm ngắt, GIỮ đăng nhập
  reconnect: (acc) => j("/reconnect", json({ acc: acc || "default" })),    // kết nối lại, KHÔNG cần QR
  restoreSession: (acc) => j("/restore-session", json({ acc: acc || "default" })),
};
