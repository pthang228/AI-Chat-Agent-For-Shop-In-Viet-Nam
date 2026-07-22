"""
API LỊCH ĐẶT CHỖ per-shop (Google Sheets) — gắn vào bridge 5005, sau auth guard.

Mỗi shop tự DÁN LINK Google Sheet lịch phòng của mình → hệ thống tự bóc sheet ID,
bot tra lịch trống theo sheet CỦA SHOP đó (xem sheets.homestays_for). Shop cần
share sheet (quyền Viewer) cho email service account trả về ở GET /sheets.

  GET    /sheets              → danh sách sheet của shop + service_email để share
  POST   /sheets {name, link} → thêm sheet (tự bóc ID từ link hoặc nhận thẳng ID)
  DELETE /sheets/<id>         → xoá sheet của shop mình

Nhân viên (staff) bị chặn qua staff_deny ("/sheets").
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from flask import request, jsonify

from app.core.config import Config
from app.core.db import get_db
from app.core.sheets import extract_sheet_id
from app.web_api.auth_api import _user_for_token, _bearer, request_workspace

log = logging.getLogger("sheets_api")

MAX_SHEETS = 5


def register_sheets_routes(app):
    db = get_db()

    def _auth():
        u = _user_for_token(db, _bearer())
        if u is None:
            return None, ({"ok": False, "error": "Cần đăng nhập"}, 401)
        return u, None

    def _service_email():
        """Email service account (google_credentials.json) — shop share sheet cho email này."""
        try:
            data = json.loads(Path(Config.GOOGLE_CREDENTIALS_FILE).read_text(encoding="utf-8"))
            return data.get("client_email") or ""
        except Exception:
            return ""

    @app.route("/sheets")
    def sheets_list():
        u, err = _auth()
        if err:
            return err
        ws = request_workspace(u)
        rows = db.query(
            "SELECT id, name, sheet_id, created_at FROM shop_sheets "
            "WHERE tenant=? ORDER BY id", (ws,))
        return jsonify({"ok": True, "sheets": [dict(r) for r in rows],
                        "service_email": _service_email(), "max": MAX_SHEETS})

    @app.route("/sheets", methods=["POST"])
    def sheets_add():
        u, err = _auth()
        if err:
            return err
        ws = request_workspace(u)
        data = request.get_json(force=True, silent=True) or {}
        sid = extract_sheet_id(data.get("link") or "")
        if not sid:
            return {"ok": False, "error": "Link không hợp lệ — dán link Google Sheets "
                    "dạng https://docs.google.com/spreadsheets/d/…"}, 400
        name = (data.get("name") or "").strip()[:60] or "Chi nhánh"
        n = db.query("SELECT COUNT(*) AS n FROM shop_sheets WHERE tenant=?", (ws,))[0]["n"]
        if n >= MAX_SHEETS:
            return {"ok": False, "error": f"Tối đa {MAX_SHEETS} sheet mỗi shop"}, 400
        if db.query("SELECT 1 FROM shop_sheets WHERE tenant=? AND sheet_id=?", (ws, sid)):
            log.info(f"[Sheets] {ws} thêm sheet TRÙNG ({sid[:12]}…) → 409 (đã nối từ trước)")
            return {"ok": False, "error": "Sheet này đã được thêm rồi"}, 409
        db.execute(
            "INSERT INTO shop_sheets(tenant, name, sheet_id, created_at) VALUES (?,?,?,?)",
            (ws, name, sid, datetime.now().isoformat()))
        row = db.query(
            "SELECT id, name, sheet_id, created_at FROM shop_sheets "
            "WHERE tenant=? AND sheet_id=?", (ws, sid))[0]
        log.info(f"[Sheets] {ws} thêm sheet {name} ({sid[:12]}…)")
        return jsonify({"ok": True, "sheet": dict(row), "service_email": _service_email()})

    @app.route("/sheets/<int:sid>", methods=["DELETE"])
    def sheets_delete(sid):
        u, err = _auth()
        if err:
            return err
        ws = request_workspace(u)
        if not db.query("SELECT 1 FROM shop_sheets WHERE id=? AND tenant=?", (sid, ws)):
            return {"ok": False, "error": "Không tìm thấy sheet"}, 404
        db.execute("DELETE FROM shop_sheets WHERE id=? AND tenant=?", (sid, ws))
        return {"ok": True}

    return app
