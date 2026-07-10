"""
NHẮC VIỆC FOLLOW-UP — "hẹn chăm lại khách này ngày X" (mục Khách hàng).

Khách hỏi giá chưa chốt, hẹn gọi lại, hẹn báo hàng về... → chủ đặt nhắc việc
gắn vào khách. CRM hiện panel "việc đến hạn" đầu trang + tab trong drawer khách.
Không có job nền — panel poll khi mở trang (đủ cho shop nhỏ; đẩy notify là đợt sau).
"""

import logging
from datetime import datetime

from app.core.db import get_db

log = logging.getLogger(__name__)

MAX_NOTE = 300


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _row(r) -> dict:
    return dict(r)


def create(account: str, user_id: str, note: str, due_at: str,
           created_by: str = "", tenant: str = "") -> dict:
    note = str(note or "").strip()[:MAX_NOTE]
    due_at = str(due_at or "").strip()
    if not note:
        raise ValueError("Nội dung nhắc việc trống")
    try:
        datetime.fromisoformat(due_at)
    except (TypeError, ValueError):
        raise ValueError("Ngày hẹn không hợp lệ (cần ISO, vd 2026-07-15)")
    db = get_db()
    with db.lock:
        cur = db.conn.execute(
            "INSERT INTO followups (account, user_id, note, due_at, status,"
            " created_by, created_at, tenant) VALUES (?,?,?,?,'pending',?,?,?)",
            (str(account), str(user_id), note, due_at,
             str(created_by or ""), _now(), str(tenant or "")))
        db.conn.commit()
        fid = cur.lastrowid
    return get(fid)


def get(fid: int) -> dict | None:
    rows = get_db().query("SELECT * FROM followups WHERE id=?", (fid,))
    return _row(rows[0]) if rows else None


def list_for(account: str, user_id: str) -> list:
    """Nhắc việc của 1 khách — pending trước (gần hạn nhất trên đầu), done sau."""
    rows = get_db().query(
        "SELECT * FROM followups WHERE account=? AND user_id=?"
        " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, due_at ASC LIMIT 100",
        (str(account), str(user_id)))
    return [_row(r) for r in rows]


def _tenant_where(tenant_ws):
    if not tenant_ws:
        return "", ()
    from app.core import tenant as _t
    if tenant_ws == _t.default_owner():
        return " AND (tenant=? OR tenant='')", (tenant_ws,)
    return " AND tenant=?", (tenant_ws,)


def list_pending(tenant_ws: str = None, limit: int = 100) -> dict:
    """Việc chưa xong toàn shop, gần hạn nhất trước + đếm số việc ĐÃ tới hạn.
    Trả {due_count, items:[... kèm customer_name để hiện panel]}."""
    db = get_db()
    tw, tp = _tenant_where(tenant_ws)
    rows = db.query(
        f"SELECT * FROM followups WHERE status='pending'{tw} ORDER BY due_at ASC LIMIT ?",
        tp + (limit,))
    # Tên khách: ưu tiên hồ sơ CRM, rơi về tên kênh trong sessions
    names = {}
    for r in db.query("SELECT account, user_id, name FROM sessions"):
        names[(r["account"], r["user_id"])] = r["name"] or ""
    for r in db.query("SELECT account, user_id, name FROM customers"):
        if r["name"]:
            names[(r["account"], r["user_id"])] = r["name"]
    now = _now()
    items = []
    for r in rows:
        d = _row(r)
        d["customer_name"] = names.get((d["account"], d["user_id"]), "") \
            or f"…{str(d['user_id'])[-6:]}"
        d["overdue"] = d["due_at"] <= now
        items.append(d)
    return {"due_count": sum(1 for i in items if i["overdue"]), "items": items}


def mark_done(fid: int) -> dict | None:
    f = get(fid)
    if not f:
        return None
    get_db().execute("UPDATE followups SET status='done', done_at=? WHERE id=?",
                     (_now(), fid))
    return get(fid)


def remove(fid: int):
    get_db().execute("DELETE FROM followups WHERE id=?", (fid,))
