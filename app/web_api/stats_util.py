"""
Thống kê hội thoại DÙNG CHUNG cho mọi kênh (bridge/meta/telegram/tiktok).

Gộp 2 nguồn:
  - Session ĐANG SỐNG trong ConversationManager (tối đa 48h gần nhất).
  - Session ĐÃ LƯU TRỮ (conversation.py gấp lại thành 1 dòng thống kê TRƯỚC KHI
    dọn session quá 48h) → thống kê "30 ngày"/"Năm" không bị mất dữ liệu cũ.
"""

from datetime import datetime


def parse_range(from_s, to_s):
    """'YYYY-MM-DD' → (datetime đầu ngày from, datetime 23:59:59 ngày to)."""
    try:
        from_dt = datetime.fromisoformat(from_s) if from_s else None
        to_dt   = datetime(*(int(x) for x in to_s.split("-")), 23, 59, 59) if to_s else None
    except Exception:
        from_dt, to_dt = None, None
    return from_dt, to_dt


def compute_stats(conv_manager, from_s=None, to_s=None, uid_filter=None,
                  tenant_ws=None) -> dict:
    """Trả payload thống kê {total_conv, total_msg, user_msg, bot_msg, confirmed,
    by_stage, timeline}. uid_filter(uid)->bool để lọc theo kênh/bot.
    tenant_ws: MULTI-TENANT — chỉ đếm hội thoại của workspace này (None = tất cả).
    Archive giờ MANG tenant (ghi lúc dọn session) → shop thuê giữ được số liệu
    lịch sử; dòng cũ trước migrate (tenant='') chỉ chủ nền tảng thấy — visible()."""
    from_dt, to_dt = parse_range(from_s, to_s)
    total_conv = total_msg = user_msg = bot_msg = confirmed = 0
    by_stage: dict = {}
    timeline: dict = {}

    def _add(stage, n_total, n_user, n_bot, day):
        nonlocal total_conv, total_msg, user_msg, bot_msg, confirmed
        total_conv += 1
        total_msg  += n_total
        user_msg   += n_user
        bot_msg    += n_bot
        st = stage or "greeting"
        by_stage[st] = by_stage.get(st, 0) + 1
        if st == "confirmed":
            confirmed += 1
        e = timeline.setdefault(day, {"date": day, "conv": 0, "msg": 0})
        e["conv"] += 1
        e["msg"]  += n_total

    if tenant_ws:
        from app.core import tenant as _tenant

    # 1) Session đang sống trong RAM
    for uid, conv in list(conv_manager._sessions.items()):
        if uid_filter and not uid_filter(uid):
            continue
        if tenant_ws and not _tenant.visible(getattr(conv, "tenant", "") or "", tenant_ws):
            continue
        lu = conv.last_updated
        if from_dt and lu < from_dt:
            continue
        if to_dt and lu > to_dt:
            continue
        msgs = conv.messages
        _add(
            conv.stage,
            len(msgs),
            sum(1 for m in msgs if m.get("role") == "user"),
            sum(1 for m in msgs if m.get("role") == "assistant"),
            lu.strftime("%Y-%m-%d"),
        )

    # 2) Session đã lưu trữ (bị dọn khỏi RAM sau 48h không hoạt động).
    # Lọc theo tenant TỪNG DÒNG (archive ghi tenant lúc dọn) — cùng luật
    # visible() với session sống: dòng mồ côi ('') chỉ chủ nền tảng thấy.
    archived = getattr(conv_manager, "archived_stats", None)
    for row in (archived() if archived else []):
        if uid_filter and not uid_filter(row.get("user_id", "")):
            continue
        if tenant_ws and not _tenant.visible(row.get("tenant", "") or "", tenant_ws):
            continue
        day = row.get("date") or ""
        try:
            d = datetime(*(int(x) for x in day.split("-")))
        except Exception:
            continue
        if from_dt and d < from_dt:
            continue
        if to_dt and d > to_dt:
            continue
        _add(row.get("stage"), row.get("total_msg", 0), row.get("user_msg", 0),
             row.get("bot_msg", 0), day)

    return {
        "total_conv": total_conv, "total_msg": total_msg,
        "user_msg": user_msg, "bot_msg": bot_msg,
        "confirmed": confirmed, "by_stage": by_stage,
        "timeline": sorted(timeline.values(), key=lambda x: x["date"]),
    }
