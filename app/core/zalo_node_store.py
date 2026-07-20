"""
ZaloNodeStore — MULTI-ACCOUNT Zalo cá nhân: mỗi SHOP 1 tài khoản Zalo riêng
trên Node service. Store chỉ giữ MAPPING accId → chủ shop (owner_username);
phiên đăng nhập thật nằm ở Node (zalo-sessions/<accId>.json).

accId 'default' = tài khoản của CHỦ NỀN TẢNG (tương thích bản cũ — user_id
uid trần, session zalo-session.json).

LƯU TRỮ: SQLite bảng channel_accounts (channel='zalo_node') qua
SQLiteChannelStore — thay data/zalo_accounts.json cũ. Đây là store dính race
nặng nhất trước đây: bridge + tiến trình kênh cùng ghi zalo_accounts.json,
last-writer-wins nuốt acc vừa cấp. SQLite ghi từng dòng + đọc tươi → hết race.
File JSON cũ migrate 1 lần rồi đổi tên *.migrated (xem channel_store.py).
"""

import logging
import secrets
import threading
from datetime import datetime

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)

STORE_FILE = Config.DATA_DIR / "zalo_accounts.json"   # file legacy (chỉ để migrate)


class ZaloNodeStore:
    def __init__(self, path=None):
        # path giữ để tương thích chữ ký cũ — giờ chỉ làm legacy_file migrate
        self.path = path or STORE_FILE
        self._store = SQLiteChannelStore("zalo_node", legacy_file=self.path)
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def clear(self):
        """Xoá sạch acc (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def create(self, owner_username: str, name: str = "") -> str:
        """Cấp acc mới cho shop (accId ngắn, an toàn cho path/URL)."""
        with self._lock:
            acc = "z" + secrets.token_hex(5)
            self._store.upsert(acc, {
                "owner_username": (owner_username or "").lower(),
                "name": name or "",
                "created_at": datetime.now().isoformat(),
            })
            log.info(f"[ZaloStore] cấp acc {acc} cho {owner_username}")
            return acc

    def get_owner_username(self, acc: str):
        if not acc or acc == "default":
            return None      # acc default = chủ nền tảng → gate/tenant toàn cục
        # đọc TƯƠI từ SQLite — tiến trình khác vừa cấp acc là thấy ngay
        a = self._store.get(acc)
        return (a or {}).get("owner_username") or None

    def acc_for_owner(self, owner_username: str):
        """Acc của 1 shop (v1: mỗi shop 1 acc). Không có → None."""
        owner = (owner_username or "").lower()
        with self._lock:
            for acc, a in self._store.list():
                if a.get("owner_username") == owner:
                    return acc
        return None

    def ensure_for_owner(self, owner_username: str) -> str:
        """Acc của shop — chưa có thì cấp mới (gọi khi shop mở trang kết nối)."""
        with self._lock:
            return self.acc_for_owner(owner_username) or self.create(owner_username)

    def exists(self, acc: str) -> bool:
        return acc == "default" or self._store.exists(acc)

    def remove(self, acc: str):
        with self._lock:
            self._store.remove(acc)

    def list_accounts(self) -> list:
        with self._lock:
            return [{"acc": k, **v} for k, v in self._store.list()]
