// API Sổ đơn hàng (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

import { HOST } from "./apiConfig.js";
const URL = HOST.bridge;

async function j(path, opts = {}) {
  try {
    const r = await fetch(URL + path, {
      ...opts,
      headers: {
        ...(opts.json ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${getToken()}`,
      },
      body: opts.json ? JSON.stringify(opts.json) : undefined,
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

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
