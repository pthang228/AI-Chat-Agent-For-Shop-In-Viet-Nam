"""
Kho bot Telegram đa khách (multi-tenant) — mỗi homestay 1 bot token (dán trong web).

Mỗi bot: { token, username, name, owner_chat_id, owner_name }.
Webhook/poll nhận tin của bot nào → tra token bot đó để trả lời + báo đúng chủ.

LƯU TRỮ: SQLite bảng channel_accounts (channel='telegram') qua SQLiteChannelStore
— thay data/telegram_bots.json cũ (ghi cả file per-process → race liên tiến trình).
token + caller_session (StringSession Telethon = TOÀN QUYỀN tài khoản Telegram
khách) được mã hoá at-rest ở tầng store — code ở đây KHÔNG gọi secretbox trực
tiếp nữa (1 tầng mã hoá duy nhất, khỏi mã hoá 2 lần).
File JSON cũ được migrate 1 lần rồi đổi tên *.migrated (xem channel_store.py).
"""

import logging
import threading

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class TelegramStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "telegram",
            legacy_file=path or (Config.DATA_DIR / "telegram_bots.json"),
            secret_fields=("token", "caller_session"))
        # RLock: tuần tự hoá chu trình đọc-sửa-ghi trong tiến trình (liên tiến
        # trình đã có WAL + ghi từng dòng của SQLite lo)
        self._lock = threading.RLock()

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác, không cần save."""

    def clear(self):
        """Xoá sạch bot (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def upsert(self, bot_id, token=None, username=None, name=None, owner_username=None):
        bid = str(bot_id)
        with self._lock:
            b = self._store.get(bid)
            if token is not None:    b["token"] = token
            if username is not None: b["username"] = username
            if name is not None:     b["name"] = name
            # owner_username = tài khoản CHỦ HOMESTAY sở hữu bot này (để tính quota/gói).
            # Chỉ set khi chưa có (giữ chủ đầu tiên đã kết nối).
            if owner_username and not b.get("owner_username"):
                b["owner_username"] = owner_username
            self._store.upsert(bid, b)

    def get_owner_username(self, bot_id):
        with self._lock:
            b = self._store.get(str(bot_id))
            return b.get("owner_username") if b else None

    def owns(self, bot_id, owner_username) -> bool:
        """Bot này có thuộc CHỦ owner_username không (kiểm quyền cross-tenant).
        Bot chưa gắn chủ (kết nối trước khi có owner) → không ai 'sở hữu' → chỉ
        quản trị nền tảng đụng được (caller tự xử admin riêng)."""
        if not owner_username:
            return False
        with self._lock:
            b = self._store.get(str(bot_id))
            return bool(b) and b.get("owner_username") == owner_username

    def set_owner(self, bot_id, chat_id, name=""):
        bid = str(bot_id)
        with self._lock:
            b = self._store.get(bid)
            if not b:
                log.warning(f"[TGStore] set_owner: bot_id={bid} không tồn tại trong store")
                return
            b["owner_chat_id"] = str(chat_id)
            b["owner_name"] = name
            self._store.upsert(bid, b)

    def set_caller_session(self, bot_id, session, profile=None):
        """Lưu phiên Telethon (StringSession) của acc gọi cho bot này + hồ sơ acc.
        Mã hoá at-rest do SQLiteChannelStore lo (secret_fields) — không encrypt
        ở đây nữa để chỉ có ĐÚNG 1 tầng mã hoá."""
        bid = str(bot_id)
        with self._lock:
            b = self._store.get(bid)
            if not b:
                log.warning(f"[TGStore] set_caller_session: bot_id={bid} không tồn tại trong store")
                return
            b["caller_session"] = session
            if profile:
                fn = profile.get("first_name", "") or ""
                ln = profile.get("last_name", "") or ""
                b["caller_id"] = str(profile.get("id", "") or "")
                b["caller_name"] = (fn + (" " + ln if ln else "")).strip()
                b["caller_username"] = profile.get("username", "") or ""
            self._store.upsert(bid, b)

    def get_caller_session(self, bot_id):
        with self._lock:
            b = self._store.get(str(bot_id))
            return b.get("caller_session") if b else None   # store đã giải mã sẵn

    def clear_caller_session(self, bot_id):
        bid = str(bot_id)
        with self._lock:
            b = self._store.get(bid)
            if b:
                for k in ("caller_session", "caller_id", "caller_name", "caller_username"):
                    b.pop(k, None)
                self._store.upsert(bid, b)

    def get_token(self, bot_id):
        with self._lock:
            b = self._store.get(str(bot_id))
            return b.get("token") if b else None

    def get_owner_chat_id(self, bot_id):
        with self._lock:
            b = self._store.get(str(bot_id))
            return b.get("owner_chat_id") if b else None

    def get(self, bot_id):
        with self._lock:
            return self._store.get(str(bot_id))

    def all_bots(self):
        """[(bot_id, token)] để khởi động poller cho từng bot."""
        with self._lock:
            return [(bid, b.get("token"))
                    for bid, b in self._store.list() if b.get("token")]

    def list_bots(self, owner=None):
        """Danh sách công khai (KHÔNG lộ token) cho UI.
        owner=None → tất cả (chỉ dùng cho quản trị nền tảng). owner='<username>' →
        CHỈ bot của shop đó (multi-tenant: shop không thấy bot shop khác)."""
        with self._lock:
            return [
                {
                    "bot_id": bid,
                    "username": b.get("username", ""),
                    "name": b.get("name", ""),
                    "owner_registered": bool(b.get("owner_chat_id")),
                    "owner_name": b.get("owner_name", ""),
                    "caller_logged_in": bool(b.get("caller_session")),
                    "caller_name": b.get("caller_name", ""),
                    "caller_username": b.get("caller_username", ""),
                }
                for bid, b in self._store.list()
                if owner is None or b.get("owner_username") == owner
            ]

    def remove(self, bot_id):
        with self._lock:
            self._store.remove(str(bot_id))
