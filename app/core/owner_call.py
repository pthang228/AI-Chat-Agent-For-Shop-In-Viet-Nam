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


def telethon_call():
    """
    Gọi Telegram cho chủ nhà, cứ 3 phút gọi lại nếu không bắt máy.
    Dừng khi bắt máy hoặc sau 10 lần (30 phút). Chạy trong thread riêng.
    """
    if not (Config.TELEGRAM_TARGET_ID and Path(Config.TG_SESSION + ".session").exists()):
        return
    threading.Thread(target=_telethon_loop, daemon=True).start()


def _telethon_loop():
    import asyncio, os, hashlib, random
    from telethon import TelegramClient, events
    from telethon.tl import types
    from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
    from telethon.tl.types import PhoneCallProtocol, PhoneCallDiscardReasonHangup

    target_id = int(Config.TELEGRAM_TARGET_ID)

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
        client = TelegramClient(Config.TG_SESSION, 2040, "b18441a1ff607e10a989891a5462e627")
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


def alert():
    """Báo động đầy đủ: beep + gọi Telegram."""
    beep()
    telethon_call()
