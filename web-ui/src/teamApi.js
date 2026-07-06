// TEAM — quản lý nhân viên (chủ) + danh sách thành viên workspace (mọi người).
// Backend: bridge 5005 (auth_api). /team* chỉ CHỦ; /teammates cả nhân viên đọc được.
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

export const teamApi = {
  list: () => j("/team"),
  add: (email, name, password) => j("/team", json("POST", { email, name, password })),
  update: (username, patch) => j("/team/" + encodeURIComponent(username), json("PATCH", patch)),
  remove: (username) => j("/team/" + encodeURIComponent(username), { method: "DELETE" }),
  teammates: () => j("/teammates"),
};
