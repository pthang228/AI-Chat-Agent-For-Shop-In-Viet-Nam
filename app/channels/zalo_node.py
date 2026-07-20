"""
Kênh Zalo qua Node service (zca-js) — cài đặt giao diện Channel bằng cách
gọi HTTP tới service Node ở zalo-node/ (cổng 4000).

Brain ra lệnh → ZaloNodeChannel POST sang Node → zca-js gửi tin Zalo thật.
Chiều ngược lại (Node nhận tin khách → Python) do bridge.py xử lý.
"""

import logging
import time
from pathlib import Path

import requests

from app.core.config import Config
from app.core.channel import Channel, LEGACY_ROOM_SETS
from app.core.http_util import post_with_retry
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5


class ZaloNodeChannel(Channel):
    """MULTI-ACCOUNT: mỗi shop 1 acc Zalo riêng trên Node service.
    user_id 2 dạng: uid TRẦN (số — acc 'default' của chủ nền tảng, tương thích
    dữ liệu cũ) hoặc 'zl:<accId>:<uid>' (acc của shop thuê)."""

    def __init__(self, node_url: str = "http://127.0.0.1:4000", conv_manager=None):
        self.node_url = node_url.rstrip("/")
        self.conv_manager = conv_manager
        self.brain = None   # main_node.py gán Brain sau
        self._recent_bot_sends: dict[str, list[tuple[float, str]]] = {}
        import threading as _th
        self._ctx = _th.local()   # accId đang xử lý — notify_owner báo đúng shop

    # ── Multi-account helpers ─────────────────────────────────────

    @staticmethod
    def _parse(user_id: str):
        """'zl:<acc>:<uid>' → (acc, uid); uid trần → ('default', uid)."""
        s = str(user_id or "")
        if s.startswith("zl:"):
            parts = s.split(":", 2)
            if len(parts) == 3 and parts[1]:
                return parts[1], parts[2]
        return "default", s

    def set_ctx(self, acc):
        self._ctx.acc = acc or None

    def get_ctx(self):
        return getattr(self._ctx, "acc", None)

    # ── Gọi Node ──────────────────────────────────────────────────

    def _post(self, path: str, payload: dict):
        # BẢO MẬT: Node :4000 có thể khoá bằng NODE_API_KEY → gửi kèm header
        # X-Node-Key. Không đặt key → KHÔNG truyền kwarg headers (giữ nguyên
        # chữ ký gọi cũ cho dev/test đang mock requests.post).
        kw = {}
        if Config.ZALO_NODE_API_KEY:
            kw["headers"] = {"X-Node-Key": Config.ZALO_NODE_API_KEY}
        r = post_with_retry(f"{self.node_url}{path}", json=payload, timeout=60,
                            retries=Config.SEND_RETRIES, log_tag=f"Node {path}", **kw)
        if r is None:
            return None
        if r.status_code >= 400:
            log.error(f"[Node] {path} → {r.status_code} {r.text[:200]}")
        return r

    # ── Giao diện Channel ─────────────────────────────────────────

    @staticmethod
    def _norm_text(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    def _mark_bot_send(self, user_id: str, text: str = "") -> None:
        now = time.time()
        key = str(user_id)
        rows = [
            (ts, msg)
            for ts, msg in self._recent_bot_sends.get(key, [])
            if now - ts < 180
        ]
        rows.append((now, self._norm_text(text)))
        self._recent_bot_sends[key] = rows[-20:]

    def is_recent_bot_echo(self, user_id: str, text: str = "", window: int = 180) -> bool:
        now = time.time()
        incoming = self._norm_text(text)
        rows = []
        matched = False
        for ts, msg in self._recent_bot_sends.get(str(user_id), []):
            if now - ts >= window:
                continue
            rows.append((ts, msg))
            if not incoming or msg == incoming:
                matched = True
        self._recent_bot_sends[str(user_id)] = rows
        return matched

    def send_text(self, user_id: str, text: str) -> None:
        MAX_LEN = 2000
        acc, zuid = self._parse(user_id)
        for i in range(0, len(text), MAX_LEN):
            chunk = text[i:i + MAX_LEN]
            self._mark_bot_send(user_id, chunk)
            self._post("/send", {"acc": acc, "userId": zuid, "text": chunk})

    def _send_dir(self, user_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            str(f.resolve()) for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        if not photos:
            return False
        acc, zuid = self._parse(user_id)
        self.send_text(user_id, caption)
        self._mark_bot_send(user_id)
        self._post("/send-image", {"acc": acc, "userId": zuid, "paths": photos})
        return True

    def send_photo_folder(self, user_id: str, folder, caption: str) -> bool:
        return self._send_dir(user_id, Path(folder), caption)

    def send_file(self, user_id: str, path, url: str, kind: str, caption: str = "") -> bool:
        """Zalo Node đọc file LOCAL trực tiếp (KHÔNG tải qua URL/tunnel — tunnel
        hay chết + Node cùng máy). Ảnh: gửi thật qua /send-image. Video/ghi âm:
        zca-js/Node chưa hỗ trợ gửi file → trả False (chat_tools báo rõ)."""
        if kind == "image":
            try:
                acc, zuid = self._parse(user_id)
                if caption:
                    self.send_text(user_id, caption)
                self._mark_bot_send(user_id)
                self._post("/send-image", {"acc": acc, "userId": zuid,
                                           "paths": [str(Path(path).resolve())]})
                return True
            except Exception as e:
                log.error(f"[ZaloNode] send_file ảnh lỗi: {e}")
                return False
        return False   # Zalo cá nhân chưa gửi được video/ghi âm

    def send_image_url(self, user_id: str, url: str, caption: str = "") -> None:
        # Node /send-image chỉ nhận path local → tải ảnh về file tạm rồi gửi;
        # tải lỗi → fallback gửi text kèm link (Zalo hiện preview).
        try:
            import requests as _rq
            r = _rq.get(url, timeout=15)
            r.raise_for_status()
            tmp_dir = Config.DATA_DIR / "qr_tmp"
            tmp_dir.mkdir(exist_ok=True)
            f = tmp_dir / f"img_{abs(hash(url)) % 10**8}.png"
            f.write_bytes(r.content)
            acc, zuid = self._parse(user_id)
            if caption:
                self.send_text(user_id, caption)
            self._mark_bot_send(user_id)
            self._post("/send-image", {"acc": acc, "userId": zuid, "paths": [str(f.resolve())]})
        except Exception as e:
            log.error(f"[ZaloNode] send_image_url lỗi ({e}) → gửi link")
            self.send_text(user_id, (caption + "\n" if caption else "") + url)

    def send_room_photos(self, user_id: str, room_names: list[str]) -> None:
        base = Path(Config.ROOMS_PHOTOS_DIR)
        sent = False
        for phong in room_names:
            so_phong = phong.strip().split()[-1]
            if self._send_dir(user_id, base / so_phong, f"📸 Ảnh {phong}:"):
                sent = True
        if not sent:
            self.send_text(
                user_id,
                "📷 Ảnh phòng đang được cập nhật. Bạn muốn mình mô tả chi tiết hơn không?",
            )

    def send_price_photos(self, user_id: str) -> None:
        base = Path(Config.PRICE_PHOTOS_DIR)
        sent = False
        for folder_name, label in LEGACY_ROOM_SETS:
            if self._send_dir(user_id, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self.send_text(
                user_id,
                "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!",
            )

    def notify_owner(self, text: str) -> None:
        """
        Báo chủ SHOP đang xử lý (ctx acc — bridge set trước brain.handle). Node
        gửi tới nhóm/chủ mà shop đã CHỌN TRONG GIAO DIỆN (node-config per acc).
        Chưa chọn → Node trả 400, bỏ qua (không chặn việc trả lời khách).
        """
        acc = self.get_ctx() or "default"
        r = self._post("/notify-owner", {"acc": acc, "text": text})
        if r is not None and r.status_code == 400:
            log.warning(f"[Node][{acc}] Chưa chọn nhóm nhận thông báo → bỏ qua báo chủ")

    def call_owner(self) -> None:
        # Telethon gọi điện là session GLOBAL của CHỦ NỀN TẢNG — chỉ gọi khi hội
        # thoại thuộc acc default; shop thuê dùng notify (nhắn nhóm) là chính.
        if (self.get_ctx() or "default") == "default":
            owner_call.alert()
