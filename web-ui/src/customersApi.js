// API CRM Khách hàng (bridge 5005) — kèm Bearer token.
import { getToken } from "./auth.js";

import { HOST } from "./apiConfig.js";
const URL = HOST.bridge;

async function j(path, opts = {}) {
  try {
    const r = await fetch(URL + path, {
      ...opts,
      headers: {
        Authorization: `Bearer ${getToken()}`,
        ...(opts.body ? { "Content-Type": "application/json" } : {}),
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

const enc = encodeURIComponent;
const base = (acc, uid) => `/customers/${enc(acc)}/${enc(uid)}`;

export const customersApi = {
  list: ({ q = "", platform = "", limit = 200, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (q) p.set("q", q);
    if (platform) p.set("platform", platform);
    return j("/customers?" + p.toString());
  },
  get: (acc, uid) => j(base(acc, uid)),
  update: (acc, uid, fields) =>
    j(base(acc, uid), { method: "PATCH", body: JSON.stringify(fields) }),
  scan: (acc, uid) => j(base(acc, uid) + "/scan", { method: "POST" }),
  orders: (acc, uid) => j(base(acc, uid) + "/orders"),
  memoryAdd: (acc, uid, content) =>
    j(base(acc, uid) + "/memory", { method: "POST", body: JSON.stringify({ content }) }),
  memoryAi: (acc, uid) => j(base(acc, uid) + "/memory/ai", { method: "POST" }),
  memoryDel: (id) => j("/customers/memory/" + id, { method: "DELETE" }),
};
