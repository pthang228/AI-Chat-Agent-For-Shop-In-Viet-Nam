"""
Kênh Telegram — bot trả lời khách qua Telegram Bot API.

Ưu điểm so với Meta: KHÔNG cần App Review, người lạ nhắn được NGAY, long-polling
nên KHÔNG cần public URL/deploy. Khách (homestay) tự kết nối bằng cách DÁN token
bot (@BotFather) ngay trong web → đa khách.

Quy ước user_id:
  - Đa khách: "tg:<bot_id>:<chat_id>" → tra token bot trong TelegramStore.
  - 1 bot (.env, tương thích cũ): "tg:<chat_id>" → dùng token .env.
chat_id (chat 1-1) chính là Telegram user id → dùng cho cả nhắn báo lẫn gọi thoại.
Telegram cho UPLOAD ảnh local trực tiếp (multipart), KHÔNG cần URL công khai.

Báo chủ (notify/call) phụ thuộc bot nào đang xử lý → dùng ngữ cảnh thread-local
(_ctx) đặt bởi telegram_api lúc dispatch (brain.handle chạy trong thread riêng).
"""

import logging
import threading
from pathlib import Path

import requests

from app.core.config import Config
from app.core.channel import Channel, LEGACY_ROOM_SETS
from app.core.http_util import post_with_retry
from app.core import owner_call, telegram_owner

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5
MAX_LEN = 4000  # Telegram giới hạn 4096 ký tự/tin


class TelegramChannel(Channel):

    def __init__(self, store=None, token: str = None, owner_chat_id: str = None, conv_manager=None):
        self.store = store          # TelegramStore: token theo từng bot (đa khách)
        self.token = token if token is not None else Config.TELEGRAM_BOT_TOKEN  # 1 bot (.env)
        self.owner_chat_id = (
            owner_chat_id if owner_chat_id is not None else Config.TELEGRAM_OWNER_CHAT_ID
        )
        self.conv_manager = conv_manager
        self.brain = None
        self._sent: list = []       # ghi payload đã gửi (phục vụ test/mock)
        self._ctx = threading.local()  # bot_id của tin đang xử lý (cho notify/call)

    # ── Ngữ cảnh bot (đa khách) ───────────────────────────────────

    def set_ctx(self, bot_id):
        self._ctx.bot_id = bot_id

    def get_ctx(self):
        return getattr(self._ctx, "bot_id", None)

    def _cur_bot(self):
        return getattr(self._ctx, "bot_id", None)

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'tg:BOT:CHAT' → ('BOT','CHAT'); 'tg:CHAT' → (None,'CHAT'); 'CHAT' → (None,'CHAT')."""
        s = str(user_id)
        parts = s.split(":")
        if len(parts) >= 3:           # tg:bot:chat
            return parts[1], ":".join(parts[2:])
        if len(parts) == 2:           # tg:chat (1 bot)
            return None, parts[1]
        return None, s

    def _token_for(self, bot_id):
        if bot_id and self.store:
            t = self.store.get_token(bot_id)
            if t:
                return t
        return self.token

    def _owner_for(self, bot_id):
        if bot_id and self.store:
            cid = self.store.get_owner_chat_id(bot_id)
            if cid:
                return cid
        return telegram_owner.get_owner_chat_id() or (self.owner_chat_id or None)

    def _post(self, token, method: str, data: dict, files: dict = None):
        self._sent.append((method, data))
        if not token:
            log.info(f"[TG mock] {method} {data}")
            return None
        r = post_with_retry(f"https://api.telegram.org/bot{token}/{method}",
                            data=data, files=files, timeout=30,
                            retries=Config.SEND_RETRIES, log_tag=f"TG {method}")
        if r is None:
            return None
        if r.status_code >= 400:
            log.error(f"[TG] {method} {r.status_code}: {r.text[:300]}")
        return r

    def _send_photo_file(self, token, chat_id: str, path: Path):
        self._sent.append(("sendPhoto", {"chat_id": chat_id, "path": str(path)}))
        if not token:
            log.info(f"[TG mock] sendPhoto {path}")
            return
        try:
            with open(path, "rb") as f:
                r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                                  data={"chat_id": chat_id}, files={"photo": f}, timeout=60)
                if r.status_code >= 400:
                    log.error(f"[TG] sendPhoto {r.status_code}: {r.text[:200]}")
        except Exception as e:
            log.error(f"[TG] lỗi sendPhoto {path}: {e}")

    def _send_dir(self, token, chat_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        if not photos:
            return False
        self._post(token, "sendMessage", {"chat_id": chat_id, "text": caption})
        for p in photos:
            self._send_photo_file(token, chat_id, p)
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        bot_id, chat_id = self._parse(user_id)
        token = self._token_for(bot_id)
        for i in range(0, len(text), MAX_LEN):
            self._post(token, "sendMessage", {"chat_id": chat_id, "text": text[i:i + MAX_LEN]})

    def send_file(self, user_id: str, path, url: str, kind: str, caption: str = "") -> bool:
        """Telegram gửi ảnh/video/ghi âm THẬT (upload multipart local file) — không
        phụ thuộc URL/tunnel."""
        from pathlib import Path as _P
        bot_id, chat_id = self._parse(user_id)
        token = self._token_for(bot_id)
        method, field = {"image": ("sendPhoto", "photo"),
                         "video": ("sendVideo", "video"),
                         "audio": ("sendAudio", "audio")}.get(kind, ("sendDocument", "document"))
        self._sent.append((method, {"chat_id": chat_id, "path": str(path)}))
        if not token:
            log.info(f"[TG mock] {method} {path}")
            return True
        try:
            with open(_P(path), "rb") as f:
                data = {"chat_id": chat_id}
                if caption:
                    data["caption"] = caption[:1000]
                r = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                                  data=data, files={field: f}, timeout=120)
            if r.status_code >= 400:
                log.error(f"[TG] {method} {r.status_code}: {r.text[:200]}")
                # định dạng bị từ chối (vd webm ghi âm) → thử gửi dạng tài liệu
                if method != "sendDocument":
                    with open(_P(path), "rb") as f:
                        r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                                          data={"chat_id": chat_id}, files={"document": f}, timeout=120)
                    return r.status_code < 400
                return False
            return True
        except Exception as e:
            log.error(f"[TG] lỗi {method} {path}: {e}")
            return False

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        bot_id, chat_id = self._parse(user_id)
        return self._send_dir(self._token_for(bot_id), chat_id, Path(folder), caption)

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        bot_id, chat_id = self._parse(user_id)
        # Telegram sendPhoto nhận URL trực tiếp — không cần tải về
        self._post(self._token_for(bot_id), "sendPhoto",
                   {"chat_id": chat_id, "photo": url, "caption": caption or ""})

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        bot_id, chat_id = self._parse(user_id)
        token = self._token_for(bot_id)
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(token, chat_id, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._post(token, "sendMessage", {
                "chat_id": chat_id,
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?",
            })

    def send_price_photos(self, user_id: str) -> None:
        bot_id, chat_id = self._parse(user_id)
        token = self._token_for(bot_id)
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in LEGACY_ROOM_SETS:
            if self._send_dir(token, chat_id, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._post(token, "sendMessage", {
                "chat_id": chat_id,
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!",
            })

    def notify_owner(self, text: str) -> None:
        bot_id = self._cur_bot()
        owner = self._owner_for(bot_id)
        if owner:
            self._post(self._token_for(bot_id), "sendMessage", {"chat_id": owner, "text": text})
        else:
            log.warning("[TG] Chưa có chủ (chủ nhắn /start để đăng ký) → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # Gọi cho chủ (target) bằng acc gọi của bot đó (session đã đăng nhập QR);
        # bản .env không có session → dùng file Config.TG_SESSION chung.
        bot_id = self._cur_bot()
        session = self.store.get_caller_session(bot_id) if (bot_id and self.store) else None
        owner_call.alert(target_id=self._owner_for(bot_id), session=session)
