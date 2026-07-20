"""
Khởi động bot kênh TikTok (Business Messaging API, webhook) — ĐA KHÁCH.

Mỗi homestay 1 TikTok Business Account (dán access token trong web →
data/tiktok_accounts.json). TikTok đẩy tin về webhook /tiktok/webhook →
cần PUBLIC_BASE_URL (ngrok, dùng chung domain với Meta) khi chạy thật.
Chưa có token → channel chạy MOCK, giao diện quản lý vẫn dùng được.

Chạy (TỪ GỐC):  python -m app.main_tiktok     (Flask API cổng 5008)
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
from app.core.tiktok_store import TikTokStore
from app.channels.tiktok import TikTokChannel
from app.web_api.tiktok_api import create_tiktok_api

from app.core.logging_setup import setup_logging
setup_logging("bot_tiktok.log")
log = logging.getLogger(__name__)


def main():
    port = Config.TIKTOK_API_PORT
    conv = ConversationManager(account="tiktok")   # data/sessions_tiktok.json
    store = TikTokStore()
    channel = TikTokChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_tiktok_api(channel.brain, conv, channel, store)

    accounts = store.list_accounts()

    print("=" * 55)
    print("  TIKTOK BOT (đa khách)")
    print("=" * 55)
    print(f"  API         : http://0.0.0.0:{port}  (/tiktok/connect, /tiktok/conversations)")
    print(f"  Webhook     : <PUBLIC_BASE_URL>/tiktok/webhook  (verify: {Config.TIKTOK_VERIFY_TOKEN})")
    print(f"  Account nối : {len(accounts)} (dán access token thêm trong web)")
    print(f"  Token .env  : {'(có)' if Config.TIKTOK_ACCESS_TOKEN else '(không — chạy mock)'}")
    print(f"  Database    : {conv._db.path} (account={conv._account})")
    print("=" * 55)

    if not accounts and not Config.TIKTOK_ACCESS_TOKEN:
        print("⚠️  Chưa có account nào. Vào web → kênh TikTok → dán access token.\n")
    else:
        print("🤖 Đang chờ TikTok đẩy tin về webhook... Ctrl+C để dừng.\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
