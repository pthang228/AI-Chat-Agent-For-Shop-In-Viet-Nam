// Gọi API kênh Zalo OA (Flask cổng 5010).
import { withAuth } from "./apiAuth.js";
import { HOST } from "./apiConfig.js";
const URL = HOST.zalooa;

async function j(path, opts) {
  try {
    const r = await fetch(URL + path, withAuth(opts));
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };   // server 5010 chưa chạy → offline
  }
}

export const zalooa = {
  config: () => j("/zalooa/config"),
  accounts: () => j("/zalooa/accounts"),
  connect: (accessToken, oaId, name, refreshToken = "") =>
    j("/zalooa/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken, oa_id: oaId, name, refresh_token: refreshToken }),
    }),
  removeAccount: (oaId) =>
    j("/zalooa/accounts/" + encodeURIComponent(oaId), { method: "DELETE" }),
  accountToggle: (oaId, enabled) =>
    j("/zalooa/accounts/" + encodeURIComponent(oaId) + "/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  setOwner: (userId, name) =>
    j("/zalooa/set-owner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, name }),
    }),
  conversations: (oaId, { limit = 50, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (oaId) p.set("oa_id", oaId);
    return j("/zalooa/conversations?" + p.toString());
  },
  conversation: (uid) => j("/zalooa/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/zalooa/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) => j("/zalooa/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/zalooa/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to, oaId = "") => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    if (oaId) p.set("oa_id", oaId);
    return j(`/zalooa/stats?${p}`);
  },
};
