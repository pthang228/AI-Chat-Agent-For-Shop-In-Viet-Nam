"""
Kho site Webchat đa khách (multi-tenant) — mỗi khách hàng (chủ shop) tạo 1+ site,
mỗi site 1 mã nhúng để dán vào WEBSITE của họ:

  <script src="<PUBLIC_BASE_URL>/widget.js" data-site="<site_id>"></script>

Mỗi site: { name, owner_username (tính quota/gói), owner_user_id (visitor được
đặt làm chủ để nhận notify — như Shopee/Zalo OA), owner_name, created_at }.
site_id sinh ngẫu nhiên "wc" + hex — nằm CÔNG KHAI trong HTML web khách nên chỉ
là ĐỊNH DANH, không phải bí mật (quota tính vào tài khoản chủ nên có phanh sẵn).
Lưu JSON ở data/webchat_sites.json.
"""

import json
import logging
import secrets
import threading
from datetime import datetime

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class WebChatStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "webchat_sites.json")
        self._lock = threading.RLock()
        self._sites: dict = {}   # site_id -> {name,owner_username,owner_user_id,owner_name,created_at}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._sites = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[WebChatStore] load lỗi: {e}")
            self._sites = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._sites, "WebChatStore")

    def create(self, name: str, owner_username: str = None) -> str:
        """Tạo site mới → trả site_id (wc + 10 hex)."""
        with self._lock:
            while True:
                sid = "wc" + secrets.token_hex(5)
                if sid not in self._sites:
                    break
            self._sites[sid] = {
                "name": (name or "").strip()[:80] or "Website của tôi",
                "owner_username": owner_username or "",
                "owner_user_id": "",
                "owner_name": "",
                "created_at": datetime.now().isoformat(),
            }
            self.save()
            return sid

    def exists(self, site_id) -> bool:
        with self._lock:
            return str(site_id) in self._sites

    def get(self, site_id) -> dict:
        with self._lock:
            return dict(self._sites.get(str(site_id), {}))

    def get_owner_username(self, site_id):
        with self._lock:
            s = self._sites.get(str(site_id))
            return s.get("owner_username") or None if s else None

    def get_owner_user_id(self, site_id):
        with self._lock:
            s = self._sites.get(str(site_id))
            return s.get("owner_user_id") or None if s else None

    def set_owner(self, site_id, user_id, name=""):
        sid = str(site_id)
        with self._lock:
            s = self._sites.get(sid)
            if s is None:
                log.warning(f"[WebChatStore] set_owner: site {sid} không tồn tại")
                return
            s["owner_user_id"] = str(user_id)
            s["owner_name"] = name
            self.save()

    def list_sites(self):
        """Danh sách cho UI (site_id công khai sẵn nên trả luôn)."""
        with self._lock:
            return [
                {
                    "site_id": sid,
                    "name": s.get("name", ""),
                    "owner_registered": bool(s.get("owner_user_id")),
                    "owner_name": s.get("owner_name", ""),
                    "created_at": s.get("created_at", ""),
                }
                for sid, s in self._sites.items()
            ]

    def remove(self, site_id):
        with self._lock:
            self._sites.pop(str(site_id), None)
            self.save()
