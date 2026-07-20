"""
NHẮC VIỆC FOLLOW-UP — "hẹn chăm lại khách này ngày X" (mục Khách hàng).

Khách hỏi giá chưa chốt, hẹn gọi lại, hẹn báo hàng về... → chủ đặt nhắc việc
gắn vào khách. CRM hiện panel "việc đến hạn" đầu trang + tab trong drawer khách.
Ngoài panel (poll khi mở trang) còn có JOB NỀN start_reminder_thread — quét mỗi
5 phút, việc tới hạn chưa báo → notify_fn(text) tới chủ (cùng pattern
orders.start_reminder_thread; bridge wire lúc khởi động).
"""

import logging
import threading
import time
from datetime import datetime

from app.core.db import get_db

log = logging.getLogger(__name__)

MAX_NOTE = 300
REMIND_SCAN_SECONDS = 300   # chu kỳ quét việc tới hạn (5 phút — cùng nhịp orders)


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
    """Mảnh ' AND ...' multi-tenant (nguồn chung: tenant.tenant_where)."""
    from app.core import tenant as _t
    frag, params = _t.tenant_where(tenant_ws)
    return (" AND " + frag, tuple(params)) if frag else ("", ())


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


# ── Job nền nhắc chủ (trước đây KHÔNG có — không mở trang là quên việc) ──

def due_unnotified() -> list:
    """Việc pending ĐÃ tới hạn mà chưa từng báo chủ (notified_at trống).
    notified_at (cột migrate thêm ở db.py) là chốt chống nhắc trùng mỗi vòng
    quét — giống orders.reminded nhưng giữ timestamp để còn debug."""
    rows = get_db().query(
        "SELECT * FROM followups WHERE status='pending' AND due_at <= ?"
        " AND (notified_at IS NULL OR notified_at='')", (_now(),))
    return [_row(r) for r in rows]


def mark_notified(fid: int):
    get_db().execute("UPDATE followups SET notified_at=? WHERE id=?", (_now(), fid))


def _customer_name(account: str, user_id: str) -> str:
    """Tên khách cho tin nhắc: ưu tiên hồ sơ CRM → tên kênh → đuôi user_id
    (cùng thứ tự với list_pending, nhưng tra 1 khách thay vì nạp cả bảng)."""
    db = get_db()
    for table in ("customers", "sessions"):
        rows = db.query(f"SELECT name FROM {table} WHERE account=? AND user_id=?",
                        (str(account), str(user_id)))
        if rows and rows[0]["name"]:
            return rows[0]["name"]
    return f"…{str(user_id)[-6:]}"


def _remind_text(f: dict) -> str:
    return (f"📌 NHẮC VIỆC tới hạn: {f['note']}\n"
            f"👤 {_customer_name(f['account'], f['user_id'])}\n"
            f"🗓 Hạn: {f['due_at']}")


def check_and_notify(notify_fn) -> int:
    """Quét 1 lượt việc tới hạn chưa báo → notify_fn(text) từng việc + đánh dấu
    đã nhắc. notify lỗi (kênh chủ chết) → KHÔNG đánh dấu, vòng sau thử lại.
    Trả về số việc đã nhắc."""
    from app.core import notify as _notify
    n = 0
    for f in due_unnotified():
        try:
            # MULTI-TENANT: việc của shop thuê đi EMAIL chủ shop đó (như orders)
            ok = _notify.deliver_to_owner(
                f.get("tenant") or "", "[NovaChat] ⏰ Nhắc việc tới hạn",
                _remind_text(f), notify_fn)
            if ok:
                mark_notified(f["id"])
                n += 1
        except Exception as e:
            log.error(f"[Followups] nhắc việc #{f['id']} lỗi: {e}")
    return n


def start_reminder_thread(notify_fn, interval=REMIND_SCAN_SECONDS):
    """Thread nền quét việc tới hạn — ĐÚNG pattern orders.start_reminder_thread
    (daemon, nuốt lỗi từng vòng để loop không chết). Chỉ EXPORT ở đây; bridge
    wire notify_fn lúc khởi động (không import bridge từ core)."""
    def _loop():
        while True:
            try:
                n = check_and_notify(notify_fn)
                if n:
                    log.info(f"[Followups] đã nhắc {n} việc tới hạn")
            except Exception as e:
                log.error(f"[Followups] reminder loop lỗi: {e}")
            time.sleep(interval)
    t = threading.Thread(target=_loop, daemon=True, name="followups-reminder")
    t.start()
    return t
