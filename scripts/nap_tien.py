#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
nap_tien.py — ADMIN xác nhận lệnh nạp tiền (chạy trên máy chủ, ghi thẳng SQLite).

Cách dùng (TỪ GỐC dự án):
  python scripts/nap_tien.py                 → liệt kê lệnh nạp đang chờ
  python scripts/nap_tien.py NAP483920       → xác nhận đã nhận tiền mã đó → cộng ví

Quy trình: khách tạo lệnh nạp trong web (trang Gói dịch vụ) → chuyển khoản với
NỘI DUNG = mã NAPxxxxxx → bạn thấy tiền về tài khoản → chạy lệnh xác nhận.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from app.core import billing


def main():
    if len(sys.argv) < 2:
        rows = billing.pending_deposits()
        if not rows:
            print("✅ Không có lệnh nạp nào đang chờ.")
            return
        print(f"⏳ {len(rows)} lệnh nạp đang chờ xác nhận:\n")
        for d in rows:
            print(f"  {d['code']}  |  {d['amount']:>12,}₫  |  {d['username']}  |  tạo lúc {d['created_at'][:19]}")
        print("\nXác nhận: python scripts/nap_tien.py <MÃ>")
        return

    code = sys.argv[1].strip().upper()
    try:
        r = billing.confirm_deposit(code)
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)
    print(f"✅ Đã cộng {r['amount']:,}₫ vào ví của {r['username']} (mã {code}).")


if __name__ == "__main__":
    main()
