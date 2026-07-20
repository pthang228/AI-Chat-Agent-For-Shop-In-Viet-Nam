#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tenant_brain.py — não bot tenant-hoá (không rò nghiệp vụ homestay gốc):
  A. Greeting: shop GỐC giữ kịch bản homestay; shop THUÊ nhận bản trung tính
     (không 'còn phòng không', chèn tên shop)
  B. apply_intent_overrides: '301'/'haru' chỉ override cho shop gốc;
     khách shop thuê nhắn '301' KHÔNG bị ép photo_request
  C. Tương thích: snapshot không truyền is_default → hành vi cũ (test cũ không vỡ)

Chạy TỪ GỐC: python tests/test_tenant_brain.py
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
os.environ.setdefault('REPLY_DELAY', '0')
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tenantbrain_tmp.sqlite')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_tenantbrain_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime
from app.core.db import get_db
from app.core import brain as br

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
NOW = datetime.now().isoformat()
db.execute("INSERT OR IGNORE INTO users(username, password_hash, homestay, created_at)"
           " VALUES ('root@x.vn', 'x', 'Homestay Gốc', ?)", (NOW,))
db.execute("INSERT OR IGNORE INTO users(username, password_hash, homestay, created_at)"
           " VALUES ('nail@x.vn', 'x', 'Nail Xinh', ?)", (NOW,))

class FakeConv:
    def __init__(self, tenant): self.tenant = tenant

print("\n── A. Greeting theo tenant ──")
g_root = br._greeting_for(FakeConv(""))            # tenant rỗng = shop gốc
check(g_root == br.FIRST_MESSAGE_GREETING, "A1 shop gốc giữ kịch bản homestay")
g_root2 = br._greeting_for(FakeConv("root@x.vn"))   # tenant = default_owner
check(g_root2 == br.FIRST_MESSAGE_GREETING, "A2 tenant=chủ nền tảng → như shop gốc")
g_nail = br._greeting_for(FakeConv("nail@x.vn"))
check("còn phòng" not in g_nail and "đặt phòng" not in g_nail,
      "A3 shop thuê KHÔNG nhận kịch bản homestay", g_nail[:80])
check("Nail Xinh" in g_nail, "A4 greeting chèn tên shop", g_nail[:80])

print("\n── B. Override đặc thù shop gốc bị gate theo tenant ──")
ai_other = {"intent": "other", "use_ai_reply": False, "reply": ""}
snap_default = {"stage": "greeting", "checkin": None, "selected_room": None, "is_default": True}
snap_tenant  = {"stage": "greeting", "checkin": None, "selected_room": None, "is_default": False}

it, _ = br.apply_intent_overrides("cho xin ảnh 301", dict(ai_other), dict(snap_default))
check(it == "photo_request", "B1 shop gốc: '301' + xin ảnh → photo_request", it)
it, _ = br.apply_intent_overrides("cho xin ảnh 301", dict(ai_other), dict(snap_tenant))
check(it != "photo_request", "B2 shop thuê: '301' KHÔNG bị ép photo_request", it)
it, _ = br.apply_intent_overrides("giá haru nhiêu", dict(ai_other), dict(snap_default))
check(it != "other", "B3 shop gốc: 'haru' vẫn được override", it)
it, _ = br.apply_intent_overrides("ảnh haru đi", dict(ai_other), dict(snap_tenant))
check(it != "photo_request", "B4 shop thuê: 'haru' không kích override ảnh homestay", it)
# nghiệp vụ CHUNG (lịch trống theo Sheets per-tenant) vẫn hoạt động cho shop thuê
it, _ = br.apply_intent_overrides("tối nay còn chỗ không", dict(ai_other), dict(snap_tenant))
check(it == "availability_check", "B5 shop thuê: hỏi lịch chung vẫn override", it)

print("\n── C. Tương thích snapshot cũ (không truyền is_default) ──")
it, _ = br.apply_intent_overrides("cho xin ảnh 301", dict(ai_other),
                                  {"stage": "greeting", "checkin": None, "selected_room": None})
check(it == "photo_request", "C1 thiếu is_default → mặc định True (hành vi cũ)", it)

try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_tenantbrain_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
