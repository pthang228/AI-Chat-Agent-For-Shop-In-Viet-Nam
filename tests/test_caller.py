#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_caller.py — GỌI KHẨN QUA TELEGRAM cấp SHOP (mọi kênh):
  A. shop_caller store: set/get/target/clear + fallback shop con → tài khoản chính
  B. shop_caller.call(): gọi đúng target+session (mock owner_call), thiếu → False
  C. notify.alert mode "call": shop CÓ caller → KHÔNG fallback channel.call_owner;
     shop KHÔNG có → fallback cơ chế cũ y nguyên
  D. API /caller: 401 không token, staff 403, owner đọc được, test-call 400 khi trống

Chạy TỪ GỐC: python tests/test_caller.py  (PYTHONIOENCODING=utf-8)
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
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_caller_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '0'
sys.path.insert(0, '.')
for suf in ("", "-wal", "-shm"):
    _P(str(_TMPDIR / f"test_db_caller_tmp.sqlite{suf}")).unlink(missing_ok=True)

from datetime import datetime
from flask import Flask
from app.core.db import get_db
from app.core import shop_caller, shops, notify

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()

# ── A. store + fallback ──────────────────────────────────────────────
print("A. store + fallback shop con")
shop_caller.set_session("chu@x.vn", "SESS_STR", {"first_name": "Thắng", "username": "thang"})
shop_caller.set_target("chu@x.vn", 12345, "Thắng", "thang")
cfg = shop_caller.get("chu@x.vn")
check(cfg["caller_session"] == "SESS_STR" and cfg["target_id"] == 12345,
      "A1 set/get session + target", cfg)
check(cfg["caller_name"] == "Thắng" and cfg["caller_username"] == "thang", "A2 profile lưu đúng")

s2 = shops.create("chu@x.vn", "Shop 2")
eff = shop_caller.config_for(s2["ws"])
check(eff.get("caller_session") == "SESS_STR",
      "A3 shop con chưa cấu hình → fallback tài khoản chính", eff)
shop_caller.set_session(s2["ws"], "SESS_RIENG", {"first_name": "B", "username": "b"})
shop_caller.set_target(s2["ws"], 99, "B", "b")
check(shop_caller.config_for(s2["ws"])["target_id"] == 99, "A4 shop con có riêng → bản riêng thắng")
shop_caller.clear(s2["ws"])
check(shop_caller.config_for(s2["ws"])["target_id"] == 12345, "A5 clear → quay lại fallback")
check(shop_caller.config_for("nguoila@x.vn") == {}, "A6 người lạ → rỗng")

# ── B. call() ────────────────────────────────────────────────────────
print("B. call()")
from app.core import owner_call
with patch.object(owner_call, "telethon_call") as mc:
    check(shop_caller.call("chu@x.vn") is True, "B1 đủ cấu hình → True")
    mc.assert_called_once_with(12345, session="SESS_STR")
with patch.object(owner_call, "telethon_call") as mc:
    check(shop_caller.call(s2["ws"]) is True, "B2 shop con → gọi bằng cấu hình tài khoản chính")
    mc.assert_called_once_with(12345, session="SESS_STR")
with patch.object(owner_call, "telethon_call") as mc:
    check(shop_caller.call("nguoila@x.vn") is False and not mc.called,
          "B3 chưa cấu hình → False, không gọi")

# ── C. notify.alert routing ──────────────────────────────────────────
print("C. notify.alert mode 'call'")
class FakeCh:
    def __init__(self): self.notes = []; self.called = 0
    def notify_owner(self, m): self.notes.append(m)
    def call_owner(self): self.called += 1

cfg_call = notify.get_config("chu@x.vn")
cfg_call["events"]["contact_request"] = "call"
with patch.object(owner_call, "telethon_call") as mc:
    ch = FakeCh()
    notify.alert(ch, "contact_request", "khách cần gặp", cfg=cfg_call)
    check(len(ch.notes) == 1, "C1 vẫn nhắn báo chủ qua kênh")
    check(mc.called and ch.called == 0,
          "C2 shop CÓ caller → gọi Telegram shop, KHÔNG fallback call_owner cũ",
          (mc.called, ch.called))

cfg_none = notify.get_config("nguoila@x.vn")
cfg_none["events"]["contact_request"] = "call"
with patch.object(owner_call, "telethon_call") as mc:
    ch = FakeCh()
    notify.alert(ch, "contact_request", "khách cần gặp", cfg=cfg_none)
    check(not mc.called and ch.called == 1,
          "C3 shop KHÔNG có caller → fallback channel.call_owner như cũ",
          (mc.called, ch.called))

cfg_notify = notify.get_config("chu@x.vn")
cfg_notify["events"]["contact_request"] = "notify"
with patch.object(owner_call, "telethon_call") as mc:
    ch = FakeCh()
    notify.alert(ch, "contact_request", "x", cfg=cfg_notify)
    check(not mc.called and ch.called == 0, "C4 mức 'notify' → không gọi ai")

# ── D. API /caller ───────────────────────────────────────────────────
print("D. API /caller")
from app.web_api.auth_api import _issue_token, register_auth_routes
from app.web_api.caller_api import register_caller_routes
for u, role, own in (("chu@x.vn", "owner", ""), ("nv@x.vn", "staff", "chu@x.vn")):
    db.execute("INSERT OR IGNORE INTO users(username, password_hash, created_at, role,"
               " owner_username) VALUES (?, 'x', ?, ?, ?)",
               (u, datetime.now().isoformat(), role, own))
TOK = _issue_token(db, "chu@x.vn")
TOK_NV = _issue_token(db, "nv@x.vn")
api = Flask(__name__)
register_caller_routes(api)
c = api.test_client()

r = c.get("/caller")
check(r.status_code == 401, "D1 không token → 401", r.status_code)
r = c.get("/caller", headers={"Authorization": f"Bearer {TOK_NV}"})
check(r.status_code == 403, "D2 staff → 403", r.status_code)
r = c.get("/caller", headers={"Authorization": f"Bearer {TOK}"})
check(r.status_code == 200 and r.json["logged_in"] and r.json["target_id"] == 12345,
      "D3 owner đọc trạng thái (đã cấu hình ở A)", r.json)
with patch.object(owner_call, "telethon_call"):
    r = c.post("/caller/test-call", headers={"Authorization": f"Bearer {TOK}"})
    check(r.status_code == 200, "D4 test-call đủ cấu hình → 200", r.text)
shop_caller.clear("chu@x.vn")
r = c.post("/caller/test-call", headers={"Authorization": f"Bearer {TOK}"})
check(r.status_code == 400, "D5 test-call khi trống → 400 lỗi rõ", r.status_code)
r = c.get("/caller", headers={"Authorization": f"Bearer {TOK}"})
check(r.status_code == 200 and not r.json["logged_in"], "D6 sau logout/clear → logged_in False")

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
