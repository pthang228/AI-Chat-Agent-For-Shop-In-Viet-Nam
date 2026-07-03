// Gọi API Prompt Builder (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

const URL = "http://localhost:5005";

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
  // AI viết prompt — chậm (20-60s), đừng đặt timeout phía UI
  generate: (links, instructions) =>
    j("/prompt/generate", { method: "POST", body: JSON.stringify({ links, instructions }) }),
  apply: (prompt) =>
    j("/prompt/apply", { method: "POST", body: JSON.stringify({ prompt }) }),
  restoreDefault: () => j("/prompt/restore-default", { method: "POST" }),
};
