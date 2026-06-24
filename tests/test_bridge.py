#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_bridge.py — kiểm tra wiring kênh Zalo-Node:
  - bridge /incoming định tuyến đúng (bỏ qua group/self/owner_active, gọi brain cho khách)
  - ZaloNodeChannel.send_text / send_price_photos gọi đúng HTTP tới Node

Chạy: python -X utf8 test_bridge.py
"""

import os, sys
from unittest.mock import MagicMock, patch

# Mock external deps trước khi import brain/zalo_node_channel
sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
os.environ.setdefault('OWNER_ZALO_ID', 'OWNER123')
sys.path.insert(0, '.')

from pathlib import Path
from app.core.channel import Channel
from app.core.conversation import ConversationManager
from app.core.brain import Brain
import app.web_api.bridge as bridge_mod
import app.channels.zalo_node as znc_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# Cô lập sessions
cm = ConversationManager(account=1)
cm._file = Path("test_bridge_tmp.json"); cm._sessions.clear()

# ── FakeChannel để brain "gửi" mà ta bắt được ──
class FakeChannel(Channel):
    def __init__(self): self.texts=[]; self.price=False; self.rooms=[]; self.owner=[]; self.called=False
    def send_text(self, uid, text): self.texts.append(text)
    def send_room_photos(self, uid, names): self.rooms.extend(names)
    def send_price_photos(self, uid): self.price=True
    def notify_owner(self, text): self.owner.append(text)
    def call_owner(self): self.called=True

# Thread chạy đồng bộ để test xác định
class _SyncThread:
    def __init__(self, target=None, **kw): self._t=target
    def start(self): self._t() if self._t else None

print("\n── A. Bridge routing ──")
with patch.object(bridge_mod, 'threading') as mth, \
     patch('app.core.brain.analyze_message', return_value={"intent":"other","reply":"Chào bạn!"}), \
     patch('app.core.brain.format_availability_for_ai', return_value=""), \
     patch('app.core.brain.time') as bt:
    mth.Thread = _SyncThread
    bt.sleep = lambda *a: None
    fc = FakeChannel()
    brain = Brain(channel=fc, conv_manager=cm)
    bridge_mod.BOT_STATE_FILE = Path("test_bot_state_tmp.json")  # cô lập, không đụng data thật
    try: bridge_mod.BOT_STATE_FILE.unlink()
    except: pass
    app = bridge_mod.create_bridge(brain, cm)
    client = app.test_client()

    # A1: tin nhóm → bỏ qua
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"u1","text":"hi","isGroup":True})
    check(r.get_json().get("skipped")=="group" and not fc.texts, "A1 group_skipped")

    # A2: tin tự gửi (isSelf, echo bot) → bỏ qua
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"u1","text":"hi","isSelf":True})
    check(r.get_json().get("skipped")=="self-echo" and not fc.texts, "A2 self_echo_skipped")

    # A3: khách mới → brain xử lý, gửi greeting + bảng giá
    fc.texts.clear(); fc.price=False
    r = client.post("/incoming", json={"userId":"cust1","text":"xin chào"})
    check(r.get_json().get("ok") is True, "A3 customer_ok")
    check(any("Haru AI" in t for t in fc.texts), "A3 greeting_sent", f"texts={fc.texts}")
    check(fc.price is True, "A3 price_sent")

    # A4: owner_active → bỏ qua
    cm.get("cust2").set_owner_active(True)
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"cust2","text":"còn phòng ko"})
    check(r.get_json().get("skipped")=="owner_active" and not fc.texts, "A4 owner_active_skipped")

    # A5: thiếu userId → 400
    r = client.post("/incoming", json={"text":"hi"})
    check(r.status_code==400, "A5 missing_userId_400")

    # A6: chủ nhà tự nhắn khách (isSelf + ownerTyped) → bật owner_active, không trả lời
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"cust3","text":"để anh hỗ trợ","isSelf":True,"ownerTyped":True})
    check(r.get_json().get("owner_takeover") is True, "A6 owner_takeover_flag")
    check(cm.get("cust3").is_owner_active(), "A6 owner_active_set")
    check(not fc.texts, "A6 no_reply_on_takeover")

    # A7: sau khi chủ tiếp quản, khách nhắn tiếp → bot im lặng
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"cust3","text":"còn phòng ko"})
    check(r.get_json().get("skipped")=="owner_active" and not fc.texts, "A7 silent_after_takeover")

    # A8: self non-text/media echo không được bật owner_active
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"cust4","text":"","isSelf":True,"ownerTyped":True})
    check(r.get_json().get("skipped")=="self-non-text", "A8 self_non_text_skipped")
    check(not cm.get("cust4").is_owner_active(), "A8 owner_active_not_set")

    # ── C. Bật/tắt bot toàn cục (nút màn hình chính) ──
    print("\n── C. Bật/tắt bot toàn cục ──")
    # C1: mặc định bot đang BẬT
    check(client.get("/bot-status").get_json().get("enabled") is True, "C1 default_enabled")

    # C2: TẮT bot → trả enabled false + nhắn nhóm chung (notify_owner) có chữ "TẮT"
    fc.owner.clear()
    r = client.post("/bot-toggle", json={"enabled": False, "app_name": "Haru"})
    check(r.get_json().get("enabled") is False, "C2 toggle_off")
    check(any("TẮT" in t and "Haru" in t for t in fc.owner), "C2 group_notified_off", f"owner={fc.owner}")

    # C3: bot TẮT → khách nhắn bị bỏ qua, không auto-reply
    fc.texts.clear(); fc.price=False
    r = client.post("/incoming", json={"userId":"cust5","text":"còn phòng ko"})
    check(r.get_json().get("skipped")=="bot_disabled" and not fc.texts, "C3 customer_skipped_when_off")

    # C4: BẬT lại → enabled true + nhắn nhóm có chữ "BẬT"
    fc.owner.clear()
    r = client.post("/bot-toggle", json={"enabled": True, "app_name": "Haru"})
    check(r.get_json().get("enabled") is True, "C4 toggle_on")
    check(any("BẬT" in t for t in fc.owner), "C4 group_notified_on", f"owner={fc.owner}")

    # C5: bot BẬT lại → khách mới được trả lời bình thường
    fc.texts.clear()
    r = client.post("/incoming", json={"userId":"cust6","text":"xin chào"})
    check(any("Haru AI" in t for t in fc.texts), "C5 reply_resumed", f"texts={fc.texts}")

print("\n── B. ZaloNodeChannel gọi Node đúng ──")
with patch.object(znc_mod, 'requests') as mreq:
    calls=[]
    def fake_post(url, json=None, timeout=None):
        calls.append((url, json)); m=MagicMock(); m.status_code=200; return m
    mreq.post.side_effect = fake_post
    ch = znc_mod.ZaloNodeChannel(node_url="http://127.0.0.1:4000", conv_manager=cm)

    # B1: send_text → POST /send
    ch.send_text("cust1", "hello")
    check(calls and calls[-1][0].endswith("/send") and calls[-1][1]=={"userId":"cust1","text":"hello"},
          "B1 send_text_posts", f"calls={calls}")

    # B2: text > 2000 ký tự → chia 2 lần
    calls.clear(); ch.send_text("cust1", "x"*2500)
    check(len(calls)==2, "B2 long_text_split", f"n={len(calls)}")

    # B3: notify_owner gọi /notify-owner (Node tự quyết nhóm/chủ theo cấu hình UI)
    calls.clear(); ch.notify_owner("báo chủ")
    check(len(calls)==1 and calls[-1][0].endswith("/notify-owner") and calls[-1][1]=={"text":"báo chủ"},
          "B3 notify_owner_endpoint", f"calls={calls}")

print(f"\n{'='*40}\n  KẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
for _f in ("test_bridge_tmp.json", "test_bot_state_tmp.json"):
    try: Path(_f).unlink()
    except: pass
sys.exit(1 if FAIL else 0)
