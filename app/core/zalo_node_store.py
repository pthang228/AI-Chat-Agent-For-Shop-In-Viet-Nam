"""
ZaloNodeStore — MULTI-ACCOUNT Zalo cá nhân: mỗi SHOP 1 tài khoản Zalo riêng
trên Node service. Store chỉ giữ MAPPING accId → chủ shop (owner_username);
phiên đăng nhập thật nằm ở Node (zalo-sessions/<accId>.json).

accId 'default' = tài khoản của CHỦ NỀN TẢNG (tương thích bản cũ — user_id
uid trần, session zalo-session.json).

File: data/zalo_accounts.json  {accId: {owner_username, name, created_at}}
"""

import json
import logging
import secrets
import threading
from datetime import datetime

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)

STORE_FILE = Config.DATA_DIR / "zalo_accounts.json"


class ZaloNodeStore:
    def __init__(self, path=None):
        self.path = path or STORE_FILE
        self._lock = threading.RLock()
        self._accounts: dict = {}
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                self._accounts = json.loads(self.path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[ZaloStore] load lỗi: {e}")

    def _save(self):
        try:
            atomic_write_json(self.path, self._accounts)
        except Exception as e:
            log.error(f"[ZaloStore] save lỗi: {e}")

    def create(self, owner_username: str, name: str = "") -> str:
        """Cấp acc mới cho shop (accId ngắn, an toàn cho path/URL)."""
        with self._lock:
            self._load()   # đọc TƯƠI — nhiều tiến trình/instance cùng file
            acc = "z" + secrets.token_hex(5)
            self._accounts[acc] = {
                "owner_username": (owner_username or "").lower(),
                "name": name or "",
                "created_at": datetime.now().isoformat(),
            }
            self._save()
            log.info(f"[ZaloStore] cấp acc {acc} cho {owner_username}")
            return acc

    def get_owner_username(self, acc: str):
        if not acc or acc == "default":
            return None      # acc default = chủ nền tảng → gate/tenant toàn cục
        with self._lock:
            self._load()     # đọc TƯƠI — instance khác có thể vừa cấp acc
            a = self._accounts.get(acc)
        return (a or {}).get("owner_username") or None

    def acc_for_owner(self, owner_username: str):
        """Acc của 1 shop (v1: mỗi shop 1 acc). Không có → None."""
        owner = (owner_username or "").lower()
        with self._lock:
            self._load()
            for acc, a in self._accounts.items():
                if a.get("owner_username") == owner:
                    return acc
        return None

    def ensure_for_owner(self, owner_username: str) -> str:
        """Acc của shop — chưa có thì cấp mới (gọi khi shop mở trang kết nối)."""
        with self._lock:
            return self.acc_for_owner(owner_username) or self.create(owner_username)

    def exists(self, acc: str) -> bool:
        return acc == "default" or acc in self._accounts

    def remove(self, acc: str):
        with self._lock:
            self._accounts.pop(acc, None)
            self._save()

    def list_accounts(self) -> list:
        with self._lock:
            return [{"acc": k, **v} for k, v in self._accounts.items()]
