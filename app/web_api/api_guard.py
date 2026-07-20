"""
Lớp bảo vệ + hạ tầng dùng chung cho MỌI server Flask (bridge + 5 kênh):

1. CORS chuẩn — chỉ cho phép origin trong Config.ALLOWED_ORIGINS (thay '*'),
   và MỞ header Authorization (bắt buộc, vì client giờ gửi Bearer token).
2. install_auth_guard — chặn mọi request KHÔNG có Bearer token hợp lệ, TRỪ các
   đường dẫn công khai (webhook nền tảng, health, config, phục vụ media, đăng
   nhập…). Đây là cái vá lỗ hổng: trước đây /conversations/*/send, /*/connect,
   toggle, delete… ai gọi cũng được — trong khi cổng Meta (5006) đã phơi ra
   internet qua ngrok.
3. DedupCache — nhớ id sự kiện đã xử lý (webhook nền tảng gửi lại khi ta chậm).
4. get_pool/submit — ThreadPoolExecutor trần Config.WORKER_THREADS thay cho việc
   đẻ 1 thread/tin không giới hạn (spam tin = sập CPU/RAM).

Token được xác thực qua bảng auth_tokens trong SQLite dùng chung (mọi tiến trình
đọc cùng data/homestay.db) — giống cách các endpoint connect đã dùng
auth_api.current_username().
"""

import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from flask import request

from app.core.config import Config

log = logging.getLogger("api_guard")


def _guard_enabled() -> bool:
    """Cho phép tắt guard khi chạy test (API_AUTH_GUARD=0). Đọc lúc request để
    test có thể bật/tắt linh hoạt. Mặc định BẬT (production)."""
    return os.getenv("API_AUTH_GUARD", "1").strip().lower() in ("1", "true", "yes", "on")


# ── CORS ────────────────────────────────────────────────────────────

def add_cors(resp):
    origin = request.headers.get("Origin", "")
    allowed = Config.ALLOWED_ORIGINS
    # Origin hợp lệ → phản chiếu đúng nó. Không hợp lệ → KHÔNG set Allow-Origin
    # (trình duyệt tự chặn) thay vì phản chiếu allowed[0] gây hiểu nhầm. Request
    # server-to-server (webhook, không có Origin) không cần header này.
    if origin and origin in allowed:
        resp.headers["Access-Control-Allow-Origin"] = origin
    resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp


def install_cors(app):
    app.after_request(add_cors)


# ── Auth guard ──────────────────────────────────────────────────────

def _bearer_token() -> str:
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else ""


def _is_public(path: str, public_exact, public_prefixes) -> bool:
    if path in public_exact:
        return True
    return any(path.startswith(p) for p in public_prefixes)


def _parse_deny(entries):
    """Chuẩn hoá staff_deny: mỗi entry là "tiền_tố" (mọi method) hoặc
    "METHOD tiền_tố" (chỉ method đó). Trả list (method|None, prefix)."""
    rules = []
    for e in entries:
        e = (e or "").strip()
        if not e:
            continue
        if " " in e:
            m, p = e.split(None, 1)
            rules.append((m.upper(), p.strip()))
        else:
            rules.append((None, e))
    return rules


def _staff_denied(method, path, rules) -> bool:
    for m, prefix in rules:
        if m is not None and m != method:
            continue
        # Khớp theo RANH GIỚI segment: "/team" chặn "/team" và "/team/x"
        # nhưng KHÔNG chặn "/teammates" (prefix trần sẽ dính nhầm).
        if path == prefix or path.startswith(prefix + "/"):
            return True
    return False


def install_auth_guard(app, public_exact=(), public_prefixes=(), staff_deny=()):
    """Chặn request thiếu/hỏng Bearer token, trừ đường dẫn công khai.
    public_exact: set path đúng-tuyệt-đối công khai. public_prefixes: tiền tố.
    staff_deny: các route tài khoản NHÂN VIÊN (role=staff) bị cấm — entry dạng
    "tiền_tố" hoặc "METHOD tiền_tố" (vd "DELETE /conversations"). Chủ (owner)
    không bị giới hạn. User đã xác thực được gắn vào flask.g.auth_user."""
    public_exact = set(public_exact) | {"/health"}
    public_prefixes = tuple(public_prefixes)
    deny_rules = _parse_deny(staff_deny)

    @app.before_request
    def _guard():
        if not _guard_enabled():            # tắt trong test
            return None
        if request.method == "OPTIONS":     # preflight CORS → luôn cho qua
            return None
        path = request.path.rstrip("/") or "/"
        # so cả path gốc lẫn path đã bỏ '/' cuối để khớp linh hoạt
        if _is_public(request.path, public_exact, public_prefixes) or \
           _is_public(path, public_exact, public_prefixes):
            return None
        from app.web_api.auth_api import _user_for_token, role_of
        from app.core.db import get_db
        u = _user_for_token(get_db(), _bearer_token())
        if u is None:
            return {"ok": False, "error": "Cần đăng nhập (token không hợp lệ hoặc hết hạn)"}, 401
        from flask import g
        g.auth_user = u
        if role_of(u) == "staff" and (
                _staff_denied(request.method, request.path, deny_rules)
                or _staff_denied(request.method, path, deny_rules)):
            return {"ok": False, "error": "Tài khoản nhân viên không có quyền dùng chức năng này"}, 403
        return None


# ── Health SÂU (dùng chung 7 server) ────────────────────────────────

def health_payload():
    """Trả (body, status) cho /health: CHẠM DB thật + kiểm disk còn chỗ.
    Trước đây trả {"ok": True} tĩnh — disk đầy/DB hỏng thì mọi request nghiệp
    vụ 500 nhưng healthcheck vẫn xanh, che mất sự cố đúng lúc cần thấy nhất.
    503 khi hỏng để Docker healthcheck + uptime monitor (UptimeRobot) bắt được."""
    import shutil
    from app.core.config import Config
    from app.core.db import get_db
    db_ok = True
    try:
        get_db().query("SELECT 1")
    except Exception as e:
        db_ok = False
        log.error(f"[health] DB lỗi: {e}")
    free_mb = None
    try:
        free_mb = shutil.disk_usage(str(Config.DATA_DIR)).free // (1024 * 1024)
    except Exception:
        pass
    disk_ok = free_mb is None or free_mb > 200   # <200MB là WAL/backup sắp nghẹt
    ok = db_ok and disk_ok
    return {"ok": ok, "db": db_ok, "disk_free_mb": free_mb}, (200 if ok else 503)


# ── MULTI-TENANT: quyền sở hữu account kênh (dùng chung mọi *_api) ──
# Bài học IDOR: guard này từng CHỈ có ở telegram_api (_own_bot_or_404), 5 kênh
# copy còn lại bị bỏ quên → shop A liệt kê/xoá/tắt được kênh của shop B.
# Đặt 1 chỗ ở đây cho mọi kênh dùng chung — thêm kênh mới không phải chép tay.

def tenant_ctx():
    """(workspace đăng nhập — staff quy về chủ, có phải quản trị nền tảng).
    (None, False) khi không có ngữ cảnh đăng nhập (test / guard tắt)."""
    try:
        from app.web_api.auth_api import current_workspace
        from app.core import tenant as _t
        ws = current_workspace()
        return ws, _t.is_platform_admin(ws)
    except Exception:
        return None, False


def own_account_or_404(store, account_id):
    """None nếu workspace hiện tại được thao tác account kênh này (chủ sở hữu /
    quản trị nền tảng / không có ngữ cảnh đăng nhập — như tenant.visible);
    ngược lại (json, 404) — trả 404 chứ không 403 để khỏi lộ account_id tồn tại.
    Account KHÔNG có chủ (kết nối cũ) chỉ quản trị nền tảng đụng được."""
    ws, is_admin = tenant_ctx()
    if ws is None or is_admin:
        return None
    try:
        owner = store.get_owner_username(account_id) if store else None
    except Exception:
        owner = None
    if owner and owner == ws:
        return None
    return {"ok": False, "error": "not found"}, 404


def filter_owned(store, rows, id_key):
    """Lọc danh sách account kênh theo workspace đăng nhập (quản trị nền tảng
    thấy hết; account không chủ — kết nối cũ — chỉ quản trị thấy)."""
    ws, is_admin = tenant_ctx()
    if ws is None or is_admin:
        return rows
    out = []
    for r in rows:
        try:
            if store.get_owner_username(r.get(id_key)) == ws:
                out.append(r)
        except Exception:
            pass
    return out


# ── Dedup sự kiện webhook ───────────────────────────────────────────

class DedupCache:
    """Nhớ N id gần nhất (thread-safe). seen(id) trả True nếu id ĐÃ gặp."""

    def __init__(self, maxlen: int = 500):
        self._max = maxlen
        self._d: "OrderedDict[str, bool]" = OrderedDict()
        self._lock = threading.Lock()

    def seen(self, key: str) -> bool:
        if not key:
            return False           # không có id → không thể dedup, cứ xử lý
        with self._lock:
            if key in self._d:
                return True
            self._d[key] = True
            while len(self._d) > self._max:
                self._d.popitem(last=False)
        return False

    def clear(self):
        with self._lock:
            self._d.clear()


# ── Thread pool xử lý tin (trần WORKER_THREADS) ─────────────────────

_pool = None
_pool_lock = threading.Lock()


def get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadPoolExecutor(
                    max_workers=max(1, Config.WORKER_THREADS),
                    thread_name_prefix="msg",
                )
    return _pool


def _safe(fn, args, kwargs):
    """Chạy task + LOG lỗi. Không có wrapper này thì exception trong task bị
    ThreadPoolExecutor nuốt hoàn toàn (Future không ai đọc) → lỗi học tri thức/
    backfill/xử lý webhook biến mất âm thầm, không debug được."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        log.error(f"[pool] task {getattr(fn, '__name__', fn)} lỗi: {e}", exc_info=True)


def submit(fn, *args, **kwargs):
    """Chạy fn trong pool dùng chung. Nuốt lỗi submit (pool đóng lúc tắt) để
    không làm sập route webhook. WORKER_SYNC=1 → chạy ĐỒNG BỘ (cho test kiểm
    tra kết quả ngay, không cần chờ thread)."""
    if os.getenv("WORKER_SYNC", "").strip().lower() in ("1", "true", "yes", "on"):
        _safe(fn, args, kwargs)
        return
    try:
        get_pool().submit(_safe, fn, args, kwargs)
    except Exception as e:
        log.error(f"[pool] không submit được task: {e}")
