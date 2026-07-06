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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tmp.sqlite'   # DB test riêng, không đụng DB thật
os.environ['API_AUTH_GUARD'] = '0'   # tắt auth-guard trong test (test_client không có token)
os.environ['WORKER_SYNC'] = '1'      # submit chạy đồng bộ → kiểm tra kết quả ngay
sys.path.insert(0, '.')

from pathlib import Path
from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.meta_store import MetaStore
from app.channels.meta import MetaChannel
import app.web_api.meta_webhook as meta_mod
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

cm = ConversationManager(account="meta-test")
cm._sessions.clear()

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

# A6: gửi thật dùng token Page (patch requests) → đúng access_token + endpoint Facebook
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch2 = MetaChannel(store=store, page_token="", public_base_url="https://p", conv_manager=cm)
    ch2.send_text("fb:PAGE1:PSID9", "hi")
    check(calls and calls[-1][1]["access_token"] == "TOK_PAGE1", "A6 send_uses_page_token", f"calls={calls}")
    check("graph.facebook.com" in calls[-1][0] and calls[-1][2].get("messaging_type") == "RESPONSE",
          "A6 fb_endpoint", f"url={calls[-1][0]}")

# A7: Instagram ĐA KHÁCH — có token Page → gửi qua graph.facebook.com + token Page (RESPONSE)
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch_ig = MetaChannel(store=store, page_token="", ig_token="IG_TOK",
                        public_base_url="https://p", conv_manager=cm)
    ch_ig.send_text("ig:PAGE1:IGU1", "chào")
    check(calls and "graph.facebook.com" in calls[-1][0], "A7 ig_multitenant_fb_endpoint", f"url={calls[-1][0] if calls else None}")
    check(calls and calls[-1][1]["access_token"] == "TOK_PAGE1", "A7 ig_uses_page_token", f"calls={calls}")
    check(calls and calls[-1][2].get("messaging_type") == "RESPONSE", "A7 ig_messaging_type", f"json={calls[-1][2] if calls else None}")

# A8: Instagram DỰ PHÒNG — không có token Page → graph.instagram.com + IG_ACCESS_TOKEN, KHÔNG messaging_type
with patch.object(httputil.requests, 'post') as mreq:
    calls = []
    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json)); m = MagicMock(); m.status_code = 200; return m
    mreq.side_effect = fake_post
    ch_ig2 = MetaChannel(store=store, page_token="", ig_token="IG_TOK",
                         public_base_url="https://p", conv_manager=cm)
    ch_ig2.send_text("ig:IGU1", "chào")   # 2 phần → page_id=None → fallback
    check(calls and "graph.instagram.com" in calls[-1][0], "A8 ig_fallback_endpoint", f"url={calls[-1][0] if calls else None}")
    check(calls and calls[-1][1]["access_token"] == "IG_TOK", "A8 ig_fallback_token", f"calls={calls}")
    check(calls and "messaging_type" not in calls[-1][2], "A8 ig_fallback_no_messaging_type", f"json={calls[-1][2] if calls else None}")

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

    # B4b: Instagram Login format — tin trong entry.changes[field=messages].value
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "instagram", "entry": [
        {"id": "IG1", "changes": [{"field": "messages", "value": {
            "sender": {"id": "IGU9"}, "recipient": {"id": "IG1"},
            "message": {"mid": "m1", "text": "giá phòng"}}}]}]})
    check(fb.handled == [("ig:PAGE1:IGU9", "giá phòng")], "B4b instagram_changes_routed", f"h={fb.handled}")

    # B4c: changes nhưng sender == IG account (echo bot tự gửi) → bỏ
    fb.handled.clear()
    client.post("/fb/webhook", json={"object": "instagram", "entry": [
        {"id": "IG1", "changes": [{"field": "messages", "value": {
            "sender": {"id": "IG1"}, "recipient": {"id": "IGU9"},
            "message": {"mid": "m2", "text": "bot tự nói"}}}]}]})
    check(fb.handled == [], "B4c instagram_changes_echo_skipped", f"h={fb.handled}")

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

    # C1: config (kèm cờ enable_ig cho frontend xin quyền IG)
    body = client.get("/meta/config").get_json()
    check("app_id" in body and "configured" in body and "enable_ig" in body, "C1 meta_config", f"b={body}")

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

print("\n── D. Cờ Instagram (FB_ENABLE_IG) ──")
from app.channels import meta_graph
# D1: subscribe_fields ở CẤP PAGE chỉ chứa field Messenger hợp lệ, KHÔNG đổi theo
# cờ IG (tin IG route ở cấp app, không qua subscribed_apps). Nhét field IG vào đây
# từng làm Graph trả 400 → hỏng cả subscribe `messages`.
with patch.object(meta_graph.Config, "FB_ENABLE_IG", False):
    f_off = meta_graph.subscribe_fields()
with patch.object(meta_graph.Config, "FB_ENABLE_IG", True):
    f_on = meta_graph.subscribe_fields()
check("messages" in f_off and "messaging_postbacks" in f_off, "D1 fields_has_messages", f_off)
check(f_on == f_off, "D1 fields_stable_regardless_of_ig", f"{f_on} vs {f_off}")
check("instagram" not in f_on and "reaction" not in f_on, "D1 fields_no_invalid_ig", f_on)

print("\n── E. Data Deletion + Deauthorize (App Review Meta) ──")
import base64 as _b64mod, json as _jsonmod, hmac as _hmac, hashlib as _hash

def _make_signed(payload: dict, secret: str) -> str:
    p = _b64mod.urlsafe_b64encode(_jsonmod.dumps(payload).encode()).decode().rstrip("=")
    sig = _hmac.new(secret.encode(), p.encode(), _hash.sha256).digest()
    s = _b64mod.urlsafe_b64encode(sig).decode().rstrip("=")
    return f"{s}.{p}"

# _parse_signed_request đúng/sai chữ ký
SECRET = "app_secret_test"
good = _make_signed({"user_id": "PSID_DEL"}, SECRET)
check(meta_mod._parse_signed_request(good, SECRET)["user_id"] == "PSID_DEL", "E1 parse_valid_sig")
check(meta_mod._parse_signed_request(good, "sai_secret") is None, "E2 reject_bad_sig")
check(meta_mod._parse_signed_request("rác", SECRET) is None, "E3 reject_malformed")

# Xoá dữ liệu theo PSID: seed 1 hội thoại fb + hồ sơ CRM rồi xoá
from app.core.db import get_db
_db = get_db()
ACC = cm._account   # 'meta-test' trong test (production dùng 'meta')
cm.get("fb:PAGE9:PSID_DEL").add_user_message("hi"); cm.save()
_db.execute("INSERT OR REPLACE INTO customers(account,user_id,name) VALUES(?,'fb:PAGE9:PSID_DEL','X')", (ACC,))
_db.execute("INSERT INTO customer_memory(account,user_id,content,source,created_at) "
            "VALUES(?,'fb:PAGE9:PSID_DEL','thích phòng 301','ai','2026-01-01')", (ACC,))
n = meta_mod._delete_meta_user_data(cm, "PSID_DEL")
check(n == 1, "E4 deleted_count", n)
check("fb:PAGE9:PSID_DEL" not in cm._sessions, "E5 session_gone_cache")
check(not _db.query("SELECT 1 FROM sessions WHERE account=? AND user_id='fb:PAGE9:PSID_DEL'", (ACC,)),
      "E6 session_gone_db")
check(not _db.query("SELECT 1 FROM customers WHERE account=? AND user_id='fb:PAGE9:PSID_DEL'", (ACC,)),
      "E7 customer_gone")
check(not _db.query("SELECT 1 FROM customer_memory WHERE account=? AND user_id='fb:PAGE9:PSID_DEL'", (ACC,)),
      "E8 memory_gone")

# Endpoint /meta/data-deletion + /meta/deauthorize + status page
with patch.object(meta_mod.Config, "FB_APP_SECRET", SECRET), \
     patch.object(meta_mod.Config, "PUBLIC_BASE_URL", "https://shop.example"):
    dclient = meta_mod.create_meta_webhook(FakeBrain(), cm, store).test_client()
    cm.get("fb:PAGE9:PSID_E9").add_user_message("hi"); cm.save()
    r = dclient.post("/meta/data-deletion",
                     data={"signed_request": _make_signed({"user_id": "PSID_E9"}, SECRET)})
    body = r.get_json()
    check(r.status_code == 200 and body.get("confirmation_code") and
          body["url"].startswith("https://shop.example/meta/deletion-status"),
          "E9 data_deletion_response", body)
    check("fb:PAGE9:PSID_E9" not in cm._sessions, "E10 endpoint_deleted_data")
    r = dclient.post("/meta/data-deletion", data={"signed_request": "sai"})
    check(r.status_code == 400, "E11 bad_signed_request_400")
    r = dclient.get("/meta/deletion-status?code=abc123")
    check(r.status_code == 200 and "abc123" in r.get_data(as_text=True), "E12 status_page")
    r = dclient.post("/meta/deauthorize",
                     data={"signed_request": _make_signed({"user_id": "PSID_X"}, SECRET)})
    check(r.status_code == 200 and r.get_json().get("ok"), "E13 deauthorize_ok")

print(f"\n{'='*40}\n  KẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
for _f in ("test_meta_tmp.json", "test_meta_store_tmp.json", "test_meta_store2_tmp.json"):
    try: Path(_f).unlink()
    except: pass
sys.exit(1 if FAIL else 0)
