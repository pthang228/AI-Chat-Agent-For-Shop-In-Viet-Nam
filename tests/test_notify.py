#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_notify.py — LIÊN HỆ KHẨN CẤP & THÔNG BÁO (thay tự-gọi-điện):
  A. get_config mặc định + save_config upsert + chuẩn hoá giá trị lạ
  B. contact_line / contact_for theo share_mode × intent
  C. event_mode + alert() gate notify_owner/call theo off|notify|call
  D. API /notify/config GET/POST (bare Flask)
  E. brain e2e: booking (new_order) mặc định KHÔNG gọi; contact_request đưa số + gọi;
     unknown đưa số khi share_mode=ask; greeting kèm số khi mode=greeting

Chạy TỪ GỐC: python tests/test_notify.py
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
os.environ.setdefault('REPLY_DELAY', '0')
os.environ['HOMESTAY_DB_PATH'] = 'test_db_notify_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from pathlib import Path
for suf in ("", "-wal", "-shm"):
    Path(f"test_db_notify_tmp.sqlite{suf}").unlink(missing_ok=True)

from datetime import datetime
from app.core.db import get_db
from app.core import notify

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


# seed 1 chủ shop
db = get_db()
db.execute("INSERT INTO users(username, homestay, provider, role, created_at) "
           "VALUES ('chu@shop.vn','Shop','password','owner',?)", (datetime.now().isoformat(),))

# ── A. get/save config ───────────────────────────────────────────────
print("A. get/save config")
cfg = notify.get_config()
check(cfg["username"] == "chu@shop.vn", "A1 single-tenant lấy chủ đầu tiên")
check(cfg["share_mode"] == "ask" and cfg["events"]["contact_request"] == "call",
      "A2 mặc định share=ask, contact_request=call", cfg["events"])
check(cfg["events"]["new_order"] == "notify", "A3 mặc định new_order=notify (KHÔNG gọi)")

cfg2 = notify.save_config("chu@shop.vn", {
    "emergency_phone": "0901234567", "emergency_zalo": "0901234567",
    "share_mode": "greeting",
    "events": {"new_order": "call", "unknown": "off", "xxx_lạ": "call", "contact_request": "sai_giá_trị"},
})
check(cfg2["emergency_phone"] == "0901234567" and cfg2["share_mode"] == "greeting", "A4 lưu liên hệ + mode")
check(cfg2["events"]["new_order"] == "call", "A5 lưu event new_order=call")
check(cfg2["events"]["unknown"] == "off", "A6 lưu event unknown=off")
check("xxx_lạ" not in cfg2["events"], "A7 bỏ event key lạ")
check(cfg2["events"]["contact_request"] == "call", "A8 giá trị lạ giữ nguyên mặc định call")
cfg3 = notify.save_config("chu@shop.vn", {"share_mode": "linh_tinh"})
check(cfg3["share_mode"] == "greeting", "A9 share_mode lạ → giữ giá trị cũ")

# ── B. liên hệ khẩn cho khách ────────────────────────────────────────
print("B. contact_line / contact_for")
notify.save_config("chu@shop.vn", {
    "emergency_phone": "0901234567", "emergency_zalo": "", "emergency_tele": "@shop",
    "share_mode": "ask"})
line = notify.contact_line()
check("0901234567" in line and "@shop" in line and "Zalo" not in line,
      "B1 contact_line chỉ gồm field có nhập", line)

# share_mode=ask: contact_request YES, unknown YES, greeting NO
check(notify.contact_for("contact_request") != "", "B2 ask: contact_request đưa số")
check(notify.contact_for("unknown_question") != "", "B3 ask: bot bí đưa số")
check(notify.contact_for("greeting") == "", "B4 ask: greeting KHÔNG đưa")

notify.save_config("chu@shop.vn", {"share_mode": "strict"})
check(notify.contact_for("contact_request") != "", "B5 strict: khách hỏi thẳng vẫn đưa")
check(notify.contact_for("unknown_question") == "", "B6 strict: bot bí KHÔNG đưa")

notify.save_config("chu@shop.vn", {"share_mode": "greeting"})
check(notify.contact_for("greeting") != "", "B7 greeting: tin chào đưa số")

notify.save_config("chu@shop.vn", {"share_mode": "off"})
check(notify.contact_for("contact_request") == "", "B8 off: không bao giờ đưa")

# chưa nhập liên hệ nào → rỗng dù mode bật
notify.save_config("chu@shop.vn", {"emergency_phone": "", "emergency_tele": "", "share_mode": "ask"})
check(notify.contact_for("contact_request") == "", "B9 chưa nhập liên hệ → rỗng")

# ── C. alert() gate ──────────────────────────────────────────────────
print("C. event_mode + alert()")
class FakeCh:
    def __init__(self): self.notified = []; self.called = 0
    def notify_owner(self, m): self.notified.append(m)
    def call_owner(self): self.called += 1

notify.save_config("chu@shop.vn", {"events": {"new_order": "off", "contact_request": "call", "unknown": "notify"}})
ch = FakeCh()
notify.alert(ch, "new_order", "msg")
check(ch.notified == [] and ch.called == 0, "C1 new_order=off → không báo, không gọi")
notify.alert(ch, "unknown", "msg unknown")
check(ch.notified == ["msg unknown"] and ch.called == 0, "C2 unknown=notify → nhắn, không gọi")
notify.alert(ch, "contact_request", "msg contact")
check(len(ch.notified) == 2 and ch.called == 1, "C3 contact_request=call → nhắn + gọi")
# notify_owner nổ không được làm chết luồng
class BoomCh(FakeCh):
    def notify_owner(self, m): raise RuntimeError("kênh chết")
notify.alert(BoomCh(), "unknown", "x")   # không raise
check(True, "C4 notify_owner nổ → nuốt lỗi, không raise")

# ── D. API ───────────────────────────────────────────────────────────
print("D. API /notify/config")
from flask import Flask
from app.web_api.notify_api import register_notify_routes
from app.web_api.auth_api import register_auth_routes
api = Flask(__name__)
register_auth_routes(api)
register_notify_routes(api)
c = api.test_client()
# đăng nhập lấy token (auth guard tắt nhưng current_username đọc Bearer)
db.execute("UPDATE users SET password_hash=? WHERE username='chu@shop.vn'",
           (__import__("app.web_api.auth_api", fromlist=["hash_password"]).hash_password("1234"),))
tok = c.post("/auth/login", json={"username": "chu@shop.vn", "password": "1234"}).json["token"]
H = {"Authorization": f"Bearer {tok}"}
r = c.get("/notify/config", headers=H)
check(r.status_code == 200 and "config" in r.json and "events_meta" in r.json, "D1 GET config + meta")
r = c.get("/notify/config")
check(r.status_code == 401, "D2 GET không token → 401")
r = c.post("/notify/config", json={"emergency_phone": "0988", "share_mode": "strict",
                                   "events": {"new_order": "call"}}, headers=H)
check(r.status_code == 200 and r.json["config"]["emergency_phone"] == "0988"
      and r.json["config"]["share_mode"] == "strict", "D3 POST lưu")
check(notify.get_config()["events"]["new_order"] == "call", "D4 lưu xuống DB thật")

# ── E. brain e2e ─────────────────────────────────────────────────────
print("E. brain e2e")
from app.core.conversation import ConversationManager
from app.core.channel import Channel
import app.core.claude_ai as claude_ai
from app.core.brain import Brain

class BrainCh(Channel):
    def __init__(self): self.texts=[]; self.notified=[]; self.called=0; self.price=0
    def send_text(self, uid, t): self.texts.append(t)
    def send_room_photos(self, uid, n): pass
    def send_price_photos(self, uid): self.price += 1
    def notify_owner(self, m): self.notified.append(m)
    def call_owner(self): self.called += 1

cm = ConversationManager(account="notify_test"); cm._sessions.clear()

def run(uid, text, intent, reply="reply", confirmed=False):
    def fake(*a, **kw):
        return {"intent": intent, "reply": reply, "booking_confirmed": confirmed,
                "checkin": None, "checkout": None, "room": None}
    orig = claude_ai.analyze_message
    claude_ai.analyze_message = fake
    import app.core.brain as bmod
    bmod.analyze_message = fake
    try:
        ch = BrainCh(); Brain(channel=ch, conv_manager=cm).handle(uid, text)
        return ch
    finally:
        claude_ai.analyze_message = orig; bmod.analyze_message = orig

# contact_request: mode=ask (đưa số), event=call
notify.save_config("chu@shop.vn", {"emergency_phone": "0901234567", "share_mode": "ask",
                                   "events": {"contact_request": "call", "new_order": "notify", "unknown": "notify"}})
ch = run("u_contact", "cho gặp chủ", "contact_request")
check(any("0901234567" in t for t in ch.texts), "E1 contact_request: khách nhận số khẩn", ch.texts)
check(ch.called == 1 and len(ch.notified) == 1, "E2 contact_request event=call → gọi + nhắn")

# new_order mặc định notify → KHÔNG gọi (điểm mấu chốt scale)
ch = run("u_book", "đặt phòng 301", "booking", reply="", confirmed=True)
check(ch.called == 0 and len(ch.notified) >= 1, "E3 booking new_order=notify → CHỈ nhắn, KHÔNG gọi", (ch.called, ch.notified))

# new_order = call → có gọi
notify.save_config("chu@shop.vn", {"events": {"new_order": "call"}})
ch = run("u_book2", "đặt phòng 302", "booking", reply="", confirmed=True)
check(ch.called == 1, "E4 booking new_order=call → có gọi", ch.called)

# unknown: mode=ask đưa số
notify.save_config("chu@shop.vn", {"share_mode": "ask", "events": {"unknown": "notify"}})
ch = run("u_unk", "trái đất hình gì", "unknown_question", reply="")
check(any("0901234567" in t for t in ch.texts), "E5 unknown share=ask → đưa số", ch.texts)
check(ch.called == 0, "E6 unknown=notify → không gọi")

# greeting kèm số khi mode=greeting (khách mới, tin đầu)
notify.save_config("chu@shop.vn", {"share_mode": "greeting"})
cm._sessions.clear()
ch = run("u_new", "chào shop", "other")
check(any("0901234567" in t for t in ch.texts), "E7 greeting mode → tin chào kèm số", ch.texts[:1])

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
