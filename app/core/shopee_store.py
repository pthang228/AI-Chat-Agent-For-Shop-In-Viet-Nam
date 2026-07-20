"""
Kho shop Shopee đa khách (multi-tenant) — mỗi shop 1 Shopee Shop uỷ quyền cho
app của vendor trên Shopee Open Platform (dán shop_id + access_token trong web,
giống TikTok dán token).

Mỗi shop: { access_token, refresh_token, name, owner_buyer_id, owner_name,
owner_username }. Webhook nhận tin của shop nào → tra token shop đó để trả lời
+ báo đúng chủ.

LƯU TRỮ: SQLite bảng channel_accounts (channel='shopee') qua SQLiteChannelStore
— thay data/shopee_shops.json cũ (ghi cả file per-process → race liên tiến
trình). Cặp token được mã hoá at-rest ở tầng store. File JSON cũ migrate 1 lần
rồi đổi tên *.migrated (xem channel_store.py).
"""

import logging
import threading

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class ShopeeStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "shopee",
            legacy_file=path or (Config.DATA_DIR / "shopee_shops.json"),
            secret_fields=("access_token", "refresh_token"))
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác."""

    def clear(self):
        """Xoá sạch shop (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def upsert(self, shop_id, access_token=None, refresh_token=None, name=None,
               owner_username=None):
        sid = str(shop_id)
        with self._lock:
            s = self._store.get(sid)
            if access_token is not None:  s["access_token"] = access_token
            if refresh_token is not None: s["refresh_token"] = refresh_token
            if name is not None:          s["name"] = name
            if owner_username and not s.get("owner_username"):
                s["owner_username"] = owner_username
            self._store.upsert(sid, s)

    def get_owner_username(self, shop_id):
        with self._lock:
            s = self._store.get(str(shop_id))
            return s.get("owner_username") if s else None

    def set_owner(self, shop_id, buyer_id, name=""):
        sid = str(shop_id)
        with self._lock:
            s = self._store.get(sid)
            if not s:
                log.warning(f"[SPStore] set_owner: shop_id={sid} không tồn tại trong store")
                return
            s["owner_buyer_id"] = str(buyer_id)
            s["owner_name"] = name
            self._store.upsert(sid, s)

    def get_token(self, shop_id):
        with self._lock:
            s = self._store.get(str(shop_id))
            return s.get("access_token") if s else None

    def get_owner_buyer_id(self, shop_id):
        with self._lock:
            s = self._store.get(str(shop_id))
            return s.get("owner_buyer_id") if s else None

    def get(self, shop_id):
        with self._lock:
            return self._store.get(str(shop_id))

    def list_shops(self):
        """Danh sách công khai (KHÔNG lộ token) cho UI."""
        with self._lock:
            return [
                {
                    "shop_id": sid,
                    "name": s.get("name", ""),
                    "owner_registered": bool(s.get("owner_buyer_id")),
                    "owner_name": s.get("owner_name", ""),
                }
                for sid, s in self._store.list()
            ]

    def remove(self, shop_id):
        with self._lock:
            self._store.remove(str(shop_id))
