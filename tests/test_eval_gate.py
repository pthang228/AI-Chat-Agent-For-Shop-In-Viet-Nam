#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_eval_gate.py — CỔNG eval LLM (scripts/eval_llm_real.py) chặn ĐÚNG:
  A. Mọi trục đạt → exit 0
  B. booking_acc tụt (bỏ sót chốt đơn) → exit 1 (trước đây booking không gate)
  C. date_acc tụt (bóc sai ngày) → exit 1
  D. intent_acc tụt → exit 1
  E. tỉ lệ LỖI gọi cao → exit 1 (trước đây run hỏng vẫn 'xanh giả')
  F. reply lộ <analysis>/JSON → exit 1
  G. booking-only case KHÔNG cộng điểm intent free (không thổi phồng intent_acc)

Mock LLM (analyze_message) + override để chạy tất định, KHÔNG gọi mạng.
Chạy TỪ GỐC: python tests/test_eval_gate.py
"""

import os, sys, json
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
from pathlib import Path as _P
_TMPDIR = _P(__file__).parent / '.tmp'
_TMPDIR.mkdir(exist_ok=True)
os.environ['HOMESTAY_DB_PATH'] = str(_TMPDIR / 'test_db_evalgate_tmp.sqlite')
os.environ['EVAL_REPORT'] = str(_TMPDIR / 'eval_report_test.json')
sys.path.insert(0, '.')

import scripts.eval_llm_real as ev
from app.core.config import Config
from app.core import claude_ai
import app.core.brain as brain

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

Config.DEEPSEEK_API_KEY = "sk-fake"   # để main() KHÔNG skip


def run(golden, control, err_texts=()):
    """control: text -> dict result (intent/reply/checkin/booking_confirmed).
    err_texts: text làm analyze_message NÉM lỗi (mô phỏng API rớt)."""
    gf = _TMPDIR / "golden_test.jsonl"
    gf.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in golden), encoding="utf-8")

    def fake_analyze(text, history):
        if text in err_texts:
            raise RuntimeError("API rớt")
        return dict(control.get(text, {"intent": "other", "reply": "ok"}))

    def fake_overrides(text, result, snap):
        return result.get("intent", "other"), snap

    with patch.object(ev, "GOLDEN", gf), \
         patch.object(claude_ai, "analyze_message", fake_analyze), \
         patch.object(brain, "apply_intent_overrides", fake_overrides), \
         patch.object(sys, "argv", ["eval_llm_real.py"]):
        return ev.main()


# golden chuẩn: 4 intent + 1 booking + 1 date(+intent)
GOLDEN = [
    {"text": "q_ok1", "intent": "availability_check"},
    {"text": "q_ok2", "intent": "price_list_request"},
    {"text": "q_ok3", "intent": "photo_request"},
    {"text": "q_ok4", "intent": "contact_request"},
    {"text": "q_book", "expect_booking": True},
    {"text": "q_date", "intent": "other", "checkin": "+1"},
]
GOOD_DATE = ev.expected_date("+1")
GOOD = {
    "q_ok1": {"intent": "availability_check", "reply": "dạ còn phòng"},
    "q_ok2": {"intent": "price_list_request", "reply": "giá 500k"},
    "q_ok3": {"intent": "photo_request", "reply": "ảnh đây"},
    "q_ok4": {"intent": "contact_request", "reply": "sđt 09..."},
    "q_book": {"intent": "booking_confirmed", "reply": "đã giữ phòng", "booking_confirmed": True},
    "q_date": {"intent": "other", "reply": "ok", "checkin": GOOD_DATE},
}

print("\n── A. Mọi trục đạt → 0 ──")
check(run(GOLDEN, GOOD) == 0, "A1 tất cả đạt → exit 0")

print("\n── B. booking tụt → 1 ──")
bad_book = dict(GOOD); bad_book["q_book"] = {"intent": "other", "reply": "ừ", "booking_confirmed": False}
check(run(GOLDEN, bad_book) == 1, "B1 bỏ sót chốt đơn → exit 1 (booking gate MỚI)")

print("\n── C. date tụt → 1 ──")
bad_date = dict(GOOD); bad_date["q_date"] = {"intent": "other", "reply": "ok", "checkin": "01/01/2000"}
check(run(GOLDEN, bad_date) == 1, "C1 bóc sai ngày → exit 1 (date gate MỚI)")

print("\n── D. intent tụt → 1 ──")
bad_int = dict(GOOD)
bad_int["q_ok1"] = {"intent": "other", "reply": "x"}
bad_int["q_ok2"] = {"intent": "other", "reply": "x"}
bad_int["q_ok3"] = {"intent": "other", "reply": "x"}   # 3/5 sai → 40% < 70%
check(run(GOLDEN, bad_int) == 1, "D1 intent 40% < 70% → exit 1")

print("\n── E. lỗi gọi nhiều → 1 (không xanh giả) ──")
# q_ok1,q_ok2 ném lỗi (2/6 ≈ 33% > 20%); phần còn lại đúng hết
check(run(GOLDEN, GOOD, err_texts=("q_ok1", "q_ok2")) == 1,
      "E1 error-rate 33% > 20% → exit 1 (trước đây inflate rồi xanh)")

print("\n── F. leak → 1 ──")
leak = dict(GOOD); leak["q_ok1"] = {"intent": "availability_check", "reply": '<analysis>{"intent":"x"}'}
check(run(GOLDEN, leak) == 1, "F1 reply lộ <analysis> → exit 1")

print("\n── G. booking-only KHÔNG cộng điểm intent free ──")
# Nếu booking-only vẫn tính intent_ok, dù 3/5 intent sai vẫn có thể qua ngưỡng.
# Với sửa mới: intent_total=5 (không gồm q_book), 3 sai → 40% → phải RỚT.
check(run(GOLDEN, bad_int) == 1, "G1 intent chỉ tính case có 'intent' (booking-only không free)")

rep = json.loads(Path(os.environ['EVAL_REPORT']).read_text(encoding="utf-8"))
check(rep.get("intent_total") == 5, "G2 intent_total = 5 (loại booking-only khỏi mẫu)", rep.get("intent_total"))

for suf in ("", "-wal", "-shm"):
    Path(str(_TMPDIR / f"test_db_evalgate_tmp.sqlite{suf}")).unlink(missing_ok=True)

print("\n" + "=" * 40)
print(f"KẾT QUẢ: {PASS} pass / {FAIL} fail")
print("=" * 40)
sys.exit(1 if FAIL else 0)
