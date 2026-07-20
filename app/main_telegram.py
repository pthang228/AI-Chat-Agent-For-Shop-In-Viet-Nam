"""
Khởi động bot kênh Telegram (Bot API, long-polling) — ĐA KHÁCH.

Mỗi homestay 1 bot token (dán trong web → lưu data/telegram_bots.json). Mỗi bot
1 poller riêng. Bot .env (TELEGRAM_BOT_TOKEN, nếu có) chạy như "bot mặc định".

KHÔNG cần public URL/webhook (long-polling) → chạy thẳng trên máy, người lạ nhắn
được NGAY (Telegram không có App Review như Meta).

Chạy (TỪ GỐC):  python -m app.main_telegram     (Flask API cổng 5007)
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
from app.core.telegram_store import TelegramStore
from app.channels.telegram import TelegramChannel
from app.web_api.telegram_api import create_telegram_api, start_poller

from app.core.logging_setup import setup_logging
setup_logging("bot_telegram.log")
log = logging.getLogger(__name__)


def main():
    port = Config.TELEGRAM_API_PORT
    conv = ConversationManager(account="telegram")   # data/sessions_telegram.json
    store = TelegramStore()
    channel = TelegramChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_telegram_api(channel.brain, conv, channel, store)

    bots = store.all_bots()

    print("=" * 55)
    print("  TELEGRAM BOT (đa khách)")
    print("=" * 55)
    print(f"  API        : http://0.0.0.0:{port}  (/tg/connect, /tg/bots, /tg/conversations)")
    print(f"  Bot đã nối : {len(bots)} (dán token thêm trong web)")
    print(f"  Bot .env   : {'(có)' if Config.TELEGRAM_BOT_TOKEN else '(không)'}")
    print(f"  Mã chủ     : /start {Config.TELEGRAM_OWNER_SETUP_CODE}  (hoặc /chunha)")
    print(f"  Database   : {conv._db.path} (account={conv._account})")
    print("=" * 55)

    # Bật poller cho từng bot đã lưu (đa khách)
    for bot_id, token in bots:
        start_poller(bot_id, token, bot_id, channel.brain, conv, store)
    # Bot .env (mặc định, tương thích cũ) — user_id 'tg:<chat>'
    if Config.TELEGRAM_BOT_TOKEN:
        start_poller("__env__", Config.TELEGRAM_BOT_TOKEN, None, channel.brain, conv, store)

    if bots or Config.TELEGRAM_BOT_TOKEN:
        print("🤖 Đang lắng nghe Telegram (long-polling)... Ctrl+C để dừng.\n")
    else:
        print("⚠️  Chưa có bot nào. Vào web → kênh Telegram → dán token bot (@BotFather).\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
