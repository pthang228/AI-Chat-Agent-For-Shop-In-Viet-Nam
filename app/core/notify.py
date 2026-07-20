"""
LIÊN HỆ KHẨN CẤP & THÔNG BÁO CHỦ SHOP.

Thay cơ chế cũ "khách đặt phòng xong bot TỰ GỌI ĐIỆN chủ" — không scale (10k khách
= 10k cuộc gọi chồng nhau, beep kêu ở máy chủ, Telethon rủi ro khóa acc). Hai ý:

1. LIÊN HỆ KHẨN cho KHÁCH (khách CHỦ ĐỘNG gọi — scale vô tận):
   chủ shop nhập SĐT / Zalo / Telegram → bot đưa số cho khách khi cần gấp, theo
   chế độ `share_mode`:
     off      — không bao giờ đưa
     strict   — chỉ khi khách hỏi thẳng số/gặp chủ (intent contact_request)
     ask      — khi khách xin gặp người HOẶC bot bí (contact_request + unknown)
     greeting — luôn kèm ở tin chào (+ contact_request)

2. THÔNG BÁO CHỦ có CHỌN LỌC (thay tự-gọi mọi lúc): mỗi loại sự kiện chủ tự đặt
   mức trong `events`:
     off    — không báo
     notify — chỉ nhắn tin báo (channel.notify_owner — với kênh Telegram đây CHÍNH
              là push bot, miễn phí/tức thì/không khóa acc)
     call   — nhắn tin + gọi điện (chỉ nên bật cho việc thật khẩn)

Single-tenant như payments.get_bank: không truyền username → lấy chủ shop ĐẦU TIÊN.
"""

import json
import logging
from datetime import datetime

from app.core.db import get_db

log = logging.getLogger(__name__)

# Sự kiện báo chủ + nhãn hiển thị + mức mặc định.
# Mặc định GIẢM tải: chỉ 'contact_request' (khách xin gặp người) mới gọi điện,
# còn lại chỉ nhắn tin (push) — đúng tinh thần "đừng gọi mỗi sự kiện".
EVENTS = {
    "new_order":       ("Khách chốt đơn / đặt phòng",       "notify"),
    "contact_request": ("Khách xin gặp người thật",          "call"),
    "unknown":         ("Bot bí — câu chưa trả lời được",    "notify"),
    "payment":         ("Khách chuyển khoản thành công",     "notify"),
}
SHARE_MODES = ("off", "strict", "ask", "greeting")
_MODE_VALUES = ("off", "notify", "call")


def _default_events() -> dict:
    return {k: v[1] for k, v in EVENTS.items()}


# ── Đọc / ghi cấu hình ───────────────────────────────────────────────

def _owner_username() -> str | None:
    """Chủ shop chính (single-tenant): user KHÔNG phải nhân viên, tạo sớm nhất."""
    rows = get_db().query(
        "SELECT username FROM users WHERE COALESCE(role,'owner') != 'staff' "
        "ORDER BY created_at LIMIT 1")
    return rows[0]["username"] if rows else None


def deliver_to_owner(tenant: str, subject: str, text: str, notify_fn=None) -> bool:
    """Đưa 1 thông báo VẬN HÀNH (nhắc đơn/nhắc việc...) tới ĐÚNG chủ shop.

    Multi-tenant: notify_fn (notify_owner của kênh) trỏ về nhóm/số của CHỦ NỀN
    TẢNG — bắn dữ liệu shop thuê qua đó là lộ PII chéo tenant (đã dính thật với
    thread nhắc đơn). Luật:
      - shop gốc (tenant rỗng / default_owner) → notify_fn như cũ
      - shop thuê → EMAIL chủ shop (username là email, SMTP dùng chung với OTP)
    Trả True = đã đưa (hoặc best-effort xong: SMTP chưa cấu hình chỉ log —
    KHÔNG trả False để caller khỏi retry vô hạn mỗi vòng quét).
    Raise/False chỉ khi kênh CÓ cấu hình mà gửi thất bại (caller thử lại)."""
    from app.core import tenant as _tenant
    t = (tenant or "").strip()
    if not t or t == _tenant.default_owner():
        if notify_fn is None:
            return True
        notify_fn(text)          # lỗi → raise cho caller giữ semantics retry cũ
        return True
    from app.core import mailer
    if not mailer.configured():
        log.warning(f"[notify] SMTP chưa cấu hình → không gửi được nhắc việc cho "
                    f"shop {t} (subject: {subject[:60]})")
        return True              # config state, không phải lỗi — đừng retry mãi
    return mailer.send_mail(t, subject, text)


def get_config(username: str = None) -> dict:
    """Cấu hình của chủ (mặc định chủ chính). LUÔN trả dict đầy đủ (kể cả chưa
    lưu bao giờ) để code gọi khỏi phải kiểm None."""
    username = username or _owner_username()
    cfg = {
        "username": username or "",
        "emergency_phone": "", "emergency_zalo": "", "emergency_tele": "",
        "share_mode": "ask", "events": _default_events(),
    }
    if not username:
        return cfg
    rows = get_db().query("SELECT * FROM notify_config WHERE username=?", (username,))
    if rows:
        r = rows[0]
        cfg.update({
            "emergency_phone": r["emergency_phone"] or "",
            "emergency_zalo":  r["emergency_zalo"] or "",
            "emergency_tele":  r["emergency_tele"] or "",
            "share_mode": r["share_mode"] if r["share_mode"] in SHARE_MODES else "ask",
        })
        try:
            saved = json.loads(r["events"] or "{}")
        except Exception:
            saved = {}
        # gộp default + đã lưu (giữ default cho sự kiện mới thêm sau này)
        ev = _default_events()
        for k, v in saved.items():
            if k in ev and v in _MODE_VALUES:
                ev[k] = v
        cfg["events"] = ev
    return cfg


def save_config(username: str, data: dict) -> dict:
    """Lưu cấu hình cho 1 chủ shop (upsert). Bỏ qua field lạ, chuẩn hoá giá trị."""
    cur = get_config(username)
    phone = (data.get("emergency_phone", cur["emergency_phone"]) or "").strip()[:40]
    zalo  = (data.get("emergency_zalo",  cur["emergency_zalo"])  or "").strip()[:80]
    tele  = (data.get("emergency_tele",  cur["emergency_tele"])  or "").strip()[:80]
    mode  = data.get("share_mode", cur["share_mode"])
    if mode not in SHARE_MODES:
        mode = cur["share_mode"]
    ev = dict(cur["events"])
    for k, v in (data.get("events") or {}).items():
        if k in ev and v in _MODE_VALUES:
            ev[k] = v
    get_db().execute(
        "INSERT INTO notify_config (username, emergency_phone, emergency_zalo,"
        " emergency_tele, share_mode, events, updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(username) DO UPDATE SET emergency_phone=excluded.emergency_phone,"
        " emergency_zalo=excluded.emergency_zalo, emergency_tele=excluded.emergency_tele,"
        " share_mode=excluded.share_mode, events=excluded.events, updated_at=excluded.updated_at",
        (username, phone, zalo, tele, mode, json.dumps(ev, ensure_ascii=False),
         datetime.now().isoformat()))
    return get_config(username)


# ── Liên hệ khẩn cho KHÁCH ───────────────────────────────────────────

def contact_line(cfg: dict = None) -> str:
    """Dòng liên hệ khẩn gửi khách (rỗng nếu chủ chưa nhập gì)."""
    cfg = cfg or get_config()
    parts = []
    if cfg["emergency_phone"]:
        parts.append(f"📞 {cfg['emergency_phone']}")
    if cfg["emergency_zalo"]:
        parts.append(f"Zalo: {cfg['emergency_zalo']}")
    if cfg["emergency_tele"]:
        parts.append(f"Telegram: {cfg['emergency_tele']}")
    if not parts:
        return ""
    return "📲 Cần gấp bạn liên hệ trực tiếp: " + " · ".join(parts)


def contact_for(intent: str, cfg: dict = None) -> str:
    """Liên hệ khẩn để CHÈN vào câu trả lời cho intent này (rỗng nếu không hợp lệ
    theo share_mode hoặc chủ chưa nhập liên hệ)."""
    cfg = cfg or get_config()
    mode = cfg["share_mode"]
    if mode == "off":
        return ""
    allow = False
    if intent == "contact_request":
        allow = mode in ("strict", "ask", "greeting")   # khách hỏi thẳng → luôn đưa
    elif intent == "unknown_question":
        allow = mode in ("ask", "greeting")              # bot bí → đưa nếu bật ask
    elif intent == "greeting":
        allow = mode == "greeting"
    if not allow:
        return ""
    return contact_line(cfg)


# ── Thông báo chủ có chọn lọc ────────────────────────────────────────

def event_mode(event: str, cfg: dict = None) -> str:
    cfg = cfg or get_config()
    return cfg["events"].get(event, EVENTS.get(event, (None, "notify"))[1])


def alert(channel, event: str, msg: str, cfg: dict = None):
    """Báo chủ về 1 sự kiện THEO cấu hình:
      off    → không làm gì
      notify → channel.notify_owner(msg)   (kênh Telegram = push bot)
      call   → notify_owner + channel.call_owner()
    Nuốt lỗi (thông báo hỏng không được chặn luồng trả lời khách)."""
    try:
        mode = event_mode(event, cfg)
    except Exception:
        mode = "notify"          # lỗi đọc config → cứ nhắn tin cho an toàn
    if mode == "off":
        log.info(f"[notify] sự kiện '{event}' đang TẮT → bỏ qua báo chủ")
        return
    try:
        channel.notify_owner(msg)
    except Exception as e:
        log.error(f"[notify] notify_owner lỗi: {e}")
    if mode == "call":
        try:
            channel.call_owner()
        except Exception as e:
            log.error(f"[notify] call_owner lỗi: {e}")
