// API Copilot quản trị (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

const URL = "http://127.0.0.1:5005";

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
