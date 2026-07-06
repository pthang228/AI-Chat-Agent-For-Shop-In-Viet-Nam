// Liên hệ khẩn cấp & Thông báo — bridge 5005, chỉ CHỦ shop (owner).
import { withAuth } from "./apiAuth.js";

import { HOST } from "./apiConfig.js";
const BASE = HOST.bridge;

async function j(path, opts) {
  try {
    const r = await fetch(BASE + path, withAuth(opts));
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };
  }
}

export const notifyApi = {
  get: () => j("/notify/config"),
  set: (config) => j("/notify/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  }),
};
