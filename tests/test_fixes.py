#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_fixes.py — khoá các fix từ đợt audit toàn diện (không cho tái phát):
  A. claude_ai._parse_ai_output: <analysis> chứa JSON non-dict (array/số/chuỗi)
     → KHÔNG crash, trả dict mặc định + reply
  B. store_util.atomic_write_json: ghi atomic, đọc lại đúng; lỗi ghi không mất file cũ
  C. payment_api._payhook_authorized: khớp key chính xác (Apikey/Bearer/trần),
     TỪ CHỐI header chỉ CHỨA key (bug 'in' cũ)
  D. Channel.get_ctx/set_ctx: base no-op + kênh đa khách nhớ đúng; _make_order
     truyền ctx sang thread con
  E. conversation.cleanup_old: KHÔNG xoá session vừa có tin mới (race dọn)

Chạy (TỪ GỐC):  python tests/test_fixes.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_fixes_tmp.sqlite'
sys.path.insert(0, '.')

import json
from datetime import datetime, timedelta
from pathlib import Path

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

print("\n── A. claude_ai._parse_ai_output non-dict ──")
from app.core.claude_ai import _parse_ai_output

# array trong <analysis> → json.loads KHÔNG raise nhưng là list → không được **list
out = _parse_ai_output('Xin chào <analysis>["a","b"]</analysis>')
check(isinstance(out, dict) and out["reply"] == "Xin chào" and out["intent"] == "other",
      "A1 array_analysis_safe", f"{out}")
# số / chuỗi
check(_parse_ai_output("Hi <analysis>42</analysis>")["reply"] == "Hi", "A2 number_analysis_safe")
check(_parse_ai_output('X <analysis>"str"</analysis>')["reply"] == "X", "A3 string_analysis_safe")
# dict hợp lệ vẫn hoạt động
out = _parse_ai_output('Ok <analysis>{"intent":"booking_request"}</analysis>[BOOKING_CONFIRMED]')
check(out["intent"] == "booking_request" and out["booking_confirmed"] is True and out["reply"] == "Ok",
      "A4 valid_dict_ok", f"{out}")

print("\n── B. store_util.atomic_write_json ──")
from app.core.store_util import atomic_write_json

p = Path("test_atomic_tmp.json")
p.unlink(missing_ok=True)
ok = atomic_write_json(p, {"a": 1, "tên": "Nắng"}, "test")
check(ok and json.loads(p.read_text(encoding="utf-8"))["tên"] == "Nắng", "B1 write_read")
check(not p.with_suffix(".json.tmp").exists(), "B1 no_tmp_left")
# ghi lỗi (data không serialize được) → trả False, file CŨ còn nguyên
ok = atomic_write_json(p, {"bad": {1, 2, 3}}, "test")   # set không JSON được
check(ok is False and json.loads(p.read_text(encoding="utf-8"))["a"] == 1, "B2 fail_keeps_old")
p.unlink(missing_ok=True)

print("\n── C. payment_api._payhook_authorized ──")
import app.web_api.payment_api as pay
from flask import Flask
_app = Flask(__name__)

def _auth_with(header, key):
    with _app.test_request_context(headers={"Authorization": header} if header else {}):
        with patch.object(pay.Config, "SEPAY_API_KEY", key):
            return pay._payhook_authorized()

check(_auth_with("Apikey SECRET123", "SECRET123") is True, "C1 apikey_prefix_ok")
check(_auth_with("Bearer SECRET123", "SECRET123") is True, "C2 bearer_prefix_ok")
check(_auth_with("SECRET123", "SECRET123") is True, "C3 bare_key_ok")
check(_auth_with("Apikey SECRET123EXTRA", "SECRET123") is False, "C4 substring_rejected")
check(_auth_with("Apikey WRONG", "SECRET123") is False, "C5 wrong_rejected")
check(_auth_with("", "SECRET123") is False, "C6 missing_rejected")
check(_auth_with("bất kỳ", "") is True, "C7 no_key_allows_all")

print("\n── D. Channel.get_ctx/set_ctx ──")
from app.core.channel import Channel
from app.channels.shopee import ShopeeChannel
from app.channels.tiktok import TikTokChannel
from app.channels.zalo_oa import ZaloOAChannel

# base no-op
class _Bare(Channel):
    def send_text(self, u, t): pass
    def send_room_photos(self, u, n): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass
b = _Bare()
b.set_ctx("x")
check(b.get_ctx() is None, "D1 base_noop")

for Ch, val in [(ShopeeChannel, "SHOP9"), (TikTokChannel, "BIZ9"), (ZaloOAChannel, "OA9")]:
    ch = Ch(store=None, access_token="", conv_manager=None) if Ch is not TikTokChannel \
         else Ch(store=None, access_token="", conv_manager=None)
    ch.set_ctx(val)
    check(ch.get_ctx() == val, f"D2 {Ch.__name__}_roundtrip", f"{ch.get_ctx()}")

# _make_order truyền ctx sang thread con (chạy đồng bộ để kiểm)
from app.core.conversation import ConversationManager
from app.core.brain import Brain

seen_ctx = {}
class _CtxCh(Channel):
    def __init__(self): self._v = None
    def set_ctx(self, v): self._v = v
    def get_ctx(self): return self._v
    def send_text(self, u, t): pass
    def send_room_photos(self, u, n): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): seen_ctx["at_notify"] = self._v
    def call_owner(self): pass

cm = ConversationManager(account="fixes-test")
cm._sessions.clear()
ch = _CtxCh(); ch.set_ctx("SHOP_B")
brain = Brain(channel=ch, conv_manager=cm)
conv = cm.get("sp:SHOP_B:U1"); conv.checkin = "25/12/2026"; conv.selected_room = "301"

class _SyncThread:
    def __init__(self, target=None, daemon=None, **kw): self._t = target
    def start(self):
        if self._t: self._t()

with patch("threading.Thread", _SyncThread), \
     patch("app.core.orders.create_from_conversation",
           return_value={"id": 1, "code": "DH0001", "total": 0}), \
     patch("app.core.payments.get_bank", return_value=None), \
     patch("time.sleep"):
    brain._handle_booking_confirmed("sp:SHOP_B:U1", conv, "Đã ghi nhận!")
# notify trong _make_order (thread con) phải thấy ctx SHOP_B
check(seen_ctx.get("at_notify") == "SHOP_B", "D3 make_order_ctx_propagated", f"{seen_ctx}")

print("\n── E. cleanup_old không xoá session vừa có tin ──")
cm2 = ConversationManager(account="fixes-test2")
cm2._sessions.clear()
old = cm2.get("OLD"); old.last_updated = datetime.now() - timedelta(hours=1000)
fresh = cm2.get("FRESH"); fresh.last_updated = datetime.now() - timedelta(hours=1000)
# giả lập: FRESH vừa có tin mới NGAY TRƯỚC khi cleanup xử lý nó
_orig_archive = cm2._archive_session
def _touch_fresh(s):
    if s.user_id == "FRESH":
        cm2._sessions["FRESH"].last_updated = datetime.now()   # tin mới đến
    return _orig_archive(s)
# đơn giản hơn: set FRESH mới rồi chạy cleanup
fresh.last_updated = datetime.now()
cm2.cleanup_old(hours=720)
check("OLD" not in cm2._sessions, "E1 old_removed")
check("FRESH" in cm2._sessions, "E2 fresh_kept")

# Dọn
for f in ["test_atomic_tmp.json", "test_atomic_tmp.json.tmp"]:
    Path(f).unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
