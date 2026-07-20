#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_tenant_channels.py — IDOR cách ly tenant trên API QUẢN LÝ KÊNH:
guard sở hữu dùng chung (api_guard.own_account_or_404 / filter_owned) phải chặn
shop C đụng account kênh của shop B trên CẢ 5 kênh từng bị hổng:
  A. TikTok   — list lọc theo chủ, DELETE/toggle/set-owner chéo shop → 404
  B. Shopee   — như trên
  C. Zalo OA  — như trên
  D. Webchat  — như trên
  E. Meta     — /meta/pages lọc, DELETE guard, /meta/stats không gộp chéo tenant,
                /meta/fetch-names chỉ quét khách shop mình
(Telegram đã có guard riêng _own_bot_or_404 — cover ở test_team/test_telegram.)

Chạy TỪ GỐC: python tests/test_tenant_channels.py
"""

import os, sys
from unittest.mock import MagicMock
from pathlib import Path

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tenant_channels_tmp.sqlite')
os.environ['API_AUTH_GUARD'] = '1'    # BẬT — IDOR test cần auth thật
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_tenant_channels_tmp.sqlite{suf}")).unlink(missing_ok=True)

from flask import Flask
from app.core.conversation import ConversationManager
from app.core.channel import Channel
from app.web_api.auth_api import register_auth_routes

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


class FakeChannel(Channel):
    def __init__(self): self.sent = []
    def send_text(self, uid, t): self.sent.append((uid, t))
    def send_room_photos(self, uid, n): pass
    def send_price_photos(self, uid): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass

class FakeBrain:
    def __init__(self): self.channel = FakeChannel()
    def handle(self, uid, text): pass


# ── 3 tài khoản: root (chủ nền tảng = admin), shop B, shop C ─────────
auth_app = Flask(__name__)
register_auth_routes(auth_app)
ac = auth_app.test_client()

TOK = {}
for u, hs in (("root@x.vn", "Nền tảng"), ("shopb@x.vn", "Shop B"), ("shopc@x.vn", "Shop C")):
    r = ac.post("/auth/register", json={"username": u, "password": "1234", "homestay": hs})
    TOK[u] = r.json["token"]
H_ROOT = {"Authorization": f"Bearer {TOK['root@x.vn']}"}
H_B = {"Authorization": f"Bearer {TOK['shopb@x.vn']}"}
H_C = {"Authorization": f"Bearer {TOK['shopc@x.vn']}"}


def run_channel_case(tag, api, store, list_path, item_path, id_key, acc_id, toggle=True, set_owner_path=None, uid_prefix=None):
    """Bộ check IDOR chung cho 1 kênh: acc_id thuộc shop B."""
    # list: C không thấy, B thấy, admin thấy
    r = api.get(list_path, headers=H_C)
    ids = [x.get(id_key) for x in (r.json or [])]
    check(acc_id not in ids, f"{tag} list_C_empty", f"{ids}")
    r = api.get(list_path, headers=H_B)
    ids = [x.get(id_key) for x in (r.json or [])]
    check(acc_id in ids, f"{tag} list_B_sees_own", f"{ids}")
    r = api.get(list_path, headers=H_ROOT)
    ids = [x.get(id_key) for x in (r.json or [])]
    check(acc_id in ids, f"{tag} list_admin_sees_all", f"{ids}")

    # toggle chéo shop → 404, không đổi gì
    if toggle:
        r = api.post(f"{item_path}/toggle", json={"enabled": False}, headers=H_C)
        check(r.status_code == 404, f"{tag} toggle_C_404", f"{r.status_code}")

    # set-owner chéo shop → 404
    if set_owner_path and uid_prefix:
        r = api.post(set_owner_path, json={"user_id": f"{uid_prefix}:{acc_id}:u1"}, headers=H_C)
        check(r.status_code == 404, f"{tag} set_owner_C_404", f"{r.status_code}")

    # DELETE chéo shop → 404 + account còn nguyên
    r = api.delete(item_path, headers=H_C)
    check(r.status_code == 404, f"{tag} delete_C_404", f"{r.status_code}")
    check(store.get_owner_username(acc_id) == "shopb@x.vn", f"{tag} delete_C_no_effect")

    # DELETE chính chủ → ok, account biến mất
    r = api.delete(item_path, headers=H_B)
    check(r.status_code == 200 and (r.json or {}).get("ok"), f"{tag} delete_B_ok", f"{r.status_code}")
    check(not store.get_owner_username(acc_id), f"{tag} delete_B_removed")


print("\n── A. TikTok ──")
from app.core.tiktok_store import TikTokStore
import app.web_api.tiktok_api as tt
tt_store = TikTokStore(path=str(_TMPDIR / "tt_store_tmp.json"))
tt_store.upsert("BIZB", access_token="t1", name="TikTok B", owner_username="shopb@x.vn")
fb = FakeBrain()
cm_tt = ConversationManager(account="tt_test")
api = tt.create_tiktok_api(fb, cm_tt, fb.channel, tt_store).test_client()
run_channel_case("A", api, tt_store, "/tiktok/accounts", "/tiktok/accounts/BIZB",
                 "business_id", "BIZB", set_owner_path="/tiktok/set-owner", uid_prefix="tt")

print("\n── B. Shopee ──")
from app.core.shopee_store import ShopeeStore
import app.web_api.shopee_api as sp
sp_store = ShopeeStore(path=str(_TMPDIR / "sp_store_tmp.json"))
sp_store.upsert("SHOPB", access_token="t1", name="Shopee B", owner_username="shopb@x.vn")
fb = FakeBrain()
cm_sp = ConversationManager(account="sp_test")
api = sp.create_shopee_api(fb, cm_sp, fb.channel, sp_store).test_client()
run_channel_case("B", api, sp_store, "/shopee/shops", "/shopee/shops/SHOPB",
                 "shop_id", "SHOPB", set_owner_path="/shopee/set-owner", uid_prefix="sp")

print("\n── C. Zalo OA ──")
from app.core.zalo_oa_store import ZaloOAStore
import app.web_api.zalo_oa_api as oa
oa_store = ZaloOAStore(path=str(_TMPDIR / "oa_store_tmp.json"))
oa_store.upsert("OAB", access_token="t1", name="OA B", owner_username="shopb@x.vn")
fb = FakeBrain()
cm_oa = ConversationManager(account="oa_test")
api = oa.create_zalo_oa_api(fb, cm_oa, fb.channel, oa_store).test_client()
run_channel_case("C", api, oa_store, "/zalooa/accounts", "/zalooa/accounts/OAB",
                 "oa_id", "OAB", set_owner_path="/zalooa/set-owner", uid_prefix="oa")

print("\n── D. Webchat ──")
from app.core.webchat_store import WebChatStore
import app.web_api.webchat_api as wc
wc_store = WebChatStore(path=str(_TMPDIR / "wc_store_tmp.json"))
SITE_B = wc_store.create("Site B", owner_username="shopb@x.vn")
fb = FakeBrain()
cm_wc = ConversationManager(account="wc_test")
api = wc.create_webchat_api(fb, cm_wc, fb.channel, wc_store).test_client()
run_channel_case("D", api, wc_store, "/webchat/sites", f"/webchat/sites/{SITE_B}",
                 "site_id", SITE_B, set_owner_path="/webchat/set-owner", uid_prefix="web")

print("\n── E. Meta (pages / stats / fetch-names) ──")
from app.core.meta_store import MetaStore
import app.web_api.meta_webhook as mw
meta_store = MetaStore(path=str(_TMPDIR / "meta_store_tmp.json"))
meta_store.upsert("PGB", name="Page B", access_token="t1", owner_username="shopb@x.vn")
fb = FakeBrain()
cm_meta = ConversationManager(account="meta_test")
conv = cm_meta.get("fb:PGB:111")
conv.tenant = "shopb@x.vn"
conv.messages.append({"role": "user", "content": "hi"})
api = mw.create_meta_webhook(fb, cm_meta, store=meta_store).test_client()

# pages: C không thấy, B thấy, admin thấy
r = api.get("/meta/pages", headers=H_C)
check([] == [x for x in (r.json or []) if x.get("page_id") == "PGB"], "E pages_C_empty", f"{r.json}")
r = api.get("/meta/pages", headers=H_B)
check(any(x.get("page_id") == "PGB" for x in (r.json or [])), "E pages_B_sees_own")
r = api.get("/meta/pages", headers=H_ROOT)
check(any(x.get("page_id") == "PGB" for x in (r.json or [])), "E pages_admin_sees_all")

# stats: C không được gộp hội thoại shop B; B thấy hội thoại của mình
r = api.get("/meta/stats", headers=H_C)
check((r.json or {}).get("total_conv") == 0, "E stats_C_zero", f"{r.json}")
r = api.get("/meta/stats", headers=H_B)
check((r.json or {}).get("total_conv") == 1, "E stats_B_own", f"{r.json}")

# fetch-names: C không quét được khách shop B (checked=0); B quét khách mình
r = api.post("/meta/fetch-names", headers=H_C)
check((r.json or {}).get("checked") == 0, "E fetchnames_C_zero", f"{r.json}")
r = api.post("/meta/fetch-names", headers=H_B)
check((r.json or {}).get("checked") == 1, "E fetchnames_B_own", f"{r.json}")

# DELETE page: C → 404 còn nguyên; B → ok
r = api.delete("/meta/pages/PGB", headers=H_C)
check(r.status_code == 404, "E delete_C_404", f"{r.status_code}")
check(meta_store.get_owner_username("PGB") == "shopb@x.vn", "E delete_C_no_effect")
r = api.delete("/meta/pages/PGB", headers=H_B)
check(r.status_code == 200 and (r.json or {}).get("ok"), "E delete_B_ok", f"{r.status_code}")
check(not meta_store.get_owner_username("PGB"), "E delete_B_removed")

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
