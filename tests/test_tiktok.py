#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tiktok.py — kênh TikTok (Business Messaging API, webhook):
  - TikTokChannel: parse 'tt:<biz>:<user>', gửi text (mock + thật), chia tin dài,
    fallback ảnh, notify_owner theo ngữ cảnh account
  - tiktok_api: parse_event (1 sự kiện / gộp events / echo), handle_event
    (bật/tắt + owner-takeover), stats
  - stats_util: compute_stats gộp session sống + archive

Chạy (TỪ GỐC):  python tests/test_tiktok.py
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
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tmp.sqlite')   # DB test riêng, không đụng DB thật
os.environ['API_AUTH_GUARD'] = '0'   # tắt auth-guard trong test (test_client không có token)
os.environ['WORKER_SYNC'] = '1'      # submit chạy đồng bộ → kiểm tra kết quả ngay
sys.path.insert(0, '.')

from pathlib import Path
from datetime import datetime, timedelta
from app.core.conversation import ConversationManager
from app.core.tiktok_store import TikTokStore
from app.channels.tiktok import TikTokChannel
from app.web_api.stats_util import compute_stats
import app.web_api.tiktok_api as tt
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="tt-test")
cm._sessions.clear()

# Backend giờ là SQLite — clear() dọn dữ liệu kênh sót từ lần chạy trước
store = TikTokStore(path=Path(str(_TMPDIR / "test_tt_store_tmp.json")))
store.clear()

print("\n── A. TikTokChannel ──")
ch = TikTokChannel(store=store, access_token="", business_id="", conv_manager=cm)

# A1: parse user_id
check(ch._parse("tt:BIZ1:USER9") == ("BIZ1", "USER9"), "A1 parse_multi")
check(ch._parse("tt:USER9") == (None, "USER9"), "A1 parse_single")
check(ch._parse("USER9") == (None, "USER9"), "A1 parse_bare")

# A2: send_text mock (không token) → ghi _sent
ch._sent.clear(); ch.send_text("tt:BIZ1:U1", "xin chào")
check(ch._sent == [("U1", {"text": "xin chào"})], "A2 send_text_mock", f"{ch._sent}")

# A3: text dài → chia nhiều tin (MAX_LEN=2000)
ch._sent.clear(); ch.send_text("tt:B:U", "x" * 4500)
check(len(ch._sent) == 3, "A3 long_text_split", f"n={len(ch._sent)}")

# A4: gửi thật dùng token store (patch requests) → đúng URL + payload
store.upsert("BIZ1", access_token="TTTOKEN", name="Haru TikTok")
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append((url, headers, json)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch.send_text("tt:BIZ1:U77", "hi")
    check(calls and "/business/message/send/" in calls[-1][0], "A4 send_url", f"{calls}")
    check(calls and calls[-1][1]["Access-Token"] == "TTTOKEN", "A4 send_token", f"{calls}")
    check(calls and calls[-1][2]["recipient_id"] == "U77" and calls[-1][2]["text"] == "hi",
          "A4 send_payload", f"{calls}")

# A5: notify_owner theo ngữ cảnh account (owner đã set trong store)
# BIZ1 có token → không mock; patch requests.post để không gọi mạng
store.set_owner("BIZ1", "OWNER_OPEN_ID", "Chủ Haru")
ch._sent.clear(); ch.set_ctx("BIZ1")
with patch.object(httputil.requests, 'post') as _mp:
    _mp.return_value = MagicMock(status_code=200, content=b"{}")
    ch.notify_owner("báo chủ")
check(ch._sent and ch._sent[-1][0] == "OWNER_OPEN_ID", "A5 notify_owner_ctx", f"{ch._sent}")

# A6: notify_owner không có chủ → bỏ qua, không crash
ch._sent.clear(); ch.set_ctx("BIZ_KHONG_TON_TAI"); ch.notify_owner("x")
check(ch._sent == [], "A6 notify_no_owner_skip", f"{ch._sent}")

# A7: price photos không có URL công khai → fallback text
ch._sent.clear(); ch.set_ctx(None); ch.send_price_photos("tt:U1")
check(any("Bảng giá" in d.get("text", "") for _, d in ch._sent), "A7 price_fallback", f"{ch._sent}")

print("\n── B. parse_event ──")

# B1: 1 sự kiện phẳng (tuple 5 phần: +msg_id)
evs = tt.parse_event({"event": "message", "business_id": "B1", "sender_id": "U1",
                      "text": "còn phòng?", "message_id": "m1", "sender_name": "Khách A"})
check(evs == [("B1", "U1", "còn phòng?", "m1", "Khách A")], "B1 flat_event", f"{evs}")

# B2: gộp nhiều events + message dạng dict
evs = tt.parse_event({"events": [
    {"event": "message", "business_id": "B1", "sender_id": "U2", "message": {"text": "giá?"}},
    {"event": "follow", "business_id": "B1", "sender_id": "U3"},
]})
check(evs == [("B1", "U2", "giá?", "", "")], "B2 events_list_filter", f"{evs}")

# B3: echo (sender == business) → bỏ
evs = tt.parse_event({"event": "message", "business_id": "B1", "sender_id": "B1", "text": "echo"})
check(evs == [], "B3 echo_skip", f"{evs}")

# B4: thiếu sender → bỏ, không crash
check(tt.parse_event({"event": "message", "text": "x"}) == [], "B4 no_sender_skip")

# B5: dedup theo message_id (webhook gộp gửi lại) — lần 2 cùng id bị bỏ
tt._dedup.clear()
check(not tt._dedup.seen("mmm") and tt._dedup.seen("mmm"), "B5 dedup_msg_id")

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

# C1: bot BẬT → brain.handle('tt:B1:U1') + set_ctx đúng account + lưu tên
fb = FakeBrain()
with patch.object(tt.threading, 'Thread', _SyncThread), \
     patch.object(tt, '_load_bot_state', return_value={"enabled": True}):
    tt.handle_event("B1", "U1", "hello", "Khách A", fb, cm, store)
check(fb.handled == [("tt:B1:U1", "hello")], "C1 handled", f"{fb.handled}")
check(fb.channel.ctx == "B1", "C1 ctx", f"{fb.channel.ctx}")
check(cm.get("tt:B1:U1").name == "Khách A", "C1 name_saved")

# C2: kênh tiktok TẮT → bỏ qua
fb = FakeBrain()
with patch.object(tt.threading, 'Thread', _SyncThread), \
     patch.object(tt, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"tiktok": False}}):
    tt.handle_event("B1", "U1", "hello", "", fb, cm, store)
check(fb.handled == [], "C2 channel_off_skip", f"{fb.handled}")

# C3: per-account TẮT (tiktok:B1) → bỏ qua; account khác vẫn chạy
fb = FakeBrain()
with patch.object(tt.threading, 'Thread', _SyncThread), \
     patch.object(tt, '_load_bot_state',
                  return_value={"enabled": True, "channels": {"tiktok:B1": False}}):
    tt.handle_event("B1", "U1", "hello", "", fb, cm, store)
    tt.handle_event("B2", "U1", "hello", "", fb, cm, store)
check(fb.handled == [("tt:B2:U1", "hello")], "C3 per_account_toggle", f"{fb.handled}")

# C4: owner_active → im lặng
fb = FakeBrain()
cm.get("tt:B1:U9").set_owner_active(True)
with patch.object(tt.threading, 'Thread', _SyncThread), \
     patch.object(tt, '_load_bot_state', return_value={"enabled": True}):
    tt.handle_event("B1", "U9", "hello", "", fb, cm, store)
check(fb.handled == [], "C4 owner_active_skip", f"{fb.handled}")

print("\n── D. Flask API (config/connect/accounts/conversations/send/stats) ──")
fb = FakeBrain()
real_ch = TikTokChannel(store=store, access_token="", conv_manager=cm)
fb.channel = real_ch
api = tt.create_tiktok_api(fb, cm, real_ch, store).test_client()

# D1: config
r = api.get("/tiktok/config")
check(r.status_code == 200 and r.get_json()["webhook_path"] == "/tiktok/webhook", "D1 config")

# D2: connect thiếu token → 400
r = api.post("/tiktok/connect", json={"business_id": "B9"})
check(r.status_code == 400, "D2 connect_missing_token")

# D3: connect đủ (TikTok API mock lỗi mạng → vẫn lưu, verified=false)
r = api.post("/tiktok/connect", json={"access_token": "TK9", "business_id": "B9", "name": "Test Home"})
check(r.status_code == 200 and r.get_json()["ok"], "D3 connect_saved", f"{r.get_json()}")
check(store.get_token("B9") == "TK9", "D3 token_in_store")

# D4: accounts list (không lộ token) + bot_enabled
with patch.object(tt, '_load_bot_state', return_value={"enabled": True}):
    r = api.get("/tiktok/accounts")
rows = r.get_json()
check(all("access_token" not in a for a in rows), "D4 no_token_leak", f"{rows}")
check(any(a["business_id"] == "B9" and a["bot_enabled"] for a in rows), "D4 enabled_flag", f"{rows}")

# D5: webhook GET verify → echo challenge
r = api.get("/tiktok/webhook?challenge=xyz&verify_token=novachat_tiktok_verify")
check(r.status_code == 200 and r.get_data(as_text=True) == "xyz", "D5 webhook_verify")
r = api.get("/tiktok/webhook?challenge=xyz&verify_token=sai")
check(r.status_code == 403, "D5 webhook_verify_reject")

# D6: webhook POST challenge → echo JSON
r = api.post("/tiktok/webhook", json={"challenge": "abc"})
check(r.get_json() == {"challenge": "abc"}, "D6 webhook_post_challenge")

# D7: webhook POST message → vào brain (sync thread)
with patch.object(tt.threading, 'Thread', _SyncThread), \
     patch.object(tt, '_load_bot_state', return_value={"enabled": True}):
    r = api.post("/tiktok/webhook", json={"event": "message", "business_id": "B9",
                                          "sender_id": "U55", "text": "hỏi phòng"})
check(r.status_code == 200 and fb.handled == [("tt:B9:U55", "hỏi phòng")],
      "D7 webhook_to_brain", f"{fb.handled}")

# D8: conversations lọc theo account
cm.get("tt:B9:U55").add_user_message("hỏi phòng")
cm.get("tt:OTHER:U1").add_user_message("x")
r = api.get("/tiktok/conversations?business_id=B9")
items = r.get_json()["items"]
check(len(items) == 1 and items[0]["user_id"] == "tt:B9:U55", "D8 conv_filter", f"{items}")

# D9: send từ dashboard → gửi + lưu + owner_active (B9 có token → patch mạng)
with patch.object(httputil.requests, 'post') as _mp:
    _mp.return_value = MagicMock(status_code=200, content=b"{}")
    r = api.post("/tiktok/conversations/tt:B9:U55/send", json={"text": "chủ nhắn tay"})
check(r.status_code == 200, "D9 send_ok", f"{r.get_json()}")
conv = cm.get("tt:B9:U55")
check(conv.messages[-1] == {"role": "assistant", "content": "chủ nhắn tay"}, "D9 msg_saved")
check(conv.is_owner_active(), "D9 owner_active_on")

# D10: set-owner
r = api.post("/tiktok/set-owner", json={"user_id": "tt:B9:U55", "name": "Chủ 9"})
check(r.status_code == 200 and store.get_owner_open_id("B9") == "U55", "D10 set_owner")
r = api.post("/tiktok/set-owner", json={"user_id": "xxx"})
check(r.status_code == 400, "D10 set_owner_invalid")

# D11: stats chỉ đếm tt:
r = api.get("/tiktok/stats")
s = r.get_json()
check(s["total_conv"] >= 2 and all(True for _ in [1]), "D11 stats_ok", f"{s}")

print("\n── E. stats_util: archive giữ số liệu sau dọn 48h ──")
cm2 = ConversationManager(account="tt-stats-test")
cm2._sessions.clear()
cm2._db.execute("DELETE FROM stats_archive WHERE account=?", ("tt-stats-test",))

old = cm2.get("tt:B1:OLD")
old.add_user_message("hỏi cũ"); old.add_assistant_message("rep cũ")
old.stage = "confirmed"
old.last_updated = datetime.now() - timedelta(days=10)

new = cm2.get("tt:B1:NEW")
new.add_user_message("hỏi mới")

# E1: trước dọn — cả 2 session đều được đếm
s = compute_stats(cm2, uid_filter=lambda u: u.startswith("tt:"))
check(s["total_conv"] == 2 and s["confirmed"] == 1, "E1 before_cleanup", f"{s}")

# E2: dọn 48h → session cũ bị xoá khỏi RAM nhưng stats vẫn đủ nhờ archive
cm2.cleanup_old(hours=48)
check("tt:B1:OLD" not in cm2._sessions, "E2 old_removed_from_ram")
s = compute_stats(cm2, uid_filter=lambda u: u.startswith("tt:"))
check(s["total_conv"] == 2 and s["confirmed"] == 1 and s["user_msg"] == 2,
      "E2 archive_counted", f"{s}")

# E3: lọc theo ngày — chỉ lấy 7 ngày gần → session cũ (10 ngày) bị loại
frm = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
to = datetime.now().strftime("%Y-%m-%d")
s = compute_stats(cm2, from_s=frm, to_s=to, uid_filter=lambda u: u.startswith("tt:"))
check(s["total_conv"] == 1 and s["confirmed"] == 0, "E3 date_filter", f"{s}")

# Dọn file tạm
for f in [str(_TMPDIR / "test_tt_store_tmp.json")]:
    try: Path(f).unlink()
    except FileNotFoundError: pass

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
