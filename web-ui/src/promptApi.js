// Gọi API Prompt Builder (bridge 5005) — kèm Bearer token.
// j = httpClient chung (api/http.js): tự gắn Bearer + Content-Type + bắt 401.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

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
  // Chat THỬ với bot (AI thật + chẩn đoán) — không lưu, không gửi khách nào.
  // model: chỉ định model để thử ("" = model shop đang dùng)
  test: (message, history = [], model = "") =>
    j("/prompt/test", { method: "POST", body: JSON.stringify({ message, history, model }) }),
  restoreDefault: () => j("/prompt/restore-default", { method: "POST" }),

  // Bot học từ hội thoại — hàng chờ duyệt mẩu tri thức AI bóc từ câu chủ trả lời tay
  suggestions: () => j("/prompt/suggestions"),
  approveSuggestion: (id, edits = {}) =>
    j(`/prompt/suggestions/${id}/approve`, { method: "POST", body: JSON.stringify(edits) }),
  rejectSuggestion: (id) =>
    j(`/prompt/suggestions/${id}/reject`, { method: "POST", body: JSON.stringify({}) }),

  // DẠY AI v2 — phỏng vấn / báo cáo câu bí / chấm điểm não
  interview: (history) =>
    j("/prompt/interview", { method: "POST", body: JSON.stringify({ history }) }),
  report: () => j("/prompt/report"),
  reportAnswer: (question, answer, ids = []) =>
    j("/prompt/report/answer", { method: "POST", body: JSON.stringify({ question, answer, ids }) }),
  health: () => j("/prompt/health", { method: "POST", body: JSON.stringify({}) }),

  // STYLE RAG — kho mẫu hội thoại (dạy giọng + cách xử lý tình huống)
  styleList: () => j("/prompt/style"),
  styleDelete: (id) => j(`/prompt/style/${id}`, { method: "DELETE" }),
  // AI sinh bộ mẫu từ transcript/mô tả — chậm (20-60s), trả preview KHÔNG lưu
  styleGenerate: (text, model = "") =>
    j("/prompt/style/generate", { method: "POST", body: JSON.stringify({ text, model }) }),
  styleAdd: (chunks) =>
    j("/prompt/style/add", { method: "POST", body: JSON.stringify({ chunks }) }),
};
