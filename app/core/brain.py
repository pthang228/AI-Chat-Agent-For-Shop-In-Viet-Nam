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


class Brain:
    """Logic xử lý tin nhắn, dùng chung cho mọi kênh."""

    # TÓM TẮT CUỘN: vượt ngưỡng tin chưa tóm → AI gộp phần cũ thành vài dòng
    SUMMARY_TRIGGER = 26   # số tin chưa-tóm tối thiểu mới kích hoạt (26 > cửa sổ 20)
    SUMMARY_KEEP    = 12   # số tin mới nhất GIỮ THÔ (không tóm) cho ngữ cảnh tươi

    def __init__(self, channel: Channel, conv_manager: ConversationManager):
        self.channel = channel
        self.conv_manager = conv_manager
        self._summarizing: set = set()   # user_id đang tóm nền — chống chạy chồng

    # ------------------------------------------------------------------ #

    def handle(self, user_id: str, text: str):
        """Xử lý 1 tin nhắn từ khách, rồi (nền) cập nhật tóm tắt cuộn nếu hội
        thoại đã dài — chạy SAU khi khách nhận trả lời nên không thêm độ trễ."""
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

    def _handle_inner(self, user_id: str, text: str):
        """
        Xử lý 1 tin nhắn từ khách.
        text == "" nghĩa là sticker/media không có text (kênh chỉ gọi khi là khách mới).
        """
        conv = self.conv_manager.get(user_id)
        is_first_message = len(conv.messages) == 0  # Kiểm tra trước khi add

        # Sticker / media không có text → chỉ đến đây nếu là khách mới
        if not text:
            log.info(f"[Handle] Sticker từ khách mới {user_id} → gửi greeting")
            greeting = _with_contact(FIRST_MESSAGE_GREETING, "greeting", getattr(conv, "tenant", ""))
            self.channel.send_text(user_id, greeting)
            conv.add_assistant_message(greeting)
            if _default_shop(conv):   # ảnh bảng giá legacy CHỈ của shop gốc
                time.sleep(0.5)
                self.channel.send_price_photos(user_id)
            return

        conv.add_user_message(text)

        # Gửi cho AI phân tích (không bao gồm tin nhắn vừa thêm).
        # user_id + account để AI đọc TRÍ NHỚ VỀ KHÁCH (CRM) → cá nhân hoá.
        # history_for_ai: tin đã nằm trong TÓM TẮT CUỘN không gửi thô lại;
        # conv_state: trạng thái + tóm tắt + intent lượt trước (style RAG).
        result = analyze_message(text, conv.history_for_ai(n=20)[:-1],
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

        tl_check = text.lower()
        _has_room  = bool(re.search(r'\b[123]\d{2}\b', text))
        _has_home  = any(k in tl_check for k in ["haru", "mochi", "staycation"])

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
                log.info("[Intent] Override → availability_check (ngày + hỏi phòng)")
                intent = "availability_check"
            # Case 2: chỉ hỏi phòng (đã có ngày trong conv)
            elif _has_avail and conv.checkin:
                log.info("[Intent] Override → availability_check (hỏi phòng, có checkin sẵn)")
                intent = "availability_check"
            # Case 3: tin nhắn CHỈ là cụm ngày tháng (trả lời "ngày nào?")
            elif _has_day and len(text.strip().split()) <= 5:
                log.info("[Intent] Override → availability_check (chỉ nêu ngày)")
                intent = "availability_check"
            # Case 4: nêu ngày trong flow đang hỏi lịch
            elif _has_day and conv.stage in ("checking", "offering"):
                log.info("[Intent] Override → availability_check (nêu ngày trong flow lịch)")
                intent = "availability_check"
            # Case 5: câu ngắn mơ hồ trong flow đang hỏi lịch
            elif conv.stage in ("checking", "offering") and conv.checkin:
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
                    log.info("[Intent] Override → availability_check (follow-up flow lịch)")
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
                log.info(f"[Intent] Override → contact_request (was: {intent})")
                intent = "contact_request"
        # Regex bổ sung: "muốn/cần gặp chủ/admin" dưới nhiều hình thức
        if intent != "contact_request" and re.search(
            r'(muốn|cần|cho).{0,10}gặp.{0,10}(chủ|admin|người)', tl_check
        ):
            log.info(f"[Intent] Override → contact_request (regex muốn/cần gặp)")
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
                log.info(f"[Intent] Override → price_list_request (was: {intent})")
                intent = "price_list_request"
        # Regex: "giá ... bao nhiêu/thế nào/như nào" (cách nhau vài từ)
        if intent != "price_list_request" and re.search(
            r'giá.{0,25}(bao nhiêu|thế nào|như nào|ra sao)', tl_check
        ):
            log.info(f"[Intent] Override → price_list_request (regex giá+bao nhiêu)")
            intent = "price_list_request"

        # ── Override photo_request: có từ khóa ảnh + (số phòng hoặc tên homestay) ──
        _has_photo = any(k in tl_check for k in [
            "ảnh", "hình", "xem phòng", "xem của", "xem hết",
            "tất cả các phòng", "show", "cho xem",
        ])
        if intent != "photo_request" and (_has_room or _has_home) and _has_photo:
            log.info(f"[Intent] Override → photo_request (has photo keyword + room/home)")
            intent = "photo_request"

        # ── Override photo_request: "ảnh phòng", "xem hết", v.v. (không cần số phòng) ──
        _has_photo_generic = any(k in tl_check for k in [
            "ảnh phòng", "hình phòng",
            "ảnh các phòng", "hình các phòng",
            "ảnh tất cả", "xem tất cả", "tất cả các phòng", "mọi phòng",
            "xem hết", "show all",
        ])
        if intent != "photo_request" and _has_photo_generic:
            log.info(f"[Intent] Override → photo_request (generic photo phrase)")
            intent = "photo_request"

        # ── Override photo_request: số phòng + từ xác nhận tùy chọn ──
        if intent not in ("photo_request", "booking_confirm", "availability_check", "contact_request"):
            _only_rooms = bool(re.fullmatch(
                r'[\s]*(?:[123]\d{2}[\s,、và\+&]*)+[\s]*(đi|nhé|nha|luôn|thôi|đó|ạ)?[\s]*',
                text.strip(), re.IGNORECASE
            ))
            if _only_rooms and _has_room:
                log.info(f"[Intent] Override → photo_request (số phòng + xác nhận: '{text.strip()}')")
                intent = "photo_request"

        # ── Override photo_request: "X thì sao" / "bên X" follow-up ảnh ──
        if intent not in ("photo_request", "booking_confirm", "availability_check", "contact_request"):
            _photo_followup_re = re.search(
                r'(haru|mochi|staycation).{0,10}(thì sao|thế nào|như nào|thế|sao)\b'
                r'|(còn bên|bên kia|bên (haru|mochi|staycation)|homestay kia).{0,15}',
                tl_check
            )
            if _photo_followup_re and _has_home:
                log.info(f"[Intent] Override → photo_request (follow-up ảnh homestay: '{text.strip()}')")
                intent = "photo_request"

        # ── AI tự trả lời: use_ai_reply=True + intent vẫn là "other" sau override ──
        # Contact_request và photo override (số phòng / homestay) vẫn được phép chạy;
        # chỉ các override availability/price bị bỏ khi AI đã tự tin với câu trả lời.
        if use_ai_reply and intent == "other":
            log.info("[Intent] AI use_ai_reply=True, intent=other → dùng reply của AI")
            if reply:
                self.channel.send_text(user_id, reply)
                conv.add_assistant_message(reply)
            return

        # ── Câu đầu tiên với mỗi khách mới → LUÔN gửi greeting + bảng giá ──
        if is_first_message:
            log.info(f"[FirstMsg] Gửi greeting cố định cho user {user_id}")
            greeting = _with_contact(FIRST_MESSAGE_GREETING, "greeting", getattr(conv, "tenant", ""))
            self.channel.send_text(user_id, greeting)
            conv.add_assistant_message(greeting)
            if _default_shop(conv):
                # Shop gốc: kèm ảnh bảng giá legacy như trước
                time.sleep(0.5)
                self.channel.send_price_photos(user_id)
                time.sleep(0.5)
                if intent in ("other", "price_list_request"):
                    return  # Greeting + bảng giá là đủ (bảng giá đã gửi rồi, không gửi lại)
            else:
                # Shop thường: bảng giá lấy từ Thư viện ảnh (block dưới) — không rò media shop gốc
                if intent == "other":
                    return  # Greeting là đủ
            # Có intent cụ thể khác → tiếp tục xử lý bên dưới (gửi thêm câu trả lời thực)

        # ── Thư viện ảnh: khách hỏi trúng TÊN/keywords bộ ảnh shop tự đặt ──
        # (shop upload trong web → media/photo_library). Match được → gửi bộ đó;
        # không match / kênh chưa hỗ trợ → rơi xuống cơ chế cũ y nguyên.
        if intent in ("photo_request", "price_list_request"):
            from app.core import photo_library
            # multi-tenant: chỉ tìm trong bộ ảnh của SHOP sở hữu hội thoại
            matched = photo_library.find_sets(
                text, tenant_ws=getattr(conv, "tenant", "") or None)
            if matched:
                sent_any = False
                for s in matched:
                    if self.channel.send_photo_folder(
                            user_id, photo_library.set_dir(s["slug"]), f"📸 {s['name']}:"):
                        sent_any = True
                if sent_any:
                    names = ", ".join(s["name"] for s in matched)
                    fixed = f"Đây là ảnh {names} bạn nhé! 📸"
                    self.channel.send_text(user_id, fixed)
                    conv.add_assistant_message(fixed)
                    log.info(f"[PhotoLib] gửi bộ ảnh: {names}")
                    return

        # Khi khách xin bảng giá
        if intent == "price_list_request":
            if not _default_shop(conv):
                # Shop thường chưa có bộ ảnh "bảng giá" match ở trên → trả lời bằng AI
                # (giá nằm trong não đã train), tuyệt đối không gửi bảng giá shop gốc
                fallback = reply or ("Bạn chờ mình chút nha, mình gửi thông tin giá ngay! "
                                     "Bạn muốn xem giá dịch vụ nào ạ? 😊")
                self.channel.send_text(user_id, fallback)
                conv.add_assistant_message(fallback)
                return
            if reply:
                self.channel.send_text(user_id, reply)
                conv.add_assistant_message(reply)
            time.sleep(0.5)
            self.channel.send_price_photos(user_id)
            return

        # Khi khách xin ảnh phòng
        if intent == "photo_request":
            if not _default_shop(conv):
                # Shop thường: ảnh lấy từ Thư viện ảnh (đã thử match ở trên, không trúng)
                # → không đụng kho media/map phòng legacy của shop gốc
                fallback = reply or ("Bạn muốn xem ảnh phần nào để mình gửi đúng bộ ạ? 📸 "
                                     "(shop sẽ bổ sung thêm ảnh nếu chưa có nha)")
                self.channel.send_text(user_id, fallback)
                conv.add_assistant_message(fallback)
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
                self.channel.send_text(user_id, fixed_reply)
                conv.add_assistant_message(fixed_reply)
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
                    fixed_reply = "Đây là ảnh tất cả các phòng bạn nhé! 📸"
                    self.channel.send_text(user_id, fixed_reply)
                    conv.add_assistant_message(fixed_reply)
                    time.sleep(0.5)
                    self.channel.send_room_photos(user_id, [f"Phòng {r}" for r in all_rooms])
                else:
                    if reply:
                        self.channel.send_text(user_id, reply)
                        conv.add_assistant_message(reply)
            else:
                # Không rõ phòng nào → AI hỏi lại
                if reply:
                    self.channel.send_text(user_id, reply)
                    conv.add_assistant_message(reply)
            return

        # ── Availability: Python fallback infer ngày nếu AI chưa extract được ──
        if intent == "availability_check" and not conv.checkin:
            inferred = _infer_date_from_text(text)
            if inferred:
                conv.checkin  = inferred
                conv.checkout = inferred
                log.info(f"[Date] Inferred từ context: {inferred}")

        # ── Availability: chỉ có checkin → checkout = cùng ngày ──
        if intent == "availability_check" and conv.checkin and not conv.checkout:
            conv.checkout = conv.checkin

        # ── Availability: không có ngày nào cả → hỏi thẳng, không dùng AI reply ──
        if intent == "availability_check" and not conv.checkin:
            fixed = "Bạn muốn kiểm tra lịch ngày nào ạ? 📅"
            self.channel.send_text(user_id, fixed)
            conv.add_assistant_message(fixed)
            return

        # Khi khách hỏi lịch và đủ ngày → check sheets
        if intent == "availability_check" and conv.checkin and conv.checkout:
            conv.stage = "checking"
            log.info(f"[Sheets] Kiểm tra lịch: {conv.checkin} → {conv.checkout}")
            context = format_availability_for_ai(conv.checkin, conv.checkout,
                                                 tenant=getattr(conv, "tenant", "") or None)
            log.info(f"[Sheets] Kết quả:\n{context}")

            # Shop chưa nối Google Sheet nào → không bịa lịch: ghi nhận + báo chủ
            if "[KHONG_CO_SHEET]" in context:
                conv.stage = "offering"
                fixed = (
                    f"Mình đã ghi nhận bạn muốn ngày {conv.checkin} rồi nha! 📅\n"
                    f"Chủ shop sẽ kiểm tra lịch trống và xác nhận lại với bạn sớm nhất 😊"
                )
                self.channel.send_text(user_id, fixed)
                conv.add_assistant_message(fixed)
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

            self.channel.send_text(user_id, reply)
            conv.add_assistant_message(reply)

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
            return

        # Khi khách muốn đổi/dời khung giờ
        if intent == "reschedule_request":
            fixed = reply if reply else (
                "Việc đổi ca/khung giờ mình không tự quyết định được bạn ơi, "
                "để mình hỏi anh chủ giúp bạn nhé! "
                "Bạn còn cần hỏi thêm gì không ạ? 😊"
            )
            self.channel.send_text(user_id, fixed)
            conv.add_assistant_message(fixed)
            reschedule_msg = (
                f"🔄 KHÁCH MUỐN ĐỔI KHUNG GIỜ\n\n"
                f"👤 ID khách: {user_id}\n"
                f"💬 Yêu cầu: \"{text[:200]}\"\n\n"
                f"Vui lòng xác nhận và liên hệ lại khách nhé!"
            )
            self.channel.notify_owner(reschedule_msg)
            self.conv_manager.save()
            return

        # Khi khách hỏi điều gì đó bot không có thông tin để trả lời
        if intent == "unknown_question":
            fixed = reply if reply else (
                "Câu này mình chưa có thông tin để trả lời bạn ơi 😅 "
                "Mình đã báo chủ nhà rồi, chủ nhà sẽ phản hồi bạn sớm nhé! "
                "Bạn còn câu hỏi gì khác không ạ? 😊"
            )
            fixed = _with_contact(fixed, "unknown_question", getattr(conv, "tenant", ""))   # bot bí → đưa số nếu bật
            self.channel.send_text(user_id, fixed)
            conv.add_assistant_message(fixed)
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
            return

        # Khi khách muốn gặp chủ nhà trực tiếp
        if intent == "contact_request":
            fixed = "Mình đã báo chủ nhà rồi nha, chủ nhà sẽ liên hệ lại với bạn trong giây lát! 📞"
            fixed = _with_contact(fixed, "contact_request", getattr(conv, "tenant", ""))   # đưa số cho khách chủ động gọi
            self.channel.send_text(user_id, fixed)
            conv.add_assistant_message(fixed)
            # Báo chủ theo cấu hình (mặc định 'call' cho việc này; chủ chỉnh được)
            contact_msg = (
                f"📞 KHÁCH CẦN GẶP CHỦ NHÀ!\n\n"
                f"👤 ID khách: {user_id}\n"
                f"💬 Tin nhắn: \"{text[:100]}\"\n\n"
                f"Vui lòng liên hệ lại khách ngay!"
            )
            notify.alert(self.channel, "contact_request", contact_msg, cfg=_notify_cfg(conv))
            return

        # Khi khách chốt đặt phòng
        if confirmed:
            effective_checkin  = conv.checkin
            effective_checkout = conv.checkout or conv.checkin

            if effective_checkin:
                # Luôn verify sheets trước khi xác nhận — tránh confirm phòng đã đặt
                # ([KHONG_CO_SHEET] không chứa marker từ chối → shop chưa nối sheet
                #  thì bỏ qua bước verify, đơn vẫn ghi nhận để chủ tự xác nhận)
                log.info(f"[Booking] Xác minh lịch trước khi confirm: {effective_checkin}")
                context = format_availability_for_ai(effective_checkin, effective_checkout,
                                                     tenant=getattr(conv, "tenant", "") or None)

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
                    self.channel.send_text(user_id, deny)
                    conv.add_assistant_message(deny)
                    return

                # Còn phòng → dùng reply cố định, tránh AI bịa "chưa có dữ liệu"
                reply = (
                    "Dạ, mình đã ghi nhận yêu cầu đặt phòng của bạn rồi! 😊\n\n"
                    "Chủ nhà sẽ liên hệ lại để xác nhận và hướng dẫn đặt cọc trong giây lát nhé! 🏠"
                )

            self._handle_booking_confirmed(user_id, conv, reply)
            return

        # Trả lời thông thường
        if reply:
            self.channel.send_text(user_id, reply)
            conv.add_assistant_message(reply)

        # Lưu lại sau mỗi lần xử lý tin nhắn
        self.conv_manager.save()

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
                bank = payments.get_bank()
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
