// Gọi API gói dịch vụ & nạp tiền (bridge 5005) — kèm Bearer token.
// j = httpClient chung (api/http.js): tự gắn Bearer + Content-Type + bắt 401.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export const billing = {
  me: () => j("/billing/me"),
  redeem: (code) => j("/billing/redeem", { method: "POST", body: JSON.stringify({ code }) }),
  deposit: (amount) => j("/billing/deposit", { method: "POST", body: JSON.stringify({ amount }) }),
  deposits: () => j("/billing/deposits"),
  buy: (tier, duration) => j("/billing/buy", { method: "POST", body: JSON.stringify({ tier, duration }) }),
  history: () => j("/billing/history"),
  setAiModel: (model) => j("/billing/ai-model", { method: "POST", body: JSON.stringify({ model }) }),
  setUsage: (enabled, limit) => j("/billing/usage", { method: "POST", body: JSON.stringify({ enabled, limit }) }),
};

export const vnd = (n) => (n ?? 0).toLocaleString("vi-VN") + "₫";
