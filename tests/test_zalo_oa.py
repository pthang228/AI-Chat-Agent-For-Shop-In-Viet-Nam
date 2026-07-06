#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_zalo_oa.py — kênh Zalo OA (Official Account API v3, webhook):
  - ZaloOAChannel: parse 'oa:<oa>:<user>', gửi text (mock + thật), chia tin dài,
    TỰ REFRESH token khi Zalo báo -216, fallback ảnh, notify_owner theo ngữ cảnh
  - zalo_oa_api: valid_signature (X-ZEvent-Signature), parse_event (event chuẩn
    user_send_text / dạng phẳng / gộp / echo oa_send), DEDUP msg_id,
    handle_event (bật/tắt + owner-takeover per-OA)
  - ZaloOAStore + Flask API (config/connect/accounts/conversations/send/stats)

Chạy (TỪ GỐC):  python tests/test_zalo_oa.py
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
from pathlib import Path
from app.core.conversation import ConversationManager
from app.core.zalo_oa_store import ZaloOAStore
from app.channels.zalo_oa import ZaloOAChannel, SEND_PATH, MAX_LEN
import app.web_api.zalo_oa_api as oa
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="oa-test")
cm._sessions.clear()

store = ZaloOAStore(path=Path("test_oa_store_tmp.json"))
store._oas.clear()

print("\n── A. ZaloOAChannel ──")
ch = ZaloOAChannel(store=store, access_token="", oa_id="",
                   app_id="", app_secret="", conv_manager=cm)

# A1: parse user_id
check(ch._parse("oa:OA1:U9") == ("OA1", "U9"), "A1 parse_multi")
check(ch._parse("oa:U9") == (None, "U9"), "A1 parse_single")
check(ch._parse("U9") == (None, "U9"), "A1 parse_bare")

# A2: send_text mock (chưa token) → ghi _sent, không gọi mạng
ch._sent.clear(); ch.send_text("oa:OA1:U1", "xin chào")
check(ch._sent == [("U1", {"text": "xin chào"})], "A2 send_text_mock", f"{ch._sent}")

# A3: text dài → chia nhiều tin (MAX_LEN=2000)
ch._sent.clear(); ch.send_text("oa:O:U", "x" * 4500)
check(len(ch._sent) == 3, "A3 long_text_split", f"n={len(ch._sent)}")
check(MAX_LEN == 2000, "A3 max_len_2000")

# A4: gửi thật dùng token store (patch requests) → đúng URL + header + body
store.upsert("888", access_token="TOK777", name="OA Nắng")
ch2 = ZaloOAChannel(store=store, access_token="", oa_id="",
                    app_id="APP1", app_secret="SEC1", conv_manager=cm)
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        calls.append((url, headers, json, data)); m = MagicMock(); m.status_code = 200
        m.content = b"{}"; m.json = lambda: {"error": 0}; return m
    mreq.side_effect = fake_post
    ch2.send_text("oa:888:12399", "hi")
    check(calls and SEND_PATH in calls[-1][0], "A4 send_url", f"{calls}")
    check(calls and calls[-1][1]["access_token"] == "TOK777", "A4 send_header_token", f"{calls}")
    check(calls and calls[-1][2]["recipient"]["user_id"] == "12399"
          and calls[-1][2]["message"]["text"] == "hi", "A4 send_body", f"{calls}")

# A5: token chết (-216) → TỰ refresh bằng refresh_token → lưu token mới + gửi lại
store.upsert("888", access_token="OLD", refresh_token="RT1")
with patch.object(httputil.requests, 'post') as mreq:
    seq = []
    def fake_post(url, headers=None, json=None, data=None, timeout=None):
        m = MagicMock(); m.status_code = 200
        if "oauth" in url:                       # refresh endpoint
            seq.append(("refresh", data))
            m.content = b"x"; m.json = lambda: {"access_token": "NEW_AT", "refresh_token": "RT2"}
        else:
            tok = headers["access_token"]
            seq.append(("send", tok))
            if tok == "OLD":
                m.content = b"x"; m.json = lambda: {"error": -216, "message": "invalid"}
            else:
                m.content = b"x"; m.json = lambda: {"error": 0}
        return m
    mreq.side_effect = fake_post
    ch2.send_text("oa:888:U1", "hi")
check([s[0] for s in seq] == ["send", "refresh", "send"], "A5 auto_refresh_flow", f"{seq}")
check(seq[-1][1] == "NEW_AT", "A5 resend_with_new_token", f"{seq}")
check(store.get_token("888") == "NEW_AT" and store.get_refresh_token("888") == "RT2",
      "A5 new_tokens_saved")

# A6: notify_owner theo ngữ cảnh OA (owner set trong store)
# 888 có token thật → không mock; patch requests.post để không gọi mạng
store.set_owner("888", "OWNER_U", "Chủ OA")
ch._sent.clear(); ch.set_ctx("888")
with patch.object(httputil.requests, 'post') as _mp:
    _mp.return_value = MagicMock(status_code=200, content=b"{}")
    ch.notify_owner("báo chủ")
check(ch._sent and ch._sent[-1][0] == "OWNER_U", "A6 notify_owner_ctx", f"{ch._sent}")

# A7: notify_owner không có chủ → bỏ qua, không crash
ch._sent.clear(); ch.set_ctx("OA_KHONG_TON_TAI"); ch.notify_owner("x")
check(ch._sent == [], "A7 notify_no_owner_skip", f"{ch._sent}")

# A8: price photos không có URL công khai → fallback text
ch._sent.clear(); ch.set_ctx(None); ch.send_price_photos("oa:U1")
check(any("Bảng giá" in d.get("text", "") for _, d in ch._sent), "A8 price_fallback", f"{ch._sent}")

# A9: send_image_url → attachment template media (mock ghi image_url)
ch._sent.clear(); ch.send_image_url("oa:OA1:U1", "https://x/qr.png", "QR đây")
check(ch._sent == [("U1", {"text": "QR đây"}), ("U1", {"image_url": "https://x/qr.png"})],
      "A9 image_url", f"{ch._sent}")

print("\n── B. valid_signature + parse_event ──")

# B1: chữ ký đúng công thức sha256(app_id + body + timestamp + secret)
body = b'{"event_name":"user_send_text"}'
mac = hashlib.sha256(b"APP1" + body + b"1700" + b"SEC1").hexdigest()
check(oa.valid_signature(body, f"mac={mac}", "1700", app_id="APP1", secret="SEC1"),
      "B1 sig_ok")
check(not oa.valid_signature(body, "mac=deadbeef", "1700", app_id="APP1", secret="SEC1"),
      "B1 sig_bad")
check(oa.valid_signature(body, "", "1700", app_id="", secret=""),
      "B1 sig_skip_no_secret")

# B2: event chuẩn Zalo user_send_text
evs = oa.parse_event({
    "app_id": "APP1", "event_name": "user_send_text",
    "sender": {"id": "U12"}, "recipient": {"id": "OA9"},
    "message": {"text": "còn phòng không?", "msg_id": "m1"}, "timestamp": "1700"})
check(evs == [("OA9", "U12", "còn phòng không?", "m1", "")], "B2 user_send_text", f"{evs}")

# B3: oa_send_text (OA tự gửi — echo) → bỏ
check(oa.parse_event({"event_name": "oa_send_text", "sender": {"id": "OA9"},
                      "recipient": {"id": "U12"}, "message": {"text": "e"}}) == [],
      "B3 oa_send_echo_skip")

# B4: follow/unfollow → bỏ
check(oa.parse_event({"event_name": "follow", "follower": {"id": "U1"}}) == [], "B4 follow_skip")

# B5: user_send_image → text rỗng nhưng vẫn ra event (bỏ ở handle nếu không phải tin đầu)
evs = oa.parse_event({"event_name": "user_send_image", "sender": {"id": "U1"},
                      "recipient": {"id": "OA9"}, "message": {"msg_id": "m2"}})
check(evs == [("OA9", "U1", "", "m2", "")], "B5 image_empty_text", f"{evs}")

# B6: dạng phẳng (mock/test) + gộp events
evs = oa.parse_event({"events": [
    {"event": "message", "oa_id": "O1", "sender_id": "U2", "text": "giá?", "sender_name": "Khách B"},
    {"event": "order", "oa_id": "O1", "sender_id": "U3"},
]})
check(evs == [("O1", "U2", "giá?", "", "Khách B")], "B6 flat_events_filter", f"{evs}")

# B7: thiếu sender → bỏ, không crash
check(oa.parse_event({"event": "message", "text": "x"}) == [], "B7 no_sender_skip")

# B8: dedup msg_id — lần 1 False, lần 2 True; rỗng không dedup
oa._seen_msgs.clear()
check(not oa._is_dup("mm1"), "B8 first_not_dup")
check(oa._is_dup("mm1"), "B8 second_is_dup")
check(not oa._is_dup("") and not oa._is_dup(""), "B8 empty_never_dup")

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

# C1: bot BẬT → brain.handle('oa:O1:U1') + set_ctx đúng OA + lưu tên
fb = FakeBrain()
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state', return_value={"enabled": True}):
    oa.handle_event("O1", "U1", "hello", "Khách A", fb, cm, store)
check(fb.handled == [("oa:O1:U1", "hello")], "C1 handled", f"{fb.handled}")
check(fb.channel.ctx == "O1", "C1 ctx", f"{fb.channel.ctx}")
check(cm.get("oa:O1:U1").name == "Khách A", "C1 name_saved")

# C2: kênh zalooa TẮT → bỏ qua
fb = FakeBrain()
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"zalooa": False}}):
    oa.handle_event("O1", "U1", "hello", "", fb, cm, store)
check(fb.handled == [], "C2 channel_off_skip", f"{fb.handled}")

# C3: per-OA TẮT (zalooa:O1) → bỏ qua; OA khác vẫn chạy
fb = FakeBrain()
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"zalooa:O1": False}}):
    oa.handle_event("O1", "U1", "hello", "", fb, cm, store)
    oa.handle_event("O2", "U1", "hello", "", fb, cm, store)
check(fb.handled == [("oa:O2:U1", "hello")], "C3 per_oa_toggle", f"{fb.handled}")

# C4: owner_active → im lặng
fb = FakeBrain()
cm.get("oa:O1:U9").set_owner_active(True)
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state', return_value={"enabled": True}):
    oa.handle_event("O1", "U9", "hello", "", fb, cm, store)
check(fb.handled == [], "C4 owner_active_skip", f"{fb.handled}")

# C5: KÊNH ZALO CÁ NHÂN tắt KHÔNG ảnh hưởng zalooa (2 kênh khác nhau)
fb = FakeBrain()
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"zalo": False}}):
    oa.handle_event("O3", "U1", "hello", "", fb, cm, store)
check(fb.handled == [("oa:O3:U1", "hello")], "C5 zalo_off_not_zalooa", f"{fb.handled}")

print("\n── D. Flask API ──")
fb = FakeBrain()
real_ch = ZaloOAChannel(store=store, access_token="", app_id="", app_secret="", conv_manager=cm)
fb.channel = real_ch
api = oa.create_zalo_oa_api(fb, cm, real_ch, store).test_client()

# D1: config
r = api.get("/zalooa/config")
check(r.status_code == 200 and r.get_json()["webhook_path"] == "/zalooa/webhook", "D1 config")

# D2: connect thiếu token → 400
check(api.post("/zalooa/connect", json={"oa_id": "O9"}).status_code == 400, "D2 missing_token_400")

# D3: connect đủ (Zalo API mock lỗi mạng → vẫn lưu, verified=false)
r = api.post("/zalooa/connect", json={"access_token": "TK9", "oa_id": "O9",
                                      "refresh_token": "RT9", "name": "OA Test"})
check(r.status_code == 200 and r.get_json()["ok"], "D3 connect_saved", f"{r.get_json()}")
check(store.get_token("O9") == "TK9" and store.get_refresh_token("O9") == "RT9",
      "D3 tokens_in_store")

# D3b: connect KHÔNG có oa_id + không tra được từ Zalo → 400
r = api.post("/zalooa/connect", json={"access_token": "TKX"})
check(r.status_code == 400, "D3b no_oa_id_400", f"{r.get_json()}")

# D4: accounts list (không lộ token) + bot_enabled + has_refresh
with patch.object(oa, '_load_bot_state', return_value={"enabled": True}):
    r = api.get("/zalooa/accounts")
rows = r.get_json()
check(all("access_token" not in s and "refresh_token" not in s for s in rows),
      "D4 no_token_leak", f"{rows}")
check(any(s["oa_id"] == "O9" and s["bot_enabled"] and s["has_refresh"] for s in rows),
      "D4 enabled_flag", f"{rows}")

# D5: webhook GET → ok (kiểm tra URL sống)
r = api.get("/zalooa/webhook")
check(r.status_code == 200, "D5 webhook_get_alive")

# D6: webhook POST event chuẩn → vào brain (sync thread)
oa._seen_msgs.clear()
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state', return_value={"enabled": True}):
    r = api.post("/zalooa/webhook", json={
        "app_id": "A", "event_name": "user_send_text",
        "sender": {"id": "U55"}, "recipient": {"id": "O9"},
        "message": {"text": "hỏi phòng", "msg_id": "w1"}, "timestamp": "1"})
check(r.status_code == 200 and fb.handled == [("oa:O9:U55", "hỏi phòng")],
      "D6 webhook_to_brain", f"{fb.handled}")

# D6b: Zalo gửi LẠI cùng msg_id → dedup, không xử lý lần 2
with patch.object(oa.threading, 'Thread', _SyncThread), \
     patch.object(oa, '_load_bot_state', return_value={"enabled": True}):
    api.post("/zalooa/webhook", json={
        "app_id": "A", "event_name": "user_send_text",
        "sender": {"id": "U55"}, "recipient": {"id": "O9"},
        "message": {"text": "hỏi phòng", "msg_id": "w1"}, "timestamp": "1"})
check(fb.handled == [("oa:O9:U55", "hỏi phòng")], "D6b webhook_dedup", f"{fb.handled}")

# D7: toggle per-OA
with patch.object(oa, '_load_bot_state', return_value={"enabled": True, "channels": {}}), \
     patch.object(oa, '_save_bot_state') as msave:
    r = api.post("/zalooa/accounts/O9/toggle", json={"enabled": False})
check(r.status_code == 200 and msave.call_args[0][0]["channels"]["zalooa:O9"] is False,
      "D7 oa_toggle", f"{r.get_json()}")

# D8: conversations lọc theo OA
cm.get("oa:O9:U55").add_user_message("hỏi phòng")
cm.get("oa:OTHER:U1").add_user_message("x")
r = api.get("/zalooa/conversations?oa_id=O9")
items = r.get_json()["items"]
check(len(items) == 1 and items[0]["user_id"] == "oa:O9:U55", "D8 conv_filter", f"{items}")

# D9: send từ dashboard → gửi + lưu + owner_active (O9 có token → patch mạng)
with patch.object(httputil.requests, 'post') as _mp:
    _mp.return_value = MagicMock(status_code=200, content=b"{}")
    r = api.post("/zalooa/conversations/oa:O9:U55/send", json={"text": "chủ nhắn tay"})
check(r.status_code == 200, "D9 send_ok", f"{r.get_json()}")
conv = cm.get("oa:O9:U55")
check(conv.messages[-1] == {"role": "assistant", "content": "chủ nhắn tay"}, "D9 msg_saved")
check(conv.is_owner_active(), "D9 owner_active_on")

# D10: toggle-bot hội thoại + reset
r = api.post("/zalooa/conversations/oa:O9:U55/toggle-bot", json={"bot_on": True})
check(r.status_code == 200 and not cm.get("oa:O9:U55").is_owner_active(), "D10 conv_toggle")
r = api.delete("/zalooa/conversations/oa:O9:U55")
check(r.status_code == 200, "D10 reset")

# D11: set-owner qua API
r = api.post("/zalooa/set-owner", json={"user_id": "oa:O9:U55", "name": "Chủ"})
check(r.status_code == 200 and store.get_owner_user_id("O9") == "U55", "D11 set_owner")

# D12: stats endpoint chạy
r = api.get("/zalooa/stats")
check(r.status_code == 200 and "total_conv" in r.get_json(), "D12 stats")

print("\n── E. Auth guard (Bearer token) ──")
# Bật guard cho phần này (các phần trên tắt để test_client không cần token)
os.environ['API_AUTH_GUARD'] = '1'
from app.core.db import get_db
from app.web_api.auth_api import _issue_token, hash_password
_db = get_db()
_db.execute(
    "INSERT OR IGNORE INTO users(username,password_hash,homestay,email,provider,picture,created_at) "
    "VALUES(?,?,?,?,?,?,?)",
    ("guard@test", hash_password("x"), "", "", "password", "", "2026-01-01T00:00:00"))
_tok = _issue_token(_db, "guard@test")

# E1: endpoint quản trị KHÔNG token → 401
check(api.post("/zalooa/conversations/oa:O9:U55/toggle-bot",
               json={"bot_on": True}).status_code == 401, "E1 no_token_401")
# E2: webhook + config vẫn CÔNG KHAI (không cần token)
check(api.get("/zalooa/webhook").status_code == 200, "E2 webhook_public")
check(api.get("/zalooa/config").status_code == 200, "E2 config_public")
# E3: có token hợp lệ → 200
r = api.post("/zalooa/conversations/oa:O9:U55/toggle-bot", json={"bot_on": True},
             headers={"Authorization": f"Bearer {_tok}"})
check(r.status_code == 200, "E3 with_token_ok", f"{r.status_code}")
# E4: token rác → 401
check(api.get("/zalooa/accounts",
              headers={"Authorization": "Bearer rac"}).status_code == 401, "E4 bad_token_401")
os.environ['API_AUTH_GUARD'] = '0'   # tắt lại cho lần chạy sau

# Dọn file tạm
store._oas.clear(); store.save()
Path("test_oa_store_tmp.json").unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
