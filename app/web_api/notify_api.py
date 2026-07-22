"""
API Liên hệ khẩn cấp & Thông báo (bridge 5005, owner-only qua staff_deny "/notify").

  GET  /notify/config  → {config, events_meta, share_modes}
  POST /notify/config  → lưu (emergency_phone/zalo/tele, share_mode, events)
"""

import logging

from flask import request

from app.core import notify
# current_workspace (KHÔNG phải current_username): staff quy về chủ + tôn trọng
# X-Shop — đứng ở shop con thì Cài đặt đọc/lưu config CỦA SHOP ĐÓ (chưa lưu
# riêng thì notify.get_config tự fallback config tài khoản chính)
from app.web_api.auth_api import current_workspace as current_username

log = logging.getLogger("notify_api")


def register_notify_routes(app):

    @app.route("/notify/config")
    def notify_get():
        u = current_username()
        if not u:
            return {"ok": False, "error": "Cần đăng nhập"}, 401
        return {
            "ok": True,
            "config": notify.get_config(u),
            # Metadata cho UI dựng form (nhãn + mô tả từng sự kiện/chế độ)
            "events_meta": {k: v[0] for k, v in notify.EVENTS.items()},
            "share_modes": list(notify.SHARE_MODES),
        }

    @app.route("/notify/config", methods=["POST"])
    def notify_set():
        u = current_username()
        if not u:
            return {"ok": False, "error": "Cần đăng nhập"}, 401
        data = request.get_json(force=True, silent=True) or {}
        cfg = notify.save_config(u, data)
        log.info(f"[notify] {u} cập nhật cấu hình (share_mode={cfg['share_mode']})")
        return {"ok": True, "config": cfg}

    return app
