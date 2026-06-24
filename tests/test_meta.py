#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_meta.py — kênh Meta (Facebook Messenger + Instagram), multi-tenant:
  - MetaChannel: parse 'platform:page:recipient', gửi đúng token theo Page, ảnh URL công khai
  - meta_webhook: verify, nhận tin route theo Page ID, bật/tắt + owner-takeover, bỏ echo
  - luồng "Kết nối Facebook": /meta/connect lưu token Page + subscribe, /meta/pages, xoá

Chạy (TỪ GỐC):  python tests/test_meta.py
"""

import os, sys
from unittest.mock import MagicMock, patch

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
from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.meta_store import MetaStore
from app.channels.meta import MetaChannel
import app.web_api.meta_webhook as meta_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="meta-test")
cm._file = Path("test_meta_tmp.json"); cm._sessions.clear()

# Store cô lập, nạp sẵn 1 Page có token để test gửi đúng token
store = MetaStore(path=Path("test_meta_store_tmp.json"))
store._pages.clear()
store.upsert("PAGE1", name="Haru Page", access_token="TOK_PAGE1", ig_id="IG1", ig_username="haru.ig")

print("\n── A. MetaChannel (multi-tenant) ──")
ch = MetaChannel(store=store, page_token="", public_base_url="https://pub.example.com", conv_manager=cm)

# A1: parse 3 phần / 2 phần
check(ch._parse("fb:PAGE1:PSID9") == ("fb", "PAGE1", "PSID9"), "A1 parse_3part")
check(ch._parse("ig:PSID9") == ("ig", None, "PSID9"), "A1 parse_2part")
check(ch._parse("777") == ("fb", None, "777"), "A1 parse_1part")

# A2: token lấy theo Page từ store, fallback .env
check(ch._token_for("PAGE1") == "TOK_PAGE1", "A2 token_from_store")
check(ch._token_for("UNKNOWN") == "", "A2 token_fallback_empty")

# A3: send_text tới đúng recipient (đã bóc page)
ch._sent.clear(); ch.send_text("fb:PAGE1:PSID9", "xin chào")
check(ch._sent == [("PSID9", {"text": "xin chào"})], "A3 send_text", f"sent={ch._sent}")

# A4: text dài → chia 2
ch._sent.clear(); ch.send_text("fb:PAGE1:PSID9", "x" * 2500)
check(len(ch._sent) == 2, "A4 long_text_split", f"n={len(ch._sent)}")

# A5: send_price_photos → caption + ảnh URL công khai
ch._sent.clear(); ch.send_price_photos("fb:PAGE1:PSID9")
imgs = [m for r, m in ch._sent if "attachment" in m]
check(any("Bảng giá" in m.get("text", "") for r, m in ch._sent), "A5 price_caption")
check(imgs and all(m["attachment"]["payload"]["url"].startswith("https://pub.example.com/media/")
                   for m in imgs), "A5 image_public_url", f"imgs={imgs[:1]}")

# A6: gửi thật dùng token Page (patch requests) → đúng access_token của Page
with patch.object(__import__('app.channels.meta', fromlist=['requests']), 'requests') as mreq:
    calls = []
    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((params, json)); m = MagicMock(); m.status_code = 200; return m
    mreq.post.side_effect = fake_post
    ch2 = MetaChannel(store=store, page_token="", public_base_url="https://p", conv_manager=cm)
    ch2.send_text("fb:PAGE1:PSID9", "hi")
    check(calls and calls[-1][0]["access_token"] == "TOK_PAGE1", "A6 send_uses_page_token", f"calls={calls}")

print("\n── B. Webhook nhận tin (route theo Page) ──")

class _SyncThread:
    def __init__(self, target=None, **kw): self._t = target
    def start(self): self._t() if self._t else None

class FakeBrain:
    def __init__(self): self.handled = []
    def handle(self, uid, text): self.handled.append((uid, text))

with patch.object(meta_mod, 'threading') as mth, \
     patch.object(meta_mod, '_load_bot_state', return_value={"enabled": True}), \
     patch.object(meta_mod, 'time') as mt:
    mth.Thread = _SyncThread
    mt.sleep = lambda *a: None
    fb = FakeBrain()
    app = meta_mod.create_meta_webhook(fb, cm, store)
    client = app.test_client()

    # B1: verify
    r = client.get("/fb/webhook", query_string={
        "hub.mode": "subscribe", "hub.verify_token": Config.FB_VERIFY_TOKEN, "hub.challenge": "C1"})
    check(r.status_code == 200 and r.get_data(as_text=True) == "C1", "B1 verify_ok")
    r = client.get("/fb/webhook", query_string={
        "hub.mode": "subscribe", "hub.verify_token": "WRONG", "hub.challenge": "C1"})
    check(r.status_code == 403, "B2 verify_bad_token")

    # B3: Messenger → brain.handle('fb:<page>:<psid>')
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "page", "entry": [
        {"id": "PAGE1", "messaging": [{"sender": {"id": "PSID7"}, "message": {"text": "còn phòng ko"}}]}]})
    check(fb.handled == [("fb:PAGE1:PSID7", "còn phòng ko")], "B3 messenger_routed", f"h={fb.handled}")

    # B4: Instagram → map ig id (IG1) về PAGE1
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "instagram", "entry": [
        {"id": "IG1", "messaging": [{"sender": {"id": "IGU1"}, "message": {"text": "giá nhiêu"}}]}]})
    check(fb.handled == [("ig:PAGE1:IGU1", "giá nhiêu")], "B4 instagram_routed_to_page", f"h={fb.handled}")

    # B5: echo bỏ qua
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "page", "entry": [
        {"id": "PAGE1", "messaging": [{"sender": {"id": "PSID7"}, "message": {"text": "hi", "is_echo": True}}]}]})
    check(fb.handled == [], "B5 echo_skipped")

    # B6: owner_active im lặng
    cm.get("fb:PAGE1:PSID8").set_owner_active(True)
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "page", "entry": [
        {"id": "PAGE1", "messaging": [{"sender": {"id": "PSID8"}, "message": {"text": "alo"}}]}]})
    check(fb.handled == [], "B6 owner_active_silent")

# B7: bot TẮT toàn cục
with patch.object(meta_mod, 'threading') as mth, \
     patch.object(meta_mod, '_load_bot_state', return_value={"enabled": False}), \
     patch.object(meta_mod, 'time') as mt:
    mth.Thread = _SyncThread; mt.sleep = lambda *a: None
    fb2 = FakeBrain()
    client2 = meta_mod.create_meta_webhook(fb2, cm, store).test_client()
    client2.post("/fb/webhook", json={"object": "page", "entry": [
        {"id": "PAGE1", "messaging": [{"sender": {"id": "PSIDX"}, "message": {"text": "hello"}}]}]})
    check(fb2.handled == [], "B7 bot_disabled_skipped")

print("\n── C. Luồng 'Kết nối Facebook' (OAuth) ──")
with patch.object(meta_mod.meta_graph, 'exchange_long_lived_user_token', return_value="LONG_TOKEN") as mex, \
     patch.object(meta_mod.meta_graph, 'list_pages', return_value=[
        {"id": "PAGE_NEW", "name": "Mochi Page", "access_token": "TOK_NEW",
         "instagram_business_account": {"id": "IG_NEW", "username": "mochi.ig"}}]) as mlp, \
     patch.object(meta_mod.meta_graph, 'subscribe_page', return_value=True) as msub:
    store2 = MetaStore(path=Path("test_meta_store2_tmp.json")); store2._pages.clear()
    client = meta_mod.create_meta_webhook(FakeBrain(), cm, store2).test_client()

    # C1: config
    body = client.get("/meta/config").get_json()
    check("app_id" in body and "configured" in body, "C1 meta_config")

    # C2: connect thiếu token → 400
    r = client.post("/meta/connect", json={})
    check(r.status_code == 400, "C2 connect_missing_token")

    # C3: connect → lưu Page + subscribe, trả danh sách
    r = client.post("/meta/connect", json={"userToken": "SHORT_TOKEN"})
    body = r.get_json()
    check(body.get("ok") and body["pages"][0]["page_id"] == "PAGE_NEW", "C3 connect_returns_page", f"b={body}")
    check(store2.get_token("PAGE_NEW") == "TOK_NEW", "C3 token_stored")
    check(msub.called, "C3 page_subscribed")
    check(store2.page_for_ig("IG_NEW") == "PAGE_NEW", "C3 ig_mapped")

    # C4: /meta/pages liệt kê (KHÔNG lộ token)
    pages = client.get("/meta/pages").get_json()
    check(pages and pages[0]["page_id"] == "PAGE_NEW" and "access_token" not in pages[0],
          "C4 list_pages_no_token", f"p={pages}")

    # C5: xoá Page
    client.delete("/meta/pages/PAGE_NEW")
    check(store2.get_token("PAGE_NEW") is None, "C5 page_removed")

print(f"\n{'='*40}\n  KẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
for _f in ("test_meta_tmp.json", "test_meta_store_tmp.json", "test_meta_store2_tmp.json"):
    try: Path(_f).unlink()
    except: pass
sys.exit(1 if FAIL else 0)
