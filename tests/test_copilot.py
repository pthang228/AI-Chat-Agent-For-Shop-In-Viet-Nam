#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_copilot.py — Copilot QUẢN TRỊ (trợ lý giúp chủ shop):
  A. Tools đọc: overview/stats/prompt_status/channel_guide trả dict hợp lệ
  B. chat(): AI xin tool → backend chạy → AI trả lời (loop); trả text thẳng khi
     AI không JSON; navigate lọc route hợp lệ; action → pending KHÔNG tự chạy
  C. confirm_action: chạy action ghi thật (toggle_bot, add_canned) + reject tên lạ
  D. API bridge: /copilot/chat + /copilot/confirm (401 không token, 400 thiếu msg)

Chạy (TỪ GỐC):  python tests/test_copilot.py
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
os.environ['HOMESTAY_DB_PATH'] = 'test_db_copilot_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '0'
sys.path.insert(0, '.')

import json
from pathlib import Path
from app.core import copilot
from app.core.db import get_db
import app.web_api.bridge as bridge_mod

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
db.execute("DELETE FROM canned_replies")
bridge_mod.BOT_STATE_FILE = Path("test_bot_state_co_tmp.json")
bridge_mod.BOT_STATE_FILE.unlink(missing_ok=True)

# A–D test hạng CHUYÊN SÂU (có gói) → ép premium; hạng cơ bản test riêng ở E.
_orig_is_premium = copilot._is_premium
copilot._is_premium = lambda u: True

print("\n── A. Tools đọc ──")
ov = copilot._t_overview(None, {})
check("bots_per_channel" in ov and "billing" in ov and "customers_total" in ov, "A1 overview", f"{list(ov)}")
check(set(ov["bots_per_channel"]) == set(copilot.CHANNELS), "A2 all_channels")
st = copilot._t_stats(None, {})
check("total_conversations" in st and "total_messages" in st, "A3 stats")
pr = copilot._t_prompt(None, {})
check("source" in pr and "mode" in pr, "A4 prompt_status")
g = copilot._t_channel_guide(None, {"channel": "telegram"})
check("BotFather" in g["guide"], "A5 channel_guide")
check("không xác định" in copilot._t_channel_guide(None, {"channel": "xyz"})["guide"], "A6 guide_unknown")

print("\n── B. chat() agent loop ──")

# B1: AI xin tool overview → vòng 2 trả lời dựa kết quả
seq = iter([
    '{"tool": "overview", "args": {}}',
    '{"reply": "Shop anh/chị đang chạy tốt ạ!", "navigate": [{"label":"Xem thống kê","to":"/?s=stats"}]}',
])
with patch("app.core.copilot._call_ai", side_effect=lambda m: next(seq)):
    r = copilot.chat("chu@test", "tình hình shop thế nào?", [])
check(r["reply"].startswith("Shop") and r["debug"]["tools"] == ["overview"], "B1 tool_then_reply", f"{r}")
check(r.get("mode") == "premium", "B1 mode_premium", f"{r.get('mode')}")
check(r["navigate"] == [{"label": "Xem thống kê", "to": "/?s=stats"}], "B1 navigate_ok")
check(r["pending_action"] is None, "B1 no_action")

# B2: AI trả action (việc ghi) → pending KÈM CHỮ KÝ, KHÔNG tự chạy
with patch("app.core.copilot._call_ai",
           return_value='{"reply":"Anh/chị muốn tắt bot Telegram ạ?","action":{"name":"toggle_bot","args":{"channel":"telegram","enabled":false},"label":"Tắt bot Telegram"}}'):
    r = copilot.chat("chu@test", "tắt bot telegram", [])
check(r["pending_action"]["name"] == "toggle_bot"
      and r["pending_action"]["args"]["channel"] == "telegram", "B2 pending_action", f"{r['pending_action']}")
check(len(r["pending_action"].get("sig") or "") >= 16, "B2 has_signature", f"{r['pending_action']}")
# xác nhận: bot telegram VẪN chưa bị tắt (chưa confirm)
from app.web_api.bridge import _load_bot_state
check(_load_bot_state().get("channels", {}).get("telegram") is None, "B2 not_executed_yet")
_B2_SIG = r["pending_action"]["sig"]

# B2b: off-by-one — AI xin tool ở CẢ 3 vòng → vẫn ép trả lời, không kẹt fallback vô ích
_seq3 = iter(['{"tool":"overview"}', '{"tool":"stats"}', '{"tool":"prompt_status"}',
              '{"reply":"Dạ mọi thứ ổn ạ!"}'])
with patch("app.core.copilot._call_ai", side_effect=lambda m: next(_seq3)):
    r = copilot.chat("chu@test", "kiểm tra mọi thứ", [])
check(r["reply"] == "Dạ mọi thứ ổn ạ!" and len(r["debug"]["tools"]) == 3, "B2b max_steps_tools_then_answer", f"{r}")

# B3: navigate route LẠ bị lọc bỏ
with patch("app.core.copilot._call_ai",
           return_value='{"reply":"ok","navigate":[{"label":"Hack","to":"/evil"},{"label":"Gói","to":"/billing"}]}'):
    r = copilot.chat("chu@test", "x", [])
check(r["navigate"] == [{"label": "Gói", "to": "/billing"}], "B3 nav_whitelist", f"{r['navigate']}")

# B4: AI trả text thường (không JSON) → coi là câu trả lời
with patch("app.core.copilot._call_ai", return_value="Dạ anh/chị cần gì ạ?"):
    r = copilot.chat("chu@test", "x", [])
check(r["reply"] == "Dạ anh/chị cần gì ạ?" and r["pending_action"] is None, "B4 plain_text")

# B5: action tên LẠ trong reply → không thành pending (bỏ qua)
with patch("app.core.copilot._call_ai",
           return_value='{"reply":"ok","action":{"name":"delete_everything","args":{}}}'):
    r = copilot.chat("chu@test", "x", [])
check(r["pending_action"] is None, "B5 unknown_action_ignored")

print("\n── C. confirm_action (chạy việc ghi, cần CHỮ KÝ) ──")
# C0: chữ ký SAI → từ chối, KHÔNG chạy
r = copilot.confirm_action("chu@test", "toggle_bot", {"channel": "telegram", "enabled": False}, sig="bịa")
check(not r["ok"] and "không hợp lệ" in r["message"], "C0 bad_sig_rejected", f"{r}")
check(_load_bot_state().get("channels", {}).get("telegram") is None, "C0 not_run_on_bad_sig")
# C0b: args KHÁC đề xuất (dù cùng name) → chữ ký không khớp → từ chối
r = copilot.confirm_action("chu@test", "toggle_bot", {"channel": "all", "enabled": False}, sig=_B2_SIG)
check(not r["ok"], "C0b tampered_args_rejected")
# C1: đúng chữ ký của B2 → chạy
r = copilot.confirm_action("chu@test", "toggle_bot", {"channel": "telegram", "enabled": False}, sig=_B2_SIG)
check(r["ok"] and "TẮT" in r["message"], "C1 toggle_ok", f"{r}")
check(_load_bot_state()["channels"]["telegram"] is False, "C2 bot_actually_off")
_sig_canned = copilot._sign_action("chu@test", "add_canned_reply", {"title": "Chào", "content": "Xin chào shop ạ!"})
r = copilot.confirm_action("chu@test", "add_canned_reply", {"title": "Chào", "content": "Xin chào shop ạ!"}, sig=_sig_canned)
check(r["ok"], "C3 canned_ok")
check(db.query("SELECT COUNT(*) AS n FROM canned_replies")[0]["n"] == 1, "C4 canned_in_db")
r = copilot.confirm_action("chu@test", "add_canned_reply", {"content": ""},
                           sig=copilot._sign_action("chu@test", "add_canned_reply", {"content": ""}))
check(not r["ok"], "C5 empty_rejected")
r = copilot.confirm_action("chu@test", "delete_all", {}, sig="x")
check(not r["ok"] and "không hợp lệ" in r["message"], "C6 unknown_rejected")

print("\n── D. API bridge ──")
from app.core.conversation import ConversationManager
from app.core.brain import Brain
from app.core.channel import Channel
from app.web_api.auth_api import _issue_token, hash_password
from datetime import datetime

class FakeChannel(Channel):
    def send_text(self, u, t): pass
    def send_room_photos(self, u, n): pass
    def send_price_photos(self, u): pass
    def notify_owner(self, t): pass
    def call_owner(self): pass

db.execute("INSERT OR IGNORE INTO users(username,password_hash,homestay,email,provider,picture,created_at)"
           " VALUES(?,?,?,?,?,?,?)",
           ("co@test", hash_password("x"), "", "", "password", "", datetime.now().isoformat()))
tok = _issue_token(db, "co@test")
H = {"Authorization": f"Bearer {tok}"}
cm = ConversationManager(account="co-test")
api = bridge_mod.create_bridge(Brain(channel=FakeChannel(), conv_manager=cm), cm).test_client()

# D1: không token → 401 (auth guard)
os.environ['API_AUTH_GUARD'] = '1'   # bật guard để test chặn
import importlib, app.web_api.api_guard as ag
importlib.reload(ag)
# (guard đọc env lúc install; api đã tạo ở trên với guard tắt → kiểm route-level _user_or_401 thay vì guard)
r = api.post("/copilot/chat", json={"message": "hi"})   # không header
check(r.status_code == 401, "D1 no_token_401", f"{r.status_code}")

# D2: có token + AI mock → 200
with patch("app.core.copilot._call_ai", return_value='{"reply":"Chào anh/chị!"}'):
    r = api.post("/copilot/chat", headers=H, json={"message": "chào"})
check(r.status_code == 200 and r.get_json()["reply"] == "Chào anh/chị!", "D2 chat_ok", f"{r.get_json()}")

# D3: thiếu message → 400
check(api.post("/copilot/chat", headers=H, json={}).status_code == 400, "D3 missing_msg_400")

# D4: confirm qua API (kèm chữ ký hợp lệ)
_sig_meta = copilot._sign_action("co@test", "toggle_bot", {"channel": "meta", "enabled": True})
r = api.post("/copilot/confirm", headers=H,
             json={"name": "toggle_bot", "args": {"channel": "meta", "enabled": True}, "sig": _sig_meta})
check(r.status_code == 200 and r.get_json()["ok"], "D4 confirm_api", f"{r.get_json()}")
check(_load_bot_state()["channels"]["meta"] is True, "D5 meta_on")
# D6: confirm API KHÔNG sig → từ chối
r = api.post("/copilot/confirm", headers=H, json={"name": "toggle_bot", "args": {"channel": "meta", "enabled": False}})
check(r.status_code == 200 and not r.get_json()["ok"], "D6 no_sig_rejected", f"{r.get_json()}")

print("\n── E. Hạng CƠ BẢN (chưa đăng ký gói) ──")
from datetime import timedelta
copilot._is_premium = lambda u: False   # giả lập user chưa có gói

# E1: chỉ trả lời kiến thức cơ bản — navigate LỌC còn "/" + "/billing", mode=basic
with patch("app.core.copilot._call_ai",
           return_value='{"reply":"Dạ gói Pro ạ!","navigate":[{"label":"Gói","to":"/billing"},{"label":"Thống kê","to":"/?s=stats"}]}'):
    r = copilot.chat("free@test", "giá gói pro?", [])
check(r["mode"] == "basic" and r["reply"] == "Dạ gói Pro ạ!", "E1 basic_reply", f"{r}")
check(r["navigate"] == [{"label": "Gói", "to": "/billing"}], "E1 nav_basic_whitelist", f"{r['navigate']}")

# E2: AI xin tool → hạng cơ bản KHÔNG chạy tool (không có vòng lặp agent)
with patch("app.core.copilot._call_ai", return_value='{"tool":"overview","args":{}}') as mock_ai:
    r = copilot.chat("free@test", "tình hình shop?", [])
check(mock_ai.call_count == 1 and r["debug"]["tools"] == [], "E2 no_tools_in_basic", f"{r['debug']}")

# E3: AI trả action → hạng cơ bản KHÔNG tạo pending
with patch("app.core.copilot._call_ai",
           return_value='{"reply":"ok","action":{"name":"toggle_bot","args":{"channel":"tiktok","enabled":false},"label":"Tắt"}}'):
    r = copilot.chat("free@test", "tắt bot", [])
check(r["pending_action"] is None, "E3 no_action_in_basic")

# E4: confirm_action bị CHẶN khi chưa có gói (kể cả chữ ký đúng)
_sig = copilot._sign_action("free@test", "toggle_bot", {"channel": "tiktok", "enabled": False})
r = copilot.confirm_action("free@test", "toggle_bot", {"channel": "tiktok", "enabled": False}, sig=_sig)
check(not r["ok"] and "gói" in r["message"], "E4 confirm_blocked_basic", f"{r}")
check(_load_bot_state().get("channels", {}).get("tiktok") is None, "E4 not_executed")

# E5: _is_premium THẬT đọc billing: trial → False; lên gói còn hạn → True; hết hạn → False
copilot._is_premium = _orig_is_premium
from app.core import billing
billing.ensure_billing("prem@test")
check(copilot._is_premium("prem@test") is False, "E5 trial_is_basic")
db.execute("UPDATE billing SET tier='pro', plan='m1', expires_at=? WHERE username=?",
           ((datetime.now() + timedelta(days=30)).isoformat(), "prem@test"))
check(copilot._is_premium("prem@test") is True, "E6 paid_is_premium")
db.execute("UPDATE billing SET expires_at=? WHERE username=?",
           ((datetime.now() - timedelta(days=1)).isoformat(), "prem@test"))
check(copilot._is_premium("prem@test") is False, "E7 expired_back_to_basic")
check(copilot._is_premium("") is False, "E8 empty_user_basic")

# Dọn
bridge_mod.BOT_STATE_FILE.unlink(missing_ok=True)
print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
