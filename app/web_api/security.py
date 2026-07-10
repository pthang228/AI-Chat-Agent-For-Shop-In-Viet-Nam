"""
Lớp bảo mật CƠ SỞ dùng chung cho MỌI server Flask (bridge + các kênh).

Bổ sung cho api_guard.py (auth token + CORS) 3 lớp phòng thủ mạng:

1. RateLimiter — giới hạn số request/IP trong cửa sổ trượt. Chặn spam/DoS ở các
   endpoint nhạy cảm (đăng nhập, đăng ký) trước khi chúng chạm DB/CPU.
2. LoginGuard — chống DÒ MẬT KHẨU (brute-force): đếm số lần đăng nhập SAI theo
   (username + IP), khoá tạm tăng dần khi vượt ngưỡng. Đây là lỗ hổng nghiêm
   trọng nhất trước khi có lớp này: /auth/login cho thử mật khẩu vô hạn.
3. security headers — HSTS (ép HTTPS), X-Frame-Options (chống clickjacking),
   X-Content-Type-Options, Referrer-Policy, CSP tối thiểu cho API.

Tất cả in-memory theo TIẾN TRÌNH (đăng nhập chỉ xảy ra ở bridge 5005 nên đủ);
không cần Redis cho quy mô hiện tại. Tắt trong test bằng API_AUTH_GUARD=0
(tái dùng cờ có sẵn — test tắt auth guard cũng tắt luôn rate-limit/lockout).
"""

import logging
import os
import threading
import time
from collections import defaultdict, deque

from flask import request

log = logging.getLogger("security")


def _security_enabled() -> bool:
    """Tắt cùng lúc với auth guard trong test (API_AUTH_GUARD=0)."""
    return os.getenv("API_AUTH_GUARD", "1").strip().lower() in ("1", "true", "yes", "on")


def client_ip() -> str:
    """IP thật của client. Sau reverse proxy (nginx/cloudflare) dùng header
    X-Forwarded-For (IP đầu tiên = client gốc). LƯU Ý: chỉ tin header này khi
    CÓ proxy tin cậy đứng trước — bật qua TRUST_PROXY=1 ở production."""
    if os.getenv("TRUST_PROXY", "").strip().lower() in ("1", "true", "yes", "on"):
        xff = request.headers.get("X-Forwarded-For", "")
        if xff:
            return xff.split(",")[0].strip()
    return request.remote_addr or "?"


# ── Rate limiter (cửa sổ trượt theo IP) ─────────────────────────────

class RateLimiter:
    """Giới hạn N request / window giây / khoá (IP hoặc IP+path).
    Cửa sổ trượt bằng deque timestamp — chính xác hơn fixed-window (không cho
    dồn 2N request quanh mốc reset)."""

    def __init__(self, limit: int, window: float):
        self.limit = limit
        self.window = window
        self._hits: "dict[str, deque]" = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> bool:
        """Ghi 1 lần gọi. Trả True nếu CÒN trong hạn mức, False nếu VƯỢT."""
        now = time.monotonic()
        with self._lock:
            dq = self._hits[key]
            cutoff = now - self.window
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(dq) >= self.limit:
                return False
            dq.append(now)
            # Dọn rác định kỳ: khoá không còn hit nào thì bỏ (tránh phình RAM)
            if len(self._hits) > 10_000:
                self._gc(cutoff)
            return True

    def _gc(self, cutoff):
        for k in [k for k, d in self._hits.items() if not d or d[-1] < cutoff]:
            self._hits.pop(k, None)

    def clear(self):
        with self._lock:
            self._hits.clear()


# ── Chống dò mật khẩu (login lockout) ───────────────────────────────

class LoginGuard:
    """Khoá tạm theo (username|IP) sau nhiều lần đăng nhập SAI. Khoá tăng dần:
    5 lần sai → khoá 1 phút; mỗi 5 lần tiếp → gấp đôi, trần 30 phút. Đăng nhập
    ĐÚNG xoá bộ đếm. Chống cả dò 1 tài khoản lẫn 1 IP rải nhiều tài khoản."""

    THRESHOLD = 5
    BASE_LOCK = 60.0          # giây
    MAX_LOCK = 1800.0         # 30 phút

    def __init__(self):
        self._fail: "dict[str, int]" = defaultdict(int)
        self._until: "dict[str, float]" = {}
        self._lock = threading.Lock()

    @staticmethod
    def _keys(username: str, ip: str):
        # Khoá theo cả tài khoản-trên-IP LẪN IP tổng (chặn rải nhiều account/1 IP)
        return (f"u:{(username or '').lower()}|{ip}", f"ip:{ip}")

    def locked_for(self, username: str, ip: str) -> float:
        """Số giây còn bị khoá (0 = không khoá)."""
        now = time.monotonic()
        with self._lock:
            wait = 0.0
            for k in self._keys(username, ip):
                u = self._until.get(k, 0)
                if u > now:
                    wait = max(wait, u - now)
            return wait

    def record_fail(self, username: str, ip: str):
        now = time.monotonic()
        with self._lock:
            for k in self._keys(username, ip):
                self._fail[k] += 1
                n = self._fail[k]
                if n >= self.THRESHOLD:
                    steps = n // self.THRESHOLD
                    lock = min(self.BASE_LOCK * (2 ** (steps - 1)), self.MAX_LOCK)
                    self._until[k] = now + lock

    def record_success(self, username: str, ip: str):
        with self._lock:
            for k in self._keys(username, ip):
                self._fail.pop(k, None)
                self._until.pop(k, None)

    def clear(self):
        with self._lock:
            self._fail.clear()
            self._until.clear()


# Instance dùng chung toàn tiến trình
login_guard = LoginGuard()
_login_limiter = RateLimiter(limit=10, window=60.0)     # 10 lần thử login/IP/phút
_signup_limiter = RateLimiter(limit=5, window=300.0)    # 5 đăng ký/IP/5 phút
_global_limiter = RateLimiter(limit=300, window=60.0)   # trần chung 300 req/IP/phút

# Endpoint nhạy cảm → limiter riêng (khắt khe hơn trần chung)
_SENSITIVE = {
    "/auth/login": _login_limiter,
    "/auth/google": _login_limiter,
    "/auth/register": _signup_limiter,
}


# ── Cài đặt vào app ─────────────────────────────────────────────────

def install_security(app, enable_global_limit: bool = True):
    """Gắn rate-limit + security headers cho 1 Flask app. Gọi SAU install_cors
    và TRƯỚC/không đụng install_auth_guard (chúng độc lập). enable_global_limit:
    trần chung mọi request (tắt cho tiến trình chỉ có webhook nếu cần)."""

    @app.before_request
    def _rate_limit():
        if not _security_enabled():
            return None
        if request.method == "OPTIONS":
            return None
        ip = client_ip()
        path = request.path.rstrip("/") or "/"
        limiter = _SENSITIVE.get(path) or _SENSITIVE.get(request.path)
        if limiter is not None:
            if not limiter.hit(f"{path}|{ip}"):
                log.warning(f"[security] rate-limit {path} từ {ip}")
                return _too_many()
        elif enable_global_limit:
            if not _global_limiter.hit(ip):
                log.warning(f"[security] rate-limit CHUNG từ {ip}")
                return _too_many()
        return None

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # CSP tối thiểu cho API JSON (không phục vụ HTML app từ đây)
        resp.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        # HSTS chỉ khi chạy HTTPS thật (production) — tránh khoá nhầm localhost HTTP
        if os.getenv("FORCE_HTTPS", "").strip().lower() in ("1", "true", "yes", "on"):
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        return resp


def _too_many():
    from flask import jsonify
    r = jsonify({"ok": False, "error": "Quá nhiều yêu cầu — vui lòng thử lại sau ít phút"})
    r.status_code = 429
    r.headers["Retry-After"] = "60"
    return r
