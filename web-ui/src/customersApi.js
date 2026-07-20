// API CRM Khách hàng (bridge 5005) — kèm Bearer token.
// j = httpClient chung (api/http.js): tự gắn Bearer + Content-Type + bắt 401.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

const enc = encodeURIComponent;
const base = (acc, uid) => `/customers/${enc(acc)}/${enc(uid)}`;

export const customersApi = {
  list: ({ q = "", platform = "", tag = "", stage = "", limit = 200, offset = 0 } = {}) => {
    const p = new URLSearchParams({ limit, offset });
    if (q) p.set("q", q);
    if (platform) p.set("platform", platform);
    if (tag) p.set("tag", tag);
    if (stage) p.set("stage", stage);
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

  // Tag / gộp trùng / điểm / nhắc việc (CRM nâng cấp 2026-07)
  tags: () => j("/customers/tags"),
  duplicates: () => j("/customers/duplicates"),
  merge: (primary, duplicate) =>
    j("/customers/merge", { method: "POST", body: JSON.stringify({ primary, duplicate }) }),
  pointsAdjust: (acc, uid, delta, reason = "") =>
    j(base(acc, uid) + "/points", { method: "POST", body: JSON.stringify({ delta, reason }) }),
  followupAdd: (acc, uid, note, due_at) =>
    j(base(acc, uid) + "/followups", { method: "POST", body: JSON.stringify({ note, due_at }) }),
  followups: () => j("/followups"),
  followupDone: (id) => j(`/followups/${id}/done`, { method: "POST" }),
  followupDel: (id) => j(`/followups/${id}`, { method: "DELETE" }),
};
