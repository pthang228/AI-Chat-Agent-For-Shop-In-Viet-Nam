#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_orders.py — Sổ đơn hàng (Phase 1 module đơn hàng):
  - CRUD + mã đơn DHxxxx tăng dần + timeline khi đổi trạng thái
  - list filter (status/channel/q) + summary (đếm + doanh thu)
  - extract_from_messages (mock AI) + create_from_conversation (fallback khi AI hỏng)
  - due_orders / check_and_notify (nhắc tới hạn, không nhắc đơn done/cancelled/đã nhắc)
  - API /orders (Bearer)

Chạy (TỪ GỐC):  python tests/test_orders.py
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
sys.path.insert(0, '.')

import json
from datetime import datetime, timedelta
from flask import Flask
from app.core import orders as od
from app.core.db import get_db
import app.web_api.auth_api as auth_mod
import app.web_api.orders_api as orders_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

get_db().execute("DELETE FROM orders")

print("\n── A. CRUD + mã đơn + timeline ──")
o1 = od.create(channel="zalo", customer_name="Chị Trang", order_type="booking",
               items=[{"name": "Phòng 301 qua đêm", "qty": 1, "price": 380000}],
               total=380000, due_at="2026-12-25T14:00")
# Mã đơn = DH + id thật (AUTOINCREMENT không reset khi xoá → không đòi DH0001 tuyệt đối)
check(o1["code"] == f"DH{o1['id']:04d}" and o1["status"] == "draft", "A1 create_code", o1["code"])
o2 = od.create(channel="shopee", order_type="goods", total=250000)
check(o2["code"] == f"DH{o2['id']:04d}" and o2["id"] == o1["id"] + 1, "A2 code_increments", o2["code"])

# đổi trạng thái → timeline ghi lại
o1b = od.update(o1["id"], status="awaiting_payment")
check(o1b["status"] == "awaiting_payment"
      and any("draft → awaiting_payment" in t["event"] for t in o1b["timeline"]),
      "A3 status_timeline", f"{o1b['timeline']}")
# trạng thái không hợp lệ → giữ nguyên
o1c = od.update(o1["id"], status="bay_mau")
check(o1c["status"] == "awaiting_payment", "A4 invalid_status_ignored")
# sửa field thường
o1d = od.update(o1["id"], phone="0901234567", total=400000)
check(o1d["phone"] == "0901234567" and o1d["total"] == 400000, "A5 update_fields")
# đổi due_at → reset cờ reminded
get_db().execute("UPDATE orders SET reminded=1 WHERE id=?", (o1["id"],))
od.update(o1["id"], due_at="2026-12-26T14:00")
check(od.get(o1["id"])["reminded"] is False, "A6 due_change_resets_reminded")

print("\n── B. list + summary ──")
r = od.list_orders(status="awaiting_payment")
check(r["total"] == 1 and r["items"][0]["code"] == o1["code"], "B1 filter_status")
r = od.list_orders(channel="shopee")
check(r["total"] == 1 and r["items"][0]["code"] == o2["code"], "B2 filter_channel")
r = od.list_orders(q="Trang")
check(r["total"] == 1, "B3 search_name")
od.update(o2["id"], status="awaiting_payment"); od.update(o2["id"], status="paid")
s = od.summary()
check(s["total"] == 2 and s["by_status"]["paid"] == 1 and s["revenue"] == 250000,
      "B4 summary_revenue", s)

print("\n── C. extract + create_from_conversation ──")
FAKE_JSON = json.dumps({
    "customer_name": "Anh Nam", "phone": "0912345678", "order_type": "booking",
    "items": [{"name": "Phòng 201 ca chiều", "qty": 1, "price": 260000}],
    "total": 260000, "due_at": "2026-12-30T16:30", "note": "khách xin checkin sớm"})

class FakeConv:
    def __init__(self):
        self.messages = [{"role": "user", "content": "đặt phòng 201 ca chiều 30/12"},
                         {"role": "assistant", "content": "dạ em chốt nhé"}]
        self.name = "Nam"; self.checkin = "30/12/2026"; self.selected_room = "201"

with patch.object(__import__('app.core.claude_ai', fromlist=['_call_ai']), '_call_ai',
                  return_value=f"```json\n{FAKE_JSON}\n```"):
    o = od.create_from_conversation("zalo_u1", FakeConv(), channel="zalo")
check(o and o["customer_name"] == "Anh Nam" and o["total"] == 260000
      and o["due_at"] == "2026-12-30T16:30" and o["status"] == "draft",
      "C1 extract_full", o)
check(o["items"][0]["name"] == "Phòng 201 ca chiều", "C2 items_extracted")

# AI hỏng → vẫn tạo đơn tối thiểu từ hints (KHÔNG mất đơn)
with patch.object(__import__('app.core.claude_ai', fromlist=['_call_ai']), '_call_ai',
                  side_effect=RuntimeError("AI chết")):
    o = od.create_from_conversation("zalo_u2", FakeConv(), channel="zalo")
check(o and o["customer_name"] == "Nam" and o["items"][0]["name"] == "Phòng 201"
      and o["due_at"] == "2026-12-30T14:00",
      "C3 ai_fail_fallback_hints", o)

# _ddmmyyyy_to_iso
check(od._ddmmyyyy_to_iso("25/12/2026") == "2026-12-25T14:00", "C4 date_convert")
check(od._ddmmyyyy_to_iso("rác") is None, "C5 bad_date_none")

print("\n── D. nhắc tới hạn ──")
get_db().execute("DELETE FROM orders")
soon = (datetime.now() + timedelta(hours=3)).isoformat(timespec="minutes")
far = (datetime.now() + timedelta(days=10)).isoformat(timespec="minutes")
a = od.create(customer_name="Sắp tới", due_at=soon, status="paid", total=100000)
b = od.create(customer_name="Còn xa", due_at=far, status="paid")
c = od.create(customer_name="Đã xong", due_at=soon, status="done")
d = od.create(customer_name="Đã huỷ", due_at=soon, status="cancelled")

due = od.due_orders()
check([x["customer_name"] for x in due] == ["Sắp tới"], "D1 due_filter",
      [x["customer_name"] for x in due])

notes = []
n = od.check_and_notify(lambda t: notes.append(t))
check(n == 1 and a["code"] in notes[0] and "Sắp tới" in notes[0], "D2 notify_text", notes)
check(od.due_orders() == [], "D3 no_double_remind")
# đơn quá hạn (due trong quá khứ) chưa nhắc → vẫn nhắc
e = od.create(customer_name="Quá hạn", status="paid",
              due_at=(datetime.now() - timedelta(hours=2)).isoformat(timespec="minutes"))
check(len(od.due_orders()) == 1, "D4 overdue_included")

print("\n── E. API /orders ──")
get_db().execute("DELETE FROM orders")
for t in ("users", "auth_tokens"):
    get_db().execute(f"DELETE FROM {t}")
flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
orders_mod.register_orders_routes(flask_app)
api = flask_app.test_client()
tok = api.post("/auth/register", json={"username": "od@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

check(api.get("/orders").status_code == 401, "E1 needs_auth")
r = api.post("/orders", json={"customer_name": "Khách A", "order_type": "goods",
                              "items": [{"name": "Váy", "qty": 2, "price": 250000}],
                              "total": 500000, "channel": "shopee"}, headers=H)
check(r.status_code == 200 and r.get_json()["order"]["code"].startswith("DH"), "E2 api_create")
oid = r.get_json()["order"]["id"]

r = api.patch(f"/orders/{oid}", json={"status": "paid"}, headers=H)
check(r.status_code == 200 and r.get_json()["order"]["status"] == "paid", "E3 api_status")
check(api.patch(f"/orders/{oid}", json={"status": "xxx"}, headers=H).status_code == 400,
      "E4 api_bad_status_400")

r = api.get("/orders?status=paid&channel=shopee", headers=H)
check(r.get_json()["total"] == 1, "E5 api_filter")
r = api.get("/orders/summary", headers=H)
check(r.get_json()["revenue"] == 500000, "E6 api_summary")
r = api.get(f"/orders/{oid}", headers=H)
check(r.status_code == 200 and len(r.get_json()["order"]["timeline"]) >= 2, "E7 api_detail_timeline")
check(api.get("/orders/99999", headers=H).status_code == 404, "E8 api_404")
r = api.delete(f"/orders/{oid}", headers=H)
check(r.status_code == 200 and api.get(f"/orders/{oid}", headers=H).status_code == 404, "E9 api_delete")

# Dọn
get_db().execute("DELETE FROM orders")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
