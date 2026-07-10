"""
Gửi email hệ thống (mã quên mật khẩu…) qua SMTP.

Cấu hình trong .env:
  SMTP_USER=ban@gmail.com      # tài khoản gửi
  SMTP_PASS=xxxx xxxx xxxx     # Gmail: BẬT xác minh 2 bước rồi tạo "App Password"
                               # (myaccount.google.com/apppasswords) — KHÔNG dùng mật khẩu thường
  SMTP_HOST=smtp.gmail.com     # mặc định Gmail
  SMTP_PORT=587                # 587 = STARTTLS, 465 = SSL
  SMTP_FROM=                   # tên hiển thị người gửi, trống = SMTP_USER

Chưa cấu hình → configured() False, tính năng phụ thuộc email tự báo rõ cho user.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import Config

log = logging.getLogger("mailer")


def configured() -> bool:
    return bool(Config.SMTP_HOST and Config.SMTP_USER and Config.SMTP_PASS)


def send_mail(to: str, subject: str, body: str) -> bool:
    """Gửi email text thuần. Trả True nếu gửi thành công (không ném exception)."""
    if not configured():
        log.warning("[mailer] SMTP chưa cấu hình (SMTP_USER/SMTP_PASS) — không gửi được email")
        return False
    msg = EmailMessage()
    msg["From"] = Config.SMTP_FROM or Config.SMTP_USER
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        if Config.SMTP_PORT == 465:
            with smtplib.SMTP_SSL(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as s:
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as s:
                s.starttls()
                s.login(Config.SMTP_USER, Config.SMTP_PASS)
                s.send_message(msg)
        log.info(f"[mailer] đã gửi '{subject}' tới {to}")
        return True
    except Exception as e:
        log.error(f"[mailer] gửi email tới {to} thất bại: {e}")
        return False
