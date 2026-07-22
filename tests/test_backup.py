#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_backup.py — sao lưu SQLite an toàn + offsite + verify (scripts/backup_db.py,
scripts/backup_loop.py):
  A. backup() tạo bản sao HỢP LỆ (mở lại được, còn dữ liệu) qua sqlite .backup()
  B. _verify BẮT bản hỏng/rỗng → raise + XOÁ file rác (không để 'backup rỗng' lọt)
  C. prune giữ đúng N bản mới nhất
  D. _offsite gọi rclone khi có remote; rclone chưa cài → ALERT ops; không remote → skip
  E. run_once ghi heartbeat khi thành công (healthcheck đọc)

Chạy TỪ GỐC: python tests/test_backup.py
"""

import os, sys, types
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_backup_tmp.sqlite')
sys.path.insert(0, '.')

import sqlite3
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_backup_tmp.sqlite{suf}")).unlink(missing_ok=True)

from app.core.db import get_db
from scripts import backup_db, backup_loop

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()   # tạo schema tại HOMESTAY_DB_PATH
db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at) VALUES ('u@x.vn','x','2026')")

BK = _TMPDIR / "bk"
for p in (BK,):
    if p.exists():
        for f in p.glob("*"):
            try: f.unlink()
            except OSError: pass


print("\n── A. backup() bản sao hợp lệ ──")
out = backup_db.backup(BK)
check(out.exists() and out.stat().st_size > 0, "A1 file backup tạo ra", out)
c = sqlite3.connect(str(out))
qc = c.execute("PRAGMA quick_check").fetchone()[0]
nrow = c.execute("SELECT count(*) FROM users").fetchone()[0]
c.close()
check(qc == "ok" and nrow >= 1, "A2 mở lại được + còn dữ liệu (quick_check ok)", (qc, nrow))


print("\n── B. _verify bắt bản hỏng/rỗng ──")
bad = BK / "homestay-99999999-000000.db"
bad.write_text("day khong phai SQLite", encoding="utf-8")
raised = False
try:
    backup_db._verify(bad)
except RuntimeError:
    raised = True
check(raised and not bad.exists(), "B1 bản HỎNG → raise + xoá file rác")

empty = BK / "homestay-99999998-000000.db"
sqlite3.connect(str(empty)).close()   # SQLite hợp lệ nhưng KHÔNG schema
raised = False
try:
    backup_db._verify(empty)
except RuntimeError:
    raised = True
check(raised and not empty.exists(), "B2 bản RỖNG (không schema) → raise + xoá")


print("\n── C. prune giữ N bản mới nhất ──")
PR = _TMPDIR / "pr"
PR.mkdir(exist_ok=True)
for f in PR.glob("*"):
    try: f.unlink()
    except OSError: pass
for i in range(5):
    (PR / f"homestay-2026010{i}-000000.db").write_text("x", encoding="utf-8")
removed = backup_db.prune(PR, 3)
left = sorted(p.name for p in PR.glob("homestay-*.db"))
check(len(removed) == 2 and len(left) == 3, "C1 giữ 3 bản mới, dọn 2 bản cũ", (removed, left))
check(left == ["homestay-20260102-000000.db", "homestay-20260103-000000.db",
               "homestay-20260104-000000.db"], "C2 giữ đúng 3 bản MỚI nhất", left)


print("\n── D. _offsite qua rclone ──")
fake_ok = types.SimpleNamespace(returncode=0, stderr="")
with patch.object(backup_loop, "RCLONE_REMOTE", "r2:novachat-bk"), \
     patch.object(backup_loop.subprocess, "run", return_value=fake_ok) as m_run:
    backup_loop._offsite(BK)
check(m_run.called and m_run.call_args[0][0][:2] == ["rclone", "copy"],
      "D1 có remote → gọi `rclone copy`", m_run.call_args)

with patch.object(backup_loop, "RCLONE_REMOTE", "r2:novachat-bk"), \
     patch.object(backup_loop.subprocess, "run", side_effect=FileNotFoundError()), \
     patch.object(backup_loop, "_alert") as m_alert:
    backup_loop._offsite(BK)
check(m_alert.called, "D2 rclone CHƯA CÀI → alert ops (không sập)")

with patch.object(backup_loop, "RCLONE_REMOTE", ""), \
     patch.object(backup_loop.subprocess, "run") as m_run2:
    backup_loop._offsite(BK)
check(not m_run2.called, "D3 không remote → KHÔNG gọi rclone")

fake_fail = types.SimpleNamespace(returncode=1, stderr="permission denied")
with patch.object(backup_loop, "RCLONE_REMOTE", "r2:novachat-bk"), \
     patch.object(backup_loop.subprocess, "run", return_value=fake_fail), \
     patch.object(backup_loop, "_alert") as m_alert2:
    backup_loop._offsite(BK)
check(m_alert2.called, "D4 rclone lỗi (rc!=0) → alert ops")


print("\n── E. run_once ghi heartbeat khi thành công ──")
HB = BK / ".last_success"
if HB.exists(): HB.unlink()
with patch.object(backup_loop, "DEST", BK), \
     patch.object(backup_loop, "HEARTBEAT", HB), \
     patch.object(backup_loop, "RCLONE_REMOTE", ""):
    ok = backup_loop.run_once()
check(ok and HB.exists(), "E1 backup thành công → ghi heartbeat /backups/.last_success")


try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_backup_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
