#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_shops.py — SHOP CON (nhiều shop trong 1 tài khoản, mỗi shop 1 workspace):
  A. shops core: default/create/rename/remove/account_of/is_shop_of
  B. API /auth/shops CRUD + phân quyền staff
  C. /auth/apps theo shop (X-Shop) + MỖI SHOP 1 BOT MỖI LOẠI (409, nhóm meta)
  D. X-Shop IDOR: tài khoản khác / staff — không đổi được workspace sang shop lạ
  E. Billing dùng chung: account_of, channel_gate/tier_of không tạo billing shop con
  F. Broadcast theo shop: created_by = ws shop, audience đúng tenant

Chạy TỪ GỐC: python tests/test_shops.py  (cần PYTHONIOENCODING=utf-8)
"""

import os, sys
from unittest.mock import MagicMock

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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_shops_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    _P(str(_TMPDIR / f"test_db_shops_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime
from flask import Flask

from app.core.db import get_db
from app.core import shops, billing, broadcast
from app.web_api.auth_api import register_auth_routes
from app.web_api.broadcast_api import register_broadcast_routes

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
api = Flask(__name__)
register_auth_routes(api)
register_broadcast_routes(api)
c = api.test_client()

# ── Tạo 2 tài khoản chủ + 1 nhân viên qua API thật ───────────────────
def make_user(username, password="matkhau123"):
    r = c.post("/auth/register", json={"username": username, "password": password})
    assert r.status_code == 200 and r.json.get("token"), f"register {username}: {r.text}"
    return r.json["token"]

TOK_A = make_user("chua@shop.vn")
TOK_B = make_user("chub@shop.vn")
# nhân viên của A (INSERT thẳng — luồng mời staff test ở test_team)
db.execute("INSERT INTO users (username, password_hash, created_at, role, owner_username)"
           " VALUES ('nv@a.vn', 'x', ?, 'staff', 'chua@shop.vn')",
           (datetime.now().isoformat(),))
db.execute("INSERT INTO auth_tokens (token, username, created_at) VALUES"
           " ('TOK_STAFF', 'nv@a.vn', ?)", (datetime.now().isoformat(),))

def H(tok, shop=None):
    h = {"Authorization": f"Bearer {tok}"}
    if shop is not None:
        h["X-Shop"] = shop
    return h

# ── A. shops core ────────────────────────────────────────────────────
print("A. shops core")
ls = shops.list_for("chua@shop.vn")
check(len(ls) == 1 and ls[0]["ws"] == "chua@shop.vn" and ls[0]["is_default"],
      "A1 list tự tạo shop mặc định (ws = username)", ls)
s2 = shops.create("chua@shop.vn", "Homestay Vũng Tàu")
check(s2["ws"].startswith("chua@shop.vn~s") and not s2["is_default"], "A2 create ws dạng owner~s", s2)
ls = shops.list_for("chua@shop.vn")
check(len(ls) == 2 and ls[0]["is_default"], "A3 list 2 shop, mặc định đứng đầu", ls)
check(shops.rename("chua@shop.vn", s2["ws"], "VT Beach"), "A4 rename")
check(not shops.rename("chub@shop.vn", s2["ws"], "hack"), "A5 rename bởi account khác → False")
check(shops.account_of(s2["ws"]) == "chua@shop.vn", "A6 account_of shop con → owner")
check(shops.account_of("chua@shop.vn") == "chua@shop.vn", "A7 account_of username → giữ nguyên")
check(shops.account_of("la~la") == "la~la", "A8 account_of ws lạ có ~ → giữ nguyên")
check(shops.is_shop_of(s2["ws"], "chua@shop.vn"), "A9 is_shop_of đúng chủ")
check(not shops.is_shop_of(s2["ws"], "chub@shop.vn"), "A10 is_shop_of sai chủ → False")
ok, msg = shops.remove("chua@shop.vn", "chua@shop.vn")
check(not ok and "mặc định" in msg, "A11 không xoá được shop mặc định", msg)

# ── B. API /auth/shops ───────────────────────────────────────────────
print("B. API /auth/shops")
r = c.get("/auth/shops", headers=H(TOK_A))
check(r.status_code == 200 and len(r.json) == 2, "B1 list qua API", r.text)
r = c.post("/auth/shops", json={"name": "Shop 3"}, headers=H(TOK_A))
check(r.status_code == 200 and r.json["shop"]["ws"].startswith("chua@shop.vn~s"),
      "B2 tạo shop qua API", r.text)
ws3 = r.json["shop"]["ws"]
r = c.post("/auth/shops", json={"name": ""}, headers=H(TOK_A))
check(r.status_code == 400, "B3 tạo shop không tên → 400")
r = c.post(f"/auth/shops/{ws3}/rename", json={"name": "Shop Ba"}, headers=H(TOK_A))
check(r.status_code == 200, "B4 rename qua API", r.text)
r = c.post("/auth/shops", json={"name": "x"}, headers=H("TOK_STAFF"))
check(r.status_code == 403, "B5 staff tạo shop → 403")
r = c.get("/auth/shops", headers=H("TOK_STAFF"))
check(r.status_code == 200 and len(r.json) == 3, "B6 staff THẤY shop của chủ", r.text)
r = c.delete(f"/auth/shops/{ws3}", headers=H(TOK_A))
check(r.status_code == 200, "B7 xoá shop rỗng OK", r.text)
r = c.delete("/auth/shops/chua@shop.vn", headers=H(TOK_A))
check(r.status_code == 400, "B8 xoá shop mặc định → 400")

# ── C. /auth/apps theo shop + 1 bot mỗi loại ─────────────────────────
print("C. apps theo shop + 1 bot mỗi loại")
r = c.post("/auth/apps", json={"name": "Zalo nhà", "channel": "zalo"}, headers=H(TOK_A))
check(r.status_code == 200, "C1 thêm zalo shop mặc định", r.text)
r = c.post("/auth/apps", json={"name": "Zalo nữa", "channel": "zalo"}, headers=H(TOK_A))
check(r.status_code == 409, "C2 thêm zalo LẦN 2 cùng shop → 409", r.text)
r = c.post("/auth/apps", json={"name": "Zalo nhà", "channel": "zalo"}, headers=H(TOK_A))
check(r.status_code == 200 and r.json.get("duplicated"),
      "C3 trùng cả tên+kênh (migrate chạy lại) → trả app cũ", r.text)
r = c.post("/auth/apps", json={"name": "Page", "channel": "meta"}, headers=H(TOK_A))
check(r.status_code == 200, "C4 thêm meta OK")
r = c.post("/auth/apps", json={"name": "IG", "channel": "instagram"}, headers=H(TOK_A))
check(r.status_code == 409, "C5 instagram khi đã có meta (cùng nhóm) → 409", r.text)
r = c.get("/auth/apps", headers=H(TOK_A))
check(len(r.json) == 2, "C6 shop mặc định có 2 app", r.json)
# shop 2: danh sách RỖNG, thêm zalo riêng của nó OK
r = c.get("/auth/apps", headers=H(TOK_A, s2["ws"]))
check(r.json == [], "C7 shop 2 chưa có app (độc lập)", r.json)
r = c.post("/auth/apps", json={"name": "Zalo VT", "channel": "zalo"}, headers=H(TOK_A, s2["ws"]))
check(r.status_code == 200, "C8 shop 2 thêm zalo riêng OK (không đụng shop 1)", r.text)
r = c.get("/auth/apps", headers=H(TOK_A, s2["ws"]))
check(len(r.json) == 1 and r.json[0]["name"] == "Zalo VT", "C9 shop 2 thấy đúng app mình")
r = c.get("/auth/apps", headers=H(TOK_A))
check(len(r.json) == 2, "C10 shop mặc định vẫn 2 app — không lẫn")

# ── D. X-Shop IDOR ───────────────────────────────────────────────────
print("D. X-Shop IDOR")
r = c.get("/auth/apps", headers=H(TOK_B, s2["ws"]))
check(r.json == [], "D1 account B mượn X-Shop của A → về workspace B (rỗng)", r.json)
r = c.post("/auth/apps", json={"name": "Hack", "channel": "zalo"}, headers=H(TOK_B, s2["ws"]))
check(r.status_code == 200, "D2 B thêm app với X-Shop lạ → rơi về shop B")
rows = db.query("SELECT username, shop_ws FROM user_apps WHERE name='Hack'")
check(rows[0]["username"] == "chub@shop.vn" and rows[0]["shop_ws"] == "",
      "D3 app đó nằm ở shop mặc định CỦA B, không dính shop A", dict(rows[0]))
r = c.get("/auth/apps", headers=H("TOK_STAFF", s2["ws"]))
check(len(r.json) == 1 and r.json[0]["name"] == "Zalo VT",
      "D4 staff của A chuyển sang shop 2 của A được (đúng quyền)", r.json)

# ── E. Billing dùng chung tài khoản ──────────────────────────────────
print("E. billing dùng chung")
check(billing.account_of(s2["ws"]) == "chua@shop.vn", "E1 billing.account_of → owner")
t1 = billing.tier_of(s2["ws"]); t2 = billing.tier_of("chua@shop.vn")
check(t1 == t2, "E2 tier shop con = tier tài khoản", (t1, t2))
billing.channel_gate(s2["ws"])   # gate 1 tin đến kênh của shop con
rows = db.query("SELECT username FROM billing")
check(all("~s" not in r["username"] for r in rows),
      "E3 channel_gate KHÔNG tạo dòng billing cho shop con", [r["username"] for r in rows])
b_owner = db.query("SELECT ai_used FROM billing WHERE username='chua@shop.vn'")
check(b_owner and b_owner[0]["ai_used"] >= 1, "E4 lượt AI của shop con trừ vào quota tài khoản",
      dict(b_owner[0]) if b_owner else None)

# ── F. Broadcast theo shop ───────────────────────────────────────────
print("F. broadcast theo shop")
db.execute("INSERT OR REPLACE INTO sessions (account, user_id, name, stage, owner_active,"
           " last_updated, messages, tenant) VALUES ('zalooa','oa:X:1','K1','greeting',0,?,"
           "'[]',?)", (datetime.now().isoformat(), s2["ws"]))
db.execute("INSERT OR REPLACE INTO sessions (account, user_id, name, stage, owner_active,"
           " last_updated, messages, tenant) VALUES ('zalooa','oa:Y:2','K2','greeting',0,?,"
           "'[]','chua@shop.vn')", (datetime.now().isoformat(),))
a = broadcast.audience(["zalooa"], {"type": "all"}, tenant_ws=s2["ws"])
check([x["user_id"] for x in a] == ["oa:X:1"], "F1 audience chỉ khách của shop 2", a)
r = c.post("/broadcasts", json={"message": "Tin cho khách shop 2 nè", "channels": ["zalooa"]},
           headers=H(TOK_A, s2["ws"]))
check(r.status_code == 200 and r.json["broadcast"]["created_by"] == s2["ws"],
      "F2 campaign created_by = ws shop 2", r.text)
r = c.get("/broadcasts", headers=H(TOK_A))
names = [b["created_by"] for b in r.json]
check(s2["ws"] not in names, "F3 shop mặc định KHÔNG thấy campaign của shop 2", names)
r = c.get("/broadcasts", headers=H(TOK_A, s2["ws"]))
check(len(r.json) == 1 and r.json[0]["created_by"] == s2["ws"],
      "F4 shop 2 thấy đúng campaign của mình", r.text)

# ── G. Liên hệ khẩn (Cài đặt gọi điện) theo shop ─────────────────────
print("G. notify config theo shop")
from app.core import notify
notify.save_config("chua@shop.vn", {"emergency_phone": "0900111222", "share_mode": "strict"})
cfg = notify.get_config(s2["ws"])
check(cfg["emergency_phone"] == "0900111222",
      "G1 shop con CHƯA lưu riêng → fallback SĐT tài khoản chính", cfg["emergency_phone"])
notify.save_config(s2["ws"], {"emergency_phone": "0900333444"})
cfg = notify.get_config(s2["ws"])
check(cfg["emergency_phone"] == "0900333444", "G2 shop con lưu riêng → bản riêng thắng")
cfg = notify.get_config("chua@shop.vn")
check(cfg["emergency_phone"] == "0900111222", "G3 config tài khoản chính không bị đè")
check(notify.contact_for("contact_request", notify.get_config(s2["ws"])) != "",
      "G4 khách shop con hỏi gặp chủ → có dòng liên hệ")

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
