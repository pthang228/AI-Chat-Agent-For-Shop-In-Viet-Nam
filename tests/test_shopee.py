#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_shopee.py — kênh Shopee (Open Platform sellerchat, webhook push):
  - ShopeeChannel: parse 'sp:<shop>:<buyer>', gửi text (mock + thật, chữ ký HMAC v2),
    chia tin dài, fallback ảnh, notify_owner theo ngữ cảnh shop
  - shopee_api: parse_event (push code 10 / dạng phẳng / gộp events / echo),
    handle_event (bật/tắt + owner-takeover per-shop)
  - ShopeeStore + Flask API (config/connect/shops/conversations/send/stats)

Chạy (TỪ GỐC):  python tests/test_shopee.py
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

import hashlib
import hmac as hmac_mod
from pathlib import Path
from app.core.conversation import ConversationManager
from app.core.shopee_store import ShopeeStore
from app.channels.shopee import ShopeeChannel, SEND_PATH
import app.web_api.shopee_api as sp
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="sp-test")
cm._sessions.clear()

store = ShopeeStore(path=Path("test_sp_store_tmp.json"))
store._shops.clear()

print("\n── A. ShopeeChannel ──")
ch = ShopeeChannel(store=store, access_token="", shop_id="",
                   partner_id="", partner_key="", conv_manager=cm)

# A1: parse user_id
check(ch._parse("sp:SHOP1:BUYER9") == ("SHOP1", "BUYER9"), "A1 parse_multi")
check(ch._parse("sp:BUYER9") == (None, "BUYER9"), "A1 parse_single")
check(ch._parse("BUYER9") == (None, "BUYER9"), "A1 parse_bare")

# A2: send_text mock (chưa token/partner) → ghi _sent, không gọi mạng
ch._sent.clear(); ch.send_text("sp:SHOP1:U1", "xin chào")
check(ch._sent == [("U1", {"text": "xin chào"})], "A2 send_text_mock", f"{ch._sent}")

# A3: text dài → chia nhiều tin (MAX_LEN=1000)
ch._sent.clear(); ch.send_text("sp:S:U", "x" * 2500)
check(len(ch._sent) == 3, "A3 long_text_split", f"n={len(ch._sent)}")

# A4: chữ ký HMAC-SHA256 đúng công thức Shopee v2
ch2 = ShopeeChannel(store=store, access_token="", shop_id="",
                    partner_id="12345", partner_key="secretkey", conv_manager=cm)
expected = hmac_mod.new(b"secretkey",
                        f"12345{SEND_PATH}1700000000TOK777888".encode(),
                        hashlib.sha256).hexdigest()
check(ch2._sign(SEND_PATH, 1700000000, "TOK777", "888") == expected, "A4 sign_hmac")

# A5: gửi thật dùng token store (patch requests) → đúng URL + params + body
store.upsert("888", access_token="TOK777", name="Nắng Store")
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json)); m = MagicMock(); m.status_code = 200
        m.content = b"{}"; m.json = lambda: {}; return m
    mreq.side_effect = fake_post
    ch2.send_text("sp:888:12399", "hi")
    check(calls and SEND_PATH in calls[-1][0], "A5 send_url", f"{calls}")
    check(calls and calls[-1][1]["access_token"] == "TOK777"
          and calls[-1][1]["shop_id"] == "888"
          and calls[-1][1]["partner_id"] == "12345", "A5 send_params", f"{calls}")
    check(calls and calls[-1][2]["to_id"] == 12399
          and calls[-1][2]["content"]["text"] == "hi", "A5 send_body", f"{calls}")

# A6: notify_owner theo ngữ cảnh shop (owner set trong store)
store.set_owner("888", "OWNER_BUYER", "Chủ Shop")
ch._sent.clear(); ch.set_ctx("888")
# ch (không partner key) → mock mode, ghi _sent
ch.notify_owner("báo chủ")
check(ch._sent and ch._sent[-1][0] == "OWNER_BUYER", "A6 notify_owner_ctx", f"{ch._sent}")

# A7: notify_owner không có chủ → bỏ qua, không crash
ch._sent.clear(); ch.set_ctx("SHOP_KHONG_TON_TAI"); ch.notify_owner("x")
check(ch._sent == [], "A7 notify_no_owner_skip", f"{ch._sent}")

# A8: price photos không có URL công khai → fallback text
ch._sent.clear(); ch.set_ctx(None); ch.send_price_photos("sp:U1")
check(any("Bảng giá" in d.get("text", "") for _, d in ch._sent), "A8 price_fallback", f"{ch._sent}")

print("\n── B. parse_event ──")

# B1: push CHUẨN Shopee code 10
evs = sp.parse_event({
    "code": 10, "shop_id": 888,
    "data": {"type": "message", "content": {
        "from_id": 12399, "to_id": 888, "message_type": "text",
        "content": {"text": "còn hàng không?"}, "message_id": "spm1", "from_user_name": "Khách A"}}})
check(evs == [("888", "12399", "còn hàng không?", "spm1", "Khách A")], "B1 push_code10", f"{evs}")

# B2: push code khác 10 (vd đơn hàng) → bỏ
check(sp.parse_event({"code": 3, "shop_id": 888, "data": {}}) == [], "B2 other_code_skip")

# B3: dạng phẳng (mock/test)
evs = sp.parse_event({"event": "message", "shop_id": "S1", "sender_id": "U1",
                      "text": "giá?", "sender_name": "Khách B"})
check(evs == [("S1", "U1", "giá?", "", "Khách B")], "B3 flat_event", f"{evs}")

# B4: gộp events + lọc sự kiện không phải message
evs = sp.parse_event({"events": [
    {"event": "message", "shop_id": "S1", "sender_id": "U2", "message": {"text": "ship?"}},
    {"event": "order", "shop_id": "S1", "sender_id": "U3"},
]})
check(evs == [("S1", "U2", "ship?", "", "")], "B4 events_list_filter", f"{evs}")

# B4b: dedup theo message_id (Shopee gửi lại push) — lần 2 cùng id bị bỏ
sp._dedup.clear()
check(not sp._dedup.seen("dz1") and sp._dedup.seen("dz1"), "B4b dedup_msg_id")

# B5: echo (from_id == shop_id) → bỏ
evs = sp.parse_event({"code": 10, "shop_id": 888,
                      "data": {"type": "message", "content": {
                          "from_id": 888, "message_type": "text", "content": {"text": "e"}}}})
check(evs == [], "B5 echo_skip", f"{evs}")

# B6: thiếu sender → bỏ, không crash
check(sp.parse_event({"event": "message", "text": "x"}) == [], "B6 no_sender_skip")

print("\n── C. handle_event (gate bật/tắt + owner-takeover) ──")

class _FakeCh:
    def __init__(self): self.sent = []; self.ctx = "unset"
    def set_ctx(self, b): self.ctx = b
    def send_text(self, uid, t): self.sent.append((uid, t))

class FakeBrain:
    def __init__(self): self.handled = []; self.channel = _FakeCh()
    def handle(self, uid, text): self.handled.append((uid, text))

class _SyncThread:
    def __init__(self, target=None, daemon=None, **kw): self._t = target
    def start(self):
        if self._t: self._t()

# C1: bot BẬT → brain.handle('sp:S1:U1') + set_ctx đúng shop + lưu tên
fb = FakeBrain()
with patch.object(sp.threading, 'Thread', _SyncThread), \
     patch.object(sp, '_load_bot_state', return_value={"enabled": True}):
    sp.handle_event("S1", "U1", "hello", "Khách A", fb, cm, store)
check(fb.handled == [("sp:S1:U1", "hello")], "C1 handled", f"{fb.handled}")
check(fb.channel.ctx == "S1", "C1 ctx", f"{fb.channel.ctx}")
check(cm.get("sp:S1:U1").name == "Khách A", "C1 name_saved")

# C2: kênh shopee TẮT → bỏ qua
fb = FakeBrain()
with patch.object(sp.threading, 'Thread', _SyncThread), \
     patch.object(sp, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"shopee": False}}):
    sp.handle_event("S1", "U1", "hello", "", fb, cm, store)
check(fb.handled == [], "C2 channel_off_skip", f"{fb.handled}")

# C3: per-shop TẮT (shopee:S1) → bỏ qua; shop khác vẫn chạy
fb = FakeBrain()
with patch.object(sp.threading, 'Thread', _SyncThread), \
     patch.object(sp, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"shopee:S1": False}}):
    sp.handle_event("S1", "U1", "hello", "", fb, cm, store)
    sp.handle_event("S2", "U1", "hello", "", fb, cm, store)
check(fb.handled == [("sp:S2:U1", "hello")], "C3 per_shop_toggle", f"{fb.handled}")

# C4: owner_active → im lặng
fb = FakeBrain()
cm.get("sp:S1:U9").set_owner_active(True)
with patch.object(sp.threading, 'Thread', _SyncThread), \
     patch.object(sp, '_load_bot_state', return_value={"enabled": True}):
    sp.handle_event("S1", "U9", "hello", "", fb, cm, store)
check(fb.handled == [], "C4 owner_active_skip", f"{fb.handled}")

print("\n── D. Flask API ──")
fb = FakeBrain()
real_ch = ShopeeChannel(store=store, access_token="", partner_id="", partner_key="", conv_manager=cm)
fb.channel = real_ch
api = sp.create_shopee_api(fb, cm, real_ch, store).test_client()

# D1: config
r = api.get("/shopee/config")
check(r.status_code == 200 and r.get_json()["webhook_path"] == "/shopee/webhook", "D1 config")

# D2: connect thiếu field → 400
check(api.post("/shopee/connect", json={"shop_id": "S9"}).status_code == 400, "D2 missing_token_400")
check(api.post("/shopee/connect", json={"access_token": "T"}).status_code == 400, "D2 missing_shop_400")

# D3: connect đủ (Shopee API mock lỗi mạng → vẫn lưu, verified=false)
r = api.post("/shopee/connect", json={"access_token": "TK9", "shop_id": "S9", "name": "Test Shop"})
check(r.status_code == 200 and r.get_json()["ok"], "D3 connect_saved", f"{r.get_json()}")
check(store.get_token("S9") == "TK9", "D3 token_in_store")

# D4: shops list (không lộ token) + bot_enabled
with patch.object(sp, '_load_bot_state', return_value={"enabled": True}):
    r = api.get("/shopee/shops")
rows = r.get_json()
check(all("access_token" not in s for s in rows), "D4 no_token_leak", f"{rows}")
check(any(s["shop_id"] == "S9" and s["bot_enabled"] for s in rows), "D4 enabled_flag", f"{rows}")

# D5: webhook GET → ok (Shopee không dùng challenge)
r = api.get("/shopee/webhook")
check(r.status_code == 200, "D5 webhook_get_alive")

# D6: webhook POST push code 10 → vào brain (sync thread)
with patch.object(sp.threading, 'Thread', _SyncThread), \
     patch.object(sp, '_load_bot_state', return_value={"enabled": True}):
    r = api.post("/shopee/webhook", json={
        "code": 10, "shop_id": "S9",
        "data": {"type": "message", "content": {
            "from_id": "U55", "message_type": "text", "content": {"text": "hỏi hàng"}}}})
check(r.status_code == 200 and fb.handled == [("sp:S9:U55", "hỏi hàng")],
      "D6 webhook_to_brain", f"{fb.handled}")

# D7: toggle per-shop
with patch.object(sp, '_load_bot_state', return_value={"enabled": True, "channels": {}}), \
     patch.object(sp, '_save_bot_state') as msave:
    r = api.post("/shopee/shops/S9/toggle", json={"enabled": False})
check(r.status_code == 200 and msave.call_args[0][0]["channels"]["shopee:S9"] is False,
      "D7 shop_toggle", f"{r.get_json()}")

# D8: conversations lọc theo shop
cm.get("sp:S9:U55").add_user_message("hỏi hàng")
cm.get("sp:OTHER:U1").add_user_message("x")
r = api.get("/shopee/conversations?shop_id=S9")
items = r.get_json()["items"]
check(len(items) == 1 and items[0]["user_id"] == "sp:S9:U55", "D8 conv_filter", f"{items}")

# D9: send từ dashboard → gửi + lưu + owner_active
r = api.post("/shopee/conversations/sp:S9:U55/send", json={"text": "chủ nhắn tay"})
check(r.status_code == 200, "D9 send_ok", f"{r.get_json()}")
conv = cm.get("sp:S9:U55")
check(conv.messages[-1] == {"role": "assistant", "content": "chủ nhắn tay"}, "D9 msg_saved")
check(conv.is_owner_active(), "D9 owner_active_on")

# D10: toggle-bot hội thoại + reset
r = api.post("/shopee/conversations/sp:S9:U55/toggle-bot", json={"bot_on": True})
check(r.status_code == 200 and not cm.get("sp:S9:U55").is_owner_active(), "D10 conv_toggle")
r = api.delete("/shopee/conversations/sp:S9:U55")
check(r.status_code == 200, "D10 reset")

# D11: set-owner qua API
r = api.post("/shopee/set-owner", json={"user_id": "sp:S9:U55", "name": "Chủ"})
check(r.status_code == 200 and store.get_owner_buyer_id("S9") == "U55", "D11 set_owner")

# D12: stats endpoint chạy
r = api.get("/shopee/stats")
check(r.status_code == 200 and "total_conv" in r.get_json(), "D12 stats")

# Dọn file tạm
store._shops.clear(); store.save()
Path("test_sp_store_tmp.json").unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
