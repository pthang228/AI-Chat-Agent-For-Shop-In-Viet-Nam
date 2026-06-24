"""
Lấy Zalo ID qua cookie + imei từ trình duyệt.
"""

import json
from zlapi import ZaloAPI

print("=" * 60)
print("  BƯỚC 1 — Lấy COOKIE (từ Network tab):")
print()
print("  1. Chrome → chat.zalo.me → đăng nhập")
print("  2. F12 → tab NETWORK → F5 reload")
print("  3. Click request bất kỳ → Request Headers")
print("  4. Tìm dòng 'cookie:' → copy toàn bộ giá trị")
print("=" * 60)

raw_cookie = input("\nDán COOKIE vào đây: ").strip()

print()
print("=" * 60)
print("  BƯỚC 2 — Lấy IMEI (từ Console tab):")
print()
print("  1. F12 → tab CONSOLE")
print("  2. Nếu thấy cảnh báo, gõ:  allow pasting  rồi Enter")
print("  3. Gõ lệnh sau rồi Enter:")
print("     copy(localStorage.getItem('z_uuid'))")
print("  4. Nếu không có, thử:")
print("     copy(Object.keys(localStorage).find(k=>k.includes('imei')))")
print("     hoặc: copy(JSON.stringify(localStorage))")
print("=" * 60)

imei = input("\nDán IMEI / z_uuid vào đây: ").strip()

# Nếu user paste toàn bộ JSON localStorage, tìm imei trong đó
if imei.startswith("{"):
    try:
        ls = json.loads(imei)
        for k, v in ls.items():
            if "imei" in k.lower() or "uuid" in k.lower() or "z_uuid" in k.lower():
                imei = v
                print(f"  → Tìm thấy: {k} = {imei[:30]}...")
                break
    except Exception:
        pass

# Parse cookie string
cookies = {}
for part in raw_cookie.split(";"):
    part = part.strip()
    if "=" in part:
        k, _, v = part.partition("=")
        cookies[k.strip()] = v.strip()

print(f"\nĐã đọc {len(cookies)} cookie, imei: {imei[:20] if imei else 'trống'}...")
print("Đang kết nối Zalo...")

class TempBot(ZaloAPI):
    pass

try:
    bot = TempBot(
        phone="",
        password="",
        imei=imei or None,
        cookies=cookies,
    )
    uid = bot.uid() or bot.user_id
    print(f"\n✅ Kết nối thành công!")
    print(f"👤 Zalo ID: {uid}")
    print(f"\n👉 Điền vào .env:  OWNER_ZALO_ID={uid}")

    # Lưu ra file để dùng lại
    acc_num = input("\nĐây là tài khoản số mấy? (1/2/3...) [mặc định: 1]: ").strip() or "1"
    filename = "data/zalo_cookies.json" if acc_num == "1" else f"data/zalo_cookies_{acc_num}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump({"cookies": cookies, "imei": imei}, f, ensure_ascii=False, indent=2)
    print(f"✅ Đã lưu vào {filename}")

except Exception as e:
    print(f"\n❌ Lỗi: {e}")
    print("\nThử cách thay thế — lấy imei từ Network request:")
    print("  1. F12 → Network → filter: getLoginInfo")
    print("  2. Tìm request đó → xem URL → copy giá trị imei=... trong URL")
