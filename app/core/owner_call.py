"""
Báo động chủ nhà — beep loa máy + gọi Telegram (Telethon).
Tách riêng để mọi kênh (Zalo zlapi, Zalo Node, Instagram...) dùng chung.
"""

import time
import logging
import threading
from pathlib import Path

from app.core.config import Config

log = logging.getLogger(__name__)


def caller_session_path() -> Path:
    return Path(Config.TG_SESSION + ".session")


def beep():
    """Phát beep trên máy tính (Windows)."""
    def _beep():
        try:
            import winsound
            for _ in range(5):
                winsound.Beep(1000, 600)
                time.sleep(0.2)
        except Exception:
            pass
    threading.Thread(target=_beep, daemon=True).start()
    log.info("[Call] Đã phát beep thông báo")


def telethon_call(target_id=None, session=None):
    """
    Gọi Telegram cho chủ nhà, cứ 3 phút gọi lại nếu không bắt máy.
    target_id: ID Telegram cần gọi (mặc định Config.TELEGRAM_TARGET_ID).
    session:   StringSession của acc gọi theo từng bot (đa khách). None → dùng
               file session chung Config.TG_SESSION (bản .env 1 bot).
    Dừng khi bắt máy hoặc sau 10 lần (30 phút). Chạy trong thread riêng.
    """
    target = str(target_id or Config.TELEGRAM_TARGET_ID or "").strip()
    if not target:
        return
    if not session and not caller_session_path().exists():
        return   # bản .env: chưa có file session thì khỏi gọi
    threading.Thread(target=_telethon_loop, args=(target, session), daemon=True).start()


def _telethon_loop(target, session=None):
    import asyncio, os, hashlib, random
    from telethon import TelegramClient, events
    from telethon.sessions import StringSession
    from telethon.tl import types
    from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
    from telethon.tl.types import PhoneCallProtocol, PhoneCallDiscardReasonHangup

    target_id = int(target)

    async def _one_call(client) -> bool:
        g_a = os.urandom(256)
        g_a_hash = hashlib.sha256(g_a).digest()
        answered = asyncio.Event()

        @client.on(events.Raw(types.UpdatePhoneCall))
        async def _on_call_update(update):
            if isinstance(update.phone_call, types.PhoneCallAccepted):
                answered.set()

        try:
            result = await client(RequestCallRequest(
                user_id=target_id,
                random_id=random.randint(0, 2**31 - 1),
                g_a_hash=g_a_hash,
                protocol=PhoneCallProtocol(
                    udp_p2p=True, udp_reflector=True,
                    min_layer=92, max_layer=92, library_versions=["5.0.0"],
                ),
            ))
            try:
                await asyncio.wait_for(answered.wait(), timeout=30)
                log.info("[Telegram] ✅ Chủ nhà đã bắt máy!")
                was_answered = True
            except asyncio.TimeoutError:
                log.info("[Telegram] Không bắt máy (timeout 30s)")
                was_answered = False
            try:
                await client(DiscardCallRequest(
                    peer=result.phone_call, duration=0,
                    reason=PhoneCallDiscardReasonHangup(), connection_id=0,
                ))
            except Exception:
                pass
            return was_answered
        except Exception as e:
            log.error(f"[Telegram] Lỗi trong cuộc gọi: {e}")
            return False
        finally:
            client.remove_event_handler(_on_call_update)

    async def _call_loop():
        sess = StringSession(session) if session else Config.TG_SESSION
        client = TelegramClient(sess, Config.TELEGRAM_API_ID, Config.TELEGRAM_API_HASH)
        await client.connect()
        try:
            for attempt in range(10):
                log.info(f"[Telegram] Gọi lần {attempt + 1}/10 → {target_id}")
                if await _one_call(client):
                    break
                if attempt < 9:
                    log.info("[Telegram] Chờ 3 phút rồi gọi lại...")
                    await asyncio.sleep(180)
        finally:
            await client.disconnect()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_call_loop())
    except Exception as e:
        log.error(f"[Telegram] asyncio lỗi: {e}")
    finally:
        loop.close()


def alert(target_id=None, session=None):
    """Báo động đầy đủ: beep + gọi Telegram (target_id + session tuỳ kênh/bot)."""
    beep()
    telethon_call(target_id, session=session)
