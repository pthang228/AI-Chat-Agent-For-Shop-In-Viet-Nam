// API Loyalty — mã giảm giá + áp vào đơn (bridge 5005), kèm Bearer token.
// j = httpClient chung (api/http.js): tự gắn Bearer + Content-Type + bắt 401.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

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
