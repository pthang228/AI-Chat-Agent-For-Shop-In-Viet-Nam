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
# Rác test (DB sqlite/json tạm) gom vào tests/.tmp/ — không xả ra gốc repo
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_tmp.sqlite')   # DB test riêng, không đụng DB thật
os.environ['API_AUTH_GUARD'] = '0'   # tắt auth-guard trong test (test_client không có token)
os.environ['WORKER_SYNC'] = '1'      # submit chạy đồng bộ → kiểm tra kết quả ngay
sys.path.insert(0, '.')

from pathlib import Path
from app.core.channel import Channel
from app.core.conversation import ConversationManager
from app.core.brain import Brain
import app.web_api.bridge as bridge_mod
import app.channels.zalo_node as znc_mod
import app.core.http_util as httputil   # send đi qua đây → patch requests.post ở đây

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# Cô lập sessions (DB test qua HOMESTAY_DB_PATH ở trên)
cm = ConversationManager(account=1)
cm._sessions.clear()

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
    bridge_mod.BOT_STATE_FILE = Path(str(_TMPDIR / "test_bot_state_tmp.json"))  # cô lập, không đụng data thật
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
    check(any("trợ lý AI" in t for t in fc.texts), "A3 greeting_sent", f"texts={fc.texts}")
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

    # A9: GATE-LAST — tin bị DROP sớm (owner_active / non-text) KHÔNG được gọi
    # channel_gate: gate GHI 1 lượt AI khi cho qua, gọi trước các check sớm là
    # trừ quota oan của chủ shop dù bot không hề trả lời
    with patch("app.core.billing.channel_gate", return_value=True) as mgate:
        r = client.post("/incoming", json={"userId":"cust2","text":"alo"})   # cust2 owner_active từ A4
        check(r.get_json().get("skipped")=="owner_active" and not mgate.called,
              "A9 gate_after_owner_active", f"called={mgate.called}")
        r = client.post("/incoming", json={"userId":"cust1","text":""})      # cust1 đã có lịch sử (A3)
        check(r.get_json().get("skipped")=="non-text non-first" and not mgate.called,
              "A9 gate_after_non_text", f"called={mgate.called}")

    # A10: gate chặn (hết gói/quota) → không vào brain, skipped=billing_expired
    with patch("app.core.billing.channel_gate", return_value=False) as mgate:
        fc.texts.clear()
        r = client.post("/incoming", json={"userId":"custgate","text":"hi"})
        check(r.get_json().get("skipped")=="billing_expired" and mgate.called and not fc.texts,
              "A10 gate_blocks_before_brain", f"{r.get_json()}")

    # ── D. BRIDGE_SECRET: shared-secret bảo vệ /incoming ──
    print("\n── D. BRIDGE_SECRET /incoming ──")
    with patch.object(bridge_mod.Config, 'BRIDGE_SECRET', 'sec-test-123'):
        # D1: secret đặt + KHÔNG header → 401 (chặn giả tin cùng mạng)
        fc.texts.clear()
        r = client.post("/incoming", json={"userId": "sec1", "text": "hi"})
        check(r.status_code == 401 and not fc.texts, "D1 secret_no_header_401", f"{r.status_code}")
        # D2: header SAI → 401
        r = client.post("/incoming", json={"userId": "sec1", "text": "hi"},
                        headers={"X-Bridge-Secret": "sai-secret"})
        check(r.status_code == 401, "D2 secret_wrong_header_401", f"{r.status_code}")
        # D3: header ĐÚNG → xử lý bình thường (khách mới được chào)
        fc.texts.clear()
        r = client.post("/incoming", json={"userId": "sec1", "text": "xin chào"},
                        headers={"X-Bridge-Secret": "sec-test-123"})
        check(r.status_code == 200 and r.get_json().get("ok") is True,
              "D3 secret_ok_processed", f"{r.status_code}")
        check(any("trợ lý AI" in t for t in fc.texts), "D3 greeting_after_secret", f"texts={fc.texts}")
        # D4: kể cả isSelf+ownerTyped cũng bị chặn khi thiếu secret (chính là
        # vector tắt bot 48h mà secret sinh ra để chặn)
        r = client.post("/incoming", json={"userId": "sec2", "text": "x",
                                           "isSelf": True, "ownerTyped": True})
        check(r.status_code == 401 and not cm.get("sec2").is_owner_active(),
              "D4 ownerTyped_forgery_blocked", f"{r.status_code}")
    # D5: KHÔNG đặt secret → hành vi cũ, không cần header (dev/test)
    fc.texts.clear()
    r = client.post("/incoming", json={"userId": "sec3", "text": "xin chào"})
    check(r.status_code == 200 and r.get_json().get("ok") is True,
          "D5 no_secret_old_behavior", f"{r.status_code}")

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
    check(any("trợ lý AI" in t for t in fc.texts), "C5 reply_resumed", f"texts={fc.texts}")

    # ── E. /zalo-node proxy: UI gọi Node QUA bridge (whitelist + ép acc) ──
    print("\n── E. /zalo-node proxy ──")
    import requests as _real_rq

    # E1: endpoint ngoài whitelist (/send — chỉ nội bộ) → 404, không forward
    r = client.post("/zalo-node/send", json={"userId": "x", "text": "hack"})
    check(r.status_code == 404, "E1 non_whitelist_404", f"{r.status_code}")

    # E2: chưa đăng nhập (không workspace) → 401
    r = client.get("/zalo-node/status?acc=default")
    check(r.status_code == 401, "E2 no_login_401", f"{r.status_code}")

    # E3: shop thường → acc bị ÉP về acc CỦA SHOP (bỏ qua ?acc= client tự khai —
    # chặn shop A mượn proxy đụng acc Zalo shop B)
    with patch.object(bridge_mod, "_ws", return_value="shopA@x"), \
         patch("app.core.tenant.is_platform_admin", return_value=False), \
         patch.object(_real_rq, "get") as mget:
        mresp = MagicMock(); mresp.content = b'{"ok":true}'
        mresp.status_code = 200; mresp.headers = {"Content-Type": "application/json"}
        mget.return_value = mresp
        r = client.get("/zalo-node/status?acc=default")   # cố xin acc default
        sent = (mget.call_args.kwargs.get("params") or {}) if mget.call_args else {}
        check(r.status_code == 200 and sent.get("acc") not in ("", None, "default"),
              "E3 acc_forced_per_shop", f"params={sent}")

    # E4: admin nền tảng → được giữ acc chỉ định (quản trị mọi shop)
    with patch.object(bridge_mod, "_ws", return_value="admin@x"), \
         patch("app.core.tenant.is_platform_admin", return_value=True), \
         patch.object(_real_rq, "get") as mget:
        mresp = MagicMock(); mresp.content = b'{}'
        mresp.status_code = 200; mresp.headers = {}
        mget.return_value = mresp
        client.get("/zalo-node/status?acc=acc-shopB")
        sent = (mget.call_args.kwargs.get("params") or {}) if mget.call_args else {}
        check(sent.get("acc") == "acc-shopB", "E4 admin_keeps_acc", f"params={sent}")

print("\n── B. ZaloNodeChannel gọi Node đúng ──")
with patch.object(httputil.requests, 'post') as mreq:
    calls=[]
    def fake_post(url, json=None, timeout=None):
        calls.append((url, json)); m=MagicMock(); m.status_code=200; return m
    mreq.side_effect = fake_post
    ch = znc_mod.ZaloNodeChannel(node_url="http://127.0.0.1:4000", conv_manager=cm)

    # B1: send_text → POST /send (MULTI-ACC 2026-07-07: payload kèm acc,
    # uid trần → acc "default")
    ch.send_text("cust1", "hello")
    check(calls and calls[-1][0].endswith("/send")
          and calls[-1][1]=={"acc":"default","userId":"cust1","text":"hello"},
          "B1 send_text_posts", f"calls={calls}")

    # B2: text > 2000 ký tự → chia 2 lần
    calls.clear(); ch.send_text("cust1", "x"*2500)
    check(len(calls)==2, "B2 long_text_split", f"n={len(calls)}")

    # B3: notify_owner gọi /notify-owner (Node tự quyết nhóm/chủ theo cấu hình UI)
    calls.clear(); ch.notify_owner("báo chủ")
    check(len(calls)==1 and calls[-1][0].endswith("/notify-owner")
          and calls[-1][1]=={"acc":"default","text":"báo chủ"},
          "B3 notify_owner_endpoint", f"calls={calls}")

print(f"\n{'='*40}\n  KẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
for _f in (str(_TMPDIR / "test_bridge_tmp.json"), str(_TMPDIR / "test_bot_state_tmp.json")):
    try: Path(_f).unlink()
    except: pass
sys.exit(1 if FAIL else 0)
