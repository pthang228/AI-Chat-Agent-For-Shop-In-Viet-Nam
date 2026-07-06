// TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — bridge 5005, chỉ CHỦ (owner).
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

const json = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const broadcastApi = {
  preview: (channels, segment) => j("/broadcasts/preview", json("POST", { channels, segment })),
  list: () => j("/broadcasts"),
  create: (payload) => j("/broadcasts", json("POST", payload)),
  get: (id) => j("/broadcasts/" + id),
  send: (id) => j(`/broadcasts/${id}/send`, { method: "POST" }),
  cancel: (id) => j(`/broadcasts/${id}/cancel`, { method: "POST" }),
};
