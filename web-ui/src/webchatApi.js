// Gọi API kênh Webchat — widget nhúng website khách hàng (Flask cổng 5011).
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.webchat);

export const webchat = {
  config: () => j("/webchat/config"),
  sites: () => j("/webchat/sites"),
  createSite: (name) =>
    j("/webchat/sites", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  removeSite: (siteId) =>
    j("/webchat/sites/" + encodeURIComponent(siteId), { method: "DELETE" }),
  siteToggle: (siteId, enabled) =>
    j("/webchat/sites/" + encodeURIComponent(siteId) + "/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  setOwner: (userId, name) =>
    j("/webchat/set-owner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, name }),
    }),
  conversations: (siteId, { limit = 50, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (siteId) p.set("site_id", siteId);
    return j("/webchat/conversations?" + p.toString());
  },
  conversation: (uid) => j("/webchat/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/webchat/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) => j("/webchat/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/webchat/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to, siteId = "") => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    if (siteId) p.set("site_id", siteId);
    return j(`/webchat/stats?${p}`);
  },
};
