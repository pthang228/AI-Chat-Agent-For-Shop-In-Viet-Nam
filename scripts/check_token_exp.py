"""Xem token Page đã lưu sống tới bao giờ (expires_at) — chẩn đoán token ngắn hạn."""
import sys, time, datetime
sys.path.insert(0, ".")
import requests
from app.core.meta_store import MetaStore
from app.core.config import Config

PAGE_ID = "592025713991892"
tok = MetaStore().get_token(PAGE_ID)
gv = Config.FB_GRAPH_VERSION
app_token = f"{Config.FB_APP_ID}|{Config.FB_APP_SECRET}"
r = requests.get(f"https://graph.facebook.com/{gv}/debug_token",
                 params={"input_token": tok, "access_token": app_token}, timeout=30)
d = r.json().get("data", {})
exp = d.get("expires_at", None)
print("HTTP:", r.status_code)
print("Loại token :", d.get("type"))
print("Hợp lệ     :", d.get("is_valid"))
if exp == 0 or exp is None:
    print("Hết hạn    : KHÔNG hết hạn (vĩnh viễn) ✅")
else:
    dt = datetime.datetime.fromtimestamp(exp)
    left = (exp - time.time()) / 60
    print(f"Hết hạn lúc: {dt}  (còn ~{left:.0f} phút)")
print("Scopes     :", ",".join(d.get("scopes", [])))
