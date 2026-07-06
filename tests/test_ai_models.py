#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_ai_models.py — MULTI-MODEL AI + tính theo usage khi vượt quota:
  A. Catalog + giá: price_vnd_1m, cost_vnd, catalog_for_ui (available theo key)
  B. model_for_owner: chọn hợp lệ / không hợp lệ / thiếu key → mặc định
  C. record_token_usage: trong quota KHÔNG trừ ví; hết quota + bật usage → trừ ví
     + cộng usage_spent; reset theo tháng
  D. can_reply: hết quota → False; bật usage còn hạn mức + ví → True; chạm limit → False
  E. API /billing/ai-model + /billing/usage: validate + lưu

Chạy TỪ GỐC: python -m tests.test_ai_models
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_ai_models_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '1'
os.environ['WORKER_SYNC'] = '1'
os.environ['AI_USD_VND'] = '25000'      # tỷ giá cố định cho test
os.environ['AI_PRICE_MARKUP'] = '1.0'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(f"test_db_ai_models_tmp.sqlite{suf}").unlink(missing_ok=True)

from flask import Flask
from app.web_api.auth_api import register_auth_routes
from app.web_api.billing_api import register_billing_routes
from app.core import ai_models as am
from app.core import billing
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


print("A. Catalog + giá")
pin, pout = am.price_vnd_1m("deepseek-chat")   # 0.26 / 0.38 USD × 25000
check(pin == 6500 and pout == 9500, "A1 giá VNĐ/1M đúng tỷ giá", (pin, pout))
c = am.cost_vnd("gpt-4o", 1000, 500)           # (1000*2.5 + 500*10)/1e6 × 25000
check(abs(c - 187.5) < 0.01, "A2 cost_vnd đúng công thức", c)
ui = am.catalog_for_ui()
check(len(ui) == len(am.CATALOG) and all("in_vnd" in m for m in ui), "A3 catalog_for_ui đủ model")
check(any(m["default"] for m in ui), "A4 có model mặc định")

print("B. model_for_owner")
from app.core.config import Config
Config.DEEPSEEK_API_KEY = "sk-test"; Config.OPENAI_API_KEY = ""
check(am.model_for_owner(None) == am.DEFAULT_MODEL, "B1 không owner → mặc định")

app = Flask(__name__)
register_auth_routes(app)
register_billing_routes(app)
cli = app.test_client()
r = cli.post("/auth/register", json={"username": "shop@x.vn", "password": "1234", "homestay": "Shop"})
H = {"Authorization": f"Bearer {r.json['token']}"}
U = "shop@x.vn"

db = get_db()
db.execute("UPDATE billing SET ai_model='gpt-5-mini' WHERE username=?", (U,))
check(am.model_for_owner(U) == am.DEFAULT_MODEL, "B2 chọn model thiếu key → về mặc định")
Config.OPENAI_API_KEY = "sk-openai-test"
check(am.model_for_owner(U) == "gpt-5-mini", "B3 có key → dùng model đã chọn")
db.execute("UPDATE billing SET ai_model='model-lạ' WHERE username=?", (U,))
check(am.model_for_owner(U) == am.DEFAULT_MODEL, "B4 model lạ → mặc định")
db.execute("UPDATE billing SET ai_model='' WHERE username=?", (U,))

print("C. record_token_usage")
def brow():
    return db.query("SELECT * FROM billing WHERE username=?", (U,))[0]
db.execute("UPDATE billing SET balance=100000 WHERE username=?", (U,))
# Trong quota (trial mới → chưa vượt) → không trừ ví
billing.record_token_usage(U, "deepseek-chat", 100_000, 50_000)
b = brow()
check(b["balance"] == 100000 and (b["usage_spent"] or 0) == 0,
      "C1 trong quota: KHÔNG trừ ví, usage_spent=0", dict(b))
# Ép hết quota (trial: 500 lượt/ngày) + bật usage
db.execute("UPDATE billing SET ai_used=?, ai_period=?, usage_enabled=1, usage_limit=50000 "
           "WHERE username=?", (10_000, billing._period("trial"), U))
billing.record_token_usage(U, "deepseek-chat", 1_000_000, 1_000_000)  # 6500+9500=16000đ
b = brow()
check(b["balance"] == 100000 - 16000, "C2 vượt quota + bật usage → trừ ví đúng giá", b["balance"])
check(b["usage_spent"] == 16000, "C3 usage_spent cộng dồn", b["usage_spent"])
# Tắt usage → vượt quota cũng không trừ
db.execute("UPDATE billing SET usage_enabled=0 WHERE username=?", (U,))
billing.record_token_usage(U, "deepseek-chat", 1_000_000, 0)
b = brow()
check(b["balance"] == 84000 and b["usage_spent"] == 16000,
      "C4 tắt usage: không trừ thêm", dict(balance=b["balance"], spent=b["usage_spent"]))

print("D. can_reply với usage")
db.execute("UPDATE billing SET usage_enabled=0 WHERE username=?", (U,))
check(not billing.can_reply(U), "D1 hết quota + tắt usage → bot dừng")
db.execute("UPDATE billing SET usage_enabled=1, usage_limit=50000 WHERE username=?", (U,))
check(billing.can_reply(U), "D2 bật usage còn hạn mức + ví → bot chạy")
db.execute("UPDATE billing SET usage_spent=50000 WHERE username=?", (U,))
check(not billing.can_reply(U), "D3 chạm giới hạn tháng → bot dừng")
db.execute("UPDATE billing SET usage_spent=0, balance=0 WHERE username=?", (U,))
check(not billing.can_reply(U), "D4 ví 0đ → bot dừng")
db.execute("UPDATE billing SET balance=50000, ai_used=0 WHERE username=?", (U,))
check(billing.can_reply(U), "D5 còn quota → chạy bình thường")

print("E. API chọn model + usage")
r = cli.get("/billing/me", headers=H)
check(r.status_code == 200 and len(r.json["ai_models"]) == len(am.CATALOG),
      "E1 /billing/me kèm bảng giá model")
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o-mini"})
check(r.status_code == 200 and r.json["ai_model"] == "gpt-4o-mini", "E2 chọn model OK", r.text[:80])
r = cli.post("/billing/ai-model", headers=H, json={"model": "model-lạ"})
check(r.status_code == 400, "E3 model lạ → 400")
Config.OPENAI_API_KEY = ""
r = cli.post("/billing/ai-model", headers=H, json={"model": "gpt-4o"})
check(r.status_code == 400, "E4 thiếu key server → 400")
Config.OPENAI_API_KEY = "sk-openai-test"
r = cli.post("/billing/usage", headers=H, json={"enabled": True, "limit": 300000})
check(r.status_code == 200 and r.json["usage_enabled"] and r.json["usage_limit"] == 300000,
      "E5 bật usage + limit OK", r.text[:80])
r = cli.post("/billing/usage", headers=H, json={"enabled": True, "limit": 0})
check(r.status_code == 400, "E6 bật mà limit 0 → 400")
r = cli.post("/billing/usage", headers=H, json={"enabled": False, "limit": 0})
check(r.status_code == 200 and not r.json["usage_enabled"], "E7 tắt usage OK")

# dọn
try:
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    Path(f"test_db_ai_models_tmp.sqlite{suf}").unlink(missing_ok=True)

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
