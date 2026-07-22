"""
API Tin nhắn hàng loạt (broadcast) — gắn vào bridge 5005, sau auth guard.
CHỈ CHỦ (owner) dùng được: guard đã chặn staff bằng staff_deny "/broadcasts".

  POST /broadcasts/preview {channels, segment}     → {count, sample}
  GET  /broadcasts                                  → list chiến dịch
  POST /broadcasts {name, message, channels, segment, send_now}
  GET  /broadcasts/<id>                             → chi tiết + log lỗi gần nhất
  POST /broadcasts/<id>/send                        → bắt đầu gửi
  POST /broadcasts/<id>/cancel                      → dừng
"""

import logging

from flask import request, jsonify

from app.core import broadcast

log = logging.getLogger("broadcast_api")


def _bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.startswith("Bearer ") else ""


def register_broadcast_routes(app):

    def _ws():
        from app.core import tenant
        return tenant.current_workspace_or_none()

    def _bc_visible(b) -> bool:
        """Chiến dịch thuộc shop đang đăng nhập (cũ chưa gắn → chủ nền tảng)."""
        from app.core import tenant as _t
        return _t.visible(b.get("created_by", "") or "", _ws())

    @app.route("/broadcasts/preview", methods=["POST"])
    def bc_preview():
        d = request.get_json(force=True, silent=True) or {}
        targets = broadcast.audience(d.get("channels") or [], d.get("segment") or {},
                                     tenant_ws=_ws())
        by_channel = {}
        for t in targets:
            by_channel[t["channel"]] = by_channel.get(t["channel"], 0) + 1
        return {"ok": True, "count": len(targets), "by_channel": by_channel,
                "sample": [{"name": t["name"], "user_id": t["user_id"],
                            "channel": t["channel"]} for t in targets[:8]]}

    @app.route("/broadcasts")
    def bc_list():
        return jsonify(broadcast.list_all(tenant_ws=_ws()))

    @app.route("/broadcasts", methods=["POST"])
    def bc_create():
        d = request.get_json(force=True, silent=True) or {}
        message = (d.get("message") or "").strip()
        if len(message) < 5:
            return {"ok": False, "error": "Nội dung tin quá ngắn (tối thiểu 5 ký tự)"}, 400
        channels = [c for c in (d.get("channels") or []) if c in broadcast.CHANNELS]
        if not channels:
            return {"ok": False, "error": "Chọn ít nhất 1 kênh"}, 400
        # created_by = WORKSPACE (shop đang chọn) — audience/worker lọc khách
        # theo tenant=shop; dùng username thô thì shop con sẽ gửi 0 khách
        b = broadcast.create(d.get("name") or "", message, channels,
                             d.get("segment") or {}, _ws() or "")
        if d.get("send_now"):
            broadcast.start(b["id"], auth_token=_bearer())
            b = broadcast.get(b["id"])
        return {"ok": True, "broadcast": b}

    @app.route("/broadcasts/<int:bid>")
    def bc_get(bid):
        b = broadcast.get(bid)
        if not b or not _bc_visible(b):
            return {"ok": False, "error": "Không tìm thấy chiến dịch"}, 404
        b["errors"] = broadcast.logs(bid, limit=50, only_failed=True)
        return {"ok": True, "broadcast": b}

    @app.route("/broadcasts/<int:bid>/send", methods=["POST"])
    def bc_send(bid):
        b = broadcast.get(bid)
        if not b or not _bc_visible(b):
            return {"ok": False, "error": "Không tìm thấy chiến dịch"}, 404
        if not broadcast.start(bid, auth_token=_bearer()):
            return {"ok": False, "error": "Chiến dịch không ở trạng thái nháp"}, 400
        return {"ok": True}

    @app.route("/broadcasts/<int:bid>/cancel", methods=["POST"])
    def bc_cancel(bid):
        b = broadcast.get(bid)
        if not b or not _bc_visible(b):
            return {"ok": False, "error": "Không tìm thấy chiến dịch"}, 404
        if not broadcast.cancel(bid):
            return {"ok": False, "error": "Chiến dịch không thể dừng"}, 400
        return {"ok": True}

    return app
