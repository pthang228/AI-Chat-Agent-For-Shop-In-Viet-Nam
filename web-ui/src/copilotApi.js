// API Copilot quản trị (bridge 5005) — kèm Bearer token.
// Dùng httpClient chung (api/http.js). handle401:false vì AdminCopilot tự hiện
// lời nhắn "phiên hết hạn" trong khung chat (UX cũ) thay vì bị đá về /login giữa chừng.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const post = makeClient(HOST.bridge, { handle401: false });
const j = (path, body) => post(path, { method: "POST", json: body });

export const copilotApi = {
  chat: (message, history = []) => j("/copilot/chat", { message, history }),
  confirm: (name, args, sig) => j("/copilot/confirm", { name, args, sig }),
};
