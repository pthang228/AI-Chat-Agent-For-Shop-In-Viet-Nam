"""
Lưu "chủ nhà" của bot Telegram — tự bắt khi chủ nhắn /start <mã> cho bot
(KHÔNG cần tìm chat_id thủ công). chat_id của chat 1-1 chính là Telegram user id
→ dùng luôn cho cả notify (bot nhắn) lẫn gọi thoại (Telethon).

Single-tenant: 1 chủ cho 1 bot (đủ 1 homestay). Đa khách (chủ theo từng bot) sau.
Lưu JSON ở data/telegram_owner.json.
"""

import json
import logging

from app.core.config import Config

log = logging.getLogger(__name__)

_FILE = Config.DATA_DIR / "telegram_owner.json"
_CALLER_FILE = Config.DATA_DIR / "telegram_caller.json"


def get_owner() -> dict:
    """{chat_id, name, registered_at} hoặc {} nếu chưa đăng ký."""
    try:
        if _FILE.exists():
            return json.loads(_FILE.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.error(f"[TG owner] load lỗi: {e}")
    return {}


def get_owner_chat_id():
    """chat_id chủ đã đăng ký, fallback .env TELEGRAM_OWNER_CHAT_ID."""
    cid = get_owner().get("chat_id")
    return str(cid) if cid else (Config.TELEGRAM_OWNER_CHAT_ID or None)


def set_owner(chat_id, name: str = "") -> None:
    import time
    data = {"chat_id": str(chat_id), "name": name, "registered_at": time.time()}
    try:
        _FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"[TG owner] Đã đăng ký chủ: {chat_id} ({name})")
    except Exception as e:
        log.error(f"[TG owner] save lỗi: {e}")
def get_caller() -> dict:
    try:
        if _CALLER_FILE.exists():
            return json.loads(_CALLER_FILE.read_text(encoding="utf-8")) or {}
    except Exception as e:
        log.error(f"[TG caller] load loi: {e}")
    return {}


def set_caller(chat_id, name: str = "") -> None:
    import time
    data = {"chat_id": str(chat_id), "name": name, "registered_at": time.time()}
    try:
        _CALLER_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"[TG caller] Da chon nguoi goi: {chat_id} ({name})")
    except Exception as e:
        log.error(f"[TG caller] save loi: {e}")
