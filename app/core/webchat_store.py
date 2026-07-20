"""
Kho site Webchat đa khách (multi-tenant) — mỗi khách hàng (chủ shop) tạo 1+ site,
mỗi site 1 mã nhúng để dán vào WEBSITE của họ:

  <script src="<PUBLIC_BASE_URL>/widget.js" data-site="<site_id>"></script>

Mỗi site: { name, owner_username (tính quota/gói), owner_user_id (visitor được
đặt làm chủ để nhận notify — như Shopee/Zalo OA), owner_name, created_at }.
site_id sinh ngẫu nhiên "wc" + hex — nằm CÔNG KHAI trong HTML web khách nên chỉ
là ĐỊNH DANH, không phải bí mật (quota tính vào tài khoản chủ nên có phanh sẵn).

LƯU TRỮ: SQLite bảng channel_accounts (channel='webchat') qua SQLiteChannelStore
— thay data/webchat_sites.json cũ (ghi cả file per-process → race liên tiến
trình). Không có field bí mật. File JSON cũ migrate 1 lần rồi đổi tên *.migrated
(xem channel_store.py).
"""

import logging
import secrets
import threading
from datetime import datetime

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class WebChatStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "webchat",
            legacy_file=path or (Config.DATA_DIR / "webchat_sites.json"))
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác."""

    def clear(self):
        """Xoá sạch site (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def create(self, name: str, owner_username: str = None) -> str:
        """Tạo site mới → trả site_id (wc + 10 hex)."""
        with self._lock:
            while True:
                sid = "wc" + secrets.token_hex(5)
                if not self._store.exists(sid):
                    break
            self._store.upsert(sid, {
                "name": (name or "").strip()[:80] or "Website của tôi",
                "owner_username": owner_username or "",
                "owner_user_id": "",
                "owner_name": "",
                "created_at": datetime.now().isoformat(),
            })
            return sid

    def exists(self, site_id) -> bool:
        return self._store.exists(str(site_id))

    def get(self, site_id) -> dict:
        with self._lock:
            return self._store.get(str(site_id))

    def get_owner_username(self, site_id):
        with self._lock:
            s = self._store.get(str(site_id))
            return s.get("owner_username") or None if s else None

    def get_owner_user_id(self, site_id):
        with self._lock:
            s = self._store.get(str(site_id))
            return s.get("owner_user_id") or None if s else None

    def set_owner(self, site_id, user_id, name=""):
        sid = str(site_id)
        with self._lock:
            s = self._store.get(sid)
            if not s:
                log.warning(f"[WebChatStore] set_owner: site {sid} không tồn tại")
                return
            s["owner_user_id"] = str(user_id)
            s["owner_name"] = name
            self._store.upsert(sid, s)

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
                for sid, s in self._store.list()
            ]

    def remove(self, site_id):
        with self._lock:
            self._store.remove(str(site_id))
