// API Copilot quản trị (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

import { HOST } from "./apiConfig.js";
const URL = HOST.bridge;

async function j(path, body) {
  try {
    const r = await fetch(URL + path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify(body),
    });
    let b = null;
    try { b = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body: b };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export const copilotApi = {
  chat: (message, history = []) => j("/copilot/chat", { message, history }),
  confirm: (name, args, sig) => j("/copilot/confirm", { name, args, sig }),
};
