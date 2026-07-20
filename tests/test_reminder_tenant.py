#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_reminder_tenant.py — nhắc đơn/nhắc việc route ĐÚNG chủ shop (chống lộ PII):
  A. Đơn shop GỐC tới hạn → notify_fn (kênh chat chủ nền tảng) như cũ
  B. Đơn shop THUÊ tới hạn → EMAIL chủ shop đó; notify_fn KHÔNG chứa PII shop thuê
  C. Followups: cùng luật routing
  D. SMTP chưa cấu hình → việc shop thuê vẫn mark reminded (không retry vô hạn),
     và vẫn KHÔNG rơi sang notify_fn
  E. notify_fn lỗi (kênh chủ chết) → KHÔNG mark, vòng sau thử lại (semantics cũ)

Chạy TỪ GỐC: python tests/test_reminder_tenant.py
"""

import os, sys
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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_remtenant_tmp.sqlite')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_remtenant_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime, timedelta
from app.core.db import get_db
from app.core import orders, followups, mailer

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
NOW = datetime.now()
db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at) VALUES ('root@x.vn','x',?)",
           (NOW.isoformat(),))
db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at) VALUES ('spa@x.vn','x',?)",
           (NOW.isoformat(),))

DUE = (NOW + timedelta(hours=2)).isoformat(timespec="minutes")
o_root = orders.create(channel="zalo", user_id="k1", customer_name="Khách Gốc",
                       phone="0901111111", due_at=DUE, tenant="root@x.vn")
o_spa = orders.create(channel="meta", user_id="k2", customer_name="Khách Spa",
                      phone="0902222222", due_at=DUE, tenant="spa@x.vn")

notified, mails = [], []
def notify_fn(text): notified.append(text)
def fake_send(to, subject, body): mails.append((to, subject, body)); return True

print("\n── A+B. Đơn tới hạn route đúng chủ ──")
with patch.object(mailer, "configured", lambda: True), \
     patch.object(mailer, "send_mail", fake_send):
    n = orders.check_and_notify(notify_fn)
check(n == 2, "A0 nhắc đủ 2 đơn", n)
check(any(o_root["code"] in t for t in notified), "A1 đơn shop gốc → kênh chat chủ nền tảng")
check(not any("Khách Spa" in t or "0902222222" in t for t in notified),
      "B1 notify_fn KHÔNG chứa PII shop thuê", notified)
spa_mails = [m for m in mails if m[0] == "spa@x.vn"]
check(spa_mails and "Khách Spa" in spa_mails[0][2] and o_spa["code"] in spa_mails[0][2],
      "B2 chủ spa nhận EMAIL đơn của mình", mails)
check(orders.due_orders() == [], "B3 cả 2 đơn đã mark reminded")

print("\n── C. Followups cùng luật ──")
notified.clear(); mails.clear()
f_root = followups.create("zalo", "k1", "gọi lại khách gốc", NOW.isoformat(timespec="minutes"),
                          tenant="root@x.vn")
f_spa = followups.create("meta", "k2", "chăm lại khách spa", NOW.isoformat(timespec="minutes"),
                         tenant="spa@x.vn")
with patch.object(mailer, "configured", lambda: True), \
     patch.object(mailer, "send_mail", fake_send):
    n = followups.check_and_notify(notify_fn)
check(n == 2, "C0 nhắc đủ 2 việc", n)
check(any("khách gốc" in t for t in notified) and not any("khách spa" in t for t in notified),
      "C1 kênh chat chỉ việc shop gốc", notified)
check(any(m[0] == "spa@x.vn" and "khách spa" in m[2] for m in mails),
      "C2 việc shop thuê đi email chủ spa", mails)

print("\n── D. SMTP chưa cấu hình ──")
notified.clear(); mails.clear()
f2 = followups.create("meta", "k3", "việc khi smtp off", NOW.isoformat(timespec="minutes"),
                      tenant="spa@x.vn")
with patch.object(mailer, "configured", lambda: False):
    n = followups.check_and_notify(notify_fn)
check(n == 1, "D1 vẫn mark (không retry vô hạn)", n)
check(notified == [], "D2 tuyệt đối không rơi sang kênh chủ nền tảng", notified)
check(followups.due_unnotified() == [], "D3 không còn việc treo")

print("\n── E. notify_fn lỗi → giữ semantics retry ──")
o3 = orders.create(channel="zalo", user_id="k4", customer_name="Khách Retry",
                   due_at=DUE, tenant="root@x.vn")
def broken_notify(text): raise RuntimeError("kênh chết")
with patch.object(mailer, "configured", lambda: True), \
     patch.object(mailer, "send_mail", fake_send):
    n = orders.check_and_notify(broken_notify)
check(n == 0, "E1 không đếm đơn nhắc lỗi", n)
check(any(o["id"] == o3["id"] for o in orders.due_orders()), "E2 đơn còn trong hàng chờ retry")

try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_remtenant_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
