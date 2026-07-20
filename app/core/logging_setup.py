"""
Cấu hình logging DÙNG CHUNG cho mọi entry (main_*.py).

Trước đây mỗi entry tự `basicConfig` với FileHandler ghi thẳng bot_*.log ra GỐC
repo, KHÔNG xoay vòng → chạy lâu là phình vô hạn (bot.log từng ~1MB+ nằm ở gốc).
Ở đây dùng RotatingFileHandler (mặc định 5MB/bản × 5 bản) ghi vào DATA_DIR/logs/,
kích thước/số bản chỉnh qua .env (LOG_MAX_BYTES, LOG_BACKUP_COUNT).
"""

import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler

from app.core.config import Config


class TelegramAlertHandler(logging.Handler):
    """Bắn log ERROR trở lên vào Telegram NGƯỜI VẬN HÀNH (không phải chủ shop).

    Vì sao: production không có Sentry/uptime monitor thì lỗi nằm im trong file
    log — 2h sáng container treo, khách nhắn không ai trả lời, không gì reo.
    Cấu hình .env: ALERT_TG_BOT_TOKEN (bot riêng cho ops) + ALERT_TG_CHAT_ID.
    Thiếu 1 trong 2 → handler không được gắn (setup_logging kiểm).

    Chống bão alert: mỗi logger-name tối đa 1 tin / ALERT_THROTTLE_SECS (mặc
    định 300s). Gửi trong thread daemon riêng + tự tắt logging của urllib để
    KHÔNG đệ quy (lỗi gửi alert lại sinh log ERROR)."""

    def __init__(self, token: str, chat_id: str, throttle: int = 300):
        super().__init__(level=logging.ERROR)
        self._token = token
        self._chat_id = chat_id
        self._throttle = max(10, throttle)
        self._last: dict = {}
        self._lock = threading.Lock()

    def emit(self, record):
        try:
            now = time.time()
            with self._lock:
                if now - self._last.get(record.name, 0) < self._throttle:
                    return
                self._last[record.name] = now
            text = (f"🔥 [{record.levelname}] {record.name}\n"
                    f"{self.format(record)[:1500]}")
            threading.Thread(target=self._send, args=(text,), daemon=True).start()
        except Exception:
            pass                     # alert hỏng không được phá luồng chính

    def _send(self, text: str):
        try:
            import json as _json
            import urllib.request
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                data=_json.dumps({"chat_id": self._chat_id, "text": text}).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception:
            pass


def _alert_handler():
    """Dựng TelegramAlertHandler nếu .env có đủ token + chat_id, ngược lại None."""
    token = os.getenv("ALERT_TG_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ALERT_TG_CHAT_ID", "").strip()
    if not (token and chat_id):
        return None
    try:
        throttle = int(os.getenv("ALERT_THROTTLE_SECS", "300"))
    except ValueError:
        throttle = 300
    return TelegramAlertHandler(token, chat_id, throttle)


def setup_logging(logfile: str = "bot.log", level=logging.INFO) -> None:
    """Bật logging stdout + FILE CÓ XOAY VÒNG. Gọi 1 lần ở đầu mỗi entry."""
    path = logfile
    try:
        log_dir = Config.DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / logfile
    except Exception:
        pass  # DATA_DIR lỗi → vẫn ghi cạnh cwd, đừng chặn khởi động

    try:
        max_bytes = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
    except ValueError:
        max_bytes = 5 * 1024 * 1024
    try:
        backups = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    except ValueError:
        backups = 5

    handlers = [logging.StreamHandler()]
    try:
        handlers.append(RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backups, encoding="utf-8"))
    except Exception as e:
        # Không mở được file (quyền/đĩa đầy) → vẫn log ra stdout, không chết
        print(f"[logging_setup] không mở được file log {path}: {e}")

    alert = _alert_handler()
    if alert is not None:
        handlers.append(alert)
        print("[logging_setup] alert ERROR → Telegram ops: BẬT")

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,   # ghi đè handler cũ nếu module được nạp lại
    )
