"""
API CRM Khách hàng — gắn vào bridge 5005 (đọc thẳng SQLite dùng chung nên thấy
khách của MỌI kênh). Tất cả sau auth guard (Bearer).

  GET   /customers?q=&platform=&limit=&offset=      → danh sách gộp mọi kênh
  GET   /customers/<account>/<user_id>              → hồ sơ đầy đủ (profile+stats+memory+history)
  PATCH /customers/<account>/<user_id>              → cập nhật hồ sơ (ghi audit)
  POST  /customers/<account>/<user_id>/scan         → quét SĐT/email từ hội thoại (regex)
  GET   /customers/<account>/<user_id>/orders       → đơn hàng của khách
  POST  /customers/<account>/<user_id>/memory       → thêm ghi nhớ tay {content}
  POST  /customers/<account>/<user_id>/memory/ai    → AI quét hội thoại bóc facts (chậm vài giây)
  DELETE /customers/memory/<id>                     → xoá 1 ghi nhớ
"""

import logging

from flask import request, jsonify

from app.core import customers
from app.core.db import get_db

log = logging.getLogger("customers_api")


def register_customers_routes(app):

    def _ws():
        """Workspace của request — multi-tenant (None khi test/guard tắt)."""
        from app.core import tenant
        return tenant.current_workspace_or_none()

    def _owns(account, user_id) -> bool:
        """Khách này có thuộc shop đang đăng nhập không (chốt chặn ghi/scan/memory)."""
        return customers.get_customer(account, user_id, tenant_ws=_ws()) is not None

    @app.route("/customers")
    def customers_list():
        try:
            limit = min(max(int(request.args.get("limit", 200)), 1), 1000)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 200, 0
        return jsonify(customers.list_customers(
            q=request.args.get("q", ""), platform=request.args.get("platform", ""),
            limit=limit, offset=offset, tenant_ws=_ws()))

    @app.route("/customers/<account>/<path:user_id>")
    def customers_get(account, user_id):
        c = customers.get_customer(account, user_id, tenant_ws=_ws())
        if not c:
            return {"ok": False, "error": "không thấy khách"}, 404
        return jsonify({"ok": True, **c})

    @app.route("/customers/<account>/<path:user_id>", methods=["PATCH"])
    def customers_update(account, user_id):
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        data = request.get_json(force=True, silent=True) or {}
        profile = customers.update_customer(account, user_id, data)
        return {"ok": True, "profile": profile}

    @app.route("/customers/<account>/<path:user_id>/scan", methods=["POST"])
    def customers_scan(account, user_id):
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        return {"ok": True, **customers.scan_contact(account, user_id)}

    @app.route("/customers/<account>/<path:user_id>/orders")
    def customers_orders(account, user_id):
        if not _owns(account, user_id):
            return jsonify([])
        rows = get_db().query(
            "SELECT id, code, status, total, order_type, due_at, created_at "
            "FROM orders WHERE user_id=? ORDER BY id DESC LIMIT 100", (str(user_id),))
        return jsonify([dict(r) for r in rows])

    @app.route("/customers/<account>/<path:user_id>/memory", methods=["POST"])
    def customers_memory_add(account, user_id):
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        data = request.get_json(force=True, silent=True) or {}
        try:
            m = customers.add_memory(account, user_id, data.get("content"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, "memory": m}

    @app.route("/customers/<account>/<path:user_id>/memory/ai", methods=["POST"])
    def customers_memory_ai(account, user_id):
        """AI đọc hội thoại → bóc facts về khách (đồng bộ, chậm vài giây — UI hiện spinner)."""
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        try:
            added = customers.ai_extract_memory(account, user_id)
        except Exception as e:
            log.error(f"[CRM] AI quét ghi nhớ lỗi: {e}", exc_info=True)
            return {"ok": False, "error": f"AI lỗi: {e}"}, 502
        return {"ok": True, "added": added,
                "memory": customers.list_memory(account, user_id)}

    @app.route("/customers/memory/<int:mid>", methods=["DELETE"])
    def customers_memory_del(mid):
        customers.delete_memory(mid)
        return {"ok": True}

    return app
