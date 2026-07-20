#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_zalo_multi.py — ZALO CÁ NHÂN MULTI-ACCOUNT (mỗi shop 1 acc riêng):
  A. ZaloNodeChannel._parse + payload gửi Node kèm acc + ctx notify + call gate
  B. ZaloNodeStore: cấp acc, mapping owner, ensure
  C. bridge /incoming: acc → user_id namespaced, gate theo chủ shop, tenant,
     acc default giữ uid TRẦN (tương thích dữ liệu cũ)
  D. /zalo/my-account: chủ nền tảng = default, shop khác = acc riêng

Chạy TỪ GỐC: python tests/test_zalo_multi.py
"""

import os, sys
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_zmulti_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_zmulti_tmp.sqlite{suf}")).unlink(missing_ok=True)
Path(str(_TMPDIR / "test_zmulti_store_tmp.json")).unlink(missing_ok=True)

from datetime import datetime
from app.core.channel import Channel
from app.core.conversation import ConversationManager
from app.core.zalo_node_store import ZaloNodeStore
from app.core.brain import Brain
from app.channels.zalo_node import ZaloNodeChannel
import app.web_api.bridge as bridge_mod
import app.core.http_util as httputil

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

from app.core.db import get_db
db = get_db()
# 2 chủ shop: A = chủ nền tảng (đầu tiên), B = shop thuê
db.execute("INSERT INTO users(username, homestay, provider, role, created_at) "
           "VALUES ('chua@x.vn','Shop A','password','owner',?)", (datetime.now().isoformat(),))
db.execute("INSERT INTO users(username, homestay, provider, role, created_at) "
           "VALUES ('chub@x.vn','Shop B','password','owner',?)", (datetime.now().isoformat(),))
from app.core import tenant
tenant._default_cache.update(t=0, v=None)

# ── A. ZaloNodeChannel multi-acc ─────────────────────────────────────
print("A. ZaloNodeChannel")
ch = ZaloNodeChannel(node_url="http://node.test:4000")
check(ch._parse("123456") == ("default", "123456"), "A1 uid trần → acc default")
check(ch._parse("zl:zabc123:999") == ("zabc123", "999"), "A2 zl:acc:uid tách đúng")
check(ch._parse("zl::999") == ("default", "zl::999"), "A3 zl thiếu acc → coi như trần (an toàn)")

calls = []
def fake_post(url, params=None, json=None, timeout=None, headers=None):
    calls.append((url, json)); m = MagicMock(); m.status_code = 200; return m
with patch.object(httputil.requests, 'post', side_effect=fake_post):
    ch.send_text("zl:zabc123:999", "xin chào shop B")
    check(calls and calls[-1][1]["acc"] == "zabc123" and calls[-1][1]["userId"] == "999",
          "A4 send payload kèm acc + uid trần cho Node", calls[-1])
    calls.clear()
    ch.send_text("777", "chào acc default")
    check(calls[-1][1]["acc"] == "default" and calls[-1][1]["userId"] == "777",
          "A5 uid trần → acc default")
    # notify theo ctx
    calls.clear()
    ch.set_ctx("zabc123")
    ch.notify_owner("có đơn!")
    check(calls[-1][0].endswith("/notify-owner") and calls[-1][1]["acc"] == "zabc123",
          "A6 notify_owner đúng acc theo ctx", calls[-1])
    ch.set_ctx(None)
    calls.clear()
    ch.notify_owner("đơn nền tảng")
    check(calls[-1][1]["acc"] == "default", "A7 ctx None → notify acc default")

# call_owner gate: shop thuê KHÔNG kích Telethon của chủ nền tảng
with patch("app.channels.zalo_node.owner_call") as oc:
    ch.set_ctx("zabc123"); ch.call_owner()
    check(not oc.alert.called, "A8 call_owner acc shop → KHÔNG gọi Telethon global")
    ch.set_ctx(None); ch.call_owner()
    check(oc.alert.called, "A9 call_owner acc default → gọi như cũ")

# ── B. ZaloNodeStore ─────────────────────────────────────────────────
print("B. ZaloNodeStore")
store = ZaloNodeStore(path=Path(str(_TMPDIR / "test_zmulti_store_tmp.json")))
acc_b = store.create("chub@x.vn", name="Zalo Shop B")
check(acc_b.startswith("z") and len(acc_b) == 11, "B1 accId format", acc_b)
check(store.get_owner_username(acc_b) == "chub@x.vn", "B2 mapping owner")
check(store.get_owner_username("default") is None, "B3 default → None (gate toàn cục)")
check(store.acc_for_owner("chub@x.vn") == acc_b, "B4 acc_for_owner")
check(store.ensure_for_owner("chub@x.vn") == acc_b, "B5 ensure không cấp trùng")
acc_c = store.ensure_for_owner("chuc@x.vn")
check(acc_c != acc_b, "B6 shop khác → acc khác")
store2 = ZaloNodeStore(path=Path(str(_TMPDIR / "test_zmulti_store_tmp.json")))
check(store2.get_owner_username(acc_b) == "chub@x.vn", "B7 persist qua file")

# ── C. bridge /incoming multi-acc ────────────────────────────────────
print("C. bridge /incoming")
class FakeChannel(Channel):
    def __init__(self): self.texts = []; self._ctx_v = None
    def send_text(self, uid, t): self.texts.append((uid, t))
    def send_room_photos(self, uid, n): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass
    def set_ctx(self, v): self._ctx_v = v
    def get_ctx(self): return self._ctx_v

cm = ConversationManager(account=1)
cm._sessions.clear()
fch = FakeChannel()
brain = Brain(channel=fch, conv_manager=cm)
app = bridge_mod.create_bridge(brain, cm)
# bridge tự tạo ZaloNodeStore() (file thật data/zalo_accounts.json) → thay bằng
# store test qua closure: route đọc zalo_store từ closure — patch không được.
# → Đăng ký acc test vào store THẬT rồi dọn cuối test.
from app.core.zalo_node_store import ZaloNodeStore as _RealStore
real_store = _RealStore()

def _clean_test_accs():
    """Dọn acc test (owner chub/chuc) khỏi store THẬT — kể cả rác lần chạy trước."""
    for a in list(real_store.list_accounts()):
        if a.get("owner_username") in ("chub@x.vn", "chuc@x.vn"):
            real_store.remove(a["acc"])

_clean_test_accs()
acc_real = real_store.create("chub@x.vn", name="test-acc")
client = app.test_client()

handled = []
brain.handle = lambda uid, text: handled.append((uid, text, fch.get_ctx()))

# bot_state đọc file THẬT (máy dev có thể đang tắt bot) → ép bật trong test
_bs_patch = patch.object(bridge_mod, "_load_bot_state",
                         return_value={"enabled": True, "channels": {}})
_bs_patch.start()

# acc default → uid TRẦN (tương thích cũ)
r = client.post("/incoming", json={"userId": "111222", "text": "hi", "isSelf": False})
check(r.status_code == 200 and handled and handled[-1][0] == "111222",
      "C1 acc default: user_id uid trần", handled)
check(cm._sessions["111222"].tenant == "chua@x.vn", "C2 default → tenant chủ nền tảng")

# acc shop B → user_id namespaced + tenant B + ctx acc
r = client.post("/incoming", json={"acc": acc_real, "userId": "333", "text": "hi shop B",
                                   "isSelf": False})
uidB = f"zl:{acc_real}:333"
check(handled[-1][0] == uidB, "C3 acc shop: user_id zl:<acc>:<uid>", handled[-1])
check(cm._sessions[uidB].tenant == "chub@x.vn", "C4 tenant = chủ shop B")
check(handled[-1][2] == acc_real, "C5 ctx acc set trong thread xử lý", handled[-1])

# gate theo gói chủ shop: shop B hết hạn → tin bị bỏ
from app.core import billing
with patch.object(billing, "channel_gate", return_value=False):
    n_before = len(handled)
    r = client.post("/incoming", json={"acc": acc_real, "userId": "444", "text": "x",
                                       "isSelf": False})
    check(r.json.get("skipped") == "billing_expired" and len(handled) == n_before,
          "C6 gói chủ shop chặn → bot im", r.json)

# ── D. /zalo/my-account ──────────────────────────────────────────────
print("D. /zalo/my-account")
from app.web_api.auth_api import register_auth_routes
auth_app = __import__("flask").Flask(__name__)
register_auth_routes(auth_app)
ac = auth_app.test_client()
# đặt mật khẩu để login lấy token
from app.web_api.auth_api import hash_password
db.execute("UPDATE users SET password_hash=? WHERE username='chua@x.vn'", (hash_password("1234"),))
db.execute("UPDATE users SET password_hash=? WHERE username='chub@x.vn'", (hash_password("1234"),))
tok_a = ac.post("/auth/login", json={"username": "chua@x.vn", "password": "1234"}).json["token"]
tok_b = ac.post("/auth/login", json={"username": "chub@x.vn", "password": "1234"}).json["token"]

r = client.get("/zalo/my-account", headers={"Authorization": f"Bearer {tok_a}"})
check(r.status_code == 200 and r.json["acc"] == "default" and r.json["platform_admin"],
      "D1 chủ nền tảng → acc default", r.json)
r = client.get("/zalo/my-account", headers={"Authorization": f"Bearer {tok_b}"})
check(r.status_code == 200 and r.json["acc"] == acc_real and not r.json["platform_admin"],
      "D2 shop B → đúng acc đã cấp (ensure không cấp trùng)", r.json)

_bs_patch.stop()

# dọn acc test khỏi store THẬT
_clean_test_accs()
Path(str(_TMPDIR / "test_zmulti_store_tmp.json")).unlink(missing_ok=True)

print(f"\nKẾT QUẢ: {PASS} pass, {FAIL} fail")
sys.exit(1 if FAIL else 0)
