"""
Kênh TikTok — trả lời khách qua TikTok Business Messaging API (DM).

Brain ra lệnh → TikTokChannel POST tới business-api.tiktok.com → tin tới khách.
Chiều ngược lại (khách nhắn → Python) do app/web_api/tiktok_api.py (webhook) xử lý.

Quy ước user_id (đa khách / multi-tenant): "tt:<business_id>:<user_open_id>"
  - business_id : tài khoản TikTok Business nhận tin → tra token trong TikTokStore
  - user_open_id: open_id của khách trên TikTok
Tương thích 1 tài khoản (.env): "tt:<user_open_id>" → dùng TIKTOK_ACCESS_TOKEN.

LƯU Ý THỰC TẾ: API nhắn tin TikTok CHỈ cấp cho app developer được TikTok duyệt
(Business Messaging, đang mở hạn chế). Chưa có token → channel chạy MOCK (ghi
_sent + log, không gọi mạng) — toàn bộ giao diện quản lý/thống kê vẫn hoạt động.
Mapping field API gói gọn trong _send_api() — TikTok đổi spec chỉ sửa 1 chỗ.

Giống Meta: TikTok KHÔNG nhận file local — ảnh phải là URL công khai
(PUBLIC_BASE_URL + /media/...). Thiếu → rơi về câu "đang cập nhật".

Báo chủ (notify/call) phụ thuộc account nào đang xử lý → dùng ngữ cảnh
thread-local (_ctx) đặt bởi tiktok_api lúc dispatch (như kênh Telegram).
"""

import logging
import threading
from pathlib import Path
from urllib.parse import quote

import requests

from app.core.config import Config
from app.core.channel import Channel
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5
MAX_LEN = 2000


class TikTokChannel(Channel):

    def __init__(self, store=None, access_token: str = None, business_id: str = None,
                 public_base_url: str = None, conv_manager=None):
        self.store = store          # TikTokStore: token theo từng business account (đa khách)
        self.access_token = (
            access_token if access_token is not None else Config.TIKTOK_ACCESS_TOKEN
        )
        self.business_id = (
            business_id if business_id is not None else Config.TIKTOK_BUSINESS_ID
        )
        base = public_base_url if public_base_url is not None else Config.PUBLIC_BASE_URL
        self.public_base_url = (base or "").rstrip("/")
        self.api_base = Config.TIKTOK_API_BASE.rstrip("/")
        self.conv_manager = conv_manager
        self.brain = None
        self._sent: list = []       # ghi payload đã gửi (phục vụ test/mock)
        self._ctx = threading.local()  # business_id của tin đang xử lý (cho notify/call)

    # ── Ngữ cảnh account (đa khách) ───────────────────────────────

    def set_ctx(self, business_id):
        self._ctx.business_id = business_id

    def _cur_account(self):
        return getattr(self._ctx, "business_id", None)

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'tt:BIZ:USER' → ('BIZ','USER'); 'tt:USER' → (None,'USER'); 'USER' → (None,'USER')."""
        parts = str(user_id).split(":")
        if len(parts) >= 3:
            return parts[1], ":".join(parts[2:])
        if len(parts) == 2:
            return None, parts[1]
        return None, str(user_id)

    def _token_for(self, business_id):
        if business_id and self.store:
            t = self.store.get_token(business_id)
            if t:
                return t
        return self.access_token

    def _owner_for(self, business_id):
        if business_id and self.store:
            oid = self.store.get_owner_open_id(business_id)
            if oid:
                return oid
        return None

    def _send_api(self, business_id, user_open_id: str, message: dict):
        """Gửi 1 tin DM. `message`: {"text": ...} hoặc {"image_url": ...}.
        Toàn bộ mapping sang API TikTok nằm ở đây — spec đổi chỉ sửa hàm này."""
        token = self._token_for(business_id)
        self._sent.append((user_open_id, message))
        if not token:
            log.info(f"[TT mock] (chưa token, biz={business_id}) → {user_open_id}: {message}")
            return None
        payload = {
            "business_id": business_id or self.business_id,
            "recipient_id": user_open_id,
        }
        if "image_url" in message:
            payload["message_type"] = "image"
            payload["image_url"] = message["image_url"]
        else:
            payload["message_type"] = "text"
            payload["text"] = message.get("text", "")
        try:
            r = requests.post(
                f"{self.api_base}/business/message/send/",
                headers={"Access-Token": token},
                json=payload, timeout=30,
            )
            if r.status_code >= 400:
                log.error(f"[TT] send {r.status_code}: {r.text[:300]}")
            return r
        except Exception as e:
            log.error(f"[TT] lỗi gửi: {e}")
            return None

    def _public_url(self, path: Path):
        """Đường dẫn file trong MEDIA_DIR → URL công khai để TikTok tải về."""
        if not self.public_base_url:
            return None
        try:
            rel = path.resolve().relative_to(Path(Config.MEDIA_DIR).resolve())
        except Exception:
            return None
        rel_url = "/".join(quote(p) for p in rel.parts)
        return f"{self.public_base_url}/media/{rel_url}"

    def _send_dir(self, business_id, user_open_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        urls = [u for u in (self._public_url(p) for p in photos) if u]
        if not urls:
            return False
        self._send_api(business_id, user_open_id, {"text": caption})
        for u in urls:
            self._send_api(business_id, user_open_id, {"image_url": u})
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        business_id, uid = self._parse(user_id)
        for i in range(0, len(text), MAX_LEN):
            self._send_api(business_id, uid, {"text": text[i:i + MAX_LEN]})

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        business_id, uid = self._parse(user_id)
        return self._send_dir(business_id, uid, Path(folder), caption)

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        business_id, uid = self._parse(user_id)
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(business_id, uid, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._send_api(business_id, uid, {
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?"
            })

    def send_price_photos(self, user_id: str) -> None:
        business_id, uid = self._parse(user_id)
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            if self._send_dir(business_id, uid, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._send_api(business_id, uid, {
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!"
            })

    def notify_owner(self, text: str) -> None:
        """DM cho chủ (owner_open_id của account đang xử lý — chủ phải từng nhắn
        account này, đặt qua nút '⭐ Đặt làm chủ' trong web)."""
        business_id = self._cur_account()
        owner = self._owner_for(business_id)
        if owner:
            self._send_api(business_id, owner, {"text": text})
        else:
            log.warning("[TT] Chưa có chủ (đặt trong web: Khách hàng → ⭐ Đặt làm chủ) → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # TikTok không gọi thoại được → dùng chuỗi gọi Telethon chung (nếu đã cấu hình)
        owner_call.alert()
