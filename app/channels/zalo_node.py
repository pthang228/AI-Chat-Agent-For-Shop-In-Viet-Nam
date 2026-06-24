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
from app.core.channel import Channel
from app.core import owner_call

log = logging.getLogger(__name__)

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS_PER_ROOM = 5


class ZaloNodeChannel(Channel):

    def __init__(self, node_url: str = "http://127.0.0.1:4000", conv_manager=None):
        self.node_url = node_url.rstrip("/")
        self.conv_manager = conv_manager
        self.brain = None   # main_node.py gán Brain sau
        self._recent_bot_sends: dict[str, list[tuple[float, str]]] = {}

    # ── Gọi Node ──────────────────────────────────────────────────

    def _post(self, path: str, payload: dict):
        try:
            r = requests.post(f"{self.node_url}{path}", json=payload, timeout=60)
            if r.status_code >= 400:
                log.error(f"[Node] {path} → {r.status_code} {r.text[:200]}")
            return r
        except Exception as e:
            log.error(f"[Node] gọi {path} lỗi: {e}")
            return None

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
        for i in range(0, len(text), MAX_LEN):
            chunk = text[i:i + MAX_LEN]
            self._mark_bot_send(user_id, chunk)
            self._post("/send", {"userId": user_id, "text": chunk})

    def _send_dir(self, user_id: str, folder: Path, caption: str) -> bool:
        if not folder.is_dir():
            return False
        photos = sorted(
            str(f.resolve()) for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )[:MAX_PHOTOS_PER_ROOM]
        if not photos:
            return False
        self.send_text(user_id, caption)
        self._mark_bot_send(user_id)
        self._post("/send-image", {"userId": user_id, "paths": photos})
        return True

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
        for folder_name, label in [("haru", "Haru Staycation"), ("mochi", "Mochi Home")]:
            if self._send_dir(user_id, base / folder_name, f"📋 Bảng giá {label}:"):
                sent = True
        if not sent:
            self.send_text(
                user_id,
                "📋 Bảng giá đang được cập nhật. Bạn có thể hỏi mình giá từng phòng nhé!",
            )

    def notify_owner(self, text: str) -> None:
        """
        Báo chủ nhà. Node tự gửi tới nhóm/chủ mà người dùng đã CHỌN TRONG GIAO DIỆN
        (lưu ở node-config.json). Nếu chưa chọn, Node trả 400 và bỏ qua (không chặn
        việc trả lời khách).
        """
        r = self._post("/notify-owner", {"text": text})
        if r is not None and r.status_code == 400:
            log.warning("[Node] Chưa chọn nhóm nhận thông báo trong giao diện → bỏ qua báo chủ")

    def call_owner(self) -> None:
        owner_call.alert()
