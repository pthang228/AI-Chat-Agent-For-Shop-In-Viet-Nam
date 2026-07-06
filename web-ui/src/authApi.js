// Gọi API auth thật (nằm trong bridge Flask, cổng 5005) — users/token/apps trong SQLite.
const AUTH_URL = "http://127.0.0.1:5005";

async function j(path, opts = {}) {
  try {
    const r = await fetch(AUTH_URL + path, opts);
    let body = null;
    try { body = await r.json(); } catch { /* ignore */ }
    return { ok: r.ok, status: r.status, body };
  } catch {
    return { ok: false, status: 0, body: null };  // server 5005 chưa chạy → offline
  }
}

const json = (body, token) => ({
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  },
  body: JSON.stringify(body),
});
const auth = (token, method = "GET") => ({
  method,
  headers: { Authorization: `Bearer ${token}` },
});

export const authApi = {
  register: (username, password, homestay, promo = "") =>
    j("/auth/register", json({ username, password, homestay, promo })),
  login: (username, password) =>
    j("/auth/login", json({ username, password })),
  google: (credential) =>
    j("/auth/google", json({ credential })),
  me: (token) => j("/auth/me", auth(token)),
  logout: (token) => j("/auth/logout", auth(token, "POST")),
  update: (token, { homestay, email }) =>
    j("/auth/update", json({ homestay, email }, token)),
  password: (token, oldPassword, newPassword) =>
    j("/auth/password", json({ old_password: oldPassword, new_password: newPassword }, token)),

  apps: (token) => j("/auth/apps", auth(token)),
  addApp: (token, { name, channel }) => j("/auth/apps", json({ name, channel }, token)),
  removeApp: (token, id) => j("/auth/apps/" + encodeURIComponent(id), auth(token, "DELETE")),
};

export const OFFLINE_MSG =
  "Không kết nối được máy chủ (cổng 5005). Chạy start-all.bat (hoặc python -m app.main_node) rồi thử lại.";
