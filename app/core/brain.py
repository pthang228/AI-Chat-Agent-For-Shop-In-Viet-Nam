"""
"Não bộ" của bot — toàn bộ logic xử lý tin nhắn khách, ĐỘC LẬP với kênh.

Brain không biết gì về Zalo/Instagram/Messenger. Nó chỉ:
  - đọc/ghi trạng thái hội thoại qua ConversationManager
  - hỏi AI (claude_ai), tra lịch (sheets)
  - và RA LỆNH gửi tin qua giao diện Channel (channel.send_text, send_room_photos, ...)

Muốn thêm kênh mới → viết 1 class implement Channel rồi gọi Brain.handle(user_id, text).
Toàn bộ logic intent/override/booking nằm ở đây, dùng chung cho mọi kênh.
"""

import re
import time
import logging
import threading
from collections import OrderedDict
from datetime import datetime as _dt, timedelta as _td
from pathlib import Path

from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.channel import Channel
from app.core.sheets import format_availability_for_ai
from app.core.claude_ai import analyze_message
from app.core import notify

log = logging.getLogger(__name__)


def _with_contact(text: str, intent: str, tenant: str = "") -> str:
    """Chèn dòng liên hệ khẩn (SĐT/Zalo/Telegram CỦA SHOP sở hữu hội thoại) vào
    cuối câu trả lời NẾU shop đã bật cho intent này (xem notify.contact_for).
    CRM/notify lỗi thì trả nguyên text — không được làm chết luồng trả lời khách."""
    try:
        cfg = notify.get_config(tenant or None)   # multi-tenant: config của shop
        line = notify.contact_for(intent, cfg)
    except Exception:
        line = ""
    return f"{text}\n\n{line}" if line else text


def _notify_cfg(conv):
    """Config thông báo của SHOP sở hữu hội thoại (lỗi → None = mặc định)."""
    try:
        return notify.get_config(getattr(conv, "tenant", "") or None)
    except Exception:
        return None


FIRST_MESSAGE_GREETING = (
    "Admin bên shop có thể đang bận nên chưa rep được, "
    "để trợ lý AI tư vấn trước cho mình nhen 😊\n\n"
    "Mình có thể giúp bạn:\n"
    "📅 Xem lịch trống → nhắn \"tối nay còn phòng không\" hoặc \"ngày 25 còn phòng không\"\n"
    "💰 Xem bảng giá → nhắn \"bảng giá\"\n"
    "📸 Xem ảnh phòng → nhắn \"xin ảnh phòng\"\n"
    "🏠 Đặt phòng → nhắn \"đặt phòng tối nay\"\n\n"
    "Trợ lý AI do shop tự train nên còn một vài thiếu sót, mong bạn thông cảm nha 🙏 "
    "Mong bạn iu ghi rõ yêu cầu để AI hỗ trợ mình chính xác nhất có thể ạ.\n\n"
    "Bạn cần mình hỗ trợ gì ạ? 😊"
)


# ── Bộ từ khoá "hỏi lịch/phòng trống" — DÙNG CHUNG cho brain (override intent
# trên kênh thật) và Test Bot (prompt_api) để preview khớp production ──
DAY_KEYWORDS = [
    # Hôm nay
    "hôm nay", "ngày hôm nay", "hnay", "tnay", "t.nay",
    "tối nay", "tối này", "đêm nay", "đêm này",
    "chiều nay", "chiều này", "sáng nay", "sáng này", "trưa nay",
    # Ngày mai
    "ngày mai", "tối mai", "chiều mai", "sáng mai", "trưa mai",
    "hôm sau", "mai chiều", "mai tối", "mai sáng",
    # Mốt
    "ngày mốt", "ngày kia",
    # Thứ trong tuần
    "thứ 2", "thứ hai", "thứ 3", "thứ ba",
    "thứ 4", "thứ tư",  "thứ 5", "thứ năm",
    "thứ 6", "thứ sáu", "thứ 7", "thứ bảy",
    "chủ nhật", "cuối tuần", "tuần sau", "tuần tới",
    "tháng sau", "tháng tới",
    # Tiếng Anh phổ biến
    "tonight", "tomorrow",
]
AVAIL_KEYWORDS = [
    "còn phòng", "phòng trống", "còn trống", "có phòng", "còn chỗ",
    "có chỗ", "có chỗ trống", "chỗ trống",
    "đặt được", "book được", "trống không", "trống ko", "trống chưa",
    "còn ko", "còn không", "còn gì không", "còn gì ko",
    "check lịch", "xem lịch", "kiểm tra lịch", "lịch trống",
    "phòng nào trống", "ca nào trống", "ca nào còn", "kết quả", "check xong",
    "qua đêm", "ca đêm", "ca trưa", "ca chiều", "ca sáng",
    "slot", "available",
]


def mentions_availability(text_lower: str) -> bool:
    """Câu có ý 'hỏi phòng/lịch trống' không (chưa xét tới ngày)."""
    return any(k in text_lower for k in AVAIL_KEYWORDS) \
        or bool(re.search(r'còn.{0,30}(ko|không)\b', text_lower))


def _greeting_for(conv) -> str:
    """Greeting tin đầu THEO TENANT: shop GỐC giữ kịch bản homestay đầy đủ;
    shop thuê nhận bản trung tính (không 'còn phòng/đặt phòng' — shop nail/spa
    không bị chào lạc ngành ngay tin đầu tiên), chèn tên shop nếu có."""
    if _default_shop(conv):
        return FIRST_MESSAGE_GREETING
    name = ""
    try:
        from app.core.db import get_db
        t = getattr(conv, "tenant", "") or ""
        rows = get_db().query("SELECT homestay FROM users WHERE username=?", (t,))
        name = (rows[0]["homestay"] or "").strip() if rows else ""
    except Exception:
        pass
    shop = name or "shop"
    return (
        f"Chào bạn 👋 Trợ lý AI của {shop} đây ạ! Admin có thể đang bận nên em "
        "hỗ trợ mình trước nha 😊\n\n"
        "Bạn cứ nhắn điều mình cần — hỏi thông tin dịch vụ, báo giá, xem ảnh, "
        "đặt lịch/đặt hàng — em trả lời ngay ạ.\n\n"
        "Trợ lý AI do shop tự train nên còn vài thiếu sót, mong bạn thông cảm nha 🙏"
    )


def _default_shop(conv) -> bool:
    """Hội thoại thuộc SHOP GỐC (chủ nền tảng)? Chỉ shop gốc mới dùng kho media
    LEGACY (ảnh bảng giá/phòng trong media/) và map phòng cứng theo tên homestay.
    Shop thường dùng Thư viện ảnh + Google Sheet tự khai — tránh rò dữ liệu shop gốc."""
    try:
        from app.core import tenant as _tenant
        t = getattr(conv, "tenant", "") or ""
        return (not t) or t == _tenant.default_owner()
    except Exception:
        return True


def _infer_date_from_text(text: str):
    """
    Python fallback: suy ra ngày từ các từ chỉ thời gian tương đối trong tiếng Việt.
    Trả về chuỗi dd/mm/yyyy hoặc None nếu không tìm thấy.
    """
    tl = text.lower()
    now = _dt.now()

    today_kw = [
        "tối nay", "tối này", "đêm nay", "đêm này",
        "chiều nay", "chiều này",
        "sáng nay", "sáng này",
        "trưa nay", "trưa này",
        "hôm nay", "ngày hôm nay",
        "hnay", "h.nay", "tnay", "t.nay",
    ]
    tomorrow_kw = [
        "ngày mai", "tối mai", "chiều mai", "sáng mai", "trưa mai",
        "đêm mai", "hôm sau", "ngày hôm sau",
        "mn ",   # viết tắt "mai nhé/ngày mai" phổ biến trong chat
    ]
    d2_kw = ["ngày mốt", "ngày kia"]

    if any(k in tl for k in today_kw):
        return now.strftime("%d/%m/%Y")
    if any(k in tl for k in tomorrow_kw) or (tl.strip() == "mn") or re.search(r'\bmai\b', tl):
        return (now + _td(days=1)).strftime("%d/%m/%Y")
    if any(k in tl for k in d2_kw):
        return (now + _td(days=2)).strftime("%d/%m/%Y")

    # "thứ X tuần sau / tuần tới" — tính ngày thứ X của tuần sau
    if any(k in tl for k in ["tuần sau", "tuần tới", "tuần toi"]):
        weekday_aliases = [
            (["thứ 2", "thứ hai", r"\bt2\b"], 0),
            (["thứ 3", "thứ ba",  r"\bt3\b"], 1),
            (["thứ 4", "thứ tư",  r"\bt4\b"], 2),
            (["thứ 5", "thứ năm", r"\bt5\b"], 3),
            (["thứ 6", "thứ sáu", r"\bt6\b"], 4),
            (["thứ 7", "thứ bảy", r"\bt7\b"], 5),
            (["chủ nhật", r"\bcn\b"],          6),
        ]
        today_wd = now.weekday()  # Monday=0, Sunday=6
        # Tìm thứ mấy được nhắc đến (hỗ trợ cả chuỗi thường lẫn regex \b...\b)
        for aliases, target_wd in weekday_aliases:
            if any((re.search(a, tl) if a.startswith(r'\b') else a in tl) for a in aliases):
                # Tính số ngày đến thứ đó trong tuần sau (bắt đầu từ Thứ 2)
                days_to_next_monday = (7 - today_wd) % 7
                if days_to_next_monday == 0:
                    days_to_next_monday = 7  # Nếu hôm nay là Thứ 2 → tuần sau bắt đầu +7
                next_monday = now + _td(days=days_to_next_monday)
                target_date = next_monday + _td(days=target_wd)
                return target_date.strftime("%d/%m/%Y")

    return None


def apply_intent_overrides(text: str, ai_result: dict, conv_snapshot: dict):
    """
    LỚP OVERRIDE INTENT bằng Python thuần (keyword/regex tiếng Việt) đè lên kết quả AI —
    AI hay trả "other" cho câu tiếng Việt đời thường ("tối nay còn phòng ko") nên cần
    lưới an toàn tất định này.

    HÀM THUẦN cấp module: input là DỮ LIỆU THUẦN, KHÔNG đụng self/channel/side-effect
    → test trực tiếp được (tests/test_intent.py chấm đúng code production, hết drift).
      - text          : tin nhắn khách (nguyên bản, chưa lower)
      - ai_result     : dict kết quả analyze_message (dùng intent + use_ai_reply)
      - conv_snapshot : trạng thái hội thoại thuần {"stage", "checkin", "selected_room"}
                        (checkin đã gộp giá trị AI vừa extract — caller set trước)

    Trả (intent_sau_override, danh_sách_lý_do) — caller log lý do, giữ nguyên log cũ.
    """
    intent       = ai_result.get("intent", "other")
    use_ai_reply = ai_result.get("use_ai_reply", False)
    stage        = conv_snapshot.get("stage") or ""
    checkin      = conv_snapshot.get("checkin")
    reasons: list = []

    tl_check = text.lower()
    # Từ khoá ĐẶC THÙ SHOP GỐC (số phòng 3 chữ số, tên homestay Haru/Mochi) chỉ
    # được override cho shop gốc — khách shop thuê nhắn "301" (mã SP/số lượng)
    # từng bị ép photo_request lạc đề. is_default mặc định True (tương thích
    # caller/test cũ chưa truyền).
    is_default = conv_snapshot.get("is_default", True)
    _has_room  = is_default and bool(re.search(r'\b[123]\d{2}\b', text))
    _has_home  = is_default and any(k in tl_check for k in ["haru", "mochi", "staycation"])

    # ── Override availability_check (bộ từ khoá module-level DAY_KEYWORDS/
    # AVAIL_KEYWORDS — Test Bot dùng chung để preview khớp production) ──
    _has_day   = any(k in tl_check for k in DAY_KEYWORDS)
    # Viết tắt thứ: t2-t7, cn
    if not _has_day:
        _has_day = bool(re.search(r'\bt[2-7]\b|\bcn\b', tl_check))
    # "mai" đứng độc lập (không nằm trong "ngày mai" đã bắt ở trên)
    if not _has_day:
        _has_day = bool(re.search(r'\bmai\b', tl_check))
    # Viết tắt: "mn" = mai nhé / ngày mai
    if not _has_day:
        _has_day = bool(re.search(r'\bmn\b', tl_check))
    # Ngày cụ thể: "ngày 25", "25/5", "25 tháng 5"
    if not _has_day:
        _has_day = bool(re.search(
            r'ngày\s+\d+|\d{1,2}[/\.]\d{1,2}|\d{1,2}\s+tháng\s+\d+',
            tl_check
        ))
    # (gồm cả "còn...ko/không" cách nhau — vd "còn p qua đêm tối nay ko")
    _has_avail = mentions_availability(tl_check)

    if intent == "other" and not use_ai_reply:
        # Case 1: nêu ngày + hỏi phòng
        if _has_day and _has_avail:
            reasons.append("[Intent] Override → availability_check (ngày + hỏi phòng)")
            intent = "availability_check"
        # Case 2: chỉ hỏi phòng (đã có ngày trong conv)
        elif _has_avail and checkin:
            reasons.append("[Intent] Override → availability_check (hỏi phòng, có checkin sẵn)")
            intent = "availability_check"
        # Case 3: tin nhắn CHỈ là cụm ngày tháng (trả lời "ngày nào?")
        elif _has_day and len(text.strip().split()) <= 5:
            reasons.append("[Intent] Override → availability_check (chỉ nêu ngày)")
            intent = "availability_check"
        # Case 4: nêu ngày trong flow đang hỏi lịch
        elif _has_day and stage in ("checking", "offering"):
            reasons.append("[Intent] Override → availability_check (nêu ngày trong flow lịch)")
            intent = "availability_check"
        # Case 5: câu ngắn mơ hồ trong flow đang hỏi lịch
        elif stage in ("checking", "offering") and checkin:
            # Không override nếu câu là câu hỏi thông tin (khác/giống/địa điểm/...)
            _info_question = any(k in tl_check for k in [
                "khác nhau", "giống nhau", "địa điểm", "như thế nào", "thế nào ạ",
                "là gì", "ở đâu", "tại sao", "vì sao", "nghĩa là",
                "có gì", "có những gì", "cho mình biết", "cho em biết",
                "hỏi thêm", "hỏi tí", "hỏi chút",
            ])
            _followup_kw = [
                "cả 2", "cả hai", "2 căn", "2 cái", "cả 2 luôn",
                "cho mình", "đặt đi",
                "xong chưa", "check xong", "kết quả",
                "hôm đó", "ngày đó",
            ]
            # "ok/oke/okie/được" cần word-boundary để không match trong "book", "được rồi..."
            _followup_re = bool(re.search(r'\bok\b|\boke\b|\bokie\b|\bđược\b', tl_check))
            if not _info_question and (any(k in tl_check for k in _followup_kw) or _followup_re):
                reasons.append("[Intent] Override → availability_check (follow-up flow lịch)")
                intent = "availability_check"

    # ── Override contact_request (luôn chạy dù use_ai_reply=True — liên hệ chủ là ưu tiên cao nhất) ──
    _contact_kw = [
        "gọi chủ", "kêu chủ", "báo chủ", "nhắn chủ", "bảo chủ",
        "gặp chủ", "cho gặp", "gặp người thật", "nói chuyện thật",
        "chủ đâu", "admin đâu", "chủ nhà đâu", "có ai không",
        "rep đi", "rep mình", "trả lời đi", "ai đó rep",
        "gọi lại", "gọi cho mình", "gọi mình",
        "liên hệ lại", "liên hệ trực tiếp", "liên hệ mình",
        "không muốn chat bot", "cần người thật", "người thật",
        "khi nào chủ", "chủ online",
        "gặp admin", "tìm admin", "nhắn admin", "hỏi admin",
        "muốn gặp chủ", "muốn gặp admin", "cần gặp chủ", "cần gặp admin",
    ]
    if intent != "contact_request" and any(k in tl_check for k in _contact_kw):
        # Loại false positive: "gọi mình là [tên]" — người đang tự giới thiệu
        if not re.search(r'gọi (mình|tôi|tao|em|anh|chị) là', tl_check):
            reasons.append(f"[Intent] Override → contact_request (was: {intent})")
            intent = "contact_request"
    # Regex bổ sung: "muốn/cần gặp chủ/admin" dưới nhiều hình thức
    if intent != "contact_request" and re.search(
        r'(muốn|cần|cho).{0,10}gặp.{0,10}(chủ|admin|người)', tl_check
    ):
        reasons.append("[Intent] Override → contact_request (regex muốn/cần gặp)")
        intent = "contact_request"

    # ── Override price_list_request ──
    _price_kw = [
        "bảng giá", "giá phòng", "giá bao nhiêu", "bao nhiêu tiền",
        "giá như nào", "giá thế nào", "phòng mấy tiền", "mấy tiền",
        "bao nhiêu 1 đêm", "bao nhiêu 1 ca", "giá 1 đêm",
        "cho xin giá", "giá các phòng", "giá hết", "giá là",
        "tính giá", "giá thuê",
        "xem giá", "cho mình giá", "giá ca ",
        "rẻ nhất", "đắt nhất", "phòng rẻ", "phòng đắt",
        "giá haru", "giá mochi", "giá staycation",
    ]
    if intent != "price_list_request" and any(k in tl_check for k in _price_kw):
        # Loại false positive: hỏi giá đồ/dịch vụ không liên quan phòng
        _not_room_ctx = any(k in tl_check for k in ["xe máy", "xe đạp", "grab", "shipper", "đồ ăn", "cơm", "nước"])
        if not _not_room_ctx:
            reasons.append(f"[Intent] Override → price_list_request (was: {intent})")
            intent = "price_list_request"
    # Regex: "giá ... bao nhiêu/thế nào/như nào" (cách nhau vài từ)
    if intent != "price_list_request" and re.search(
        r'giá.{0,25}(bao nhiêu|thế nào|như nào|ra sao)', tl_check
    ):
        reasons.append("[Intent] Override → price_list_request (regex giá+bao nhiêu)")
        intent = "price_list_request"

    # ── Override photo_request: có từ khóa ảnh + (số phòng hoặc tên homestay) ──
    _has_photo = any(k in tl_check for k in [
        "ảnh", "hình", "xem phòng", "xem của", "xem hết",
        "tất cả các phòng", "show", "cho xem",
    ])
    if intent != "photo_request" and (_has_room or _has_home) and _has_photo:
        reasons.append("[Intent] Override → photo_request (has photo keyword + room/home)")
        intent = "photo_request"

    # ── Override photo_request: "ảnh phòng", "xem hết", v.v. (không cần số phòng) ──
    _has_photo_generic = any(k in tl_check for k in [
        "ảnh phòng", "hình phòng",
        "ảnh các phòng", "hình các phòng",
        "ảnh tất cả", "xem tất cả", "tất cả các phòng", "mọi phòng",
        "xem hết", "show all",
    ])
    if intent != "photo_request" and _has_photo_generic:
        reasons.append("[Intent] Override → photo_request (generic photo phrase)")
        intent = "photo_request"

    # ── Override photo_request: số phòng + từ xác nhận tùy chọn ──
    if intent not in ("photo_request", "booking_confirm", "availability_check", "contact_request"):
        _only_rooms = bool(re.fullmatch(
            r'[\s]*(?:[123]\d{2}[\s,、và\+&]*)+[\s]*(đi|nhé|nha|luôn|thôi|đó|ạ)?[\s]*',
            text.strip(), re.IGNORECASE
        ))
        if _only_rooms and _has_room:
            reasons.append(f"[Intent] Override → photo_request (số phòng + xác nhận: '{text.strip()}')")
            intent = "photo_request"

    # ── Override photo_request: "X thì sao" / "bên X" follow-up ảnh ──
    if intent not in ("photo_request", "booking_confirm", "availability_check", "contact_request"):
        _photo_followup_re = re.search(
            r'(haru|mochi|staycation).{0,10}(thì sao|thế nào|như nào|thế|sao)\b'
            r'|(còn bên|bên kia|bên (haru|mochi|staycation)|homestay kia).{0,15}',
            tl_check
        )
        if _photo_followup_re and _has_home:
            reasons.append(f"[Intent] Override → photo_request (follow-up ảnh homestay: '{text.strip()}')")
            intent = "photo_request"

    return intent, reasons


class Brain:
    """Logic xử lý tin nhắn, dùng chung cho mọi kênh."""

    # TÓM TẮT CUỘN: vượt ngưỡng tin chưa tóm → AI gộp phần cũ thành vài dòng
    SUMMARY_TRIGGER = 26   # số tin chưa-tóm tối thiểu mới kích hoạt (26 > cửa sổ 20)
    SUMMARY_KEEP    = 12   # số tin mới nhất GIỮ THÔ (không tóm) cho ngữ cảnh tươi

    # Trần số khoá per-user giữ trong RAM (LRU) — đủ lớn cho lượng khách đồng thời,
    # không phình vô hạn theo tổng khách.
    _MAX_USER_LOCKS = 4096

    def __init__(self, channel: Channel, conv_manager: ConversationManager):
        self.channel = channel
        self.conv_manager = conv_manager
        self._summarizing: set = set()   # user_id đang tóm nền — chống chạy chồng
        # KHOÁ THEO TỪNG KHÁCH: 2 tin của CÙNG 1 khách (khách hay nhắn dồn 2-3 tin
        # liên tiếp) phải xử lý TUẦN TỰ, không để 2 thread pool cùng mutate
        # ConversationState → tránh double-greeting, history lệch, đơn nháp trùng.
        self._user_locks: "OrderedDict[str, threading.Lock]" = OrderedDict()
        self._user_locks_guard = threading.Lock()

    def _lock_for(self, user_id: str) -> threading.Lock:
        """Lấy (hoặc tạo) khoá riêng cho 1 khách. LRU có trần — bỏ khoá cũ nhất
        KHÔNG đang được giữ để không phình bộ nhớ."""
        with self._user_locks_guard:
            lk = self._user_locks.get(user_id)
            if lk is None:
                lk = threading.Lock()
                self._user_locks[user_id] = lk
            else:
                self._user_locks.move_to_end(user_id)
            if len(self._user_locks) > self._MAX_USER_LOCKS:
                for old_uid, old_lk in list(self._user_locks.items()):
                    if old_lk.locked():
                        continue          # đang dùng → giữ lại
                    del self._user_locks[old_uid]
                    if len(self._user_locks) <= self._MAX_USER_LOCKS:
                        break
            return lk

    # ------------------------------------------------------------------ #

    def handle(self, user_id: str, text: str):
        """Xử lý 1 tin nhắn từ khách, rồi (nền) cập nhật tóm tắt cuộn nếu hội
        thoại đã dài — chạy SAU khi khách nhận trả lời nên không thêm độ trễ.
        Toàn bộ chạy trong khoá per-user → tin cùng khách không xử lý chồng nhau."""
        with self._lock_for(user_id):
            try:
                self._handle_inner(user_id, text)
            finally:
                try:
                    self._maybe_summarize(user_id)
                except Exception as e:
                    log.warning(f"[Summary] hook lỗi (bỏ qua): {e}")

    def _maybe_summarize(self, user_id: str):
        """Đủ tin chưa-tóm → thread nền gộp tóm tắt cũ + tin cũ thành tóm tắt mới.
        Khách vẫn được trả lời bình thường dù tóm tắt lỗi/chậm."""
        conv = self.conv_manager.get(user_id)
        pending = len(conv.messages) - conv.summary_upto
        if pending < self.SUMMARY_TRIGGER or user_id in self._summarizing:
            return
        cut = len(conv.messages) - self.SUMMARY_KEEP
        if cut <= conv.summary_upto:
            return
        segment = list(conv.messages[conv.summary_upto:cut])
        old_summary = conv.summary
        account = getattr(self.conv_manager, "_account", "") or ""
        self._summarizing.add(user_id)

        def _run():
            try:
                from app.core.claude_ai import (summarize_history,
                                                _owner_of_shop, _resolve_shop)
                owner = _owner_of_shop(_resolve_shop(user_id, account))
                new_summary = summarize_history(old_summary, segment,
                                                owner=owner, account=account)
                if new_summary and new_summary != old_summary:
                    c = self.conv_manager.get(user_id)
                    c.summary = new_summary
                    c.summary_upto = cut
                    self.conv_manager.save()
                    log.info(f"[Summary] {user_id}: tóm {len(segment)} tin cũ "
                             f"(upto={cut}, {len(new_summary)} ký tự)")
            except Exception as e:
                log.warning(f"[Summary] {user_id} lỗi: {e}")
            finally:
                self._summarizing.discard(user_id)

        threading.Thread(target=_run, daemon=True,
                         name=f"summary-{user_id[:20]}").start()

    def _say(self, user_id: str, conv, text: str):
        """Gửi text cho khách + ghi vào history — cặp thao tác luôn đi đôi (~15 chỗ)."""
        self.channel.send_text(user_id, text)
        conv.add_assistant_message(text)

    def _analyze(self, user_id: str, conv, text: str) -> dict:
        """Gửi cho AI phân tích (không bao gồm tin nhắn vừa thêm).
        user_id + account để AI đọc TRÍ NHỚ VỀ KHÁCH (CRM) → cá nhân hoá.
        history_for_ai: tin đã nằm trong TÓM TẮT CUỘN không gửi thô lại;
        conv_state: trạng thái + tóm tắt + intent lượt trước (style RAG)."""
        return analyze_message(text, conv.history_for_ai(n=20)[:-1],
                               user_id=user_id,
                               account=getattr(self.conv_manager, "_account", "") or "",
                               conv_state={
                                   "stage": conv.stage,
                                   "checkin": conv.checkin,
                                   "checkout": conv.checkout,
                                   "selected_room": conv.selected_room,
                                   "summary": conv.summary,
                                   "intent": conv.last_intent,
                               })

    def _handle_inner(self, user_id: str, text: str):
        """
        DISPATCHER: xử lý 1 tin nhắn từ khách — phân tích AI → override intent →
        giao cho handler theo intent. Logic từng nhánh nằm ở các _handle_* bên dưới.
        text == "" nghĩa là sticker/media không có text (kênh chỉ gọi khi là khách mới).
        """
        conv = self.conv_manager.get(user_id)
        is_first_message = len(conv.messages) == 0  # Kiểm tra trước khi add

        # Sticker / media không có text → chỉ đến đây nếu là khách mới
        if not text:
            self._handle_sticker_new_user(user_id, conv)
            return

        conv.add_user_message(text)

        result = self._analyze(user_id, conv, text)

        intent        = result.get("intent", "other")
        conv.last_intent = intent
        checkin       = result.get("checkin")  or conv.checkin
        checkout      = result.get("checkout") or conv.checkout
        reply         = result.get("reply", "")
        confirmed     = result.get("booking_confirmed", False)
        use_ai_reply  = result.get("use_ai_reply", False)  # AI tự trả lời, bỏ qua override

        log.info(f"[Intent] {intent}")

        if checkin:
            conv.checkin = checkin
        if checkout:
            conv.checkout = checkout

        if use_ai_reply:
            log.info(f"[Intent] AI use_ai_reply=True → tin tưởng AI, bỏ qua Python override")

        # ── Lớp override intent (hàm thuần — tests/test_intent.py chấm trực tiếp) ──
        intent, _ov_reasons = apply_intent_overrides(text, result, {
            "stage": conv.stage,
            "checkin": conv.checkin,
            "selected_room": conv.selected_room,
            "is_default": _default_shop(conv),
        })
        for _r in _ov_reasons:
            log.info(_r)

        # ── AI tự trả lời: use_ai_reply=True + intent vẫn là "other" sau override ──
        # Contact_request và photo override (số phòng / homestay) vẫn được phép chạy;
        # chỉ các override availability/price bị bỏ khi AI đã tự tin với câu trả lời.
        if use_ai_reply and intent == "other":
            log.info("[Intent] AI use_ai_reply=True, intent=other → dùng reply của AI")
            if reply:
                self._say(user_id, conv, reply)
            else:
                self._ask_clarify(user_id, conv)   # AI tự tin nhưng rỗng → hỏi lại, đừng câm
            return

        # ── Câu đầu tiên với mỗi khách mới → LUÔN gửi greeting + bảng giá ──
        if is_first_message and self._handle_first_message(user_id, conv, intent):
            return
            # (greeting chưa đủ → tiếp tục xử lý intent cụ thể bên dưới)

        # ── Thư viện ảnh: khách hỏi trúng TÊN/keywords bộ ảnh shop tự đặt ──
        if intent in ("photo_request", "price_list_request") and \
           self._try_photo_library(user_id, conv, text):
            return

        if intent == "price_list_request":
            self._handle_price(user_id, conv, reply)
            return

        if intent == "photo_request":
            self._handle_photo(user_id, conv, text, result, reply)
            return

        if intent == "availability_check":
            self._handle_availability(user_id, conv, text)
            return

        if intent == "reschedule_request":
            self._handle_reschedule(user_id, conv, text, reply)
            return

        if intent == "unknown_question":
            self._handle_unknown(user_id, conv, text, reply)
            return

        if intent == "contact_request":
            self._handle_contact(user_id, conv, text)
            return

        # Khi khách chốt đặt phòng
        if confirmed:
            self._handle_confirmed(user_id, conv, text, reply)
            return

        # Trả lời thông thường
        if reply:
            self._say(user_id, conv, reply)
        else:
            # CLARIFY: không nhánh nào khớp VÀ AI không đưa được câu trả lời → HỎI LẠI
            # thay vì im lặng (câm hay đoán bừa đều mất niềm tin). Nấc "agentic" đáng
            # giá nhất cho luồng chat: giảm trả lời sai bằng cách chủ động làm rõ ý.
            self._ask_clarify(user_id, conv)

        # Lưu lại sau mỗi lần xử lý tin nhắn
        self.conv_manager.save()

    # ── Các handler theo intent (tách từ _handle_inner — hành vi giữ NGUYÊN) ── #

    def _handle_sticker_new_user(self, user_id: str, conv):
        """Sticker/media không text từ KHÁCH MỚI → greeting (+ bảng giá shop gốc)."""
        log.info(f"[Handle] Sticker từ khách mới {user_id} → gửi greeting")
        greeting = _with_contact(_greeting_for(conv), "greeting", getattr(conv, "tenant", ""))
        self._say(user_id, conv, greeting)
        if _default_shop(conv):   # ảnh bảng giá legacy CHỈ của shop gốc
            time.sleep(0.5)
            self.channel.send_price_photos(user_id)

    def _handle_first_message(self, user_id: str, conv, intent: str) -> bool:
        """Câu đầu tiên với khách mới → LUÔN gửi greeting (+ bảng giá shop gốc).
        Trả True nếu greeting là ĐỦ (dừng xử lý); False → còn intent cụ thể,
        dispatcher tiếp tục gửi thêm câu trả lời thực."""
        log.info(f"[FirstMsg] Gửi greeting cố định cho user {user_id}")
        greeting = _with_contact(_greeting_for(conv), "greeting", getattr(conv, "tenant", ""))
        self._say(user_id, conv, greeting)
        if _default_shop(conv):
            # Shop gốc: kèm ảnh bảng giá legacy như trước
            time.sleep(0.5)
            self.channel.send_price_photos(user_id)
            time.sleep(0.5)
            if intent in ("other", "price_list_request"):
                return True  # Greeting + bảng giá là đủ (bảng giá đã gửi rồi, không gửi lại)
        else:
            # Shop thường: bảng giá lấy từ Thư viện ảnh (handler dưới) — không rò media shop gốc
            if intent == "other":
                return True  # Greeting là đủ
        return False

    def _try_photo_library(self, user_id: str, conv, text: str) -> bool:
        """Thư viện ảnh: khách hỏi trúng TÊN/keywords bộ ảnh shop tự đặt
        (shop upload trong web → media/photo_library). Match được → gửi bộ đó,
        trả True; không match / kênh chưa hỗ trợ → False, rơi xuống cơ chế cũ y nguyên."""
        from app.core import photo_library
        # multi-tenant: chỉ tìm trong bộ ảnh của SHOP sở hữu hội thoại
        matched = photo_library.find_sets(
            text, tenant_ws=getattr(conv, "tenant", "") or None)
        if not matched:
            return False
        sent_any = False
        for s in matched:
            if self.channel.send_photo_folder(
                    user_id, photo_library.set_dir(s["slug"]), f"📸 {s['name']}:"):
                sent_any = True
        if not sent_any:
            return False
        names = ", ".join(s["name"] for s in matched)
        self._say(user_id, conv, f"Đây là ảnh {names} bạn nhé! 📸")
        log.info(f"[PhotoLib] gửi bộ ảnh: {names}")
        return True

    def _handle_price(self, user_id: str, conv, reply: str):
        """Khách xin bảng giá."""
        if not _default_shop(conv):
            # Shop thường chưa có bộ ảnh "bảng giá" match ở trên → trả lời bằng AI
            # (giá nằm trong não đã train), tuyệt đối không gửi bảng giá shop gốc
            fallback = reply or ("Bạn chờ mình chút nha, mình gửi thông tin giá ngay! "
                                 "Bạn muốn xem giá dịch vụ nào ạ? 😊")
            self._say(user_id, conv, fallback)
            return
        if reply:
            self._say(user_id, conv, reply)
        time.sleep(0.5)
        self.channel.send_price_photos(user_id)

    def _handle_photo(self, user_id: str, conv, text: str, result: dict, reply: str):
        """Khách xin ảnh phòng — quy trình 5 bước tìm số phòng rồi gửi ảnh."""
        if not _default_shop(conv):
            # Shop thường: ảnh lấy từ Thư viện ảnh (đã thử match ở trên, không trúng)
            # → không đụng kho media/map phòng legacy của shop gốc
            fallback = reply or ("Bạn muốn xem ảnh phần nào để mình gửi đúng bộ ạ? 📸 "
                                 "(shop sẽ bổ sung thêm ảnh nếu chưa có nha)")
            self._say(user_id, conv, fallback)
            return
        # ── Bước 1: Regex tìm TẤT CẢ số phòng trong tin nhắn (nguồn chính) ──
        rooms_from_text = list(dict.fromkeys(re.findall(r'\b([123]\d{2})\b', text)))

        # ── Bước 2: AI gợi ý thêm (room_numbers là array hoặc room_number string) ──
        ai_rooms_raw = result.get("room_numbers") or []
        if not ai_rooms_raw and result.get("room_number"):
            ai_rooms_raw = [str(result["room_number"])]
        ai_rooms = [str(r).strip() for r in ai_rooms_raw if str(r).strip()]

        # ── Bước 3: Gộp, ưu tiên regex ──
        room_numbers = rooms_from_text or ai_rooms  # regex thắng nếu có

        # ── Bước 4: Nhận biết theo tên homestay nếu chưa có số phòng ──
        tl = text.lower()
        if not room_numbers:
            if any(k in tl for k in ["haru", "staycation"]) and \
               not any(k in tl for k in ["mochi"]):
                room_numbers = ["201", "202", "301"]
                log.info("[Photo] Nhận biết Haru → 201,202,301")
            elif any(k in tl for k in ["mochi"]) and \
                 not any(k in tl for k in ["haru", "staycation"]):
                room_numbers = ["111", "112", "211", "212", "311"]
                log.info("[Photo] Nhận biết Mochi → 111,112,211,212,311")

        # ── Bước 5: Kiểm tra "tất cả" nếu vẫn không tìm được số phòng nào ──
        all_keywords = ["tất cả", "tất ca", "hết", "all", "các phòng", "mọi phòng"]
        wants_all = (not room_numbers and
                     any(kw in tl for kw in all_keywords))

        log.info(f"[Photo] room_numbers={room_numbers} wants_all={wants_all}")

        if room_numbers:
            # Gửi ảnh các phòng được chỉ định
            if len(room_numbers) == 1:
                fixed_reply = f"Đây là ảnh phòng {room_numbers[0]} bạn nhé! 📸"
            else:
                joined = ", ".join(room_numbers[:-1]) + f" và {room_numbers[-1]}"
                fixed_reply = f"Đây là ảnh phòng {joined} bạn nhé! 📸"
            self._say(user_id, conv, fixed_reply)
            time.sleep(0.5)
            self.channel.send_room_photos(user_id, [f"Phòng {r}" for r in room_numbers])

        elif wants_all:
            # Gửi ảnh tất cả phòng trong thư mục rooms_photos
            base_dir = Path(Config.ROOMS_PHOTOS_DIR)
            all_rooms = sorted([
                f.name for f in base_dir.iterdir()
                if f.is_dir() and re.match(r'^\d{3}$', f.name)
            ]) if base_dir.exists() else []
            if all_rooms:
                self._say(user_id, conv, "Đây là ảnh tất cả các phòng bạn nhé! 📸")
                time.sleep(0.5)
                self.channel.send_room_photos(user_id, [f"Phòng {r}" for r in all_rooms])
            else:
                if reply:
                    self._say(user_id, conv, reply)
        else:
            # Không rõ phòng nào → AI hỏi lại
            if reply:
                self._say(user_id, conv, reply)

    def _handle_availability(self, user_id: str, conv, text: str):
        """Khách hỏi lịch/phòng trống: infer ngày nếu thiếu → hỏi ngày hoặc tra Sheets."""
        # ── Python fallback infer ngày nếu AI chưa extract được ──
        if not conv.checkin:
            inferred = _infer_date_from_text(text)
            if inferred:
                conv.checkin  = inferred
                conv.checkout = inferred
                log.info(f"[Date] Inferred từ context: {inferred}")

        # ── Chỉ có checkin → checkout = cùng ngày ──
        if conv.checkin and not conv.checkout:
            conv.checkout = conv.checkin

        # ── Không có ngày nào cả → hỏi thẳng, không dùng AI reply ──
        if not conv.checkin:
            self._say(user_id, conv, "Bạn muốn kiểm tra lịch ngày nào ạ? 📅")
            return

        # Đủ ngày → check sheets
        self._send_availability_result(user_id, conv, text)

    def _send_availability_result(self, user_id: str, conv, text: str):
        """Tra Google Sheets và trả kết quả lịch trống — fail-closed khi lỗi/thiếu sheet."""
        conv.stage = "checking"
        log.info(f"[Sheets] Kiểm tra lịch: {conv.checkin} → {conv.checkout}")
        context = format_availability_for_ai(conv.checkin, conv.checkout,
                                             tenant=getattr(conv, "tenant", "") or None)
        log.info(f"[Sheets] Kết quả:\n{context}")

        # ĐỌC SHEET LỖI (mạng/quota/permission) → KHÔNG tự nói "còn phòng":
        # báo khách đang kiểm tra + nhờ chủ xác nhận (fail-closed, chống hứa
        # nhầm phòng khi thực tế đã kín).
        if "[LOI_DOC_SHEET]" in context:
            conv.stage = "offering"
            self._say(user_id, conv, (
                f"Mình đang tra lịch ngày {conv.checkin} nhưng hệ thống lịch đang "
                f"trục trặc kết nối một chút 🙏\n"
                f"Mình đã báo chủ shop kiểm tra và xác nhận lại với bạn sớm nhất nha!"
            ))
            self.channel.notify_owner(
                f"⚠️ KHÔNG ĐỌC ĐƯỢC LỊCH khi khách hỏi ngày {conv.checkin}\n\n"
                f"👤 ID khách: {user_id}\n💬 Tin nhắn: \"{text[:200]}\"\n\n"
                f"Bot KHÔNG tự trả 'còn/hết phòng' để tránh sai. Vui lòng kiểm tra "
                f"Google Sheet (quyền chia sẻ / quota) rồi xác nhận với khách nhé!"
            )
            self.conv_manager.save()
            return

        # Shop chưa nối Google Sheet nào → không bịa lịch: ghi nhận + báo chủ
        if "[KHONG_CO_SHEET]" in context:
            conv.stage = "offering"
            self._say(user_id, conv, (
                f"Mình đã ghi nhận bạn muốn ngày {conv.checkin} rồi nha! 📅\n"
                f"Chủ shop sẽ kiểm tra lịch trống và xác nhận lại với bạn sớm nhất 😊"
            ))
            self.channel.notify_owner(
                f"📅 KHÁCH HỎI LỊCH {conv.checkin}\n\n"
                f"👤 ID khách: {user_id}\n💬 Tin nhắn: \"{text[:200]}\"\n\n"
                f"Shop chưa kết nối Google Sheet lịch — vào Cài đặt ▸ Lịch đặt chỗ "
                f"để bot tự tra lịch cho khách nhé!"
            )
            self.conv_manager.save()
            return

        # Gửi thẳng dữ liệu sheet — không qua AI để tránh hallucination
        conv.stage = "offering"

        if "[CHUA_CO_LICH]" in context:
            # Ngày tương lai chưa có booking nào → có thể đặt được
            reply = (
                f"Ngày {conv.checkin} hệ thống chưa ghi nhận booking nào — "
                f"các phòng vẫn còn trống bạn ơi! 😊\n\n"
                f"Bạn muốn đặt phòng nào và ca nào thì báo mình nhé, "
                f"chủ nhà sẽ xác nhận và hướng dẫn đặt cọc cho bạn!"
            )
        elif "KHÔNG có ca trống" in context or "NGHIÊM CẤM" in context:
            # Ngày có trong sheet nhưng đã đặt hết — gợi ý ngày mai
            try:
                checkin_date = _dt.strptime(conv.checkin, "%d/%m/%Y")
                tomorrow_str = (checkin_date + _td(days=1)).strftime("%d/%m/%Y")
                reply = (
                    f"Dạ mình kiểm tra rồi, ngày {conv.checkin} không còn ca trống nào bạn ơi 😢\n\n"
                    f"Bạn có muốn xem lịch ngày mai ({tomorrow_str}) không?"
                )
            except Exception:
                reply = f"Dạ ngày {conv.checkin} không còn ca trống nào bạn ơi 😢 Bạn thử ngày khác nhé!"
        else:
            reply = f"Dạ, mình kiểm tra cho bạn nè! 😊\n\n{context}\n\nBạn muốn đặt phòng nào thì báo mình nhé!"

        self._say(user_id, conv, reply)

        # Thêm note vào history để AI nhớ đúng trạng thái phòng cho các tin sau
        if "[CHUA_CO_LICH]" in context:
            conv.add_user_message(
                f"[HỆ THỐNG] Ngày {conv.checkin}: chưa có booking nào trong Google Sheets. "
                f"Tất cả các phòng của cả hai chi nhánh đều có thể đặt được. "
                f"Hãy tư vấn khách chọn phòng và ca phù hợp."
            )
            conv.add_assistant_message(
                "Đã ghi nhận: ngày này chưa có booking, tất cả phòng còn trống. "
                "Sẽ tư vấn khách chọn phòng và ca."
            )
        else:
            conv.add_user_message(
                f"[HỆ THỐNG] Dữ liệu phòng trống đã xác nhận từ Google Sheets:\n{context}\n"
                f"Chỉ được tư vấn theo danh sách này. Phòng không có trong danh sách = đã đặt hết."
            )
            conv.add_assistant_message(
                "Đã ghi nhận dữ liệu phòng trống. Tôi sẽ chỉ tư vấn theo danh sách thực tế trên."
            )

    def _handle_reschedule(self, user_id: str, conv, text: str, reply: str):
        """Khách muốn đổi/dời khung giờ — bot không tự quyết, báo chủ."""
        fixed = reply if reply else (
            "Việc đổi ca/khung giờ mình không tự quyết định được bạn ơi, "
            "để mình hỏi anh chủ giúp bạn nhé! "
            "Bạn còn cần hỏi thêm gì không ạ? 😊"
        )
        self._say(user_id, conv, fixed)
        self.channel.notify_owner(
            f"🔄 KHÁCH MUỐN ĐỔI KHUNG GIỜ\n\n"
            f"👤 ID khách: {user_id}\n"
            f"💬 Yêu cầu: \"{text[:200]}\"\n\n"
            f"Vui lòng xác nhận và liên hệ lại khách nhé!"
        )
        self.conv_manager.save()

    def _handle_unknown(self, user_id: str, conv, text: str, reply: str):
        """Khách hỏi điều bot không có thông tin — trấn an + báo chủ + ghi sổ câu bí."""
        fixed = reply if reply else (
            "Câu này mình chưa có thông tin để trả lời bạn ơi 😅 "
            "Mình đã báo chủ nhà rồi, chủ nhà sẽ phản hồi bạn sớm nhé! "
            "Bạn còn câu hỏi gì khác không ạ? 😊"
        )
        fixed = _with_contact(fixed, "unknown_question", getattr(conv, "tenant", ""))   # bot bí → đưa số nếu bật
        self._say(user_id, conv, fixed)
        # Báo chủ theo cấu hình (mặc định chỉ nhắn tin, không gọi)
        unknown_msg = (
            f"❓ KHÁCH HỎI CHƯA TRẢ LỜI ĐƯỢC\n\n"
            f"👤 ID khách: {user_id}\n"
            f"💬 Câu hỏi: \"{text[:200]}\"\n\n"
            f"Bot chưa có thông tin để trả lời — chủ nhà vui lòng phản hồi khách nhé!"
        )
        notify.alert(self.channel, "unknown", unknown_msg, cfg=_notify_cfg(conv))
        # Ghi sổ CÂU BOT BÍ → "Báo cáo não bot" trên trang Dạy AI gom theo tuần,
        # chủ bổ sung tri thức 1 chạm. Best-effort — không được chết luồng trả lời.
        try:
            from app.core.db import get_db
            from app.core import tenant as _tenant
            from datetime import datetime as _now
            get_db().execute(
                "INSERT INTO bot_misses (shop, channel, user_id, question, created_at)"
                " VALUES (?,?,?,?,?)",
                (_tenant.shop_key(getattr(conv, "tenant", "") or None),
                 getattr(self.conv_manager, "_account", "") or "",
                 user_id, text[:500], _now.now().isoformat()))
        except Exception as e:
            log.warning(f"[misses] ghi câu bí lỗi: {e}")
        self.conv_manager.save()

    def _handle_contact(self, user_id: str, conv, text: str):
        """Khách muốn gặp chủ nhà trực tiếp — trấn an + báo chủ theo cấu hình."""
        fixed = "Mình đã báo chủ nhà rồi nha, chủ nhà sẽ liên hệ lại với bạn trong giây lát! 📞"
        fixed = _with_contact(fixed, "contact_request", getattr(conv, "tenant", ""))   # đưa số cho khách chủ động gọi
        self._say(user_id, conv, fixed)
        # Báo chủ theo cấu hình (mặc định 'call' cho việc này; chủ chỉnh được)
        contact_msg = (
            f"📞 KHÁCH CẦN GẶP CHỦ NHÀ!\n\n"
            f"👤 ID khách: {user_id}\n"
            f"💬 Tin nhắn: \"{text[:100]}\"\n\n"
            f"Vui lòng liên hệ lại khách ngay!"
        )
        notify.alert(self.channel, "contact_request", contact_msg, cfg=_notify_cfg(conv))

    def _handle_confirmed(self, user_id: str, conv, text: str, reply: str):
        """Khách chốt đặt phòng — verify Sheets trước khi confirm (fail-closed)."""
        effective_checkin  = conv.checkin
        effective_checkout = conv.checkout or conv.checkin

        if effective_checkin:
            # Luôn verify sheets trước khi xác nhận — tránh confirm phòng đã đặt
            # ([KHONG_CO_SHEET] không chứa marker từ chối → shop chưa nối sheet
            #  thì bỏ qua bước verify, đơn vẫn ghi nhận để chủ tự xác nhận)
            log.info(f"[Booking] Xác minh lịch trước khi confirm: {effective_checkin}")
            # ĐỌC TƯƠI khi verify: sheet do chủ ghi tay, bản cache TTL 45s có thể
            # thiếu booking vừa ghi → xoá cache trước bước chốt tiền. Đọc tươi
            # lỗi (429...) sẽ rơi vào nhánh [LOI_DOC_SHEET] fail-closed bên dưới.
            from app.core import sheets as _sheets_mod
            _sheets_mod.clear_cache()
            context = format_availability_for_ai(effective_checkin, effective_checkout,
                                                 tenant=getattr(conv, "tenant", "") or None)

            # ĐỌC SHEET LỖI → KHÔNG tự chốt (chưa xác minh được còn phòng):
            # báo khách chủ sẽ xác nhận + nhờ chủ kiểm tra tay. Tránh nhận cọc
            # cho phòng chưa chắc còn.
            if "[LOI_DOC_SHEET]" in context:
                self._say(user_id, conv, (
                    "Mình đang kiểm tra lại lịch phòng, có chút trục trặc kết nối 🙏\n"
                    "Chủ nhà sẽ xác nhận phòng trống và hướng dẫn đặt cọc cho bạn ngay nhé!"
                ))
                self.channel.notify_owner(
                    f"⚠️ KHÁCH MUỐN ĐẶT nhưng KHÔNG đọc được Google Sheet để xác minh lịch\n\n"
                    f"👤 ID khách: {user_id}\n"
                    f"📅 {effective_checkin} → {effective_checkout}\n"
                    f"💬 \"{text[:150]}\"\n\n"
                    f"Vui lòng kiểm tra lịch thủ công rồi xác nhận + gửi thông tin cọc cho khách."
                )
                self.conv_manager.save()
                return

            if "KHÔNG có ca trống" in context or "NGHIÊM CẤM" in context:
                # Hết phòng → không confirm, báo khách
                try:
                    tomorrow = (_dt.strptime(effective_checkin, "%d/%m/%Y") + _td(days=1)).strftime("%d/%m/%Y")
                    deny = (
                        f"Dạ mình vừa kiểm tra thì ngày {effective_checkin} "
                        f"không còn ca trống nào bạn ơi 😢\n\n"
                        f"Bạn có muốn xem lịch ngày mai ({tomorrow}) không?"
                    )
                except Exception:
                    deny = f"Dạ ngày {effective_checkin} không còn ca trống bạn ơi 😢 Bạn thử ngày khác nhé!"
                self._say(user_id, conv, deny)
                return

            # CHỐNG DOUBLE-BOOKING: bot không ghi ngược vào sheet nên 2 khách
            # chốt cùng ngày trong cửa sổ ngắn đều thấy "còn". Khách khác cùng
            # shop đang GIỮ ngày này (hold trong SQLite, mọi tiến trình thấy)
            # → không tự chốt/gửi QR, đẩy chủ xác nhận thứ tự.
            from app.core import booking_holds
            _tenant_key = getattr(conv, "tenant", "") or ""
            others = booking_holds.conflicting_holds(
                _tenant_key, user_id, effective_checkin, effective_checkout,
                room=conv.selected_room)
            if others:
                self._say(user_id, conv, (
                    "Dạ vừa có một khách khác cũng đang giữ chỗ ngày này, "
                    "chủ nhà sẽ kiểm tra và xác nhận lại với bạn ngay ạ! 🙏"
                ))
                notify.alert(self.channel, "new_order", (
                    f"⚠️ 2 KHÁCH CÙNG GIỮ CHỖ 1 NGÀY!\n\n"
                    f"👤 Khách mới: {user_id}\n"
                    f"📅 {effective_checkin} → {effective_checkout}\n"
                    f"👤 Khách đang giữ trước: {others[0]['user_id']}\n\n"
                    f"Vui lòng xác nhận thứ tự và chốt tay với từng khách!"),
                    cfg=_notify_cfg(conv))
                self.conv_manager.save()
                return
            booking_holds.place_hold(_tenant_key, user_id, effective_checkin,
                                     effective_checkout, room=conv.selected_room)

            # Còn phòng → dùng reply cố định, tránh AI bịa "chưa có dữ liệu"
            reply = (
                "Dạ, mình đã ghi nhận yêu cầu đặt phòng của bạn rồi! 😊\n\n"
                "Chủ nhà sẽ liên hệ lại để xác nhận và hướng dẫn đặt cọc trong giây lát nhé! 🏠"
            )

        self._handle_booking_confirmed(user_id, conv, reply)

    def _ask_clarify(self, user_id, conv):
        """Hỏi lại khi bot không chắc ý khách (thay vì trả lời rỗng/đoán bừa)."""
        clarify = (
            "Dạ em chưa chắc ý mình, anh/chị cần em hỗ trợ phần nào ạ? 😊\n"
            "Ví dụ: xem phòng trống · bảng giá · ảnh phòng · đặt phòng · gặp chủ shop."
        )
        clarify = _with_contact(clarify, "unknown_question", getattr(conv, "tenant", ""))
        self.channel.send_text(user_id, clarify)
        conv.add_assistant_message(clarify)

    # ------------------------------------------------------------------ #

    def _handle_booking_confirmed(self, user_id, conv, reply):
        if conv.stage == "owner_notified":
            return  # Tránh thông báo nhiều lần

        conv.stage = "owner_notified"

        if reply:
            self.channel.send_text(user_id, reply)
            conv.add_assistant_message(reply)

        # Thông báo chủ nhà theo cấu hình sự kiện 'new_order'
        # (mặc định chỉ nhắn tin; chủ muốn gọi thì bật 'call' trong Cài đặt)
        owner_msg = (
            f"🔔 KHÁCH MUỐN ĐẶT PHÒNG!\n\n"
            f"👤 ID khách: {user_id}\n"
            f"📅 Check-in:  {conv.checkin or 'chưa rõ'}\n"
            f"📅 Check-out: {conv.checkout or 'chưa rõ'}\n"
            f"🏠 Phòng:     {conv.selected_room or 'chưa chọn'}\n\n"
            f"Vui lòng liên hệ lại khách để xác nhận và hướng dẫn đặt cọc!"
        )
        notify.alert(self.channel, "new_order", owner_msg, cfg=_notify_cfg(conv))

        # Tự tạo ĐƠN NHÁP từ hội thoại (chạy nền — AI bóc tách hơi chậm,
        # không được chặn luồng trả lời khách). Lỗi cũng không ảnh hưởng booking.
        import threading as _threading
        _channel_name = getattr(self.conv_manager, "_account", "") or ""
        # Ctx đa khách (shop_id/oa_id/business_id) là thread-local → thread con
        # _make_order KHÔNG kế thừa → snapshot rồi set lại để notify_owner báo
        # ĐÚNG chủ shop (đa khách TikTok/Shopee/Zalo OA).
        _ctx_snapshot = self.channel.get_ctx()

        def _make_order():
            try:
                self.channel.set_ctx(_ctx_snapshot)
                from app.core import orders, payments
                o = orders.create_from_conversation(user_id, conv, channel=_channel_name)
                if not o:
                    return
                self.channel.notify_owner(
                    f"📝 Đã tạo đơn nháp {o['code']}"
                    + (f" · {o['total']:,}đ" if o['total'] else "")
                    + " — vào web mục Đơn hàng để duyệt.")
                # Shop đã khai tài khoản nhận tiền + đơn có số tiền → gửi QR động
                # cho khách (nội dung CK = mã đơn để đối soát tự động), đơn sang
                # "chờ thanh toán". Chưa khai bank → dừng ở đơn nháp như cũ.
                # MULTI-TENANT: truyền CHỦ SHOP sở hữu hội thoại → QR ra ĐÚNG tài
                # khoản của shop đó (không lấy nhầm tài khoản shop khác).
                bank = payments.get_bank(getattr(conv, "tenant", "") or None)
                if bank and o["total"] > 0:
                    qr = payments.build_vietqr_url(bank, amount=o["total"], memo=o["code"])
                    self.channel.send_image_url(
                        user_id, qr,
                        f"Để giữ chỗ, mình chuyển khoản (cọc hoặc đủ {o['total']:,}đ) "
                        f"với nội dung {o['code']} giúp em nhé 👇 "
                        f"Nhận được tiền hệ thống tự xác nhận ạ!")
                    orders.update(o["id"], status="awaiting_payment")
                    orders.add_event(o["id"], "Đã gửi QR thanh toán cho khách")
            except Exception as e:
                log.error(f"[Orders] tạo đơn nháp lỗi: {e}")

        _threading.Thread(target=_make_order, daemon=True).start()
        # (Việc gọi/nhắn chủ đã do notify.alert("new_order") ở trên xử lý theo
        # cấu hình — KHÔNG gọi call_owner() vô điều kiện nữa: 10k khách đặt =
        # 10k cuộc gọi chồng nhau là điểm chết của cơ chế cũ.)
