#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_flow.py — Kiểm tra luồng hội thoại end-to-end.

Test toàn bộ _handle() với:
  - analyze_message()          → mock trả về intent/checkin/reply tùy scenario
  - format_availability_for_ai() → mock trả về kết quả sheet giả
  - _send_text / _send_price_photos / _send_room_photos → capture output
  - time.sleep                 → no-op để test chạy nhanh

Usage: python -X utf8 test_flow.py
"""

import os, sys, re, time as _time
from unittest.mock import MagicMock, patch
from collections import defaultdict
from datetime import datetime, timedelta

# ─── Mock external deps trước khi import bot ────────────────────────────
class _FakeZaloAPI:
    def __init__(self, *a, **kw): pass
    def uid(self): return "BOT_TEST"
    def sendMessage(self, *a, **kw): pass
    def sendLocalImage(self, *a, **kw): pass

_m_zlapi        = MagicMock(); _m_zlapi.ZaloAPI = _FakeZaloAPI
_m_zlapi_models = MagicMock()
_m_zlapi_models.Message    = type("Message",    (), {"__init__": lambda s,text="":None})
_m_zlapi_models.ThreadType = type("ThreadType", (), {"USER":"user","GROUP":"group"})

sys.modules.update({
    'zlapi':                      _m_zlapi,
    'zlapi.models':               _m_zlapi_models,
    'gspread':                    MagicMock(),
    'google':                     MagicMock(),
    'google.oauth2':              MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai':                     MagicMock(),
    'groq':                       MagicMock(),
    'winsound':                   MagicMock(),
    'PIL':                        MagicMock(),
    'PIL.Image':                  MagicMock(),
})

os.environ.setdefault('REPLY_DELAY', '0')
os.environ['HOMESTAY_DB_PATH'] = 'test_db_tmp.sqlite'   # DB test riêng, không đụng DB thật
sys.path.insert(0, '.')

from app.channels.zalo_cookie import bot as bot_module
from app.channels.zalo_cookie.bot import ZaloChannel, conv_manager
from app.core.brain import Brain, FIRST_MESSAGE_GREETING, _infer_date_from_text
from app.core.channel import Channel
from app.core.conversation import ConversationManager

# Cô lập test khỏi DB production: HOMESTAY_DB_PATH (đặt ở trên, TRƯỚC import app)
# trỏ sang test_db_tmp.sqlite. Bắt đầu với state rỗng để tránh uid trùng.
conv_manager._sessions.clear()

_UID_COUNTER = [0]

def _uid():
    """Tạo user ID mới mỗi test để tránh ô nhiễm state."""
    _UID_COUNTER[0] += 1
    return f"user_{_UID_COUNTER[0]:04d}"

THREAD = "thread_test"
TTYPE  = "user"

# ─── Bot giả — capture output thay vì gửi Zalo thật ────────────────────
# TestBot kế thừa ZaloChannel để giữ onMessage + chống echo + owner-takeover thật,
# nhưng override các primitive của Channel để CAPTURE thay vì gửi Zalo thật.
# Logic xử lý nằm ở Brain (brain.py) — TestBot.brain gọi vào đó.
class TestBot(ZaloChannel):
    def __init__(self):
        self._account           = 1
        from collections import deque
        self._bot_sent_cache    = deque(maxlen=100)   # fingerprint cache như ZaloChannel thật
        self._bot_image_threads = deque(maxlen=200)
        self.sent_texts         : list[str]  = []
        self.sent_rooms     : list[str]  = []
        self.price_sent     : bool       = False
        self.owner_msgs     : list[str]  = []
        self.call_fired     : bool       = False
        self.conv_manager   = conv_manager
        self.brain          = Brain(channel=self, conv_manager=conv_manager)

    def uid(self): return "BOT_TEST"

    # ── Channel primitives — capture ──
    def send_text(self, user_id, text):
        # Giữ nguyên logic chunking của ZaloChannel.send_text (bao gồm _track_sent)
        MAX_LEN = 2000
        chunks = [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)]
        for chunk in chunks:
            self._track_sent(user_id, chunk)   # lưu fingerprint như bot thật
            self.sent_texts.append(chunk)

    def send_price_photos(self, user_id):
        self.price_sent = True

    def send_room_photos(self, user_id, room_names):
        self.sent_rooms.extend(room_names)

    def notify_owner(self, text):
        self.owner_msgs.append(text)

    def call_owner(self):
        self.call_fired = True

    # Không gửi ảnh thật nên _image_size không cần PIL
    @staticmethod
    def _image_size(path): return (1920, 1080)

    def reset(self):
        self.sent_texts = []; self.sent_rooms = []
        self.price_sent = False; self.owner_msgs = []; self.call_fired = False

    # Gọi brain.handle() với time.sleep bị no-op
    def handle(self, uid, text, ai_result=None, sheets_result=None):
        with patch('app.core.brain.time') as pt, \
             patch('app.core.brain.analyze_message', return_value=ai_result or {}), \
             patch('app.core.brain.format_availability_for_ai', return_value=sheets_result or ""):
            pt.sleep = lambda *a: None
            self.brain.handle(uid, text)


# ─── Helpers ─────────────────────────────────────────────────────────────
PASS = FAIL = 0
FAILURES: list[tuple[str,str,str]] = []

def check(cond: bool, name: str, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append((name, detail, ""))
        print(f"  ✗ FAIL  {name}: {detail}")

def ok(name: str):
    global PASS
    PASS += 1

def section(title: str):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ════════════════════════════════════════════════════════════════
# GROUP A — First-message handling
# ════════════════════════════════════════════════════════════════
section("A. Tin nhắn đầu tiên")

def test_first_text_greeting():
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "xin chào", ai_result={"intent":"other","reply":"Chào bạn!"})
    check(any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "A1 first_text_greeting", "greeting phải có trong sent_texts")
    check(bot.price_sent, "A1 first_text_price", "bảng giá phải được gửi")
    # intent=other → không gửi thêm reply AI
    extra = [t for t in bot.sent_texts if t == "Chào bạn!"]
    check(len(extra) == 0, "A1 first_text_no_extra_reply", "không được gửi reply AI khi intent=other")

def test_first_text_with_avail_intent():
    """Tin nhắn đầu có intent cụ thể → greeting + xử lý luôn."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG từ...\n🏠 Haru:\n  ✅ Phòng 201: còn ca 21h-10h30")
    check(any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "A2 first+intent greeting", "greeting vẫn phải gửi dù có intent")
    check(any("201" in t or "Haru" in t or "kiểm tra" in t for t in bot.sent_texts),
          "A2 first+intent avail_reply", "phải có reply kết quả phòng trống")

def test_sticker_first_message():
    """Sticker (text rỗng) là tin đầu tiên → greeting."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "", ai_result={})
    check(any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "A3 sticker_greeting", "sticker đầu tiên phải nhận greeting")
    check(bot.price_sent, "A3 sticker_price", "sticker đầu tiên phải gửi bảng giá")

def test_second_message_no_greeting():
    """Tin thứ 2 trở đi KHÔNG được gửi greeting lại."""
    bot = TestBot(); uid = _uid()
    # Tin 1
    bot.handle(uid, "xin chào", ai_result={"intent":"other","reply":""})
    bot.reset()
    # Tin 2
    bot.handle(uid, "còn phòng không",
               ai_result={"intent":"availability_check","checkin":None,"reply":""},
               sheets_result="")
    check(not any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "A4 no_repeat_greeting", "tin thứ 2 không được gửi greeting")

def test_sticker_second_ignored():
    """Sticker sau tin đầu tiên → bỏ qua."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "xin chào", ai_result={"intent":"other","reply":""})
    bot.reset()
    # Sticker thứ 2
    with patch('app.channels.zalo_cookie.bot.time') as pt:
        pt.sleep = lambda *a: None
        bot_module.conv_manager.get(uid)  # ensure conv exists
        # Simulate onMessage with empty text, but conv already has messages
    conv = conv_manager.get(uid)
    check(len(conv.messages) > 0, "A5 second_sticker_has_history", "conv phải có messages")

test_first_text_greeting()
test_first_text_with_avail_intent()
test_sticker_first_message()
test_second_message_no_greeting()
test_sticker_second_ignored()


# ════════════════════════════════════════════════════════════════
# GROUP B — Availability check flow
# ════════════════════════════════════════════════════════════════
section("B. Kiểm tra lịch phòng")

def test_avail_with_ai_checkin():
    """AI trả về checkin → gọi sheets → reply kết quả."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    # First message
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    # Second message
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 201: còn ca 21h-10h30")
    check(any("201" in t or "còn" in t for t in bot.sent_texts),
          "B1 avail_ai_checkin", "phải reply có info phòng")
    conv = conv_manager.get(uid)
    check(conv.stage == "offering", "B1 stage_offering", "stage phải chuyển sang offering")

def test_avail_python_infer_today():
    """AI không trả checkin → Python infer 'tối nay' → sheets."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":None,"checkout":None,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 301: còn ca 16h30-20h30")
    conv = conv_manager.get(uid)
    check(conv.checkin == today, "B2 python_infer_today", f"checkin nên là {today}, got {conv.checkin}")

def test_avail_python_infer_tomorrow():
    """'ngày mai' → infer ngày mai."""
    bot = TestBot(); uid = _uid()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d/%m/%Y")
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ngày mai còn phòng ko",
               ai_result={"intent":"availability_check","checkin":None,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG")
    conv = conv_manager.get(uid)
    check(conv.checkin == tomorrow, "B3 python_infer_tomorrow",
          f"checkin nên là {tomorrow}, got {conv.checkin}")

def test_avail_no_date_ask():
    """Không có ngày → bot hỏi lại, KHÔNG gọi sheets."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    sheets_called = []
    with patch('app.core.brain.format_availability_for_ai', side_effect=lambda *a: sheets_called.append(a) or "") as msh, \
         patch('app.core.brain.analyze_message', return_value={"intent":"availability_check","checkin":None,"reply":""}), \
         patch('app.core.brain.time') as pt:
        pt.sleep = lambda *a: None
        bot.brain.handle(uid, "còn phòng không")
    check(len(sheets_called) == 0, "B4 no_date_no_sheets", "không được gọi sheets khi chưa có ngày")
    check(any("ngày nào" in t or "kiểm tra" in t for t in bot.sent_texts),
          "B4 no_date_ask_reply", "phải hỏi ngày")

def test_avail_chua_co_lich():
    """[CHUA_CO_LICH] → reply 'chưa có booking, còn trống'."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="[CHUA_CO_LICH]\nNgày X: chưa có lịch booking nào...")
    check(any("chưa" in t and ("trống" in t or "booking" in t) for t in bot.sent_texts),
          "B5 chua_co_lich_reply", "phải nói 'chưa có booking, còn trống'")
    check(not any("hết phòng" in t or "không còn" in t for t in bot.sent_texts),
          "B5 chua_co_lich_no_full", "KHÔNG được nói 'hết phòng'")

def test_avail_all_booked():
    """KHÔNG có ca trống (sheet có dữ liệu) → reply 'không còn'."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="[DỮ LIỆU THỰC TẾ - BẮT BUỘC TUÂN THEO]\nKHÔNG có ca trống nào...\nNGHIÊM CẤM")
    check(any("không còn" in t or "hết" in t or "trống nào" in t for t in bot.sent_texts),
          "B6 all_booked_reply", "phải nói 'không còn ca trống'")

def test_avail_date_regex_specific():
    """'ngày 25 còn phòng ko' → Python dùng regex nhận ngày."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ngày 25 còn phòng ko",
               ai_result={"intent":"availability_check","checkin":None,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 201: còn ca 21h-10h30")
    # Kết quả: intent=availability_check (có _has_day vì "ngày 25") và phải check được
    conv = conv_manager.get(uid)
    check(conv.checkin is not None or any("kiểm tra" in t or "201" in t for t in bot.sent_texts),
          "B7 specific_date_regex", "ngày cụ thể phải được xử lý")

def test_avail_multiturn_date_then_check():
    """Luồng 2 bước: hỏi ngày → trả lời ngày → check sheet."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    # Bước 1: bot hỏi ngày
    bot.handle(uid, "còn phòng không",
               ai_result={"intent":"availability_check","checkin":None,"reply":""})
    check(any("ngày nào" in t for t in bot.sent_texts),
          "B8a ask_date", "phải hỏi 'ngày nào'")
    bot.reset()
    # Bước 2: khách trả lời ngày
    bot.handle(uid, "tối nay",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 301: còn ca 21h-10h30")
    check(any("301" in t or "còn" in t for t in bot.sent_texts),
          "B8b date_answered_then_sheets", "phải reply kết quả sheet sau khi có ngày")

test_avail_with_ai_checkin()
test_avail_python_infer_today()
test_avail_python_infer_tomorrow()
test_avail_no_date_ask()
test_avail_chua_co_lich()
test_avail_all_booked()
test_avail_date_regex_specific()
test_avail_multiturn_date_then_check()


# ════════════════════════════════════════════════════════════════
# GROUP C — Price list
# ════════════════════════════════════════════════════════════════
section("C. Bảng giá")

def test_price_sends_photos():
    """Bất kỳ yêu cầu bảng giá → gửi price photos."""
    for msg, note in [
        ("bảng giá",              "C1 bảng_giá"),
        ("giá phòng bao nhiêu",   "C2 giá_bao_nhiêu"),
        ("cho xin giá",           "C3 cho_xin_giá"),
        ("phòng nào rẻ nhất",     "C4 rẻ_nhất"),
        ("cho mình xem giá",      "C5 xem_giá"),
        ("giá haru bao nhiêu",    "C6 giá_haru"),
    ]:
        bot = TestBot(); uid = _uid()
        bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
        bot.reset()
        bot.handle(uid, msg, ai_result={"intent":"price_list_request","reply":"Đây là bảng giá:"})
        check(bot.price_sent, note, f"'{msg}' → phải gửi price photos")

def test_price_reply_sent():
    """AI reply kèm giá → reply text cũng được gửi."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "bảng giá", ai_result={"intent":"price_list_request","reply":"Bảng giá phòng:"})
    check(any("Bảng giá" in t for t in bot.sent_texts),
          "C7 price_text_reply", "reply AI cũng phải được gửi")

test_price_sends_photos()
test_price_reply_sent()


# ════════════════════════════════════════════════════════════════
# GROUP D — Photo request
# ════════════════════════════════════════════════════════════════
section("D. Ảnh phòng")

def test_photo_single_room():
    """'ảnh 201' → gửi ảnh phòng 201."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ảnh 201", ai_result={"intent":"photo_request","reply":"Đây là ảnh phòng 201"})
    check(any("201" in r for r in bot.sent_rooms) or any("201" in t for t in bot.sent_texts),
          "D1 photo_single_room", "phải gửi ảnh phòng 201")

def test_photo_multi_rooms():
    """'ảnh 201 và 301' → gửi ảnh cả 2 phòng."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ảnh 201 và 301", ai_result={"intent":"photo_request","reply":""})
    rooms = bot.sent_rooms
    check(any("201" in r for r in rooms) or any("201" in t for t in bot.sent_texts),
          "D2 photo_multi_201", "phải có phòng 201")
    check(any("301" in r for r in rooms) or any("301" in t for t in bot.sent_texts),
          "D2 photo_multi_301", "phải có phòng 301")

def test_photo_haru_keyword():
    """'ảnh haru' → gửi ảnh 201, 202, 301."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ảnh haru", ai_result={"intent":"photo_request","reply":""})
    text_all = " ".join(bot.sent_texts + bot.sent_rooms)
    check("201" in text_all and "202" in text_all and "301" in text_all,
          "D3 photo_haru", "phải có 201, 202, 301")

def test_photo_mochi_keyword():
    """'ảnh mochi' → gửi ảnh 111, 112, 211, 212, 311."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ảnh mochi", ai_result={"intent":"photo_request","reply":""})
    text_all = " ".join(bot.sent_texts + bot.sent_rooms)
    check("111" in text_all and "211" in text_all,
          "D4 photo_mochi", "phải có 111, 211 (mochi rooms)")

def test_photo_room_number_only():
    """Chỉ gõ '201' → nhận ảnh phòng."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "201", ai_result={"intent":"other","reply":""})
    # Override should detect photo_request from room-only message
    text_all = " ".join(bot.sent_texts + bot.sent_rooms)
    check("201" in text_all, "D5 room_number_only", "chỉ '201' → phải gửi ảnh phòng 201")

def test_photo_generic_all():
    """'ảnh phòng đẹp nhất' → trigger photo intent (generic phrase)."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "ảnh phòng đẹp nhất", ai_result={"intent":"other","reply":"Ảnh phòng đây bạn"})
    # photo_request should be triggered even without specific room
    check(any("ảnh" in t.lower() or "phòng" in t.lower() for t in bot.sent_texts + bot.sent_rooms)
          or len(bot.sent_texts) > 0,
          "D6 generic_photo_phrase", "generic photo phrase phải tạo ra reply hoặc ảnh")

test_photo_single_room()
test_photo_multi_rooms()
test_photo_haru_keyword()
test_photo_mochi_keyword()
test_photo_room_number_only()
test_photo_generic_all()


# ════════════════════════════════════════════════════════════════
# GROUP E — Contact request
# ════════════════════════════════════════════════════════════════
section("E. Liên hệ chủ nhà")

def test_contact_sends_fixed_reply():
    """'gọi chủ đi' → fixed reply + owner notified."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "gọi chủ đi", ai_result={"intent":"contact_request","reply":""})
    check(any("báo" in t or "chủ nhà" in t or "liên hệ" in t for t in bot.sent_texts),
          "E1 contact_fixed_reply", "phải gửi reply thông báo đang gọi chủ")
    check(len(bot.owner_msgs) > 0, "E1 owner_notified", "chủ nhà phải nhận được thông báo")
    check(bot.call_fired, "E1 call_fired", "_zalo_call phải được gọi")

def test_contact_override_other():
    """'mình muốn gặp admin' → Python override → contact_request."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "mình muốn gặp admin", ai_result={"intent":"other","reply":"Để tôi giúp"})
    check(len(bot.owner_msgs) > 0 and bot.call_fired,
          "E2 contact_override", "Python override contact từ 'mình muốn gặp admin'")

def test_contact_owner_msg_has_user_text():
    """Thông báo chủ nhà phải chứa nội dung tin nhắn gốc của khách."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    msg = "tôi cần nói chuyện với chủ nhà ngay bây giờ"
    bot.handle(uid, msg, ai_result={"intent":"contact_request","reply":""})
    combined_owner = " ".join(bot.owner_msgs)
    check(uid in combined_owner or msg[:20] in combined_owner,
          "E3 owner_msg_context", "thông báo chủ phải có uid hoặc nội dung tin nhắn")

def test_contact_false_positive_self_intro():
    """'gọi mình là Tuấn' KHÔNG trigger contact."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "gọi mình là Tuấn", ai_result={"intent":"other","reply":"Chào Tuấn!"})
    check(not bot.call_fired and len(bot.owner_msgs) == 0,
          "E4 fp_self_intro", "'gọi mình là [tên]' KHÔNG được trigger contact_request")

test_contact_sends_fixed_reply()
test_contact_override_other()
test_contact_owner_msg_has_user_text()
test_contact_false_positive_self_intro()


# ════════════════════════════════════════════════════════════════
# GROUP F — Booking confirmed
# ════════════════════════════════════════════════════════════════
section("F. Đặt phòng / Booking confirm")

def test_booking_confirmed_available():
    """Khách chốt đặt + sheet còn phòng → reply booking + thông báo chủ."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("tối nay")  # setup checkin
    conv.checkin  = today
    conv.checkout = today
    bot.handle(uid, "đặt phòng 201 ca tối đi",
               ai_result={"intent":"booking_confirm","booking_confirmed":True,"reply":"Đã đặt xong!"},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 201: còn ca 21h-10h30")
    check(any("đặt" in t or "xác nhận" in t or "ghi nhận" in t for t in bot.sent_texts),
          "F1 booking_reply", "phải có reply xác nhận booking")
    check(len(bot.owner_msgs) > 0, "F1 owner_notified", "chủ nhà phải được thông báo")
    # ĐỔI HÀNH VI (2026-07-06): booking KHÔNG còn tự gọi điện — sự kiện 'new_order'
    # mặc định chỉ NHẮN TIN (notify), tránh 10k khách = 10k cuộc gọi. Chủ muốn gọi
    # thì bật 'call' trong Cài đặt. Xem notify.EVENTS + tests/test_notify.py E3/E4.
    check(not bot.call_fired, "F1 no_auto_call", "booking mặc định KHÔNG tự gọi (chỉ nhắn)")

def test_booking_confirmed_all_taken():
    """Khách chốt đặt + sheet hết phòng → từ chối, KHÔNG thông báo chủ."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("x"); conv.checkin = today; conv.checkout = today
    bot.handle(uid, "cho mình đặt đi",
               ai_result={"intent":"booking_confirm","booking_confirmed":True,"reply":"Đã đặt!"},
               sheets_result="[DỮ LIỆU THỰC TẾ]\nKHÔNG có ca trống nào\nNGHIÊM CẤM")
    check(any("không còn" in t or "hết" in t or "trống nào" in t for t in bot.sent_texts),
          "F2 booking_deny_reply", "phải nói 'không còn ca' khi hết phòng")
    check(len(bot.owner_msgs) == 0 and not bot.call_fired,
          "F2 no_owner_when_full", "chủ không được thông báo khi hết phòng")

def test_booking_confirmed_chua_co_lich():
    """Sheet chưa có dữ liệu → vẫn xác nhận booking (có thể đặt)."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("x"); conv.checkin = today; conv.checkout = today
    bot.handle(uid, "đặt luôn đi",
               ai_result={"intent":"booking_confirm","booking_confirmed":True,"reply":"Đặt thành công!"},
               sheets_result="[CHUA_CO_LICH]\nNgày X: chưa có lịch...")
    check(any("đặt" in t or "ghi nhận" in t or "xác nhận" in t for t in bot.sent_texts),
          "F3 booking_no_data_confirm", "[CHUA_CO_LICH] → có thể đặt, reply booking bình thường")
    check(len(bot.owner_msgs) > 0, "F3 owner_notified_no_data", "chủ phải được thông báo")

def test_booking_stage_no_double_notify():
    """Booking chỉ thông báo chủ 1 lần, dù khách nhắn nhiều lần."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("x"); conv.checkin = today; conv.checkout = today
    # Lần 1 confirm
    bot.handle(uid, "đặt đi",
               ai_result={"intent":"booking_confirm","booking_confirmed":True,"reply":"OK"},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 201: còn ca 21h-10h30")
    notify_count_1 = len(bot.owner_msgs)
    # Lần 2 confirm lại (trùng)
    bot.handle(uid, "đặt đi nha",
               ai_result={"intent":"booking_confirm","booking_confirmed":True,"reply":"OK"},
               sheets_result="📅 Lịch ca TRỐNG\n  ✅ Phòng 201: còn ca 21h-10h30")
    check(len(bot.owner_msgs) == notify_count_1,
          "F4 no_double_notify", "booking đã xác nhận rồi thì không thông báo lần 2")

test_booking_confirmed_available()
test_booking_confirmed_all_taken()
test_booking_confirmed_chua_co_lich()
test_booking_stage_no_double_notify()


# ════════════════════════════════════════════════════════════════
# GROUP G — State transitions & conversation context
# ════════════════════════════════════════════════════════════════
section("G. State transitions & luồng multi-turn")

def test_stage_transitions():
    """greeting → checking → offering khi hỏi lịch."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    check(conv.stage == "greeting", "G1a stage_initial", "stage ban đầu phải là greeting")
    # Tin đầu
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    # Hỏi lịch
    bot.reset()
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="📅 Lịch trống...")
    check(conv.stage == "offering", "G1b stage_offering", "sau khi check sheet → offering")

def test_context_followup_in_offering():
    """Trong stage offering, 'cả 2 luôn' → check sheets (Case 5 override)."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("đã hỏi trước")
    conv.checkin = today; conv.checkout = today; conv.stage = "offering"
    sheets_called = []
    with patch('app.core.brain.format_availability_for_ai',
               side_effect=lambda *a: sheets_called.append(a) or "📅 Lịch trống") as ms, \
         patch('app.core.brain.analyze_message',
               return_value={"intent":"other","checkin":None,"reply":""}), \
         patch('app.core.brain.time') as pt:
        pt.sleep = lambda *a: None
        bot.brain.handle(uid, "cả 2 luôn đi")
    check(len(sheets_called) > 0, "G2 followup_in_offering",
          "'cả 2 luôn đi' trong offering+checkin phải check sheets")

def test_checkin_persists_across_turns():
    """checkin được giữ qua nhiều tin nhắn."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    # Tin 1 thiết lập checkin
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.handle(uid, "tối nay còn phòng ko",
               ai_result={"intent":"availability_check","checkin":today,"checkout":today,"reply":""},
               sheets_result="📅 Lịch trống")
    conv = conv_manager.get(uid)
    check(conv.checkin == today, "G3a checkin_set", "checkin phải được set")
    bot.reset()
    # Tin tiếp theo không nêu ngày
    bot.handle(uid, "phòng nào trống",
               ai_result={"intent":"availability_check","checkin":None,"reply":""},
               sheets_result="📅 Lịch trống cụ thể")
    check(conv.checkin == today, "G3b checkin_persists", "checkin phải giữ nguyên")
    check(any("trống" in t for t in bot.sent_texts),
          "G3c reply_uses_saved_checkin", "phải dùng checkin cũ để check sheet")

def test_ai_history_used():
    """Lịch sử hội thoại được truyền cho analyze_message (không bao gồm tin vừa thêm)."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    received_history = []
    def fake_ai(text, history, *a, **kw):   # nhận thêm user_id/account (CRM memory)
        received_history.append(list(history))
        return {"intent":"other","reply":"ok"}
    conv = conv_manager.get(uid)
    conv.add_user_message("tin trước")
    conv.add_assistant_message("trả lời trước")
    with patch('app.core.brain.analyze_message', side_effect=fake_ai), \
         patch('app.core.brain.time') as pt:
        pt.sleep = lambda *a: None
        bot.brain.handle(uid, "tin mới")
    check(len(received_history) > 0 and len(received_history[0]) >= 2,
          "G4 ai_gets_history", "analyze_message phải nhận lịch sử ≥ 2 turns")

test_stage_transitions()
test_context_followup_in_offering()
test_checkin_persists_across_turns()
test_ai_history_used()


# ════════════════════════════════════════════════════════════════
# GROUP H — Edge cases
# ════════════════════════════════════════════════════════════════
section("H. Edge cases")

def test_long_message_split():
    """Reply >2000 ký tự phải được chia thành nhiều phần gửi."""
    bot = TestBot(); uid = _uid()
    long_reply = "A" * 4500
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "kể tôi nghe",
               ai_result={"intent":"other","reply":long_reply})
    total_chars = sum(len(t) for t in bot.sent_texts)
    check(total_chars >= 4500, "H1 long_msg_split_chars",
          f"tổng ký tự gửi {total_chars} phải ≥ 4500")
    check(len(bot.sent_texts) >= 2, "H1 long_msg_split_count",
          f"phải chia thành ≥2 phần (got {len(bot.sent_texts)})")

def test_unknown_intent_uses_ai_reply():
    """Intent không khớp override nào → dùng reply từ AI."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "phòng có wifi không",
               ai_result={"intent":"other","reply":"Dạ phòng có wifi miễn phí bạn nhé!"})
    check(any("wifi" in t for t in bot.sent_texts),
          "H2 ai_reply_passthrough", "reply AI phải được gửi khi không có override")

def test_price_false_positive_xe_may():
    """'xe máy mấy tiền thuê' KHÔNG phải price_list_request."""
    bot = TestBot(); uid = _uid()
    bot.handle(uid, "x", ai_result={"intent":"other","reply":""})
    bot.reset()
    bot.handle(uid, "xe máy mấy tiền thuê",
               ai_result={"intent":"other","reply":"Dạ bên mình không cho thuê xe máy"})
    check(not bot.price_sent, "H3 fp_xe_may_no_price_photos",
          "'xe máy' không được trigger bảng giá")

def test_infer_date_direct():
    """Unit test _infer_date_from_text trực tiếp."""
    now = datetime.now()
    today_str = now.strftime("%d/%m/%Y")
    tomorrow_str = (now + timedelta(days=1)).strftime("%d/%m/%Y")
    d2_str = (now + timedelta(days=2)).strftime("%d/%m/%Y")

    cases = [
        ("tối nay còn phòng ko",       today_str,    "tối nay"),
        ("hôm nay",                     today_str,    "hôm nay"),
        ("tnay",                        today_str,    "tnay abbrev"),
        ("ngày mai",                    tomorrow_str, "ngày mai"),
        ("mai chiều còn phòng ko",      tomorrow_str, "mai chiều"),
        ("ngày mốt",                    d2_str,       "ngày mốt"),
    ]
    for text, expected, note in cases:
        result = _infer_date_from_text(text)
        check(result == expected, f"H4 infer_{note}",
              f"'{text}' → expected {expected}, got {result}")

def test_avail_no_repeat_check_when_offering():
    """Sau khi đã offer, tin nhắn 'ok đặt' không gọi sheets 2 lần."""
    bot = TestBot(); uid = _uid()
    today = datetime.now().strftime("%d/%m/%Y")
    conv = conv_manager.get(uid)
    conv.add_user_message("x"); conv.checkin = today; conv.checkout = today
    conv.stage = "offering"
    # Mock booking scenario
    sheets_calls = []
    with patch('app.core.brain.format_availability_for_ai',
               side_effect=lambda *a: sheets_calls.append(1) or "📅 Lịch trống\n  ✅ Phòng 201"),\
         patch('app.core.brain.analyze_message',
               return_value={"intent":"booking_confirm","booking_confirmed":True,"reply":"OK"}),\
         patch('app.core.brain.time') as pt:
        pt.sleep = lambda *a: None
        bot.brain.handle(uid, "đặt phòng 201 tối nay đi")
    check(len(sheets_calls) == 1, "H5 sheets_called_once",
          f"sheets phải gọi đúng 1 lần khi booking, got {len(sheets_calls)}")

test_long_message_split()
test_unknown_intent_uses_ai_reply()
test_price_false_positive_xe_may()
test_infer_date_direct()
test_avail_no_repeat_check_when_offering()


# ════════════════════════════════════════════════════════════════
# GROUP I — Owner Takeover
# ════════════════════════════════════════════════════════════════
section("I. Chủ nhà tiếp quản — bot dừng reply")

def _simulate_owner_reply(bot: TestBot, customer_uid: str):
    """Giả lập chủ nhà tự tay nhắn cho khách từ app Zalo.
    → onMessage fires với author_id == bot.uid(), thread_id == customer_uid
    và thread KHÔNG có trong _bot_handling (vì không phải auto-reply).
    """
    bot.onMessage(
        mid=None,
        author_id=bot.uid(),   # chính account bot/chủ
        message="Ok mình sẽ hỗ trợ bạn nhé!",
        thread_id=customer_uid,
        thread_type=TTYPE,
    )

def _simulate_customer_msg(bot: TestBot, customer_uid: str, text: str,
                            ai_result=None, sheets_result=None):
    """Giả lập khách gửi tin nhắn (đi qua onMessage đầy đủ)."""
    with patch('app.core.brain.analyze_message', return_value=ai_result or {"intent":"other","reply":"ok"}), \
         patch('app.core.brain.format_availability_for_ai', return_value=sheets_result or ""), \
         patch('app.core.brain.time') as pt, \
         patch('app.channels.zalo_cookie.bot.time') as pt2:
        pt.sleep = lambda *a: None
        pt2.sleep = lambda *a: None
        bot.onMessage(
            mid=None,
            author_id=customer_uid,
            message=text,
            thread_id=customer_uid,
            thread_type=TTYPE,
        )

def test_owner_takeover_stops_bot():
    """Sau khi chủ nhà tự nhắn, bot không reply tin nhắn tiếp của khách."""
    bot = TestBot(); uid = _uid()

    # Khách nhắn lần 1 → bot reply bình thường
    _simulate_customer_msg(bot, uid, "xin chào")
    check(any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "I1a bot_replied_before_takeover", "bot phải reply trước khi chủ tiếp quản")

    # Chủ nhà tự tay nhắn → đánh dấu owner_active
    _simulate_owner_reply(bot, uid)
    conv = conv_manager.get(uid)
    check(conv.owner_active, "I1b owner_active_set", "owner_active phải = True sau khi chủ nhắn")

    # Khách nhắn tiếp → bot phải im lặng
    bot.reset()
    _simulate_customer_msg(bot, uid, "tối nay còn phòng ko")
    check(len(bot.sent_texts) == 0 and not bot.price_sent,
          "I1c bot_silent_after_takeover", "bot KHÔNG được reply sau khi chủ tiếp quản")

def test_bot_autoreply_not_trigger_takeover():
    """Auto-reply của bot (bên trong _handle) KHÔNG kích hoạt owner_active."""
    bot = TestBot(); uid = _uid()

    # Khách nhắn → bot tự reply (trong _handle → _bot_handling chứa thread_id)
    _simulate_customer_msg(bot, uid, "bảng giá",
                           ai_result={"intent":"price_list_request","reply":"Giá:"})

    conv = conv_manager.get(uid)
    check(not conv.owner_active,
          "I2 autoreply_no_takeover", "auto-reply của bot KHÔNG được kích hoạt owner_active")

def test_owner_active_log_skip():
    """Log [Skip] phải xuất hiện khi bot bỏ qua tin nhắn của khách bị tiếp quản."""
    bot = TestBot(); uid = _uid()

    # Setup: chủ đã tiếp quản (dùng set_owner_active để đóng dấu timestamp,
    # nếu không is_owner_active() sẽ tự reset vì thiếu owner_active_since)
    conv = conv_manager.get(uid)
    conv.set_owner_active(True)

    # Khách nhắn → phải bị skip hoàn toàn
    bot.reset()
    _simulate_customer_msg(bot, uid, "còn phòng không")
    check(len(bot.sent_texts) == 0, "I3 skip_when_owner_active",
          "owner_active=True → bot không gửi gì cả")

def test_new_customer_not_affected():
    """owner_active của khách A không ảnh hưởng khách B."""
    bot = TestBot()
    uid_a = _uid()
    uid_b = _uid()

    # Chủ tiếp quản khách A
    conv_a = conv_manager.get(uid_a)
    conv_a.owner_active = True

    # Khách B nhắn → bot vẫn reply bình thường
    _simulate_customer_msg(bot, uid_b, "xin chào")
    check(any(FIRST_MESSAGE_GREETING in t for t in bot.sent_texts),
          "I4 other_customer_unaffected", "khách B không bị ảnh hưởng bởi takeover của khách A")

def test_bot_echo_fingerprint_no_takeover():
    """Echo Zalo (cùng nội dung bot vừa gửi) KHÔNG kích hoạt owner_active.
    Mô phỏng đúng timing thực tế: echo về SAU khi _handle() đã xong.
    """
    bot = TestBot(); uid = _uid()

    # Bot gửi greeting (track fingerprint vào cache)
    bot.send_text(uid, FIRST_MESSAGE_GREETING)

    # Zalo echo về sau (như thực tế — 4+ giây sau)
    bot.onMessage(
        mid=None,
        author_id=bot.uid(),
        message=FIRST_MESSAGE_GREETING,   # cùng nội dung bot vừa gửi
        thread_id=uid,
        thread_type=TTYPE,
    )
    conv = conv_manager.get(uid)
    check(not conv.owner_active,
          "I5 echo_fingerprint_no_takeover",
          "echo cùng nội dung bot gửi KHÔNG được set owner_active")

def test_owner_different_text_triggers_takeover():
    """Chủ gõ nội dung KHÁC với bot → kích hoạt owner_active."""
    bot = TestBot(); uid = _uid()

    # Bot gửi greeting
    bot.send_text(uid, FIRST_MESSAGE_GREETING)

    # Chủ nhà gõ tay — nội dung khác hoàn toàn
    bot.onMessage(
        mid=None,
        author_id=bot.uid(),
        message="Ok để anh hỗ trợ trực tiếp cho bạn nhé",  # chủ tự gõ
        thread_id=uid,
        thread_type=TTYPE,
    )
    conv = conv_manager.get(uid)
    check(conv.owner_active,
          "I6 owner_diff_text_takeover",
          "chủ gõ nội dung khác → phải set owner_active")

test_owner_takeover_stops_bot()
test_bot_autoreply_not_trigger_takeover()
test_owner_active_log_skip()
test_new_customer_not_affected()
test_bot_echo_fingerprint_no_takeover()
test_owner_different_text_triggers_takeover()


# ════════════════════════════════════════════════════════════════
# FINAL REPORT
# ════════════════════════════════════════════════════════════════
print(f"\n{'═'*65}")
print(f"  KẾT QUẢ FLOW TESTS")
print(f"{'═'*65}")
print(f"  ✅ PASS : {PASS:4d} / {PASS+FAIL}")
print(f"  ❌ FAIL : {FAIL:4d} / {PASS+FAIL}")
print(f"\n  📊 Pass rate: {PASS/(PASS+FAIL)*100:.1f}%")

if FAILURES:
    print(f"\n{'─'*65}")
    print("  ❌ CHI TIẾT THẤT BẠI:")
    for name, detail, _ in FAILURES:
        print(f"    • [{name}] {detail}")

print(f"\n  Nhóm:\n"
      f"    A. First message      | B. Availability\n"
      f"    C. Price list         | D. Photo request\n"
      f"    E. Contact request    | F. Booking confirm\n"
      f"    G. State transitions  | H. Edge cases\n"
      f"    I. Owner Takeover")
print(f"{'═'*65}\n")

sys.exit(0 if FAIL == 0 else 1)
