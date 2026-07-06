// Gọi API Prompt Builder (bridge 5005) — kèm Bearer token.
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

export const promptApi = {
  current: () => j("/prompt/current"),
  template: () => j("/prompt/template"),
  // AI viết prompt — chậm (20-60s), đừng đặt timeout phía UI
  // links: mảng string URL hoặc {url, note} (note = shop mô tả link, tuỳ chọn)
  // model: key ai_models shop chọn để DẠY ("" = mặc định hệ thống)
  generate: (links, instructions, model = "") =>
    j("/prompt/generate", { method: "POST", body: JSON.stringify({ links, instructions, model }) }),
  // chunks (mẩu tri thức) đi kèm draft từ generate — có chunks = chế độ lai (RAG)
  apply: (prompt, chunks = null) =>
    j("/prompt/apply", { method: "POST", body: JSON.stringify({ prompt, chunks }) }),
  knowledge: () => j("/prompt/knowledge"),
  // Chat THỬ với bot (AI thật + chẩn đoán) — không lưu, không gửi khách nào
  test: (message, history = []) =>
    j("/prompt/test", { method: "POST", body: JSON.stringify({ message, history }) }),
  restoreDefault: () => j("/prompt/restore-default", { method: "POST" }),

  // Bot học từ hội thoại — hàng chờ duyệt mẩu tri thức AI bóc từ câu chủ trả lời tay
  suggestions: () => j("/prompt/suggestions"),
  approveSuggestion: (id, edits = {}) =>
    j(`/prompt/suggestions/${id}/approve`, { method: "POST", body: JSON.stringify(edits) }),
  rejectSuggestion: (id) =>
    j(`/prompt/suggestions/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),
};
