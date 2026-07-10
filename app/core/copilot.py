"""
COPILOT QUẢN TRỊ — trợ lý AI giúp CHỦ SHOP cài đặt & vận hành NovaChat.

KHÁC bot trả lời khách (brain) và bot bán hàng "Mi" (support_api): copilot này
nói chuyện với CHỦ SHOP đã đăng nhập, đọc TRẠNG THÁI THẬT của tài khoản họ và
làm giúp vài việc AN TOÀN (bật/tắt bot, tạo câu trả lời mẫu) — việc nặng (đổi
gói, xoá) chỉ DẪN tới đúng trang chứ không tự bấm.

Kiến trúc agent (server-side loop, tương thích DeepSeek/Groq không cần function
calling chuẩn): mỗi lượt AI trả 1 JSON:
  { "tool": "<tên tool đọc>"?, "reply": "<câu trả lời>"?,
    "action": {"name","args","label"}?, "navigate": [{"label","to"}]? }
- Có `tool` → backend chạy TOOL ĐỌC (an toàn), nhét kết quả lại, hỏi AI tiếp
  (tối đa MAX_STEPS vòng) → agent tự thu thập dữ liệu rồi mới trả lời.
- `action` = việc GHI → KHÔNG chạy trong loop; trả về cho UI để chủ BẤM XÁC NHẬN
  (rồi gọi confirm_action). Chống agent tự ý đổi trạng thái.
- `navigate` = gợi ý mở trang (UI render nút).

Mọi thứ scope theo `username` (chủ đang đăng nhập) — không đụng dữ liệu shop khác.
"""

import hmac
import json
import logging
import re
import secrets

from app.core.claude_ai import _call_ai

# Bí mật ký PHIÊN (mỗi lần khởi động 1 giá trị) — dùng ràng buộc "pending_action"
# do chat() đề xuất với lệnh confirm_action: client chỉ chạy được ĐÚNG action mà
# AI đã đề xuất (kèm chữ ký), không tự bịa name/args tuỳ ý gọi thẳng /confirm.
_SIGN_SECRET = secrets.token_bytes(24)


def _sign_action(username: str, name: str, args: dict) -> str:
    payload = f"{username}|{name}|{json.dumps(args or {}, sort_keys=True, ensure_ascii=False)}"
    return hmac.new(_SIGN_SECRET, payload.encode("utf-8"), "sha256").hexdigest()[:24]

log = logging.getLogger(__name__)

MAX_STEPS = 3           # số vòng tối đa agent gọi tool đọc trước khi trả lời
MAX_TURNS = 10          # lịch sử chat gửi cho AI


# ── 2 HẠNG TRỢ LÝ theo gói ───────────────────────────────────────────
# Chưa đăng ký gói (trial / hết hạn) → trợ lý CƠ BẢN: kiến thức ngang bot "Mi"
# ngoài landing (tính năng, bảng giá, mời nâng cấp), KHÔNG tool, KHÔNG action.
# Đã đăng ký gói còn hạn → trợ lý CHUYÊN SÂU: đọc dữ liệu thật + hướng dẫn
# thuần thục mọi thao tác trong app + làm giúp việc có xác nhận.

def _is_premium(username: str) -> bool:
    """Đã đăng ký gói trả phí còn hạn chưa? Lỗi/không rõ → coi là chưa (cơ bản)."""
    if not username:
        return False
    try:
        from app.core import billing
        st = billing.status(username)
        return bool(st.get("active")) and st.get("tier") != "trial"
    except Exception as e:
        log.warning(f"[copilot] không đọc được billing của {username}: {e}")
        return False

# Route hợp lệ để agent gợi ý điều hướng (chống mở link lạ)
NAV_ROUTES = {
    "/": "Tổng quan", "/?s=chat": "Hội thoại", "/?s=customers": "Khách hàng",
    "/?s=chatbot": "Chatbot / Kênh", "/?s=orders": "Đơn hàng",
    "/?s=posts": "Bài viết & bình luận", "/?s=stats": "Thống kê",
    "/prompt": "Dạy AI", "/billing": "Gói dịch vụ", "/settings": "Cài đặt",
}
CHANNELS = ("zalo", "meta", "telegram", "tiktok", "shopee", "zalooa", "webchat")


# ── TOOLS ĐỌC (an toàn, agent tự chạy) ──────────────────────────────

def _t_overview(username, args):
    """Ảnh chụp nhanh toàn tài khoản: kênh bật/tắt, số app, gói, quota, khách, đơn."""
    from app.web_api.bridge import _load_bot_state, _channel_enabled
    from app.core import billing, orders, customers
    from app.core.db import get_db
    db = get_db()
    state = _load_bot_state()
    bots = {ch: _channel_enabled(state, ch) for ch in CHANNELS}
    apps = db.query("SELECT channel, COUNT(*) AS n FROM user_apps WHERE username=? GROUP BY channel",
                    (username,)) if username else []
    try:
        bill = billing.status(username) if username else {}
    except Exception:
        bill = {}
    try:
        osum = orders.summary()
    except Exception:
        osum = {}
    cust = customers.list_customers(limit=1)
    return {
        "bot_enabled_global": state.get("enabled", True),
        "bots_per_channel": bots,
        "apps_added": [{"channel": a["channel"], "count": a["n"]} for a in apps],
        "billing": {k: bill.get(k) for k in
                    ("tier_label", "plan_label", "on_trial", "active", "days_left",
                     "ai_used", "ai_quota", "balance") if k in bill},
        "orders": osum,
        "customers_total": cust.get("total", 0),
    }


def _t_stats(username, args):
    """Tổng hội thoại/tin nhắn toàn kênh (đọc thẳng bảng sessions)."""
    from app.core.db import get_db
    rows = get_db().query("SELECT messages FROM sessions")
    conv = len(rows)
    msg = 0
    for r in rows:
        try:
            msg += len(json.loads(r["messages"] or "[]"))
        except Exception:
            pass
    return {"total_conversations": conv, "total_messages": msg}


def _t_prompt(username, args):
    """Trạng thái 'bộ não' bot (mặc định / tuỳ chỉnh / lai + số mẩu tri thức)."""
    from app.core import prompt_builder
    cur = prompt_builder.current()
    return {"source": cur.get("source"), "mode": cur.get("mode"),
            "chunk_count": cur.get("chunk_count", 0),
            "updated_at": cur.get("updated_at")}


def _t_channel_guide(username, args):
    """Hướng dẫn kết nối 1 kênh (text tĩnh, chính xác — agent diễn giải cho chủ)."""
    ch = str((args or {}).get("channel") or "").lower()
    guides = {
        "zalo": "Zalo cá nhân: mở app kênh Zalo trong web → tab Kết nối → QUÉT MÃ QR bằng điện thoại. Không cần token.",
        "zalooa": "Zalo OA: cần Official Account (oa.zalo.me) → uỷ quyền cho NovaChat → dán Access Token + Refresh Token vào tab Kết nối. Hệ thống tự gia hạn token 25h.",
        "meta": "Messenger + Instagram: bấm 'Đăng nhập Facebook' trong app kênh Mess+IG → chọn Page → xong. 1 lần đăng nhập chạy cả Messenger lẫn IG.",
        "telegram": "Telegram: nhắn @BotFather tạo bot → copy token → dán vào tab Kết nối. Người lạ nhắn được ngay, không cần duyệt.",
        "tiktok": "TikTok: cần TikTok Business + app được TikTok duyệt (Business Messaging) → dán access token + business id. Chưa duyệt thì chạy thử nghiệm.",
        "shopee": "Shopee: shop uỷ quyền cho app NovaChat trên Shopee Open Platform → dán Shop ID + Access Token. Cần Shopee duyệt app vendor.",
        "webchat": "Website: mở app kênh Website → điền tên web → bấm 'Tạo mã nhúng' → copy 1 dòng <script> dán vào cuối trang web của shop (trước </body>). Không token, không chờ duyệt — dán xong là bong bóng chat hiện ngay.",
    }
    return {"channel": ch, "guide": guides.get(ch, "Kênh không xác định.")}


READ_TOOLS = {
    "overview": _t_overview,
    "stats": _t_stats,
    "prompt_status": _t_prompt,
    "channel_guide": _t_channel_guide,
}

# ── TOOLS GHI (an toàn, cần chủ XÁC NHẬN mới chạy) ───────────────────

def _a_toggle_bot(username, args):
    from app.web_api.bridge import _load_bot_state, _save_bot_state, _norm_channel
    ch = _norm_channel(str((args or {}).get("channel") or "").strip())
    enabled = bool((args or {}).get("enabled", True))
    state = _load_bot_state()
    if not ch or ch in ("all", ""):
        state["enabled"] = enabled
        for c in list(state.get("channels", {})):
            state["channels"][c] = enabled
        target = "tất cả kênh"
    else:
        state.setdefault("channels", {})[ch] = enabled
        target = ch
    _save_bot_state(state)
    return f"Đã {'BẬT' if enabled else 'TẮT'} bot cho {target}."


def _a_add_canned(username, args):
    from datetime import datetime
    from app.core.db import get_db
    content = str((args or {}).get("content") or "").strip()
    if not content:
        raise ValueError("Thiếu nội dung câu trả lời mẫu")
    title = str((args or {}).get("title") or "").strip()[:60] or content[:30]
    # MULTI-TENANT: đóng dấu workspace của người ra lệnh — thiếu là câu mẫu
    # rơi vào workspace chủ nền tảng (tenant='' được coi là của chủ đầu tiên)
    db = get_db()
    ws = username
    rows = db.query("SELECT role, owner_username FROM users WHERE username=?", (username,))
    if rows and rows[0]["role"] == "staff" and rows[0]["owner_username"]:
        ws = rows[0]["owner_username"]
    db.execute(
        "INSERT INTO canned_replies (title, content, created_at, tenant) VALUES (?,?,?,?)",
        (title, content[:2000], datetime.now().isoformat(), ws))
    return f"Đã tạo câu trả lời mẫu \"{title}\"."


ACTION_TOOLS = {
    "toggle_bot": _a_toggle_bot,
    "add_canned_reply": _a_add_canned,
}


# ── Agent loop ───────────────────────────────────────────────────────

def _plans_text() -> str:
    """Bảng giá lấy TRỰC TIẾP từ billing (như bot Mi) — không bao giờ lệch giá thật."""
    from app.core import billing
    rows = []
    for t in billing.plans_catalog():
        prices = " · ".join(
            f"{billing.DURATIONS[d]['label']}: {p:,}₫" for d, p in t["prices"].items())
        rows.append(
            f"- {t['label']}: {t['quota']:,} lượt AI/tháng, "
            f"{'1 kênh' if t['channels'] else 'TẤT CẢ kênh'}, "
            f"{'có' if t['call_owner'] else 'không'} gọi điện báo chủ. Giá: {prices}")
    return "\n".join(rows).replace(",", ".")


# Trợ lý CƠ BẢN (chưa đăng ký gói) — kiến thức NGANG bot Mi ngoài landing page.
_BASIC_NAV = {"/", "/billing"}

def _basic_system() -> str:
    return f"""Bạn là TRỢ LÝ CƠ BẢN của NovaChat — phần mềm trợ lý AI trả lời khách tự động đa kênh (Zalo, Zalo OA, Messenger, Instagram, Telegram, TikTok, Shopee, chat trên website) cho shop dịch vụ Việt Nam. Người đang chat là chủ shop ĐÃ ĐĂNG NHẬP nhưng CHƯA ĐĂNG KÝ GÓI (đang dùng thử hoặc gói đã hết hạn).

BẠN CHỈ TRẢ LỜI KIẾN THỨC CƠ BẢN (như tư vấn viên trên trang chủ):
- NovaChat làm gì: bot AI tự tư vấn & chốt khách 24/7 đa kênh; tự tra dữ liệu shop (Google Sheets: lịch trống, giá, tồn kho...); gửi bảng giá + ảnh; chốt đơn/đặt lịch; khách cần thì nhắn + gọi điện báo chủ.
- "Dạy AI": dán link dữ liệu + vài dòng hướng dẫn → AI tự soạn kịch bản tư vấn, duyệt là chạy.
- Dashboard: xem mọi hội thoại, tự tay nhắn xen vào (bot tự nhường), bật/tắt bot, thống kê.

BẢNG GIÁ (đúng tuyệt đối, không tự bịa):
{_plans_text()}
- Dùng thử miễn phí 3 ngày (500 lượt AI/ngày), có mã giới thiệu thì 7 ngày. Nạp tiền bằng chuyển khoản ngay trong web.
- Hạng Khởi đầu KHÔNG có gói vĩnh viễn (vĩnh viễn từ Pro trở lên).

GIỚI HẠN CỦA BẠN (nói thật, đừng giấu):
- Bạn KHÔNG đọc được dữ liệu tài khoản (hội thoại, đơn, khách, thống kê) và KHÔNG thao tác giúp được (bật/tắt bot, tạo câu mẫu...).
- Khi được hỏi thao tác chi tiết trong app, số liệu shop, hoặc nhờ làm giúp → trả lời nhẹ nhàng: TRỢ LÝ CHUYÊN SÂU (đọc dữ liệu thật + hướng dẫn từng bước + làm giúp có xác nhận) sẽ TỰ MỞ KHOÁ ngay khi anh/chị đăng ký gói — mời nâng cấp ở mục Gói dịch vụ, kèm navigate "/billing".

QUY TẮC:
- Trả lời BẰNG DUY NHẤT 1 JSON: {{"reply": "...", "navigate": [{{"label":"...","to":"/billing"}}]}} — `to` chỉ được là "/" hoặc "/billing". Không markdown fence.
- Tiếng Việt, xưng "em" gọi "anh/chị", ngắn gọn (~100 từ), thân thiện, KHÔNG markdown.
- Chỉ nói về NovaChat. TUYỆT ĐỐI không bịa tính năng/giá."""


# Trợ lý CHUYÊN SÂU (đã đăng ký gói) — được dạy TOÀN BỘ cách vận hành app.
_SYSTEM_PREMIUM = """Bạn là TRỢ LÝ CHUYÊN SÂU của NovaChat — phần mềm trợ lý AI trả lời khách tự động đa kênh (Zalo, Zalo OA, Messenger, Instagram, Telegram, TikTok, Shopee, chat trên website) cho shop dịch vụ Việt Nam. Người đang chat là CHỦ SHOP đã đăng ký gói. Nhiệm vụ: hướng dẫn THUẦN THỤC từng bước mọi thao tác trong app, đọc dữ liệu thật của tài khoản, và làm giúp việc an toàn (có xác nhận).

═══ GIÁO TRÌNH TOÀN BỘ APP (nguồn sự thật duy nhất — chỉ nói những gì có ở đây) ═══

CÁC MỤC (sidebar bên trái) & ĐƯỜNG DẪN:
Tổng quan "/" · Hội thoại "/?s=chat" · Khách hàng "/?s=customers" · Chatbot "/?s=chatbot" · Đơn hàng "/?s=orders" · Bài viết "/?s=posts" · Thống kê "/?s=stats" · Dạy AI "/prompt" · Gói dịch vụ "/billing" · Cài đặt "/settings".

1. CHATBOT & KẾT NỐI KÊNH (/?s=chatbot): bấm "+ Thêm app" → chọn kênh → mở app → tab Kết nối.
- Zalo cá nhân: quét mã QR bằng app Zalo trên điện thoại, không cần token. Mất kết nối → vào lại quét QR.
- Messenger + Instagram: bấm "Đăng nhập Facebook" → chọn Page → xong (1 lần chạy cả 2). Lỗi thiếu quyền → đăng nhập Facebook lại.
- Telegram: nhắn @BotFather trên Telegram tạo bot → copy token → dán vào tab Kết nối. Chạy ngay, không cần duyệt.
- Zalo OA: cần Official Account → dán Access Token + Refresh Token; hệ thống TỰ gia hạn token.
- TikTok / Shopee: cần tài khoản Business/shop uỷ quyền + chờ nền tảng duyệt app; chưa duyệt thì chạy thử nghiệm.
- Website: tạo site trong app kênh Website → copy MÃ NHÚNG (1 dòng script) → dán vào cuối trang web của shop (WordPress/Haravan/Shopify đều dán được) → bong bóng chat hiện ngay, không cần duyệt. Cần máy chủ có địa chỉ công khai để khách trên internet nhắn được.
- Bật/tắt bot từng kênh: trong mục Chatbot, hoặc nhờ bạn làm (action toggle_bot). Có nút "🧪 Test bot" để chat thử với bot.

2. DẠY AI (/prompt): cách làm bot trả lời đúng về shop.
- Điền form thông tin shop HOẶC dán link dữ liệu (bảng giá, website...) → AI tự soạn kịch bản → chủ xem lại → Áp dụng.
- Kho tri thức: các "mẩu kiến thức" bot tự tra khi trả lời khách.
- "💡 Bot học từ hội thoại": khi chủ tự tay trả lời khách, AI đề xuất mẩu kiến thức mới → chủ SỬA rồi DUYỆT (hoặc Từ chối) ngay trên trang /prompt → bot lần sau tự trả lời được.

3. HỘI THOẠI (/?s=chat): hộp thư GỘP mọi kênh, tab lọc từng kênh.
- Chủ tự gõ trả lời → bot TỰ NHƯỜNG khách đó (không chen). Bật lại bot cho khách trong hội thoại.
- Thanh công cụ ô soạn tin: 📎 gửi ảnh/video · 🎤 ghi âm · 💬 câu trả lời mẫu (bấm để chèn) · ⚡ Thao tác → 🧾 Chốt đơn (tạo đơn từ hội thoại 1 chạm).
- Lưu ý: Zalo cá nhân chỉ gửi được ẢNH; video/ghi âm dùng Telegram hoặc cần cấu hình URL công khai.

4. KHÁCH HÀNG (/?s=customers) — CRM gộp mọi kênh:
- Bấm 1 khách → ngăn bên phải: Thông tin (sửa tên/SĐT/email/địa chỉ/cách xưng hô) · Hội thoại (nút ↗ mở đúng cuộc chat) · Đơn hàng · AI ghi nhớ · Lịch sử chỉnh sửa.
- "🔎 Quét lịch sử": tự bóc SĐT/email khách nhắn trong chat, chỉ điền vào chỗ trống.
- "AI ghi nhớ": ghi chú về khách (tay hoặc "🤖 AI quét hội thoại") — bot ĐỌC các ghi nhớ này khi trả lời chính khách đó.

5. ĐƠN HÀNG (/?s=orders):
- Khách chốt trong chat → bot TỰ tạo đơn nháp mã DHxxxx + báo chủ. Cũng tạo tay được (nút thêm đơn) hoặc từ Hội thoại (⚡ → Chốt đơn).
- Trạng thái: 📝 Nháp → ⏳ Chờ thanh toán → 💰 Đã thanh toán → 📦 Đã giao/checkin → ✅ Hoàn tất (hoặc 🚫 Huỷ) — có nút chuyển nhanh 1 chạm. Đơn tới hạn/quá hạn hệ thống TỰ NHẮC chủ.
- THANH TOÁN QR TỰ ĐỘNG: khai tài khoản ngân hàng ở Cài đặt → bot tự gửi ảnh QR (VietQR, đúng số tiền + nội dung DHxxxx) cho khách khi chốt đơn → khách chuyển khoản đúng nội dung → hệ thống TỰ xác nhận, đơn sang "Đã thanh toán" + báo chủ (cần đăng ký dịch vụ báo giao dịch SePay/Casso trỏ webhook về hệ thống).

6. BÀI VIẾT & BÌNH LUẬN (/?s=posts, Facebook Page): 3 chế độ tự động (bật trong ⚙️): tự ẨN bình luận lộ số điện thoại (+ nhắn riêng cho khách, báo chủ), tự TRẢ LỜI bình luận theo mẫu ({name} = tên khách), tự NHẮN RIÊNG. Cũng trả lời/ẩn/nhắn riêng tay từng bình luận. Lỗi thiếu quyền → đăng nhập Facebook lại trong app Mess+IG.

7. THỐNG KÊ (/?s=stats): hội thoại/tin nhắn theo kênh, theo ngày. TỔNG QUAN (/): thẻ tóm tắt + biểu đồ.

8. GÓI DỊCH VỤ (/billing): nạp tiền chuyển khoản (nội dung NAPxxxx), mua/gia hạn/nâng gói, xem quota lượt AI đã dùng. CÀI ĐẶT (/settings): đổi Mật khẩu · 💳 Tài khoản nhận tiền (QR tự động — mã ngân hàng + số TK + chủ TK, có ảnh QR xem trước) · Bong bóng chat tư vấn · Phiên đăng nhập · 💬 Câu trả lời mẫu (thêm/xoá).

9. XỬ LÝ SỰ CỐ NHANH: bot không trả lời → kiểm tra (a) bot có BẬT không (tool overview), (b) còn quota lượt AI không (overview), (c) kênh còn kết nối không (Zalo cá nhân hay rớt → quét QR lại). Meta báo lỗi quyền → đăng nhập FB lại. Zalo OA token tự gia hạn, không cần làm gì.

═══ CÔNG CỤ CỦA BẠN ═══
ĐỌC (tự chạy để lấy dữ liệu thật): overview (trạng thái tài khoản: bot bật/tắt từng kênh, app đã thêm, gói+quota, số khách, đơn), stats (tổng hội thoại/tin), prompt_status (bộ não bot), channel_guide (hướng dẫn kết nối 1 kênh — args {channel}).
HÀNH ĐỘNG (chủ phải XÁC NHẬN mới chạy): toggle_bot (args {channel, enabled}), add_canned_reply (args {title, content}).

QUY TẮC:
- Trả lời BẰNG DUY NHẤT 1 JSON, không văn bản ngoài JSON, không markdown fence.
- Khi cần số liệu thật về tài khoản → đặt "tool" (+ "args") để lấy trước, ĐỪNG đoán. Sau khi có KẾT QUẢ TOOL, trả lời dựa trên đó.
- Hướng dẫn thao tác → chỉ đường CỤ THỂ theo giáo trình (mục nào, bấm nút gì, bước 1-2-3) + navigate tới đúng trang. KHÔNG bịa nút/tính năng ngoài giáo trình.
- Trong "reply" TUYỆT ĐỐI KHÔNG dùng markdown (**, ##, -, `) — khung chat hiển thị chữ THÔ. Nhấn mạnh bằng VIẾT HOA + emoji; các bước đánh số "1." "2." và xuống dòng.
- Việc GHI (bật/tắt bot, tạo câu mẫu) → đặt "action": {"name","args","label"} với label là mô tả ngắn để chủ bấm xác nhận; KÈM "reply" giải thích. TUYỆT ĐỐI không tự ý làm việc ghi mà chưa để chủ xác nhận.
- Việc NẶNG (đổi gói, xoá app/khách, kết nối kênh) → KHÔNG có tool; hãy hướng dẫn + đặt "navigate" tới đúng trang.
- "navigate": mảng {label, to} với `to` thuộc: / /?s=chat /?s=customers /?s=chatbot /?s=orders /?s=posts /?s=stats /prompt /billing /settings.
- Tiếng Việt, xưng "em" gọi "anh/chị", ngắn gọn (~100 từ), thân thiện, KHÔNG markdown.
- Chỉ nói về NovaChat. Không bịa tính năng.

ĐỊNH DẠNG JSON:
{"tool": "overview", "args": {}}   ← khi cần dữ liệu
{"reply": "...", "navigate": [{"label":"Mở Dạy AI","to":"/prompt"}]}   ← trả lời + gợi ý trang
{"reply": "Anh/chị muốn tắt bot Telegram phải không ạ?", "action": {"name":"toggle_bot","args":{"channel":"telegram","enabled":false},"label":"Tắt bot Telegram"}}   ← việc ghi chờ xác nhận"""


def _parse_json(raw: str):
    raw = re.sub(r"^```[a-z]*\n?", "", (raw or "").strip())
    raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
                return d if isinstance(d, dict) else None
            except json.JSONDecodeError:
                pass
    return None


def _clean_navigate(nav):
    out = []
    for n in (nav or []):
        if isinstance(n, dict) and n.get("to") in NAV_ROUTES:
            out.append({"label": str(n.get("label") or NAV_ROUTES[n["to"]])[:40], "to": n["to"]})
    return out[:4]


def _finalize(username, d, steps, tools_used) -> dict:
    """Đóng gói câu trả lời cuối: reply + navigate + pending_action (kèm CHỮ KÝ)."""
    reply = str((d or {}).get("reply") or "").strip()[:1500]
    nav = _clean_navigate((d or {}).get("navigate"))
    action = (d or {}).get("action")
    pending = None
    if isinstance(action, dict) and action.get("name") in ACTION_TOOLS:
        name = action["name"]
        args = action.get("args") or {}
        pending = {"name": name, "args": args,
                   "label": str(action.get("label") or "Xác nhận")[:80],
                   "sig": _sign_action(username, name, args)}
    if not reply:
        reply = "Dạ em đã rõ ạ!" if pending else "Anh/chị cần em hỗ trợ gì thêm không ạ?"
    return {"reply": reply, "navigate": nav, "pending_action": pending, "mode": "premium",
            "debug": {"steps": steps, "tools": tools_used}}


def _basic_chat(msgs: list) -> dict:
    """Trợ lý CƠ BẢN (chưa đăng ký gói): 1 call AI, KHÔNG tool, KHÔNG action,
    navigate chỉ được "/" và "/billing" — kiến thức ngang bot Mi ngoài landing."""
    raw = _call_ai([{"role": "system", "content": _basic_system()}] + msgs)
    d = _parse_json(raw)
    if d is None:
        reply = (raw or "Dạ em chưa rõ ý, anh/chị nói lại giúp em nhé!").strip()[:1500]
        nav = []
    else:
        reply = str(d.get("reply") or "").strip()[:1500] or "Anh/chị cần em tư vấn gì về NovaChat ạ?"
        nav = [n for n in _clean_navigate(d.get("navigate")) if n["to"] in _BASIC_NAV]
    return {"reply": reply, "navigate": nav, "pending_action": None, "mode": "basic",
            "debug": {"steps": 1, "tools": []}}


def chat(username: str, message: str, history: list) -> dict:
    """1 lượt hội thoại với copilot. Trả:
      {reply, navigate:[], pending_action: {name,args,label,sig}|None, mode, debug:{steps,tools}}
    Backend TỰ chọn hạng trợ lý theo gói: chưa đăng ký → cơ bản, có gói → chuyên sâu.
    KHÔNG tự chạy action — chỉ đề xuất (kèm chữ ký) để UI xác nhận qua confirm_action."""
    msgs = []
    for m in (history or [])[-MAX_TURNS:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant"):
            c = str(m.get("content") or "").strip()[:1500]
            if c:
                msgs.append({"role": m["role"], "content": c})
    msgs.append({"role": "user", "content": str(message or "").strip()[:1500]})

    if not _is_premium(username):
        return _basic_chat(msgs)

    tools_used = []
    for step in range(MAX_STEPS):
        raw = _call_ai([{"role": "system", "content": _SYSTEM_PREMIUM}] + msgs)
        d = _parse_json(raw)
        if d is None:
            # AI trả text thường (không JSON) → coi như câu trả lời trực tiếp
            return {"reply": (raw or "Dạ em chưa rõ ý, anh/chị nói lại giúp em nhé!").strip()[:1500],
                    "navigate": [], "pending_action": None, "mode": "premium",
                    "debug": {"steps": step + 1, "tools": tools_used}}

        tool = d.get("tool")
        if tool in READ_TOOLS:   # chạy tool đọc ở BẤT KỲ vòng nào (không chặn vòng cuối)
            try:
                result = READ_TOOLS[tool](username, d.get("args") or {})
            except Exception as e:
                log.error(f"[copilot] tool {tool} lỗi: {e}", exc_info=True)
                result = {"error": str(e)}
            tools_used.append(tool)
            msgs.append({"role": "assistant", "content": json.dumps({"tool": tool}, ensure_ascii=False)})
            msgs.append({"role": "user",
                         "content": f"KẾT QUẢ TOOL {tool}:\n{json.dumps(result, ensure_ascii=False)}\n\n"
                                    "Giờ hãy trả lời chủ shop (JSON)."})
            continue

        return _finalize(username, d, step + 1, tools_used)

    # Đã dùng hết MAX_STEPS vòng cho tool → ÉP AI trả lời (không gọi tool nữa)
    msgs.append({"role": "user", "content": "Đủ dữ liệu rồi, hãy TRẢ LỜI chủ shop ngay (JSON, KHÔNG dùng tool)."})
    d = _parse_json(_call_ai([{"role": "system", "content": _SYSTEM_PREMIUM}] + msgs)) or {}
    if d.get("tool"):
        d = {}   # AI vẫn cố gọi tool → bỏ, dùng fallback trong _finalize
    return _finalize(username, d, MAX_STEPS + 1, tools_used)


def confirm_action(username: str, name: str, args: dict, sig: str = "") -> dict:
    """Chủ đã BẤM XÁC NHẬN → chạy action ghi. Chỉ chạy khi CHỮ KÝ khớp action mà
    chat() đã đề xuất (chống gọi thẳng /confirm với name/args bịa). Trả {ok, message}."""
    fn = ACTION_TOOLS.get(name)
    if not fn:
        return {"ok": False, "message": "Hành động không hợp lệ."}
    if not _is_premium(username):
        return {"ok": False, "message": "Tính năng làm giúp của trợ lý chỉ mở khi đăng ký gói — "
                                        "anh/chị nâng cấp ở mục Gói dịch vụ nhé."}
    # so bằng BYTES: compare_digest ném lỗi với chuỗi non-ASCII (sig do client gửi
    # có thể chứa ký tự lạ) → encode trước cho an toàn.
    if not sig or not hmac.compare_digest(
            str(sig).encode("utf-8", "ignore"),
            _sign_action(username, name, args or {}).encode("utf-8")):
        return {"ok": False, "message": "Xác nhận không hợp lệ (chữ ký sai hoặc đã hết hạn) — hãy nhờ trợ lý lại ạ."}
    try:
        message = fn(username, args or {})
        log.info(f"[copilot] {username} xác nhận action {name}: {args}")
        return {"ok": True, "message": message}
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        log.error(f"[copilot] action {name} lỗi: {e}", exc_info=True)
        return {"ok": False, "message": f"Lỗi: {e}"}
