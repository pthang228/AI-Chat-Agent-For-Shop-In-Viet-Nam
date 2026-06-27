"""
Đăng nhập acc gọi (Telethon) bằng QR ngay trong web — thay cho script terminal.

Mỗi shop/bot tự đăng nhập tài khoản Telegram dùng để GỌI cho chủ. Telethon là
asyncio còn Flask là sync → chạy 1 event-loop nền (1 thread) và marshal lời gọi
sang đó. Phiên đăng nhập lưu dạng StringSession (string) để cất vào TelegramStore.

Luồng QR (giống flow QR Zalo Node):
  start_login(bot_id) → hiện QR (png base64). Khách mở Telegram quét.
  Quét xong:
    - acc KHÔNG bật 2FA → state="done" (đã có session).
    - acc bật 2FA       → state="need_password" → submit_password(bot_id, pw) → "done".
  QR token hết hạn ~30s → tự tạo lại (recreate), png cập nhật, poll lấy png mới.

Bảo mật: session = TOÀN QUYỀN acc khách. Gọi store.set_caller_session để cất
(nên mã hoá khi lưu — TODO production).
"""

import io
import time
import base64
import asyncio
import logging
import threading

import qrcode
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError

from app.core.config import Config

log = logging.getLogger(__name__)

# ── Event-loop nền dùng chung cho mọi thao tác Telethon ────────────────
_loop = None
_loop_lock = threading.Lock()


def _get_loop():
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True).start()
    return _loop


def _run(coro, timeout=30):
    """Chạy 1 coroutine trên loop nền và chờ kết quả (đồng bộ cho Flask)."""
    return asyncio.run_coroutine_threadsafe(coro, _get_loop()).result(timeout=timeout)


# ── Registry phiên đăng nhập đang dở: bot_id -> state dict ─────────────
_logins: dict = {}
_llock = threading.Lock()

QR_WAIT = 18        # mỗi nhịp chờ quét trước khi tạo lại token
QR_DEADLINE = 240   # tổng thời gian cho 1 lần đăng nhập (giây)


def _qr_png(url: str) -> str:
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _api():
    return Config.TELEGRAM_API_ID, Config.TELEGRAM_API_HASH


def status(bot_id) -> dict:
    """Trạng thái phiên đăng nhập (an toàn để trả JSON)."""
    st = _logins.get(str(bot_id))
    if not st:
        return {"state": "idle"}
    return {
        "state": st.get("state", "idle"),
        "png": st.get("png"),
        "profile": st.get("profile"),
        "error": st.get("error"),
    }


def start_login(bot_id) -> dict:
    """Bắt đầu đăng nhập QR cho 1 bot. Trả về trạng thái ban đầu (có png)."""
    bid = str(bot_id)
    stop_login(bid)   # huỷ phiên dở cũ (nếu có)
    st = {"state": "starting", "png": None, "profile": None, "error": None}
    with _llock:
        _logins[bid] = st
    try:
        _run(_init_qr(bid, st), timeout=30)
    except Exception as e:
        log.error(f"[TG login {bid}] start lỗi: {e}")
        st["state"] = "error"
        st["error"] = str(e)
    return status(bid)


async def _init_qr(bid, st):
    api_id, api_hash = _api()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    st["client"] = client
    qr = await client.qr_login()
    st["qr"] = qr
    st["png"] = _qr_png(qr.url)
    st["state"] = "pending"
    asyncio.ensure_future(_wait_qr(bid, st))   # chờ quét ở nền (cùng loop)


async def _wait_qr(bid, st):
    client = st["client"]
    qr = st["qr"]
    deadline = time.time() + QR_DEADLINE
    try:
        while time.time() < deadline:
            try:
                await qr.wait(timeout=QR_WAIT)   # quét xong (acc không 2FA)
                await _finish(st, client)
                return
            except asyncio.TimeoutError:
                await qr.recreate()              # token hết hạn → làm mới
                st["png"] = _qr_png(qr.url)
                continue
            except SessionPasswordNeededError:
                st["state"] = "need_password"     # quét xong nhưng cần 2FA
                return                            # GIỮ client để submit_password
        st["state"] = "expired"
        await client.disconnect()
    except Exception as e:
        log.error(f"[TG login {bid}] wait lỗi: {e}")
        st["state"] = "error"
        st["error"] = str(e)
        try:
            await client.disconnect()
        except Exception:
            pass


def submit_password(bot_id, password) -> dict:
    """Gửi mật khẩu 2FA cho acc đang ở bước need_password."""
    bid = str(bot_id)
    st = _logins.get(bid)
    if not st or st.get("state") != "need_password":
        return {"ok": False, "error": "Không ở bước nhập mật khẩu 2FA"}
    try:
        _run(_do_password(st, password), timeout=30)
        return {"ok": True, "state": st.get("state"), "profile": st.get("profile")}
    except Exception as e:
        msg = str(e)
        # mật khẩu sai → giữ nguyên bước need_password để nhập lại
        log.error(f"[TG login {bid}] 2FA lỗi: {msg}")
        return {"ok": False, "error": msg}


async def _do_password(st, password):
    client = st["client"]
    await client.sign_in(password=password)
    await _finish(st, client)


async def _finish(st, client):
    me = await client.get_me()
    st["session"] = client.session.save()
    st["profile"] = {
        "id": me.id,
        "first_name": me.first_name or "",
        "last_name": me.last_name or "",
        "username": me.username or "",
    }
    st["state"] = "done"
    await client.disconnect()


def take_result(bot_id):
    """Lấy (session, profile) khi state=done để lưu vào store, rồi dọn phiên."""
    st = _logins.get(str(bot_id))
    if not st or st.get("state") != "done":
        return None
    res = (st.get("session"), st.get("profile"))
    stop_login(bot_id)
    return res


def stop_login(bot_id):
    """Dọn phiên đăng nhập (ngắt client nếu còn)."""
    with _llock:
        st = _logins.pop(str(bot_id), None)
    client = st and st.get("client")
    if client:
        try:
            _run(client.disconnect(), timeout=10)
        except Exception:
            pass
