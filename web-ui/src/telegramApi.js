// Gọi server Telegram (telegram_api Flask, cổng 5007) — đã bật CORS.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.telegram);

export const tg = {
  config: () => j("/tg/config"),
  bots: () => j("/tg/bots"),
  connect: (token) =>
    j("/tg/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    }),
  removeBot: (botId) => j("/tg/bots/" + encodeURIComponent(botId), { method: "DELETE" }),
  setOwner: (userId, name) =>
    j("/tg/set-owner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, name: name || "" }),
    }),
  // Acc GỌI (Telethon) — đăng nhập bằng QR theo từng bot
  caller: (botId) => j("/tg/caller?bot_id=" + encodeURIComponent(botId)),
  callerQrLogin: (botId) =>
    j("/tg/caller/qr-login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_id: botId }),
    }),
  callerLoginStatus: (botId) =>
    j("/tg/caller/login-status?bot_id=" + encodeURIComponent(botId)),
  callerPassword: (botId, password) =>
    j("/tg/caller/password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_id: botId, password }),
    }),
  callerLogout: (botId) =>
    j("/tg/caller/logout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_id: botId }),
    }),

  pollers: () => j("/tg/pollers"),
  botToggle: (botId, enabled) =>
    j(`/tg/bots/${encodeURIComponent(botId)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  conversations: (botId, { limit = 50, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (botId) p.set("bot_id", botId);
    return j("/tg/conversations?" + p.toString());
  },
  conversation: (uid) => j("/tg/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/tg/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) => j("/tg/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/tg/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to, botId = "") => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    if (botId) p.set("bot_id", botId);
    return j(`/tg/stats?${p}`);
  },
};
