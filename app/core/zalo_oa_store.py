"""
Kho Zalo OA đa khách (multi-tenant) — mỗi khách hàng 1 Official Account uỷ quyền
cho app của vendor trên developers.zalo.me (dán oa_id + access_token +
refresh_token trong web, giống Shopee/TikTok).

Mỗi OA: { access_token, refresh_token, name, owner_user_id, owner_name,
owner_username }. Webhook nhận tin của OA nào → tra token OA đó để trả lời
+ báo đúng chủ. Access token Zalo chỉ sống ~25h → channel tự refresh và gọi
upsert() lưu đè cặp token mới.

LƯU TRỮ: SQLite bảng channel_accounts (channel='zalo_oa') qua SQLiteChannelStore
— thay data/zalo_oa_accounts.json cũ (ghi cả file per-process → race liên tiến
trình). Cặp token được mã hoá at-rest ở tầng store. File JSON cũ migrate 1 lần
rồi đổi tên *.migrated (xem channel_store.py).
"""

import logging
import threading

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class ZaloOAStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "zalo_oa",
            legacy_file=path or (Config.DATA_DIR / "zalo_oa_accounts.json"),
            secret_fields=("access_token", "refresh_token"))
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác."""

    def clear(self):
        """Xoá sạch OA (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def upsert(self, oa_id, access_token=None, refresh_token=None, name=None,
               owner_username=None):
        oid = str(oa_id)
        with self._lock:
            s = self._store.get(oid)
            if access_token is not None:  s["access_token"] = access_token
            if refresh_token is not None: s["refresh_token"] = refresh_token
            if name is not None:          s["name"] = name
            if owner_username and not s.get("owner_username"):
                s["owner_username"] = owner_username
            self._store.upsert(oid, s)

    def get_owner_username(self, oa_id):
        with self._lock:
            s = self._store.get(str(oa_id))
            return s.get("owner_username") if s else None

    def set_owner(self, oa_id, user_id, name=""):
        oid = str(oa_id)
        with self._lock:
            s = self._store.get(oid)
            if not s:
                log.warning(f"[OAStore] set_owner: oa_id={oid} không tồn tại trong store")
                return
            s["owner_user_id"] = str(user_id)
            s["owner_name"] = name
            self._store.upsert(oid, s)

    def get_token(self, oa_id):
        with self._lock:
            s = self._store.get(str(oa_id))
            return s.get("access_token") if s else None

    def get_refresh_token(self, oa_id):
        with self._lock:
            s = self._store.get(str(oa_id))
            return s.get("refresh_token") if s else None

    def get_owner_user_id(self, oa_id):
        with self._lock:
            s = self._store.get(str(oa_id))
            return s.get("owner_user_id") if s else None

    def get(self, oa_id):
        with self._lock:
            return self._store.get(str(oa_id))

    def list_oas(self):
        """Danh sách công khai (KHÔNG lộ token) cho UI."""
        with self._lock:
            return [
                {
                    "oa_id": oid,
                    "name": s.get("name", ""),
                    "has_refresh": bool(s.get("refresh_token")),
                    "owner_registered": bool(s.get("owner_user_id")),
                    "owner_name": s.get("owner_name", ""),
                }
                for oid, s in self._store.list()
            ]

    def remove(self, oa_id):
        with self._lock:
            self._store.remove(str(oa_id))
