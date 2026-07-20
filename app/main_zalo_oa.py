"""
Khởi động bot kênh Zalo OA (Official Account API v3, webhook) — ĐA KHÁCH.

Mỗi khách hàng 1 OA uỷ quyền (dán oa_id + access_token + refresh_token trong
web → data/zalo_oa_accounts.json). Zalo đẩy tin về webhook /zalooa/webhook →
cần PUBLIC_BASE_URL (ngrok, dùng chung domain với Meta) khi chạy thật.
Access token OA sống ~25h → hệ thống TỰ refresh bằng refresh_token.
Chưa có token → channel chạy MOCK, giao diện quản lý vẫn dùng được.

Chạy (TỪ GỐC):  python -m app.main_zalo_oa     (Flask API cổng 5010)
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
from app.core.zalo_oa_store import ZaloOAStore
from app.channels.zalo_oa import ZaloOAChannel
from app.web_api.zalo_oa_api import create_zalo_oa_api

from app.core.logging_setup import setup_logging
setup_logging("bot_zalo_oa.log")
log = logging.getLogger(__name__)


def main():
    port = Config.ZALO_OA_API_PORT
    conv = ConversationManager(account="zalooa")   # sessions account=zalooa trong SQLite
    store = ZaloOAStore()
    channel = ZaloOAChannel(store=store, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)
    app = create_zalo_oa_api(channel.brain, conv, channel, store)

    oas = store.list_oas()

    print("=" * 55)
    print("  ZALO OA BOT (đa khách)")
    print("=" * 55)
    print(f"  API         : http://0.0.0.0:{port}  (/zalooa/connect, /zalooa/conversations)")
    print(f"  Webhook     : <PUBLIC_BASE_URL>/zalooa/webhook  (khai trên developers.zalo.me)")
    print(f"  OA đã nối   : {len(oas)} (dán oa_id + access_token thêm trong web)")
    print(f"  App .env    : {'(có)' if Config.ZALO_OA_APP_ID else '(không — chạy mock)'}")
    print(f"  Database    : {conv._db.path} (account={conv._account})")
    print("=" * 55)

    if not oas and not Config.ZALO_OA_ACCESS_TOKEN:
        print("⚠️  Chưa có OA nào. Vào web → kênh Zalo OA → dán access token.\n")
    else:
        print("🤖 Đang chờ Zalo đẩy tin về webhook... Ctrl+C để dừng.\n")

    from app.web_api.serve import run
    run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
