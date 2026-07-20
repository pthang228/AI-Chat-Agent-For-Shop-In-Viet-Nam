"""
Kho token Meta đa Page (multi-tenant) — lưu token của TỪNG Facebook Page mà
khách kết nối qua nút "Kết nối Facebook" trên UI.

Mỗi Page: { name, access_token, ig_id, ig_username }.
Webhook nhận tin của Page nào → tra token Page đó để trả lời (gửi đúng danh nghĩa).

LƯU TRỮ: SQLite bảng channel_accounts (channel='meta') qua SQLiteChannelStore
— thay data/meta_pages.json cũ (ghi cả file per-process → race liên tiến trình).
access_token được mã hoá at-rest ở tầng store. File JSON cũ migrate 1 lần rồi
đổi tên *.migrated (xem channel_store.py).
"""

import logging
import threading

from app.core.channel_store import SQLiteChannelStore
from app.core.config import Config

log = logging.getLogger(__name__)


class MetaStore:
    def __init__(self, path=None):
        # path giữ làm legacy_file để migrate JSON cũ 1 lần (tương thích chữ ký cũ)
        self._store = SQLiteChannelStore(
            "meta",
            legacy_file=path or (Config.DATA_DIR / "meta_pages.json"),
            secret_fields=("access_token",))
        self._lock = threading.RLock()   # tuần tự hoá đọc-sửa-ghi trong tiến trình

    def save(self):
        """No-op tương thích cũ — SQLite ghi ngay từng thao tác."""

    def clear(self):
        """Xoá sạch Page (tests dọn dữ liệu)."""
        with self._lock:
            self._store.clear()

    def upsert(self, page_id, name=None, access_token=None, ig_id=None, ig_username=None, owner_username=None):
        pid = str(page_id)
        with self._lock:   # mutate + ghi trong cùng lock (2 request connect song song)
            p = self._store.get(pid)
            if name is not None:         p["name"] = name
            if access_token is not None:
                p["access_token"] = access_token
                p.pop("token_invalid", None)   # nối lại token mới → xoá cờ cần-kết-nối-lại
            if ig_id is not None:        p["ig_id"] = str(ig_id)
            if ig_username is not None:  p["ig_username"] = ig_username
            # owner_username = tài khoản chủ homestay sở hữu Page (để tính quota/gói)
            if owner_username and not p.get("owner_username"):
                p["owner_username"] = owner_username
            self._store.upsert(pid, p)

    def get_token(self, page_id):
        p = self._store.get(str(page_id))
        return p.get("access_token") if p else None

    def mark_token_invalid(self, page_id):
        """Token Page hết hạn/thu hồi (Meta code 190) → đánh dấu để UI báo chủ
        kết nối lại. Chỉ ghi khi đổi trạng thái (tránh ghi DB liên tục)."""
        with self._lock:
            p = self._store.get(str(page_id))
            if p and not p.get("token_invalid"):
                p["token_invalid"] = True
                self._store.upsert(str(page_id), p)

    def get_owner_username(self, page_id):
        p = self._store.get(str(page_id))
        return p.get("owner_username") if p else None

    def page_for_ig(self, ig_id):
        """Map IG business account id → page_id (sự kiện Instagram dùng ig id ở entry)."""
        for pid, p in self._store.list():
            if str(p.get("ig_id")) == str(ig_id):
                return pid
        return None

    def list_pages(self):
        """Danh sách công khai (KHÔNG kèm token) để hiển thị lên UI."""
        return [
            {
                "page_id": pid,
                "name": p.get("name", ""),
                "ig_username": p.get("ig_username", ""),
                "has_ig": bool(p.get("ig_id")),
                "token_valid": not p.get("token_invalid"),
            }
            for pid, p in self._store.list()
        ]

    def remove(self, page_id):
        with self._lock:
            self._store.remove(str(page_id))
