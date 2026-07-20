// Gọi server TikTok (tiktok_api Flask, cổng 5008) — đã bật CORS.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.tiktok);

export const tiktok = {
  config: () => j("/tiktok/config"),
  accounts: () => j("/tiktok/accounts"),
  connect: (accessToken, businessId, name) =>
    j("/tiktok/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken, business_id: businessId, name: name || "" }),
    }),
  removeAccount: (bizId) =>
    j("/tiktok/accounts/" + encodeURIComponent(bizId), { method: "DELETE" }),
  accountToggle: (bizId, enabled) =>
    j(`/tiktok/accounts/${encodeURIComponent(bizId)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  setOwner: (userId, name) =>
    j("/tiktok/set-owner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, name: name || "" }),
    }),
  conversations: (bizId, { limit = 50, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (bizId) p.set("business_id", bizId);
    return j("/tiktok/conversations?" + p.toString());
  },
  conversation: (uid) => j("/tiktok/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/tiktok/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) => j("/tiktok/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/tiktok/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to, bizId = "") => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    if (bizId) p.set("business_id", bizId);
    return j(`/tiktok/stats?${p}`);
  },
};
