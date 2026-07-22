#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_booking_holds.py — hold giữ chỗ chống double-booking (app/core/booking_holds.py):
  A. place + conflicting: khách KHÁC cùng ngày → tranh chấp; chính mình → không
  B. Cách ly tenant: shop khác cùng ngày → không tranh chấp
  C. Phòng: khác phòng rõ ràng 2 phía → không tranh chấp; thiếu 1 phía → có
  D. Range ngày giao nhau (20-22 vs 21) → tranh chấp; rời nhau → không
  E. Hết hạn: hold quá hạn không chặn + được cleanup dọn
  F. place lại của cùng khách → thay hold cũ (đổi ngày không để rác)
  G. release nhả hold

Chạy TỪ GỐC: python tests/test_booking_holds.py
"""

import os, sys
from unittest.mock import MagicMock
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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_holds_tmp.sqlite')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_holds_tmp.sqlite{suf}")).unlink(missing_ok=True)

from app.core import booking_holds as bh
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

T = "shop@x.vn"

print("\n── A. place + conflicting cơ bản ──")
bh.place_hold(T, "khach1", "20/07/2026")
c = bh.conflicting_holds(T, "khach2", "20/07/2026")
check(len(c) == 1 and c[0]["user_id"] == "khach1", "A1 khách khác cùng ngày → tranh chấp", c)
check(bh.conflicting_holds(T, "khach1", "20/07/2026") == [], "A2 chính mình → không tự chặn")
check(bh.conflicting_holds(T, "khach2", "25/07/2026") == [], "A3 ngày khác → không tranh chấp")

print("\n── B. Cách ly tenant ──")
check(bh.conflicting_holds("shopkhac@x.vn", "khach2", "20/07/2026") == [],
      "B1 shop khác cùng ngày → không dính hold shop này")

print("\n── C. Phòng ──")
bh.place_hold(T, "khach3", "01/08/2026", room="201")
check(bh.conflicting_holds(T, "khach4", "01/08/2026", room="301") == [],
      "C1 khác phòng rõ ràng 2 phía → không tranh chấp")
check(len(bh.conflicting_holds(T, "khach4", "01/08/2026", room="201")) == 1,
      "C2 cùng phòng → tranh chấp")
check(len(bh.conflicting_holds(T, "khach4", "01/08/2026")) == 1,
      "C3 khách mới không rõ phòng → tính tranh chấp (bảo thủ)")

print("\n── D. Range ngày giao nhau ──")
bh.place_hold(T, "khach5", "20/08/2026", "22/08/2026")
check(len(bh.conflicting_holds(T, "khach6", "21/08/2026")) == 1, "D1 ngày nằm trong range → tranh chấp")
check(bh.conflicting_holds(T, "khach6", "23/08/2026") == [], "D2 ngoài range → không")
check(len(bh.conflicting_holds(T, "khach6", "18/08/2026", "20/08/2026")) == 1,
      "D3 range chạm mép → tranh chấp")

print("\n── E. Hết hạn + cleanup ──")
bh.place_hold(T, "khach7", "05/09/2026", minutes=-1)   # đã hết hạn ngay
check(bh.conflicting_holds(T, "khach8", "05/09/2026") == [], "E1 hold hết hạn không chặn")
n = get_db().query("SELECT count(*) c FROM booking_holds WHERE user_id='khach7'")[0]["c"]
check(n == 0, "E2 cleanup đã dọn hold hết hạn", n)

print("\n── F. place lại thay hold cũ ──")
bh.place_hold(T, "khach9", "10/09/2026")
bh.place_hold(T, "khach9", "11/09/2026")   # khách đổi ngày
check(bh.conflicting_holds(T, "khachA", "10/09/2026") == [], "F1 ngày cũ được nhả")
check(len(bh.conflicting_holds(T, "khachA", "11/09/2026")) == 1, "F2 ngày mới đang giữ")
n = get_db().query("SELECT count(*) c FROM booking_holds WHERE user_id='khach9'")[0]["c"]
check(n == 1, "F3 mỗi khách tối đa 1 hold", n)

print("\n── G. release ──")
bh.release(T, "khach9")
check(bh.conflicting_holds(T, "khachA", "11/09/2026") == [], "G1 release nhả hold")

print("\n── H. try_place_hold ATOMIC: race 2 CONNECTION (mô phỏng 2 tiến trình) ──")
# H1 tuần tự: đặt được → tranh chấp thì KHÔNG đặt chồng
r1 = bh.try_place_hold(T, "atk1", "01/12/2026")
check(r1 == [], "H1 khách đầu đặt hold OK", r1)
r2 = bh.try_place_hold(T, "atk2", "01/12/2026")
check(len(r2) == 1 and r2[0]["user_id"] == "atk1", "H2 khách sau bị chặn (không đặt chồng)", r2)
n = get_db().query("SELECT count(*) c FROM booking_holds WHERE checkin='01/12/2026'")[0]["c"]
check(n == 1, "H3 chỉ 1 hold tồn tại", n)

# H4 RACE THẬT: 2 Db connection riêng (như 2 tiến trình kênh) cùng chốt 1 ca.
# BEGIN IMMEDIATE phải serialize → đúng 1 thắng, 1 bị chặn, DB chỉ 1 hold.
import threading
from app.core.db import Db
_PATH = os.environ['HOMESTAY_DB_PATH']
dbA, dbB = Db(_PATH), Db(_PATH)
results = {}
barrier = threading.Barrier(2)
def _worker(name, dbx):
    try:
        barrier.wait()
        results[name] = bh.try_place_hold(T, f"race_{name}", "15/12/2026", db=dbx)
    except Exception as e:
        results[name] = f"ERR:{e}"
tA = threading.Thread(target=_worker, args=("A", dbA))
tB = threading.Thread(target=_worker, args=("B", dbB))
tA.start(); tB.start(); tA.join(); tB.join()
placed = [k for k, v in results.items() if v == []]
blocked = [k for k, v in results.items() if isinstance(v, list) and v]
check(len(placed) == 1 and len(blocked) == 1,
      "H4 race 2 connection: đúng 1 đặt được, 1 bị chặn", results)
n = get_db().query("SELECT count(*) c FROM booking_holds WHERE checkin='15/12/2026'")[0]["c"]
check(n == 1, "H5 sau race DB chỉ còn 1 hold (không double-book)", n)
for _d in (dbA, dbB):
    try: _d.conn.close()
    except Exception: pass

try:
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_holds_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
