"""
API Loyalty (mã giảm giá + điểm) — gắn vào bridge 5005, sau auth guard (Bearer).

  GET    /vouchers                      → danh sách mã của shop
  POST   /vouchers {code, kind, value, min_total?, max_uses?, expires_at?, note?}
  PATCH  /vouchers/<id> {active?, note?, max_uses?, expires_at?, min_total?}
  DELETE /vouchers/<id>
  POST   /vouchers/check {code, total}  → thử mã (xem giảm bao nhiêu, chưa áp)
  POST   /orders/<id>/voucher {code}    → áp mã vào đơn (draft/awaiting_payment)
"""

import logging

from flask import request, jsonify

from app.core import loyalty

log = logging.getLogger("loyalty_api")


def register_loyalty_routes(app):

    def _ws():
        from app.core import tenant
        return tenant.current_workspace_or_none()

    def _visible(v) -> bool:
        ws = _ws()
        if ws is None:
            return True
        from app.core import tenant as _t
        return _t.visible(v.get("tenant", "") or "", ws)

    @app.route("/vouchers")
    def vouchers_list():
        return jsonify(loyalty.list_vouchers(tenant_ws=_ws()))

    @app.route("/vouchers", methods=["POST"])
    def vouchers_create():
        data = request.get_json(force=True, silent=True) or {}
        try:
            v = loyalty.create_voucher(
                code=data.get("code"), kind=data.get("kind", "amount"),
                value=data.get("value"), min_total=data.get("min_total", 0),
                max_uses=data.get("max_uses", 0), expires_at=data.get("expires_at"),
                note=data.get("note", ""), tenant=_ws() or "")
        except (ValueError, TypeError) as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, "voucher": v}

    @app.route("/vouchers/<int:vid>", methods=["PATCH"])
    def vouchers_update(vid):
        v = loyalty.get_voucher(vid)
        if not v or not _visible(v):
            return {"ok": False, "error": "không thấy mã"}, 404
        data = request.get_json(force=True, silent=True) or {}
        return {"ok": True, "voucher": loyalty.update_voucher(vid, **data)}

    @app.route("/vouchers/<int:vid>", methods=["DELETE"])
    def vouchers_delete(vid):
        v = loyalty.get_voucher(vid)
        if not v or not _visible(v):
            return {"ok": False, "error": "không thấy mã"}, 404
        loyalty.delete_voucher(vid)
        return {"ok": True}

    @app.route("/vouchers/check", methods=["POST"])
    def vouchers_check():
        data = request.get_json(force=True, silent=True) or {}
        r = loyalty.check(data.get("code", ""), data.get("total", 0), tenant_ws=_ws())
        # voucher đầy đủ không cần trả cho UI thử mã — chỉ discount là đủ
        return ({"ok": True, "discount": r["discount"]} if r["ok"]
                else ({"ok": False, "error": r["error"]}, 400))

    @app.route("/orders/<int:order_id>/voucher", methods=["POST"])
    def order_apply_voucher(order_id):
        data = request.get_json(force=True, silent=True) or {}
        r = loyalty.apply_to_order(order_id, data.get("code", ""), tenant_ws=_ws())
        return (r if r["ok"] else (r, 400))

    return app
