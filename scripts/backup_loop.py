#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vòng lặp sao lưu tự động — chạy như service `backup` trong deploy/docker-compose.yml.

Vì sao service riêng thay vì cron trong container app: image không có cron daemon,
và backup nằm CHUNG volume dbdata thì mất disk = mất cả DB lẫn backup. Service này
ghi sang volume RIÊNG (backups:/backups) — mất volume dbdata vẫn còn bản sao.

Chu kỳ: BACKUP_INTERVAL_SECS (mặc định 86400 = hằng ngày). Giữ BACKUP_KEEP bản
(mặc định 14 — xem scripts/backup_db.py). Sao lưu NGAY 1 bản lúc khởi động rồi
mới vào nhịp — deploy xong là có bản đầu tiên, không phải đợi tới đêm.

Offsite (KHUYẾN NGHỊ khi có shop trả tiền): cron trên HOST đẩy /backups lên
cloud, vd rclone:  0 4 * * * docker cp novachat-backup-1:/backups /tmp/nb && rclone sync /tmp/nb remote:novachat-backups
"""

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backup_db import backup, prune, _keep  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backup_loop")

INTERVAL = max(300, int(os.getenv("BACKUP_INTERVAL_SECS", "86400")))
DEST = Path(os.getenv("BACKUP_DIR") or "/backups")
HEARTBEAT = DEST / ".last_success"                 # healthcheck đọc mtime file này
# Offsite: rclone remote (vd "r2:novachat-backups"). Rỗng → chỉ backup local.
RCLONE_REMOTE = os.getenv("BACKUP_RCLONE_REMOTE", "").strip()
ALERT_TG_BOT_TOKEN = os.getenv("ALERT_TG_BOT_TOKEN", "")
ALERT_TG_CHAT_ID = os.getenv("ALERT_TG_CHAT_ID", "")
_last_alert = [0.0]


def _alert(msg: str) -> None:
    """Báo ops qua Telegram khi backup hỏng/offsite lỗi (throttle 5' chống spam)."""
    if not (ALERT_TG_BOT_TOKEN and ALERT_TG_CHAT_ID):
        return
    now = time.time()
    if now - _last_alert[0] < 300:
        return
    _last_alert[0] = now
    try:
        data = json.dumps({"chat_id": ALERT_TG_CHAT_ID,
                           "text": f"⚠️ [NovaChat backup] {msg}"}).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{ALERT_TG_BOT_TOKEN}/sendMessage",
            data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.error(f"Gửi alert Telegram lỗi: {e}")


def _offsite(dest: Path) -> None:
    """Đẩy bản sao lên cloud qua rclone (BACKUP_RCLONE_REMOTE). rclone chưa cài /
    lỗi → log + alert, KHÔNG làm sập vòng backup local (local vẫn có bản)."""
    if not RCLONE_REMOTE:
        return
    try:
        r = subprocess.run(
            ["rclone", "copy", str(dest), RCLONE_REMOTE, "--transfers=2", "--quiet"],
            capture_output=True, text=True, timeout=900)
        if r.returncode != 0:
            log.error(f"rclone offsite lỗi (rc={r.returncode}): {r.stderr[:300]}")
            _alert(f"Đẩy backup offsite THẤT BẠI (rclone rc={r.returncode}) — kiểm tra config/remote.")
        else:
            log.info(f"Offsite OK → {RCLONE_REMOTE}")
    except FileNotFoundError:
        log.error("rclone CHƯA CÀI trong container → không đẩy offsite được")
        _alert("BACKUP_RCLONE_REMOTE đã đặt nhưng rclone CHƯA CÀI → backup KHÔNG được đẩy offsite.")
    except Exception as e:
        log.error(f"rclone offsite lỗi: {e}", exc_info=True)
        _alert(f"Đẩy backup offsite lỗi: {e}")


def run_once() -> bool:
    """1 lượt: backup local (đã tự verify) → heartbeat → prune → offsite.
    Trả True nếu backup local thành công."""
    try:
        out = backup(DEST)                 # backup() đã _verify bản sao
        removed = prune(DEST, _keep())
        HEARTBEAT.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        log.info(f"Đã sao lưu {out.name} ({out.stat().st_size / 1024:,.0f} KB); "
                 f"dọn {len(removed)} bản cũ")
        _offsite(DEST)                     # best-effort, không chặn heartbeat local
        return True
    except SystemExit as e:                # chưa có DB (mới deploy) — bình thường, KHÔNG alert
        log.warning(f"Bỏ qua lượt này: {e}")
        return False
    except Exception as e:                 # backup hỏng / verify fail / I/O — ALERT ops
        log.error(f"Sao lưu lỗi: {e}", exc_info=True)
        _alert(f"SAO LƯU DB THẤT BẠI: {e}")
        return False


def main():
    log.info(f"Backup loop: mỗi {INTERVAL}s → {DEST} (giữ {_keep()} bản)"
             f"{'; offsite → ' + RCLONE_REMOTE if RCLONE_REMOTE else ''}")
    while True:
        run_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
