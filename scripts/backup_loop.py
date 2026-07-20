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

import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.backup_db import backup, prune, _keep  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backup_loop")

INTERVAL = max(300, int(os.getenv("BACKUP_INTERVAL_SECS", "86400")))
DEST = Path(os.getenv("BACKUP_DIR") or "/backups")


def main():
    log.info(f"Backup loop: mỗi {INTERVAL}s → {DEST} (giữ {_keep()} bản)")
    while True:
        try:
            out = backup(DEST)
            removed = prune(DEST, _keep())
            log.info(f"Đã sao lưu {out.name} ({out.stat().st_size / 1024:,.0f} KB); "
                     f"dọn {len(removed)} bản cũ")
        except SystemExit as e:      # backup_db raise SystemExit khi chưa có DB
            log.warning(f"Bỏ qua lượt này: {e}")
        except Exception as e:
            log.error(f"Sao lưu lỗi: {e}", exc_info=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
