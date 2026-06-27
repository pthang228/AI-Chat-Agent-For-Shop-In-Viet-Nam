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

log = logging.getLogger(__name__)


class TelegramStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "telegram_bots.json")
        self._lock = threading.Lock()
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
            try:
                self._file.write_text(
                    json.dumps(self._bots, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                log.error(f"[TGStore] save lỗi: {e}")

    def upsert(self, bot_id, token=None, username=None, name=None):
        bid = str(bot_id)
        b = self._bots.get(bid, {})
        if token is not None:    b["token"] = token
        if username is not None: b["username"] = username
        if name is not None:     b["name"] = name
        self._bots[bid] = b
        self.save()

    def set_owner(self, bot_id, chat_id, name=""):
        bid = str(bot_id)
        b = self._bots.get(bid)
        if b is None:
            return
        b["owner_chat_id"] = str(chat_id)
        b["owner_name"] = name
        self.save()

    def set_caller_session(self, bot_id, session, profile=None):
        """Lưu phiên Telethon (StringSession) của acc gọi cho bot này + hồ sơ acc."""
        bid = str(bot_id)
        b = self._bots.get(bid)
        if b is None:
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
        b = self._bots.get(str(bot_id))
        return b.get("caller_session") if b else None

    def clear_caller_session(self, bot_id):
        b = self._bots.get(str(bot_id))
        if b:
            for k in ("caller_session", "caller_id", "caller_name", "caller_username"):
                b.pop(k, None)
            self.save()

    def get_token(self, bot_id):
        b = self._bots.get(str(bot_id))
        return b.get("token") if b else None

    def get_owner_chat_id(self, bot_id):
        b = self._bots.get(str(bot_id))
        return b.get("owner_chat_id") if b else None

    def get(self, bot_id):
        return self._bots.get(str(bot_id), {})

    def all_bots(self):
        """[(bot_id, token)] để khởi động poller cho từng bot."""
        return [(bid, b.get("token")) for bid, b in self._bots.items() if b.get("token")]

    def list_bots(self):
        """Danh sách công khai (KHÔNG lộ token) cho UI."""
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
        self._bots.pop(str(bot_id), None)
        self.save()
