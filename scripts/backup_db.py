#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sao lưu SQLite AN TOÀN bằng sqlite3 .backup() — nhất quán KỂ CẢ khi WAL đang ghi
(khác hẳn cp/tar file .db đang mở có thể ra bản hỏng). Giữ N bản gần nhất.

Chạy tay:   python scripts/backup_db.py [thư_mục_đích]
Cron VPS:   0 3 * * *  cd /app && python scripts/backup_db.py /app/data/backups

.env:  BACKUP_KEEP=14  (số bản giữ lại), BACKUP_DIR (đích mặc định).
"""

import glob
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import Config


def _keep() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_KEEP", "14")))
    except ValueError:
        return 14


def _verify(path: Path) -> None:
    """Mở LẠI bản sao + PRAGMA quick_check + kiểm còn schema — chống 'backup rỗng/
    cụt/hỏng' lọt IM LẶNG (service báo 'đã sao lưu' nhưng file 0 byte). Hỏng → XOÁ
    file rác + raise để caller alert và KHÔNG prune đè lên bản tốt."""
    ok = False
    detail = ""
    try:
        c = sqlite3.connect(str(path))
        try:
            row = c.execute("PRAGMA quick_check").fetchone()
            ok = bool(row) and str(row[0]).strip().lower() == "ok"
            detail = str(row)
            if ok:
                n = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0]
                if n == 0:                 # SQLite hợp lệ nhưng RỖNG (không schema) = hỏng
                    ok, detail = False, "sqlite_master trống (bản rỗng)"
        finally:
            c.close()
    except Exception as e:
        ok, detail = False, str(e)
    if not ok:
        try:
            os.remove(path)
        except OSError:
            pass
        raise RuntimeError(f"Bản sao KHÔNG hợp lệ ({path.name}): {detail}")


def backup(dst_dir: Path) -> Path:
    db_path = Path(Config.DB_PATH)         # tôn trọng HOMESTAY_DB_PATH (không hardcode)
    if not db_path.exists():
        raise SystemExit(f"Không thấy DB: {db_path}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = dst_dir / f"homestay-{stamp}.db"

    src = sqlite3.connect(str(db_path))
    dst = sqlite3.connect(str(out))
    try:
        with dst:
            src.backup(dst)   # copy nhất quán qua WAL
    finally:
        dst.close()
        src.close()
    _verify(out)              # xác minh bản sao mở được + không hỏng (raise nếu hỏng)
    return out


def prune(dst_dir: Path, keep: int) -> list:
    backups = sorted(glob.glob(str(dst_dir / "homestay-*.db")))
    old = backups[:-keep] if len(backups) > keep else []
    for f in old:
        try:
            os.remove(f)
        except OSError:
            pass
    return old


def main():
    dst_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(os.getenv("BACKUP_DIR") or (Config.DATA_DIR / "backups")))
    out = backup(dst_dir)
    size_kb = out.stat().st_size / 1024
    removed = prune(dst_dir, _keep())
    print(f"✅ Đã sao lưu {out} ({size_kb:,.0f} KB); dọn {len(removed)} bản cũ; "
          f"giữ {_keep()} bản gần nhất.")


if __name__ == "__main__":
    main()
