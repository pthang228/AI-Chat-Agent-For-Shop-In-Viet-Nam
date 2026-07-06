// Gọi API gói dịch vụ & nạp tiền (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

import { HOST } from "./apiConfig.js";
const URL = HOST.bridge;

async function j(path, opts = {}) {
  try {
    const r = await fetch(URL + path, {
      ...opts,
      headers: {
        ...(opts.body ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${getToken()}`,
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
