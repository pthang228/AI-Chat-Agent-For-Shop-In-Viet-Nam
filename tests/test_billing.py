#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_billing.py — gói theo HẠNG (tier) × thời hạn, ví, nạp tiền, QUOTA lượt AI:
  - trial 3/7 ngày (mã giới thiệu), redeem sau
  - nạp tiền: tạo → admin xác nhận → cộng ví
  - mua gói tier×duration: đủ/thiếu, gia hạn nối tiếp cùng hạng, nâng hạng, lifetime
  - quota AI: đếm/tháng, hết quota chặn, reset sang tháng mới, nâng hạng mở lại
  - gate: has_active_subscription (toàn cục) + channel_gate(owner) (theo chủ + ghi quota)
  - API /billing/* (Bearer) + admin key

Chạy (TỪ GỐC):  python tests/test_billing.py
"""

import os, sys
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tmp.sqlite'
os.environ['BILLING_PROMO_CODE'] = 'MACUAT'
os.environ['BILLING_ADMIN_KEY'] = 'adminkey123'
sys.path.insert(0, '.')

from datetime import datetime, timedelta
from flask import Flask
from app.core.db import get_db
from app.core import billing
import app.web_api.auth_api as auth_mod
import app.web_api.billing_api as bill_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
def wipe():
    for t in ("users", "auth_tokens", "user_apps", "billing", "deposits", "transactions"):
        db.execute(f"DELETE FROM {t}")
    billing._invalidate_cache()
wipe()

def days_left_of(username):
    b = db.query("SELECT * FROM billing WHERE username=?", (username,))[0]
    exp = datetime.fromisoformat(b["expires_at"])
    return (exp - datetime.now()).total_seconds() / 86400

def credit(username, amount):
    billing.confirm_deposit(billing.create_deposit(username, amount)["code"])

print("\n── A. Trial 3/7 ngày ──")
billing.ensure_billing("a@x.vn")
check(2.9 < days_left_of("a@x.vn") <= 3.01, "A1 trial_3_days", days_left_of("a@x.vn"))
st = billing.status("a@x.vn")
check(st["tier"] == "trial" and st["on_trial"] and st["ai_quota"] == billing.TRIAL_DAILY_QUOTA,
      "A1 trial_tier_500_daily", f"{st}")
check(st["ai_period_label"] == "hôm nay", "A1 trial_daily_label")

# Trial quota reset THEO NGÀY: dùng 500 hôm nay → chặn; hôm qua dùng 500 → hôm nay thoải mái
billing.record_ai_usage("a@x.vn", 500)
check(not billing.can_reply("a@x.vn"), "A1b trial_daily_cap_blocks")
from datetime import timedelta as _td
db.execute("UPDATE billing SET ai_period=? WHERE username='a@x.vn'",
           ((datetime.now() - _td(days=1)).strftime("%Y-%m-%d"),))
check(billing.can_reply("a@x.vn"), "A1c trial_new_day_resets")
check(billing.status("a@x.vn")["ai_used"] == 0, "A1c usage_zero_new_day")
db.execute("UPDATE billing SET ai_used=0 WHERE username='a@x.vn'")

billing.ensure_billing("b@x.vn", promo="macuat")
check(6.9 < days_left_of("b@x.vn") <= 7.01, "A2 promo_7_days")
billing.redeem_promo("a@x.vn", "MACUAT")
check(6.9 < days_left_of("a@x.vn") <= 7.01, "A3 redeem_upgrades")
try:
    billing.redeem_promo("a@x.vn", "MACUAT"); check(False, "A4 redeem_twice_blocked")
except ValueError:
    check(True, "A4 redeem_twice_blocked")

print("\n── B. Nạp tiền ──")
d = billing.create_deposit("a@x.vn", 500_000)
check(d["code"].startswith("NAP") and len(d["code"]) == 9, "B1 code")
check(billing.status("a@x.vn")["balance"] == 0, "B2 pending_not_credited")
try:
    billing.create_deposit("a@x.vn", 5_000); check(False, "B3 min_amount")
except ValueError:
    check(True, "B3 min_amount")
r = billing.confirm_deposit(d["code"].lower())
check(r["amount"] == 500_000 and billing.status("a@x.vn")["balance"] == 500_000, "B4 confirm_credits")
try:
    billing.confirm_deposit(d["code"]); check(False, "B5 confirm_twice_blocked")
except ValueError:
    check(True, "B5 confirm_twice_blocked")

print("\n── C. Mua gói tier × duration ──")
# Giá đúng bảng
check(billing.PRICES["pro"]["month"] == 500_000 and billing.PRICES["starter"]["month"] == 250_000
      and billing.PRICES["business"]["month"] == 1_300_000, "C1 prices")
# Quota ladder ×5
check(billing.TIERS["starter"]["quota"] == 6_000 and billing.TIERS["pro"]["quota"] == 30_000
      and billing.TIERS["business"]["quota"] == 150_000, "C1 quota_ladder")

# a có 500k → mua starter month (250k)
st = billing.buy_plan("a@x.vn", "starter", "month")
check(st["tier"] == "starter" and st["balance"] == 250_000 and st["ai_quota"] == 6_000, "C2 buy_starter", f"{st}")
check(29.9 < days_left_of("a@x.vn") <= 30.1, "C2 month_days")

# Gia hạn NỐI TIẾP cùng hạng: mua thêm starter month → ~60 ngày
billing.buy_plan("a@x.vn", "starter", "month")
check(59.8 < days_left_of("a@x.vn") <= 60.2, "C3 same_tier_extends", days_left_of("a@x.vn"))

# NÂNG HẠNG → tính lại từ hôm nay (không cộng dồn)
credit("a@x.vn", 500_000)
billing.buy_plan("a@x.vn", "pro", "month")
st = billing.status("a@x.vn")
check(st["tier"] == "pro" and 29.9 < days_left_of("a@x.vn") <= 30.1, "C4 upgrade_resets", f"{st} d={days_left_of('a@x.vn')}")

# Thiếu tiền
try:
    billing.buy_plan("a@x.vn", "business", "year"); check(False, "C5 insufficient")
except ValueError as e:
    check("không đủ" in str(e), "C5 insufficient")

# Lifetime
credit("b@x.vn", 10_000_000)
st = billing.buy_plan("b@x.vn", "pro", "lifetime")
check(st["lifetime"] and st["expires_at"] is None and st["tier"] == "pro", "C6 lifetime", f"{st}")

# Khởi đầu KHÔNG có gói vĩnh viễn
check("lifetime" not in billing.PRICES["starter"], "C7 starter_no_lifetime_price")
try:
    billing.buy_plan("a@x.vn", "starter", "lifetime"); check(False, "C7 starter_lifetime_blocked")
except ValueError as e:
    check("không có" in str(e), "C7 starter_lifetime_blocked", str(e))
# Catalog cho UI cũng không liệt kê
cat = {t["tier"]: t["prices"] for t in billing.plans_catalog()}
check("lifetime" not in cat["starter"] and "lifetime" in cat["pro"], "C8 catalog_hides_it")

print("\n── D. Quota lượt AI ──")
wipe()
billing.ensure_billing("q@x.vn"); credit("q@x.vn", 500_000)
billing.buy_plan("q@x.vn", "starter", "month")   # quota 6000
check(billing.can_reply("q@x.vn"), "D1 can_reply_fresh")
billing.record_ai_usage("q@x.vn", 5_999)
st = billing.status("q@x.vn")
check(st["ai_used"] == 5_999 and st["ai_left"] == 1, "D2 usage_counted", f"{st}")
check(billing.can_reply("q@x.vn"), "D3 still_ok_at_limit_minus1")
billing.record_ai_usage("q@x.vn", 1)             # chạm 6000
check(not billing.can_reply("q@x.vn"), "D4 quota_exhausted_blocks")

# Sang tháng mới → reset (giả lập bằng đổi ai_period)
db.execute("UPDATE billing SET ai_period='2000-01' WHERE username='q@x.vn'")
check(billing.can_reply("q@x.vn"), "D5 new_month_resets")
check(billing.status("q@x.vn")["ai_used"] == 0, "D5 usage_zero_new_month")

# Nâng hạng mở quota lớn hơn
db.execute("UPDATE billing SET ai_used=6000, ai_period=? WHERE username='q@x.vn'", (billing._period(),))
billing._invalidate_cache()
check(not billing.can_reply("q@x.vn"), "D6 starter_exhausted")
credit("q@x.vn", 500_000); billing.buy_plan("q@x.vn", "pro", "month")   # quota 30000
check(billing.can_reply("q@x.vn"), "D7 upgrade_unblocks_quota")

print("\n── E. Gate: channel_gate(owner) ──")
wipe()
db.execute("INSERT INTO users(username,password_hash,homestay,email,provider,picture,created_at) "
           "VALUES ('shop@x.vn','h','','','password','',?)", (datetime.now().isoformat(),))
billing.ensure_billing("shop@x.vn"); credit("shop@x.vn", 500_000)
billing.buy_plan("shop@x.vn", "starter", "month")

# channel_gate biết chủ → cho qua + GHI quota
before = billing.status("shop@x.vn")["ai_used"]
ok = billing.channel_gate("shop@x.vn")
after = billing.status("shop@x.vn")["ai_used"]
check(ok and after == before + 1, "E1 gate_records_usage", f"{before}->{after}")

# Hết hạn chủ → gate chặn
db.execute("UPDATE billing SET expires_at=? WHERE username='shop@x.vn'",
           ((datetime.now() - timedelta(days=1)).isoformat(),))
billing._invalidate_cache()
check(not billing.channel_gate("shop@x.vn"), "E2 gate_blocks_expired")

# Kênh KHÔNG gắn chủ (owner=None) → gate toàn cục (còn user shop hết hạn → False)
check(not billing.channel_gate(None), "E3 global_gate_all_expired")
# Gia hạn → mở lại
db.execute("UPDATE billing SET expires_at=? WHERE username='shop@x.vn'",
           ((datetime.now() + timedelta(days=5)).isoformat(),))
billing._invalidate_cache()
check(billing.channel_gate(None), "E4 global_gate_active")

# Chưa có user nào → luôn cho qua (chưa áp billing)
wipe()
check(billing.has_active_subscription(), "E5 no_users_active")

print("\n── F. API /billing/* ──")
wipe()
flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
bill_mod.register_billing_routes(flask_app)
api = flask_app.test_client()
def bearer(t): return {"Authorization": f"Bearer {t}"}

tok = api.post("/auth/register", json={"username": "web@x.vn", "password": "test1234",
                                       "homestay": "Web", "promo": "MACUAT"}).get_json()["token"]
r = api.get("/billing/me", headers=bearer(tok))
b = r.get_json()
check(r.status_code == 200 and b["on_trial"] and b["days_left"] == 7, "F1 me_trial")
check(len(b["tiers"]) == 3 and b["tiers"][0]["prices"]["month"] == 250_000
      and len(b["durations"]) == 4, "F2 catalog", f"{b['tiers'][0] if b['tiers'] else None}")

code = api.post("/billing/deposit", json={"amount": 500000}, headers=bearer(tok)).get_json()["code"]
r = api.post("/billing/admin/confirm", json={"code": code})
check(r.status_code == 403, "F3 admin_needs_key")
api.post("/billing/admin/confirm", json={"code": code}, headers={"X-Admin-Key": "adminkey123"})

r = api.post("/billing/buy", json={"tier": "starter", "duration": "month"}, headers=bearer(tok))
b = r.get_json()
check(r.status_code == 200 and b["tier"] == "starter" and b["balance"] == 250_000, "F4 api_buy", f"{b}")

r = api.post("/billing/buy", json={"tier": "business", "duration": "year"}, headers=bearer(tok))
check(r.status_code == 400, "F5 api_buy_insufficient")

r = api.post("/billing/buy", json={"tier": "xxx", "duration": "month"}, headers=bearer(tok))
check(r.status_code == 400, "F6 api_buy_bad_tier")

r = api.get("/billing/history", headers=bearer(tok))
check(r.status_code == 200 and len(r.get_json()) >= 2, "F7 history")
r = api.get("/billing/me")
check(r.status_code == 401, "F8 needs_auth")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
