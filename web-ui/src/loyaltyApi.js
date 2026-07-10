// API Loyalty — mã giảm giá + áp vào đơn (bridge 5005), kèm Bearer token.
import { getToken } from "./auth.js";
import { HOST } from "./apiConfig.js";

const URL = HOST.bridge;

async function j(path, opts = {}) {
  try {
    const r = await fetch(URL + path, {
      ...opts,
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(opts.body ? { "Content-Type": "application/json" } : {}),
        ...(opts.headers || {}),
      },
    });
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export const loyaltyApi = {
  vouchers: () => j("/vouchers"),
  createVoucher: (v) => j("/vouchers", { method: "POST", body: JSON.stringify(v) }),
  updateVoucher: (id, fields) =>
    j("/vouchers/" + id, { method: "PATCH", body: JSON.stringify(fields) }),
  deleteVoucher: (id) => j("/vouchers/" + id, { method: "DELETE" }),
  checkVoucher: (code, total) =>
    j("/vouchers/check", { method: "POST", body: JSON.stringify({ code, total }) }),
  applyToOrder: (orderId, code) =>
    j(`/orders/${orderId}/voucher`, { method: "POST", body: JSON.stringify({ code }) }),
};
