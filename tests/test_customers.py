#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_customers.py — CRM Khách hàng:
  A. list_customers gộp mọi account + lọc q/platform; get_customer đủ field
  B. update_customer ghi audit history; name đè tên kênh
  C. scan_contact bóc SĐT (cả viết tách)/email từ tin KHÁCH, tự điền khi trống
  D. memory CRUD + trần 50 + memory_block cho bot; ai_extract_memory (mock AI,
     bỏ trùng, parse rác an toàn)
  E. claude_ai inject memory vào system prompt (legacy + hybrid) — lỗi CRM
     không giết bot
  F. API bridge: list/get/patch/scan/orders/memory + 404

Chạy (TỪ GỐC):  python tests/test_customers.py
"""

import os, sys
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(), 'requests': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
os.environ.setdefault('OWNER_ZALO_ID', 'OWNER123')
os.environ['HOMESTAY_DB_PATH'] = 'test_db_customers_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

import json
from pathlib import Path
from app.core.conversation import ConversationManager
from app.core import customers as crm
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
for t in ("customers", "customer_memory", "customer_history", "orders"):
    db.execute(f"DELETE FROM {t}")
db.execute("DELETE FROM sessions")

# Seed sessions 2 kênh (bridge đọc thẳng DB → khách mọi kênh)
cm_zalo = ConversationManager(account="1")
cm_meta = ConversationManager(account="meta")
cm_zalo._sessions.clear(); cm_meta._sessions.clear()
c1 = cm_zalo.get("Z001"); c1.name = "Cường Tony"
c1.add_user_message("cho mình hỏi giá, sđt mình 0912 345 678 nhé, mail cuong@gmail.com")
c2 = cm_meta.get("fb:PG:U9"); c2.name = "Khách FB"
c2.add_user_message("còn hàng không shop")
cm_zalo.save(); cm_meta.save()

print("\n── A. list + get ──")
r = crm.list_customers()
check(r["total"] == 2, "A1 gop_moi_kenh", f"{r['total']}")
plats = {i["platform"] for i in r["items"]}
check(plats == {"zalo", "meta"}, "A2 platform_map", f"{plats}")
r = crm.list_customers(platform="meta")
check(r["total"] == 1 and r["items"][0]["user_id"] == "fb:PG:U9", "A3 filter_platform")
r = crm.list_customers(q="cường")
check(r["total"] == 1 and r["items"][0]["user_id"] == "Z001", "A4 search_ten_co_dau")
c = crm.get_customer("1", "Z001")
check(c and c["name"] == "Cường Tony" and c["message_count"] == 1
      and c["order_count"] == 0, "A5 get_full", f"{c and c.get('name')}")
check(crm.get_customer("1", "KHONG_CO") is None, "A6 not_found_none")

print("\n── B. update + audit ──")
crm.update_customer("1", "Z001", {"phone": "0999888777", "salutation": "anh",
                                  "field_la": "bo qua"})
p = crm.get_customer("1", "Z001")
check(p["phone"] == "0999888777" and p["salutation"] == "anh", "B1 updated")
hist = crm.list_history("1", "Z001")
check(len(hist) == 2 and {h["field"] for h in hist} == {"phone", "salutation"},
      "B2 audit_logged", f"{hist}")
# đổi tên → name đè tên kênh trong list
crm.update_customer("1", "Z001", {"name": "Anh Cường VIP"})
check(crm.list_customers(q="VIP")["total"] == 1, "B3 name_override")
# update không đổi gì → không ghi thêm history
n_before = len(crm.list_history("1", "Z001"))
crm.update_customer("1", "Z001", {"phone": "0999888777"})
check(len(crm.list_history("1", "Z001")) == n_before, "B4 no_change_no_audit")

print("\n── C. scan SĐT/email ──")
db.execute("DELETE FROM customers")   # hồ sơ trống để scan tự điền
r = crm.scan_contact("1", "Z001")
check("0912345678" in r["phones"], "C1 phone_viet_tach", f"{r['phones']}")
check("cuong@gmail.com" in r["emails"], "C2 email", f"{r['emails']}")
check(r["updated"] and crm.get_customer("1", "Z001")["phone"] == "0912345678",
      "C3 auto_fill")
# đã có phone → scan không ghi đè
r = crm.scan_contact("1", "Z001")
check(not r["updated"], "C4 no_overwrite")
r = crm.scan_contact("meta", "fb:PG:U9")
check(r["phones"] == [] and r["emails"] == [], "C5 nothing_found")

print("\n── D. memory ──")
m = crm.add_memory("1", "Z001", "Khách thích phòng view biển")
check(m["id"] and m["source"] == "manual", "D1 add")
crm.add_memory("1", "Z001", "Hay đặt cuối tuần", source="ai")
ml = crm.list_memory("1", "Z001")
check(len(ml) == 2 and ml[0]["source"] == "ai", "D2 list_desc")
blk = crm.memory_block("1", "Z001")
check("GHI NHỚ VỀ KHÁCH" in blk and "view biển" in blk, "D3 block", blk[:60])
check(crm.memory_block("1", "KHACH_LA") == "", "D4 empty_block")
crm.delete_memory(m["id"])
check(len(crm.list_memory("1", "Z001")) == 1, "D5 delete")
try:
    crm.add_memory("1", "Z001", "")
    check(False, "D6 empty_rejected")
except ValueError:
    check(True, "D6 empty_rejected")

# ai_extract: mock _call_ai, bỏ trùng
with patch("app.core.claude_ai._call_ai",
           return_value='["Hay đặt cuối tuần", "Có nuôi mèo", "Dị ứng hải sản"]'):
    added = crm.ai_extract_memory("1", "Z001")
check(len(added) == 2 and all(a["source"] == "ai" for a in added), "D7 ai_extract_dedup", f"{added}")
with patch("app.core.claude_ai._call_ai", return_value="xin lỗi không hiểu"):
    check(crm.ai_extract_memory("1", "Z001") == [], "D8 ai_garbage_safe")

print("\n── E. inject memory vào bot ──")
from app.core import claude_ai
sys_prompt = claude_ai._build_system_prompt("chào", [], user_id="Z001", account="1")
check("GHI NHỚ VỀ KHÁCH" in sys_prompt and "Có nuôi mèo" in sys_prompt, "E1 legacy_inject")
sys_prompt2 = claude_ai._build_system_prompt("chào", [])   # không user_id → không inject
check("GHI NHỚ VỀ KHÁCH" not in sys_prompt2, "E2 no_uid_no_inject")
# CRM lỗi không được giết bot
with patch("app.core.customers.memory_block", side_effect=RuntimeError("db chết")):
    s = claude_ai._build_system_prompt("chào", [], user_id="Z001", account="1")
    check(isinstance(s, str) and len(s) > 100, "E3 crm_error_safe")

print("\n── F. API bridge ──")
from app.core.brain import Brain
from app.core.channel import Channel
import app.web_api.bridge as bridge_mod

class FakeChannel(Channel):
    def send_text(self, u, t): pass
    def send_room_photos(self, u, n): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass

bridge_mod.BOT_STATE_FILE = Path("test_bot_state_cu_tmp.json")
api = bridge_mod.create_bridge(Brain(channel=FakeChannel(), conv_manager=cm_zalo), cm_zalo).test_client()

r = api.get("/customers")
check(r.status_code == 200 and r.get_json()["total"] == 2, "F1 list")
r = api.get("/customers/meta/fb:PG:U9")
check(r.status_code == 200 and r.get_json()["platform"] == "meta", "F2 get_uid_co_dau_hai_cham")
check(api.get("/customers/1/KHONG").status_code == 404, "F3 404")
r = api.patch("/customers/meta/fb:PG:U9", json={"note": "khách sộp"})
check(r.status_code == 200 and r.get_json()["profile"]["note"] == "khách sộp", "F4 patch")
r = api.post("/customers/1/Z001/scan")
check(r.status_code == 200, "F5 scan")
# đơn hàng của khách
from app.core import orders as ordmod
o = ordmod.create(channel="zalo", user_id="Z001", customer_name="Cường", total=500000, status="paid")
r = api.get("/customers/1/Z001/orders")
check(r.status_code == 200 and r.get_json()[0]["code"] == o["code"], "F6 orders")
c = crm.get_customer("1", "Z001")
check(c["order_count"] == 1 and c["order_value"] == 500000, "F7 stats_value")
r = api.post("/customers/1/Z001/memory", json={"content": "Thích tầng cao"})
mid = r.get_json()["memory"]["id"]
check(r.status_code == 200 and mid, "F8 memory_add")
check(api.delete(f"/customers/memory/{mid}").status_code == 200, "F9 memory_del")

Path("test_bot_state_cu_tmp.json").unlink(missing_ok=True)
print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
