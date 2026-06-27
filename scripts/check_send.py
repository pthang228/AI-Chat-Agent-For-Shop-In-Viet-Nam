"""Thử gửi 1 tin Messenger bằng token Page đã lưu → xem Graph trả gì."""
import sys
sys.path.insert(0, ".")
import requests
from app.core.meta_store import MetaStore
from app.core.config import Config

PAGE_ID = "592025713991892"
PSID = "23906725982269332"   # khách đã nhắn Messenger
tok = MetaStore().get_token(PAGE_ID)
gv = Config.FB_GRAPH_VERSION
r = requests.post(
    f"https://graph.facebook.com/{gv}/me/messages",
    params={"access_token": tok},
    json={"recipient": {"id": PSID}, "message": {"text": "test gửi từ bot ✅"}, "messaging_type": "RESPONSE"},
    timeout=30,
)
print("HTTP:", r.status_code)
print(r.text[:600])
