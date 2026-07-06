"""
Kênh Meta — Facebook Messenger + Instagram DM (dùng chung Graph API Send API).

Brain ra lệnh → MetaChannel POST tới graph.facebook.com → tin tới khách.
Chiều ngược lại (khách nhắn → Python) do meta_webhook.py xử lý.

Quy ước user_id (đa Page / multi-tenant): "<platform>:<page_id>:<recipient_id>"
  - platform: "fb" (Messenger) | "ig" (Instagram)
  - page_id : Page nhận tin → tra token trong MetaStore để trả lời ĐÚNG danh nghĩa
  - recipient_id: PSID (FB) / IGSID (IG) của khách
Tương thích ngược: "<platform>:<recipient_id>" (2 phần) → page_id=None, dùng token .env.
Cùng 1 endpoint /me/messages cho cả Messenger lẫn IG, chỉ khác token theo Page.

Khác Zalo: Messenger/IG KHÔNG nhận đường dẫn file local — ảnh phải là URL công khai
(serve qua meta_webhook /media/... với PUBLIC_BASE_URL). Thiếu PUBLIC_BASE_URL thì
không gửi được ảnh (rơi về câu "đang cập nhật").
"""

import hashlib
import hmac
import logging
from pathlib import Path
from urllib.parse import quote

from app.core.config import Config
from app.core.channel import Channel
from app.core.http_util import post_with_retry
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5
MAX_LEN = 2000


class MetaChannel(Channel):

    def __init__(
        self,
        store=None,
        page_token: str = None,
        public_base_url: str = None,
        graph_version: str = None,
        owner_psid: str = None,
        conv_manager=None,
        ig_token: str = None,
        ig_graph_version: str = None,
    ):
        self.store = store          # MetaStore: token theo từng Page (multi-tenant)
        self.page_token = page_token if page_token is not None else Config.FB_PAGE_ACCESS_TOKEN
        base = public_base_url if public_base_url is not None else Config.PUBLIC_BASE_URL
        self.public_base_url = (base or "").rstrip("/")
        self.graph_version = graph_version or Config.FB_GRAPH_VERSION
        self.owner_psid = owner_psid if owner_psid is not None else Config.FB_OWNER_PSID
        # Instagram (nhánh Instagram Login): gửi qua graph.instagram.com bằng token IG riêng
        self.ig_token = ig_token if ig_token is not None else Config.IG_ACCESS_TOKEN
        self.ig_graph_version = ig_graph_version or Config.IG_GRAPH_VERSION
        self.conv_manager = conv_manager
        self.brain = None          # main_meta.py gán Brain sau
        self._sent: list = []      # ghi lại payload đã gửi (phục vụ test/mock)

    # ── Tiện ích ──────────────────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'fb:PAGE:PSID' → ('fb','PAGE','PSID'); 'fb:PSID' → ('fb',None,'PSID')."""
        parts = str(user_id).split(":")
        if len(parts) >= 3:
            return parts[0], parts[1], ":".join(parts[2:])
        if len(parts) == 2:
            return parts[0], None, parts[1]
        return "fb", None, str(user_id)

    def _token_for(self, page_id):
        """Token của Page (multi-tenant) → fallback token .env (single-tenant/test)."""
        if page_id and self.store:
            t = self.store.get_token(page_id)
            if t:
                return t
        return self.page_token

    def _endpoint(self, platform: str, page_id):
        """(url, token) tuỳ nền tảng:
          - fb: graph.facebook.com + token Page (Messenger)
          - ig: ĐA KHÁCH → ưu tiên token Page của khách qua graph.facebook.com
            (app đã được cấp instagram_manage_messages → gửi IG bằng chính token
            Page, mỗi homestay 1 token riêng, KHÔNG cần token IG thủ công).
            Fallback single-tenant: graph.instagram.com + IG_ACCESS_TOKEN (.env).
        """
        if platform == "ig":
            page_tok = self._token_for(page_id) if page_id else None
            if page_tok:
                return (f"https://graph.facebook.com/{self.graph_version}/me/messages", page_tok)
            return (f"https://graph.instagram.com/{self.ig_graph_version}/me/messages", self.ig_token)
        return (f"https://graph.facebook.com/{self.graph_version}/me/messages",
                self._token_for(page_id))

    @staticmethod
    def _appsecret_proof(token: str) -> str:
        """appsecret_proof = HMAC-SHA256(app_secret, access_token) — Meta khuyến
        nghị kèm để token bị lộ cũng không gọi API thay bạn được. Chỉ dùng cho
        graph.facebook.com; rỗng khi chưa cấu hình FB_APP_SECRET."""
        secret = Config.FB_APP_SECRET
        if not (secret and token):
            return ""
        return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()

    def _check_token_error(self, resp, page_id):
        """Meta trả code 190 = token hết hạn/thu hồi → đánh dấu Page cần kết nối
        lại (UI hiện cảnh báo) thay vì im lặng mãi. Chỉ đánh dấu 1 lần."""
        if not (page_id and self.store and hasattr(self.store, "mark_token_invalid")):
            return
        try:
            err = (resp.json() or {}).get("error") or {}
        except Exception:
            return
        if err.get("code") == 190:
            self.store.mark_token_invalid(page_id)
            log.error(f"[Meta] token Page {page_id} hết hạn/thu hồi (code 190) "
                      f"→ đã đánh dấu CẦN KẾT NỐI LẠI")

    def _send_api(self, platform, page_id, recipient_id: str, message: dict):
        url, token = self._endpoint(platform, page_id)
        self._sent.append((recipient_id, message))
        if not token:
            log.info(f"[Meta mock] (chưa token, {platform} page={page_id}) → {recipient_id}: {message}")
            return None
        payload = {"recipient": {"id": recipient_id}, "message": message}
        params = {"access_token": token}
        # graph.instagram.com (Instagram Login) KHÔNG dùng messaging_type/appsecret_proof.
        if "graph.instagram.com" not in url:
            payload["messaging_type"] = "RESPONSE"
            proof = self._appsecret_proof(token)
            if proof:
                params["appsecret_proof"] = proof
        r = post_with_retry(url, params=params, json=payload, timeout=30,
                            retries=Config.SEND_RETRIES, log_tag=f"Meta {platform}")
        if r is None:
            return None
        if r.status_code >= 400:
            log.error(f"[Meta][{platform}] send {r.status_code}: {r.text[:300]}")
            self._check_token_error(r, page_id)
        return r

    def _public_url(self, path: Path):
        """Đổi đường dẫn file trong MEDIA_DIR → URL công khai để Meta tải về."""
        if not self.public_base_url:
            return None
        try:
            rel = path.resolve().relative_to(Path(Config.MEDIA_DIR).resolve())
        except Exception:
            return None
        rel_url = "/".join(quote(p) for p in rel.parts)
        return f"{self.public_base_url}/media/{rel_url}"

    def _send_dir(self, platform, page_id, recipient_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            f for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        urls = [u for u in (self._public_url(p) for p in photos) if u]
        if not urls:
            return False
        self._send_api(platform, page_id, recipient_id, {"text": caption})
        for u in urls:
            self._send_api(platform, page_id, recipient_id, {
                "attachment": {"type": "image", "payload": {"url": u, "is_reusable": True}}
            })
        return True

    # ── Giao diện Channel ─────────────────────────────────────────

    def send_text(self, user_id: str, text: str) -> None:
        platform, page_id, rid = self._parse(user_id)
        for i in range(0, len(text), MAX_LEN):
            self._send_api(platform, page_id, rid, {"text": text[i:i + MAX_LEN]})

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        platform, page_id, rid = self._parse(user_id)
        return self._send_dir(platform, page_id, rid, Path(folder), caption)

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        platform, page_id, rid = self._parse(user_id)
        if caption:
            self._send_api(platform, page_id, rid, {"text": caption})
        self._send_api(platform, page_id, rid, {
            "attachment": {"type": "image", "payload": {"url": url, "is_reusable": True}}
        })

    def send_room_photos(self, user_id: str, room_names: list) -> None:
        platform, page_id, rid = self._parse(user_id)
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(platform, page_id, rid, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self._send_api(platform, page_id, rid, {
                "text": "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?"
            })

    def send_price_photos(self, user_id: str) -> None:
        platform, page_id, rid = self._parse(user_id)
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            if self._send_dir(platform, page_id, rid, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self._send_api(platform, page_id, rid, {
                "text": "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!"
            })

    def notify_owner(self, text: str) -> None:
        """Meta không có nhóm như Zalo → DM cho PSID chủ nhà nếu đã cấu hình.
        (Multi-tenant: hiện báo ở mức vendor; báo theo từng Page sẽ làm sau khi
        brain truyền được ngữ cảnh Page.)"""
        if self.owner_psid:
            self._send_api("fb", None, self.owner_psid, {"text": text})
        else:
            log.warning("[Meta] Chưa cấu hình FB_OWNER_PSID → bỏ qua báo chủ (vẫn rep khách bình thường)")

    def call_owner(self) -> None:
        owner_call.alert()
