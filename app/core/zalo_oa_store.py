"""
Kho Zalo OA đa khách (multi-tenant) — mỗi khách hàng 1 Official Account uỷ quyền
cho app của vendor trên developers.zalo.me (dán oa_id + access_token +
refresh_token trong web, giống Shopee/TikTok).

Mỗi OA: { access_token, refresh_token, name, owner_user_id, owner_name,
owner_username }. Webhook nhận tin của OA nào → tra token OA đó để trả lời
+ báo đúng chủ. Access token Zalo chỉ sống ~25h → channel tự refresh và gọi
upsert() lưu đè cặp token mới. Lưu JSON ở data/zalo_oa_accounts.json.
"""

import json
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class ZaloOAStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "zalo_oa_accounts.json")
        self._lock = threading.RLock()
        self._oas: dict = {}   # oa_id -> {access_token,refresh_token,name,owner_user_id,owner_name,owner_username}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._oas = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[OAStore] load lỗi: {e}")
            self._oas = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._oas, "OAStore")

    def upsert(self, oa_id, access_token=None, refresh_token=None, name=None,
               owner_username=None):
        oid = str(oa_id)
        with self._lock:
            s = self._oas.get(oid, {})
            if access_token is not None:  s["access_token"] = access_token
            if refresh_token is not None: s["refresh_token"] = refresh_token
            if name is not None:          s["name"] = name
            if owner_username and not s.get("owner_username"):
                s["owner_username"] = owner_username
            self._oas[oid] = s
            self.save()

    def get_owner_username(self, oa_id):
        with self._lock:
            s = self._oas.get(str(oa_id))
            return s.get("owner_username") if s else None

    def set_owner(self, oa_id, user_id, name=""):
        oid = str(oa_id)
        with self._lock:
            s = self._oas.get(oid)
            if s is None:
                log.warning(f"[OAStore] set_owner: oa_id={oid} không tồn tại trong store")
                return
            s["owner_user_id"] = str(user_id)
            s["owner_name"] = name
            self.save()

    def get_token(self, oa_id):
        with self._lock:
            s = self._oas.get(str(oa_id))
            return s.get("access_token") if s else None

    def get_refresh_token(self, oa_id):
        with self._lock:
            s = self._oas.get(str(oa_id))
            return s.get("refresh_token") if s else None

    def get_owner_user_id(self, oa_id):
        with self._lock:
            s = self._oas.get(str(oa_id))
            return s.get("owner_user_id") if s else None

    def get(self, oa_id):
        with self._lock:
            return dict(self._oas.get(str(oa_id), {}))

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
                for oid, s in self._oas.items()
            ]

    def remove(self, oa_id):
        with self._lock:
            self._oas.pop(str(oa_id), None)
            self.save()
