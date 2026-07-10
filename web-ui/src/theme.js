// Chủ đề sáng/tối — lưu localStorage, áp qua <html data-theme="...">.
// Gọi applyTheme(getTheme()) SỚM (main.jsx) để không chớp nền sáng khi mở app.
const KEY = "hb_theme";

export function getTheme() {
  return localStorage.getItem(KEY) === "dark" ? "dark" : "light";
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

export function setTheme(theme) {
  localStorage.setItem(KEY, theme);
  applyTheme(theme);
}
