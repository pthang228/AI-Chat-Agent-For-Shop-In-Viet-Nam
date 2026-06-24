// Gọi "não bộ" Python (bridge Flask, cổng 5005) — đã bật CORS.
const BRIDGE_URL = "http://localhost:5005";

async function j(path, opts) {
  const r = await fetch(BRIDGE_URL + path, opts);
  let body = null;
  try { body = await r.json(); } catch { /* ignore */ }
  return { ok: r.ok, status: r.status, body };
}

export const brain = {
  botStatus: () => j("/bot-status"),
  botToggle: (enabled, appName) =>
    j("/bot-toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, app_name: appName }),
    }),
  conversations: () => j("/conversations"),
  conversation: (id) => j("/conversations/" + encodeURIComponent(id)),
  toggleBot: (id, botOn) =>
    j("/conversations/" + encodeURIComponent(id) + "/toggle-bot", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bot_on: botOn }),
    }),
  reset: (id) =>
    j("/conversations/" + encodeURIComponent(id), { method: "DELETE" }),
};
