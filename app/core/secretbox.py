"""
Mã hoá AT-REST cho bí mật NHẠY CẢM lưu trong data/*.json:
  - session Telethon của acc gọi (StringSession = TOÀN QUYỀN tài khoản Telegram
    của khách — lộ là chiếm tài khoản),
  - (tuỳ chọn) token kênh.

Dùng Fernet (AES-128-CBC + HMAC-SHA256). Khoá lấy từ .env NOVACHAT_SECRET_KEY.

DEGRADE AN TOÀN: thiếu thư viện `cryptography` HOẶC chưa đặt khoá → NO-OP (trả
nguyên văn) để KHÔNG chặn chạy dev/test, kèm cảnh báo log. Chuỗi mã hoá có tiền tố
'enc:v1:' → đọc được CẢ dữ liệu thô cũ lẫn dữ liệu mã hoá (migrate dần: bản ghi cũ
đọc thô OK, lần ghi kế tiếp tự mã hoá).
"""

import base64
import hashlib
import logging
import os

log = logging.getLogger(__name__)

_PREFIX = "enc:v1:"


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception:
        return None
    raw = (os.getenv("NOVACHAT_SECRET_KEY") or "").strip()
    if not raw:
        return None
    # Derive khoá Fernet 32 byte từ mật khẩu người dùng đặt (khỏi bắt họ tạo key base64)
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())
    try:
        return Fernet(key)
    except Exception as e:
        log.warning(f"[secretbox] khoá không hợp lệ: {e}")
        return None


def enabled() -> bool:
    """Có mã hoá thật không (đủ lib + khoá)."""
    return _fernet() is not None


def encrypt(text):
    """Mã hoá 1 chuỗi bí mật. Không có khoá/lib → trả nguyên văn (degrade)."""
    if not text or not isinstance(text, str):
        return text
    if text.startswith(_PREFIX):
        return text   # đã mã hoá rồi
    f = _fernet()
    if f is None:
        return text
    try:
        return _PREFIX + f.encrypt(text.encode("utf-8")).decode("ascii")
    except Exception as e:
        log.warning(f"[secretbox] mã hoá lỗi: {e}")
        return text


def decrypt(text):
    """Giải mã. Dữ liệu THÔ cũ (không tiền tố) → trả nguyên. Có tiền tố mà thiếu
    khoá → trả '' (không lộ, buộc đăng nhập lại)."""
    if not isinstance(text, str) or not text.startswith(_PREFIX):
        return text
    f = _fernet()
    if f is None:
        log.warning("[secretbox] có dữ liệu MÃ HOÁ nhưng thiếu khoá/lib → không giải được")
        return ""
    try:
        return f.decrypt(text[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except Exception as e:
        log.warning(f"[secretbox] giải mã lỗi: {e}")
        return ""
