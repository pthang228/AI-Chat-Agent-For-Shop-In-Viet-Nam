"""
GỌI KHẨN QUA TELEGRAM cấp SHOP — dùng chung cho MỌI kênh.

Chủ shop tự đăng nhập 1 acc Telegram PHỤ (QR — cơ chế y hệt "acc gọi" của kênh
Telegram: telegram_login + Telethon StringSession) và khai acc Telegram CHÍNH
của mình (@username). Khi sự kiện đặt mức "Gọi" (vd khách cần gặp chủ) ở BẤT KỲ
kênh nào (Zalo/OA/Meta/Shopee/Webchat/Telegram...), notify.alert nhờ acc phụ
GỌI acc chính qua owner_call.telethon_call (đổ chuông Telegram, gọi lại mỗi 3
phút tới khi bắt máy, tối đa 10 lần).

Lưu: SQLiteChannelStore("shop_caller") — key = ws (workspace/shop), field
caller_session được secretbox mã hoá như token kênh. SHOP CON chưa cấu hình
riêng → fallback cấu hình TÀI KHOẢN CHÍNH (giống notify_config/billing).
"""

import logging
import re
import threading

from app.core.channel_store import SQLiteChannelStore

log = logging.getLogger(__name__)

_store = None
_lock = threading.RLock()


def store() -> SQLiteChannelStore:
    global _store
    with _lock:
        if _store is None:
            _store = SQLiteChannelStore("shop_caller",
                                        secret_fields=("caller_session",))
    return _store


def get(ws: str) -> dict:
    """Cấu hình gọi CỦA CHÍNH ws (không fallback) — cho trang Cài đặt."""
    return store().get(str(ws or "")) or {}


def config_for(ws: str) -> dict:
    """Cấu hình dùng LÚC GỌI: ws chưa có → fallback tài khoản chính (shop con)."""
    cfg = get(ws)
    if cfg.get("caller_session"):
        return cfg
    try:
        from app.core import shops
        acct = shops.account_of(ws or "")
        if acct and acct != ws:
            return get(acct)
    except Exception:
        pass
    return cfg


def set_session(ws: str, session: str, profile: dict):
    """Lưu acc gọi sau khi QR xong (profile từ telegram_login._finish)."""
    with _lock:
        cfg = get(ws)
        cfg.update({
            "owner_username": str(ws),
            "caller_session": session,
            "caller_name": " ".join(x for x in [(profile or {}).get("first_name"),
                                                (profile or {}).get("last_name")] if x),
            "caller_username": (profile or {}).get("username") or "",
        })
        store().upsert(str(ws), cfg)


def set_target(ws: str, target_id, name: str = "", username: str = ""):
    with _lock:
        cfg = get(ws)
        cfg["owner_username"] = str(ws)
        cfg["target_id"] = int(target_id)
        cfg["target_name"] = name or ""
        cfg["target_username"] = username or ""
        store().upsert(str(ws), cfg)


def clear(ws: str):
    store().remove(str(ws))


def get_owner_username(ws: str):
    """Hợp đồng chung store (registry/guard): chủ của bản ghi = chính ws."""
    return (get(ws) or {}).get("owner_username") or None


def resolve_target(ws: str, handle: str) -> dict:
    """Tra acc Telegram CHÍNH của chủ từ @username — dùng chính acc gọi đã đăng
    nhập để get_entity (đồng thời cache access-hash vào session → gọi được ngay).
    Trả {ok, target?, error?}. Khuyên dùng @username (SĐT chỉ tra được khi acc
    gọi đã lưu số đó trong danh bạ)."""
    cfg = get(ws)
    session = cfg.get("caller_session")
    if not session:
        return {"ok": False, "error": "Đăng nhập acc gọi (QR) trước đã"}
    handle = (handle or "").strip()
    if not handle:
        return {"ok": False, "error": "Nhập @username Telegram của bạn"}
    if not re.fullmatch(r"@?[A-Za-z0-9_]{4,32}|\+?\d{8,15}", handle):
        return {"ok": False, "error": "Dạng không hợp lệ — nhập @username hoặc SĐT quốc tế"}
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from app.core import telegram_login as tgl
        from app.core.config import Config

        async def _resolve():
            client = TelegramClient(StringSession(session),
                                    Config.TELEGRAM_API_ID, Config.TELEGRAM_API_HASH)
            await client.connect()
            try:
                ent = await client.get_entity(handle)
                return {"id": ent.id,
                        "name": " ".join(x for x in [getattr(ent, "first_name", ""),
                                                     getattr(ent, "last_name", "")] if x),
                        "username": getattr(ent, "username", "") or ""}
            finally:
                await client.disconnect()

        info = tgl._run(_resolve(), timeout=30)
        set_target(ws, info["id"], info["name"], info["username"])
        return {"ok": True, "target": info}
    except Exception as e:
        log.warning(f"[shop_caller] resolve '{handle}' cho {ws} lỗi: {e}")
        return {"ok": False, "error": f"Không tìm thấy tài khoản ({e})"}


def call(ws: str) -> bool:
    """Gọi chủ shop ws (fallback tài khoản chính). True = ĐÃ phát lệnh gọi;
    False = shop chưa cấu hình / lỗi → caller nên fallback cơ chế cũ của kênh."""
    try:
        cfg = config_for(ws)
        session, target = cfg.get("caller_session"), cfg.get("target_id")
        if not (session and target):
            return False
        from app.core import owner_call
        owner_call.telethon_call(target, session=session)
        log.info(f"[shop_caller] gọi chủ shop {ws} → tg:{target}")
        return True
    except Exception as e:
        log.error(f"[shop_caller] gọi {ws} lỗi: {e}")
        return False
