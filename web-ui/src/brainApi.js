// Gọi "não bộ" Python (bridge Flask, cổng 5005) — đã bật CORS.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export const brain = {
  botStatus: (channel) => j("/bot-status" + (channel ? "?channel=" + encodeURIComponent(channel) : "")),
  botToggle: (enabled, channel) =>
    j("/bot-toggle", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled, channel: channel || "" }),
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
  sendMessage: (id, text) =>
    j("/conversations/" + encodeURIComponent(id) + "/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    }),
  stats: (from, to) => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    return j(`/stats?${p}`);
  },
  // Chất lượng bot toàn shop (mọi kênh): thời gian phản hồi avg/P95 theo ngày
  // + số câu bot bí trong kỳ — nuôi 2 biểu đồ Thống kê
  quality: (from, to) => {
    const p = new URLSearchParams();
    if (from) p.set("from", from);
    if (to) p.set("to", to);
    return j(`/stats/quality?${p}`);
  },
};
