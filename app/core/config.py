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

    # Bot
    ROOMS_PHOTOS_DIR  = _resolve(os.getenv("ROOMS_PHOTOS_DIR"), "media/rooms_photos")
    PRICE_PHOTOS_DIR  = _resolve(None, "media/price_photos")
    REPLY_DELAY      = int(os.getenv("REPLY_DELAY", "2"))

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
