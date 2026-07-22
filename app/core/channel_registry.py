"""
REGISTRY KÊNH — nguồn sự thật DUY NHẤT về các kênh hệ thống biết.

Vì sao: thông tin "kênh nào có store nào / uid prefix gì / chạy cổng nào" trước
đây rải ở ≥4 chỗ (bridge.resolve_perbot_owner if/elif 7 nhánh, ALL_CHANNELS,
ACCOUNT_CHANNEL trong ai_models, từng main_*.py) — thêm kênh thứ 9 phải nhớ đủ
mọi chỗ, sót 1 chỗ là lệch hành vi (đúng kiểu lỗi IDOR từng chỉ vá telegram).
Thêm kênh mới giờ = thêm 1 entry ở đây (+ test_guard_drift tự quét file API mới).

store: factory lười (import bên trong) — tránh import vòng và không bắt mọi
process nạp đủ 7 store.
"""

import logging

log = logging.getLogger(__name__)


def _zalo_store():
    from app.core.zalo_node_store import ZaloNodeStore
    return ZaloNodeStore()

def _telegram_store():
    from app.core.telegram_store import TelegramStore
    return TelegramStore()

def _meta_store():
    from app.core.meta_store import MetaStore
    return MetaStore()

def _zalooa_store():
    from app.core.zalo_oa_store import ZaloOAStore
    return ZaloOAStore()

def _webchat_store():
    from app.core.webchat_store import WebChatStore
    return WebChatStore()

def _shopee_store():
    from app.core.shopee_store import ShopeeStore
    return ShopeeStore()


# key = tên kênh chuẩn hoá (khớp bot_state "kênh:<id>", user_apps.channel).
CHANNELS = {
    "zalo":     {"label": "Zalo cá nhân",  "uid_prefix": "",     "port": 5005, "store": _zalo_store},
    "meta":     {"label": "Messenger/IG",  "uid_prefix": "fb:",  "port": 5006, "store": _meta_store},
    "telegram": {"label": "Telegram",      "uid_prefix": "tg:",  "port": 5007, "store": _telegram_store},
    "shopee":   {"label": "Shopee",        "uid_prefix": "sp:",  "port": 5009, "store": _shopee_store},
    "zalooa":   {"label": "Zalo OA",       "uid_prefix": "oa:",  "port": 5010, "store": _zalooa_store},
    "webchat":  {"label": "Web widget",    "uid_prefix": "web:", "port": 5011, "store": _webchat_store},
}

ALL_KEYS = tuple(CHANNELS.keys())


def store_for(channel: str):
    """Store của 1 kênh (instance mới, đọc-ghi tươi SQLite). None nếu kênh lạ."""
    ent = CHANNELS.get((channel or "").strip().lower())
    if not ent:
        return None
    try:
        return ent["store"]()
    except Exception as e:
        log.warning(f"[registry] store kênh '{channel}' lỗi: {e}")
        return None


def accounts_of(channel: str) -> list:
    """[(account_id, data)] MỌI tài khoản con của 1 kênh (page/bot/OA/site...) —
    cho tính năng cần duyệt cả kho (vd nút Trợ lý AI resolve bot CỦA SHOP).
    Mọi store đều bọc SQLiteChannelStore ở thuộc tính `_store` (cùng bảng
    channel_accounts); kênh lạ/lỗi → [] (không ném)."""
    st = store_for(channel)
    inner = getattr(st, "_store", None)
    if inner is None:
        return []
    try:
        return list(inner.list())
    except Exception as e:
        log.warning(f"[registry] accounts_of '{channel}' lỗi: {e}")
        return []


def owner_of(channel_key: str):
    """Chủ (owner_username) của account sau key 'kênh:<id>' — None nếu không rõ.
    Mọi store đều có get_owner_username (hợp đồng chung của registry)."""
    try:
        parent, rid = (channel_key or "").split(":", 1)
    except ValueError:
        return None
    st = store_for(parent)
    if st is None:
        return None
    try:
        return st.get_owner_username(rid)
    except Exception as e:
        log.warning(f"[registry] owner_of '{channel_key}' lỗi: {e}")
        return None
