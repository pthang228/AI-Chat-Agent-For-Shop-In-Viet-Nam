"""
Kho shop Shopee đa khách (multi-tenant) — mỗi shop 1 Shopee Shop uỷ quyền cho
app của vendor trên Shopee Open Platform (dán shop_id + access_token trong web,
giống TikTok dán token).

Mỗi shop: { access_token, refresh_token, name, owner_buyer_id, owner_name,
owner_username }. Webhook nhận tin của shop nào → tra token shop đó để trả lời
+ báo đúng chủ. Lưu JSON ở data/shopee_shops.json.
"""

import json
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class ShopeeStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "shopee_shops.json")
        self._lock = threading.RLock()
        self._shops: dict = {}   # shop_id -> {access_token,refresh_token,name,owner_buyer_id,owner_name,owner_username}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._shops = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[SPStore] load lỗi: {e}")
            self._shops = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._shops, "SPStore")

    def upsert(self, shop_id, access_token=None, refresh_token=None, name=None,
               owner_username=None):
        sid = str(shop_id)
        with self._lock:
            s = self._shops.get(sid, {})
            if access_token is not None:  s["access_token"] = access_token
            if refresh_token is not None: s["refresh_token"] = refresh_token
            if name is not None:          s["name"] = name
            if owner_username and not s.get("owner_username"):
                s["owner_username"] = owner_username
            self._shops[sid] = s
            self.save()

    def get_owner_username(self, shop_id):
        with self._lock:
            s = self._shops.get(str(shop_id))
            return s.get("owner_username") if s else None

    def set_owner(self, shop_id, buyer_id, name=""):
        sid = str(shop_id)
        with self._lock:
            s = self._shops.get(sid)
            if s is None:
                log.warning(f"[SPStore] set_owner: shop_id={sid} không tồn tại trong store")
                return
            s["owner_buyer_id"] = str(buyer_id)
            s["owner_name"] = name
            self.save()

    def get_token(self, shop_id):
        with self._lock:
            s = self._shops.get(str(shop_id))
            return s.get("access_token") if s else None

    def get_owner_buyer_id(self, shop_id):
        with self._lock:
            s = self._shops.get(str(shop_id))
            return s.get("owner_buyer_id") if s else None

    def get(self, shop_id):
        with self._lock:
            return dict(self._shops.get(str(shop_id), {}))

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
                for sid, s in self._shops.items()
            ]

    def remove(self, shop_id):
        with self._lock:
            self._shops.pop(str(shop_id), None)
            self.save()
