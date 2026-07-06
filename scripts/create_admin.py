#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tạo (hoặc nâng cấp) TÀI KHOẢN QUẢN TRỊ NỀN TẢNG — role='admin', chỉ để đăng nhập
khu /admin, tách khỏi tài khoản shop.

Chạy TỪ GỐC:
  python -m scripts.create_admin admin@novachat.vn MatKhauManh123!

Trên VPS (Docker):
  docker compose exec bridge python -m scripts.create_admin admin@novachat.vn MatKhauManh123!

Email đã tồn tại → NÂNG role thành admin + đổi mật khẩu (huỷ mọi phiên cũ).
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.db import get_db
from app.web_api.auth_api import hash_password


def main():
    if len(sys.argv) < 3:
        print("Cách dùng: python -m scripts.create_admin <email> <mật_khẩu>")
        sys.exit(1)
    email = sys.argv[1].strip().lower()
    password = sys.argv[2]
    if "@" not in email:
        print("❌ Email không hợp lệ"); sys.exit(1)
    if len(password) < 8:
        print("❌ Mật khẩu admin tối thiểu 8 ký tự"); sys.exit(1)

    db = get_db()
    exists = db.query("SELECT username FROM users WHERE username=?", (email,))
    if exists:
        db.execute(
            "UPDATE users SET role='admin', password_hash=? WHERE username=?",
            (hash_password(password), email))
        db.execute("DELETE FROM auth_tokens WHERE username=?", (email,))
        print(f"✅ Đã NÂNG {email} thành QUẢN TRỊ NỀN TẢNG + đổi mật khẩu (phiên cũ bị huỷ).")
    else:
        db.execute(
            "INSERT INTO users(username, password_hash, homestay, email, provider,"
            " picture, role, owner_username, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (email, hash_password(password), "Quản trị NovaChat", email,
             "password", "", "admin", "", datetime.now().isoformat()))
        print(f"✅ Đã tạo tài khoản QUẢN TRỊ NỀN TẢNG: {email}")
    print("→ Đăng nhập web bằng tài khoản này rồi vào mục 'Quản trị' (/admin).")


if __name__ == "__main__":
    main()
