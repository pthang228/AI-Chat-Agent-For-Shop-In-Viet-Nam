"""
Gọi Graph API phục vụ luồng "Kết nối Facebook" (OAuth) của khách:
  - đổi token ngắn hạn → dài hạn
  - liệt kê các Page khách quản lý (kèm token từng Page + Instagram liên kết)
  - đăng ký (subscribe) Page vào webhook của app để nhận tin

Tách riêng để webhook gọi gọn, và test mock dễ.
"""

import logging

import requests

from app.core.config import Config

log = logging.getLogger(__name__)


def _graph() -> str:
    return f"https://graph.facebook.com/{Config.FB_GRAPH_VERSION}"


def exchange_long_lived_user_token(short_token: str) -> str:
    """Token user ngắn hạn (từ FB Login) → dài hạn (~60 ngày). Lỗi thì trả lại token cũ."""
    try:
        r = requests.get(f"{_graph()}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": Config.FB_APP_ID,
            "client_secret": Config.FB_APP_SECRET,
            "fb_exchange_token": short_token,
        }, timeout=30)
        if r.status_code >= 400:
            log.error(f"[Meta oauth] đổi token dài hạn lỗi {r.status_code}: {r.text[:200]}")
            return short_token
        return r.json().get("access_token") or short_token
    except Exception as e:
        log.error(f"[Meta oauth] exchange lỗi: {e}")
        return short_token


def list_pages(user_token: str) -> list:
    """Các Page khách quản lý: [{id, name, access_token, instagram_business_account{id,username}}]."""
    out, url = [], f"{_graph()}/me/accounts"
    params = {
        "access_token": user_token,
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "limit": 100,
    }
    while url:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code >= 400:
            log.error(f"[Meta oauth] list pages lỗi {r.status_code}: {r.text[:200]}")
            break
        d = r.json()
        out.extend(d.get("data", []))
        url = (d.get("paging") or {}).get("next")
        params = None  # link 'next' đã kèm sẵn tham số
    return out


def subscribe_page(page_id: str, page_token: str,
                   fields: str = "messages,messaging_postbacks,messaging_referrals") -> bool:
    """Đăng ký Page vào webhook của app (để nhận tin nhắn)."""
    try:
        r = requests.post(f"{_graph()}/{page_id}/subscribed_apps", params={
            "access_token": page_token,
            "subscribed_fields": fields,
        }, timeout=30)
        if r.status_code >= 400:
            log.error(f"[Meta subscribe] {page_id} lỗi {r.status_code}: {r.text[:200]}")
            return False
        return bool(r.json().get("success", True))
    except Exception as e:
        log.error(f"[Meta subscribe] {page_id} lỗi: {e}")
        return False
