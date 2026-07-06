"""
Billing — HẠNG gói (tier), thời hạn, dùng thử, ví tiền, nạp tiền và QUOTA lượt AI.

Hai chiều giá:
  - TIER (hạng): starter | pro | business — quyết định quota AI/tháng + tính năng.
  - DURATION (thời hạn): month | quarter | year | lifetime — giá = PRICES[tier][duration].

Luật:
  - Tài khoản mới: dùng thử 3 NGÀY (tier "trial" = tính năng như Pro, quota nhỏ).
    Có mã giới thiệu (BILLING_PROMO_CODE) → 7 NGÀY. Mỗi acc dùng mã 1 lần.
  - Quota lượt AI reset theo THÁNG (ai_period='YYYY-MM'). Vượt quota → bot ngừng
    trả lời tới đầu tháng sau hoặc tới khi nâng hạng.
  - Nạp ví: tạo lệnh → CK đúng nội dung NAPxxxxxx → admin xác nhận → cộng ví.
  - Bot NGỪNG trả lời khi: gói hết hạn HOẶC hết quota tháng. Kênh không gắn chủ
    (kết nối cũ, của chính operator) → dùng gate toàn cục has_active_subscription().
"""

import secrets
import time
import logging
from datetime import datetime, timedelta

from app.core.config import Config
from app.core.db import get_db

log = logging.getLogger(__name__)

TRIAL_DAYS = 3
PROMO_TRIAL_DAYS = 7
TRIAL_DAILY_QUOTA = 500      # bản dùng thử: 500 lượt AI MỖI NGÀY (reset hằng ngày)
MIN_DEPOSIT = 10_000
MAX_DEPOSIT = 100_000_000

# HẠNG gói — quota AI/tháng (ladder ×5), giới hạn kênh, tính năng.
TIERS = {
    "starter":  {"label": "Khởi đầu", "quota": 6_000,   "channels": 1,    "call_owner": False, "adv_stats": False},
    "pro":      {"label": "Pro",      "quota": 30_000,  "channels": None, "call_owner": True,  "adv_stats": True},
    "business": {"label": "Chuỗi",    "quota": 150_000, "channels": None, "call_owner": True,  "adv_stats": True},
}
# THỜI HẠN
DURATIONS = {
    "month":    {"label": "tháng",     "days": 30},
    "quarter":  {"label": "quý",       "days": 90},
    "year":     {"label": "năm",       "days": 365},
    "lifetime": {"label": "vĩnh viễn", "days": None},
}
# GIÁ [tier][duration] (VND) — chỉnh ở đây là xong.
# Hạng Khởi đầu KHÔNG có gói vĩnh viễn (muốn vĩnh viễn → lên Pro).
PRICES = {
    "starter":  {"month": 250_000,   "quarter": 675_000,   "year": 2_500_000},
    "pro":      {"month": 500_000,   "quarter": 1_350_000, "year": 5_000_000,  "lifetime": 10_000_000},
    "business": {"month": 1_300_000, "quarter": 3_500_000, "year": 13_000_000, "lifetime": 26_000_000},
}


def _now():
    return datetime.now()


def _period(tier: str = None):
    """Kỳ tính quota: trial reset THEO NGÀY (YYYY-MM-DD), gói trả tiền theo THÁNG (YYYY-MM)."""
    if tier == "trial":
        return _now().strftime("%Y-%m-%d")
    return _now().strftime("%Y-%m")


def _promo_ok(code: str) -> bool:
    want = (Config.BILLING_PROMO_CODE or "").strip().lower()
    return bool(want) and (code or "").strip().lower() == want


def _tx(db, username, tx_type, amount, note):
    db.conn.execute(
        "INSERT INTO transactions(username, type, amount, note, created_at) VALUES (?,?,?,?,?)",
        (username, tx_type, amount, note, _now().isoformat()))


def _tier_of(row) -> str:
    t = row["tier"] if "tier" in row.keys() else "trial"
    return t or "trial"


def _quota_of(row) -> int:
    tier = _tier_of(row)
    if tier == "trial":
        return TRIAL_DAILY_QUOTA
    return TIERS.get(tier, TIERS["pro"])["quota"]


def _features_of(row) -> dict:
    tier = _tier_of(row)
    if tier == "trial":
        base = TIERS["pro"]     # trial được trải nghiệm như Pro
    else:
        base = TIERS.get(tier, TIERS["pro"])
    return {"channels": base["channels"], "call_owner": base["call_owner"], "adv_stats": base["adv_stats"]}


# ── Khởi tạo / trạng thái ───────────────────────────────────────────

def ensure_billing(username: str, promo: str = None):
    """Tạo dòng billing (trial) cho user nếu chưa có."""
    db = get_db()
    if db.query("SELECT 1 FROM billing WHERE username=?", (username,)):
        return
    use_promo = _promo_ok(promo)
    days = PROMO_TRIAL_DAYS if use_promo else TRIAL_DAYS
    now = _now()
    with db.lock:
        db.conn.execute(
            "INSERT OR IGNORE INTO billing(username, balance, plan, tier, lifetime, expires_at, "
            "promo_used, ai_used, ai_period, created_at) VALUES (?,0,'trial','trial',0,?,?,0,?,?)",
            (username, (now + timedelta(days=days)).isoformat(),
             1 if use_promo else 0, _period("trial"), now.isoformat()))
        if use_promo:
            _tx(db, username, "promo", 0, f"Mã giới thiệu → dùng thử {PROMO_TRIAL_DAYS} ngày")
        db.conn.commit()
    _invalidate_cache()
    log.info(f"[Billing] {username} bắt đầu dùng thử {days} ngày")


def _row(username):
    db = get_db()
    ensure_billing(username)
    return db, db.query("SELECT * FROM billing WHERE username=?", (username,))[0]


def status(username: str) -> dict:
    db, b = _row(username)
    now = _now()
    lifetime = bool(b["lifetime"])
    expires = datetime.fromisoformat(b["expires_at"]) if b["expires_at"] else None
    time_ok = lifetime or (expires is not None and expires > now)
    tier = _tier_of(b)
    quota = _quota_of(b)
    used = b["ai_used"] if b["ai_period"] == _period(tier) else 0
    days_left = None
    if not lifetime and expires:
        secs = (expires - now).total_seconds()
        days_left = max(0, int(secs // 86400) + (1 if secs % 86400 > 0 else 0))
    feats = _features_of(b)
    return {
        "balance": b["balance"],
        "plan": b["plan"],
        "tier": tier,
        "tier_label": "Dùng thử" if tier == "trial" else TIERS.get(tier, {}).get("label", tier),
        "plan_label": ("Vĩnh viễn" if lifetime else DURATIONS.get(b["plan"], {}).get("label", "Dùng thử")),
        "lifetime": lifetime,
        "expires_at": b["expires_at"],
        "active": time_ok,
        "days_left": days_left,
        "on_trial": tier == "trial",
        "promo_used": bool(b["promo_used"]),
        # Quota lượt AI (trial: theo NGÀY; gói trả tiền: theo THÁNG)
        "ai_quota": quota,
        "ai_used": used,
        "ai_left": max(0, quota - used),
        "ai_period": _period(tier),
        "ai_period_label": "hôm nay" if tier == "trial" else "tháng này",
        # Tính năng theo hạng
        "channels_limit": feats["channels"],   # None = không giới hạn
        "feature_call_owner": feats["call_owner"],
        "feature_adv_stats": feats["adv_stats"],
        # Multi-model + tính theo usage khi vượt quota
        "ai_model": (b["ai_model"] if "ai_model" in b.keys() else "") or "",
        "usage_enabled": bool(b["usage_enabled"]) if "usage_enabled" in b.keys() else False,
        "usage_limit": (b["usage_limit"] if "usage_limit" in b.keys() else 0) or 0,
        "usage_spent": ((b["usage_spent"] or 0)
                        if ("usage_spent" in b.keys()
                            and b["usage_period"] == now.strftime("%Y-%m")) else 0),
    }


def redeem_promo(username: str, code: str):
    if not _promo_ok(code):
        raise ValueError("Mã giới thiệu không đúng")
    db, b = _row(username)
    if b["promo_used"]:
        raise ValueError("Tài khoản đã dùng mã giới thiệu rồi")
    if _tier_of(b) != "trial":
        raise ValueError("Mã giới thiệu chỉ dùng được khi đang dùng thử")
    created = datetime.fromisoformat(b["created_at"])
    new_exp = created + timedelta(days=PROMO_TRIAL_DAYS)
    cur_exp = datetime.fromisoformat(b["expires_at"]) if b["expires_at"] else created
    if new_exp < cur_exp:
        new_exp = cur_exp
    with db.lock:
        db.conn.execute("UPDATE billing SET expires_at=?, promo_used=1 WHERE username=?",
                        (new_exp.isoformat(), username))
        _tx(db, username, "promo", 0, f"Mã giới thiệu → dùng thử {PROMO_TRIAL_DAYS} ngày")
        db.conn.commit()
    _invalidate_cache()


# ── Nạp tiền ────────────────────────────────────────────────────────

def create_deposit(username: str, amount: int) -> dict:
    amount = int(amount)
    if amount < MIN_DEPOSIT or amount > MAX_DEPOSIT:
        raise ValueError(f"Số tiền nạp từ {MIN_DEPOSIT:,} đến {MAX_DEPOSIT:,}₫")
    db = get_db()
    ensure_billing(username)
    for _ in range(10):
        code = f"NAP{secrets.randbelow(1_000_000):06d}"
        if not db.query("SELECT 1 FROM deposits WHERE code=?", (code,)):
            break
    db.execute(
        "INSERT INTO deposits(username, amount, code, status, created_at) VALUES (?,?,?, 'pending', ?)",
        (username, amount, code, _now().isoformat()))
    log.info(f"[Billing] {username} tạo lệnh nạp {amount:,}₫ mã {code}")
    return {"code": code, "amount": amount}


def list_deposits(username: str, limit: int = 20) -> list:
    db = get_db()
    return [dict(r) for r in db.query(
        "SELECT id, amount, code, status, created_at, confirmed_at FROM deposits "
        "WHERE username=? ORDER BY id DESC LIMIT ?", (username, limit))]


def pending_deposits() -> list:
    db = get_db()
    return [dict(r) for r in db.query(
        "SELECT id, username, amount, code, created_at FROM deposits "
        "WHERE status='pending' ORDER BY id")]


def confirm_deposit(code: str) -> dict:
    db = get_db()
    rows = db.query("SELECT * FROM deposits WHERE code=?", ((code or "").strip().upper(),))
    if not rows:
        raise ValueError(f"Không tìm thấy lệnh nạp mã {code}")
    d = rows[0]
    if d["status"] != "pending":
        raise ValueError(f"Lệnh nạp {code} đã ở trạng thái {d['status']}")
    with db.lock:
        db.conn.execute("UPDATE deposits SET status='confirmed', confirmed_at=? WHERE id=?",
                        (_now().isoformat(), d["id"]))
        db.conn.execute("UPDATE billing SET balance = balance + ? WHERE username=?",
                        (d["amount"], d["username"]))
        _tx(db, d["username"], "deposit", d["amount"], f"Nạp tiền (mã {d['code']})")
        db.conn.commit()
    log.info(f"[Billing] XÁC NHẬN nạp {d['amount']:,}₫ cho {d['username']} (mã {d['code']})")
    return {"username": d["username"], "amount": d["amount"]}


def cancel_deposit(username: str, code: str):
    db = get_db()
    db.execute("UPDATE deposits SET status='canceled' WHERE username=? AND code=? AND status='pending'",
               (username, (code or "").strip().upper()))


# ── Mua gói (tier × duration) ───────────────────────────────────────

def buy_plan(username: str, tier: str, duration: str) -> dict:
    if tier not in TIERS:
        raise ValueError("Hạng gói không hợp lệ")
    if duration not in DURATIONS:
        raise ValueError("Thời hạn không hợp lệ")
    if duration not in PRICES[tier]:
        raise ValueError(f"Hạng {TIERS[tier]['label']} không có gói {DURATIONS[duration]['label']}")
    price = PRICES[tier][duration]
    db = get_db()
    ensure_billing(username)
    with db.lock:
        b = db.conn.execute("SELECT * FROM billing WHERE username=?", (username,)).fetchone()
        if b["lifetime"] and _tier_of(b) == tier:
            raise ValueError("Bạn đang dùng gói VĨNH VIỄN hạng này rồi")
        if b["balance"] < price:
            raise ValueError(f"Ví không đủ ({b['balance']:,}₫) — cần {price:,}₫, hãy nạp thêm")
        now = _now()
        label = f"{TIERS[tier]['label']} · {DURATIONS[duration]['label']}"
        if duration == "lifetime":
            db.conn.execute(
                "UPDATE billing SET balance=balance-?, plan='lifetime', tier=?, lifetime=1, "
                "expires_at=NULL WHERE username=?", (price, tier, username))
        else:
            days = DURATIONS[duration]["days"]
            cur = datetime.fromisoformat(b["expires_at"]) if b["expires_at"] else now
            # Gia hạn nối tiếp CHỈ khi cùng hạng & còn hạn & không phải trial;
            # nâng/hạ hạng → tính lại từ hôm nay.
            same = (_tier_of(b) == tier and b["tier"] != "trial")
            base = cur if (cur > now and same) else now
            new_exp = base + timedelta(days=days)
            db.conn.execute(
                "UPDATE billing SET balance=balance-?, plan=?, tier=?, lifetime=0, expires_at=? WHERE username=?",
                (price, duration, tier, new_exp.isoformat(), username))
        _tx(db, username, "purchase", -price, f"Mua {label}")
        db.conn.commit()
    _invalidate_cache()
    log.info(f"[Billing] {username} mua {label} ({price:,}₫)")
    return status(username)


def transactions(username: str, limit: int = 30) -> list:
    db = get_db()
    return [dict(r) for r in db.query(
        "SELECT type, amount, note, created_at FROM transactions "
        "WHERE username=? ORDER BY id DESC LIMIT ?", (username, limit))]


def plans_catalog() -> list:
    """Bảng giá đầy đủ cho UI: mỗi hạng kèm giá 4 thời hạn + quota + tính năng."""
    out = []
    for tk, t in TIERS.items():
        out.append({
            "tier": tk, "label": t["label"], "quota": t["quota"],
            "channels": t["channels"], "call_owner": t["call_owner"], "adv_stats": t["adv_stats"],
            # Chỉ liệt kê thời hạn hạng này CÓ bán (starter không có lifetime)
            "prices": {dk: PRICES[tk][dk] for dk in DURATIONS if dk in PRICES[tk]},
        })
    return out


def durations_catalog() -> list:
    return [{"key": k, "label": v["label"], "days": v["days"]} for k, v in DURATIONS.items()]


# ── Quota lượt AI ───────────────────────────────────────────────────

def record_token_usage(username: str, model_key: str,
                       tokens_in: int, tokens_out: int) -> None:
    """Ghi chi phí token của 1 lượt gọi AI (gọi từ ai_models.chat).
    Đang trong quota → chi phí thuộc gói, không trừ ví. ĐÃ HẾT quota (hoặc
    kỳ khác) + shop bật 'tính theo usage' → TRỪ VÍ + cộng usage_spent
    (reset theo tháng usage_period) — giống extra usage của Claude."""
    from app.core import ai_models
    cost = ai_models.cost_vnd(model_key, tokens_in, tokens_out)
    cost_i = max(1, round(cost)) if (tokens_in or tokens_out) else 0
    if not cost_i:
        return
    db = get_db()
    ensure_billing(username)
    period = _now().strftime("%Y-%m")
    with db.lock:
        b = db.conn.execute("SELECT * FROM billing WHERE username=?", (username,)).fetchone()
        spent = (b["usage_spent"] or 0) if b["usage_period"] == period else 0
        used = b["ai_used"] if b["ai_period"] == _period(_tier_of(b)) else 0
        over_quota = used >= _quota_of(b)
        if over_quota and b["usage_enabled"]:
            db.conn.execute(
                "UPDATE billing SET balance=balance-?, usage_spent=?, usage_period=? "
                "WHERE username=?", (cost_i, spent + cost_i, period, username))
        else:
            db.conn.execute(
                "UPDATE billing SET usage_spent=?, usage_period=? WHERE username=?",
                (spent, period, username))
        db.conn.commit()


def is_blocked(username: str) -> bool:
    """Shop bị QUẢN TRỊ NỀN TẢNG chặn? (users.blocked — khoá đăng nhập + tắt bot)."""
    try:
        r = get_db().query("SELECT blocked FROM users WHERE username=?", (username,))
        return bool(r) and bool(r[0]["blocked"])
    except Exception:
        return False


def can_reply(username: str) -> bool:
    """User này còn quyền cho bot trả lời? Không bị chặn + gói còn hạn + (còn quota
    HOẶC đã bật 'tính theo usage' còn hạn mức tháng và ví còn tiền)."""
    if is_blocked(username):
        return False
    st = status(username)
    if not st["active"]:
        return False
    if st["ai_left"] > 0:
        return True
    return (st["usage_enabled"] and st["usage_spent"] < st["usage_limit"]
            and st["balance"] > 0)


def record_ai_usage(username: str, n: int = 1) -> None:
    """Tăng bộ đếm lượt AI của user (trial reset theo NGÀY, gói trả tiền theo THÁNG)."""
    db = get_db()
    ensure_billing(username)
    with db.lock:
        b = db.conn.execute("SELECT tier, ai_period FROM billing WHERE username=?", (username,)).fetchone()
        period = _period(b["tier"] or "trial")
        if b["ai_period"] != period:
            db.conn.execute("UPDATE billing SET ai_used=?, ai_period=? WHERE username=?",
                            (n, period, username))
        else:
            db.conn.execute("UPDATE billing SET ai_used=ai_used+? WHERE username=?", (n, username))
        db.conn.commit()


# ── Gate toàn cục (kênh chưa gắn chủ / tương thích cũ) ──────────────

_active_cache = {"t": 0.0, "v": True}
_CACHE_TTL = 30

def _invalidate_cache():
    _active_cache["t"] = 0.0

def has_active_subscription() -> bool:
    """True nếu cài đặt còn quyền chạy bot ở mức TOÀN CỤC:
       - CHƯA có tài khoản nào → True (chưa áp billing)
       - Có ≥1 user còn hạn (lifetime/expires) → True; hết hạn hết → False.
       Dùng cho kênh chưa gắn chủ. Kênh đã gắn chủ dùng can_reply(owner)."""
    now = time.time()
    if now - _active_cache["t"] < _CACHE_TTL:
        return _active_cache["v"]
    try:
        db = get_db()
        n_users = db.query("SELECT count(*) c FROM users")[0]["c"]
        if n_users == 0:
            v = True
        else:
            if db.query("SELECT count(*) c FROM billing")[0]["c"] == 0:
                for u in db.query("SELECT username FROM users"):
                    ensure_billing(u["username"])
            v = bool(db.query(
                "SELECT 1 FROM billing WHERE lifetime=1 OR expires_at > ? LIMIT 1",
                (_now().isoformat(),)))
    except Exception as e:
        log.error(f"[Billing] lỗi kiểm tra gói: {e}")
        v = True
    _active_cache.update(t=now, v=v)
    return v


# ── Quản trị nền tảng: cấp / thu hồi gói (không trừ ví) ─────────────

def admin_grant(username: str, tier: str, duration: str) -> dict:
    """CẤP gói cho shop (quản trị nền tảng tặng/kích hoạt tay — KHÔNG trừ ví).
    Cùng hạng & còn hạn → gia hạn nối tiếp; khác hạng → tính từ hôm nay."""
    if tier not in TIERS:
        raise ValueError("Hạng gói không hợp lệ")
    if duration not in DURATIONS:
        raise ValueError("Thời hạn không hợp lệ")
    db = get_db()
    ensure_billing(username)
    with db.lock:
        b = db.conn.execute("SELECT * FROM billing WHERE username=?", (username,)).fetchone()
        now = _now()
        label = f"{TIERS[tier]['label']} · {DURATIONS[duration]['label']}"
        if duration == "lifetime":
            db.conn.execute(
                "UPDATE billing SET plan='lifetime', tier=?, lifetime=1, expires_at=NULL "
                "WHERE username=?", (tier, username))
        else:
            days = DURATIONS[duration]["days"]
            cur = datetime.fromisoformat(b["expires_at"]) if b["expires_at"] else now
            same = (_tier_of(b) == tier and b["tier"] != "trial")
            base = cur if (cur > now and same) else now
            db.conn.execute(
                "UPDATE billing SET plan=?, tier=?, lifetime=0, expires_at=? WHERE username=?",
                (duration, tier, (base + timedelta(days=days)).isoformat(), username))
        _tx(db, username, "promo", 0, f"Quản trị cấp gói {label}")
        db.conn.commit()
    _invalidate_cache()
    log.info(f"[Billing] ADMIN cấp {label} cho {username}")
    return status(username)


def admin_revoke(username: str) -> dict:
    """THU HỒI gói của shop: hết hạn ngay lập tức (bot ngừng, dữ liệu giữ nguyên)."""
    db = get_db()
    ensure_billing(username)
    with db.lock:
        db.conn.execute(
            "UPDATE billing SET lifetime=0, expires_at=? WHERE username=?",
            (_now().isoformat(), username))
        _tx(db, username, "promo", 0, "Quản trị thu hồi gói (hết hạn ngay)")
        db.conn.commit()
    _invalidate_cache()
    log.info(f"[Billing] ADMIN thu hồi gói của {username}")
    return status(username)


def channel_gate(owner_username: str) -> bool:
    """Cổng cho 1 tin đến kênh: nếu biết chủ (owner_username) → theo gói+quota của
    chủ, đồng thời GHI 1 lượt AI khi cho qua. Không biết chủ → gate toàn cục."""
    if owner_username:
        if not can_reply(owner_username):
            return False
        record_ai_usage(owner_username, 1)
        return True
    return has_active_subscription()
