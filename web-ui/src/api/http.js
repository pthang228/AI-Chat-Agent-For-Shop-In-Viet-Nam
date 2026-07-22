// httpClient DUY NHẤT cho mọi API client — thay ~20 bản sao j() + fetch rải rác.
//
// - getToken(): NGUỒN DUY NHẤT đọc token phiên. Sau này đổi cách lưu token
//   (vd. chuyển cookie) chỉ cần sửa Ở ĐÂY, không đụng 20 file client.
// - request(): fetch + parse JSON + tự gắn Bearer + bắt 401 TẬP TRUNG:
//   token ĐÃ gắn mà server vẫn trả 401 = phiên hết hạn → xoá phiên + đưa về
//   /login (khớp UX cũ: Billing/PromptBuilder từng tự nav("/login") tay).
// - makeClient(base, defaults): tạo hàm j(path, opts) cho từng file client —
//   GIỮ NGUYÊN chữ ký j(path, opts) cũ nên các object export (brain, meta, tg…)
//   và component đang import chúng không phải sửa.

const TOKEN_KEY = "hb_token";
const USER_KEY = "hb_user";
const SHOP_KEY = "hb_shop";   // SHOP CON đang chọn ('' = shop mặc định)

// Token lưu ở localStorage (ghi nhớ đăng nhập) hoặc sessionStorage (mất khi đóng tab)
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || "";
}

// SHOP CON: ws shop đang làm việc — đính header X-Shop vào MỌI request để
// backend trả đúng dữ liệu shop đó (kênh/hội thoại/khách/đơn/não AI riêng).
export function getActiveShop() {
  return localStorage.getItem(SHOP_KEY) || "";
}
export function setActiveShop(ws) {
  if (ws) localStorage.setItem(SHOP_KEY, ws);
  else localStorage.removeItem(SHOP_KEY);
}

// Xoá sạch phiên ở CẢ 2 storage (đăng xuất / token hết hạn)
export function clearSession() {
  for (const s of [localStorage, sessionStorage]) {
    s.removeItem(TOKEN_KEY);
    s.removeItem(USER_KEY);
    s.removeItem(SHOP_KEY);
    s.removeItem("hb_session"); // phiên kiểu cũ
  }
}

// auth.js cần ghi token/user đúng key — export để không hard-code 2 nơi
export { TOKEN_KEY, USER_KEY };

// 401 khi ĐÃ gắn token = phiên hết hạn → xoá phiên + về trang đăng nhập.
// Dùng window.location (không phụ thuộc react-router) vì client nằm ngoài component tree.
function onSessionExpired() {
  clearSession();
  if (typeof window !== "undefined" && window.location.pathname !== "/login") {
    window.location.assign("/login");
  }
}

// opts nhận mọi thứ của fetch, THÊM:
//   auth:      true (mặc định) = tự gắn Bearer nếu đã đăng nhập
//   handle401: true (mặc định) = 401 có token → xoá phiên + về /login.
//              false cho endpoint coi 401 là kết quả bình thường
//              (đăng nhập sai, đổi mật khẩu sai mật khẩu cũ…)
//   json:      object → tự JSON.stringify + Content-Type: application/json
//   fallbackBody: body trả về khi offline (status 0) / response không phải JSON
// Trả về LUÔN LUÔN {ok, status, body} — không bao giờ throw (offline → status 0).
export async function request(base, path, opts = {}) {
  const {
    auth = true,
    handle401 = true,
    json,
    fallbackBody = null,
    headers: extraHeaders,
    ...rest
  } = opts;

  const headers = { ...(extraHeaders || {}) };
  let body = rest.body;
  if (json !== undefined) {
    body = JSON.stringify(json);
    if (!headers["Content-Type"]) headers["Content-Type"] = "application/json";
  } else if (typeof body === "string" && !headers["Content-Type"]) {
    // body đã stringify sẵn (kiểu cũ của billing/customers…) → vẫn tự thêm
    // Content-Type như các bản j() trước đây. FormData thì KHÔNG đụng vào
    // (trình duyệt tự set multipart boundary).
    headers["Content-Type"] = "application/json";
  }
  const token = auth ? getToken() : "";
  if (token && !headers.Authorization) headers.Authorization = `Bearer ${token}`;
  // X-Shop đi kèm MỌI request có đăng nhập — kể cả client kiểu cũ truyền token
  // tường minh với auth:false (authApi…); điều kiện là CÓ Authorization, không
  // phải cờ auth (bẫy đã dính: addApp rơi vào shop mặc định vì thiếu header)
  const shop = getActiveShop();
  if (shop && headers.Authorization && !headers["X-Shop"]) headers["X-Shop"] = shop;

  try {
    const r = await fetch(base + path, { ...rest, headers, body });
    let b = fallbackBody;
    try { b = await r.json(); } catch { /* body không phải JSON → fallback */ }
    if (r.status === 401 && handle401 && token) onSessionExpired();
    return { ok: r.ok, status: r.status, body: b };
  } catch {
    // server chưa chạy / mạng lỗi → UI hiện "offline", không treo
    return { ok: false, status: 0, body: fallbackBody };
  }
}

// Tạo hàm j(path, opts) gắn sẵn base URL + mặc định riêng của từng client
export function makeClient(base, defaults = {}) {
  return (path, opts = {}) => request(base, path, { ...defaults, ...opts });
}
