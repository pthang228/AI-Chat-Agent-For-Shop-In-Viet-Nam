#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_webchat.py — kênh Website (widget nhúng web khách hàng):
  A. WebChatStore: create/get/owner/list/remove + persist
  B. WebChatChannel: parse uid, outbox (push/fetch/seq/cap), chia tin dài,
     send_image_url/send_file entry đúng loại, _media_url tương đối/tuyệt đối,
     notify_owner theo ctx site
  C. API công khai: /webchat/pub/send (site sai/visitor sai/tin trống/rate-limit,
     gate bot-tắt + owner_active + billing → vẫn LƯU tin), poll since, history,
     /widget.js + CORS "*", /media traversal
  D. API quản trị: sites CRUD + toggle per-site, set-owner, conversations
     {total,items} + filter site, send tay → outbox + owner_active, reset

Chạy (TỪ GỐC):  python tests/test_webchat.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_webchat_tmp.sqlite'   # DB riêng cho suite này
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from pathlib import Path
from app.core.conversation import ConversationManager
from app.core.webchat_store import WebChatStore
from app.channels.webchat import WebChatChannel, MAX_LEN, OUTBOX_MAX
import app.web_api.webchat_api as wc
import app.web_api.bridge as bridge_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

bridge_mod.BOT_STATE_FILE = Path("test_bot_state_wc_tmp.json")
bridge_mod.BOT_STATE_FILE.unlink(missing_ok=True)

cm = ConversationManager(account="webchat-test")
cm._sessions.clear()

print("\n── A. WebChatStore ──")
store = WebChatStore(path=Path("test_wc_store_tmp.json"))
store._sites.clear()

sid = store.create("Web Haru", owner_username="chu@x")
check(sid.startswith("wc") and len(sid) == 12, "A1 site_id_format", sid)
check(store.exists(sid) and not store.exists("wc_khac"), "A2 exists")
check(store.get(sid)["name"] == "Web Haru", "A3 get_name")
check(store.get_owner_username(sid) == "chu@x", "A4 owner_username")
store.set_owner(sid, "vOwner123", "Anh Chủ")
check(store.get_owner_user_id(sid) == "vOwner123", "A5 set_owner")
ls = store.list_sites()
check(len(ls) == 1 and ls[0]["owner_registered"] and ls[0]["name"] == "Web Haru", "A6 list", f"{ls}")
store2 = WebChatStore(path=Path("test_wc_store_tmp.json"))   # persist qua file
check(store2.exists(sid), "A7 persisted")
sid2 = store.create("", None)
check(store.get(sid2)["name"] == "Website của tôi", "A8 default_name")
store.remove(sid2)
check(not store.exists(sid2), "A9 remove")

print("\n── B. WebChatChannel ──")
ch = WebChatChannel(store=store, conv_manager=cm)

check(ch._parse(f"web:{sid}:v123") == (sid, "v123"), "B1 parse_multi")
check(ch._parse("web:v123") == (None, "v123"), "B1 parse_single")

uid = f"web:{sid}:vAlice1"
ch.send_text(uid, "xin chào")
msgs, seq = ch.fetch(uid, 0)
check(seq == 1 and msgs[0]["type"] == "text" and msgs[0]["text"] == "xin chào", "B2 outbox_push_fetch", f"{msgs}")
msgs2, seq2 = ch.fetch(uid, 1)
check(msgs2 == [] and seq2 == 1, "B3 fetch_since_empty")
ch.send_text(uid, "x" * (MAX_LEN + 10))
msgs3, seq3 = ch.fetch(uid, 1)
check(len(msgs3) == 2 and seq3 == 3, "B4 long_text_split", f"n={len(msgs3)}")

ch.send_image_url(uid, "http://cdn/a.png", caption="QR đây ạ")
msgs4, _ = ch.fetch(uid, 3)
check(msgs4[0]["type"] == "text" and msgs4[1]["type"] == "image"
      and msgs4[1]["url"] == "http://cdn/a.png", "B5 image_url_entries", f"{msgs4}")

ok = ch.send_file(uid, None, "http://h/v.mp4", "video", caption="clip")
m5, _ = ch.fetch(uid, ch.last_seq(uid) - 1)
check(ok and m5[0]["type"] == "video" and m5[0]["url"] == "http://h/v.mp4", "B6 send_file_video", f"{m5}")
check(ch.send_file(uid, None, "", "video") is False, "B7 send_file_no_url_false")

# cap outbox
for i in range(OUTBOX_MAX + 20):
    ch.send_text(uid, f"m{i}")
mall, _ = ch.fetch(uid, 0)
check(len(mall) == OUTBOX_MAX, "B8 outbox_cap", f"n={len(mall)}")

# _media_url: LUÔN tương đối (widget prefix origin server — không phụ thuộc
# PUBLIC_BASE_URL/tunnel; tunnel chết là URL tuyệt đối gãy)
from app.core.config import Config
p = Path(Config.MEDIA_DIR) / "rooms_photos" / "x.jpg"
rel = ch._media_url(p)
check(rel == "/media/rooms_photos/x.jpg", "B9 media_url_relative", rel)
check(ch._media_url(Path("C:/ngoai/media.jpg")) is None, "B11 media_url_outside_none")

# B10: send_file có file local trong MEDIA_DIR → ưu tiên đường dẫn tương đối
_out = Path(Config.MEDIA_DIR) / "outbox"; _out.mkdir(parents=True, exist_ok=True)
_f = _out / "wc_test_clip.mp4"; _f.write_bytes(b"x")
ch.send_file(uid, str(_f), "https://tunnel-chet.example/media/outbox/wc_test_clip.mp4", "video")
m10, _ = ch.fetch(uid, ch.last_seq(uid) - 1)
check(m10[0]["url"] == "/media/outbox/wc_test_clip.mp4", "B10 send_file_prefers_relative", f"{m10}")
_f.unlink(missing_ok=True)

# notify_owner theo ctx site (owner đã đặt ở A5)
ch.set_ctx(sid)
ch.notify_owner("Khách cần hỗ trợ!")
mo, _ = ch.fetch(f"web:{sid}:vOwner123", 0)
check(mo and mo[-1]["text"] == "Khách cần hỗ trợ!", "B12 notify_owner_outbox", f"{mo}")
ch.set_ctx(None)
ch.notify_owner("rơi vào đâu?")   # không ctx → chỉ log, không crash
check(True, "B13 notify_no_ctx_safe")

print("\n── C. API công khai ──")

class FakeChannelBrain:
    """Brain giả: nhận tin → lưu user msg + trả lời cố định qua channel."""
    def __init__(self, channel, conv):
        self.channel = channel; self.conv = conv; self.calls = []
    def handle(self, user_id, text):
        self.calls.append((user_id, text))
        c = self.conv.get(user_id)
        c.add_user_message(text)
        self.channel.send_text(user_id, "Dạ shop chào bạn ạ!")
        c.add_assistant_message("Dạ shop chào bạn ạ!")
        self.conv.save()

chan = WebChatChannel(store=store, conv_manager=cm)
brain = FakeChannelBrain(chan, cm)
api = wc.create_webchat_api(brain, cm, chan, store).test_client()

# C1: gửi hợp lệ → bot trả lời (WORKER_SYNC → chạy ngay) → poll thấy reply
with patch("app.core.billing.channel_gate", return_value=True):
    r = api.post("/webchat/pub/send", json={"site": sid, "visitor": "vKhach01", "text": "còn phòng không?"})
check(r.status_code == 200 and r.get_json()["ok"] and r.get_json()["bot"], "C1 send_ok", f"{r.get_json()}")
check(brain.calls and brain.calls[-1] == (f"web:{sid}:vKhach01", "còn phòng không?"), "C1 brain_called", f"{brain.calls}")
r = api.get(f"/webchat/pub/poll?site={sid}&visitor=vKhach01&since=0")
j = r.get_json()
check(j["ok"] and j["messages"] and j["messages"][-1]["text"] == "Dạ shop chào bạn ạ!", "C2 poll_reply", f"{j}")
_seq_after = j["seq"]
r = api.get(f"/webchat/pub/poll?site={sid}&visitor=vKhach01&since={_seq_after}")
check(r.get_json()["messages"] == [], "C3 poll_since")

# C4: history đọc từ conversation (kể cả sau restart outbox)
r = api.get(f"/webchat/pub/history?site={sid}&visitor=vKhach01")
j = r.get_json()
check(j["ok"] and j["name"] == "Web Haru" and len(j["messages"]) == 2
      and j["messages"][0]["role"] == "user", "C4 history", f"{j}")

# C5: site sai 404, visitor sai 400, tin trống 400
check(api.post("/webchat/pub/send", json={"site": "wcFAKE00000", "visitor": "vKhach01", "text": "hi"}).status_code == 404, "C5 bad_site_404")
check(api.post("/webchat/pub/send", json={"site": sid, "visitor": "x!", "text": "hi"}).status_code == 400, "C5 bad_visitor_400")
check(api.post("/webchat/pub/send", json={"site": sid, "visitor": "vKhach01", "text": ""}).status_code == 400, "C5 empty_400")

# C6: tên khách tự đặt + nhận name từ widget
conv = cm.get(f"web:{sid}:vKhach01")
check(conv.name.startswith("Khách web #"), "C6 auto_name", conv.name)
with patch("app.core.billing.channel_gate", return_value=True):
    api.post("/webchat/pub/send", json={"site": sid, "visitor": "vKhach01", "text": "tôi tên Lan", "name": "Lan"})
check(cm.get(f"web:{sid}:vKhach01").name == "Lan", "C6 name_from_widget")

# C7: GATE — bot tắt per-site → KHÔNG gọi brain nhưng tin VẪN LƯU vào conv
state = bridge_mod._load_bot_state()
state.setdefault("channels", {})[f"webchat:{sid}"] = False
bridge_mod._save_bot_state(state)
n_calls = len(brain.calls)
n_msgs = len(cm.get(f"web:{sid}:vGate01").messages)
r = api.post("/webchat/pub/send", json={"site": sid, "visitor": "vGate01", "text": "alo?"})
j = r.get_json()
check(r.status_code == 200 and j["ok"] and j["bot"] is False, "C7 gated_bot_false", f"{j}")
check(len(brain.calls) == n_calls, "C7 brain_not_called")
check(len(cm.get(f"web:{sid}:vGate01").messages) == n_msgs + 1, "C7 msg_still_saved")
state["channels"][f"webchat:{sid}"] = True
bridge_mod._save_bot_state(state)

# C8: GATE owner_active → bot im
cm.get(f"web:{sid}:vKhach01").set_owner_active(True)
with patch("app.core.billing.channel_gate", return_value=True):
    r = api.post("/webchat/pub/send", json={"site": sid, "visitor": "vKhach01", "text": "chủ ơi"})
check(r.get_json()["bot"] is False, "C8 owner_active_gate")
cm.get(f"web:{sid}:vKhach01").set_owner_active(False)

# C9: GATE billing → bot im, tin vẫn lưu
with patch("app.core.billing.channel_gate", return_value=False):
    r = api.post("/webchat/pub/send", json={"site": sid, "visitor": "vQuota01", "text": "hi"})
check(r.get_json()["bot"] is False and len(cm.get(f"web:{sid}:vQuota01").messages) == 1, "C9 billing_gate")

# C10: rate-limit theo IP
old_max = wc.RATE_MAX
wc.RATE_MAX = 3
wc._hits.clear()
codes = [api.post("/webchat/pub/send", json={"site": sid, "visitor": "vRate01", "text": f"m{i}"}).status_code
         for i in range(5)]
check(codes.count(429) == 2, "C10 rate_limit_429", f"{codes}")
wc.RATE_MAX = old_max
wc._hits.clear()

# C11: widget.js + CORS "*" cho route công khai; route quản trị thì KHÔNG
r = api.get("/widget.js")
check(r.status_code == 200 and "javascript" in r.content_type
      and b"nvc-fab" in r.data, "C11 widget_served", r.content_type)
check(r.headers.get("Access-Control-Allow-Origin") == "*", "C11 widget_cors_star")
r = api.get(f"/webchat/pub/poll?site={sid}&visitor=vKhach01&since=0")
check(r.headers.get("Access-Control-Allow-Origin") == "*", "C11 pub_cors_star")
r = api.get("/webchat/sites")
check(r.headers.get("Access-Control-Allow-Origin") != "*", "C11 admin_no_star")

# C12: /media traversal bị chặn (route-level hoặc normalize) — không bao giờ 200
r = api.get("/media/..%2f..%2fapp%2fcore%2fconfig.py")
check(r.status_code in (403, 404), "C12 media_traversal_blocked", f"{r.status_code}")

print("\n── D. API quản trị ──")

# D1: tạo site → snippet chứa /widget.js + data-site
r = api.post("/webchat/sites", json={"name": "Web Mochi"})
j = r.get_json()
check(r.status_code == 200 and j["ok"] and "/widget.js" in j["site"]["snippet"]
      and j["site"]["site_id"] in j["site"]["snippet"], "D1 create_site", f"{j}")
sid_b = j["site"]["site_id"]

# D2: list sites có bot_enabled + snippet
r = api.get("/webchat/sites")
sites = r.get_json()
check(len(sites) == 2 and all("snippet" in s and "bot_enabled" in s for s in sites), "D2 list_sites", f"{sites}")

# D3: toggle per-site ghi bot_state key webchat:<id>
api.post(f"/webchat/sites/{sid_b}/toggle", json={"enabled": False})
check(bridge_mod._load_bot_state()["channels"][f"webchat:{sid_b}"] is False, "D3 toggle_state")
r = api.get("/webchat/sites")
check([s for s in r.get_json() if s["site_id"] == sid_b][0]["bot_enabled"] is False, "D3 toggle_reflected")

# D4: set-owner qua API
r = api.post("/webchat/set-owner", json={"user_id": f"web:{sid_b}:vBoss99", "name": "Chị Chủ"})
check(r.get_json()["ok"] and store.get_owner_user_id(sid_b) == "vBoss99", "D4 set_owner_api")
check(api.post("/webchat/set-owner", json={"user_id": "rác"}).status_code == 400, "D4 bad_uid_400")

# D5: conversations {total, items} + filter theo site
r = api.get("/webchat/conversations")
j = r.get_json()
check(j["total"] >= 3 and isinstance(j["items"], list), "D5 conv_list", f"total={j.get('total')}")
r = api.get(f"/webchat/conversations?site_id={sid_b}")
check(r.get_json()["total"] == 0, "D5 conv_filter_site")

# D6: chi tiết hội thoại
r = api.get(f"/webchat/conversations/web:{sid}:vKhach01")
j = r.get_json()
check(j["user_id"] == f"web:{sid}:vKhach01" and len(j["messages"]) >= 2, "D6 conv_detail", f"{j.get('user_id')}")
check(api.get("/webchat/conversations/web:none:x").status_code == 404, "D6 not_found_404")

# D7: chủ nhắn tay → vào OUTBOX (widget thấy) + owner_active bật + hook học
with patch("app.core.knowledge_learn.suggest_from_reply") as mock_learn:
    before = chan.last_seq(f"web:{sid}:vKhach01")
    r = api.post(f"/webchat/conversations/web:{sid}:vKhach01/send", json={"text": "Chủ shop đây ạ!"})
    check(r.get_json()["ok"], "D7 owner_send_ok")
    mm, _ = chan.fetch(f"web:{sid}:vKhach01", before)
    check(mm and mm[-1]["text"] == "Chủ shop đây ạ!", "D7 owner_msg_in_outbox", f"{mm}")
    check(cm.get(f"web:{sid}:vKhach01").is_owner_active(), "D7 owner_active_on")
    check(mock_learn.called, "D7 learn_hook_called")

# D8: toggle-bot per-conversation + reset
api.post(f"/webchat/conversations/web:{sid}:vKhach01/toggle-bot", json={"bot_on": True})
check(not cm.get(f"web:{sid}:vKhach01").is_owner_active(), "D8 bot_on_again")
api.delete(f"/webchat/conversations/web:{sid}:vKhach01")
check(len(cm.get(f"web:{sid}:vKhach01").messages) == 0, "D8 reset")

# Dọn
bridge_mod.BOT_STATE_FILE.unlink(missing_ok=True)
Path("test_wc_store_tmp.json").unlink(missing_ok=True)
print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
