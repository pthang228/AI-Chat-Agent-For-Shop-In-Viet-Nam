#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_latency.py — ĐO THỜI GIAN PHẢN HỒI (biểu đồ Thống kê):
  A. latency.record/stats: avg + P95 tổng & theo ngày, lọc from/to + tenant,
     outlier > MAX_SECONDS bỏ, cleanup theo retention
  B. stats_util timeline có user/bot theo ngày (nuôi "Tỷ lệ AI trả lời" thật)

Chạy TỪ GỐC: python tests/test_latency.py  (PYTHONIOENCODING=utf-8)
"""

import os, sys
from unittest.mock import MagicMock

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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_latency_tmp.sqlite')
sys.path.insert(0, '.')
for suf in ("", "-wal", "-shm"):
    _P(str(_TMPDIR / f"test_db_latency_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime, timedelta
from app.core.db import get_db
from app.core import latency

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
YESTER = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")

# ── A. record + stats ────────────────────────────────────────────────
print("A. record + stats")
for s in (2.0, 4.0, 6.0):
    latency.record("shopA@x.vn", s)
latency.record("shopB@x.vn", 30.0)          # shop khác — không được lẫn
latency.record("shopA@x.vn", 9999)          # outlier > MAX_SECONDS → bỏ
latency.record("shopA@x.vn", 0)             # 0/âm → bỏ
# 1 dòng hôm qua (sửa created_at tay để test timeline + from/to)
db.execute("INSERT INTO latency_log (tenant, seconds, created_at) VALUES (?,?,?)",
           ("shopA@x.vn", 10.0, (NOW - timedelta(days=1)).isoformat()))

st = latency.stats(tenant_ws="shopA@x.vn")
check(st["n"] == 4, "A1 đếm đúng 4 lượt (outlier + 0 bị bỏ, shopB không lẫn)", st)
check(st["avg"] == round((2 + 4 + 6 + 10) / 4, 2), "A2 avg đúng", st["avg"])
days = {t["date"]: t for t in st["timeline"]}
check(TODAY in days and days[TODAY]["n"] == 3 and days[TODAY]["avg"] == 4.0,
      "A3 timeline hôm nay: 3 lượt avg 4s", days.get(TODAY))
check(YESTER in days and days[YESTER]["avg"] == 10.0, "A4 timeline hôm qua 10s", days.get(YESTER))

st = latency.stats(from_s=TODAY, to_s=TODAY, tenant_ws="shopA@x.vn")
check(st["n"] == 3 and len(st["timeline"]) == 1, "A5 lọc from/to chỉ còn hôm nay", st)
st_b = latency.stats(tenant_ws="shopB@x.vn")
check(st_b["n"] == 1 and st_b["avg"] == 30.0, "A6 shopB thấy đúng của mình", st_b)

# P95: 20 giá trị 1..20 → p95 = giá trị thứ int(0.95*19)=18 (0-index) = 19
db.execute("DELETE FROM latency_log")
for i in range(1, 21):
    latency.record("shopA@x.vn", float(i))
st = latency.stats(tenant_ws="shopA@x.vn")
check(st["p95"] == 19.0, "A7 P95 đúng công thức", st["p95"])

# cleanup: dòng 100 ngày trước bị dọn khi gọi stats
db.execute("INSERT INTO latency_log (tenant, seconds, created_at) VALUES (?,?,?)",
           ("shopA@x.vn", 5.0, (NOW - timedelta(days=100)).isoformat()))
latency.stats(tenant_ws="shopA@x.vn")
old = db.query("SELECT COUNT(*) n FROM latency_log WHERE created_at < ?",
               ((NOW - timedelta(days=95)).isoformat(),))[0]["n"]
check(old == 0, "A8 log quá hạn 90 ngày tự dọn", old)

# ── B. stats_util timeline user/bot ──────────────────────────────────
print("B. stats_util timeline user/bot")
from app.web_api.stats_util import compute_stats

class FakeConv:
    def __init__(self, msgs, day_offset=0, stage="greeting", tenant=""):
        self.messages = msgs
        self.stage = stage
        self.tenant = tenant
        self.last_updated = NOW - timedelta(days=day_offset)
        self.checkin = self.checkout = self.selected_room = None

class FakeCM:
    def __init__(self, sessions): self._sessions = sessions

cm = FakeCM({
    "u1": FakeConv([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                    {"role": "user", "content": "c"}]),
    "u2": FakeConv([{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
                   day_offset=1),
})
out = compute_stats(cm)
tl = {t["date"]: t for t in out["timeline"]}
check(tl[TODAY]["user"] == 2 and tl[TODAY]["bot"] == 1,
      "B1 timeline hôm nay user=2 bot=1", tl.get(TODAY))
check(tl[YESTER]["user"] == 1 and tl[YESTER]["bot"] == 1,
      "B2 timeline hôm qua user=1 bot=1", tl.get(YESTER))
check(out["user_msg"] == 3 and out["bot_msg"] == 2, "B3 tổng user/bot giữ nguyên hành vi cũ")

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
