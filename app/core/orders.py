"""
Sổ đơn hàng — Phase 1 module đơn hàng (như AloChat "Bán hàng").

Luồng: khách chốt trong chat (booking_confirmed) → brain gọi
`create_from_conversation` → AI đọc hội thoại bóc thông tin → ĐƠN NHÁP (draft)
→ chủ xem/duyệt/đổi trạng thái trong web (mục Đơn hàng) → scheduler
`start_reminder_thread` quét đơn tới hạn (due_at) → notify chủ.

Trạng thái: draft → awaiting_payment → paid → fulfilled → done (hoặc cancelled).
2 loại đơn: booking (phòng/lịch hẹn — due_at = ngày checkin/hẹn) và
goods (bán hàng — due_at = hạn gửi hàng).
"""

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta

from app.core.db import get_db

log = logging.getLogger(__name__)

STATUSES = ("draft", "awaiting_payment", "paid", "fulfilled", "done", "cancelled")
ORDER_TYPES = ("booking", "goods")
REMIND_BEFORE_HOURS = 24        # nhắc trước hạn bao lâu
REMIND_SCAN_SECONDS = 300       # chu kỳ quét đơn tới hạn


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _row_to_order(r) -> dict:
    d = dict(r)
    for k in ("items", "timeline"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    d["reminded"] = bool(d.get("reminded"))
    return d


# (Mã đơn lấy từ chính id AUTOINCREMENT của dòng vừa insert — không dùng MAX(id)
#  vì SQLite giữ sequence sau khi xoá dòng, MAX sẽ lệch với id thật.)


# ── CRUD ─────────────────────────────────────────────────────────────

def create(channel="", user_id="", customer_name="", phone="", order_type="booking",
           items=None, total=0, status="draft", due_at=None, note="") -> dict:
    if order_type not in ORDER_TYPES:
        order_type = "booking"
    if status not in STATUSES:
        status = "draft"
    items = items if isinstance(items, list) else []
    db = get_db()
    with db.lock:
        now = _now()
        timeline = [{"at": now, "event": f"Tạo đơn ({status})"}]
        cur = db.conn.execute(
            "INSERT INTO orders (code, channel, user_id, customer_name, phone, order_type,"
            " items, total, status, due_at, note, timeline, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("", channel, user_id, customer_name, phone, order_type,
             json.dumps(items, ensure_ascii=False), int(total or 0), status, due_at,
             note, json.dumps(timeline, ensure_ascii=False), now, now))
        code = f"DH{cur.lastrowid:04d}"
        db.conn.execute("UPDATE orders SET code=? WHERE id=?", (code, cur.lastrowid))
        db.conn.commit()
    log.info(f"[Orders] tạo {code} ({channel}, {order_type}, {total}đ, status={status})")
    return get_by_code(code)


def get(order_id) -> dict | None:
    rows = get_db().query("SELECT * FROM orders WHERE id=?", (order_id,))
    return _row_to_order(rows[0]) if rows else None


def get_by_code(code) -> dict | None:
    rows = get_db().query("SELECT * FROM orders WHERE code=?", (code,))
    return _row_to_order(rows[0]) if rows else None


def list_orders(status="", channel="", q="", limit=100, offset=0) -> dict:
    where, params = [], []
    if status:
        where.append("status=?"); params.append(status)
    if channel:
        where.append("channel=?"); params.append(channel)
    if q:
        where.append("(code LIKE ? OR customer_name LIKE ? OR phone LIKE ? OR note LIKE ?)")
        params += [f"%{q}%"] * 4
    sql_where = (" WHERE " + " AND ".join(where)) if where else ""
    db = get_db()
    total = db.query(f"SELECT COUNT(*) AS n FROM orders{sql_where}", tuple(params))[0]["n"]
    rows = db.query(
        f"SELECT * FROM orders{sql_where} ORDER BY id DESC LIMIT ? OFFSET ?",
        tuple(params) + (int(limit), int(offset)))
    return {"total": total, "items": [_row_to_order(r) for r in rows]}


def update(order_id, **fields) -> dict | None:
    """Sửa đơn. Đổi status → tự ghi timeline. Chỉ nhận field hợp lệ."""
    cur = get(order_id)
    if not cur:
        return None
    allowed = {"customer_name", "phone", "order_type", "items", "total",
               "status", "due_at", "note", "channel", "user_id"}
    sets, params = [], []
    timeline = cur["timeline"]
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == "status":
            if v not in STATUSES or v == cur["status"]:
                continue
            timeline.append({"at": _now(), "event": f"{cur['status']} → {v}"})
            # đổi due/hết hạn → cho phép nhắc lại nếu due_at đổi sau này
        if k == "items":
            v = json.dumps(v if isinstance(v, list) else [], ensure_ascii=False)
        if k == "total":
            v = int(v or 0)
        sets.append(f"{k}=?"); params.append(v)
    if "due_at" in fields and fields["due_at"] != cur.get("due_at"):
        sets.append("reminded=0")           # hạn mới → nhắc lại
    if not sets:
        return cur
    sets.append("timeline=?"); params.append(json.dumps(timeline, ensure_ascii=False))
    sets.append("updated_at=?"); params.append(_now())
    params.append(order_id)
    get_db().execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=?", tuple(params))
    return get(order_id)


def add_event(order_id, event: str) -> dict | None:
    """Ghi 1 dòng vào nhật ký đơn (timeline) — vd 'Nhận CK 380.000đ (tự động)'."""
    cur = get(order_id)
    if not cur:
        return None
    tl = cur["timeline"]
    tl.append({"at": _now(), "event": str(event)})
    get_db().execute("UPDATE orders SET timeline=?, updated_at=? WHERE id=?",
                     (json.dumps(tl, ensure_ascii=False), _now(), order_id))
    return get(order_id)


def remove(order_id):
    get_db().execute("DELETE FROM orders WHERE id=?", (order_id,))


def summary() -> dict:
    """Đếm theo trạng thái + doanh thu (đơn đã thanh toán trở lên, trừ huỷ)."""
    db = get_db()
    by_status = {s: 0 for s in STATUSES}
    for r in db.query("SELECT status, COUNT(*) AS n FROM orders GROUP BY status"):
        if r["status"] in by_status:
            by_status[r["status"]] = r["n"]
    rev = db.query(
        "SELECT COALESCE(SUM(total),0) AS s FROM orders WHERE status IN ('paid','fulfilled','done')")
    return {"by_status": by_status, "revenue": rev[0]["s"],
            "total": sum(by_status.values())}


# ── Bóc đơn từ hội thoại (AI) ────────────────────────────────────────

_EXTRACT_PROMPT = """Bạn là trợ lý bóc tách ĐƠN HÀNG từ hội thoại chat giữa khách và shop.
Đọc hội thoại rồi trả về DUY NHẤT một JSON (không giải thích, không markdown):
{
  "customer_name": "tên khách nếu biết, không thì chuỗi rỗng",
  "phone": "SĐT khách nếu có trong hội thoại, không thì rỗng",
  "order_type": "booking (đặt phòng/đặt lịch/đặt bàn) hoặc goods (mua hàng gửi đi)",
  "items": [{"name": "tên phòng/dịch vụ/món hàng", "qty": 1, "price": 500000}],
  "total": 500000,
  "due_at": "YYYY-MM-DDTHH:MM nếu có ngày checkin/hẹn/giao, không rõ thì null",
  "note": "ghi chú ngắn gọn giúp chủ shop hiểu đơn (ca giờ, yêu cầu đặc biệt...)"
}
Quy tắc: price/total là SỐ VND (500k → 500000); không bịa — thiếu thì để rỗng/0/null;
qty mặc định 1; đơn phòng theo ca thì ghi ca vào name/note."""


def _parse_json_loose(raw: str):
    raw = re.sub(r"^```[a-z]*\n?", "", (raw or "").strip())
    raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def extract_from_messages(messages: list) -> dict:
    """AI đọc hội thoại → dict thông tin đơn. AI hỏng → {} (caller tự fallback)."""
    convo = "\n".join(
        f"{'KHÁCH' if m.get('role') == 'user' else 'SHOP'}: {m.get('content', '')}"
        for m in messages[-24:] if m.get("content"))
    if not convo.strip():
        return {}
    try:
        from app.core.claude_ai import _call_ai
        raw = _call_ai([
            {"role": "system", "content": _EXTRACT_PROMPT},
            {"role": "user", "content": f"HỘI THOẠI:\n{convo}\n\nTrả về JSON đơn hàng."},
        ])
        data = _parse_json_loose(raw)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        log.error(f"[Orders] extract AI lỗi: {e}")
        return {}


def _ddmmyyyy_to_iso(s):
    """'25/12/2026' → '2026-12-25T14:00' (giờ checkin mặc định 14h)."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", str(s or "").strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), 14, 0) \
            .isoformat(timespec="minutes")
    except ValueError:
        return None


def create_from_conversation(user_id: str, conv, channel: str) -> dict | None:
    """Tạo ĐƠN NHÁP khi khách chốt: AI bóc hội thoại + hints sẵn có trong conv
    (checkin/selected_room/name). AI hỏng vẫn tạo đơn tối thiểu — không mất đơn."""
    try:
        data = extract_from_messages(getattr(conv, "messages", []) or [])
        items = data.get("items") if isinstance(data.get("items"), list) else []
        # Hints từ conv thắng khi AI thiếu
        room = getattr(conv, "selected_room", None)
        if not items and room:
            items = [{"name": f"Phòng {room}", "qty": 1, "price": 0}]
        due = data.get("due_at") or _ddmmyyyy_to_iso(getattr(conv, "checkin", None))
        return create(
            channel=channel or "",
            user_id=user_id,
            customer_name=data.get("customer_name") or getattr(conv, "name", "") or "",
            phone=data.get("phone") or "",
            order_type=data.get("order_type") if data.get("order_type") in ORDER_TYPES else "booking",
            items=items,
            total=int(data.get("total") or 0),
            status="draft",
            due_at=due,
            note=data.get("note") or "",
        )
    except Exception as e:
        log.error(f"[Orders] create_from_conversation lỗi: {e}", exc_info=True)
        return None


# ── Nhắc tới hạn ─────────────────────────────────────────────────────

def due_orders(within_hours=REMIND_BEFORE_HOURS) -> list:
    """Đơn CHƯA nhắc, chưa xong/huỷ, tới hạn trong within_hours tới (kể cả quá hạn)."""
    horizon = (datetime.now() + timedelta(hours=within_hours)).isoformat(timespec="minutes")
    rows = get_db().query(
        "SELECT * FROM orders WHERE reminded=0 AND due_at IS NOT NULL AND due_at != ''"
        " AND due_at <= ? AND status NOT IN ('done','cancelled')", (horizon,))
    return [_row_to_order(r) for r in rows]


def mark_reminded(order_id):
    get_db().execute("UPDATE orders SET reminded=1 WHERE id=?", (order_id,))


def _remind_text(o: dict) -> str:
    what = "khách đến (checkin/lịch hẹn)" if o["order_type"] == "booking" else "hạn gửi hàng"
    items = ", ".join(f"{i.get('name')} x{i.get('qty', 1)}" for i in o["items"]) or "(chưa có mục)"
    return (f"⏰ ĐƠN {o['code']} sắp tới {what}!\n"
            f"👤 {o['customer_name'] or o['user_id']}"
            + (f" · 📞 {o['phone']}" if o['phone'] else "") + "\n"
            f"🧾 {items} · 💰 {o['total']:,}đ · trạng thái: {o['status']}\n"
            f"🗓 Hạn: {o['due_at']}" + (f"\n📝 {o['note']}" if o['note'] else ""))


def check_and_notify(notify_fn) -> int:
    """Quét 1 lượt đơn tới hạn → gọi notify_fn(text) từng đơn. Trả số đơn đã nhắc."""
    n = 0
    for o in due_orders():
        try:
            notify_fn(_remind_text(o))
            mark_reminded(o["id"])
            n += 1
        except Exception as e:
            log.error(f"[Orders] nhắc {o['code']} lỗi: {e}")
    return n


def start_reminder_thread(notify_fn, interval=REMIND_SCAN_SECONDS):
    """Thread nền quét đơn tới hạn (gọi 1 lần từ create_bridge)."""
    def _loop():
        while True:
            try:
                n = check_and_notify(notify_fn)
                if n:
                    log.info(f"[Orders] đã nhắc {n} đơn tới hạn")
            except Exception as e:
                log.error(f"[Orders] reminder loop lỗi: {e}")
            time.sleep(interval)
    t = threading.Thread(target=_loop, daemon=True, name="orders-reminder")
    t.start()
    return t
