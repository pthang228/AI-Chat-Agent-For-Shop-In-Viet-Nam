import os
from pathlib import Path
from dotenv import load_dotenv

# Gốc dự án = thư mục chứa app/ (file này: app/core/config.py → lên 3 cấp)
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
MEDIA_DIR = BASE_DIR / "media"

# Nạp .env từ gốc dự án (đúng dù chạy từ thư mục nào)
load_dotenv(BASE_DIR / ".env")


def _resolve(value: str, default: str) -> str:
    """Đường dẫn tương đối → tính từ gốc dự án; tuyệt đối → giữ nguyên."""
    p = Path(value or default)
    return str(p if p.is_absolute() else BASE_DIR / p)


class Config:
    # Thư mục
    BASE_DIR  = BASE_DIR
    DATA_DIR  = DATA_DIR
    MEDIA_DIR = MEDIA_DIR
    # SQLite dùng chung (sessions + stats_archive). Đổi qua .env HOMESTAY_DB_PATH
    # (tests đặt biến này để không đụng DB thật).
    DB_PATH   = _resolve(os.getenv("HOMESTAY_DB_PATH"), "data/homestay.db")
    # Phiên Telethon (không kèm .session — Telethon tự thêm)
    TG_SESSION = str(DATA_DIR / "tg_caller_session")

    # Zalo
    ZALO_PHONE    = os.getenv("ZALO_PHONE", "")
    ZALO_PASSWORD = os.getenv("ZALO_PASSWORD", "")
    OWNER_ZALO_ID   = os.getenv("OWNER_ZALO_ID", "")    # Zalo ID tài khoản 1
    OWNER_ZALO_ID_2 = os.getenv("OWNER_ZALO_ID_2", "")  # Zalo ID tài khoản 2
    OWNER_GROUP_ID  = os.getenv("OWNER_GROUP_ID", "")

    # DeepSeek (chính)
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    # Groq (fallback)
    GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")

    # Google Sheets
    GOOGLE_CREDENTIALS_FILE = _resolve(os.getenv("GOOGLE_CREDENTIALS_FILE"), "google_credentials.json")
    HARU_SHEET_ID           = os.getenv("HARU_SHEET_ID",  "")   # Haru Staycation
    MOCHI_SHEET_ID          = os.getenv("MOCHI_SHEET_ID", "")   # Mochi Home

    # Telegram — gọi điện qua Telethon
    TELEGRAM_TARGET_ID = os.getenv("TELEGRAM_TARGET_ID", "")  # ID acc nhận cuộc gọi
    # api_id/api_hash để đăng nhập acc gọi (đăng ký riêng ở my.telegram.org).
    # Fallback creds Telegram Desktop công khai (CHỈ để chạy thử — đa khách phải đổi sang của bạn).
    TELEGRAM_API_ID   = int(os.getenv("TELEGRAM_API_ID", "2040"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")

    # Telegram BOT (kênh trả lời khách qua Bot API — KHÁC Telethon ở trên)
    TELEGRAM_BOT_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")       # token từ @BotFather
    TELEGRAM_OWNER_CHAT_ID  = os.getenv("TELEGRAM_OWNER_CHAT_ID", "")   # chat_id chủ (fallback; thường tự bắt qua /start)
    TELEGRAM_OWNER_SETUP_CODE = os.getenv("TELEGRAM_OWNER_SETUP_CODE", "chunha")  # chủ /start <mã> để tự đăng ký
    TELEGRAM_API_PORT       = int(os.getenv("TELEGRAM_API_PORT", "5007"))

    # Meta (Facebook Messenger + Instagram DM) — chung 1 app/webhook
    FB_APP_ID            = os.getenv("FB_APP_ID", "")            # ID app (công khai) — cho nút "Kết nối Facebook"
    FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN", "")  # token 1 Page (chế độ single-tenant/test thủ công)
    FB_APP_SECRET        = os.getenv("FB_APP_SECRET", "")         # xác thực chữ ký webhook
    FB_VERIFY_TOKEN      = os.getenv("FB_VERIFY_TOKEN", "haru_verify_token")  # tự đặt, khớp khi đăng ký webhook
    FB_GRAPH_VERSION     = os.getenv("FB_GRAPH_VERSION", "v21.0")
    FB_OWNER_PSID        = os.getenv("FB_OWNER_PSID", "")         # PSID chủ nhà để báo (Meta không có nhóm)
    PUBLIC_BASE_URL      = os.getenv("PUBLIC_BASE_URL", "")       # URL công khai (ngrok/domain) để gửi ảnh + nhận webhook
    META_WEBHOOK_PORT    = int(os.getenv("META_WEBHOOK_PORT", "5006"))
    # Bật kênh Instagram: chỉ TRUE khi app Meta đã setup sản phẩm Instagram +
    # có IG Professional liên kết Page. Bật sớm khi chưa setup → FB Login báo
    # "Invalid Scopes" → HỎNG luôn đăng nhập Messenger. Mặc định TẮT cho an toàn.
    FB_ENABLE_IG         = os.getenv("FB_ENABLE_IG", "false").strip().lower() in ("1", "true", "yes", "on")
    # Instagram qua nhánh "Instagram Login" (graph.instagram.com): gửi DM bằng
    # token IG riêng (lấy từ "Tạo mã" trong use case Instagram), KHÁC token Page
    # của Messenger. Single-tenant: 1 token cho 1 tài khoản IG (đủ cho 1 homestay).
    IG_ACCESS_TOKEN      = os.getenv("IG_ACCESS_TOKEN", "")
    IG_GRAPH_VERSION     = os.getenv("IG_GRAPH_VERSION", "v21.0")

    # TikTok (Business Messaging API) — kênh TikTok DM.
    # LƯU Ý: API nhắn tin TikTok chỉ cấp cho TikTok Business Account + app developer
    # được duyệt (business-api.tiktok.com). Chưa có token → channel chạy MOCK
    # (log thay vì gọi mạng) — giao diện quản lý/hội thoại/thống kê vẫn dùng được.
    TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN", "")   # token 1 tài khoản (.env, single-tenant/test)
    TIKTOK_BUSINESS_ID  = os.getenv("TIKTOK_BUSINESS_ID", "")    # business_id của tài khoản .env
    TIKTOK_API_BASE     = os.getenv("TIKTOK_API_BASE", "https://business-api.tiktok.com/open_api/v1.3")
    TIKTOK_VERIFY_TOKEN = os.getenv("TIKTOK_VERIFY_TOKEN", "haru_tiktok_verify")  # khớp khi khai webhook
    TIKTOK_API_PORT     = int(os.getenv("TIKTOK_API_PORT", "5008"))

    # Shopee Open Platform (open.shopee.com) — app của VENDOR (partner) dùng chung,
    # mỗi shop khách chỉ cần uỷ quyền → shop_id + access_token
    SHOPEE_PARTNER_ID   = os.getenv("SHOPEE_PARTNER_ID", "")
    SHOPEE_PARTNER_KEY  = os.getenv("SHOPEE_PARTNER_KEY", "")
    SHOPEE_API_BASE     = os.getenv("SHOPEE_API_BASE", "https://partner.shopeemobile.com")
    SHOPEE_ACCESS_TOKEN = os.getenv("SHOPEE_ACCESS_TOKEN", "")   # token 1 shop (.env, test)
    SHOPEE_SHOP_ID      = os.getenv("SHOPEE_SHOP_ID", "")
    SHOPEE_API_PORT     = int(os.getenv("SHOPEE_API_PORT", "5009"))

    # Bot
    ROOMS_PHOTOS_DIR  = _resolve(os.getenv("ROOMS_PHOTOS_DIR"), "media/rooms_photos")
    PRICE_PHOTOS_DIR  = _resolve(None, "media/price_photos")
    PHOTO_LIBRARY_DIR = _resolve(os.getenv("PHOTO_LIBRARY_DIR"), "media/photo_library")  # bộ ảnh đặt tên
    REPLY_DELAY      = int(os.getenv("REPLY_DELAY", "2"))
    # Giữ hội thoại khách bao lâu trước khi dọn khỏi tab Khách hàng (giờ).
    # Mặc định 720h = 30 ngày (trước đây 48h → khách im 2 ngày là MẤT).
    # Khi dọn, số liệu vẫn được gấp vào data/stats_archive*.json cho thống kê.
    SESSION_RETENTION_HOURS = int(os.getenv("SESSION_RETENTION_HOURS", "720"))

    # Billing — gói dịch vụ & nạp tiền
    BILLING_PROMO_CODE = os.getenv("BILLING_PROMO_CODE", "")   # mã giới thiệu của bạn → dùng thử 7 ngày (rỗng = tắt)
    BILLING_ADMIN_KEY  = os.getenv("BILLING_ADMIN_KEY", "")    # khoá API admin xác nhận nạp (rỗng = chỉ dùng script)
    BANK_NAME    = os.getenv("BANK_NAME", "")     # vd: Vietcombank
    BANK_ACCOUNT = os.getenv("BANK_ACCOUNT", "")  # số tài khoản nhận tiền
    BANK_HOLDER  = os.getenv("BANK_HOLDER", "")   # tên chủ tài khoản

    # Dashboard web
    DASHBOARD_PORT     = int(os.getenv("DASHBOARD_PORT", "5000"))
    DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")

    @classmethod
    def validate(cls):
        missing = []
        required = [
            ("ZALO_PHONE",    cls.ZALO_PHONE),
            ("ZALO_PASSWORD", cls.ZALO_PASSWORD),
            ("OWNER_ZALO_ID", cls.OWNER_ZALO_ID),
        ]
        if not cls.DEEPSEEK_API_KEY and not cls.GROQ_API_KEY:
            missing.append("DEEPSEEK_API_KEY hoặc GROQ_API_KEY (ít nhất 1 cái)")
        for name, val in required:
            if not val:
                missing.append(name)
        if not cls.HARU_SHEET_ID and not cls.MOCHI_SHEET_ID:
            missing.append("HARU_SHEET_ID hoặc MOCHI_SHEET_ID (ít nhất 1 cái)")
        if missing:
            raise ValueError(f"Thiếu config trong .env: {', '.join(missing)}")
