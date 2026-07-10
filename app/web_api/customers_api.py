"""
API CRM Khách hàng — gắn vào bridge 5005 (đọc thẳng SQLite dùng chung nên thấy
khách của MỌI kênh). Tất cả sau auth guard (Bearer).

  GET   /customers?q=&platform=&tag=&stage=&limit=&offset= → danh sách gộp mọi kênh (+đếm phễu)
  GET   /customers/<account>/<user_id>              → hồ sơ đầy đủ (profile+stats+memory+history+followups)
  PATCH /customers/<account>/<user_id>              → cập nhật hồ sơ kèm tags/stage (ghi audit)
  POST  /customers/<account>/<user_id>/scan         → quét SĐT/email từ hội thoại (regex)
  GET   /customers/<account>/<user_id>/orders       → đơn hàng của khách
  POST  /customers/<account>/<user_id>/memory       → thêm ghi nhớ tay {content}
  POST  /customers/<account>/<user_id>/memory/ai    → AI quét hội thoại bóc facts (chậm vài giây)
  DELETE /customers/memory/<id>                     → xoá 1 ghi nhớ
  GET   /customers/tags                             → mọi tag đang dùng (filter/autocomplete)
  GET   /customers/duplicates                       → nhóm hồ sơ trùng SĐT (gợi ý gộp)
  POST  /customers/merge {primary, duplicate}       → gộp hồ sơ dup vào primary
  POST  /customers/<account>/<user_id>/points       → cộng/trừ điểm tay {delta, reason}
  POST  /customers/<account>/<user_id>/followups    → thêm nhắc việc {note, due_at}
  GET   /followups                                  → việc pending toàn shop (+due_count)
  POST  /followups/<id>/done · DELETE /followups/<id>
"""

import logging

from flask import request, jsonify

from app.core import customers, followups
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
            tag=request.args.get("tag", ""), stage=request.args.get("stage", ""),
            limit=limit, offset=offset, tenant_ws=_ws()))

    @app.route("/customers/tags")
    def customers_tags():
        return jsonify(customers.all_tags(tenant_ws=_ws()))

    @app.route("/customers/duplicates")
    def customers_duplicates():
        return jsonify(customers.find_duplicates(tenant_ws=_ws()))

    @app.route("/customers/merge", methods=["POST"])
    def customers_merge():
        data = request.get_json(force=True, silent=True) or {}
        prim, dup = data.get("primary") or {}, data.get("duplicate") or {}
        for c in (prim, dup):
            if not c.get("account") or not c.get("user_id"):
                return {"ok": False, "error": "Thiếu primary/duplicate {account, user_id}"}, 400
            if not _owns(c["account"], c["user_id"]):
                return {"ok": False, "error": "không thấy khách"}, 404
        try:
            profile = customers.merge_customers(
                prim["account"], prim["user_id"], dup["account"], dup["user_id"])
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, "profile": profile}

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

    # ── Điểm thưởng (chỉnh tay — đơn done tự cộng qua loyalty) ──────
    @app.route("/customers/<account>/<path:user_id>/points", methods=["POST"])
    def customers_points(account, user_id):
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        data = request.get_json(force=True, silent=True) or {}
        try:
            delta = int(data.get("delta") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "delta phải là số"}, 400
        if delta == 0:
            return {"ok": False, "error": "delta = 0"}, 400
        pts = customers.adjust_points(account, user_id, delta,
                                      reason=str(data.get("reason") or "chỉnh tay")[:100])
        return {"ok": True, "points": pts}

    # ── Nhắc việc follow-up ─────────────────────────────────────────
    @app.route("/customers/<account>/<path:user_id>/followups", methods=["POST"])
    def followups_add(account, user_id):
        if not _owns(account, user_id):
            return {"ok": False, "error": "không thấy khách"}, 404
        data = request.get_json(force=True, silent=True) or {}
        try:
            f = followups.create(account, user_id, data.get("note"), data.get("due_at"),
                                 created_by=_username(), tenant=_ws() or "")
        except ValueError as e:
            return {"ok": False, "error": str(e)}, 400
        return {"ok": True, "followup": f}

    @app.route("/followups")
    def followups_list():
        return jsonify(followups.list_pending(tenant_ws=_ws()))

    @app.route("/followups/<int:fid>/done", methods=["POST"])
    def followups_done(fid):
        f = followups.mark_done(fid)
        if not f:
            return {"ok": False, "error": "không thấy nhắc việc"}, 404
        return {"ok": True, "followup": f}

    @app.route("/followups/<int:fid>", methods=["DELETE"])
    def followups_del(fid):
        followups.remove(fid)
        return {"ok": True}

    def _username() -> str:
        """User đang đăng nhập (rỗng khi guard tắt trong test)."""
        try:
            from app.web_api.auth_api import _user_for_token, _bearer
            u = _user_for_token(get_db(), _bearer())
            return (u or {}).get("username", "") if isinstance(u, dict) else \
                   (u["username"] if u else "")
        except Exception:
            return ""

    return app
