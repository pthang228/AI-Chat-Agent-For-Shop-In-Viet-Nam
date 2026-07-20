// Gọi Node service Zalo (zca-js) — MULTI-ACCOUNT: mỗi shop 1 acc riêng.
// Mọi hàm nhận acc (mặc định "default" = acc chủ nền tảng, tương thích cũ).
// Acc của shop lấy từ bridge /zalo/my-account (myAccount() bên dưới).
import { HOST } from "./apiConfig.js";
// httpClient chung. Node giờ gọi QUA BRIDGE proxy /zalo-node/* (Bearer bắt buộc,
// bridge tự ÉP acc theo shop đăng nhập — hết chuyện truyền ?acc= của shop khác;
// Caddy không còn phơi Node :4000 ra internet). 400/409 là trạng thái hợp lệ
// (chưa chọn nhóm / chưa đăng nhập Zalo) — vẫn trả body; fallbackBody {} để
// caller đọc body.x không phải optional-chain.
import { makeClient, request } from "./api/http.js";

const NODE_URL = HOST.bridge + "/zalo-node";

const j = makeClient(NODE_URL, { fallbackBody: {} });

const q = (acc) => "?acc=" + encodeURIComponent(acc || "default");
const json = (body) => ({
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const zalo = {
  // Acc Zalo của shop đang đăng nhập (bridge cấp; chủ nền tảng = "default")
  myAccount: () => request(HOST.bridge, "/zalo/my-account", { fallbackBody: {} }),

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
