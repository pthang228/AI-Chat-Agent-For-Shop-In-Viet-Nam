"""
API "Gọi khẩn qua Telegram" cấp SHOP (mọi kênh) — gắn bridge 5005, sau auth
guard. Cơ chế y hệt acc gọi per-bot của kênh Telegram (telegram_login QR +
Telethon), nhưng key theo WORKSPACE (shop đang chọn, X-Shop aware) nên mọi
kênh của shop dùng chung. Xem app/core/shop_caller.py.

  GET  /caller                    → trạng thái (acc gọi + target + inherited)
  POST /caller/qr-login           → mở QR đăng nhập acc PHỤ
  GET  /caller/login-status       → poll QR (done → tự lưu session)
  POST /caller/password {password}→ 2FA
  POST /caller/target {handle}    → khai @username acc CHÍNH của chủ
  POST /caller/test-call          → gọi thử ngay
  POST /caller/logout             → gỡ acc gọi của shop
"""

import logging

from flask import request, jsonify

from app.core import shop_caller, telegram_login
from app.core.config import Config

log = logging.getLogger("caller_api")

# key phiên QR trong telegram_login registry — prefix tránh đụng bot_id thật
def _login_key(ws: str) -> str:
    return f"ws|{ws}"


def register_caller_routes(app):
    from app.core.db import get_db
    from app.web_api.auth_api import (_user_for_token, _bearer, role_of,
                                      request_workspace)
    db = get_db()

    def _owner_ws():
        """(ws, err) — chỉ CHỦ được đụng cấu hình gọi (staff xem cũng không cần)."""
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        if role_of(u) != "owner":
            return None, ({"ok": False, "error": "Chỉ chủ shop cấu hình gọi khẩn"}, 403)
        return request_workspace(u), None

    @app.route("/caller")
    def caller_status():
        ws, err = _owner_ws()
        if err:
            return err
        own = shop_caller.get(ws)
        eff = own if own.get("caller_session") else shop_caller.config_for(ws)
        return {
            "ok": True,
            "configured_api": bool(Config.TELEGRAM_API_ID and Config.TELEGRAM_API_HASH),
            "logged_in": bool(eff.get("caller_session")),
            "caller_name": eff.get("caller_name", ""),
            "caller_username": eff.get("caller_username", ""),
            "target_id": eff.get("target_id") or None,
            "target_name": eff.get("target_name", ""),
            "target_username": eff.get("target_username", ""),
            # inherited = shop con đang dùng cấu hình của tài khoản chính
            "inherited": bool(eff.get("caller_session")) and not own.get("caller_session"),
        }

    @app.route("/caller/qr-login", methods=["POST"])
    def caller_qr():
        ws, err = _owner_ws()
        if err:
            return err
        if not (Config.TELEGRAM_API_ID and Config.TELEGRAM_API_HASH):
            return {"ok": False, "error": "Máy chủ chưa cấu hình TELEGRAM_API_ID/"
                    "TELEGRAM_API_HASH (my.telegram.org) — báo quản trị nền tảng"}, 503
        return jsonify(telegram_login.start_login(_login_key(ws)))

    @app.route("/caller/login-status")
    def caller_login_status():
        ws, err = _owner_ws()
        if err:
            return err
        st = telegram_login.status(_login_key(ws))
        if st.get("state") == "done":
            res = telegram_login.take_result(_login_key(ws))
            if res:
                session, profile = res
                shop_caller.set_session(ws, session, profile)
        return jsonify(st)

    @app.route("/caller/password", methods=["POST"])
    def caller_password():
        ws, err = _owner_ws()
        if err:
            return err
        pw = (request.get_json(force=True, silent=True) or {}).get("password") or ""
        res = telegram_login.submit_password(_login_key(ws), pw)
        if res.get("ok"):
            got = telegram_login.take_result(_login_key(ws))
            if got:
                session, profile = got
                shop_caller.set_session(ws, session, profile)
        return jsonify(res)

    @app.route("/caller/target", methods=["POST"])
    def caller_target():
        ws, err = _owner_ws()
        if err:
            return err
        handle = (request.get_json(force=True, silent=True) or {}).get("handle") or ""
        res = shop_caller.resolve_target(ws, handle)
        return (jsonify(res), 200 if res.get("ok") else 400)

    @app.route("/caller/test-call", methods=["POST"])
    def caller_test():
        ws, err = _owner_ws()
        if err:
            return err
        if not shop_caller.call(ws):
            return {"ok": False, "error": "Chưa đủ cấu hình (acc gọi + tài khoản "
                    "nhận) hoặc gọi lỗi — xem lại 2 bước phía trên"}, 400
        return {"ok": True, "message": "Đang đổ chuông Telegram của bạn — không "
                "bắt máy sẽ gọi lại sau 3 phút (tối đa 10 lần)"}

    @app.route("/caller/logout", methods=["POST"])
    def caller_logout():
        ws, err = _owner_ws()
        if err:
            return err
        shop_caller.clear(ws)
        telegram_login.stop_login(_login_key(ws))
        return {"ok": True}

    return app
