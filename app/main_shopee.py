"""
Khởi động bot kênh Shopee (Open Platform sellerchat, webhook push) — ĐA KHÁCH.

Mỗi shop 1 Shopee Shop uỷ quyền (dán shop_id + access_token trong web →
data/shopee_shops.json). Shopee đẩy tin về webhook /shopee/webhook →
cần PUBLIC_BASE_URL (ngrok, dùng chung domain với Meta) khi chạy thật.
Chưa có token → channel chạy MOCK, giao diện quản lý vẫn dùng được.

Chạy (TỪ GỐC):  python -m app.main_shopee     (Flask API cổng 5009)
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
from app.core.shopee_store import ShopeeStore
from app.channels.shopee import ShopeeChannel
from app.web_api.shopee_api import create_shopee_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot_shopee.log", encoding="utf-8")],
)
log = logging.getLogger(__name__)


def main():
    port = Config.SHOPEE_API_PORT
    conv = ConversationManager(account="shopee")   # sessions account=shopee trong SQLite
    store = ShopeeStore()
    channel = ShopeeChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_shopee_api(channel.brain, conv, channel, store)

    shops = store.list_shops()

    print("=" * 55)
    print("  SHOPEE BOT (đa khách)")
    print("=" * 55)
    print(f"  API         : http://0.0.0.0:{port}  (/shopee/connect, /shopee/conversations)")
    print(f"  Webhook     : <PUBLIC_BASE_URL>/shopee/webhook  (khai trên open.shopee.com)")
    print(f"  Shop nối    : {len(shops)} (dán shop_id + access_token thêm trong web)")
    print(f"  Partner .env: {'(có)' if Config.SHOPEE_PARTNER_ID else '(không — chạy mock)'}")
    print(f"  Database    : {conv._db.path} (account={conv._account})")
    print("=" * 55)

    if not shops and not Config.SHOPEE_ACCESS_TOKEN:
        print("⚠️  Chưa có shop nào. Vào web → kênh Shopee → dán shop_id + access token.\n")
    else:
        print("🤖 Đang chờ Shopee đẩy tin về webhook... Ctrl+C để dừng.\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
