// Lưu danh sách "app" (kênh bot) theo từng tài khoản — tạm thời bằng localStorage.

const APPS_KEY = "hb_apps";

function all() {
  try { return JSON.parse(localStorage.getItem(APPS_KEY)) || {}; }
  catch { return {}; }
}
function save(a) { localStorage.setItem(APPS_KEY, JSON.stringify(a)); }

export function getApps(username) {
  return all()[username] || [];
}

export function addApp(username, { name, channel }) {
  const a = all();
  const list = a[username] || [];
  const item = {
    id: (crypto.randomUUID ? crypto.randomUUID() : String(Date.now())),
    name: (name || "").trim() || "App chưa đặt tên",
    channel: channel || "zalo",
    connected: false,
    createdAt: Date.now(),
  };
  list.push(item);
  a[username] = list;
  save(a);
  return item;
}

export function removeApp(username, id) {
  const a = all();
  a[username] = (a[username] || []).filter((x) => x.id !== id);
  save(a);
}
