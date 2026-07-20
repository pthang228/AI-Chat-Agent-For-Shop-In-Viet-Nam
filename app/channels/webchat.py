"""
Kênh Webchat — bong bóng chat nhúng vào WEBSITE của khách hàng (như Crisp/Tawk).

KHÁC mọi kênh khác: KHÔNG có API bên thứ ba. Mình kiểm soát cả 2 đầu:
  - Chiều đi (bot/chủ → khách web): brain gọi send_text/send_image_url →
    channel đẩy tin vào OUTBOX trong RAM theo từng visitor → widget trên web
    khách poll GET /webchat/pub/poll lấy về hiển thị.
  - Chiều về (khách web → bot): widget POST /webchat/pub/send →
    app/web_api/webchat_api.py → brain.

Quy ước user_id (đa khách / multi-tenant): "web:<site_id>:<visitor_id>"
  - site_id   : site chủ shop tạo trong web (WebChatStore)
  - visitor_id: định danh khách, widget sinh ngẫu nhiên + lưu localStorage.

OUTBOX chỉ là kênh đẩy TRỰC TIẾP (in-memory, mất khi restart — chấp nhận):
lịch sử thật nằm trong ConversationManager, widget mở lại tự GET /history.

Ảnh phòng/bảng giá: đẩy đường dẫn TƯƠNG ĐỐI "/media/..." — widget tự prefix
origin của CHÍNH server nó được tải về. CHỦ ĐÍCH không dùng PUBLIC_BASE_URL:
tunnel chết (đã từng dính với Zalo media) thì URL tuyệt đối gãy, còn tương đối
sống trong mọi trường hợp vì widget và media cùng 1 server.
"""

import logging
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote

from app.core.config import Config
from app.core.channel import Channel, LEGACY_ROOM_SETS
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5
MAX_LEN = 4000            # cắt tin text quá dài cho widget dễ hiển thị
OUTBOX_MAX = 50           # giữ tối đa N tin chờ / visitor (widget poll 1-3s là lấy)


class WebChatChannel(Channel):

    def __init__(self, store=None, conv_manager=None):
        self.store = store                  # WebChatStore (đa khách)
        self.conv_manager = conv_manager
        self.brain = None
        self._sent: list = []               # ghi payload đã gửi (test)
        self._ctx = threading.local()       # site_id đang xử lý (notify/call đúng chủ)
        # outbox: user_id -> {"seq": int, "items": deque[(seq, entry)]}
        self._outbox: dict = {}
        self._olock = threading.Lock()

    # ── Ngữ cảnh site (đa khách) ──────────────────────────────────

    def set_ctx(self, site_id):
        self._ctx.site_id = site_id

    def get_ctx(self):
        return getattr(self._ctx, "site_id", None)

    # ── Outbox (widget poll) ──────────────────────────────────────

    def _push(self, user_id: str, entry: dict):
        """Đẩy 1 tin vào hộp chờ của visitor. entry: {type, text?/url?, caption?}."""
        self._sent.append((user_id, entry))
        with self._olock:
            box = self._outbox.setdefault(str(user_id), {"seq": 0, "items": deque(maxlen=OUTBOX_MAX)})
            box["seq"] += 1
            box["items"].append((box["seq"], {**entry, "ts": time.time()}))

    def fetch(self, user_id: str, since: int = 0):
        """Widget poll: trả (messages sau `since`, seq mới nhất)."""
        with self._olock:
            box = self._outbox.get(str(user_id))
            if not box:
                return [], since
            msgs = [{"seq": s, **e} for s, e in box["items"] if s > since]
            return msgs, box["seq"]

    def last_seq(self, user_id: str) -> int:
        with self._olock:
            box = self._outbox.get(str(user_id))
            return box["seq"] if box else 0

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'web:S1:V9' → ('S1','V9'); 'web:V9' → (None,'V9')."""
        parts = str(user_id).split(":")
        if len(parts) >= 3:
            return parts[1], ":".join(parts[2:])
        if len(parts) == 2:
            return None, parts[1]
        return None, str(user_id)

    def _media_url(self, path: Path):
        """File trong MEDIA_DIR → đường dẫn TƯƠNG ĐỐI '/media/...' cho widget
        (widget prefix origin server webchat — KHÔNG dùng PUBLIC_BASE_URL vì
        tunnel chết là URL tuyệt đối gãy, tương đối thì luôn sống)."""
        try:
            rel = path.resolve().relative_to(Path(Config.MEDIA_DIR).resolve())
        except Exception:
            return None
        return "/media/" + "/".join(quote(p) for p in rel.parts)

    def _send_dir(self, user_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        urls = [u for u in (self._media_url(p) for p in photos) if u]
        if not urls:
            return False
        self._push(user_id, {"type": "text", "text": caption})
        for u in urls:
            self._push(user_id, {"type": "image", "url": u})
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        for i in range(0, len(text), MAX_LEN):
            self._push(user_id, {"type": "text", "text": text[i:i + MAX_LEN]})

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        return self._send_dir(user_id, Path(folder), caption)

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        if caption:
            self._push(user_id, {"type": "text", "text": caption})
        self._push(user_id, {"type": "image", "url": url})

    def send_file(self, user_id: str, path, url: str, kind: str, caption: str = "") -> bool:
        """Widget render được cả <img>/<video>/<audio> → đẩy entry ĐÚNG LOẠI
        (không phải link chữ như base). Ưu tiên đường dẫn TƯƠNG ĐỐI từ file
        local (media/outbox cùng server) — url tuyệt đối của chat_tools có thể
        dựng từ PUBLIC_BASE_URL/tunnel đã chết."""
        rel = self._media_url(Path(path)) if path else None
        target = rel or url
        if not target:
            return False
        kind = kind if kind in ("image", "video", "audio") else "file"
        self._push(user_id, {"type": kind, "url": target, "caption": caption or ""})
        return True

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(user_id, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._push(user_id, {
                "type": "text",
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?",
            })

    def send_price_photos(self, user_id: str) -> None:
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in LEGACY_ROOM_SETS:
            if self._send_dir(user_id, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._push(user_id, {
                "type": "text",
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!",
            })

    def notify_owner(self, text: str) -> None:
        """Báo chủ = đẩy tin vào outbox của visitor được '⭐ Đặt làm chủ' (chủ mở
        widget trên chính web của họ sẽ thấy). Webchat không đẩy notify ra ngoài
        được — khuyên chủ nối thêm Telegram/Zalo để nhận báo ngoài giờ."""
        site_id = self.get_ctx()
        owner = self.store.get_owner_user_id(site_id) if (self.store and site_id) else None
        if owner:
            self._push(f"web:{site_id}:{owner}", {"type": "text", "text": text})
        else:
            log.warning("[Webchat] Chưa đặt chủ site (⭐ Đặt làm chủ) → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # Webchat không gọi thoại — dùng chuỗi gọi Telethon chung (nếu cấu hình)
        owner_call.alert()
