// Auth TẠM THỜI bằng localStorage (chưa có backend, mật khẩu chưa mã hoá).
// Chỉ để chạy luồng UI. Khi lên production sẽ thay bằng API backend thật.

const USERS_KEY = "hb_users";
const SESSION_KEY = "hb_session";

function getUsers() {
  try { return JSON.parse(localStorage.getItem(USERS_KEY)) || {}; }
  catch { return {}; }
}
function setUsers(u) { localStorage.setItem(USERS_KEY, JSON.stringify(u)); }

export function register({ username, password, homestay }) {
  username = (username || "").trim().toLowerCase();
  if (!username || !password) throw new Error("Vui lòng nhập tên đăng nhập và mật khẩu");
  if (password.length < 4) throw new Error("Mật khẩu tối thiểu 4 ký tự");
  const users = getUsers();
  if (users[username]) throw new Error("Tên đăng nhập đã tồn tại");
  users[username] = { username, password, homestay: (homestay || "").trim(), createdAt: Date.now() };
  setUsers(users);
  localStorage.setItem(SESSION_KEY, username);
  return users[username];
}

export function login({ username, password }) {
  username = (username || "").trim().toLowerCase();
  const u = getUsers()[username];
  if (!u || u.password !== password) throw new Error("Sai tên đăng nhập hoặc mật khẩu");
  localStorage.setItem(SESSION_KEY, username);
  return u;
}

export function logout() { localStorage.removeItem(SESSION_KEY); }

export function currentUser() {
  const s = localStorage.getItem(SESSION_KEY);
  if (!s) return null;
  return getUsers()[s] || null;
}
