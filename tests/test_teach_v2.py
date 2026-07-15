#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_teach_v2.py — Dạy AI v2:
  A. industry: nhận diện ngành (keyword + AI fallback), checklist
  B. bot_misses: brain ghi câu bot bí (unknown_question)
  C. learn_direct: bổ sung 1 chạm (AI bóc + fallback thô)
  D. API: /prompt/interview, /prompt/report(+answer), /prompt/health

Chạy (TỪ GỐC):  python tests/test_teach_v2.py
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
_DB = 'test_db_teach_tmp.sqlite'
for _f in (_DB, _DB + '-shm', _DB + '-wal'):
    try: os.remove(_f)
    except OSError: pass
os.environ['HOMESTAY_DB_PATH'] = _DB
sys.path.insert(0, '.')

from flask import Flask
from app.core import industry, knowledge, knowledge_learn, claude_ai
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

# ═══ A. industry ═══════════════════════════════════════════════════
print("\n── A. industry ──")

check(industry.detect_by_keywords(
    "Homestay Đà Lạt view đồi, check-in 14h, đặt phòng qua đêm giá 500k, có villa") == "homestay",
    "A1 detect_homestay")
check(industry.detect_by_keywords(
    "Spa chăm sóc da mặt, gội đầu dưỡng sinh, massage body, triệt lông, làm nail") == "spa",
    "A2 detect_spa")
check(industry.detect_by_keywords("xin chào bạn") is None, "A3 mơ_hồ_trả_None")

with patch.object(claude_ai, "_call_ai", return_value="fnb"):
    check(industry.detect("shop nhỏ bán đồ") == "fnb", "A4 AI_fallback")
with patch.object(claude_ai, "_call_ai", side_effect=RuntimeError("die")):
    check(industry.detect("shop nhỏ") == industry.DEFAULT_KEY, "A5 AI_chết_về_default")

blk = industry.checklist_block("spa")
check("SPA" in blk.upper() and "khách nam" in blk, "A6 checklist_block")
check(len(industry.test_questions("homestay")) >= 10, "A7 test_questions_đủ")
for k, ind in industry.INDUSTRIES.items():
    assert ind["checklist"] and ind["test_questions"] and ind["hints"], k
check(True, "A8 mọi_ngành_đủ_3_trường")

# ═══ B. bot_misses từ brain ════════════════════════════════════════
print("\n── B. bot_misses ──")

from app.core.brain import Brain
from app.core.conversation import ConversationState

class _Mgr:
    _account = "meta"
    def __init__(self): self.conv = ConversationState(user_id="fb:P:U9"); self.conv.tenant = ""
    def get(self, uid): return self.conv
    def save(self): pass

mgr = _Mgr()
brain = Brain(channel=MagicMock(), conv_manager=mgr)
with patch("app.core.brain.analyze_message",
           return_value={"intent": "unknown_question", "reply": "", "checkin": None,
                         "checkout": None, "booking_confirmed": False}), \
     patch("app.core.brain.notify") as _n:
    _n.alert = MagicMock(); _n.get_config = MagicMock(return_value=None)
    _n.contact_for = MagicMock(return_value="")
    brain.handle("fb:P:U9", "bên mình có cho thuê xe máy không")

rows = get_db().query("SELECT * FROM bot_misses")
check(len(rows) == 1 and "thuê xe máy" in rows[0]["question"], "B1 ghi_câu_bí",
      f"rows={len(rows)}")
check(rows[0]["resolved"] == 0, "B2 chưa_resolved")

# ═══ C. learn_direct ═══════════════════════════════════════════════
print("\n── C. learn_direct ──")

with patch.object(claude_ai, "_call_ai", return_value=(
        '{"kind":"fact","title":"Thuê xe máy","content":"Shop có cho thuê xe máy 120k/ngày",'
        '"keywords":["thue xe may","xe may"]}')):
    ck = knowledge_learn.learn_direct("có cho thuê xe máy không",
                                      "có nha, 120k/ngày", shop="default")
check(ck["title"] == "Thuê xe máy", "C1 AI_bóc_chuẩn")
check(knowledge.count("default", kind="fact") == 1, "C2 vào_kho_fact")

with patch.object(claude_ai, "_call_ai", side_effect=RuntimeError("die")):
    ck2 = knowledge_learn.learn_direct("có wifi không", "wifi free toàn khu", shop="default")
check(ck2["content"] == "wifi free toàn khu" and knowledge.count("default", kind="fact") == 2,
      "C3 AI_chết_fallback_thô")
try:
    knowledge_learn.learn_direct("q", "x", shop="default")
    check(False, "C4 trả_lời_ngắn_raise")
except ValueError:
    check(True, "C4 trả_lời_ngắn_raise")

# ═══ D. API endpoints ══════════════════════════════════════════════
print("\n── D. API /prompt/* v2 ──")

import app.web_api.auth_api as auth_mod
import app.web_api.prompt_api as prompt_mod

db = get_db()
for t in ("users", "auth_tokens"):
    db.execute(f"DELETE FROM {t}")
flask_app = Flask(__name__)
auth_mod.register_auth_routes(flask_app)
prompt_mod.register_prompt_routes(flask_app)
api = flask_app.test_client()
tok = api.post("/auth/register", json={"username": "v2@x.vn", "password": "test1234"}).get_json()["token"]
H = {"Authorization": f"Bearer {tok}"}

# D1-D3: interview — hỏi tiếp / kết thúc / AI trả text trần
with patch.object(claude_ai, "_call_ai",
                  return_value='{"done": false, "question": "Shop mình bán gì ạ?"}'):
    r = api.post("/prompt/interview", json={"history": []}, headers=H).get_json()
check(r["ok"] and not r["done"] and "bán gì" in r["question"], "D1 interview_hỏi")
with patch.object(claude_ai, "_call_ai",
                  return_value='{"done": true, "summary": "Shop spa, gội đầu 100k..."}'):
    r = api.post("/prompt/interview",
                 json={"history": [{"role": "assistant", "content": "?"},
                                   {"role": "user", "content": "đủ rồi"}]}, headers=H).get_json()
check(r["ok"] and r["done"] and "spa" in r["summary"], "D2 interview_kết_thúc")
with patch.object(claude_ai, "_call_ai", return_value="Giá dịch vụ chính của mình là gì?"):
    r = api.post("/prompt/interview", json={"history": []}, headers=H).get_json()
check(r["ok"] and not r["done"] and "Giá" in r["question"], "D3 interview_text_trần_không_chết")

# D4-D5: report — user v2@x.vn là default_owner → thấy misses shop 'default'
r = api.get("/prompt/report", headers=H).get_json()
check(r["ok"] and r["total"] == 1 and r["misses"][0]["count"] == 1, "D4 report_có_câu_bí",
      f"r={r}")
mid = r["misses"][0]["ids"][0]
with patch.object(claude_ai, "_call_ai", return_value=(
        '{"kind":"fact","title":"Cho thuê xe máy","content":"Có, 120k/ngày","keywords":["xe may"]}')):
    r2 = api.post("/prompt/report/answer", headers=H,
                  json={"question": "có cho thuê xe máy không", "answer": "có nha 120k/ngày",
                        "ids": [mid]}).get_json()
check(r2["ok"] and r2["chunk"]["title"], "D5 report_answer_lưu")
r3 = api.get("/prompt/report", headers=H).get_json()
check(r3["total"] == 0, "D6 miss_đã_resolved", f"r={r3}")

# D7: health — mock não + giám khảo
db.execute("UPDATE users SET industry='spa' WHERE username='v2@x.vn'")
with patch.object(claude_ai, "analyze_with_debug",
                  return_value={"reply": "Dạ gội đầu 100k ạ"}), \
     patch.object(claude_ai, "_call_ai",
                  return_value='[{"i":1,"ok":true},{"i":2,"ok":false,"note":"thiếu giá"}]'):
    r = api.post("/prompt/health", headers=H, json={}).get_json()
check(r["ok"] and r["industry"] == "spa" and r["total"] == 10, "D7 health_chạy",
      f"r={ {k: r.get(k) for k in ('industry', 'total', 'passed')} }")
check(r["passed"] == 1 and any(not it["ok"] and it["note"] for it in r["items"]),
      "D8 health_verdict_map")
check(api.post("/prompt/health").status_code == 401, "D9 health_cần_auth")

print("\n" + "=" * 40)
print(f"  KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
