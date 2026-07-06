"""
Kho bot Telegram đa khách (multi-tenant) — mỗi homestay 1 bot token (dán trong web).

Mỗi bot: { token, username, name, owner_chat_id, owner_name }.
Webhook/poll nhận tin của bot nào → tra token bot đó để trả lời + báo đúng chủ.
Lưu JSON ở data/telegram_bots.json. "Danh bạ bot" cho nhiều homestay.
"""

import json
import time
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class TelegramStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "telegram_bots.json")
        self._lock = threading.RLock()  # RLock: cho phép lock lồng nhau (mutate rồi gọi save)
        self._bots: dict = {}   # bot_id -> {token,username,name,owner_chat_id,owner_name,caller_session,caller_id,caller_name,caller_username}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._bots = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[TGStore] load lỗi: {e}")
            self._bots = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._bots, "TGStore")

    def upsert(self, bot_id, token=None, username=None, name=None, owner_username=None):
        bid = str(bot_id)
        with self._lock:
            b = self._bots.get(bid, {})
            if token is not None:    b["token"] = token
            if username is not None: b["username"] = username
            if name is not None:     b["name"] = name
            # owner_username = tài khoản CHỦ HOMESTAY sở hữu bot này (để tính quota/gói).
            # Chỉ set khi chưa có (giữ chủ đầu tiên đã kết nối).
            if owner_username and not b.get("owner_username"):
                b["owner_username"] = owner_username
            self._bots[bid] = b
            self.save()

    def get_owner_username(self, bot_id):
        with self._lock:
            b = self._bots.get(str(bot_id))
            return b.get("owner_username") if b else None

    def set_owner(self, bot_id, chat_id, name=""):
        bid = str(bot_id)
        with self._lock:
            b = self._bots.get(bid)
            if b is None:
                log.warning(f"[TGStore] set_owner: bot_id={bid} không tồn tại trong store")
                return
            b["owner_chat_id"] = str(chat_id)
            b["owner_name"] = name
            self.save()

    def set_caller_session(self, bot_id, session, profile=None):
        """Lưu phiên Telethon (StringSession) của acc gọi cho bot này + hồ sơ acc."""
        bid = str(bot_id)
        with self._lock:
            b = self._bots.get(bid)
            if b is None:
                log.warning(f"[TGStore] set_caller_session: bot_id={bid} không tồn tại trong store")
                return
            b["caller_session"] = session
            if profile:
                fn = profile.get("first_name", "") or ""
                ln = profile.get("last_name", "") or ""
                b["caller_id"] = str(profile.get("id", "") or "")
                b["caller_name"] = (fn + (" " + ln if ln else "")).strip()
                b["caller_username"] = profile.get("username", "") or ""
            self.save()

    def get_caller_session(self, bot_id):
        with self._lock:
            b = self._bots.get(str(bot_id))
            return b.get("caller_session") if b else None

    def clear_caller_session(self, bot_id):
        with self._lock:
            b = self._bots.get(str(bot_id))
            if b:
                for k in ("caller_session", "caller_id", "caller_name", "caller_username"):
                    b.pop(k, None)
                self.save()

    def get_token(self, bot_id):
        with self._lock:
            b = self._bots.get(str(bot_id))
            return b.get("token") if b else None

    def get_owner_chat_id(self, bot_id):
        with self._lock:
            b = self._bots.get(str(bot_id))
            return b.get("owner_chat_id") if b else None

    def get(self, bot_id):
        with self._lock:
            return dict(self._bots.get(str(bot_id), {}))

    def all_bots(self):
        """[(bot_id, token)] để khởi động poller cho từng bot."""
        with self._lock:
            return [(bid, b.get("token")) for bid, b in self._bots.items() if b.get("token")]

    def list_bots(self):
        """Danh sách công khai (KHÔNG lộ token) cho UI."""
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
                for bid, b in self._bots.items()
            ]

    def remove(self, bot_id):
        with self._lock:
            self._bots.pop(str(bot_id), None)
            self.save()
