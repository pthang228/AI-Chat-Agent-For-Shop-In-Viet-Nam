#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_shop_sheets.py — LỊCH ĐẶT CHỖ per-shop (Google Sheets):
  A. extract_sheet_id: bóc ID từ link (hoặc nhận thẳng ID)
  B. API /sheets: CRUD + cách ly tenant + không token 401
  C. homestays_for + format_availability_for_ai: shop chưa nối → [KHONG_CO_SHEET],
     shop thường KHÔNG dính sheet .env legacy của shop gốc

Chạy TỪ GỐC: python -m tests.test_shop_sheets
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
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_shop_sheets_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '1'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_shop_sheets_tmp.sqlite{suf}")).unlink(missing_ok=True)

from flask import Flask
from app.web_api.auth_api import register_auth_routes
from app.web_api.sheets_api import register_sheets_routes
from app.core import sheets as sh

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


print("A. extract_sheet_id")
LONG_ID = "1AbC-xYz_0123456789abcdefghij"
check(sh.extract_sheet_id(
    f"https://docs.google.com/spreadsheets/d/{LONG_ID}/edit#gid=0") == LONG_ID,
    "A1 bóc ID từ link đầy đủ")
check(sh.extract_sheet_id(LONG_ID) == LONG_ID, "A2 nhận thẳng ID")
check(sh.extract_sheet_id("https://example.com/khong-phai-sheet") is None, "A3 link lạ → None")
check(sh.extract_sheet_id("") is None, "A4 rỗng → None")
check(sh.extract_sheet_id("id ngắn") is None, "A5 chuỗi rác → None")


# App: auth (đăng ký 2 shop) + sheets API
app = Flask(__name__)
register_auth_routes(app)
register_sheets_routes(app)
c = app.test_client()

r = c.post("/auth/register", json={"username": "shopa@x.vn", "password": "1234", "homestay": "Shop A"})
HA = {"Authorization": f"Bearer {r.json['token']}"}
r = c.post("/auth/register", json={"username": "shopb@x.vn", "password": "1234", "homestay": "Shop B"})
HB = {"Authorization": f"Bearer {r.json['token']}"}

SHEET_B = "1SheetShopB_0123456789abcdef"
LINK_B = f"https://docs.google.com/spreadsheets/d/{SHEET_B}/edit?usp=sharing"

print("B. API /sheets — CRUD + cách ly tenant")
r = c.get("/sheets", headers=HB)
check(r.status_code == 200 and r.json["sheets"] == [], "B1 list rỗng ban đầu", r.text[:80])
r = c.post("/sheets", headers=HB, json={"name": "Cơ sở 1", "link": LINK_B})
check(r.status_code == 200 and r.json["sheet"]["sheet_id"] == SHEET_B,
      "B2 dán link → tự bóc ID", r.text[:120])
r = c.post("/sheets", headers=HB, json={"name": "Trùng", "link": LINK_B})
check(r.status_code == 409, "B3 sheet trùng → 409")
r = c.post("/sheets", headers=HB, json={"name": "X", "link": "link-rác-abc"})
check(r.status_code == 400, "B4 link rác → 400")
r = c.get("/sheets", headers=HA)
check(r.status_code == 200 and r.json["sheets"] == [], "B5 shop A KHÔNG thấy sheet shop B")
r = c.get("/sheets", headers=HB)
sid_b = r.json["sheets"][0]["id"]
r = c.delete(f"/sheets/{sid_b}", headers=HA)
check(r.status_code == 404, "B6 A xoá sheet của B → 404")
r = c.get("/sheets")
check(r.status_code == 401, "B7 không token → 401")

print("C. homestays_for + [KHONG_CO_SHEET]")
hs_b = sh.homestays_for("shopb@x.vn")
check(len(hs_b) == 1 and hs_b[0]["sheet_id"] == SHEET_B, "C1 shop B thấy sheet mình", hs_b)
check(sh.homestays_for("shopc@x.vn") == [], "C2 shop chưa khai → rỗng")
out = sh.format_availability_for_ai("25/12/2026", "25/12/2026", tenant="shopc@x.vn")
check("[KHONG_CO_SHEET]" in out, "C3 chưa nối sheet → [KHONG_CO_SHEET]", out[:80])
# Shop gốc gộp sheet .env legacy; shop thường thì KHÔNG
orig = sh.HOMESTAYS
sh.HOMESTAYS = [{"name": "Legacy", "sheet_id": "legacy_id_0123456789abcdef"}]
try:
    hs_root = sh.homestays_for(None)
    check(any(h["sheet_id"] == "legacy_id_0123456789abcdef" for h in hs_root),
          "C4 shop gốc gộp sheet .env legacy", hs_root)
    hs_b2 = sh.homestays_for("shopb@x.vn")
    check(all(h["sheet_id"] != "legacy_id_0123456789abcdef" for h in hs_b2),
          "C5 shop thường KHÔNG dính sheet legacy của shop gốc", hs_b2)
finally:
    sh.HOMESTAYS = orig
# Xoá sheet B → B cũng thành [KHONG_CO_SHEET]
r = c.delete(f"/sheets/{sid_b}", headers=HB)
check(r.status_code == 200, "C6 B xoá sheet mình → 200")
out = sh.format_availability_for_ai("25/12/2026", "25/12/2026", tenant="shopb@x.vn")
check("[KHONG_CO_SHEET]" in out, "C7 xoá hết sheet → lại [KHONG_CO_SHEET]")

# dọn file tạm
try:
    from app.core.db import get_db
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_shop_sheets_tmp.sqlite{suf}")).unlink(missing_ok=True)

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
