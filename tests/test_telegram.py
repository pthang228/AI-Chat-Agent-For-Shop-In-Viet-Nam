#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_telegram.py — kênh Telegram (Bot API, long-polling):
  - TelegramChannel: parse 'tg:<chat>', gửi sendMessage, chia tin dài, fallback ảnh
  - telegram_api: parse_message (private/group), handle_update (bật/tắt + owner-takeover)

Chạy (TỪ GỐC):  python tests/test_telegram.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tmp.sqlite'   # DB test riêng, không đụng DB thật
os.environ['API_AUTH_GUARD'] = '0'   # tắt auth-guard trong test (test_client không có token)
os.environ['WORKER_SYNC'] = '1'      # submit chạy đồng bộ → kiểm tra kết quả ngay
sys.path.insert(0, '.')

from pathlib import Path
from app.core.conversation import ConversationManager
from app.channels.telegram import TelegramChannel
import app.web_api.telegram_api as tg
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="tg-test")
cm._sessions.clear()

print("\n── A. TelegramChannel ──")
ch = TelegramChannel(token="", owner_chat_id="OWNER_CHAT", conv_manager=cm)

# A1: parse chat_id (1 bot: bot_id=None)
check(ch._parse("tg:12345") == (None, "12345"), "A1 parse_prefixed")
check(ch._parse("999") == (None, "999"), "A1 parse_bare")

# A2: send_text mock (không token) → ghi _sent với method+chat_id+text
ch._sent.clear(); ch.send_text("tg:12345", "xin chào")
check(ch._sent == [("sendMessage", {"chat_id": "12345", "text": "xin chào"})], "A2 send_text", f"{ch._sent}")

# A3: text dài → chia nhiều tin (MAX_LEN=4000)
ch._sent.clear(); ch.send_text("tg:1", "x" * 9000)
check(len(ch._sent) == 3, "A3 long_text_split", f"n={len(ch._sent)}")

# A4: gửi thật dùng token (patch requests) → đúng URL + chat_id
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, data=None, files=None, timeout=None):
        calls.append((url, data)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch2 = TelegramChannel(token="TESTTOKEN", conv_manager=cm)
    ch2.send_text("tg:777", "hi")
    check(calls and "bot TESTTOKEN".replace(" ", "") in calls[-1][0].replace("bot", "bot") and "/sendMessage" in calls[-1][0],
          "A4 send_url", f"url={calls[-1][0] if calls else None}")
    check(calls and calls[-1][1]["chat_id"] == "777" and calls[-1][1]["text"] == "hi", "A4 send_payload", f"{calls}")

# A5: notify_owner → gửi tới owner_chat_id
ch._sent.clear(); ch.notify_owner("báo chủ")
check(ch._sent == [("sendMessage", {"chat_id": "OWNER_CHAT", "text": "báo chủ"})], "A5 notify_owner", f"{ch._sent}")

# A6: price photos không có thư mục → fallback text
ch._sent.clear(); ch.send_price_photos("tg:1")
check(any("Bảng giá" in d.get("text", "") for _, d in ch._sent), "A6 price_fallback", f"{ch._sent}")

print("\n── B. parse_message + handle_update ──")

# B1: chat private → (chat_id, text, name)
upd = {"message": {"chat": {"id": 55, "type": "private"}, "text": "còn phòng ko"}}
check(tg.parse_message(upd) == ("55", "còn phòng ko", ""), "B1 parse_private")

# B2: group → bỏ qua (None)
check(tg.parse_message({"message": {"chat": {"id": 9, "type": "group"}, "text": "hi"}}) is None, "B2 parse_group_skip")
check(tg.parse_message({"edited_message": {"chat": {"id": 5, "type": "private"}, "text": "sửa"}}) == ("5", "sửa", ""), "B2 parse_edited")

class _SyncThread:
    def __init__(self, target=None, **kw): self._t = target
    def start(self): self._t() if self._t else None

class _FakeCh:
    def __init__(self): self.sent = []; self.ctx = None
    def set_ctx(self, b): self.ctx = b
    def send_text(self, uid, t): self.sent.append((uid, t))

class FakeBrain:
    def __init__(self): self.handled = []; self.channel = _FakeCh()
    def handle(self, uid, text): self.handled.append((uid, text))

# B3: handle_update bot BẬT → brain.handle('tg:<chat>')
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(tg, 'time') as mt:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb = FakeBrain()
    tg.handle_update({"message": {"chat": {"id": 55, "type": "private"}, "text": "giá nhiêu"}}, fb, cm)
    check(fb.handled == [("tg:55", "giá nhiêu")], "B3 routed", f"{fb.handled}")

# B4: bot TẮT toàn cục → bỏ qua
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": False}), \
     patch.object(tg, 'time') as mt:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb2 = FakeBrain()
    tg.handle_update({"message": {"chat": {"id": 55, "type": "private"}, "text": "alo"}}, fb2, cm)
    check(fb2.handled == [], "B4 bot_disabled_skip")

# B5: owner_active → im lặng
cm.get("tg:66").set_owner_active(True)
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(tg, 'time') as mt:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb3 = FakeBrain()
    tg.handle_update({"message": {"chat": {"id": 66, "type": "private"}, "text": "alo"}}, fb3, cm)
    check(fb3.handled == [], "B5 owner_active_silent")

print("\n── C. Tự đăng ký chủ qua /start ──")
import app.channels.telegram as tgch
from types import SimpleNamespace

class FakeBrain2:
    def __init__(self): self.handled = []; self.channel = _FakeCh()
    def handle(self, uid, text): self.handled.append((uid, text))

# C1: '/start chunha' (đúng mã) → lưu chủ, KHÔNG vào brain, có xác nhận
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(tg, 'time') as mt, \
     patch.object(tg.telegram_owner, 'set_owner') as mset:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb = FakeBrain2()
    tg.handle_update({"message": {"chat": {"id": 900, "type": "private", "first_name": "Chu"}, "text": "/start chunha"}}, fb, cm)
    check(mset.called and str(mset.call_args[0][0]) == "900", "C1 owner_registered", f"{mset.call_args}")
    check(fb.handled == [], "C1 not_to_brain")
    check(any("CHỦ NHÀ" in t for _, t in fb.channel.sent), "C1 confirm_sent", f"{fb.channel.sent}")

# C2: '/start' thường (khách) → chào, KHÔNG đăng ký chủ, KHÔNG vào brain
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(tg, 'time') as mt, \
     patch.object(tg.telegram_owner, 'set_owner') as mset:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb = FakeBrain2()
    tg.handle_update({"message": {"chat": {"id": 901, "type": "private"}, "text": "/start"}}, fb, cm)
    check(not mset.called, "C2 not_registered")
    check(fb.handled == [] and len(fb.channel.sent) == 1, "C2 greeted_not_brain", f"{fb.channel.sent}")

# C3: notify_owner dùng chủ đã bắt (ưu tiên store)
with patch.object(tgch.telegram_owner, 'get_owner_chat_id', return_value="900"):
    ch.token = ""; ch._sent.clear()
    ch.notify_owner("có khách cần gọi")
    check(ch._sent == [("sendMessage", {"chat_id": "900", "text": "có khách cần gọi"})], "C3 notify_uses_owner", f"{ch._sent}")

print("\n── D. Đa khách (token + chủ theo từng bot) ──")
from app.core.telegram_store import TelegramStore
store = TelegramStore(path=Path("test_tg_store_tmp.json")); store._bots.clear()
store.upsert("BOT1", token="TOK1", username="haru_bot", name="Haru")
store.set_owner("BOT1", "OWN1", "Chu Haru")

ch_mt = TelegramChannel(store=store, token="", conv_manager=cm)
# D0: parse 3 phần / 2 phần
check(ch_mt._parse("tg:BOT1:CHAT9") == ("BOT1", "CHAT9"), "D0 parse_3part")
check(ch_mt._parse("tg:55") == (None, "55"), "D0 parse_2part")
# D1: token theo bot + D2: notify_owner đúng chủ của bot (ctx)
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, data=None, files=None, timeout=None):
        calls.append((url, data)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch_mt.send_text("tg:BOT1:CHAT9", "hi")
    check(calls and "botTOK1/sendMessage" in calls[-1][0] and calls[-1][1]["chat_id"] == "CHAT9",
          "D1 send_uses_bot_token", f"{calls[-1] if calls else None}")
    ch_mt.set_ctx("BOT1"); calls.clear()
    ch_mt.notify_owner("khách cần gọi")
    check(calls and "botTOK1/" in calls[-1][0] and calls[-1][1]["chat_id"] == "OWN1",
          "D2 notify_owner_per_bot", f"{calls[-1] if calls else None}")

# D3: handle_update gắn bot_id → user_id 'tg:<bot>:<chat>'
with patch.object(tg, 'threading') as mth, \
     patch.object(tg, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(tg, 'time') as mt:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb = FakeBrain2()
    tg.handle_update({"message": {"chat": {"id": 77, "type": "private"}, "text": "giá"}},
                     fb, cm, bot_id="BOT1", store=store)
    check(fb.handled == [("tg:BOT1:77", "giá")], "D3 multitenant_routed", f"{fb.handled}")

# D4: /start <mã> với bot_id → lưu chủ vào STORE của bot đó
fb = FakeBrain2()
tg._try_register_owner("88", "/start chunha", "Chu Mochi", fb, cm, "BOT1", store)
check(store.get_owner_chat_id("BOT1") == "88", "D4 owner_saved_to_store", f"{store.get('BOT1')}")

print("\n── E. Admin tự chọn chủ (/tg/set-owner) ──")
app = tg.create_telegram_api(FakeBrain2(), cm, ch_mt, store)
client = app.test_client()
# E1: đa khách → lưu chủ vào store của bot
client.post("/tg/set-owner", json={"user_id": "tg:BOT1:555", "name": "Sếp"})
check(store.get_owner_chat_id("BOT1") == "555", "E1 set_owner_multitenant", f"{store.get('BOT1')}")
# E2: 1-bot (.env) → telegram_owner.set_owner
with patch.object(tg.telegram_owner, 'set_owner') as mset:
    client.post("/tg/set-owner", json={"user_id": "tg:999"})
    check(mset.called and str(mset.call_args[0][0]) == "999", "E2 set_owner_single", f"{mset.call_args}")
# E3: user_id sai → 400
r = client.post("/tg/set-owner", json={"user_id": "xxx"})
check(r.status_code == 400, "E3 bad_uid_400")

print("\n── F. Acc gọi đăng nhập QR (session theo bot) ──")
# F1: lưu session acc gọi vào store + hồ sơ acc
store.set_caller_session("BOT1", "SESSION_STR",
                         {"id": 42, "first_name": "Lễ", "last_name": "Tân", "username": "letan"})
check(store.get_caller_session("BOT1") == "SESSION_STR", "F1 set_caller_session")
# F1b: lưu acc gọi KHÔNG đụng chủ đã lưu
check(store.get_owner_chat_id("BOT1") == "555", "F1b owner_unchanged")
# F2: list_bots phơi acc gọi cho UI mà KHÔNG lộ session
row = next((b for b in store.list_bots() if b["bot_id"] == "BOT1"), {})
check(row.get("caller_logged_in") and row.get("caller_name") == "Lễ Tân"
      and row.get("caller_username") == "letan" and "caller_session" not in row,
      "F2 list_bots_exposes_caller", f"{row}")
# F3: endpoint /tg/caller phản ánh đã đăng nhập
r = client.get("/tg/caller?bot_id=BOT1").get_json()
check(r.get("logged_in") and r.get("username") == "letan", "F3 caller_status", f"{r}")
# F4: qr-login thiếu bot_id → 400
r = client.post("/tg/caller/qr-login", json={})
check(r.status_code == 400, "F4 qr_login_needs_bot")
# F5: status của bot chưa đăng nhập = idle
check(tg.telegram_login.status("NOPE")["state"] == "idle", "F5 login_idle")
# F6: logout xoá session
client.post("/tg/caller/logout", json={"bot_id": "BOT1"})
check(store.get_caller_session("BOT1") is None, "F6 logout_clears")

print(f"\n{'='*40}\n  KẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
for _f in ("test_tg_tmp.json", "test_tg_store_tmp.json"):
    try: Path(_f).unlink()
    except: pass
sys.exit(1 if FAIL else 0)
