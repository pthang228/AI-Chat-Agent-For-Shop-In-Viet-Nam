#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai_usage_log.py — sổ giá vốn LLM per shop (billing.ai_usage_log):
  A. Lượt TRONG quota: ghi log billed=0, KHÔNG trừ ví
  B. Lượt VƯỢT quota + usage bật: ghi log billed=1, TRỪ ví đúng cost
  C. ai_costs_by_shop: gộp theo shop + kèm giá gói tháng để soi lỗ
  D. Route /admin/ai-costs: admin xem được, shop thường 403

Chạy TỪ GỐC: python tests/test_ai_usage_log.py
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
os.environ['AI_PRICE_MARKUP'] = '1.0'    # cost dự đoán được trong test
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_usagelog_tmp.sqlite')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_usagelog_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime
from flask import Flask
from app.core.db import get_db
from app.core import billing
from app.web_api.auth_api import register_auth_routes
from app.web_api.admin_api import register_admin_routes

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()

app = Flask(__name__)
register_auth_routes(app)
register_admin_routes(app)
cli = app.test_client()
r = cli.post("/auth/register", json={"username": "root@x.vn", "password": "1234", "homestay": "NT"})
TOK_ROOT = r.json["token"]
r = cli.post("/auth/register", json={"username": "shop@x.vn", "password": "1234", "homestay": "S"})
TOK_SHOP = r.json["token"]

print("\n── A. Trong quota: log billed=0, không trừ ví ──")
db.execute("UPDATE billing SET balance=100000 WHERE username='shop@x.vn'")
billing.record_token_usage("shop@x.vn", "deepseek-chat", 100_000, 10_000)
rows = db.query("SELECT * FROM ai_usage_log WHERE username='shop@x.vn'")
check(len(rows) == 1 and rows[0]["billed"] == 0, "A1 lượt trong quota được ghi log", [dict(r) for r in rows])
check(rows[0]["cost_vnd"] > 0 and rows[0]["tokens_in"] == 100_000, "A2 cost + token đúng", dict(rows[0]))
bal = db.query("SELECT balance FROM billing WHERE username='shop@x.vn'")[0]["balance"]
check(bal == 100000, "A3 ví không bị trừ", bal)

print("\n── B. Vượt quota + usage bật: billed=1, trừ ví ──")
period = datetime.now().strftime("%Y-%m")
db.execute("UPDATE billing SET tier='starter', ai_used=999999, ai_period=?, "
           "usage_enabled=1, usage_limit=1000000 WHERE username='shop@x.vn'", (period,))
billing.record_token_usage("shop@x.vn", "deepseek-chat", 200_000, 20_000)
rows = db.query("SELECT * FROM ai_usage_log WHERE username='shop@x.vn' ORDER BY id")
check(len(rows) == 2 and rows[1]["billed"] == 1, "B1 lượt vượt quota billed=1", [dict(r) for r in rows])
bal2 = db.query("SELECT balance FROM billing WHERE username='shop@x.vn'")[0]["balance"]
check(bal2 == 100000 - rows[1]["cost_vnd"], "B2 ví bị trừ đúng cost", (bal2, rows[1]["cost_vnd"]))

print("\n── C. ai_costs_by_shop ──")
out = billing.ai_costs_by_shop()
me = [s for s in out if s["username"] == "shop@x.vn"]
check(me and me[0]["n_calls"] == 2, "C1 gộp đủ 2 lượt", out)
check(me[0]["cost_vnd"] == rows[0]["cost_vnd"] + rows[1]["cost_vnd"], "C2 tổng cost đúng")
check(me[0]["tier"] == "starter" and me[0]["plan_month_vnd"] == billing.PRICES["starter"]["month"],
      "C3 kèm giá gói tháng để soi lỗ", me[0])
check(billing.ai_costs_by_shop("1990-01") == [], "C4 tháng không có dữ liệu → rỗng")

print("\n── D. Route /admin/ai-costs ──")
r = cli.get("/admin/ai-costs", headers={"Authorization": f"Bearer {TOK_ROOT}"})
check(r.status_code == 200 and any(s["username"] == "shop@x.vn" for s in r.json["shops"]),
      "D1 admin xem được", r.text[:120])
r = cli.get("/admin/ai-costs", headers={"Authorization": f"Bearer {TOK_SHOP}"})
check(r.status_code == 403, "D2 shop thường bị 403", r.status_code)

try:
    db.conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_usagelog_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
