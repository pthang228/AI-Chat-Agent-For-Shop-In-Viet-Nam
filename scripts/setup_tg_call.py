"""
Đăng nhập tài khoản Telegram "caller" vào Telethon — chạy 1 lần duy nhất.
Sau đó bot sẽ dùng session này để tự động gọi khi có booking.

Chạy: python setup_tg_call.py
"""
import asyncio
from telethon import TelegramClient
from telethon.tl.functions.phone import RequestCallRequest, DiscardCallRequest
from telethon.tl.types import PhoneCallProtocol, PhoneCallDiscardReasonHangup
import os, hashlib, random

# Dùng API credentials của Telegram Desktop (công khai, không cần tạo app)
API_ID   = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"


async def main():
    print("="*50)
    print("  SETUP TELEGRAM CALLER")
    print("="*50)
    print("\nBước này đăng nhập tài khoản Telegram dùng để GỌI.")
    print("Nhập số điện thoại của acc Telegram thứ 2 (acc gọi).")
    print("Định dạng quốc tế, ví dụ: +84901234567\n")

    client = TelegramClient("data/tg_caller_session", API_ID, API_HASH)

    if os.path.exists("data/tg_caller_session.session"):
        print("✅ Tìm thấy session cũ — bỏ qua đăng nhập.\n")
        await client.connect()
    else:
        phone = input("Số điện thoại acc gọi: ").strip()
        await client.start(phone=phone)

    me = await client.get_me()
    print(f"\n✅ Đăng nhập thành công: {me.first_name} (@{me.username})")
    print(f"   ID: {me.id}")
    print("\n✅ Đã lưu session vào tg_caller_session.session")
    print("   Bot sẽ dùng file này để tự động gọi — không cần đăng nhập lại.\n")

    # Test gọi thử
    target = input("Nhập Telegram ID của acc NHẬN (để test gọi thử): ").strip()
    if target:
        print(f"\nGọi thử cho {target}...")
        await ring_call(client, int(target))
        print("✅ Xong! Kiểm tra điện thoại acc nhận xem có reng không.")

    await client.disconnect()


async def ring_call(client, target_id: int, ring_seconds: int = 10):
    """Gọi cho target_id, reng ring_seconds giây rồi tự cúp."""
    g_a = os.urandom(256)
    g_a_hash = hashlib.sha256(g_a).digest()

    result = await client(RequestCallRequest(
        user_id=target_id,
        random_id=random.randint(0, 2**31 - 1),
        g_a_hash=g_a_hash,
        protocol=PhoneCallProtocol(
            udp_p2p=True,
            udp_reflector=True,
            min_layer=92,
            max_layer=92,
            library_versions=["5.0.0"],
        ),
    ))

    await asyncio.sleep(ring_seconds)

    await client(DiscardCallRequest(
        peer=result.phone_call,
        duration=0,
        reason=PhoneCallDiscardReasonHangup(),
        connection_id=0,
    ))


if __name__ == "__main__":
    asyncio.run(main())
