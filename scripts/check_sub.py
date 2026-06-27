"""Xem Page đang subscribe field webhook gì (chẩn đoán không nhận được tin)."""
import sys
sys.path.insert(0, ".")
import requests
from app.core.meta_store import MetaStore
from app.core.config import Config

PAGE_ID = "592025713991892"
tok = MetaStore().get_token(PAGE_ID)
gv = Config.FB_GRAPH_VERSION
r = requests.get(
    f"https://graph.facebook.com/{gv}/{PAGE_ID}/subscribed_apps",
    params={"access_token": tok}, timeout=30,
)
print("subscribed_apps HTTP:", r.status_code)
print(r.text[:800])
