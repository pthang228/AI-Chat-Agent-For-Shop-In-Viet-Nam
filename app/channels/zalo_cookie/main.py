"""
Khởi động Zalo Homestay Bot.
Chạy acc 1: python main.py
Chạy acc 2: python main.py 2
"""

import sys
import json
import logging
import threading
from pathlib import Path
from app.core.config import Config
from app.channels.zalo_cookie import bot as bot_module
from app.channels.zalo_cookie.bot import ZaloChannel
from app.core.brain import Brain
from app.core.conversation import ConversationManager

log = logging.getLogger(__name__)


def load_session(account: int = 1) -> tuple[dict, str]:
    """Đọc cookie + imei từ file zalo_cookies.json (hoặc zalo_cookies_2.json)."""
    filename = "zalo_cookies.json" if account == 1 else f"zalo_cookies_{account}.json"
    cookie_file = Config.DATA_DIR / filename
    if not cookie_file.exists():
        print(f"❌ Chưa có file {filename}")
        print("👉 Chạy trước:  python get_zalo_id.py  để tạo file cookie.")
        exit(1)
    with open(cookie_file, encoding="utf-8") as f:
        data = json.load(f)
    # Hỗ trợ cả format cũ (dict cookie thẳng) và mới (có key "cookies"+"imei")
    if "cookies" in data:
        return data["cookies"], data.get("imei", "")
    return data, ""


def main():
    account = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print("=" * 50)
    print(f"  ZALO HOMESTAY BOT — Tài khoản {account}")
    print("=" * 50)

    try:
        Config.validate()
    except ValueError as e:
        print(f"\n❌ LỖI CONFIG: {e}")
        print("👉 Kiểm tra file .env\n")
        return

    print("✅ Config OK")

    # Khởi tạo ConversationManager đúng account trước khi bot chạy
    # (bot.py tạo conv_manager mặc định account=1; ghi đè ở đây để acc 2 dùng sessions_2.json)
    conv = ConversationManager(account=account)
    bot_module.conv_manager = conv   # để dashboard.py đọc đúng instance

    cookies, imei = load_session(account)
    print(f"✅ Cookie OK ({len(cookies)} mục)")

    # Kênh Zalo + "não bộ" dùng chung. Brain ra lệnh, ZaloChannel gửi tin.
    bot = ZaloChannel(
        phone="",
        password="",
        imei=imei or None,
        cookies=cookies,
        account=account,
        conv_manager=conv,
    )
    bot.brain = Brain(channel=bot, conv_manager=conv)

    my_uid = bot.uid()
    print(f"✅ Đăng nhập Zalo thành công — UID: {my_uid}")
    print(f"   OWNER_ZALO_ID trong .env : {Config.OWNER_ZALO_ID}")
    print(f"   Trùng nhau (tự nhắn)     : {my_uid == Config.OWNER_ZALO_ID}")

    # Gửi tin nhắn test vào nhóm
    from zlapi.models import Message, ThreadType
    if Config.OWNER_GROUP_ID:
        try:
            bot.sendMessage(
                Message(text="✅ Bot khởi động thành công! Sẵn sàng nhận thông báo booking."),
                Config.OWNER_GROUP_ID,
                ThreadType.GROUP
            )
            print(f"✅ Đã gửi tin test vào nhóm {Config.OWNER_GROUP_ID}")
        except Exception as e:
            print(f"❌ Gửi tin test vào nhóm THẤT BẠI: {e}")

    # Khởi động dashboard web (daemon thread)
    # Mỗi account dùng port riêng: acc 1 → DASHBOARD_PORT, acc 2 → DASHBOARD_PORT+1, ...
    dashboard_port = Config.DASHBOARD_PORT + (account - 1)
    from dashboard import start_dashboard
    threading.Thread(
        target=start_dashboard,
        args=(dashboard_port,),
        daemon=True,
        name="dashboard",
    ).start()
    print(f"🌐 Dashboard acc {account}: http://localhost:{dashboard_port}")
    if Config.DASHBOARD_PASSWORD:
        print(f"   Mật khẩu : (xem DASHBOARD_PASSWORD trong .env)")
    else:
        print(f"   ⚠️  Chưa đặt DASHBOARD_PASSWORD — không yêu cầu đăng nhập")

    print("🤖 Bot đang chạy... Nhấn Ctrl+C để dừng.\n")

    try:
        bot.listen()
    except KeyboardInterrupt:
        print("\n⛔ Bot đã dừng.")


if __name__ == "__main__":
    main()
