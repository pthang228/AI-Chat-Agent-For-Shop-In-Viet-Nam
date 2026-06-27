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
    cid = Config.FB_APP_ID
    sec = Config.FB_APP_SECRET
    log.info(f"[Meta oauth] EXCHANGE client_id={cid!r} secret_prefix={sec[:6]!r} secret_len={len(sec)} token_prefix={short_token[:14]!r}")
    try:
        r = requests.get(f"{_graph()}/oauth/access_token", params={
            "grant_type": "fb_exchange_token",
            "client_id": cid,
            "client_secret": sec,
            "fb_exchange_token": short_token,
        }, timeout=30)
        log.info(f"[Meta oauth] EXCHANGE response {r.status_code}: {r.text[:250]}")
        if r.status_code >= 400:
            return short_token
        return r.json().get("access_token") or short_token
    except Exception as e:
        log.error(f"[Meta oauth] exchange lỗi: {e}")
        return short_token


def debug_token(user_token: str) -> dict:
    """Log xem token thuộc về ai + được cấp quyền gì (chẩn đoán 0 page)."""
    info = {}
    try:
        me = requests.get(f"{_graph()}/me", params={
            "access_token": user_token, "fields": "id,name"}, timeout=15).json()
        perms = requests.get(f"{_graph()}/me/permissions", params={
            "access_token": user_token}, timeout=15).json()
        info = {"me": me, "permissions": perms.get("data", perms)}
        log.info(f"[Meta debug] token của: {me} | quyền: {perms.get('data', perms)}")
    except Exception as e:
        log.error(f"[Meta debug] lỗi: {e}")
    return info


PAGE_FIELDS = "id,name,access_token,instagram_business_account{id,username}"


def _get_data(url: str, params: dict) -> list:
    """GET 1 edge có phân trang → trả toàn bộ data (log lỗi nếu có)."""
    out = []
    while url:
        r = requests.get(url, params=params, timeout=30)
        if r.status_code >= 400:
            log.error(f"[Meta oauth] {url.split('/')[-1]} lỗi {r.status_code}: {r.text[:200]}")
            break
        d = r.json()
        out.extend(d.get("data", []))
        url = (d.get("paging") or {}).get("next")
        params = None
    return out


def _page_token(page_id: str, user_token: str):
    """Lấy access_token của 1 Page (cho Page thuộc Business, edge không trả token)."""
    try:
        r = requests.get(f"{_graph()}/{page_id}", params={
            "access_token": user_token, "fields": "access_token"}, timeout=30)
        if r.status_code < 400:
            return r.json().get("access_token")
        log.error(f"[Meta oauth] lấy token page {page_id} lỗi {r.status_code}: {r.text[:200]}")
    except Exception as e:
        log.error(f"[Meta oauth] lấy token page {page_id} lỗi: {e}")
    return None


def list_pages(user_token: str) -> list:
    """Các Page khách quản lý — gộp 2 nguồn:
      1) /me/accounts: Page user trực tiếp là admin
      2) /me/businesses → owned_pages/client_pages: Page thuộc Business Portfolio
         (New Pages Experience — /me/accounts KHÔNG trả về)
    Trả [{id, name, access_token, instagram_business_account{...}}].
    """
    pages: dict = {}

    # 1) Trang user trực tiếp quản trị
    direct = _get_data(f"{_graph()}/me/accounts",
                       {"access_token": user_token, "fields": PAGE_FIELDS, "limit": 100})
    for pg in direct:
        pages[str(pg["id"])] = pg
    log.info(f"[Meta oauth] /me/accounts trả {len(direct)} page")

    # 2) Trang thuộc Business Portfolio
    if not pages:
        bizes = _get_data(f"{_graph()}/me/businesses",
                          {"access_token": user_token, "fields": "id,name", "limit": 50})
        log.info(f"[Meta oauth] /me/businesses trả {len(bizes)} business")
        for biz in bizes:
            bid = biz.get("id")
            for edge in ("owned_pages", "client_pages"):
                for pg in _get_data(f"{_graph()}/{bid}/{edge}",
                                    {"access_token": user_token,
                                     "fields": "id,name,instagram_business_account{id,username}",
                                     "limit": 100}):
                    pid = str(pg["id"])
                    if pid in pages:
                        continue
                    pg["access_token"] = _page_token(pid, user_token)  # token riêng từng Page
                    pages[pid] = pg
        log.info(f"[Meta oauth] Sau khi gộp Business: {len(pages)} page")

    return list(pages.values())


# Field subscribe Ở CẤP PAGE (subscribed_apps) — chỉ là field Messenger hợp lệ.
# LƯU Ý: tin nhắn Instagram KHÔNG đi qua đây mà qua webhook object "instagram"
# (khai ở App Dashboard, subscribe field "messages"). Không nhét field IG vào
# subscribed_apps — Graph trả 400 "invalid subscription field" → hỏng luôn cả
# subscribe `messages` của Page (đã từng vấp khi bật FB_ENABLE_IG).
FB_SUBSCRIBE_FIELDS = "messages,messaging_postbacks,messaging_referrals"


def subscribe_fields() -> str:
    """Field webhook subscribe ở cấp Page (Messenger). IG route ở cấp app."""
    return FB_SUBSCRIBE_FIELDS


def subscribe_page(page_id: str, page_token: str, fields: str = None) -> bool:
    """Đăng ký Page vào webhook của app (để nhận tin nhắn)."""
    if fields is None:
        fields = subscribe_fields()
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
