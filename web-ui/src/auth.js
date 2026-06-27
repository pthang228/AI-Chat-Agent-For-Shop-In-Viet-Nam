// Auth TẠM THỜI bằng localStorage (chưa có backend, mật khẩu chưa mã hoá).
// Hỗ trợ đăng nhập bằng mật khẩu hoặc Google (Gmail). Lên production thay bằng API thật.

const USERS_KEY = "hb_users";
const SESSION_KEY = "hb_session";

function getUsers() {
  try { return JSON.parse(localStorage.getItem(USERS_KEY)) || {}; }
  catch { return {}; }
}
function setUsers(u) { localStorage.setItem(USERS_KEY, JSON.stringify(u)); }

// Ghi nhớ = lưu phiên ở localStorage (còn sau khi đóng trình duyệt).
// Không ghi nhớ = lưu ở sessionStorage (mất khi đóng tab/trình duyệt).
function setSession(username, remember) {
  localStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(SESSION_KEY);
  (remember ? localStorage : sessionStorage).setItem(SESSION_KEY, username);
}

export function register({ username, password, homestay, remember = true }) {
  username = (username || "").trim().toLowerCase();
  if (!username || !password) throw new Error("Vui lòng nhập email và mật khẩu");
  if (password.length < 4) throw new Error("Mật khẩu tối thiểu 4 ký tự");
  const users = getUsers();
  if (users[username]) throw new Error("Tài khoản đã tồn tại");
  users[username] = { username, password, provider: "password", homestay: (homestay || "").trim(), createdAt: Date.now() };
  setUsers(users);
  setSession(username, remember);
  return users[username];
}

export function login({ username, password, remember = true }) {
  username = (username || "").trim().toLowerCase();
  const u = getUsers()[username];
  if (!u || u.password !== password) throw new Error("Sai email hoặc mật khẩu");
  setSession(username, remember);
  return u;
}

// Đăng nhập / đăng ký bằng Google — định danh theo email, không cần mật khẩu.
export function loginWithGoogle({ email, name, picture }) {
  const username = (email || "").trim().toLowerCase();
  if (!username) throw new Error("Không lấy được email từ Google");
  const users = getUsers();
  if (!users[username]) {
    users[username] = { username, password: null, provider: "google", homestay: (name || "").trim(), picture: picture || "", createdAt: Date.now() };
  } else {
    if (!users[username].provider) users[username].provider = "google";
    if (picture) users[username].picture = picture;
    if (!users[username].homestay && name) users[username].homestay = name;
  }
  setUsers(users);
  setSession(username, true);
  return users[username];
}

export function updateProfile({ username, homestay, email }) {
  username = (username || "").trim().toLowerCase();
  const users = getUsers();
  if (!users[username]) throw new Error("Không tìm thấy tài khoản");
  if (email !== undefined) {
    email = (email || "").trim();
    if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) throw new Error("Email không hợp lệ");
    users[username].email = email;
  }
  if (homestay !== undefined) users[username].homestay = (homestay || "").trim();
  setUsers(users);
  return users[username];
}

export function changePassword({ username, oldPassword, newPassword }) {
  username = (username || "").trim().toLowerCase();
  const users = getUsers();
  const u = users[username];
  if (!u) throw new Error("Không tìm thấy tài khoản");
  if (u.provider === "google" && !u.password) throw new Error("Tài khoản Google đăng nhập bằng Gmail, không có mật khẩu");
  if (u.password && u.password !== oldPassword) throw new Error("Mật khẩu hiện tại không đúng");
  if ((newPassword || "").length < 4) throw new Error("Mật khẩu mới tối thiểu 4 ký tự");
  u.password = newPassword;
  setUsers(users);
  return u;
}

export function logout() {
  localStorage.removeItem(SESSION_KEY);
  sessionStorage.removeItem(SESSION_KEY);
}

export function currentUser() {
  const s = localStorage.getItem(SESSION_KEY) || sessionStorage.getItem(SESSION_KEY);
  if (!s) return null;
  return getUsers()[s] || null;
}
