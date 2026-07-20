#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_billing_warnings.py — cảnh báo hết hạn gói / hết quota (billing.check_and_warn):
  A. Gói sắp hết hạn (≤3 ngày, gói trả tiền) → email 1 LẦN, gọi lại không nhắc trùng
  B. Gói ĐÃ hết hạn → email "bot đã ngừng" 1 lần
  C. Quota chạm 80% rồi 100% → 2 mốc riêng, mỗi mốc 1 lần
  D. Trial mới tạo (còn 3 ngày) KHÔNG bị nhắc ngay (trial chỉ nhắc khi ≤1 ngày)
  E. notify_fn (kênh chat) CHỈ bắn cho chủ NỀN TẢNG — không lộ sang shop thuê
  F. Lifetime không bao giờ bị nhắc hạn

Chạy TỪ GỐC: python tests/test_billing_warnings.py
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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_billwarn_tmp.sqlite')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_billwarn_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime, timedelta
from app.core.db import get_db
from app.core import billing, mailer

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
NOW = datetime.now()

def add_user(u):
    db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at) VALUES (?, 'x', ?)",
               (u, NOW.isoformat()))
    billing.ensure_billing(u)

# root đăng ký đầu = chủ nền tảng; shop2 là shop thuê
add_user("root@x.vn")
add_user("shop2@x.vn")

sent_mails = []      # (to, subject)
notified = []        # msg qua notify_fn (kênh chat)

def fake_send(to, subject, body):
    sent_mails.append((to, subject))
    return True

def notify_fn(msg):
    notified.append(msg)

mp = patch.object(mailer, "send_mail", fake_send)
mc = patch.object(mailer, "configured", lambda: True)
mp.start(); mc.start()

print("\n── A. Gói trả tiền sắp hết hạn (còn 2 ngày) ──")
exp = (NOW + timedelta(days=2)).isoformat()
db.execute("UPDATE billing SET tier='starter', plan='month', expires_at=? WHERE username='shop2@x.vn'", (exp,))
n = billing.check_and_warn(notify_fn)
subj_shop2 = [s for t, s in sent_mails if t == "shop2@x.vn"]
check(any("còn 2 ngày" in s for s in subj_shop2), "A1 email sắp hết hạn cho shop2", subj_shop2)
sent_before = len(sent_mails)
billing.check_and_warn(notify_fn)
check(len(sent_mails) == sent_before, "A2 gọi lại KHÔNG nhắc trùng")

print("\n── B. Gói đã hết hạn ──")
exp2 = (NOW - timedelta(days=1)).isoformat()
db.execute("UPDATE billing SET expires_at=? WHERE username='shop2@x.vn'", (exp2,))
billing.check_and_warn(notify_fn)
subj_shop2 = [s for t, s in sent_mails if t == "shop2@x.vn"]
check(any("HẾT HẠN" in s for s in subj_shop2), "B1 email bot-đã-ngừng", subj_shop2)
sent_before = len(sent_mails)
billing.check_and_warn(notify_fn)
check(len(sent_mails) == sent_before, "B2 hết hạn chỉ nhắc 1 lần")

print("\n── C. Quota 80% rồi 100% ──")
period = NOW.strftime("%Y-%m")
db.execute("UPDATE billing SET tier='starter', plan='month', lifetime=0, expires_at=?, "
           "ai_used=?, ai_period=? WHERE username='shop2@x.vn'",
           ((NOW + timedelta(days=20)).isoformat(), 5000, period))   # 5000/6000 ≈ 83%
billing.check_and_warn(notify_fn)
subj_shop2 = [s for t, s in sent_mails if t == "shop2@x.vn"]
check(any("83%" in s for s in subj_shop2), "C1 email mốc 80%", subj_shop2)
db.execute("UPDATE billing SET ai_used=6000 WHERE username='shop2@x.vn'")
billing.check_and_warn(notify_fn)
subj_shop2 = [s for t, s in sent_mails if t == "shop2@x.vn"]
check(any("HẾT quota" in s for s in subj_shop2), "C2 email mốc 100% (mốc riêng)", subj_shop2)
sent_before = len(sent_mails)
billing.check_and_warn(notify_fn)
check(len(sent_mails) == sent_before, "C3 mỗi mốc quota 1 lần / kỳ")

print("\n── D. Trial mới (3 ngày) không bị nhắc ngay ──")
check(not any(t == "root@x.vn" and "còn" in s for t, s in sent_mails),
      "D1 root trial 3 ngày chưa bị nhắc", [s for t, s in sent_mails if t == "root@x.vn"])

print("\n── E. notify_fn chỉ cho chủ nền tảng ──")
# shop2 đã nhận nhiều cảnh báo — notify_fn không được chứa cảnh báo của shop2
check(all("shop2" not in m for m in notified), "E1 kênh chat không lộ cảnh báo shop thuê", notified[:2])
# ép root hết hạn → notify_fn PHẢI được gọi (root là chủ nền tảng)
db.execute("UPDATE billing SET tier='starter', plan='month', expires_at=? WHERE username='root@x.vn'",
           ((NOW - timedelta(hours=1)).isoformat(),))
notified.clear()
billing.check_and_warn(notify_fn)
check(len(notified) >= 1, "E2 chủ nền tảng nhận qua kênh chat", notified)

print("\n── F. Lifetime không bị nhắc ──")
db.execute("UPDATE billing SET lifetime=1, expires_at=NULL, ai_used=0 WHERE username='shop2@x.vn'")
sent_before = len(sent_mails)
billing.check_and_warn(notify_fn)
check(len([1 for t, s in sent_mails[sent_before:] if t == "shop2@x.vn"]) == 0,
      "F1 lifetime yên lặng")

mp.stop(); mc.stop()
try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_billwarn_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
