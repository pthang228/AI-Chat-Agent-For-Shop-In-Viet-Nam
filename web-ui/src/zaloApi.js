// Gọi trực tiếp Node service (zca-js) — đã bật CORS nên fetch từ React được.
// Sau này multi-tenant sẽ đổi URL theo từng app/tenant.
const NODE_URL = "http://localhost:4000";

async function j(path, opts) {
  const r = await fetch(NODE_URL + path, opts);
  // 400/409 là trạng thái hợp lệ (chưa chọn nhóm / chưa đăng nhập) — vẫn trả body
  let body = {};
  try { body = await r.json(); } catch { /* ignore */ }
  return { ok: r.ok, status: r.status, body };
}

export const zalo = {
  status: () => j("/status"),
  startQR: () => j("/login/qr", { method: "POST" }),
  groups: () => j("/groups"),
  getConfig: () => j("/config"),
  saveGroup: (ownerGroupId) =>
    j("/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ownerGroupId }),
    }),
  logout: () => j("/logout", { method: "POST" }),
};
