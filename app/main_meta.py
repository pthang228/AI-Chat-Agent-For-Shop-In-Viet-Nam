"""
Khởi động bot kênh Meta — Facebook Messenger + Instagram DM (chung 1 webhook).

Kiến trúc:
  [Meta Cloud]  ←HTTPS(webhook)→  [Python: file này]
     - khách nhắn Page/IG          - meta_webhook /fb/webhook → brain
     - Graph API gửi tin lại        - MetaChannel → POST /me/messages

Chạy:
  1) Lộ máy local ra HTTPS:   ngrok http 5006     (hoặc cloudflared)  → copy URL https
     Đặt PUBLIC_BASE_URL trong .env = URL đó (để gửi ảnh + khai webhook).
  2) python -m app.main_meta                       (mặc định cổng 5006)
  3) Khai webhook ở Meta Developers: Callback = <PUBLIC_BASE_URL>/fb/webhook,
     Verify token = FB_VERIFY_TOKEN, subscribe sự kiện messages.

Chưa có FB_PAGE_ACCESS_TOKEN → chạy ở CHẾ ĐỘ MOCK (chỉ log, không gọi Graph API).
"""

import sys
import logging

# Ép UTF-8 cho stdout/stderr (console Windows cp1252 hay lỗi emoji/tiếng Việt)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.config import Config
from app.core.conversation import ConversationManager
from app.core.brain import Brain
from app.core.meta_store import MetaStore
from app.channels.meta import MetaChannel
from app.web_api.meta_webhook import create_meta_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_meta.log", encoding="utf-8")],
)
log = logging.getLogger(__name__)


def main():
    port = Config.META_WEBHOOK_PORT

    # Sessions RIÊNG cho Meta (account="meta" trong SQLite) để không đụng kênh Zalo
    conv = ConversationManager(account="meta")
    store = MetaStore()   # kho token đa Page (khách kết nối qua UI)
    channel = MetaChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_meta_webhook(channel.brain, conv, store)

    print("=" * 55)
    print("  META BOT — Facebook Messenger + Instagram")
    print("=" * 55)
    print(f"  Webhook    : GET/POST  http://0.0.0.0:{port}/fb/webhook")
    print(f"  Media      : http://0.0.0.0:{port}/media/...")
    print(f"  App ID     : {Config.FB_APP_ID or '(CHƯA có → nút Kết nối FB chưa chạy được)'}")
    print(f"  Pages đã nối: {len(store.list_pages())}")
    print(f"  Token .env : {'(có)' if Config.FB_PAGE_ACCESS_TOKEN else '(không — dùng token theo Page từ UI)'}")
    print(f"  IG token   : {'(có)' if Config.IG_ACCESS_TOKEN else '(CHƯA — gửi DM Instagram sẽ MOCK; điền IG_ACCESS_TOKEN vào .env)'}")
    print(f"  Public URL : {Config.PUBLIC_BASE_URL or '(chưa đặt → ảnh sẽ KHÔNG gửi được)'}")
    print(f"  Verify tok : {Config.FB_VERIFY_TOKEN}")
    print(f"  Database   : {conv._db.path} (account={conv._account})")
    print("=" * 55)
    print("🤖 Đang chờ tin từ Messenger/Instagram... Ctrl+C để dừng.\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
