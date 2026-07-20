#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_payment.py — QR động (Phase 2) + đối soát tiền tự động (Phase 3):
  - bank info: set/get (sanitize), get() lấy user đầu tiên đã khai
  - build_vietqr_url: nhúng amount + addInfo + accountName, encode đúng
  - parse_webhook: format SePay + Casso, bỏ tiền RA (out), thiếu field
  - process_transfer: DHxxxx → paid + timeline + notify; đơn đã paid → chỉ báo;
    NAPxxxx → billing.confirm_deposit; không khớp → ignore
  - Channel.send_image_url: default text+link; telegram sendPhoto URL
  - brain: chốt đơn + có bank → gửi QR khách + đơn awaiting_payment
  - API: /payhook (API key), /orders/bank (Bearer)

Chạy (TỪ GỐC):  python tests/test_payment.py
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
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tmp.sqlite')
os.environ.setdefault('REPLY_DELAY', '0')
sys.path.insert(0, '.')

import json
from flask import Flask
from app.core import payments as pay
from app.core import orders as od
from app.core.db import get_db
import app.web_api.auth_api as auth_mod
import app.web_api.payment_api as pay_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
db.execute("DELETE FROM orders")
for t in ("users", "auth_tokens", "deposits", "billing"):
    db.execute(f"DELETE FROM {t}")

print("\n── A. bank info + VietQR URL ──")
# tạo user (qua auth) rồi set bank
flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
pay_mod.register_payment_routes(flask_app, notify_fn=None)
api = flask_app.test_client()
tok = api.post("/auth/register", json={"username": "pay@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

pay.set_bank("pay@x.vn", "mb ", " 0901 234 567", "nguyễn văn a")
b = pay.get_bank("pay@x.vn")
check(b["bank_code"] == "MB" and b["bank_account"] == "0901234567", "A1 set_get_sanitized", b)
check(b["bank_holder"] == "NGUYỄN VĂN A", "A2 holder_upper", b)
# get() không username → user đầu tiên đã khai
check(pay.get_bank()["bank_code"] == "MB", "A3 default_first_user")

url = pay.build_vietqr_url(b, amount=380000, memo="DH0042")
check(url.startswith("https://img.vietqr.io/image/MB-0901234567-compact2.png?"), "A4 qr_base", url)
check("amount=380000" in url and "addInfo=DH0042" in url, "A5 qr_params", url)
check("accountName=" in url and "%20" in url, "A6 qr_name_encoded", url)
# không amount/memo → URL vẫn hợp lệ
check("?" not in pay.build_vietqr_url({"bank_code": "MB", "bank_account": "1"},), "A7 qr_no_params")

print("\n── B. parse_webhook ──")
# SePay tiền VÀO
txs = pay.parse_webhook({"content": "CK DH0042 dat coc", "transferAmount": 190000, "transferType": "in"})
check(txs == [("CK DH0042 dat coc", 190000)], "B1 sepay_in", txs)
# SePay tiền RA → bỏ
check(pay.parse_webhook({"content": "x", "transferAmount": 5, "transferType": "out"}) == [], "B2 sepay_out_skip")
# Casso
txs = pay.parse_webhook({"data": [
    {"description": "NAPABC123 nap vi", "amount": 500000},
    {"description": "thieu tien", "amount": 0},
]})
check(txs == [("NAPABC123 nap vi", 500000)], "B3 casso", txs)
check(pay.parse_webhook({}) == [], "B4 empty_ok")

print("\n── C. process_transfer ──")
o = od.create(channel="zalo", customer_name="Chị Hoa", total=380000,
              status="awaiting_payment", order_type="booking")
notes = []
r = pay.process_transfer(f"NHAN CK {o['code']} tu khach", 380000, notes.append)
check(r["matched"] == "order" and od.get(o["id"])["status"] == "paid", "C1 order_paid", r)
check(any("Nhận CK 380,000đ" in e["event"] for e in od.get(o["id"])["timeline"]), "C2 timeline_logged")
check(notes and "ĐÃ NHẬN TIỀN" in notes[0] and "đủ" in notes[0], "C3 notify_full", notes)

# cọc 50% (đơn khác) → vẫn paid nhưng báo số nhận/tổng
o2 = od.create(channel="zalo", total=400000, status="awaiting_payment")
notes.clear()
pay.process_transfer(f"coc {o2['code']}", 200000, notes.append)
check("200,000đ/400,000đ" in notes[0], "C4 partial_reported", notes)

# đơn đã paid nhận thêm → không đổi trạng thái, chỉ báo
notes.clear()
r = pay.process_transfer(f"them tien {o['code']}", 50000, notes.append)
check(r.get("already") == "paid" and od.get(o["id"])["status"] == "paid", "C5 already_paid", r)

# mã nạp ví NAPxxxx → billing.confirm_deposit
from app.core import billing
billing.ensure_billing("pay@x.vn")
dep = billing.create_deposit("pay@x.vn", 500000)
notes.clear()
r = pay.process_transfer(f"chuyen khoan {dep['code']} nap vi", 500000, notes.append)
check(r["matched"] == "deposit" and r["amount"] == 500000, "C6 deposit_confirmed", r)
check(billing.status("pay@x.vn")["balance"] == 500000, "C7 wallet_credited")
# xác nhận lần 2 → không khớp nữa (đã confirmed)
r = pay.process_transfer(f"lap lai {dep['code']}", 500000, notes.append)
check(r["matched"] is None, "C8 deposit_once")

# BẢO MẬT: tạo lệnh nạp 100tr, chỉ chuyển 10k đúng mã → ví CHỈ được cộng 10k
# (không tin số ở lệnh nạp) — chống lỗ hổng "chuyển 10k, ví +100tr".
bal0 = billing.status("pay@x.vn")["balance"]
big = billing.create_deposit("pay@x.vn", 100_000_000)
r = pay.process_transfer(f"nap {big['code']}", 10_000, notes.append)
check(r["matched"] == "deposit" and r["amount"] == 10_000, "C8b credit_actual_amount", r)
check(billing.status("pay@x.vn")["balance"] == bal0 + 10_000, "C8c no_overcredit",
      billing.status("pay@x.vn")["balance"])

# không khớp gì → ignore
check(pay.process_transfer("mua tra sua", 30000, notes.append)["matched"] is None, "C9 no_match")

print("\n── D. Channel.send_image_url ──")
from app.core.channel import Channel
class Dummy(Channel):
    def __init__(self): self.sent = []
    def send_text(self, u, t): self.sent.append(t)
    def send_room_photos(self, u, r): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass
d = Dummy()
d.send_image_url("u1", "https://img.vietqr.io/x.png", "Quét QR nhé")
check(d.sent == ["Quét QR nhé\nhttps://img.vietqr.io/x.png"], "D1 default_text_link", d.sent)

with patch.dict(sys.modules, {'requests': MagicMock()}):
    from app.channels.telegram import TelegramChannel
    tgc = TelegramChannel.__new__(TelegramChannel)
    tgc._parse = lambda u: ("b", "chat9")
    tgc._token_for = lambda b: "TOK"
    posts = []
    tgc._post = lambda tok, method, payload: posts.append((method, payload))
    tgc.send_image_url("u", "http://qr.png", "cap")
    check(posts == [("sendPhoto", {"chat_id": "chat9", "photo": "http://qr.png", "caption": "cap"})],
          "D2 telegram_photo_url", posts)

print("\n── E. brain gửi QR sau chốt ──")
db.execute("DELETE FROM orders")
from app.core.conversation import ConversationManager
from app.core.brain import Brain

class FakeCh(Channel):
    def __init__(self): self.texts = []; self.images = []; self.notices = []
    def send_text(self, u, t): self.texts.append(t)
    def send_image_url(self, u, url, caption=""): self.images.append((url, caption))
    def send_room_photos(self, u, r): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): self.notices.append(t)
    def call_owner(self): pass

class _SyncThread:
    def __init__(self, target=None, daemon=None, **kw): self._t = target
    def start(self):
        if self._t: self._t()

cm = ConversationManager(account="zalo")
cm._sessions.clear()
ch = FakeCh()
brain = Brain(channel=ch, conv_manager=cm)
conv = cm.get("kh1")
conv.add_user_message("chốt phòng 301 nhé")
conv.selected_room = "301"; conv.checkin = "25/12/2026"; conv.name = "Hoa"

FAKE = json.dumps({"customer_name": "Hoa", "phone": "", "order_type": "booking",
                   "items": [{"name": "Phòng 301", "qty": 1, "price": 330000}],
                   "total": 330000, "due_at": None, "note": ""})
import threading as _th
with patch.object(__import__('app.core.claude_ai', fromlist=['_call_ai']), '_call_ai',
                  return_value=FAKE), \
     patch.object(_th, 'Thread', _SyncThread):
    brain._handle_booking_confirmed("kh1", conv, "chốt nha")

r = od.list_orders()
check(r["total"] == 1, "E1 order_created", r)
o = r["items"][0]
check(o["status"] == "awaiting_payment", "E2 status_awaiting", o["status"])
check(len(ch.images) == 1 and "amount=330000" in ch.images[0][0]
      and f"addInfo={o['code']}" in ch.images[0][0], "E3 qr_sent_with_code", ch.images)
check(any("QR thanh toán" in e["event"] for e in o["timeline"]), "E4 qr_event_logged")

# Chưa khai bank → dừng ở đơn nháp, KHÔNG gửi QR
db.execute("DELETE FROM orders")
db.execute("UPDATE users SET bank_code='', bank_account=''")
ch2 = FakeCh()
brain2 = Brain(channel=ch2, conv_manager=cm)
conv2 = cm.get("kh2"); conv2.add_user_message("chốt đi"); conv2.stage = "greeting"
with patch.object(__import__('app.core.claude_ai', fromlist=['_call_ai']), '_call_ai',
                  return_value=FAKE), \
     patch.object(_th, 'Thread', _SyncThread):
    brain2._handle_booking_confirmed("kh2", conv2, "ok")
o = od.list_orders()["items"][0]
check(o["status"] == "draft" and ch2.images == [], "E5 no_bank_stays_draft", o["status"])

print("\n── F. API /payhook + /orders/bank ──")
pay.set_bank("pay@x.vn", "MB", "0901234567", "NGUYEN VAN A")   # khai lại cho F
db.execute("DELETE FROM orders")
o = od.create(total=100000, status="awaiting_payment")

# payhook không cần Bearer
r = api.post("/payhook", json={"content": f"ck {o['code']}", "transferAmount": 100000,
                               "transferType": "in"})
check(r.status_code == 200 and r.get_json()["processed"] == 1
      and od.get(o["id"])["status"] == "paid", "F1 payhook_processes", r.get_json())
check(api.get("/payhook").status_code == 200, "F2 payhook_alive")

# API key: đặt SEPAY_API_KEY → sai key bị 401
from app.core.config import Config
with patch.object(Config, 'SEPAY_API_KEY', 'secret99'):
    r = api.post("/payhook", json={}, headers={"Authorization": "Apikey sai"})
    check(r.status_code == 401, "F3 wrong_key_401")
    r = api.post("/payhook", json={}, headers={"Authorization": "Apikey secret99"})
    check(r.status_code == 200, "F4 right_key_ok")

# /orders/bank
check(api.get("/orders/bank").status_code == 401, "F5 bank_needs_auth")
r = api.get("/orders/bank", headers=H)
check(r.get_json()["bank"]["bank_code"] == "MB" and "img.vietqr.io" in r.get_json()["sample_qr"],
      "F6 bank_get")
r = api.post("/orders/bank", json={"bank_code": "VCB", "bank_account": "999", "bank_holder": "B"}, headers=H)
check(r.get_json()["bank"]["bank_code"] == "VCB", "F7 bank_set")
check(api.post("/orders/bank", json={"bank_code": "VCB"}, headers=H).status_code == 400, "F8 bank_missing_400")

# Dọn
db.execute("DELETE FROM orders")
for t in ("users", "auth_tokens", "deposits", "billing"):
    db.execute(f"DELETE FROM {t}")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
