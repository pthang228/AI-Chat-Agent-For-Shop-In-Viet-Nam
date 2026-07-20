"""
API thanh toán — webhook đối soát tiền + tài khoản nhận tiền của shop.

  POST /payhook            → SePay/Casso đẩy biến động số dư về (KHÔNG cần Bearer;
                             bảo vệ bằng SEPAY_API_KEY trong header Authorization
                             nếu .env có đặt). Khớp DHxxxx → đơn paid; NAPxxxx →
                             xác nhận nạp ví. Luôn trả 200 để không bị retry spam.
  GET  /payhook            → kiểm tra URL sống khi khai webhook.
  GET  /orders/bank        (Bearer) → bank info của user đang đăng nhập + QR mẫu
  POST /orders/bank        (Bearer) → lưu bank_code/bank_account/bank_holder

Đăng ký ở CẢ bridge 5005 (test local) LẪN meta 5006 (đã public qua ngrok —
SePay cần URL public: <PUBLIC_BASE_URL>/payhook).
"""

import hmac
import logging

from flask import request

from app.core import payments
from app.core.config import Config

log = logging.getLogger("payment_api")


def _payhook_authorized() -> bool:
    """So khớp AN TOÀN key webhook. SePay gửi header 'Authorization: Apikey <KEY>'
    (hoặc 'Bearer <KEY>' / key trần) → bóc phần token rồi hmac.compare_digest
    (chống timing attack + không lọt header rác chỉ CHỨA key như 'in' cũ)."""
    key = Config.SEPAY_API_KEY
    if not key:
        # CHƯA đặt key. Nếu webhook đang PHƠI RA INTERNET (có PUBLIC_BASE_URL) thì
        # TỪ CHỐI — nếu không ai cũng POST giả /payhook để cộng ví / đánh dấu đơn
        # "đã thanh toán". Chỉ cho qua khi chạy nội bộ (local/dev, không public).
        if Config.PUBLIC_BASE_URL:
            log.warning("[Pay] /payhook đang public nhưng CHƯA đặt SEPAY_API_KEY → "
                        "từ chối. Hãy đặt SEPAY_API_KEY trong .env cho khớp SePay.")
            return False
        return True   # local/dev không public → nhận tất
    raw = (request.headers.get("Authorization") or "").strip()
    token = raw.split(None, 1)[1].strip() if " " in raw else raw   # bỏ tiền tố Apikey/Bearer
    return hmac.compare_digest(token, key) or hmac.compare_digest(raw, key)


def register_payment_routes(app, notify_fn=None, with_bank_api=True):
    @app.route("/payhook", methods=["GET"])
    def payhook_alive():
        return "ok", 200

    @app.route("/payhook", methods=["POST"])
    def payhook():
        # Xác thực: .env có SEPAY_API_KEY → header Authorization phải KHỚP key
        if not _payhook_authorized():
            log.warning("[Pay] webhook sai API key → bỏ qua")
            return {"ok": False, "error": "unauthorized"}, 401
        payload = request.get_json(force=True, silent=True) or {}
        results = []
        for content, amount in payments.parse_webhook(payload):
            results.append(payments.process_transfer(content, amount, notify_fn))
        log.info(f"[Pay] webhook: {len(results)} giao dịch, "
                 f"khớp {sum(1 for r in results if r.get('matched'))}")
        return {"ok": True, "processed": len(results),
                "matched": [r for r in results if r.get("matched")]}

    if not with_bank_api:
        return app

    # ── Bank info (chỉ gắn ở bridge — cần auth_api cùng app) ──
    from app.web_api.auth_api import _user_for_token, _bearer
    from app.core.db import get_db
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    @app.route("/orders/bank")
    def bank_get():
        u, err = _auth_or_401()
        if err:
            return err
        b = payments.get_bank(u["username"]) or {}
        sample = payments.build_vietqr_url(b, amount=100000, memo="DH0000") if b else ""
        return {"ok": True, "bank": {
            "bank_code": b.get("bank_code", ""),
            "bank_account": b.get("bank_account", ""),
            "bank_holder": b.get("bank_holder", ""),
        }, "sample_qr": sample}

    @app.route("/orders/bank", methods=["POST"])
    def bank_set():
        u, err = _auth_or_401()
        if err:
            return err
        d = request.get_json(force=True, silent=True) or {}
        code = (d.get("bank_code") or "").strip()
        account = (d.get("bank_account") or "").strip()
        if code and not account:
            return {"ok": False, "error": "Thiếu số tài khoản"}, 400
        payments.set_bank(u["username"], code, account, d.get("bank_holder") or "")
        b = payments.get_bank(u["username"]) or {}
        log.info(f"[Pay] {u['username']} cập nhật bank: {b.get('bank_code')}-{b.get('bank_account')}")
        return {"ok": True, "bank": b,
                "sample_qr": payments.build_vietqr_url(b, amount=100000, memo="DH0000") if b else ""}

    return app
