"""
API QUẢN TRỊ NỀN TẢNG — chỉ CHỦ NỀN TẢNG (tenant.default_owner) dùng được.
Gắn vào bridge 5005, sau auth guard (staff đã bị chặn qua staff_deny "/admin").

  GET  /admin/shops            → danh sách MỌI shop trên hệ thống: gói, hạn, quota AI,
                                  số hội thoại/khách, số đơn, nhân viên, hoạt động cuối.
  GET  /admin/shops/<username> → CHI TIẾT 1 shop (read-only, KHÔNG lộ nội dung chat):
                                  đơn hàng + doanh thu, hoạt động theo ngày, kênh đã nối.
  POST /admin/shops/<username>/block {blocked} → CHẶN/BỎ CHẶN shop (khoá đăng nhập
                                  cả workspace + huỷ phiên + bot ngừng trả lời).
  POST /admin/shops/<username>/plan {action, tier, duration} → CẤP gói (không trừ ví)
                                  hoặc THU HỒI gói (hết hạn ngay).
  GET  /admin/shops/<username>/brain → NÃO BOT của shop (read-only): prompt train,
                                  dữ liệu đã dạy (knowledge), thư viện ảnh gắn web.
"""

import logging

from flask import jsonify, request

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
        if not tenant.is_platform_admin(u["username"]):
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
        # Chỉ liệt kê SHOP (role owner) — acc admin chính danh không phải shop
        for r in db.query(
                "SELECT username, homestay, created_at, COALESCE(blocked,0) AS blocked "
                "FROM users WHERE COALESCE(role,'owner') = 'owner' ORDER BY created_at"):
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
                "blocked": bool(r["blocked"]),
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

    @app.route("/admin/ai-costs")
    def admin_ai_costs():
        """GIÁ VỐN LLM theo shop (?month=YYYY-MM, mặc định tháng này) — soi shop
        nào đốt AI vượt giá gói (cost_vnd > plan_month_vnd = đang lỗ shop đó)."""
        u, err = _platform_admin_or_403()
        if err:
            return err
        from app.core import billing
        month = (request.args.get("month") or "").strip() or None
        return jsonify({"ok": True, "month": month or "", "shops": billing.ai_costs_by_shop(month)})

    @app.route("/admin/shops/<username>")
    def admin_shop_detail(username):
        """Chi tiết 1 shop cho admin — CHỈ số liệu bán hàng (đơn, doanh thu,
        hoạt động, kênh), KHÔNG trả nội dung hội thoại (tôn trọng riêng tư shop)."""
        u, err = _platform_admin_or_403()
        if err:
            return err
        from app.core import tenant
        rows = db.query(
            "SELECT username, homestay, created_at, COALESCE(blocked,0) AS blocked "
            "FROM users WHERE username=? AND COALESCE(role,'owner')='owner'", (username,))
        if not rows:
            return jsonify({"ok": False, "error": "Không tìm thấy shop"}), 404
        shop = rows[0]
        # Chủ nền tảng gộp cả dữ liệu cũ tenant='' (như /admin/shops)
        tenants = [username] + ([""] if username == tenant.default_owner() else [])
        ph = ",".join("?" for _ in tenants)

        # ── Đơn hàng: đếm theo trạng thái + doanh thu (đơn đã trả tiền trở đi) ──
        PAID = ("paid", "fulfilled", "done")
        by_status, revenue = {}, 0
        for r in db.query(
                f"SELECT status, COUNT(*) AS n, SUM(total) AS s FROM orders "
                f"WHERE tenant IN ({ph}) GROUP BY status", tuple(tenants)):
            by_status[r["status"]] = r["n"]
            if r["status"] in PAID:
                revenue += r["s"] or 0
        recent_orders = [dict(
            code=r["code"], channel=r["channel"], customer_name=r["customer_name"],
            order_type=r["order_type"], total=r["total"], status=r["status"],
            created_at=r["created_at"], due_at=r["due_at"],
        ) for r in db.query(
            f"SELECT code, channel, customer_name, order_type, total, status,"
            f" created_at, due_at FROM orders WHERE tenant IN ({ph}) "
            f"ORDER BY created_at DESC LIMIT 30", tuple(tenants))]

        # ── Doanh thu + số đơn theo NGÀY (30 ngày gần nhất, theo created_at) ──
        rev_by_day = [dict(date=r["d"], orders=r["n"], revenue=r["s"] or 0)
                      for r in db.query(
            f"SELECT substr(created_at,1,10) AS d, COUNT(*) AS n,"
            f" SUM(CASE WHEN status IN ('paid','fulfilled','done') THEN total ELSE 0 END) AS s "
            f"FROM orders WHERE tenant IN ({ph}) "
            f"AND created_at >= date('now','-30 day') GROUP BY d ORDER BY d",
            tuple(tenants))]

        # ── Hội thoại: theo kênh + hoạt động 14 ngày (sessions còn lưu) ──
        conv_by_channel = {r["account"]: r["n"] for r in db.query(
            f"SELECT account, COUNT(*) AS n FROM sessions "
            f"WHERE tenant IN ({ph}) GROUP BY account", tuple(tenants))}
        conv_total = sum(conv_by_channel.values())
        last_row = db.query(
            f"SELECT MAX(last_updated) AS m FROM sessions WHERE tenant IN ({ph})",
            tuple(tenants))
        activity_by_day = [dict(date=r["d"], conv=r["n"]) for r in db.query(
            f"SELECT substr(last_updated,1,10) AS d, COUNT(*) AS n FROM sessions "
            f"WHERE tenant IN ({ph}) AND last_updated >= date('now','-14 day') "
            f"GROUP BY d ORDER BY d", tuple(tenants))]

        # ── Kênh đã nối (apps user tự khai) + billing + nhân viên ──
        channels = [dict(name=r["name"], channel=r["channel"], created_at=r["created_at"])
                    for r in db.query(
            "SELECT name, channel, created_at FROM user_apps "
            "WHERE username=? ORDER BY created_at", (username,))]
        staff = [dict(username=r["username"], name=r["homestay"], created_at=r["created_at"])
                 for r in db.query(
            "SELECT username, homestay, created_at FROM users "
            "WHERE owner_username=? AND COALESCE(role,'owner')='staff' "
            "ORDER BY created_at", (username,))]
        b = db.query("SELECT * FROM billing WHERE username=?", (username,))
        b = dict(b[0]) if b else None

        return jsonify({"ok": True, "shop": {
            "username": shop["username"],
            "shop_name": shop["homestay"] or shop["username"],
            "created_at": shop["created_at"],
            "blocked": bool(shop["blocked"]),
            "is_platform_admin": username == tenant.default_owner(),
        }, "billing": b, "channels": channels, "staff": staff, "conversations": {
            "total": conv_total,
            "by_channel": conv_by_channel,
            "last_activity": last_row[0]["m"] if last_row else None,
            "by_day": activity_by_day,
        }, "orders": {
            "total": sum(by_status.values()),
            "revenue": revenue,
            "by_status": by_status,
            "by_day": rev_by_day,
            "recent": recent_orders,
        }})

    @app.route("/admin/shops/<username>/brain")
    def admin_shop_brain(username):
        """NÃO BOT của shop (read-only cho admin): prompt persona, kho tri thức
        đã dạy, bộ ảnh shop upload — cấu hình do shop tạo, KHÔNG phải chat khách."""
        u, err = _platform_admin_or_403()
        if err:
            return err
        rows = db.query(
            "SELECT username FROM users WHERE username=? AND COALESCE(role,'owner')='owner'",
            (username,))
        if not rows:
            return jsonify({"ok": False, "error": "Không tìm thấy shop"}), 404
        from app.core import tenant, knowledge, prompt_builder
        from app.core import photo_library as pl
        shop = tenant.shop_key(username)   # chủ nền tảng → não 'default'
        try:
            prompt = prompt_builder.current(shop)
        except Exception as e:
            prompt = {"prompt": "", "source": "error", "mode": "", "error": str(e)}
        chunks = [dict(id=c.get("id"), title=c.get("title"), content=c.get("content"),
                       keywords=c.get("keywords") or [], pinned=bool(c.get("pinned")))
                  for c in knowledge.list_chunks(shop)]
        photos = pl.list_sets(tenant_ws=username)
        return jsonify({"ok": True, "shop_key": shop, "prompt": prompt,
                        "knowledge": chunks, "photos": photos})

    def _shop_or_404(username):
        """Shop hợp lệ để admin thao tác: tồn tại, role owner, KHÔNG phải chủ nền tảng."""
        from app.core import tenant
        rows = db.query(
            "SELECT username FROM users WHERE username=? AND COALESCE(role,'owner')='owner'",
            (username,))
        if not rows:
            return ({"ok": False, "error": "Không tìm thấy shop"}, 404)
        if username == tenant.default_owner():
            return ({"ok": False, "error": "Không thể thao tác lên chủ nền tảng"}, 400)
        return None

    @app.route("/admin/shops/<username>/block", methods=["POST"])
    def admin_shop_block(username):
        u, err = _platform_admin_or_403()
        if err:
            return err
        bad = _shop_or_404(username)
        if bad:
            return bad
        data = request.get_json(force=True, silent=True) or {}
        blocked = 1 if data.get("blocked") else 0
        db.execute("UPDATE users SET blocked=? WHERE username=?", (blocked, username))
        if blocked:
            # Huỷ mọi phiên đăng nhập của shop + nhân viên của shop (đá ra ngay)
            db.execute(
                "DELETE FROM auth_tokens WHERE username=? OR username IN "
                "(SELECT username FROM users WHERE owner_username=?)",
                (username, username))
        from app.core import billing
        billing._invalidate_cache()
        log.info(f"[admin] {u['username']} {'CHẶN' if blocked else 'BỎ CHẶN'} shop {username}")
        return jsonify({"ok": True, "blocked": bool(blocked)})

    @app.route("/admin/shops/<username>/plan", methods=["POST"])
    def admin_shop_plan(username):
        u, err = _platform_admin_or_403()
        if err:
            return err
        bad = _shop_or_404(username)
        if bad:
            return bad
        data = request.get_json(force=True, silent=True) or {}
        action = (data.get("action") or "").strip()
        from app.core import billing
        try:
            if action == "grant":
                st = billing.admin_grant(username, (data.get("tier") or "").strip(),
                                         (data.get("duration") or "").strip())
            elif action == "revoke":
                st = billing.admin_revoke(username)
            else:
                return {"ok": False, "error": "action phải là grant hoặc revoke"}, 400
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        log.info(f"[admin] {u['username']} {action} gói shop {username}")
        return jsonify({"ok": True, "billing": st})

    return app
