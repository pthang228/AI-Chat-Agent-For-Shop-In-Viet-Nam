"""
Kho token Meta đa Page (multi-tenant) — lưu token của TỪNG Facebook Page mà
khách kết nối qua nút "Kết nối Facebook" trên UI.

Mỗi Page: { name, access_token, ig_id, ig_username }.
Webhook nhận tin của Page nào → tra token Page đó để trả lời (gửi đúng danh nghĩa).
Lưu JSON ở data/meta_pages.json. Đây là "danh bạ kênh" cho nhiều homestay.
"""

import json
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)


class MetaStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "meta_pages.json")
        self._lock = threading.RLock()   # RLock: mark_token_invalid() gọi save() lồng nhau
        self._pages: dict = {}   # page_id -> {name, access_token, ig_id, ig_username}
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._pages = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[MetaStore] load lỗi: {e}")
            self._pages = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._pages, "MetaStore")

    def upsert(self, page_id, name=None, access_token=None, ig_id=None, ig_username=None, owner_username=None):
        pid = str(page_id)
        with self._lock:   # mutate + save trong cùng lock (2 request connect song song)
            p = self._pages.get(pid, {})
            if name is not None:         p["name"] = name
            if access_token is not None:
                p["access_token"] = access_token
                p.pop("token_invalid", None)   # nối lại token mới → xoá cờ cần-kết-nối-lại
            if ig_id is not None:        p["ig_id"] = str(ig_id)
            if ig_username is not None:  p["ig_username"] = ig_username
            # owner_username = tài khoản chủ homestay sở hữu Page (để tính quota/gói)
            if owner_username and not p.get("owner_username"):
                p["owner_username"] = owner_username
            self._pages[pid] = p
            self.save()

    def get_token(self, page_id):
        p = self._pages.get(str(page_id))
        return p.get("access_token") if p else None

    def mark_token_invalid(self, page_id):
        """Token Page hết hạn/thu hồi (Meta code 190) → đánh dấu để UI báo chủ
        kết nối lại. Chỉ ghi khi đổi trạng thái (tránh save liên tục)."""
        with self._lock:
            p = self._pages.get(str(page_id))
            if p is not None and not p.get("token_invalid"):
                p["token_invalid"] = True
                self.save()

    def get_owner_username(self, page_id):
        p = self._pages.get(str(page_id))
        return p.get("owner_username") if p else None

    def page_for_ig(self, ig_id):
        """Map IG business account id → page_id (sự kiện Instagram dùng ig id ở entry)."""
        for pid, p in self._pages.items():
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
            for pid, p in self._pages.items()
        ]

    def remove(self, page_id):
        self._pages.pop(str(page_id), None)
        self.save()
