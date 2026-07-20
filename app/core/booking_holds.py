"""
GIỮ CHỖ TẠM (hold) — chống double-booking.

Vấn đề: lịch nằm trên Google Sheet do CHỦ ghi tay + cache TTL 45s, bot không ghi
ngược vào sheet → 2 khách chốt cùng ca trong cửa sổ ngắn đều được xác nhận "còn
chỗ", cùng nhận QR cọc — 1 khách chuyển tiền cho ca đã mất, chủ phải hoàn tiền.

Giải pháp: khi bot sắp TỰ CHỐT cho 1 khách → đặt hold (tenant, ngày, phòng) sống
BOOKING_HOLD_MINUTES phút trong SQLite (mọi tiến trình kênh thấy ngay, WAL).
Hội thoại KHÁC cùng shop chốt ngày giao nhau khi hold còn sống → bot KHÔNG tự
chốt mà đẩy về chủ xác nhận thứ tự. Bảo thủ có chủ đích: thà hỏi chủ thừa một
lần còn hơn nhận cọc 2 khách cho 1 ca.

Phòng (room): 2 hold cùng ngày nhưng KHÁC phòng (cả 2 đều ghi rõ phòng) → không
tính tranh chấp; thiếu thông tin phòng ở 1 trong 2 phía → tính tranh chấp.
"""

import logging
import os
from datetime import datetime, timedelta

from app.core.db import get_db

log = logging.getLogger(__name__)

HOLD_MINUTES = int(os.getenv("BOOKING_HOLD_MINUTES", "30"))
_MAX_RANGE_DAYS = 60          # trần range ngày khi so giao nhau (chống input rác)


def _ensure_table(db):
    db.conn.execute(
        "CREATE TABLE IF NOT EXISTS booking_holds ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " tenant     TEXT NOT NULL DEFAULT '',"
        " user_id    TEXT NOT NULL,"
        " checkin    TEXT NOT NULL,"          # dd/mm/yyyy (định dạng brain dùng)
        " checkout   TEXT NOT NULL DEFAULT '',"
        " room       TEXT NOT NULL DEFAULT '',"
        " created_at TEXT NOT NULL,"
        " expires_at TEXT NOT NULL)")
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_holds_tenant_exp"
        " ON booking_holds(tenant, expires_at)")
    db.conn.commit()


def _dates(checkin: str, checkout: str = "") -> set:
    """Tập ngày (date) của range [checkin, checkout] — rỗng nếu không parse được."""
    try:
        ci = datetime.strptime((checkin or "").strip(), "%d/%m/%Y").date()
    except Exception:
        return set()
    try:
        co = datetime.strptime((checkout or "").strip(), "%d/%m/%Y").date()
    except Exception:
        co = ci
    if co < ci:
        co = ci
    n = min((co - ci).days, _MAX_RANGE_DAYS)
    return {ci + timedelta(days=i) for i in range(n + 1)}


def cleanup(db=None):
    """Dọn hold hết hạn (gọi kèm mỗi thao tác — bảng luôn nhỏ)."""
    db = db or get_db()
    _ensure_table(db)
    db.execute("DELETE FROM booking_holds WHERE expires_at < ?",
               (datetime.now().isoformat(),))


def place_hold(tenant: str, user_id: str, checkin: str, checkout: str = "",
               room: str = None, minutes: int = None) -> int:
    """Đặt/gia hạn hold cho khách này (mỗi khách 1 hold mới nhất). Trả id."""
    db = get_db()
    _ensure_table(db)
    now = datetime.now()
    mins = HOLD_MINUTES if minutes is None else minutes
    with db.lock:
        # khách chốt lại (đổi ngày/phòng) → thay hold cũ của chính họ
        db.conn.execute(
            "DELETE FROM booking_holds WHERE tenant=? AND user_id=?",
            (tenant or "", user_id))
        cur = db.conn.execute(
            "INSERT INTO booking_holds(tenant, user_id, checkin, checkout, room,"
            " created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
            (tenant or "", user_id, (checkin or "").strip(),
             (checkout or "").strip(), (room or "").strip(),
             now.isoformat(), (now + timedelta(minutes=mins)).isoformat()))
        db.conn.commit()
    log.info(f"[Holds] {user_id} giữ {checkin}→{checkout or checkin}"
             f"{' phòng ' + room if room else ''} ({mins}′, tenant={tenant or 'gốc'})")
    return cur.lastrowid


def conflicting_holds(tenant: str, user_id: str, checkin: str,
                      checkout: str = "", room: str = None) -> list:
    """Hold CÒN SỐNG của khách KHÁC cùng shop, ngày giao nhau (và đụng phòng).
    Trả list dict — rỗng nghĩa là an toàn để tự chốt."""
    db = get_db()
    cleanup(db)
    want = _dates(checkin, checkout)
    if not want:
        return []                # không parse được ngày → không chặn (verify Sheets lo)
    out = []
    rows = db.query(
        "SELECT * FROM booking_holds WHERE tenant=? AND user_id != ? AND expires_at >= ?",
        (tenant or "", user_id, datetime.now().isoformat()))
    for r in rows:
        if not want.intersection(_dates(r["checkin"], r["checkout"])):
            continue
        # khác phòng rõ ràng cả 2 phía → không tranh chấp
        if room and r["room"] and room.strip() != r["room"]:
            continue
        out.append(dict(r))
    return out


def release(tenant: str, user_id: str):
    """Nhả hold của 1 khách (chủ huỷ đơn / khách đổi ý)."""
    db = get_db()
    _ensure_table(db)
    db.execute("DELETE FROM booking_holds WHERE tenant=? AND user_id=?",
               (tenant or "", user_id))
