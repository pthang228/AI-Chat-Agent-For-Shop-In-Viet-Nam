"""
Kho tài khoản TikTok đa khách (multi-tenant) — mỗi homestay 1 TikTok Business
Account (dán access token trong web, giống Telegram dán token bot).

Mỗi account: { access_token, name, username, owner_open_id, owner_name }.
Webhook nhận tin của account nào → tra token account đó để trả lời + báo đúng chủ.
Lưu JSON ở data/tiktok_accounts.json.
"""

import json
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class TikTokStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "tiktok_accounts.json")
        self._lock = threading.RLock()
        self._accounts: dict = {}   # business_id -> {access_token,name,username,owner_open_id,owner_name}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._accounts = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[TTStore] load lỗi: {e}")
            self._accounts = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._accounts, "TTStore")

    def upsert(self, business_id, access_token=None, name=None, username=None, owner_username=None):
        bid = str(business_id)
        with self._lock:
            a = self._accounts.get(bid, {})
            if access_token is not None: a["access_token"] = access_token
            if name is not None:         a["name"] = name
            if username is not None:     a["username"] = username
            if owner_username and not a.get("owner_username"):
                a["owner_username"] = owner_username
            self._accounts[bid] = a
            self.save()

    def get_owner_username(self, business_id):
        with self._lock:
            a = self._accounts.get(str(business_id))
            return a.get("owner_username") if a else None

    def set_owner(self, business_id, open_id, name=""):
        bid = str(business_id)
        with self._lock:
            a = self._accounts.get(bid)
            if a is None:
                log.warning(f"[TTStore] set_owner: business_id={bid} không tồn tại trong store")
                return
            a["owner_open_id"] = str(open_id)
            a["owner_name"] = name
            self.save()

    def get_token(self, business_id):
        with self._lock:
            a = self._accounts.get(str(business_id))
            return a.get("access_token") if a else None

    def get_owner_open_id(self, business_id):
        with self._lock:
            a = self._accounts.get(str(business_id))
            return a.get("owner_open_id") if a else None

    def get(self, business_id):
        with self._lock:
            return dict(self._accounts.get(str(business_id), {}))

    def list_accounts(self):
        """Danh sách công khai (KHÔNG lộ token) cho UI."""
        with self._lock:
            return [
                {
                    "business_id": bid,
                    "name": a.get("name", ""),
                    "username": a.get("username", ""),
                    "owner_registered": bool(a.get("owner_open_id")),
                    "owner_name": a.get("owner_name", ""),
                }
                for bid, a in self._accounts.items()
            ]

    def remove(self, business_id):
        with self._lock:
            self._accounts.pop(str(business_id), None)
            self.save()
