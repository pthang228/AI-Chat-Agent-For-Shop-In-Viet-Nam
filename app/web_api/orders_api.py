"""
API Sổ đơn hàng — gắn vào bridge (5005). Tất cả cần Bearer token.

  GET    /orders?status=&channel=&q=&limit=&offset=  → danh sách đơn
  GET    /orders/summary                             → đếm theo trạng thái + doanh thu
  GET    /orders/<id>                                → chi tiết (kèm timeline)
  POST   /orders {customer_name, items, ...}         → tạo đơn tay
  PATCH  /orders/<id> {status?, items?, ...}         → sửa / đổi trạng thái
  DELETE /orders/<id>                                → xoá
"""

import logging

from flask import request

from app.core import orders
from app.web_api.auth_api import _user_for_token, _bearer
from app.core.db import get_db

log = logging.getLogger("orders_api")


def register_orders_routes(app):
    db = get_db()

    def _auth_or_401():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Phiên hết hạn — đăng nhập lại"}, 401)
        return u, None

    @app.route("/orders")
    def orders_list():
        u, err = _auth_or_401()
        if err:
            return err
        try:
            limit = min(max(int(request.args.get("limit", 100)), 1), 500)
            offset = max(int(request.args.get("offset", 0)), 0)
        except ValueError:
            limit, offset = 100, 0
        r = orders.list_orders(
            status=request.args.get("status", ""),
            channel=request.args.get("channel", ""),
            q=request.args.get("q", ""),
            limit=limit, offset=offset)
        return {"ok": True, **r}

    @app.route("/orders/summary")
    def orders_summary():
        u, err = _auth_or_401()
        if err:
            return err
        return {"ok": True, **orders.summary()}

    @app.route("/orders/<int:order_id>")
    def orders_get(order_id):
        u, err = _auth_or_401()
        if err:
            return err
        o = orders.get(order_id)
        if not o:
            return {"ok": False, "error": "Không tìm thấy đơn"}, 404
        return {"ok": True, "order": o}

    @app.route("/orders", methods=["POST"])
    def orders_create():
        u, err = _auth_or_401()
        if err:
            return err
        d = request.get_json(force=True, silent=True) or {}
        o = orders.create(
            channel=d.get("channel") or "",
            user_id=d.get("user_id") or "",
            customer_name=d.get("customer_name") or "",
            phone=d.get("phone") or "",
            order_type=d.get("order_type") or "booking",
            items=d.get("items") or [],
            total=d.get("total") or 0,
            status=d.get("status") or "draft",
            due_at=d.get("due_at") or None,
            note=d.get("note") or "")
        log.info(f"[orders] {u['username']} tạo tay {o['code']}")
        return {"ok": True, "order": o}

    @app.route("/orders/<int:order_id>", methods=["PATCH"])
    def orders_update(order_id):
        u, err = _auth_or_401()
        if err:
            return err
        d = request.get_json(force=True, silent=True) or {}
        if "status" in d and d["status"] not in orders.STATUSES:
            return {"ok": False, "error": "Trạng thái không hợp lệ"}, 400
        o = orders.update(order_id, **d)
        if not o:
            return {"ok": False, "error": "Không tìm thấy đơn"}, 404
        return {"ok": True, "order": o}

    @app.route("/orders/<int:order_id>", methods=["DELETE"])
    def orders_delete(order_id):
        u, err = _auth_or_401()
        if err:
            return err
        orders.remove(order_id)
        return {"ok": True}

    return app
