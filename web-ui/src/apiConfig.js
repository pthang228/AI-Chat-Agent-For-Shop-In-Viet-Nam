// Địa chỉ các server backend — DÙNG CHUNG cho mọi API client.
//
// DEV (vite dev, import.meta.env.PROD=false): mỗi service 1 cổng localhost riêng
//   (bridge 5005, meta 5006, telegram 5007, tiktok 5008, shopee 5009, zalooa 5010,
//    webchat 5011, zalo-node 4000).
//
// PROD (vite build): TẤT CẢ service chung 1 DOMAIN. Reverse proxy (Caddy) định
//   tuyến theo path prefix mà từng service vốn đã namespace: /meta→5006, /tg→5007,
//   /tiktok→5008, /shopee→5009, /zalooa→5010, /webchat→5011; còn lại (/auth,
//   /conversations, /billing, /orders, /prompt, /notify, /broadcasts, /team,
//   /customers, /copilot, /photos, /media…) → bridge 5005. Zalo Node để dưới
//   tiền tố /zalo-node (Caddy handle_path strip).
//
//   Mặc định lấy chính origin của trang dashboard (window.location.origin) → build
//   1 lần chạy được cho MỌI domain, không cần build lại. Có thể ép qua biến môi
//   trường build-time VITE_API_BASE nếu API nằm ở domain/subdomain khác.

const PROD = import.meta.env.PROD;
const ORIGIN = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "") ||
  (typeof window !== "undefined" ? window.location.origin : "");

export const HOST = PROD
  ? {
      bridge: ORIGIN, meta: ORIGIN, telegram: ORIGIN, tiktok: ORIGIN,
      shopee: ORIGIN, zalooa: ORIGIN, webchat: ORIGIN,
      node: ORIGIN + "/zalo-node",
    }
  : {
      bridge: "http://127.0.0.1:5005", meta: "http://127.0.0.1:5006",
      telegram: "http://127.0.0.1:5007", tiktok: "http://127.0.0.1:5008",
      shopee: "http://127.0.0.1:5009", zalooa: "http://127.0.0.1:5010",
      webchat: "http://127.0.0.1:5011", node: "http://127.0.0.1:4000",
    };

// Map kênh → host (dùng ở chatToolsApi / InboxSection / CustomersSection).
export const CH_HOST = {
  zalo: HOST.bridge, meta: HOST.meta, telegram: HOST.telegram,
  tiktok: HOST.tiktok, shopee: HOST.shopee, zalooa: HOST.zalooa,
  webchat: HOST.webchat,
};
