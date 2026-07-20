"""
Thanh toán — Phase 2+3 module đơn hàng.

Phase 2 (QR động): shop khai tài khoản nhận tiền (Cài đặt) → khách chốt đơn là
bot gửi ảnh QR VietQR (img.vietqr.io — miễn phí, không cần đăng ký) nhúng sẵn
SỐ TIỀN + NỘI DUNG = MÃ ĐƠN (DHxxxx) → đơn chuyển "chờ thanh toán".

Phase 3 (đối soát tự động): SePay/Casso đọc biến động số dư ngân hàng → POST
webhook /payhook → khớp nội dung chuyển khoản:
  - "DHxxxx" → đơn hàng chuyển "đã thanh toán" + báo chủ
  - "NAPxxxxxx" → xác nhận nạp ví (billing.confirm_deposit — hết cần admin gõ tay)
Không khớp gì → bỏ qua (trả ok để SePay không retry).

Bảo mật webhook: đặt SEPAY_API_KEY trong .env → chỉ nhận request có header
Authorization chứa key đó; để trống = nhận tất (dev/test).
"""

import logging
import re
from urllib.parse import quote

from app.core.db import get_db

log = logging.getLogger(__name__)

VIETQR_BASE = "https://img.vietqr.io/image"

ORDER_CODE_RE = re.compile(r"\bDH\d{3,}\b", re.IGNORECASE)
DEPOSIT_CODE_RE = re.compile(r"\bNAP[A-Z0-9]{4,}\b", re.IGNORECASE)


# ── Tài khoản nhận tiền của shop ─────────────────────────────────────

def get_bank(username: str = None) -> dict | None:
    """Bank info (tài khoản NHẬN TIỀN) của shop sở hữu hội thoại/đơn.

    MULTI-TENANT: LUÔN truyền username = chủ shop. Không truyền → dùng CHỦ NỀN
    TẢNG (shop gốc). TUYỆT ĐỐI KHÔNG còn fallback "user đầu tiên có bank" như bản
    cũ — đó là lỗ hổng khiến tiền khách shop B chảy vào tài khoản shop A. Shop chưa
    khai bank → None (không gửi QR, đơn dừng ở nháp)."""
    if not username:
        from app.core import tenant as _tenant
        username = _tenant.default_owner()
    if not username:
        return None
    rows = get_db().query(
        "SELECT bank_code, bank_account, bank_holder FROM users WHERE username=?",
        (username,))
    if not rows:
        return None
    b = dict(rows[0])
    if not (b.get("bank_code") and b.get("bank_account")):
        return None
    return b


def set_bank(username: str, bank_code: str, bank_account: str, bank_holder: str):
    """Lưu bank info (bank_code = mã VietQR: MB, VCB, TCB, ACB, VBA…)."""
    code = re.sub(r"[^A-Za-z0-9]", "", bank_code or "").upper()
    account = re.sub(r"[^A-Za-z0-9]", "", bank_account or "")
    get_db().execute(
        "UPDATE users SET bank_code=?, bank_account=?, bank_holder=? WHERE username=?",
        (code, account, (bank_holder or "").strip().upper(), username))


def build_vietqr_url(bank: dict, amount: int = 0, memo: str = "") -> str:
    """URL ảnh QR VietQR — mở là ra ảnh PNG, nhúng sẵn tiền + nội dung CK."""
    url = f"{VIETQR_BASE}/{quote(bank['bank_code'])}-{quote(bank['bank_account'])}-compact2.png"
    params = []
    if amount and int(amount) > 0:
        params.append(f"amount={int(amount)}")
    if memo:
        params.append(f"addInfo={quote(str(memo))}")
    if bank.get("bank_holder"):
        params.append(f"accountName={quote(bank['bank_holder'])}")
    return url + ("?" + "&".join(params) if params else "")


# ── Webhook biến động số dư (SePay / Casso) ──────────────────────────

def parse_webhook(payload: dict) -> list:
    """Payload webhook → list[(content, amount)] các giao dịch TIỀN VÀO.
    Nhận cả 2 format phổ biến (mapping gói ở đây — đổi nhà cung cấp chỉ sửa hàm này):
      SePay: {"content", "transferAmount", "transferType": "in", ...}
      Casso: {"data": [{"description", "amount", ...}, ...]}
    """
    txs = []
    if isinstance(payload.get("data"), list):          # Casso
        for t in payload["data"]:
            if not isinstance(t, dict):
                continue
            amount = int(t.get("amount") or 0)
            content = str(t.get("description") or t.get("content") or "")
            if amount > 0 and content:
                txs.append((content, amount))
    elif payload.get("content") or payload.get("transferAmount"):   # SePay
        if str(payload.get("transferType") or "in").lower() == "in":
            amount = int(payload.get("transferAmount") or payload.get("amount") or 0)
            content = str(payload.get("content") or "")
            if amount > 0 and content:
                txs.append((content, amount))
    return txs


def process_transfer(content: str, amount: int, notify_fn=None) -> dict:
    """Xử lý 1 giao dịch tiền vào: khớp MÃ ĐƠN trước, rồi MÃ NẠP VÍ.
    Trả {"matched": "order"|"deposit"|None, ...}."""
    def _notify(text):
        if notify_fn:
            try:
                notify_fn(text)
            except Exception as e:
                log.error(f"[Pay] notify lỗi: {e}")

    # 1. Mã đơn hàng DHxxxx
    m = ORDER_CODE_RE.search(content or "")
    if m:
        from app.core import orders
        code = m.group(0).upper()
        o = orders.get_by_code(code)
        if o and o["status"] in ("draft", "awaiting_payment"):
            orders.update(o["id"], status="paid")
            # ghi số tiền thật nhận (cọc 50% hay full — chủ nhìn timeline tự soi)
            orders.add_event(o["id"], f"Nhận CK {amount:,}đ (tự động)")
            short = "đủ" if amount >= (o["total"] or 0) else f"{amount:,}đ/{o['total']:,}đ"
            _notify(f"💰 ĐƠN {code} ĐÃ NHẬN TIỀN ({short})!\n"
                    f"👤 {o['customer_name'] or o['user_id']}"
                    + (f" · 📞 {o['phone']}" if o['phone'] else "")
                    + f"\nĐơn tự chuyển sang ✅ Đã thanh toán.")
            log.info(f"[Pay] {code} nhận {amount:,}đ → paid")
            return {"matched": "order", "code": code, "amount": amount}
        if o:
            log.info(f"[Pay] {code} nhận thêm {amount:,}đ (đơn đã {o['status']}) → chỉ báo")
            _notify(f"💰 Nhận thêm {amount:,}đ cho đơn {code} (đang {o['status']}).")
            return {"matched": "order", "code": code, "amount": amount, "already": o["status"]}

    # 2. Mã nạp ví NAPxxxxxx
    m = DEPOSIT_CODE_RE.search(content or "")
    if m:
        from app.core import billing
        code = m.group(0).upper()
        try:
            # ĐỐI SOÁT TỰ ĐỘNG: ghi có ĐÚNG số tiền THẬT nhận (amount), không tin
            # số ở lệnh nạp → chống chuyển 10k mà ví +100tr.
            r = billing.confirm_deposit(code, paid_amount=amount)
            _notify(f"💳 Tự xác nhận NẠP VÍ {r['amount']:,}đ cho {r['username']} (mã {code}).")
            log.info(f"[Pay] nạp ví {code} xác nhận tự động")
            return {"matched": "deposit", "code": code, **r}
        except ValueError as e:
            log.info(f"[Pay] mã nạp {code} không xử lý được: {e}")

    log.info(f"[Pay] giao dịch không khớp mã nào: '{(content or '')[:60]}' {amount:,}đ")
    return {"matched": None}
