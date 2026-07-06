"""
MULTI-TENANT — tách dữ liệu theo từng SHOP (tenant = username chủ shop).

Mô hình: mỗi kênh đã gắn CHỦ khi kết nối (store.owner_username — dùng cho billing
từ trước). Khi tin khách đến, kênh resolve owner → `assign()` đóng dấu tenant vào
hội thoại. Mọi API đọc lọc bằng `visible()` theo workspace của user đăng nhập
(auth_api.current_workspace — nhân viên quy về chủ).

Kênh CHƯA gắn chủ (kết nối trước khi có billing owner, hoặc Zalo cá nhân bản
single-instance) → fallback về CHỦ NỀN TẢNG (user đầu tiên không phải nhân viên)
để dữ liệu không mồ côi — khớp với db._migrate_tenant().
"""

import logging

from app.core.db import get_db

log = logging.getLogger(__name__)

_default_cache = {"t": 0.0, "v": None}
_DEFAULT_TTL = 60


def default_owner() -> str:
    """Chủ nền tảng (user đầu tiên, role != staff). Cache 60s — gọi mỗi tin."""
    import time
    now = time.time()
    if _default_cache["v"] is not None and now - _default_cache["t"] < _DEFAULT_TTL:
        return _default_cache["v"]
    v = ""
    try:
        rows = get_db().query(
            "SELECT username FROM users WHERE COALESCE(role,'owner') != 'staff' "
            "ORDER BY created_at LIMIT 1")
        v = rows[0]["username"] if rows else ""
    except Exception:
        pass
    _default_cache.update(t=now, v=v)
    return v


def assign(conv_manager, user_id: str, owner: str | None):
    """Đóng dấu tenant cho hội thoại (gọi lúc kênh nhận tin, TRƯỚC brain.handle).
    Chỉ gán khi chưa có (tenant là bất biến sau lần đầu — không cho tin sau
    'cướp' hội thoại sang shop khác). Không có owner → chủ nền tảng."""
    try:
        conv = conv_manager.get(user_id)
        if not conv.tenant:
            conv.tenant = owner or default_owner() or ""
    except Exception as e:
        log.error(f"[tenant] assign {user_id} lỗi: {e}")


def visible(row_tenant: str, workspace: str | None) -> bool:
    """Dòng dữ liệu này có được hiển thị cho workspace đang đăng nhập không.
    - workspace None (test/guard tắt) → thấy hết (giữ tương thích test cũ).
    - tenant rỗng (dữ liệu mồ côi hiếm) → chỉ CHỦ NỀN TẢNG thấy.
    """
    if not workspace:
        return True
    if not row_tenant:
        return workspace == default_owner()
    return row_tenant == workspace


def shop_key(workspace: str | None) -> str:
    """Khoá 'shop' cho NÃO BOT (knowledge_chunks.shop, file persona, photo...).
    Chủ nền tảng (hoặc không xác định) → 'default' (giữ nguyên não/tri thức cũ
    tạo trước multi-tenant); shop khác → chính username của shop đó."""
    if not workspace or workspace == default_owner():
        return "default"
    return workspace


def tenant_of_conv(account: str, user_id: str) -> str:
    """Tra tenant của 1 hội thoại từ DB (cho tiến trình không giữ conv object)."""
    try:
        rows = get_db().query(
            "SELECT tenant FROM sessions WHERE account=? AND user_id=?",
            (str(account), str(user_id)))
        return (rows[0]["tenant"] if rows else "") or ""
    except Exception:
        return ""


def current_workspace_or_none():
    """Workspace của request hiện tại (None khi không có token — vd test)."""
    try:
        from app.web_api.auth_api import current_workspace
        return current_workspace()
    except Exception:
        return None
