"""
TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — chủ soạn 1 tin gửi cho NHÓM khách
cũ: chăm sóc lại, báo khuyến mãi, nhắc lịch. Chạy ở bridge (5005).

Cách gửi: worker KHÔNG gọi thẳng Channel trong tiến trình bridge — mỗi kênh có
tiến trình riêng giữ token cache/outbox RAM (gọi chéo sẽ làm hỏng refresh token
Shopee/OA, webchat outbox không tới widget). Thay vào đó worker POST HTTP nội bộ
tới endpoint {prefix}/conversations/<uid>/broadcast-send của TỪNG server kênh
(chat_tools) — tiến trình kênh tự gửi bằng channel + store của chính nó và lưu
tin vào lịch sử hội thoại. Kênh nào chưa chạy server → khách kênh đó fail với
lỗi rõ ràng, không chặn kênh khác.

Ràng buộc nền tảng (UI đã cảnh báo, gửi fail sẽ ghi log từng khách):
  - Meta: chỉ nhắn được khách tương tác trong 24h (ngoài cửa sổ → Graph từ chối).
  - Zalo OA: cửa sổ 48h (ngoài → cần ZNS, chưa hỗ trợ).
  - Zalo cá nhân: gửi hàng loạt dễ bị gắn cờ spam → throttle chậm (BROADCAST_THROTTLE).
"""

import json
import logging
import threading
import time
from datetime import datetime, timedelta

import requests

from app.core.config import Config
from app.core.db import get_db

log = logging.getLogger("broadcast")

# key kênh (UI) → (cổng server, prefix API). Zalo cá nhân = chính bridge.
def _servers():
    return {
        "zalo":     (Config.BRIDGE_PORT,      ""),
        "meta":     (Config.META_WEBHOOK_PORT, "/meta"),
        "telegram": (Config.TELEGRAM_API_PORT, "/tg"),
        "tiktok":   (Config.TIKTOK_API_PORT,   "/tiktok"),
        "shopee":   (Config.SHOPEE_API_PORT,   "/shopee"),
        "zalooa":   (Config.ZALO_OA_API_PORT,  "/zalooa"),
        "webchat":  (Config.WEBCHAT_API_PORT,  "/webchat"),
    }

CHANNELS = tuple(_servers().keys())

# account trong bảng sessions → key kênh (account số = Zalo cá nhân)
_ACCOUNT_CHANNEL = {
    "meta": "meta", "telegram": "telegram", "tiktok": "tiktok",
    "shopee": "shopee", "zalooa": "zalooa", "webchat": "webchat",
}


def _channel_of_account(account: str) -> str:
    return _ACCOUNT_CHANNEL.get(str(account), "zalo")


# ── Tập khách (audience) ─────────────────────────────────────────────

def audience(channels: list, segment: dict) -> list[dict]:
    """Danh sách khách sẽ nhận tin: lọc theo kênh + mức hoạt động.
    segment: {type: "all" | "active" | "inactive", days: N}
      - active   : có nhắn trong N ngày gần đây (khách còn ấm)
      - inactive : IM LẶNG hơn N ngày (khách cũ cần đánh thức)
    """
    channels = [c for c in (channels or []) if c in CHANNELS]
    if not channels:          # không có kênh hợp lệ nào → không gửi ai cả
        return []             # (đừng hiểu nhầm "rỗng = tất cả" — nguy hiểm)
    seg_type = (segment or {}).get("type", "all")
    try:
        days = max(int((segment or {}).get("days", 30)), 1)
    except (TypeError, ValueError):
        days = 30
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()

    out = []
    for r in get_db().query(
            "SELECT account, user_id, name, last_updated FROM sessions "
            "ORDER BY last_updated DESC"):
        if not r["user_id"]:
            continue
        ch = _channel_of_account(r["account"])
        if ch not in channels:
            continue
        lu = r["last_updated"] or ""
        if seg_type == "active" and lu < cutoff:
            continue
        if seg_type == "inactive" and lu >= cutoff:
            continue
        out.append({"account": r["account"], "user_id": r["user_id"],
                    "name": r["name"] or "", "channel": ch})
    return out


# ── CRUD chiến dịch ──────────────────────────────────────────────────

def _row_dict(r) -> dict:
    d = dict(r)
    for k in ("channels", "segment"):
        try:
            d[k] = json.loads(d.get(k) or ("{}" if k == "segment" else "[]"))
        except Exception:
            d[k] = {} if k == "segment" else []
    return d


def create(name: str, message: str, channels: list, segment: dict,
           created_by: str = "") -> dict:
    db = get_db()
    cur = db.execute(
        "INSERT INTO broadcasts (name, message, channels, segment, status,"
        " created_by, created_at) VALUES (?,?,?,?, 'draft', ?, ?)",
        ((name or "").strip()[:120] or "Chiến dịch chưa đặt tên",
         message, json.dumps(channels or [], ensure_ascii=False),
         json.dumps(segment or {}, ensure_ascii=False),
         created_by or "", datetime.now().isoformat()))
    return get(cur.lastrowid)


def get(bid: int) -> dict | None:
    rows = get_db().query("SELECT * FROM broadcasts WHERE id=?", (bid,))
    return _row_dict(rows[0]) if rows else None


def list_all(limit: int = 50) -> list[dict]:
    return [_row_dict(r) for r in get_db().query(
        "SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (limit,))]


def logs(bid: int, limit: int = 200, only_failed: bool = False) -> list[dict]:
    sql = "SELECT * FROM broadcast_log WHERE broadcast_id=?"
    if only_failed:
        sql += " AND status='failed'"
    sql += " ORDER BY id DESC LIMIT ?"
    return [dict(r) for r in get_db().query(sql, (bid, limit))]


def cancel(bid: int) -> bool:
    """Dừng chiến dịch — worker kiểm status trước mỗi tin nên dừng gần như ngay."""
    db = get_db()
    r = get(bid)
    if not r or r["status"] not in ("draft", "sending"):
        return False
    db.execute("UPDATE broadcasts SET status='cancelled', finished_at=? WHERE id=?",
               (datetime.now().isoformat(), bid))
    return True


# ── Worker gửi ───────────────────────────────────────────────────────

def start(bid: int, auth_token: str = "") -> bool:
    """Bắt đầu gửi (thread nền). auth_token = Bearer của người bấm gửi — dùng để
    gọi HTTP nội bộ tới các server kênh (chúng cũng đứng sau auth guard)."""
    db = get_db()
    r = get(bid)
    if not r or r["status"] != "draft":
        return False
    db.execute("UPDATE broadcasts SET status='sending', started_at=? WHERE id=?",
               (datetime.now().isoformat(), bid))
    t = threading.Thread(target=_run, args=(bid, auth_token),
                         daemon=True, name=f"broadcast-{bid}")
    t.start()
    return True


def _send_one(item: dict, message: str, auth_token: str) -> tuple[bool, str]:
    port, prefix = _servers()[item["channel"]]
    url = f"http://127.0.0.1:{port}{prefix}/conversations/{item['user_id']}/broadcast-send"
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else {}
    try:
        resp = requests.post(url, json={"text": message}, headers=headers, timeout=30)
    except Exception as e:
        return False, f"Server kênh {item['channel']} không chạy ({e.__class__.__name__})"
    if resp.status_code == 200:
        return True, ""
    try:
        err = (resp.json() or {}).get("error") or f"HTTP {resp.status_code}"
    except Exception:
        err = f"HTTP {resp.status_code}"
    return False, str(err)[:300]


def _run(bid: int, auth_token: str = ""):
    db = get_db()
    r = get(bid)
    if not r:
        return
    targets = audience(r["channels"], r["segment"])
    db.execute("UPDATE broadcasts SET total=? WHERE id=?", (len(targets), bid))
    log.info(f"[broadcast] #{bid} '{r['name']}' bắt đầu — {len(targets)} khách")

    sent = failed = 0
    for item in targets:
        # Chủ bấm Dừng → status đổi ở DB → thoát vòng
        cur = get(bid)
        if not cur or cur["status"] != "sending":
            log.info(f"[broadcast] #{bid} bị dừng ({sent} đã gửi)")
            return
        ok, err = _send_one(item, r["message"], auth_token)
        if ok:
            sent += 1
        else:
            failed += 1
        db.execute(
            "INSERT INTO broadcast_log (broadcast_id, account, user_id, status,"
            " error, created_at) VALUES (?,?,?,?,?,?)",
            (bid, item["account"], item["user_id"],
             "sent" if ok else "failed", err, datetime.now().isoformat()))
        db.execute("UPDATE broadcasts SET sent=?, failed=? WHERE id=?",
                   (sent, failed, bid))
        time.sleep(max(Config.BROADCAST_THROTTLE, 0.1))

    db.execute("UPDATE broadcasts SET status='done', finished_at=? WHERE id=?",
               (datetime.now().isoformat(), bid))
    log.info(f"[broadcast] #{bid} xong — gửi {sent}, lỗi {failed}")
