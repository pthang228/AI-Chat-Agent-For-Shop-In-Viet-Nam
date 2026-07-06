"""
API COPILOT QUẢN TRỊ — gắn vào bridge 5005 (cần Bearer để biết CHỦ nào đang
đăng nhập → scope dữ liệu theo tài khoản đó).

  POST /copilot/chat    {message, history[]}          → {reply, navigate, pending_action}
  POST /copilot/confirm {name, args}                  → chạy action ghi đã được chủ xác nhận
"""

import logging

from flask import request

from app.core import copilot
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

log = logging.getLogger("copilot_api")


def register_copilot_routes(app):
    db = get_db()

    def _user_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    @app.route("/copilot/chat", methods=["POST"])
    def copilot_chat():
        u, err = _user_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        message = str(data.get("message") or "").strip()
        if not message:
            return {"ok": False, "error": "thiếu message"}, 400
        history = data.get("history") if isinstance(data.get("history"), list) else []
        try:
            r = copilot.chat(u["username"], message, history)
        except Exception as e:
            log.error(f"[copilot] chat lỗi: {e}", exc_info=True)
            return {"ok": False, "error": "Trợ lý đang quá tải, thử lại sau giây lát ạ."}, 502
        return {"ok": True, **r}

    @app.route("/copilot/confirm", methods=["POST"])
    def copilot_confirm():
        u, err = _user_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        name = str(data.get("name") or "").strip()
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        sig = str(data.get("sig") or "")
        r = copilot.confirm_action(u["username"], name, args, sig)
        return {"ok": r["ok"], "message": r["message"]}

    return app
