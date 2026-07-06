#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_posts.py — Bài viết & bình luận Facebook:
  - contains_phone: SĐT VN đủ kiểu viết (tách/chấm/gạch/+84), không false-positive
    mã đơn/dãy số dài
  - CommentStore: default/set/ép kiểu
  - handle_feed_change: echo Page tự bình luận, ẩn SĐT + notify + vẫn nhắn riêng,
    tự trả lời {name}, tắt hết → không làm gì
  - posts_api (Flask): settings roundtrip + re-subscribe feed, list posts,
    reply/hide/private-reply, thiếu page_id/token → 400
  - webhook feed end-to-end: POST /fb/webhook changes field=feed → auto action,
    gửi LẠI cùng comment_id → dedup

Chạy (TỪ GỐC):  python tests/test_posts.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_posts_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

import json
from pathlib import Path
from app.core import comments
from app.core.comment_store import CommentStore, DEFAULTS
import app.core.http_util as httputil

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

print("\n── A. contains_phone (SĐT Việt Nam) ──")
YES = [
    "gọi em 0912345678 nha",
    "SDT: 09 12 34 56 78",
    "0912.345.678 gọi nhé shop",
    "0912-345-678",
    "+84912345678",
    "84 912 345 678 zalo em",
    "giá nhiêu ib e (0868)123456",
]
NO = [
    "còn hàng không shop?",
    "giá 500000đ hả",
    "mã đơn DH00012345678 của em",   # dính vào dãy số dài hơn → không phải SĐT
    "091234",                        # quá ngắn
    "năm 2026 tháng 7",
]
for t in YES:
    check(comments.contains_phone(t), f"A phone_yes: {t[:30]!r}")
for t in NO:
    check(not comments.contains_phone(t), f"A phone_no: {t[:30]!r}")

print("\n── B. CommentStore ──")
cs = CommentStore(path=Path("test_cmt_store_tmp.json"))
cs._pages = {}
s = cs.get("PG1")
check(s == DEFAULTS, "B1 defaults", f"{s}")
cs.set("PG1", {"auto_hide_phone": 1, "auto_reply_text": "  Cảm ơn {name}!  ",
               "khong_hop_le": True})
s = cs.get("PG1")
check(s["auto_hide_phone"] is True and s["auto_reply_text"] == "Cảm ơn {name}!"
      and "khong_hop_le" not in s, "B2 set_clean", f"{s}")
cs2 = CommentStore(path=Path("test_cmt_store_tmp.json"))
check(cs2.get("PG1")["auto_hide_phone"] is True, "B3 persist")

print("\n── C. handle_feed_change ──")

def _val(msg, from_id="U1", name="Khách A", **kw):
    return {"item": "comment", "verb": "add", "comment_id": "C1",
            "post_id": "P1", "from": {"id": from_id, "name": name},
            "message": msg, **kw}

def _fake_graph():
    """Patch requests.post trong http_util → ghi lại (url, json) từng call."""
    calls = []
    def fake_post(url, params=None, json=None, timeout=None, **kw):
        calls.append((url, json))
        m = MagicMock(); m.status_code = 200; m.content = b"{}"
        m.json = lambda: {"success": True}
        return m
    return calls, fake_post

ALL_ON = {"auto_hide_phone": True, "auto_reply": True,
          "auto_reply_text": "Cảm ơn {name} nha!",
          "private_reply": True, "private_reply_text": "Chào {name}, shop tư vấn nhé"}

# C1: Page tự bình luận (echo) → không làm gì (chống vòng lặp tự trả lời)
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    done = comments.handle_feed_change("PG1", _val("Cảm ơn khách", from_id="PG1"),
                                       "TOK", ALL_ON)
check(done == {"hidden": False, "replied": False, "private_replied": False}
      and calls == [], "C1 page_echo_skip", f"{done} {calls}")

# C2: bình luận lộ SĐT → ẨN + notify + nhắn riêng, KHÔNG trả lời công khai
calls, fp = _fake_graph()
notes = []
with patch.object(httputil.requests, 'post', side_effect=fp):
    done = comments.handle_feed_change("PG1", _val("shop ơi 0912345678 gọi em"),
                                       "TOK", ALL_ON, notify=notes.append)
check(done["hidden"] and done["private_replied"] and not done["replied"],
      "C2 phone_hide_private", f"{done}")
check(any("/C1" in u and (j or {}).get("is_hidden") is True for u, j in calls),
      "C2 hide_call", f"{calls}")
check(any("private_replies" in u for u, _ in calls), "C2 private_call")
check(notes and "SĐT" in notes[0] and "Khách A" in notes[0], "C2 notify_owner", f"{notes}")

# C3: bình luận thường → trả lời công khai (điền {name}) + nhắn riêng
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    done = comments.handle_feed_change("PG1", _val("còn hàng không?"), "TOK", ALL_ON)
check(done["replied"] and done["private_replied"] and not done["hidden"],
      "C3 reply_and_private", f"{done}")
reply_call = next((j for u, j in calls if u.endswith("/C1/comments")), None)
check(reply_call and reply_call["message"] == "Cảm ơn Khách A nha!", "C3 name_filled", f"{reply_call}")

# C4: tắt hết → không call nào
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    done = comments.handle_feed_change("PG1", _val("0912345678"), "TOK", dict(DEFAULTS))
check(calls == [] and not any(done.values()), "C4 all_off_noop", f"{done}")

# C5: không phải comment (like/post) hoặc verb khác → bỏ
with patch.object(httputil.requests, 'post', side_effect=fp):
    d1 = comments.handle_feed_change("PG1", {"item": "like", "verb": "add"}, "TOK", ALL_ON)
    d2 = comments.handle_feed_change("PG1", _val("x", verb="remove") | {"verb": "remove"}, "TOK", ALL_ON)
check(not any(d1.values()) and not any(d2.values()), "C5 non_comment_skip")

print("\n── D. posts_api (Flask) ──")
from app.core.conversation import ConversationManager
from app.core.meta_store import MetaStore
import app.web_api.meta_webhook as mw
import app.web_api.bridge as bridge_mod

bridge_mod.BOT_STATE_FILE = Path("test_bot_state_posts_tmp.json")

class _FakeCh:
    def __init__(self): self.notes = []
    def notify_owner(self, t): self.notes.append(t)
    def send_text(self, uid, t): pass
    def _token_for(self, pid): return None

class FakeBrain:
    def __init__(self): self.handled = []; self.channel = _FakeCh()
    def handle(self, uid, text): self.handled.append((uid, text))

cm = ConversationManager(account="posts-test")
cm._sessions.clear()
mstore = MetaStore(path=Path("test_meta_store_posts_tmp.json"))
mstore._pages = {}
mstore.upsert("PG9", name="Page Test", access_token="PTOK")

fb = FakeBrain()
_cstore = CommentStore(path=Path("test_cmt_settings_api_tmp.json"))
_cstore._pages = {}
api = mw.create_meta_webhook(fb, cm, mstore, comment_store=_cstore).test_client()

# D1: settings mặc định + thiếu page_id → 400
check(api.get("/posts/settings").status_code == 400, "D1 settings_no_page_400")
r = api.get("/posts/settings?page_id=PG9")
check(r.status_code == 200 and r.get_json()["settings"]["auto_reply"] is False, "D1 settings_default")

# D2: lưu settings → re-subscribe feed được gọi
with patch.object(mw.meta_graph, 'subscribe_page', return_value=True) as msub:
    r = api.post("/posts/settings", json={"page_id": "PG9", "auto_hide_phone": True})
check(r.status_code == 200 and r.get_json()["feed_subscribed"] is True, "D2 settings_saved")
check(msub.call_args[0][0] == "PG9" and msub.call_args[0][1] == "PTOK", "D2 resubscribe_with_token")
check(api.get("/posts/settings?page_id=PG9").get_json()["settings"]["auto_hide_phone"] is True,
      "D2 persisted")

# D3: list posts (mock Graph GET)
_posts_resp = MagicMock(status_code=200)
_posts_resp.json = lambda: {"data": [{
    "id": "PG9_111", "message": "Sale cuối tuần!", "created_time": "2026-07-05T10:00:00+0000",
    "permalink_url": "https://fb.com/x", "full_picture": "https://cdn/p.jpg",
    "comments": {"summary": {"total_count": 3}}}]}
with patch.object(comments.requests, 'get', return_value=_posts_resp):
    r = api.get("/posts?page_id=PG9")
body = r.get_json()
check(r.status_code == 200 and body["items"][0]["comment_count"] == 3
      and body["items"][0]["message"] == "Sale cuối tuần!", "D3 list_posts", f"{body}")
check(api.get("/posts?page_id=KHONG_CO").status_code == 400, "D3 no_token_400")

# D4: list comments (kèm has_phone)
_cmt_resp = MagicMock(status_code=200)
_cmt_resp.json = lambda: {"data": [
    {"id": "C7", "from": {"id": "U7", "name": "Khách B"}, "message": "ib em 0868123456",
     "created_time": "2026-07-05T10:05:00+0000", "is_hidden": False, "like_count": 0},
]}
with patch.object(comments.requests, 'get', return_value=_cmt_resp):
    r = api.get("/posts/PG9_111/comments?page_id=PG9")
body = r.get_json()
check(r.status_code == 200 and body["items"][0]["has_phone"] is True, "D4 comments_has_phone", f"{body}")

# D5: reply / hide / private-reply gọi Graph đúng endpoint
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    r1 = api.post("/comments/C7/reply", json={"page_id": "PG9", "message": "Dạ shop đây ạ"})
    r2 = api.post("/comments/C7/hide", json={"page_id": "PG9", "hidden": True})
    r3 = api.post("/comments/C7/private-reply", json={"page_id": "PG9", "message": "Chào bạn"})
check(r1.status_code == 200 and any(u.endswith("/C7/comments") for u, _ in calls), "D5 reply")
check(r2.status_code == 200 and any((j or {}).get("is_hidden") for _, j in calls), "D5 hide")
check(r3.status_code == 200 and any("private_replies" in u for u, _ in calls), "D5 private")
check(api.post("/comments/C7/reply", json={"page_id": "PG9", "message": ""}).status_code == 400,
      "D5 empty_400")

print("\n── E. Webhook feed end-to-end ──")
mw._feed_dedup._d.clear()
# bật auto trên PG9 (đã bật auto_hide_phone ở D2) + thêm auto_reply
api.post("/posts/settings", json={"page_id": "PG9", "auto_reply": True,
                                  "auto_reply_text": "Cảm ơn {name}!"})

feed_payload = {"object": "page", "entry": [{"id": "PG9", "changes": [
    {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "CE1",
                                "post_id": "PG9_111", "from": {"id": "U9", "name": "Khách C"},
                                "message": "còn size M không?"}}]}]}
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    r = api.post("/fb/webhook", json=feed_payload)
check(r.status_code == 200, "E1 webhook_200")
check(any(u.endswith("/CE1/comments") and j["message"] == "Cảm ơn Khách C!" for u, j in calls),
      "E1 auto_reply_fired", f"{calls}")

# E2: Meta gửi LẠI cùng comment_id → dedup, không trả lời lần 2
calls, fp = _fake_graph()
with patch.object(httputil.requests, 'post', side_effect=fp):
    api.post("/fb/webhook", json=feed_payload)
check(calls == [], "E2 feed_dedup", f"{calls}")

# E3: field=messages vẫn chạy bình thường (không vỡ luồng tin nhắn cũ)
with patch.object(mw, '_load_bot_state', return_value={"enabled": True}), \
     patch('app.core.billing.channel_gate', return_value=True):
    api.post("/fb/webhook", json={"object": "page", "entry": [{"id": "PG9", "messaging": [
        {"sender": {"id": "U55"}, "message": {"mid": "m1", "text": "hỏi giá"}}]}]})
check(fb.handled and fb.handled[-1][0] == "fb:PG9:U55", "E3 messaging_still_works", f"{fb.handled}")

# Dọn file tạm
for f in ["test_cmt_store_tmp.json", "test_meta_store_posts_tmp.json",
          "test_bot_state_posts_tmp.json", "test_cmt_settings_api_tmp.json"]:
    Path(f).unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
