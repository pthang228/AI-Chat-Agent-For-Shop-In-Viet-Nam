"""
Khởi động kênh Webchat — widget nhúng vào WEBSITE của khách hàng (đa khách).

Chủ shop tạo site trong web (kênh Website) → nhận mã nhúng 1 dòng <script>
dán vào web của họ → khách web nhắn là bot trả lời ngay. KHÔNG cần nền tảng
nào duyệt, không webhook bên ngoài — widget gọi thẳng về server này.
Chạy thật cho web khách trên internet cần PUBLIC_BASE_URL (domain/tunnel).

Chạy (TỪ GỐC):  python -m app.main_webchat     (Flask API cổng 5011)
"""

import sys
import logging

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.brain import Brain
from app.core.webchat_store import WebChatStore
from app.channels.webchat import WebChatChannel
from app.web_api.webchat_api import create_webchat_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_webchat.log", encoding="utf-8")],
)
log = logging.getLogger(__name__)


def main():
    port = Config.WEBCHAT_API_PORT
    conv = ConversationManager(account="webchat")   # sessions account=webchat trong SQLite
    store = WebChatStore()
    channel = WebChatChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_webchat_api(channel.brain, conv, channel, store)

    sites = store.list_sites()

    print("=" * 55)
    print("  WEBCHAT BOT (widget nhúng website khách hàng)")
    print("=" * 55)
    print(f"  API         : http://0.0.0.0:{port}  (/webchat/sites, /webchat/pub/send)")
    print(f"  Widget      : <PUBLIC_BASE_URL hoặc host>/widget.js?data-site=<id>")
    print(f"  Site đã tạo : {len(sites)} (tạo thêm trong web → kênh Website)")
    print(f"  Public URL  : {Config.PUBLIC_BASE_URL or '(chưa có — chỉ chạy nội bộ/LAN)'}")
    print(f"  Database    : {conv._db.path} (account={conv._account})")
    print("=" * 55)

    if not sites:
        print("⚠️  Chưa có site nào. Vào web → kênh Website → Tạo mã nhúng.\n")
    else:
        print("🤖 Đang chờ khách web nhắn qua widget... Ctrl+C để dừng.\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
