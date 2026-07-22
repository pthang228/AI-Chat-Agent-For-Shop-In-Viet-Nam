"""
ĐO THỜI GIAN PHẢN HỒI BOT — nuôi biểu đồ "Thời gian phản hồi (giây)" Thống kê.

record() gọi từ brain.handle (mọi kênh dùng chung não → đo 1 chỗ phủ 6 kênh):
tính từ lúc tin khách vào handle tới lúc bot gửi xong trả lời (gồm AI + gửi).
stats() trả avg + P95 tổng và theo NGÀY, lọc multi-tenant (shop con là tenant
riêng nên tự tách). Log tự dọn sau RETENTION_DAYS ngày (gọi kèm trong stats).
"""

import logging
from datetime import datetime, timedelta

from app.core.db import get_db

log = logging.getLogger(__name__)

RETENTION_DAYS = 90
MAX_SECONDS = 600          # outlier guard: treo mạng/AI > 10 phút thì bỏ, khỏi phá avg


def record(tenant: str, seconds: float) -> None:
    """Ghi 1 lượt trả lời. Best-effort — đo hỏng không được chặn luồng bot."""
    try:
        s = float(seconds)
        if s <= 0 or s > MAX_SECONDS:
            return
        get_db().execute(
            "INSERT INTO latency_log (tenant, seconds, created_at) VALUES (?,?,?)",
            ((tenant or "").strip(), round(s, 3), datetime.now().isoformat()))
    except Exception as e:
        log.warning(f"[latency] record lỗi: {e}")


def cleanup(days: int = RETENTION_DAYS) -> int:
    try:
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        return get_db().execute(
            "DELETE FROM latency_log WHERE created_at < ?", (cutoff,)).rowcount
    except Exception as e:
        log.warning(f"[latency] cleanup lỗi: {e}")
        return 0


def _p95(values: list) -> float:
    vs = sorted(values)
    return vs[int(0.95 * (len(vs) - 1))] if vs else 0.0


def stats(from_s: str = None, to_s: str = None, tenant_ws: str = None) -> dict:
    """{avg, p95, n, timeline: [{date, avg, p95, n}]} trong khoảng from→to
    (YYYY-MM-DD, bao trọn ngày to). tenant_ws lọc theo shop (None = tất cả —
    dòng tenant='' thời chưa multi-tenant chỉ chủ nền tảng thấy, cùng luật
    tenant_where của mọi bảng)."""
    cleanup()
    from app.core.tenant import tenant_where
    frag, params = tenant_where(tenant_ws)
    where, args = [], []
    if frag:
        where.append(frag); args += params
    if from_s:
        where.append("created_at >= ?"); args.append(str(from_s))
    if to_s:
        where.append("created_at <= ?"); args.append(str(to_s) + "T23:59:59")
    sql = "SELECT seconds, created_at FROM latency_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    by_day, all_vals = {}, []
    try:
        for r in get_db().query(sql, tuple(args)):
            day = str(r["created_at"])[:10]
            by_day.setdefault(day, []).append(r["seconds"])
            all_vals.append(r["seconds"])
    except Exception as e:
        log.warning(f"[latency] stats lỗi: {e}")
    timeline = [
        {"date": d, "n": len(vs),
         "avg": round(sum(vs) / len(vs), 2), "p95": round(_p95(vs), 2)}
        for d, vs in sorted(by_day.items())
    ]
    return {
        "n": len(all_vals),
        "avg": round(sum(all_vals) / len(all_vals), 2) if all_vals else 0,
        "p95": round(_p95(all_vals), 2) if all_vals else 0,
        "timeline": timeline,
    }
