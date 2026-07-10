"""
LOYALTY — mã giảm giá (voucher) + điểm thưởng.

Voucher: chủ tạo mã (giảm thẳng đ hoặc %), áp vào đơn ở trạng thái draft/
awaiting_payment → total giảm, ghi timeline + redemption, used+1.

Điểm thưởng: đơn chuyển DONE → khách được cộng total // POINTS_PER_VND điểm
(orders.update gọi award_points; cột orders.points_awarded chống cộng 2 lần).
Đổi điểm: chủ trừ tay trong CRM (customers.adjust_points) rồi tự giảm đơn —
quy đổi tự động là đợt sau.
"""

import logging
import re
from datetime import datetime

from app.core.db import get_db

log = logging.getLogger(__name__)

POINTS_PER_VND = 10_000          # 10.000đ đơn done = 1 điểm
_CODE_RE = re.compile(r"^[A-Z0-9_-]{3,30}$")


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ── Voucher CRUD ─────────────────────────────────────────────────────

def create_voucher(code: str, kind: str = "amount", value: int = 0, min_total: int = 0,
                   max_uses: int = 0, expires_at: str = None, note: str = "",
                   tenant: str = "") -> dict:
    code = str(code or "").strip().upper()
    if not _CODE_RE.match(code):
        raise ValueError("Mã chỉ gồm chữ/số/gạch, 3–30 ký tự (vd GIAM50K)")
    if kind not in ("amount", "percent"):
        kind = "amount"
    value = int(value or 0)
    if value <= 0 or (kind == "percent" and value > 100):
        raise ValueError("Giá trị giảm không hợp lệ (đ > 0, % từ 1–100)")
    if expires_at:
        try:
            datetime.fromisoformat(str(expires_at))
        except (TypeError, ValueError):
            raise ValueError("Hạn dùng không hợp lệ (ISO, vd 2026-08-01)")
    db = get_db()
    with db.lock:
        dup = db.conn.execute("SELECT id FROM vouchers WHERE code=?", (code,)).fetchone()
        if dup:
            raise ValueError(f"Mã {code} đã tồn tại")
        cur = db.conn.execute(
            "INSERT INTO vouchers (code, kind, value, min_total, max_uses, used,"
            " expires_at, active, note, created_at, tenant) VALUES (?,?,?,?,?,0,?,1,?,?,?)",
            (code, kind, value, int(min_total or 0), int(max_uses or 0),
             expires_at or None, str(note or "")[:200], _now(), str(tenant or "")))
        db.conn.commit()
        vid = cur.lastrowid
    log.info(f"[Loyalty] tạo voucher {code} ({kind} {value})")
    return get_voucher(vid)


def get_voucher(vid: int) -> dict | None:
    rows = get_db().query("SELECT * FROM vouchers WHERE id=?", (vid,))
    return dict(rows[0]) if rows else None


def get_by_code(code: str) -> dict | None:
    rows = get_db().query("SELECT * FROM vouchers WHERE code=?",
                          (str(code or "").strip().upper(),))
    return dict(rows[0]) if rows else None


def _tenant_where(tenant_ws):
    if not tenant_ws:
        return "", ()
    from app.core import tenant as _t
    if tenant_ws == _t.default_owner():
        return " WHERE (tenant=? OR tenant='')", (tenant_ws,)
    return " WHERE tenant=?", (tenant_ws,)


def list_vouchers(tenant_ws: str = None) -> list:
    tw, tp = _tenant_where(tenant_ws)
    return [dict(r) for r in get_db().query(
        f"SELECT * FROM vouchers{tw} ORDER BY id DESC LIMIT 200", tp)]


def update_voucher(vid: int, **fields) -> dict | None:
    """Sửa voucher (active/note/max_uses/expires_at/min_total) — code/kind/value
    KHÔNG sửa được sau khi tạo (mã đã phát cho khách phải giữ nguyên nghĩa)."""
    cur = get_voucher(vid)
    if not cur:
        return None
    allowed = {"active", "note", "max_uses", "expires_at", "min_total"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k in ("active", "max_uses", "min_total"):
            v = int(v or 0)
        sets.append(f"{k}=?"); params.append(v)
    if not sets:
        return cur
    params.append(vid)
    get_db().execute(f"UPDATE vouchers SET {', '.join(sets)} WHERE id=?", tuple(params))
    return get_voucher(vid)


def delete_voucher(vid: int):
    get_db().execute("DELETE FROM vouchers WHERE id=?", (vid,))


# ── Kiểm tra + áp mã vào đơn ─────────────────────────────────────────

def check(code: str, total: int, tenant_ws: str = None) -> dict:
    """Voucher dùng được cho đơn `total` không. Trả {ok, discount|error, voucher?}."""
    v = get_by_code(code)
    if not v:
        return {"ok": False, "error": "Mã không tồn tại"}
    if tenant_ws:
        from app.core import tenant as _t
        if not _t.visible(v.get("tenant", "") or "", tenant_ws):
            return {"ok": False, "error": "Mã không tồn tại"}
    if not v["active"]:
        return {"ok": False, "error": "Mã đã tắt"}
    if v["expires_at"] and str(v["expires_at"]) < _now():
        return {"ok": False, "error": "Mã đã hết hạn"}
    if v["max_uses"] and v["used"] >= v["max_uses"]:
        return {"ok": False, "error": "Mã đã hết lượt dùng"}
    total = int(total or 0)
    if total < int(v["min_total"] or 0):
        return {"ok": False, "error": f"Đơn tối thiểu {v['min_total']:,}đ mới áp được mã"}
    disc = v["value"] if v["kind"] == "amount" else total * v["value"] // 100
    disc = max(0, min(int(disc), total))
    if disc <= 0:
        return {"ok": False, "error": "Mã không giảm được gì cho đơn này"}
    return {"ok": True, "discount": disc, "voucher": v}


def apply_to_order(order_id: int, code: str, tenant_ws: str = None) -> dict:
    """Áp mã vào đơn (draft/awaiting_payment, chưa có mã): total trừ discount,
    lưu voucher_code + discount, timeline, used+1, ghi redemption.
    Trả {ok, order|error}."""
    from app.core import orders
    o = orders.get(order_id)
    if not o:
        return {"ok": False, "error": "Không thấy đơn"}
    if o.get("voucher_code"):
        return {"ok": False, "error": f"Đơn đã áp mã {o['voucher_code']}"}
    if o["status"] not in ("draft", "awaiting_payment"):
        return {"ok": False, "error": "Chỉ áp mã cho đơn chưa thanh toán"}
    r = check(code, o["total"], tenant_ws=tenant_ws)
    if not r["ok"]:
        return r
    v, disc = r["voucher"], r["discount"]
    db = get_db()
    with db.lock:
        # used+1 có điều kiện — 2 request áp song song không vượt max_uses
        cur = db.conn.execute(
            "UPDATE vouchers SET used=used+1 WHERE id=? AND (max_uses=0 OR used<max_uses)",
            (v["id"],))
        if cur.rowcount == 0:
            db.conn.commit()
            return {"ok": False, "error": "Mã đã hết lượt dùng"}
        db.conn.execute(
            "UPDATE orders SET total=?, voucher_code=?, discount=?, updated_at=? WHERE id=?",
            (o["total"] - disc, v["code"], disc, _now(), order_id))
        db.conn.execute(
            "INSERT INTO voucher_redemptions (voucher_id, order_id, user_id, amount,"
            " created_at) VALUES (?,?,?,?,?)",
            (v["id"], order_id, o.get("user_id") or "", disc, _now()))
        db.conn.commit()
    orders.add_event(order_id, f"Áp mã {v['code']} −{disc:,}đ")
    log.info(f"[Loyalty] đơn #{order_id} áp {v['code']} giảm {disc}")
    return {"ok": True, "order": orders.get(order_id)}


# ── Điểm thưởng ──────────────────────────────────────────────────────

def award_points(order: dict) -> int:
    """Đơn DONE → cộng total // POINTS_PER_VND điểm cho khách (orders.update gọi).
    Trả số điểm đã cộng (0 nếu không đủ điều kiện). Không raise — loyalty chết
    không được kéo sập việc đổi trạng thái đơn."""
    try:
        if not order or order.get("status") != "done" or order.get("points_awarded"):
            return 0
        pts = int(order.get("total") or 0) // POINTS_PER_VND
        uid = order.get("user_id") or ""
        if pts <= 0 or not uid:
            return 0
        from app.core import customers
        target = customers.resolve_customer(uid)
        if not target:
            return 0
        customers.adjust_points(target[0], target[1], pts,
                                reason=f"Đơn {order.get('code', '')} hoàn tất")
        get_db().execute("UPDATE orders SET points_awarded=? WHERE id=?",
                         (pts, order["id"]))
        log.info(f"[Loyalty] +{pts} điểm cho {target} (đơn {order.get('code')})")
        return pts
    except Exception as e:
        log.error(f"[Loyalty] cộng điểm lỗi: {e}", exc_info=True)
        return 0
