#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVAL HARNESS — chấm hành vi NÃO BOT trên CODE THẬT (app.core.brain.Brain), tất định.

Khác test_intent (chấm 1 BẢN COPY của logic override, dễ drift): file này mock LLM
(analyze_message) + Sheets rồi chạy golden-set qua Brain THẬT, kiểm 2 thứ chuẩn eval:
  1. ĐỊNH TUYẾN INTENT (lớp override tiếng Việt) đúng trên code production.
  2. GROUNDING: câu trả lời KHÔNG bịa 'còn phòng' khi Sheets lỗi/hết phòng; không
     rò marker [HỆ THỐNG] ra khách.
Deterministic (0 gọi mạng) → chạy trong CI. Mở rộng golden set = thêm 1 dòng CASES.

Chạy TỪ GỐC:  python tests/test_eval_brain.py
"""

import os
import sys
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'dotenv': MagicMock(),
})
from pathlib import Path
_TMP = Path(__file__).parent / '.tmp'   # rác test vào tests/.tmp, không ra gốc repo
_TMP.mkdir(exist_ok=True)
_DB = _TMP / 'test_db_eval.sqlite'
os.environ['HOMESTAY_DB_PATH'] = str(_DB)
os.environ.setdefault('REPLY_DELAY', '0')
sys.path.insert(0, '.')

for suf in ("", "-wal", "-shm"):
    Path(f"{_DB}{suf}").unlink(missing_ok=True)

from app.core.brain import Brain
from app.core.channel import Channel
from app.core.conversation import ConversationManager

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")


class FakeChannel(Channel):
    def __init__(self):
        self.sent = []          # mọi text gửi khách
        self.calls = []         # tên primitive đã gọi (room/price/notify)
    def send_text(self, u, t): self.sent.append(t)
    def send_room_photos(self, u, names): self.calls.append(("room", tuple(names)))
    def send_price_photos(self, u): self.calls.append(("price",))
    def notify_owner(self, t): self.calls.append(("notify", t))
    def call_owner(self): self.calls.append(("call",))


cm = ConversationManager(account="eval")
ch = FakeChannel()
brain = Brain(channel=ch, conv_manager=cm)


def run(uid, msg, analysis, sheet=None, first=False):
    """Chạy 1 tin qua Brain thật với LLM/Sheets đã mock. Trả (text đã gửi, calls)."""
    conv = cm.get(uid)
    if not first and not conv.messages:      # tránh nhánh 'khách mới' (greeting) trừ khi cố ý
        conv.add_user_message("hi"); conv.add_assistant_message("chào bạn")
    ch.sent = []; ch.calls = []
    with ExitStack() as es:
        es.enter_context(patch("app.core.brain.analyze_message", return_value=dict(analysis)))
        if sheet is not None:
            es.enter_context(patch("app.core.brain.format_availability_for_ai", return_value=sheet))
        brain.handle(uid, msg)
    return "\n".join(ch.sent), ch.calls


OTHER = {"intent": "other", "checkin": None, "checkout": None,
         "reply": "Dạ em nghe ạ.", "booking_confirmed": False, "use_ai_reply": False}


print("── A. Định tuyến intent (override trên Brain thật) ──")

# A1: "còn phòng mai không" AI=other → override availability_check, tự suy ngày mai,
#     Sheets trả CHUA_CO_LICH → câu trả lời hướng khách đặt (grounded)
txt, _ = run("u_a1", "ngày mai còn phòng không", OTHER,
             sheet="[CHUA_CO_LICH]\nchưa có booking")
check("trống" in txt.lower() and "Dạ em nghe ạ." not in txt,
      "A1 avail_override + grounded_chua_co_lich", txt[:120])

# A2: "bảng giá" AI=other → override price_list_request → gửi ảnh bảng giá (shop gốc)
txt, calls = run("u_a2", "cho xin bảng giá", OTHER)
check(any(c[0] == "price" for c in calls), "A2 price_override → send_price_photos", calls)

# A3: "cho gặp chủ" AI=other → override contact_request → báo chủ + trấn an khách
txt, calls = run("u_a3", "cho mình gặp chủ nhà", OTHER)
check("chủ" in txt.lower() and any(c[0] == "notify" for c in calls),
      "A3 contact_override → notify_owner", (txt[:80], calls))

# A4: "ảnh phòng 201" AI=other → override photo_request → gửi ảnh đúng phòng
txt, calls = run("u_a4", "cho xin ảnh phòng 201", OTHER)
check(any(c[0] == "room" and "Phòng 201" in c[1] for c in calls),
      "A4 photo_override → send_room_photos(201)", calls)


print("\n── B. Grounding: KHÔNG bịa 'còn phòng' ──")

# B1: Sheets ĐỌC LỖI → tuyệt đối KHÔNG nói còn/hết phòng, phải báo chủ kiểm tra
avail = dict(OTHER, intent="availability_check", checkin="25/12/2026", checkout="25/12/2026")
txt, calls = run("u_b1", "25/12 còn phòng không", avail, sheet="[LOI_DOC_SHEET]\nlỗi đọc")
low = txt.lower()
check(("trục trặc" in low or "kiểm tra" in low) and "còn trống" not in low
      and any(c[0] == "notify" for c in calls),
      "B1 sheet_error → no_false_availability + báo chủ", txt[:140])

# B2: Hết phòng thật → nói không còn ca trống (không bịa còn)
booked = ("[DỮ LIỆU THỰC TẾ - BẮT BUỘC TUÂN THEO]\nKHÔNG có ca trống nào. NGHIÊM CẤM tự liệt kê.")
txt, _ = run("u_b2", "25/12 còn phòng không", avail, sheet=booked)
check("không còn" in txt.lower() or "không có" in txt.lower(),
      "B2 het_phong → báo hết đúng", txt[:120])

# B3: Có ca trống → hiển thị đúng dữ liệu Sheets, không thêm phòng lạ
slots = "📅 Lịch ca TRỐNG:\n🏠 Nhà A:\n  ✅ Phòng 301: còn ca 20h-22h"
txt, _ = run("u_b3", "25/12 còn phòng không", avail, sheet=slots)
check("301" in txt and "20h-22h" in txt, "B3 co_phong → hiển thị đúng slot", txt[:120])


print("\n── D. Clarify: hỏi lại thay vì im lặng ──")

# D1: AI trả rỗng, không nhánh nào khớp → PHẢI hỏi lại (không câm)
empty = dict(OTHER, reply="")
txt, _ = run("u_d1", "ờ thế à", empty)
check(txt.strip() != "" and ("chưa chắc" in txt.lower() or "hỗ trợ phần nào" in txt.lower()),
      "D1 clarify_khi_reply_rong", txt[:100])

# D2: AI tự tin (use_ai_reply) nhưng rỗng → vẫn clarify, không câm
empty_conf = dict(OTHER, reply="", use_ai_reply=True)
txt, _ = run("u_d2", "hmm", empty_conf)
check(txt.strip() != "", "D2 clarify_khi_use_ai_reply_rong", txt[:100])


print("\n── C. Không rò marker nội bộ ──")

# C1: sau availability, brain ghi [HỆ THỐNG] vào history nhưng KHÔNG gửi cho khách
_, _ = run("u_c1", "25/12 còn phòng không", avail, sheet=slots)
conv_c1 = cm.get("u_c1")
leaked = [m for m in conv_c1.messages
          if m.get("role") == "assistant" and m.get("content", "").startswith("[HỆ THỐNG]")]
sent_leak = any(t.startswith("[HỆ THỐNG]") for t in ch.sent)
check(not sent_leak, "C1 khong_ro_marker_ra_khach", f"leaked_sent={sent_leak}")


try:
    from app.core.db import get_db
    get_db().conn.close()
except Exception:
    pass
for suf in ("", "-wal", "-shm"):
    try:
        Path(f"{_DB}{suf}").unlink(missing_ok=True)
    except OSError:
        pass   # Windows giữ file khi WAL còn mở — không sao, file trong tests/.tmp

print(f"\nKẾT QUẢ EVAL: {PASS} pass / {FAIL} fail")
sys.exit(1 if FAIL else 0)
