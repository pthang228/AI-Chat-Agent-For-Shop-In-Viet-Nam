"""
Kho tài khoản TikTok đa khách (multi-tenant) — mỗi homestay 1 TikTok Business
Account (dán access token trong web, giống Telegram dán token bot).

Mỗi account: { access_token, name, username, owner_open_id, owner_name }.
Webhook nhận tin của account nào → tra token account đó để trả lời + báo đúng chủ.

LƯU TRỮ: SQLite bảng channel_accounts (channel='tiktok') qua SQLiteChannelStore
— thay data/tiktok_accounts.json cũ (ghi cả file per-process → race liên tiến
trình). access_token được mã hoá at-rest ở tầng store. File JSON cũ migrate
1 lần rồi đổi tên *.migrated (xem channel_store.py).
"""

import logging
import threading

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class TikTokStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "tiktok",
            legacy_file=path or (Config.DATA_DIR / "tiktok_accounts.json"),
            secret_fields=("access_token",))
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác."""

    def clear(self):
        """Xoá sạch account (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def upsert(self, business_id, access_token=None, name=None, username=None, owner_username=None):
        bid = str(business_id)
        with self._lock:
            a = self._store.get(bid)
            if access_token is not None: a["access_token"] = access_token
            if name is not None:         a["name"] = name
            if username is not None:     a["username"] = username
            if owner_username and not a.get("owner_username"):
                a["owner_username"] = owner_username
            self._store.upsert(bid, a)

    def get_owner_username(self, business_id):
        with self._lock:
            a = self._store.get(str(business_id))
            return a.get("owner_username") if a else None

    def set_owner(self, business_id, open_id, name=""):
        bid = str(business_id)
        with self._lock:
            a = self._store.get(bid)
            if not a:
                log.warning(f"[TTStore] set_owner: business_id={bid} không tồn tại trong store")
                return
            a["owner_open_id"] = str(open_id)
            a["owner_name"] = name
            self._store.upsert(bid, a)

    def get_token(self, business_id):
        with self._lock:
            a = self._store.get(str(business_id))
            return a.get("access_token") if a else None

    def get_owner_open_id(self, business_id):
        with self._lock:
            a = self._store.get(str(business_id))
            return a.get("owner_open_id") if a else None

    def get(self, business_id):
        with self._lock:
            return self._store.get(str(business_id))

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
                for bid, a in self._store.list()
            ]

    def remove(self, business_id):
        with self._lock:
            self._store.remove(str(business_id))
