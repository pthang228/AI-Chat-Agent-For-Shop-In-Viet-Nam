"""
API QUẢN TRỊ NỀN TẢNG — chỉ CHỦ NỀN TẢNG (tenant.default_owner) dùng được.
Gắn vào bridge 5005, sau auth guard (staff đã bị chặn qua staff_deny "/admin").

  GET /admin/shops → danh sách MỌI shop trên hệ thống: gói, hạn, quota AI,
                      số hội thoại/khách, số đơn, nhân viên, hoạt động cuối.
"""

import logging

from flask import jsonify

from app.core.db import get_db
from app.web_api.auth_api import _user_for_token, _bearer

log = logging.getLogger("admin_api")


def register_admin_routes(app):
    db = get_db()

    def _platform_admin_or_403():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Cần đăng nhập"}, 401)
        from app.core import tenant
        if u["username"] != tenant.default_owner():
            return None, ({"ok": False, "error": "Chỉ quản trị nền tảng"}, 403)
        return u, None

    @app.route("/admin/shops")
    def admin_shops():
        u, err = _platform_admin_or_403()
        if err:
            return err
        from app.core import tenant
        first = tenant.default_owner()

        # Đếm hội thoại + hoạt động cuối theo tenant (1 query mỗi bảng — nhẹ)
        conv_by = {r["tenant"]: (r["n"], r["last"]) for r in db.query(
            "SELECT tenant, COUNT(*) AS n, MAX(last_updated) AS last "
            "FROM sessions GROUP BY tenant")}
        orders_by = {r["tenant"]: r["n"] for r in db.query(
            "SELECT tenant, COUNT(*) AS n FROM orders GROUP BY tenant")}
        staff_by = {r["owner_username"]: r["n"] for r in db.query(
            "SELECT owner_username, COUNT(*) AS n FROM users "
            "WHERE COALESCE(role,'owner')='staff' GROUP BY owner_username")}
        billing_by = {r["username"]: r for r in db.query("SELECT * FROM billing")}

        out = []
        for r in db.query(
                "SELECT username, homestay, created_at FROM users "
                "WHERE COALESCE(role,'owner') != 'staff' ORDER BY created_at"):
            uname = r["username"]
            # chủ nền tảng gộp cả dữ liệu cũ tenant=''
            conv_n, last = conv_by.get(uname, (0, None))
            if uname == first and "" in conv_by:
                conv_n += conv_by[""][0]
                last = max(x for x in (last, conv_by[""][1]) if x) if (last or conv_by[""][1]) else None
            b = billing_by.get(uname)
            # Gói còn hiệu lực? (lifetime hoặc expires_at trong tương lai)
            active = False
            if b:
                if b["lifetime"]:
                    active = True
                elif b["expires_at"]:
                    from datetime import datetime as _dt
                    try:
                        active = _dt.fromisoformat(b["expires_at"]) > _dt.now()
                    except Exception:
                        active = False
            out.append({
                "active": active,
                "username": uname,
                "shop_name": r["homestay"] or uname,
                "created_at": r["created_at"],
                "is_platform_admin": uname == first,
                "staff_count": staff_by.get(uname, 0),
                "conversations": conv_n,
                "orders": orders_by.get(uname, 0) + (orders_by.get("", 0) if uname == first else 0),
                "last_activity": last,
                "tier": (b["tier"] if b else "") or "",
                "plan": (b["plan"] if b else "") or "",
                "expires_at": b["expires_at"] if b else None,
                "lifetime": bool(b["lifetime"]) if b else False,
                "ai_used": (b["ai_used"] if b else 0) or 0,
                "balance": (b["balance"] if b else 0) or 0,
            })
        return jsonify({"ok": True, "total": len(out), "shops": out})

    return app
