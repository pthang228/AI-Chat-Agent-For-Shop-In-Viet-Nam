// Gọi API kênh Shopee (Flask cổng 5009).
const URL = "http://localhost:5009";

async function j(path, opts) {
  try {
    const r = await fetch(URL + path, opts);
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };   // server 5009 chưa chạy → offline
  }
}

export const shopee = {
  config: () => j("/shopee/config"),
  shops: () => j("/shopee/shops"),
  connect: (accessToken, shopId, name, refreshToken = "") =>
    j("/shopee/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken, shop_id: shopId, name, refresh_token: refreshToken }),
    }),
  removeShop: (shopId) =>
    j("/shopee/shops/" + encodeURIComponent(shopId), { method: "DELETE" }),
  shopToggle: (shopId, enabled) =>
    j("/shopee/shops/" + encodeURIComponent(shopId) + "/toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  setOwner: (userId, name) =>
    j("/shopee/set-owner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, name }),
    }),
  conversations: (shopId, { limit = 50, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (shopId) p.set("shop_id", shopId);
    return j("/shopee/conversations?" + p.toString());
  },
  conversation: (uid) => j("/shopee/conversations/" + encodeURIComponent(uid)),
  toggleBot: (uid, botOn) =>
    j("/shopee/conversations/" + encodeURIComponent(uid) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  resetConv: (uid) => j("/shopee/conversations/" + encodeURIComponent(uid), { method: "DELETE" }),
  sendMessage: (uid, text) =>
    j("/shopee/conversations/" + encodeURIComponent(uid) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to, shopId = "") => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    if (shopId) p.set("shop_id", shopId);
    return j(`/shopee/stats?${p}`);
  },
};
