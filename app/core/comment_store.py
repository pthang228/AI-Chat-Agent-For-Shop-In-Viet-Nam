"""
Cài đặt TỰ ĐỘNG HOÁ BÌNH LUẬN theo từng Page (mục "Bài viết & bình luận").

Mỗi Page: {
  auto_hide_phone   : bool — tự ẨN bình luận lộ SĐT (chống đối thủ cướp khách)
  auto_reply        : bool — tự trả lời công khai dưới bình luận
  auto_reply_text   : str  — mẫu trả lời, hỗ trợ {name} = tên người bình luận
  private_reply     : bool — tự nhắn TIN RIÊNG cho người bình luận (comment → inbox)
  private_reply_text: str
}
Lưu JSON ở data/comment_settings.json (pattern giống các store kênh).
"""

import json
import logging
import threading

from app.core.config import Config
from app.core.store_util import atomic_write_json

log = logging.getLogger(__name__)

DEFAULTS = {
    "auto_hide_phone": False,
    "auto_reply": False,
    "auto_reply_text": "Cảm ơn {name} đã quan tâm! Shop đã nhắn tin riêng cho bạn, kiểm tra hộp thư nhé 💌",
    "private_reply": False,
    "private_reply_text": "Chào {name}, cảm ơn bạn đã bình luận! Bạn cần shop tư vấn gì cứ nhắn ở đây nhé 😊",
}


class CommentStore:
    def __init__(self, path=None):
        self._file = path or (Config.DATA_DIR / "comment_settings.json")
        self._lock = threading.RLock()
        self._pages: dict = {}   # page_id -> settings dict
        self._load()

    def _load(self):
        try:
            if self._file.exists():
                self._pages = json.loads(self._file.read_text(encoding="utf-8")) or {}
        except Exception as e:
            log.error(f"[CmtStore] load lỗi: {e}")
            self._pages = {}

    def save(self):
        with self._lock:
            atomic_write_json(self._file, self._pages, "CmtStore")

    def get(self, page_id) -> dict:
        """Cài đặt của Page (điền mặc định cho key thiếu — file cũ không vỡ)."""
        with self._lock:
            return {**DEFAULTS, **(self._pages.get(str(page_id)) or {})}

    def set(self, page_id, settings: dict) -> dict:
        """Cập nhật (chỉ nhận key hợp lệ, ép đúng kiểu). Trả bản sau khi lưu."""
        clean = {}
        for k, default in DEFAULTS.items():
            if k not in settings:
                continue
            v = settings[k]
            clean[k] = bool(v) if isinstance(default, bool) else str(v or "").strip()[:500]
        with self._lock:
            cur = self._pages.get(str(page_id)) or {}
            cur.update(clean)
            self._pages[str(page_id)] = cur
            self.save()
        return self.get(page_id)
