#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_avatar.py — AVATAR THẬT của khách trên dashboard:
  - ConversationState.avatar persist SQLite (save → load lại)
  - bridge: /incoming nhận avatar từ Node (zca-js avt); _conv_summary + detail trả avatar
  - meta: _fetch_meta_name lấy name + profile_pic → conv.avatar
  - zalo_oa: _fetch_oa_profile lấy display_name + avatar
  - telegram: /tg/avatar/<f> serve ảnh đã tải về (chặn traversal)

Chạy (TỪ GỐC):  python tests/test_avatar.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_avatar_tmp.sqlite'   # DB test RIÊNG file này
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from pathlib import Path
from app.core.conversation import ConversationManager
from app.core.config import Config

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

print("\n── A. Avatar persist SQLite ──")
cm = ConversationManager(account="av-test")
cm._sessions.clear()
c = cm.get("U1")
c.add_user_message("hi")
c.name = "Khách A"
c.avatar = "https://cdn.example.com/a.jpg"
cm.save()

cm2 = ConversationManager(account="av-test")   # load lại từ DB
c2 = cm2._sessions.get("U1")
check(c2 is not None and c2.avatar == "https://cdn.example.com/a.jpg", "A1 persist_reload",
      f"{getattr(c2, 'avatar', None)}")
check(cm2.get("KHACH_MOI").avatar == "", "A2 default_empty")

print("\n── B. Bridge: avatar từ Node + trả ra API ──")
from app.core.brain import Brain
from app.core.channel import Channel
import app.web_api.bridge as bridge_mod

class FakeChannel(Channel):
    def send_text(self, uid, text): pass
    def send_room_photos(self, uid, names): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, text): pass
    def call_owner(self): pass

bridge_mod.BOT_STATE_FILE = Path("test_bot_state_av_tmp.json")
cm._sessions.clear()
brain = Brain(channel=FakeChannel(), conv_manager=cm)
client = bridge_mod.create_bridge(brain, cm).test_client()

with patch('app.core.brain.analyze_message', return_value={"intent": "other", "reply": "Chào!"}), \
     patch('app.core.brain.format_availability_for_ai', return_value=""):
    r = client.post("/incoming", json={"userId": "Z9", "text": "xin chào",
                                       "dName": "Anh Ba", "avatar": "https://ava.zdn.vn/ba.jpg"})
check(r.status_code == 200, "B1 incoming_ok")
check(cm.get("Z9").avatar == "https://ava.zdn.vn/ba.jpg", "B1 avatar_saved",
      f"{cm.get('Z9').avatar}")

rows = client.get("/conversations").get_json()
row = next((x for x in rows if x["user_id"] == "Z9"), None)
check(row and row["avatar"] == "https://ava.zdn.vn/ba.jpg", "B2 summary_has_avatar", f"{row}")
d = client.get("/conversations/Z9").get_json()
check(d["avatar"] == "https://ava.zdn.vn/ba.jpg", "B3 detail_has_avatar")

print("\n── C. Meta: profile_pic → conv.avatar ──")
import app.web_api.meta_webhook as meta_mod

class _FakeBrainMeta:
    class channel:
        @staticmethod
        def _token_for(pid): return "TOK"
cm._sessions.clear()
mresp = MagicMock(status_code=200)
mresp.json = lambda: {"name": "Nguyễn Văn Tèo", "profile_pic": "https://scontent.xx/pic.jpg"}
with patch.object(meta_mod, '_req') as mrq:
    mrq.get.return_value = mresp
    meta_mod._fetch_meta_name("fb:PG:U7", "U7", "PG", "fb", _FakeBrainMeta, cm)
conv = cm.get("fb:PG:U7")
check(conv.name == "Nguyễn Văn Tèo" and conv.avatar == "https://scontent.xx/pic.jpg",
      "C1 meta_profile_pic", f"name={conv.name} av={conv.avatar}")
# fields gửi lên Graph có profile_pic
check("profile_pic" in mrq.get.call_args[1]["params"]["fields"], "C2 fields_include_pic")

print("\n── D. Zalo OA: user/detail → conv.avatar ──")
import app.web_api.zalo_oa_api as oa_mod

class _FakeOAChannel:
    @staticmethod
    def _token_for(oa): return "OATOK"
cm._sessions.clear()
oresp = MagicMock(status_code=200, content=b"x")
oresp.json = lambda: {"error": 0, "data": {"display_name": "Chị Tư",
                                            "avatar": "https://ava.zdn.vn/tu.jpg"}}
with patch.object(oa_mod, 'requests') as orq:
    orq.get.return_value = oresp
    oa_mod._fetch_oa_profile("oa:O1:U8", "O1", "U8", cm, _FakeOAChannel)
conv = cm.get("oa:O1:U8")
check(conv.name == "Chị Tư" and conv.avatar == "https://ava.zdn.vn/tu.jpg",
      "D1 oa_profile", f"name={conv.name} av={conv.avatar}")

# D2: dạng avatars dict (API version khác) → lấy bản 240
oresp2 = MagicMock(status_code=200, content=b"x")
oresp2.json = lambda: {"error": 0, "data": {"display_name": "Chú Năm",
                                             "avatars": {"120": "u120", "240": "u240"}}}
with patch.object(oa_mod, 'requests') as orq:
    orq.get.return_value = oresp2
    oa_mod._fetch_oa_profile("oa:O1:U9", "O1", "U9", cm, _FakeOAChannel)
check(cm.get("oa:O1:U9").avatar == "u240", "D2 avatars_dict_240")

print("\n── E. Telegram: serve avatar local ──")
from app.core.telegram_store import TelegramStore
from app.channels.telegram import TelegramChannel
import app.web_api.telegram_api as tg_mod

store = TelegramStore(path=Path("test_tg_store_av_tmp.json"))
store._bots = {}
ch = TelegramChannel(store=store, token="", conv_manager=cm)

class _FB:
    channel = ch
    def handle(self, *a): pass

api = tg_mod.create_telegram_api(_FB(), cm, ch, store).test_client()
av_dir = Config.DATA_DIR / "avatars"
av_dir.mkdir(exist_ok=True)
(av_dir / "tg_test_av.jpg").write_bytes(b"\xff\xd8fakejpg")

r = api.get("/tg/avatar/tg_test_av.jpg")
check(r.status_code == 200 and r.data.startswith(b"\xff\xd8"), "E1 serve_avatar", f"{r.status_code}")
# traversal bị chặn (Path(fname).name bỏ đường dẫn)
r = api.get("/tg/avatar/..%2F..%2Fbot_state.json")
check(r.status_code in (404, 200) and b"enabled" not in (r.data or b""), "E2 no_traversal")
# detail endpoint có field avatar
cm.get("tg:B1:55").add_user_message("hi")
d = api.get("/tg/conversations/tg:B1:55").get_json()
check("avatar" in d, "E3 detail_has_avatar")

# Dọn file tạm
(av_dir / "tg_test_av.jpg").unlink(missing_ok=True)
Path("test_bot_state_av_tmp.json").unlink(missing_ok=True)
Path("test_tg_store_av_tmp.json").unlink(missing_ok=True)

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
