// API Sổ đơn hàng (bridge 5005) — kèm Bearer token.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401; opts.json → body JSON.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export const ordersApi = {
  list: ({ status = "", channel = "", q = "", limit = 100, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (status) p.set("status", status);
    if (channel) p.set("channel", channel);
    if (q) p.set("q", q);
    return j("/orders?" + p.toString());
  },
  summary: () => j("/orders/summary"),
  get: (id) => j(`/orders/${id}`),
  create: (order) => j("/orders", { method: "POST", json: order }),
  update: (id, fields) => j(`/orders/${id}`, { method: "PATCH", json: fields }),
  remove: (id) => j(`/orders/${id}`, { method: "DELETE" }),
  // Tài khoản nhận tiền của shop (QR động gửi khách khi chốt đơn)
  bankGet: () => j("/orders/bank"),
  bankSet: (bank) => j("/orders/bank", { method: "POST", json: bank }),
};

// Nhãn + màu trạng thái dùng chung cho UI
export const ORDER_STATUS = {
  draft:            { label: "📝 Nháp",            color: "#9aa39b" },
  awaiting_payment: { label: "⏳ Chờ thanh toán",  color: "#cf9536" },
  paid:             { label: "💰 Đã thanh toán",   color: "#229ed9" },
  fulfilled:        { label: "📦 Đã giao/checkin", color: "#7C3AED" },
  done:             { label: "✅ Hoàn tất",        color: "#23a065" },
  cancelled:        { label: "🚫 Đã huỷ",          color: "#c14a32" },
};
// Trạng thái kế tiếp gợi ý (nút chuyển nhanh 1 chạm)
export const NEXT_STATUS = {
  draft: "awaiting_payment",
  awaiting_payment: "paid",
  paid: "fulfilled",
  fulfilled: "done",
};
export const vnd = (n) => (Number(n) || 0).toLocaleString("vi-VN") + "đ";
