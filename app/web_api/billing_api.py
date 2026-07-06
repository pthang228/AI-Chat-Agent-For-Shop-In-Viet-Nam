"""
API gói dịch vụ & nạp tiền — gắn vào bridge (5005) như auth_api.

User (Bearer token):
  GET  /billing/me                → trạng thái gói + ví + bảng giá + info chuyển khoản
  POST /billing/redeem {code}     → nhập mã giới thiệu (trial 7 ngày)
  POST /billing/deposit {amount}  → tạo lệnh nạp (trả mã nội dung chuyển khoản)
  GET  /billing/deposits          → các lệnh nạp của mình
  POST /billing/buy {plan}        → mua gói bằng ví (month|quarter|year|lifetime)
  GET  /billing/history           → lịch sử giao dịch

Admin (header X-Admin-Key = BILLING_ADMIN_KEY trong .env; rỗng = tắt, dùng
scripts/nap_tien.py trên máy chủ thay thế):
  GET  /billing/admin/pending     → lệnh nạp chờ xác nhận
  POST /billing/admin/confirm {code} → xác nhận đã nhận tiền → cộng ví
"""

import logging

from flask import request, jsonify

from app.core.config import Config
from app.core import billing
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

log = logging.getLogger("billing_api")


def register_billing_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    def _admin_ok():
        key = Config.BILLING_ADMIN_KEY
        return bool(key) and request.headers.get("X-Admin-Key", "") == key

    @app.route("/billing/me")
    def billing_me():
        u, err = _auth_or_401()
        if err:
            return err
        st = billing.status(u["username"])
        from app.core import ai_models
        return {
            "ok": True, **st,
            "tiers": billing.plans_catalog(),         # 3 hạng × 4 thời hạn (giá + quota + tính năng)
            "durations": billing.durations_catalog(),
            "ai_models": ai_models.catalog_for_ui(),  # bảng giá model (đ/1M token)
            "ai_model_default": ai_models.DEFAULT_MODEL,
            "promo_enabled": bool(Config.BILLING_PROMO_CODE),
            "bank": {
                "name": Config.BANK_NAME,
                "account": Config.BANK_ACCOUNT,
                "holder": Config.BANK_HOLDER,
                "configured": bool(Config.BANK_ACCOUNT),
            },
            "min_deposit": billing.MIN_DEPOSIT,
        }

    @app.route("/billing/redeem", methods=["POST"])
    def billing_redeem():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            billing.redeem_promo(u["username"], data.get("code") or "")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, **billing.status(u["username"])}

    @app.route("/billing/deposit", methods=["POST"])
    def billing_deposit():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            d = billing.create_deposit(u["username"], int(data.get("amount") or 0))
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, **d}

    @app.route("/billing/deposits")
    def billing_deposits():
        u, err = _auth_or_401()
        if err:
            return err
        return jsonify(billing.list_deposits(u["username"]))

    @app.route("/billing/buy", methods=["POST"])
    def billing_buy():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            st = billing.buy_plan(u["username"], (data.get("tier") or "").strip(),
                                  (data.get("duration") or "").strip())
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, **st}

    @app.route("/billing/history")
    def billing_history():
        u, err = _auth_or_401()
        if err:
            return err
        return jsonify(billing.transactions(u["username"]))

    @app.route("/billing/ai-model", methods=["POST"])
    def billing_ai_model():
        """Shop chọn MÔ HÌNH AI dùng cho mọi chỗ AI của shop (bot trả lời, test bot…)."""
        u, err = _auth_or_401()
        if err:
            return err
        from app.core import ai_models
        key = ((request.get_json(force=True, silent=True) or {}).get("model") or "").strip()
        if key and key not in ai_models.CATALOG:
            return {"ok": False, "error": "Mô hình không hợp lệ"}, 400
        if key and key not in ai_models.available_keys():
            return {"ok": False, "error": "Mô hình này máy chủ chưa cấu hình API key"}, 400
        billing.ensure_billing(u["username"])
        db.execute("UPDATE billing SET ai_model=? WHERE username=?", (key, u["username"]))
        return {"ok": True, **billing.status(u["username"])}

    @app.route("/billing/usage", methods=["POST"])
    def billing_usage():
        """Bật/tắt 'tính theo usage khi hết quota' + giới hạn chi tiêu tháng (đ)."""
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        enabled = 1 if data.get("enabled") else 0
        try:
            limit = int(data.get("limit") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Giới hạn không hợp lệ"}, 400
        if limit < 0 or limit > 50_000_000:
            return {"ok": False, "error": "Giới hạn từ 0 đến 50.000.000đ"}, 400
        if enabled and limit <= 0:
            return {"ok": False, "error": "Bật usage thì phải đặt giới hạn tháng > 0"}, 400
        billing.ensure_billing(u["username"])
        db.execute("UPDATE billing SET usage_enabled=?, usage_limit=? WHERE username=?",
                   (enabled, limit, u["username"]))
        return {"ok": True, **billing.status(u["username"])}

    # ── Admin ───────────────────────────────────────────────────────

    @app.route("/billing/admin/pending")
    def billing_admin_pending():
        if not _admin_ok():
            return {"ok": False, "error": "admin key sai hoặc chưa cấu hình"}, 403
        return jsonify(billing.pending_deposits())

    @app.route("/billing/admin/confirm", methods=["POST"])
    def billing_admin_confirm():
        if not _admin_ok():
            return {"ok": False, "error": "admin key sai hoặc chưa cấu hình"}, 403
        data = request.get_json(force=True, silent=True) or {}
        try:
            r = billing.confirm_deposit(data.get("code") or "")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, **r}

    return app
