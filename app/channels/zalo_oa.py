"""
Kênh Zalo OA (Official Account) — trả lời khách qua Zalo Official Account API v3.

KHÁC kênh "Zalo" hiện có (Zalo cá nhân, QR login qua Node/zca-js): đây là kênh
CHÍNH THỨC của Zalo dành cho doanh nghiệp — token cấp qua OAuth, webhook push,
không rủi ro khoá tài khoản. Brain ra lệnh → ZaloOAChannel POST tới
openapi.zalo.me → tin tới khách trong khung chat OA. Chiều ngược lại
(khách nhắn → Python) do app/web_api/zalo_oa_api.py (webhook) xử lý.

Quy ước user_id (đa khách / multi-tenant): "oa:<oa_id>:<user_id>"
  - oa_id  : OA nhận tin → tra access_token trong ZaloOAStore
  - user_id: user_id của khách do Zalo cấp (theo từng OA)
Tương thích 1 OA (.env): "oa:<user_id>" → dùng ZALO_OA_ACCESS_TOKEN.

ĐIỂM KHÁC BIỆT QUAN TRỌNG so với các kênh khác (học từ chuẩn Zalo):
  - Access token OA chỉ sống ~25 GIỜ → channel TỰ REFRESH bằng refresh_token
    (oauth.zaloapp.com v4) khi Zalo trả lỗi token (-216/-124), lưu token mới
    vào store rồi GỬI LẠI 1 lần. Refresh token dùng 1 lần — Zalo cấp cái mới
    mỗi lần refresh, PHẢI lưu đè ngay.
  - Cửa sổ nhắn tin: OA chỉ được gửi "tin Tư vấn" (CS) miễn phí trong 48h kể
    từ tin cuối của khách. Bot chỉ trả lời khi khách vừa nhắn → luôn trong
    cửa sổ; tin chủ động ngoài 48h cần ZNS (chưa làm).

Chưa có token → channel chạy MOCK (ghi _sent + log, không gọi mạng) — toàn bộ
giao diện quản lý/thống kê vẫn hoạt động. Mọi mapping API (đường dẫn, header,
body) gói trong _send_api() + _refresh() — Zalo đổi spec chỉ sửa 2 chỗ đó.

Ảnh: Zalo OA nhận ảnh qua URL CÔNG KHAI (template media) — cần PUBLIC_BASE_URL
như Meta/TikTok/Shopee. Thiếu → rơi về câu "đang cập nhật".
"""

import logging
import threading
from pathlib import Path
from urllib.parse import quote

import requests

from app.core.config import Config
from app.core.channel import Channel
from app.core.http_util import post_with_retry
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5
MAX_LEN = 2000            # Zalo OA giới hạn text ~2000 ký tự / tin

SEND_PATH = "/oa/message/cs"          # tin Tư vấn (trong cửa sổ 48h)
# Mã lỗi Zalo báo access token hỏng/hết hạn → thử refresh rồi gửi lại
TOKEN_ERRORS = (-216, -124)


class ZaloOAChannel(Channel):

    def __init__(self, store=None, access_token: str = None, oa_id: str = None,
                 app_id: str = None, app_secret: str = None,
                 public_base_url: str = None, conv_manager=None):
        self.store = store          # ZaloOAStore: token theo từng OA (đa khách)
        self.access_token = (
            access_token if access_token is not None else Config.ZALO_OA_ACCESS_TOKEN
        )
        self.oa_id = oa_id if oa_id is not None else Config.ZALO_OA_ID
        self.app_id = app_id if app_id is not None else Config.ZALO_OA_APP_ID
        self.app_secret = (
            app_secret if app_secret is not None else Config.ZALO_OA_APP_SECRET
        )
        base = public_base_url if public_base_url is not None else Config.PUBLIC_BASE_URL
        self.public_base_url = (base or "").rstrip("/")
        self.api_base = Config.ZALO_OA_API_BASE.rstrip("/")
        self.oauth_base = Config.ZALO_OA_OAUTH_BASE.rstrip("/")
        self.conv_manager = conv_manager
        self.brain = None
        self._sent: list = []       # ghi payload đã gửi (phục vụ test/mock)
        self._ctx = threading.local()  # oa_id của tin đang xử lý (cho notify/call)

    # ── Ngữ cảnh OA (đa khách) ────────────────────────────────────

    def set_ctx(self, oa_id):
        self._ctx.oa_id = oa_id

    def get_ctx(self):
        return getattr(self._ctx, "oa_id", None)

    def _cur_oa(self):
        return getattr(self._ctx, "oa_id", None)

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'oa:OA1:U9' → ('OA1','U9'); 'oa:U9' → (None,'U9'); 'U9' → (None,'U9')."""
        parts = str(user_id).split(":")
        if len(parts) >= 3:
            return parts[1], ":".join(parts[2:])
        if len(parts) == 2:
            return None, parts[1]
        return None, str(user_id)

    def _token_for(self, oa_id):
        if oa_id and self.store:
            t = self.store.get_token(oa_id)
            if t:
                return t
        return self.access_token

    def _owner_for(self, oa_id):
        if oa_id and self.store:
            oid = self.store.get_owner_user_id(oa_id)
            if oid:
                return oid
        return None

    def _refresh(self, oa_id) -> str:
        """Access token OA hết hạn (~25h) → đổi token mới bằng refresh_token
        (OAuth v4). Refresh token dùng 1 LẦN — Zalo trả cặp mới, lưu đè ngay.
        Trả về access_token mới hoặc "" nếu không refresh được."""
        if not (oa_id and self.store and self.app_id and self.app_secret):
            return ""
        rt = self.store.get_refresh_token(oa_id)
        if not rt:
            return ""
        try:
            r = requests.post(
                f"{self.oauth_base}/oa/access_token",
                headers={"secret_key": self.app_secret},
                data={"app_id": self.app_id, "grant_type": "refresh_token",
                      "refresh_token": rt},
                timeout=15,
            )
            j = r.json() if r.content else {}
            new_at = j.get("access_token") or ""
            if new_at:
                self.store.upsert(oa_id, access_token=new_at,
                                  refresh_token=j.get("refresh_token") or None)
                log.info(f"[OA] đã refresh token cho OA {oa_id}")
                return new_at
            log.error(f"[OA] refresh token thất bại OA {oa_id}: "
                      f"{str(j.get('error_name') or j)[:200]}")
        except Exception as e:
            log.error(f"[OA] lỗi refresh token OA {oa_id}: {e}")
        return ""

    def _send_api(self, oa_id, user_id: str, message: dict, _retried=False):
        """Gửi 1 tin CS. `message`: {"text": ...} hoặc {"image_url": ...}.
        Toàn bộ mapping sang API Zalo OA nằm ở đây — spec đổi chỉ sửa hàm này.
        Token hết hạn → tự refresh + gửi lại đúng 1 lần."""
        oa_id = str(oa_id or self.oa_id or "")
        token = self._token_for(oa_id)
        if not _retried:
            self._sent.append((user_id, message))
        if not token:
            log.info(f"[OA mock] (chưa có token, oa={oa_id}) → {user_id}: {message}")
            return None
        if "image_url" in message:
            msg = {"attachment": {"type": "template", "payload": {
                "template_type": "media",
                "elements": [{"media_type": "image", "url": message["image_url"]}],
            }}}
        else:
            msg = {"text": message.get("text", "")}
        body = {"recipient": {"user_id": user_id}, "message": msg}
        r = post_with_retry(
            f"{self.api_base}{SEND_PATH}",
            headers={"access_token": token, "Content-Type": "application/json"},
            json=body, timeout=30,
            retries=Config.SEND_RETRIES, log_tag="OA",
        )
        if r is None:
            return None
        j = r.json() if r.content else {}
        err = j.get("error", 0)
        if err in TOKEN_ERRORS and not _retried:
            # token chết → refresh rồi thử lại 1 lần
            if self._refresh(oa_id):
                return self._send_api(oa_id, user_id, message, _retried=True)
        if r.status_code >= 400 or err:
            log.error(f"[OA] send lỗi ({r.status_code}/err={err}): "
                      f"{str(j.get('message') or r.text)[:300]}")
        return r

    def _public_url(self, path: Path):
        """Đường dẫn file trong MEDIA_DIR → URL công khai để Zalo tải về."""
        if not self.public_base_url:
            return None
        try:
            rel = path.resolve().relative_to(Path(Config.MEDIA_DIR).resolve())
        except Exception:
            return None
        rel_url = "/".join(quote(p) for p in rel.parts)
        return f"{self.public_base_url}/media/{rel_url}"

    def _send_dir(self, oa_id, user_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        urls = [u for u in (self._public_url(p) for p in photos) if u]
        if not urls:
            return False
        self._send_api(oa_id, user_id, {"text": caption})
        for u in urls:
            self._send_api(oa_id, user_id, {"image_url": u})
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        oa_id, uid = self._parse(user_id)
        for i in range(0, len(text), MAX_LEN):
            self._send_api(oa_id, uid, {"text": text[i:i + MAX_LEN]})

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        oa_id, uid = self._parse(user_id)
        return self._send_dir(oa_id, uid, Path(folder), caption)

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        oa_id, uid = self._parse(user_id)
        if caption:
            self._send_api(oa_id, uid, {"text": caption})
        self._send_api(oa_id, uid, {"image_url": url})

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        oa_id, uid = self._parse(user_id)
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(oa_id, uid, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._send_api(oa_id, uid, {
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?"
            })

    def send_price_photos(self, user_id: str) -> None:
        oa_id, uid = self._parse(user_id)
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            if self._send_dir(oa_id, uid, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._send_api(oa_id, uid, {
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!"
            })

    def notify_owner(self, text: str) -> None:
        """Nhắn cho chủ (owner_user_id của OA đang xử lý — chủ phải từng nhắn
        OA này, đặt qua nút '⭐ Đặt làm chủ' trong web). LƯU Ý cửa sổ 48h:
        chủ im quá 48h thì tin báo có thể không tới — nhắc chủ thỉnh thoảng
        nhắn OA 1 tin."""
        oa_id = self._cur_oa()
        owner = self._owner_for(oa_id)
        if owner:
            self._send_api(oa_id, owner, {"text": text})
        else:
            log.warning("[OA] Chưa có chủ (đặt trong web: Khách hàng → ⭐ Đặt làm chủ) → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # Zalo OA không gọi thoại được → dùng chuỗi gọi Telethon chung (nếu đã cấu hình)
        owner_call.alert()
