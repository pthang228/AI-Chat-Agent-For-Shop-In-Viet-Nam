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

# ═══ PHASE 2: NÃO BOT PER-TENANT ════════════════════════════════════
print("I. shop_key")
check(tenant.shop_key("shopa@x.vn") == "default", "I1 chủ nền tảng → não 'default' (giữ não cũ)")
check(tenant.shop_key("shopb@x.vn") == "shopb@x.vn", "I2 shop khác → não riêng")
check(tenant.shop_key(None) == "default", "I3 không ws → default")

print("J. Persona prompt per-shop")
from app.core import prompt_builder, claude_ai
# Patch file não default + backup sang file TẠM (house style test_prompt) —
# tuyệt đối không đụng data/custom_prompt.txt THẬT của máy dev
prompt_builder.CUSTOM_FILE = Path("test_tenant_custom_tmp.txt")
prompt_builder.BACKUP_DIR = Path("test_tenant_backups_tmp")
Path("test_tenant_custom_tmp.txt").unlink(missing_ok=True)
PERSONA_B = "#PERSONA-B " + "Shop B chuyên bán trà sữa, xưng em ngọt ngào. " * 6
prompt_builder.apply(PERSONA_B, shop="shopb@x.vn")
check(claude_ai._load_system_prompt("shopb@x.vn").startswith("#PERSONA-B"),
      "J1 shop B đọc đúng persona B")
check(not claude_ai._load_system_prompt("default").startswith("#PERSONA-B"),
      "J2 não default KHÔNG bị B đè")
check(claude_ai._custom_prompt_file("shopb@x.vn").name != "custom_prompt.txt",
      "J3 file persona B nằm riêng (data/prompts/)")
cur_b = prompt_builder.current(shop="shopb@x.vn")
check(cur_b["source"] == "custom", "J4 current(B) = custom")
cur_d = prompt_builder.current(shop="default")
check(cur_d["source"] == "default", "J5 current(default) vẫn mặc định")
prompt_builder.restore_default(shop="shopb@x.vn")
check(prompt_builder.current(shop="shopb@x.vn")["source"] == "default", "J6 restore chỉ đụng B")

print("K. Knowledge per-shop")
from app.core import knowledge
knowledge.ingest([{"title": "Giá trà sữa", "content": "Trà sữa 35k", "keywords": ["trà sữa"]}],
                 shop="shopb@x.vn")
hits_b, _ = knowledge.context_chunks("trà sữa giá nhiêu", shop="shopb@x.vn")
hits_d, _ = knowledge.context_chunks("trà sữa giá nhiêu", shop="default")
check(any("35k" in h["content"] for h in hits_b), "K1 shop B tra được tri thức B")
check(not any("35k" in (h.get("content") or "") for h in hits_d), "K2 não default không dính tri thức B")
check(knowledge.count("shopb@x.vn") == 1 and knowledge.count("default") == 0,
      "K3 kho đếm riêng từng shop")

print("L. Photo library per-shop")
from app.core import photo_library as pl
s_a = pl.create_set("Bảng giá", ["gia"], tenant_ws="shopa@x.vn")
s_b = pl.create_set("Bảng giá", ["gia"], tenant_ws="shopb@x.vn")
check(s_a["slug"] != s_b["slug"], "L1 2 shop cùng tên bộ ảnh → slug khác nhau",
      (s_a["slug"], s_b["slug"]))
names_b = [x["slug"] for x in pl.list_sets(tenant_ws="shopb@x.vn")]
check(names_b == [s_b["slug"]], "L2 list B chỉ thấy bộ của B", names_b)
check(pl.get_set(s_a["slug"], tenant_ws="shopb@x.vn") is None, "L3 B mở bộ ảnh A → None")

print("M. Bot học (suggestions) theo shop của hội thoại")
from app.core import knowledge_learn
import app.core.claude_ai as _cai2
_cai2_orig = _cai2._call_ai
_cai2._call_ai = lambda msgs: '{"title":"Ship","content":"Shop B ship toàn quốc 20k","keywords":["ship"]}'
try:
    sug = knowledge_learn.suggest_from_reply(
        "tg:BOTB:2", "telegram",
        [{"role": "user", "content": "shop có ship không vậy ạ?"}],
        "Bên mình ship toàn quốc, phí 20k bạn nhé!")
finally:
    _cai2._call_ai = _cai2_orig
check(sug and sug.get("shop") == "shopb@x.vn", "M1 đề xuất rơi vào kho shop B (resolve từ conv)", sug)

print("N. Notify per-shop")
from app.core import notify
notify.save_config("shopb@x.vn", {"emergency_phone": "0988888888", "share_mode": "ask"})
cfg_b = notify.get_config("shopb@x.vn")
cfg_a = notify.get_config("shopa@x.vn")
check(cfg_b["emergency_phone"] == "0988888888" and cfg_a["emergency_phone"] == "",
      "N1 liên hệ khẩn riêng từng shop")
from app.core.brain import _with_contact
out = _with_contact("Đã báo shop!", "contact_request", "shopb@x.vn")
check("0988888888" in out, "N2 khách của shop B nhận đúng số shop B", out)
out_a = _with_contact("Đã báo shop!", "contact_request", "shopa@x.vn")
check("0988888888" not in out_a, "N3 khách shop A KHÔNG nhận số shop B")

print("O. Admin API — chỉ chủ nền tảng")
from app.web_api.admin_api import register_admin_routes
adm = Flask(__name__)
register_admin_routes(adm)
ax = adm.test_client()
r = ax.get("/admin/shops", headers=HA)
check(r.status_code == 200 and r.json["total"] >= 2, "O1 chủ nền tảng xem được mọi shop", r.text[:80])
shops = {s["username"]: s for s in r.json["shops"]}
check(shops["shopb@x.vn"]["conversations"] == 1, "O2 đếm hội thoại đúng theo shop",
      shops["shopb@x.vn"])
r = ax.get("/admin/shops", headers=HB)
check(r.status_code == 403, "O3 shop thường bị 403")
r = ax.get("/admin/shops")
check(r.status_code == 401, "O4 không token → 401")
# Chi tiết 1 shop (read-only, KHÔNG lộ nội dung chat)
r = ax.get("/admin/shops/shopb@x.vn", headers=HA)
check(r.status_code == 200 and r.json["ok"], "O5 admin xem chi tiết shop B", r.text[:80])
check(r.json["conversations"]["total"] == 1 and r.json["orders"]["total"] >= 1,
      "O6 chi tiết đếm đúng hội thoại + đơn của B", r.json["orders"])
check("recent" in r.json["orders"] and "messages" not in r.text,
      "O7 chi tiết KHÔNG kèm nội dung chat")
r = ax.get("/admin/shops/shopb@x.vn", headers=HB)
check(r.status_code == 403, "O8 shop thường xem chi tiết → 403")
r = ax.get("/admin/shops/khongton@x.vn", headers=HA)
check(r.status_code == 404, "O9 shop không tồn tại → 404")
# Cấp / thu hồi gói (không trừ ví)
from app.core import billing as _bl
r = ax.post("/admin/shops/shopb@x.vn/plan", headers=HA,
            json={"action": "grant", "tier": "pro", "duration": "month"})
check(r.status_code == 200 and r.json["billing"]["tier"] == "pro"
      and r.json["billing"]["active"], "O10 admin cấp gói Pro/tháng cho B", r.text[:100])
r = ax.post("/admin/shops/shopb@x.vn/plan", headers=HB,
            json={"action": "grant", "tier": "pro", "duration": "month"})
check(r.status_code == 403, "O11 shop thường cấp gói → 403")
r = ax.post("/admin/shops/shopb@x.vn/plan", headers=HA, json={"action": "revoke"})
check(r.status_code == 200 and not r.json["billing"]["active"],
      "O12 admin thu hồi gói → hết hạn ngay", r.text[:100])
# Chặn / bỏ chặn shop
r = ax.post("/admin/shops/shopa@x.vn/block", headers=HA, json={"blocked": True})
check(r.status_code == 400, "O13 không chặn được chủ nền tảng")
r = ax.post("/admin/shops/shopb@x.vn/block", headers=HA, json={"blocked": True})
check(r.status_code == 200 and r.json["blocked"], "O14 chặn shop B")
check(_bl.is_blocked("shopb@x.vn") and not _bl.can_reply("shopb@x.vn"),
      "O15 shop bị chặn → bot ngừng trả lời")
r = ac.post("/auth/login", json={"username": "shopb@x.vn", "password": "1234"})
check(r.status_code == 403, "O16 shop bị chặn không đăng nhập được", r.status_code)
r = ax.get("/admin/shops", headers=HB)
check(r.status_code == 401, "O17 token cũ của shop bị chặn vô hiệu")
r = ax.post("/admin/shops/shopb@x.vn/block", headers=HA, json={"blocked": False})
check(r.status_code == 200 and not r.json["blocked"], "O18 bỏ chặn shop B")
r = ac.post("/auth/login", json={"username": "shopb@x.vn", "password": "1234"})
check(r.status_code == 200 and r.json["ok"], "O19 bỏ chặn → đăng nhập lại OK")
# Não bot (prompt + dữ liệu + ảnh) read-only cho admin
r = ax.get("/admin/shops/shopb@x.vn/brain", headers=HA)
check(r.status_code == 200 and r.json["ok"] and r.json["shop_key"] == "shopb@x.vn"
      and len(r.json["photos"]) >= 1 and "prompt" in r.json and "knowledge" in r.json,
      "O20 admin xem não bot shop B (prompt/dữ liệu/ảnh)", r.text[:120])
r = ax.get("/admin/shops/shopb@x.vn/brain")
check(r.status_code == 401, "O21 não bot không token → 401")

# dọn file persona + ảnh test + file tạm
try:
    import shutil
    claude_ai._custom_prompt_file("shopb@x.vn").unlink(missing_ok=True)
    pl.delete_set(s_a["slug"]); pl.delete_set(s_b["slug"])
    Path("test_tenant_custom_tmp.txt").unlink(missing_ok=True)
    shutil.rmtree("test_tenant_backups_tmp", ignore_errors=True)
except Exception:
    pass

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
