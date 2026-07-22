"""
SHOP CON — 1 tài khoản chứa NHIỀU shop, mỗi shop là 1 workspace/tenant độc lập.

Cách hoạt động: tenant toàn hệ thống vốn là 1 CHUỖI workspace (username chủ).
Mỗi shop con = 1 chuỗi ws riêng → mọi máy móc multi-tenant sẵn có (kênh gắn
owner_username, sessions.tenant, orders/photo/canned tenant, não AI shop_key,
broadcast created_by, thống kê...) tự tách theo shop mà KHÔNG sửa từng module.

- Shop MẶC ĐỊNH: ws = chính username → toàn bộ dữ liệu cũ thuộc về nó (0 migrate).
- Shop thêm mới: ws = "<username>~s<hex6>" (dấu '~' không có trong username hợp lệ).
- Gói cước/ví DÙNG CHUNG tài khoản: billing.account_of() quy ws shop con → owner.
- Client chọn shop bằng header X-Shop; auth_api.current_workspace() validate
  shop thuộc đúng tài khoản rồi trả ws đó làm workspace của request.
"""

import logging
import secrets
from datetime import datetime

from app.core.db import get_db

log = logging.getLogger(__name__)


def ensure_default(owner: str):
    """Dòng shop mặc định (ws = username) — tạo nếu chưa có. Gọi mọi nơi list."""
    if not owner:
        return
    db = get_db()
    db.execute(
        "INSERT OR IGNORE INTO shops (ws, owner, name, created_at) VALUES (?,?,?,?)",
        (owner, owner, "", datetime.now().isoformat()))


def list_for(owner: str) -> list[dict]:
    """Các shop của 1 tài khoản (shop mặc định luôn đứng đầu)."""
    if not owner:
        return []
    ensure_default(owner)
    rows = get_db().query(
        "SELECT ws, name, created_at FROM shops WHERE owner=? ORDER BY created_at",
        (owner,))
    out = []
    for r in rows:
        out.append({"ws": r["ws"], "name": r["name"] or "",
                    "is_default": r["ws"] == owner})
    out.sort(key=lambda s: not s["is_default"])   # default lên đầu, còn lại giữ thứ tự
    return out


def create(owner: str, name: str) -> dict:
    ensure_default(owner)
    db = get_db()
    ws = f"{owner}~s{secrets.token_hex(3)}"
    while db.query("SELECT 1 FROM shops WHERE ws=?", (ws,)):
        ws = f"{owner}~s{secrets.token_hex(3)}"
    db.execute("INSERT INTO shops (ws, owner, name, created_at) VALUES (?,?,?,?)",
               (ws, owner, (name or "").strip()[:80], datetime.now().isoformat()))
    log.info(f"[shops] {owner} tạo shop '{name}' → {ws}")
    return {"ws": ws, "name": (name or "").strip()[:80], "is_default": False}


def rename(owner: str, ws: str, name: str) -> bool:
    cur = get_db().execute(
        "UPDATE shops SET name=? WHERE ws=? AND owner=?",
        ((name or "").strip()[:80], ws, owner))
    return cur.rowcount == 1


def remove(owner: str, ws: str) -> tuple[bool, str]:
    """Xoá shop con. Chặn: shop mặc định (dữ liệu gốc tài khoản) và shop còn app
    (bắt gỡ kênh trước — tránh mồ côi kết nối đang chạy). Hội thoại/đơn cũ của
    shop giữ nguyên trong DB (tenant=ws) để không mất lịch sử."""
    if ws == owner:
        return False, "Không xoá được shop mặc định"
    db = get_db()
    if not db.query("SELECT 1 FROM shops WHERE ws=? AND owner=?", (ws, owner)):
        return False, "Không tìm thấy shop"
    n_apps = db.query(
        "SELECT COUNT(*) AS n FROM user_apps WHERE username=? AND shop_ws=?",
        (owner, ws))[0]["n"]
    if n_apps:
        return False, f"Shop còn {n_apps} kênh — xoá các kênh trong shop trước"
    db.execute("DELETE FROM shops WHERE ws=? AND owner=?", (ws, owner))
    return True, ""


def account_of(ws: str) -> str:
    """Tài khoản chính của 1 workspace: shop con → owner; còn lại giữ nguyên.
    Dùng cho billing (gói dùng chung) — KHÔNG tra DB khi ws không có dạng shop
    con (dấu '~') để đường nóng channel_gate không tốn query vô ích."""
    if not ws or "~" not in str(ws):
        return ws
    try:
        rows = get_db().query("SELECT owner FROM shops WHERE ws=?", (str(ws),))
        return rows[0]["owner"] if rows else ws
    except Exception as e:
        log.warning(f"[shops] account_of {ws} lỗi: {e}")
        return ws


def is_shop_of(ws: str, owner: str) -> bool:
    """ws có phải shop (mặc định hoặc con) của tài khoản owner không —
    dùng validate header X-Shop (chống IDOR chọn shop tài khoản khác)."""
    if not ws or not owner:
        return False
    if ws == owner:
        return True
    try:
        return bool(get_db().query(
            "SELECT 1 FROM shops WHERE ws=? AND owner=?", (str(ws), str(owner))))
    except Exception:
        return False
