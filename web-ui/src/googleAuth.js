// Đăng nhập Google bằng Google Identity Services (GIS) — chạy phía trình duyệt.
// Cần OAuth Client ID (tạo ở Google Cloud Console) đặt trong web-ui/.env:
//   VITE_GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
// và thêm origin vào "Authorized JavaScript origins" — thêm CẢ http://localhost:5173
// LẪN http://127.0.0.1:5173 (origin tính theo URL trên thanh địa chỉ trình duyệt).

export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";

let _loading;
export function loadGis() {
  if (window.google?.accounts?.id) return Promise.resolve(window.google);
  if (_loading) return _loading;
  _loading = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://accounts.google.com/gsi/client";
    s.async = true; s.defer = true;
    s.onload = () => resolve(window.google);
    s.onerror = () => reject(new Error("Không tải được Google Sign-In"));
    document.head.appendChild(s);
  });
  return _loading;
}

// Giải mã phần payload của JWT (id_token) để lấy email/name/picture (không xác thực chữ ký — chỉ đọc).
export function decodeJwt(token) {
  try {
    const b64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const json = decodeURIComponent(
      atob(b64).split("").map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)).join("")
    );
    return JSON.parse(json);
  } catch { return {}; }
}

// Khởi tạo + render nút Google vào phần tử el.
// onUser nhận {credential, email, name, picture} — credential (id_token) được gửi
// cho BACKEND xác thực với Google (decode client-side chỉ để hiển thị nhanh).
export async function renderGoogleButton(el, onUser) {
  if (!GOOGLE_CLIENT_ID || !el) return false;
  const google = await loadGis();
  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: ({ credential }) => {
      const p = decodeJwt(credential);
      onUser({ credential, email: p.email, name: p.name, picture: p.picture });
    },
  });
  google.accounts.id.renderButton(el, { theme: "outline", size: "large", text: "continue_with", shape: "pill", locale: "vi", width: 320 });
  return true;
}
