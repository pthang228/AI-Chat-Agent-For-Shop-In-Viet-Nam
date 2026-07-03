"""
API Prompt Builder — gắn vào bridge (5005). Tất cả cần Bearer token.

  GET  /prompt/current                       → prompt đang dùng (custom/default)
  POST /prompt/generate {links[], instructions} → AI viết prompt chi tiết (chậm 20-60s)
  POST /prompt/apply {prompt}                → shop ĐỒNG Ý → lưu, bot dùng ngay
  POST /prompt/restore-default               → quay về prompt mặc định
"""

import logging

from flask import request

from app.core import prompt_builder
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

log = logging.getLogger("prompt_api")


def register_prompt_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    @app.route("/prompt/current")
    def prompt_current():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.current()}

    @app.route("/prompt/generate", methods=["POST"])
    def prompt_generate():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        links = data.get("links") or []
        instructions = data.get("instructions") or ""
        if not isinstance(links, list):
            return {"ok": False, "error": "links phải là danh sách"}, 400
        try:
            r = prompt_builder.generate(links, instructions)
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        except Exception as e:
            log.error(f"[prompt] generate lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"Tạo prompt thất bại: {e}"}, 502
        log.info(f"[prompt] {u['username']} tạo prompt ({len(r['draft'])} ký tự, {len(links)} link)")
        return {"ok": True, **r}

    @app.route("/prompt/apply", methods=["POST"])
    def prompt_apply():
        u, err = _auth_or_401()
        if err:
            return err
        data = request.get_json(force=True, silent=True) or {}
        try:
            r = prompt_builder.apply(data.get("prompt") or "")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[prompt] {u['username']} ĐÃ ÁP DỤNG prompt mới")
        return {"ok": True, **r}

    @app.route("/prompt/restore-default", methods=["POST"])
    def prompt_restore():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **prompt_builder.restore_default()}

    return app
