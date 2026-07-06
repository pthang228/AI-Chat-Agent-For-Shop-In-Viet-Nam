#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tenant.py — MULTI-TENANT: cách ly dữ liệu giữa các SHOP (nền móng SaaS):
  A. tenant.assign: gán 1 lần theo chủ kênh, fallback chủ nền tảng, không "cướp"
  B. tenant.visible: ma trận quyền nhìn
  C. API hội thoại (telegram thật): shop B KHÔNG thấy hội thoại shop A (list+detail)
  D. Chốt chặn tập trung: shop B send/toggle/assign lên hội thoại shop A → 404
  E. Orders: đơn từ hội thoại mang tenant; list/get lọc theo shop
  F. Customers: list/get lọc theo shop
  G. Canned: câu mẫu tách theo shop
  H. Broadcast audience: chỉ khách shop mình

Chạy TỪ GỐC: python tests/test_tenant.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tenant_tmp.sqlite'   # DB test riêng
os.environ['API_AUTH_GUARD'] = '1'    # BẬT — cách ly tenant cần auth thật
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(f"test_db_tenant_tmp.sqlite{suf}").unlink(missing_ok=True)
Path("test_tenant_store_tmp.json").unlink(missing_ok=True)

from flask import Flask
from app.core.conversation import ConversationManager
from app.core import tenant, orders, customers, broadcast
from app.core.channel import Channel
from app.core.telegram_store import TelegramStore
from app.web_api.auth_api import register_auth_routes

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


class FakeChannel(Channel):
    def __init__(self): self.sent = []
    def send_text(self, uid, t): self.sent.append((uid, t))
    def send_room_photos(self, uid, n): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass

class FakeBrain:
    def __init__(self): self.channel = FakeChannel()
    def handle(self, uid, text): pass


# App auth (đăng ký 2 shop) — bare Flask, guard bật
auth_app = Flask(__name__)
register_auth_routes(auth_app)
ac = auth_app.test_client()

r = ac.post("/auth/register", json={"username": "shopa@x.vn", "password": "1234", "homestay": "Shop A"})
TOK_A = r.json["token"]
r = ac.post("/auth/register", json={"username": "shopb@x.vn", "password": "1234", "homestay": "Shop B"})
TOK_B = r.json["token"]
HA = {"Authorization": f"Bearer {TOK_A}"}
HB = {"Authorization": f"Bearer {TOK_B}"}

# ── A. tenant.assign ────────────────────────────────────────────────
print("A. tenant.assign")
cm = ConversationManager(account="telegram")
cm._sessions.clear()

tenant._default_cache.update(t=0, v=None)   # xoá cache (users vừa tạo)
check(tenant.default_owner() == "shopa@x.vn", "A1 chủ nền tảng = user đầu tiên")

tenant.assign(cm, "tg:BOTA:1", "shopa@x.vn")
tenant.assign(cm, "tg:BOTB:2", "shopb@x.vn")
check(cm._sessions["tg:BOTA:1"].tenant == "shopa@x.vn", "A2 gán theo chủ kênh")
tenant.assign(cm, "tg:BOTA:1", "shopb@x.vn")   # cố "cướp"
check(cm._sessions["tg:BOTA:1"].tenant == "shopa@x.vn", "A3 tenant bất biến — không cướp được")
tenant.assign(cm, "tg:NOOWN:3", None)
check(cm._sessions["tg:NOOWN:3"].tenant == "shopa@x.vn", "A4 không chủ → fallback chủ nền tảng")
cm.get("tg:BOTA:1").add_user_message("hi A"); cm.get("tg:BOTB:2").add_user_message("hi B")
cm.save()
from app.core.db import get_db
row = get_db().query("SELECT tenant FROM sessions WHERE user_id='tg:BOTB:2'")[0]
check(row["tenant"] == "shopb@x.vn", "A5 persist tenant xuống SQLite")

# ── B. visible ──────────────────────────────────────────────────────
print("B. tenant.visible")
check(tenant.visible("shopa@x.vn", "shopa@x.vn"), "B1 chủ thấy của mình")
check(not tenant.visible("shopa@x.vn", "shopb@x.vn"), "B2 shop khác KHÔNG thấy")
check(tenant.visible("", "shopa@x.vn"), "B3 dữ liệu mồ côi → chủ nền tảng thấy")
check(not tenant.visible("", "shopb@x.vn"), "B4 dữ liệu mồ côi → shop khác không")
check(tenant.visible("shopb@x.vn", None), "B5 không workspace (test) → thấy hết")

# ── C+D. API hội thoại telegram thật ────────────────────────────────
print("C. API hội thoại cách ly")
from app.web_api.telegram_api import create_telegram_api
store = TelegramStore(path=Path("test_tenant_store_tmp.json"))
tg_app = create_telegram_api(FakeBrain(), cm, FakeChannel(), store)
tc = tg_app.test_client()

r = tc.get("/tg/conversations", headers=HA)
uids_a = [x["user_id"] for x in r.json["items"]]
check("tg:BOTA:1" in uids_a and "tg:NOOWN:3" in uids_a and "tg:BOTB:2" not in uids_a,
      "C1 shop A thấy conv mình + mồ côi, KHÔNG thấy của B", uids_a)
r = tc.get("/tg/conversations", headers=HB)
uids_b = [x["user_id"] for x in r.json["items"]]
check(uids_b == ["tg:BOTB:2"], "C2 shop B chỉ thấy conv mình", uids_b)
r = tc.get("/tg/conversations/tg:BOTA:1", headers=HB)
check(r.status_code == 404, "C3 shop B mở detail conv A → 404", r.status_code)
r = tc.get("/tg/conversations/tg:BOTA:1", headers=HA)
check(r.status_code == 200, "C4 shop A mở detail conv mình → 200")

print("D. Chốt chặn tập trung (send/toggle/assign)")
r = tc.post("/tg/conversations/tg:BOTA:1/send", json={"text": "xin chào"}, headers=HB)
check(r.status_code == 404, "D1 B send vào conv A → 404", r.status_code)
r = tc.post("/tg/conversations/tg:BOTA:1/toggle-bot", json={"bot_on": False}, headers=HB)
check(r.status_code == 404, "D2 B toggle conv A → 404")
r = tc.post("/tg/conversations/tg:BOTA:1/assign", json={"username": "x@y.z"}, headers=HB)
check(r.status_code == 404, "D3 B assign conv A → 404")
r = tc.delete("/tg/conversations/tg:BOTA:1", headers=HB)
check(r.status_code == 404 and "tg:BOTA:1" in cm._sessions, "D4 B xoá conv A → 404, conv còn nguyên")
r = tc.post("/tg/conversations/tg:BOTB:2/toggle-bot", json={"bot_on": False}, headers=HB)
check(r.status_code == 200, "D5 B thao tác conv mình → 200", r.text)

# ── E. Orders ───────────────────────────────────────────────────────
print("E. Orders theo shop")
conv_a = cm._sessions["tg:BOTA:1"]
o_a = orders.create(channel="telegram", user_id="tg:BOTA:1", customer_name="Khách A",
                    total=100000, tenant=conv_a.tenant)
o_b = orders.create(channel="telegram", user_id="tg:BOTB:2", customer_name="Khách B",
                    total=200000, tenant="shopb@x.vn")
r = orders.list_orders(tenant_ws="shopb@x.vn")
check([x["code"] for x in r["items"]] == [o_b["code"]], "E1 list B chỉ thấy đơn B", r["items"])
r = orders.list_orders(tenant_ws="shopa@x.vn")
check(o_a["code"] in [x["code"] for x in r["items"]] and o_b["code"] not in [x["code"] for x in r["items"]],
      "E2 list A thấy đơn A không thấy B")
s = orders.summary(tenant_ws="shopb@x.vn")
check(s["total"] == 1, "E3 summary B đếm đúng 1 đơn", s)
# create_from_conversation mang tenant từ conv (AI mock chết → đơn tối thiểu)
import app.core.claude_ai as _cai
_orig = _cai._call_ai
_cai._call_ai = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("AI tắt trong test"))
try:
    o_c = orders.create_from_conversation("tg:BOTB:2", cm._sessions["tg:BOTB:2"], channel="telegram")
finally:
    _cai._call_ai = _orig
check(o_c and o_c.get("tenant") == "shopb@x.vn", "E4 đơn từ hội thoại mang tenant của conv", o_c)

# ── F. Customers ────────────────────────────────────────────────────
print("F. Customers theo shop")
r = customers.list_customers(tenant_ws="shopb@x.vn")
ids = [x["user_id"] for x in r["items"]]
check(ids == ["tg:BOTB:2"], "F1 list B chỉ thấy khách B", ids)
r = customers.list_customers(tenant_ws="shopa@x.vn")
ids = [x["user_id"] for x in r["items"]]
check("tg:BOTA:1" in ids and "tg:BOTB:2" not in ids, "F2 list A không thấy khách B")
check(customers.get_customer("telegram", "tg:BOTA:1", tenant_ws="shopb@x.vn") is None,
      "F3 B mở hồ sơ khách A → None")
check(customers.get_customer("telegram", "tg:BOTA:1", tenant_ws="shopa@x.vn") is not None,
      "F4 A mở hồ sơ khách mình → OK")

# ── G. Canned theo shop ─────────────────────────────────────────────
print("G. Canned theo shop")
from app.web_api.chat_tools import register_chat_tools
cn_app = Flask(__name__)
register_auth_routes(cn_app)
register_chat_tools(cn_app, "", cm, FakeChannel(), account="telegram", with_canned=True)
cc = cn_app.test_client()
r = cc.post("/canned", json={"title": "Chào A", "content": "Shop A xin chào"}, headers=HA)
cid_a = r.json["id"]
cc.post("/canned", json={"title": "Chào B", "content": "Shop B xin chào"}, headers=HB)
titles_a = [x["title"] for x in cc.get("/canned", headers=HA).json]
titles_b = [x["title"] for x in cc.get("/canned", headers=HB).json]
check("Chào A" in titles_a and "Chào B" not in titles_a, "G1 A chỉ thấy câu mẫu A", titles_a)
check(titles_b == ["Chào B"], "G2 B chỉ thấy câu mẫu B", titles_b)
r = cc.delete(f"/canned/{cid_a}", headers=HB)
check(r.status_code == 404, "G3 B xoá câu mẫu A → 404")

# ── H. Broadcast audience theo shop ─────────────────────────────────
print("H. Broadcast audience theo shop")
a = broadcast.audience(["telegram"], {"type": "all"}, tenant_ws="shopb@x.vn")
check([x["user_id"] for x in a] == ["tg:BOTB:2"], "H1 audience B chỉ khách B", a)
a = broadcast.audience(["telegram"], {"type": "all"}, tenant_ws="shopa@x.vn")
ids = [x["user_id"] for x in a]
check("tg:BOTA:1" in ids and "tg:BOTB:2" not in ids, "H2 audience A không dính khách B")

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
