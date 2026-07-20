#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_circuit_breaker.py — mạch ngắt DeepSeek trong claude_ai._call_ai:
  A. DeepSeek lỗi liên tiếp đủ ngưỡng → MỞ mạch: lượt sau đi thẳng Groq
     (không đụng DeepSeek, không bắt khách chờ timeout)
  B. Hết cooldown → half-open: cho đúng 1 lượt thử DeepSeek; fail → đóng cửa tiếp
  C. Thử thành công → ĐÓNG mạch, DeepSeek lại là mặc định
  D. analyze_message dùng timeout ngắn riêng (AI_ANALYZE_TIMEOUT)

Chạy TỪ GỐC: python tests/test_circuit_breaker.py
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
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_cb_tmp.sqlite')
sys.path.insert(0, '.')

from app.core.config import Config
from app.core import claude_ai as ca
from app.core import ai_models as am

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

Config.DEEPSEEK_API_KEY = "sk-ds-test"
Config.GROQ_API_KEY = "sk-groq-test"

calls = []      # model_key của từng lượt gọi ai_models.chat

def make_chat(deepseek_fails):
    def fake_chat(messages, owner=None, model_key=None, timeout=None, **kw):
        calls.append((model_key, timeout))
        if model_key == am.DEFAULT_MODEL and deepseek_fails[0]:
            raise RuntimeError("connect timeout (giả lập DeepSeek sập)")
        return "ok"
    return fake_chat

def reset_cb():
    with ca._cb_lock:
        ca._cb["fails"] = 0
        ca._cb["opened_at"] = 0.0

MSGS = [{"role": "user", "content": "hi"}]

print("\n── A. Mở mạch sau N lỗi liên tiếp ──")
reset_cb()
ds_down = [True]
with patch.object(am, "chat", make_chat(ds_down)):
    for _ in range(ca._CB_FAILS):          # đủ ngưỡng lỗi (mỗi lượt vẫn fallback Groq ok)
        ca._call_ai(MSGS)
    calls.clear()
    out = ca._call_ai(MSGS)                # mạch đã MỞ
check(out == "ok", "A1 vẫn trả lời được qua Groq")
check(am.DEFAULT_MODEL not in [k for k, _ in calls], "A2 mạch mở → KHÔNG đụng DeepSeek", calls)
check(calls and calls[0][0] == am.GROQ_FALLBACK_KEYS[0], "A3 đi thẳng Groq đầu danh sách", calls)

print("\n── B. Half-open sau cooldown ──")
with ca._cb_lock:
    ca._cb["opened_at"] -= (ca._CB_COOLDOWN + 1)   # giả lập đã hết cooldown
ds_down[0] = True
with patch.object(am, "chat", make_chat(ds_down)):
    calls.clear()
    ca._call_ai(MSGS)                      # half-open: thử DeepSeek 1 lượt → fail
    tried_ds = am.DEFAULT_MODEL in [k for k, _ in calls]
    calls.clear()
    ca._call_ai(MSGS)                      # ngay sau đó: mạch vẫn mở
    tried_ds_2 = am.DEFAULT_MODEL in [k for k, _ in calls]
check(tried_ds, "B1 hết cooldown → được thử DeepSeek 1 lượt")
check(not tried_ds_2, "B2 thử fail → đóng cửa tiếp, không thử liền lượt sau")

print("\n── C. Thử thành công → đóng mạch ──")
with ca._cb_lock:
    ca._cb["opened_at"] -= (ca._CB_COOLDOWN + 1)
ds_down[0] = False                          # DeepSeek sống lại
with patch.object(am, "chat", make_chat(ds_down)):
    calls.clear()
    out = ca._call_ai(MSGS)
    ok_first = calls[0][0] == am.DEFAULT_MODEL and out == "ok"
    calls.clear()
    ca._call_ai(MSGS)                       # mạch đã đóng → DeepSeek là mặc định
    ok_second = calls[0][0] == am.DEFAULT_MODEL
check(ok_first, "C1 half-open thành công")
check(ok_second, "C2 mạch ĐÓNG: DeepSeek lại là mặc định", calls)
check(ca._cb["fails"] == 0, "C3 bộ đếm lỗi reset")

print("\n── D. analyze_message dùng timeout ngắn ──")
reset_cb()
ds_down[0] = False
with patch.object(am, "chat", make_chat(ds_down)):
    calls.clear()
    ca.analyze_message("tối nay còn phòng không", [], user_id="u1")
check(calls and calls[0][1] == Config.AI_ANALYZE_TIMEOUT,
      "D1 lượt phân tích truyền AI_ANALYZE_TIMEOUT", calls)
check(Config.AI_ANALYZE_TIMEOUT < Config.AI_TIMEOUT, "D2 timeout phân tích < timeout thường")

reset_cb()
print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
