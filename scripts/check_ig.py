"""Kiểm tra nhanh: Page Haru đã liên kết Instagram chưa (gọi Graph bằng token đã lưu)."""
import sys
sys.path.insert(0, ".")
import requests
from app.core.meta_store import MetaStore
from app.core.config import Config

PAGE_ID = "592025713991892"
store = MetaStore()
tok = store.get_token(PAGE_ID)
print("Có token Page:", bool(tok))
if not tok:
    sys.exit("Chưa có token Page trong meta_pages.json")

gv = Config.FB_GRAPH_VERSION
r = requests.get(
    f"https://graph.facebook.com/{gv}/{PAGE_ID}",
    params={
        "access_token": tok,
        "fields": "name,instagram_business_account{id,username},connected_instagram_account{id,username}",
    },
    timeout=30,
)
print("HTTP:", r.status_code)
print(r.text[:800])
