#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_chat_tools.py — công cụ chat (gửi media + chốt đơn + câu trả lời mẫu):
  A. Channel.send_file base = gửi LINK; Telegram override upload thật
  B. chat_tools API: send-media (ảnh→send_image_url, video→send_file, chặn file lạ,
     lưu message + owner_active), make-order (bóc hội thoại→đơn), canned CRUD,
     serve /media/outbox chặn traversal

Chạy (TỪ GỐC):  python tests/test_chat_tools.py
"""

import os, sys
from unittest.mock import MagicMock, patch
from io import BytesIO

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
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_chattools_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from pathlib import Path
from flask import Flask
from app.core.conversation import ConversationManager
from app.core.channel import Channel
import app.web_api.chat_tools as ct

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

print("\n── A. Channel.send_file ──")
sent = []
class _Ch(Channel):
    def send_text(self, u, t): sent.append(("text", u, t))
    def send_room_photos(self, u, n): pass
    def send_price_photos(self, u): pass
    def send_image_url(self, u, url, cap=""): sent.append(("img", u, url, cap))
    def notify_owner(self, t): pass
    def call_owner(self): pass

ch = _Ch()
# base send_file: có URL → gửi link (text); không URL → False
sent.clear()
ok = ch.send_file("U1", "/tmp/x.mp4", "https://pub/x.mp4", "video", "cho xem")
check(ok and sent and sent[-1][0] == "text" and "https://pub/x.mp4" in sent[-1][2], "A1 base_link", f"{sent}")
check(ch.send_file("U1", "/tmp/x.mp4", "", "video") is False, "A2 no_url_false")

# Telegram override: upload thật (patch requests.post)
from app.channels.telegram import TelegramChannel
tch = TelegramChannel(store=None, token="TOK", conv_manager=None)
tmp = Path(str(_TMPDIR / "test_media_tmp.mp4")); tmp.write_bytes(b"\x00\x00fakevideo")
with patch.object(__import__('app.channels.telegram', fromlist=['requests']), 'requests') as mreq:
    calls = []
    def fake_post(url, data=None, files=None, timeout=None):
        calls.append(url); m = MagicMock(); m.status_code = 200; return m
    mreq.post.side_effect = fake_post
    ok = tch.send_file("tg:U9", tmp, "https://x/x.mp4", "video", "cap")
check(ok and any("sendVideo" in u for u in calls), "A3 tg_upload_video", f"{calls}")
# A3b: Telegram gửi ẢNH thật (sendPhoto upload), không phụ thuộc URL
with patch.object(__import__('app.channels.telegram', fromlist=['requests']), 'requests') as mreq:
    calls = []
    def fake_post2(url, data=None, files=None, timeout=None):
        calls.append(url); m = MagicMock(); m.status_code = 200; return m
    mreq.post.side_effect = fake_post2
    img = Path(str(_TMPDIR / "test_img_tmp.png")); img.write_bytes(b"\x89PNG\x00")
    ok = tch.send_file("tg:U9", img, "", "image", "cap")   # url rỗng vẫn gửi được (upload path)
    img.unlink(missing_ok=True)
check(ok and any("sendPhoto" in u for u in calls), "A3b tg_upload_photo", f"{calls}")
tmp.unlink(missing_ok=True)

# A4: Zalo Node — ẢNH gửi qua PATH LOCAL (không tải URL/tunnel); VIDEO/AUDIO → False
from app.channels.zalo_node import ZaloNodeChannel
zch = ZaloNodeChannel()
posted = []
zch._post = lambda path, data: posted.append((path, data))
zch._mark_bot_send = lambda uid: None
zch.send_text = lambda uid, t: posted.append(("text", t))
ok = zch.send_file("Z1", "F:/x/anh.png", "https://tunnel-chet/x.png", "image", "cap")
check(ok and any(p[0] == "/send-image" and "anh.png" in str(p[1]) for p in posted),
      "A4 zalo_image_path", f"{posted}")
check(zch.send_file("Z1", "/x/v.mp4", "http://x", "video") is False, "A4 zalo_video_false")
check(zch.send_file("Z1", "/x/a.webm", "http://x", "audio") is False, "A4 zalo_audio_false")

print("\n── B. chat_tools API ──")
cm = ConversationManager(account="ct-test")
cm._sessions.clear()

class FakeBrain:
    def __init__(self): self.channel = _Ch()

app = Flask(__name__)
ct.register_chat_tools(app, "/tg", cm, FakeBrain().channel, account="telegram", with_canned=True)
api = app.test_client()

def _upload(uid, fname, ctype, data=b"x" * 100, caption=""):
    return api.post(f"/tg/conversations/{uid}/send-media",
                    data={"file": (BytesIO(data), fname, ctype), "caption": caption},
                    content_type="multipart/form-data")

# B1: gửi ẢNH → send_image_url + lưu message + owner_active
sent.clear()
cm.get("tg:B1:U1")
r = _upload("tg:B1:U1", "anh.jpg", "image/jpeg", caption="đây nhé")
check(r.status_code == 200 and r.get_json()["kind"] == "image", "B1 image_ok", f"{r.get_json()}")
check(any(s[0] == "img" for s in sent), "B1 called_send_image_url")
conv = cm.get("tg:B1:U1")
check("[Đã gửi ảnh" in conv.messages[-1]["content"] and conv.is_owner_active(), "B1 msg_saved_owner")

# B2: gửi VIDEO → send_file
sent.clear()
r = _upload("tg:B1:U1", "clip.mp4", "video/mp4")
check(r.status_code == 200 and r.get_json()["kind"] == "video", "B2 video_ok", f"{r.get_json()}")

# B3: file lạ (.exe) → 400
r = _upload("tg:B1:U1", "virus.exe", "application/octet-stream")
check(r.status_code == 400, "B3 reject_bad_type", f"{r.status_code}")

# B4: thiếu file → 400
r = api.post("/tg/conversations/tg:B1:U1/send-media", data={}, content_type="multipart/form-data")
check(r.status_code == 400, "B4 no_file_400")

# B5: serve /media/outbox chặn traversal
ct.OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
(ct.OUTBOX_DIR / "real.jpg").write_bytes(b"\xff\xd8jpg")
r = api.get("/media/outbox/real.jpg")
check(r.status_code == 200 and r.data.startswith(b"\xff\xd8"), "B5 serve_ok")
r = api.get("/media/outbox/..%2f..%2fbot_state.json")
check(b"enabled" not in (r.data or b""), "B5 no_traversal")
(ct.OUTBOX_DIR / "real.jpg").unlink(missing_ok=True)

# B6: make-order (patch orders.create_from_conversation)
conv = cm.get("tg:B1:U1")
conv.add_user_message("chốt phòng 301 tối nay")
with patch("app.core.orders.create_from_conversation",
           return_value={"id": 5, "code": "DH0005", "total": 500000, "customer_name": "A"}):
    r = api.post("/tg/conversations/tg:B1:U1/make-order")
check(r.status_code == 200 and r.get_json()["order"]["code"] == "DH0005", "B6 make_order", f"{r.get_json()}")
# hội thoại trống → 400
r = api.post("/tg/conversations/tg:KHONG:CO/make-order")
check(r.status_code == 400, "B6 empty_conv_400")

# B7: canned CRUD
r = api.post("/canned", json={"title": "Chào", "content": "Xin chào anh/chị 😊"})
cid = r.get_json()["id"]
check(r.status_code == 200 and cid, "B7 canned_add")
r = api.get("/canned")
check(any(c["id"] == cid and c["title"] == "Chào" for c in r.get_json()), "B7 canned_list")
r = api.post("/canned", json={"content": ""})
check(r.status_code == 400, "B7 canned_empty_400")
r = api.delete(f"/canned/{cid}")
check(r.status_code == 200 and not any(c["id"] == cid for c in api.get("/canned").get_json()),
      "B7 canned_del")

Path(str(_TMPDIR / "test_media_tmp.mp4")).unlink(missing_ok=True)
print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
