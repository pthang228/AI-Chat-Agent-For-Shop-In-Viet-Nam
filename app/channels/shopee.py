"""
Kênh Shopee — trả lời khách qua Shopee Open Platform (sellerchat API v2).

Brain ra lệnh → ShopeeChannel POST tới partner.shopeemobile.com → tin tới khách
trong khung chat Shopee. Chiều ngược lại (khách nhắn → Python) do
app/web_api/shopee_api.py (webhook push) xử lý.

Quy ước user_id (đa khách / multi-tenant): "sp:<shop_id>:<buyer_id>"
  - shop_id : shop Shopee nhận tin → tra access_token trong ShopeeStore
  - buyer_id: user_id của khách trên Shopee
Tương thích 1 shop (.env): "sp:<buyer_id>" → dùng SHOPEE_ACCESS_TOKEN.

LƯU Ý THỰC TẾ: API sellerchat CHỈ dùng được khi app vendor được Shopee DUYỆT
trên open.shopee.com (đăng ký developer → tạo app → duyệt) + shop khách UỶ QUYỀN
cho app. Chưa có token → channel chạy MOCK (ghi _sent + log, không gọi mạng) —
toàn bộ giao diện quản lý/thống kê vẫn hoạt động. Mọi mapping API (đường dẫn,
chữ ký, body) gói trong _sign() + _send_api() — Shopee đổi spec chỉ sửa 2 chỗ đó.

Giống Meta/TikTok: Shopee KHÔNG nhận file local — ảnh phải là URL công khai
(PUBLIC_BASE_URL + /media/...). Thiếu → rơi về câu "đang cập nhật".

Báo chủ (notify/call) phụ thuộc shop nào đang xử lý → dùng ngữ cảnh
thread-local (_ctx) đặt bởi shopee_api lúc dispatch (như kênh TikTok).
"""

import hashlib
import hmac
import logging
import threading
import time
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
MAX_LEN = 1000   # Shopee chat giới hạn tin ngắn hơn các kênh khác

SEND_PATH = "/api/v2/sellerchat/send_message"
REFRESH_PATH = "/api/v2/auth/access_token/get"


class ShopeeChannel(Channel):

    def __init__(self, store=None, access_token: str = None, shop_id: str = None,
                 partner_id: str = None, partner_key: str = None,
                 public_base_url: str = None, conv_manager=None):
        self.store = store          # ShopeeStore: token theo từng shop (đa khách)
        self.access_token = (
            access_token if access_token is not None else Config.SHOPEE_ACCESS_TOKEN
        )
        self.shop_id = shop_id if shop_id is not None else Config.SHOPEE_SHOP_ID
        self.partner_id = (
            partner_id if partner_id is not None else Config.SHOPEE_PARTNER_ID
        )
        self.partner_key = (
            partner_key if partner_key is not None else Config.SHOPEE_PARTNER_KEY
        )
        base = public_base_url if public_base_url is not None else Config.PUBLIC_BASE_URL
        self.public_base_url = (base or "").rstrip("/")
        self.api_base = Config.SHOPEE_API_BASE.rstrip("/")
        self.conv_manager = conv_manager
        self.brain = None
        self._sent: list = []       # ghi payload đã gửi (phục vụ test/mock)
        self._ctx = threading.local()  # shop_id của tin đang xử lý (cho notify/call)

    # ── Ngữ cảnh shop (đa khách) ──────────────────────────────────

    def set_ctx(self, shop_id):
        self._ctx.shop_id = shop_id

    def get_ctx(self):
        return getattr(self._ctx, "shop_id", None)

    def _cur_shop(self):
        return getattr(self._ctx, "shop_id", None)

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'sp:SHOP:BUYER' → ('SHOP','BUYER'); 'sp:BUYER' → (None,'BUYER'); 'BUYER' → (None,'BUYER')."""
        parts = str(user_id).split(":")
        if len(parts) >= 3:
            return parts[1], ":".join(parts[2:])
        if len(parts) == 2:
            return None, parts[1]
        return None, str(user_id)

    def _token_for(self, shop_id):
        if shop_id and self.store:
            t = self.store.get_token(shop_id)
            if t:
                return t
        return self.access_token

    def _owner_for(self, shop_id):
        if shop_id and self.store:
            oid = self.store.get_owner_buyer_id(shop_id)
            if oid:
                return oid
        return None

    def _sign(self, path: str, timestamp: int, access_token: str, shop_id: str) -> str:
        """Chữ ký Shopee v2: HMAC-SHA256(partner_key, partner_id+path+ts+token+shop_id)."""
        base = f"{self.partner_id}{path}{timestamp}{access_token}{shop_id}"
        return hmac.new(self.partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()

    def _sign_public(self, path: str, timestamp: int) -> str:
        """Chữ ký API công khai (refresh token): HMAC(partner_key, partner_id+path+ts)."""
        base = f"{self.partner_id}{path}{timestamp}"
        return hmac.new(self.partner_key.encode(), base.encode(), hashlib.sha256).hexdigest()

    def _refresh(self, shop_id) -> str:
        """Access token Shopee sống ~4h → đổi token mới bằng refresh_token.
        Trả access_token mới hoặc "" nếu không refresh được. Shopee trả cả
        refresh_token mới → lưu đè ngay (như Zalo OA)."""
        if not (shop_id and self.store and self.partner_id and self.partner_key):
            return ""
        rt = self.store.get(shop_id).get("refresh_token") if hasattr(self.store, "get") else None
        if not rt:
            return ""
        ts = int(time.time())
        try:
            r = requests.post(
                f"{self.api_base}{REFRESH_PATH}",
                params={"partner_id": self.partner_id, "timestamp": ts,
                        "sign": self._sign_public(REFRESH_PATH, ts)},
                json={"shop_id": int(shop_id) if str(shop_id).isdigit() else shop_id,
                      "refresh_token": rt, "partner_id": int(self.partner_id)
                      if str(self.partner_id).isdigit() else self.partner_id},
                timeout=15,
            )
            j = r.json() if r.content else {}
            new_at = j.get("access_token") or ""
            if new_at:
                self.store.upsert(shop_id, access_token=new_at,
                                  refresh_token=j.get("refresh_token") or None)
                log.info(f"[SP] đã refresh token cho shop {shop_id}")
                return new_at
            log.error(f"[SP] refresh token thất bại shop {shop_id}: {str(j.get('error') or j)[:200]}")
        except Exception as e:
            log.error(f"[SP] lỗi refresh token shop {shop_id}: {e}")
        return ""

    @staticmethod
    def _is_token_error(j: dict) -> bool:
        err = str((j or {}).get("error") or "").lower()
        return bool(err) and ("token" in err or "auth" in err)

    def _send_api(self, shop_id, buyer_id: str, message: dict, _retried=False):
        """Gửi 1 tin chat. `message`: {"text": ...} hoặc {"image_url": ...}.
        Toàn bộ mapping sang API Shopee nằm ở đây — spec đổi chỉ sửa hàm này.
        Token hết hạn (~4h) → tự refresh + gửi lại đúng 1 lần."""
        shop_id = str(shop_id or self.shop_id or "")
        token = self._token_for(shop_id)
        if not _retried:
            self._sent.append((buyer_id, message))
        if not (token and self.partner_id and self.partner_key):
            log.info(f"[SP mock] (chưa đủ token/partner, shop={shop_id}) → {buyer_id}: {message}")
            return None
        ts = int(time.time())
        params = {
            "partner_id": self.partner_id,
            "timestamp": ts,
            "sign": self._sign(SEND_PATH, ts, token, shop_id),
            "access_token": token,
            "shop_id": shop_id,
        }
        if "image_url" in message:
            body = {"to_id": int(buyer_id) if str(buyer_id).isdigit() else buyer_id,
                    "message_type": "image",
                    "content": {"image_url": message["image_url"]}}
        else:
            body = {"to_id": int(buyer_id) if str(buyer_id).isdigit() else buyer_id,
                    "message_type": "text",
                    "content": {"text": message.get("text", "")}}
        r = post_with_retry(f"{self.api_base}{SEND_PATH}",
                            params=params, json=body, timeout=30,
                            retries=Config.SEND_RETRIES, log_tag="SP")
        if r is None:
            return None
        if r.status_code >= 400:
            log.error(f"[SP] send {r.status_code}: {r.text[:300]}")
        else:
            j = r.json() if r.content else {}
            if self._is_token_error(j) and not _retried and self._refresh(shop_id):
                return self._send_api(shop_id, buyer_id, message, _retried=True)
            if j.get("error"):
                log.error(f"[SP] send error: {j.get('error')} {str(j.get('message', ''))[:200]}")
        return r

    def _public_url(self, path: Path):
        """Đường dẫn file trong MEDIA_DIR → URL công khai để Shopee tải về."""
        if not self.public_base_url:
            return None
        try:
            rel = path.resolve().relative_to(Path(Config.MEDIA_DIR).resolve())
        except Exception:
            return None
        rel_url = "/".join(quote(p) for p in rel.parts)
        return f"{self.public_base_url}/media/{rel_url}"

    def _send_dir(self, shop_id, buyer_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        urls = [u for u in (self._public_url(p) for p in photos) if u]
        if not urls:
            return False
        self._send_api(shop_id, buyer_id, {"text": caption})
        for u in urls:
            self._send_api(shop_id, buyer_id, {"image_url": u})
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        shop_id, uid = self._parse(user_id)
        for i in range(0, len(text), MAX_LEN):
            self._send_api(shop_id, uid, {"text": text[i:i + MAX_LEN]})

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        shop_id, uid = self._parse(user_id)
        return self._send_dir(shop_id, uid, Path(folder), caption)

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        shop_id, uid = self._parse(user_id)
        if caption:
            self._send_api(shop_id, uid, {"text": caption})
        self._send_api(shop_id, uid, {"image_url": url})

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        shop_id, uid = self._parse(user_id)
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(shop_id, uid, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._send_api(shop_id, uid, {
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?"
            })

    def send_price_photos(self, user_id: str) -> None:
        shop_id, uid = self._parse(user_id)
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            if self._send_dir(shop_id, uid, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._send_api(shop_id, uid, {
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!"
            })

    def notify_owner(self, text: str) -> None:
        """Chat cho chủ (owner_buyer_id của shop đang xử lý — chủ phải từng nhắn
        shop này, đặt qua nút '⭐ Đặt làm chủ' trong web)."""
        shop_id = self._cur_shop()
        owner = self._owner_for(shop_id)
        if owner:
            self._send_api(shop_id, owner, {"text": text})
        else:
            log.warning("[SP] Chưa có chủ (đặt trong web: Khách hàng → ⭐ Đặt làm chủ) → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # Shopee không gọi thoại được → dùng chuỗi gọi Telethon chung (nếu đã cấu hình)
        owner_call.alert()
