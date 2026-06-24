"""
Khởi động bot qua kênh Zalo-Node (zca-js, đăng nhập QR).

Kiến trúc:
  [Node zalo-node/server.js : cổng 4000]  ←HTTP→  [Python: file này]
     - QR login, nhận/gửi tin Zalo                  - bridge /incoming → brain
                                                     - ZaloNodeChannel → /send

Chạy:
  1) Terminal 1:  cd zalo-node && npm start         (đăng nhập QR ở http://localhost:4000)
  2) Terminal 2:  python main_node.py               (bật cầu nối + não bộ, cổng 5005)

Biến môi trường (tùy chọn):
  ZALO_NODE_URL   (mặc định http://127.0.0.1:4000)  — địa chỉ Node service
  PY_BRIDGE_PORT  (mặc định 5005)                    — cổng bridge nhận tin từ Node
"""

import os
import sys
import logging

# Ép UTF-8 cho stdout/stderr để in tiếng Việt/emoji không lỗi trên console Windows (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core.conversation import ConversationManager
from app.core.brain import Brain
from app.channels.zalo_node import ZaloNodeChannel
from app.web_api.bridge import create_bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bot.log", encoding="utf-8")],
)
log = logging.getLogger(__name__)


def main():
    account = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    node_url = os.getenv("ZALO_NODE_URL", "http://127.0.0.1:4000")
    bridge_port = int(os.getenv("PY_BRIDGE_PORT", "5005"))

    print("=" * 55)
    print(f"  ZALO-NODE BOT — Tài khoản {account}")
    print("=" * 55)

    conv = ConversationManager(account=account)
    channel = ZaloNodeChannel(node_url=node_url, conv_manager=conv)
    channel.brain = Brain(channel=channel, conv_manager=conv)

    app = create_bridge(channel.brain, conv)

    print(f"✅ Não bộ + cầu nối sẵn sàng")
    print(f"   Node service : {node_url}  (đăng nhập QR tại đây)")
    print(f"   Bridge       : http://127.0.0.1:{bridge_port}/incoming")
    print(f"   Sessions     : {conv._file}")
    print("🤖 Đang chờ tin nhắn khách... Ctrl+C để dừng.\n")

    app.run(host="127.0.0.1", port=bridge_port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
