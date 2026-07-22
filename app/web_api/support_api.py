"""
Chat tư vấn DỊCH VỤ (bong bóng chat góc web — như Crisp) — gắn vào bridge 5005.

Bot này KHÔNG phải bot trả lời khách của shop — nó là bot BÁN HÀNG
của chính sản phẩm NovaChat: tư vấn tính năng, bảng giá, cách kết nối kênh,
dùng thử… cho khách đang cân nhắc mua. KHÔNG cần đăng nhập (khách lạ vào trang
chủ hỏi được ngay), có rate-limit theo IP để chống spam.

  POST /support/chat {messages: [{role, content}...]} → {reply}
"""

import time
import logging
import threading

from flask import request

from app.core import billing
from app.core.claude_ai import _call_ai

log = logging.getLogger("support_api")

MAX_TURNS = 12          # chỉ gửi 12 tin gần nhất cho AI
MAX_MSG_CHARS = 1000
RATE_WINDOW = 600       # 10 phút
RATE_MAX = 40           # tối đa 40 tin / IP / 10 phút

_hits: dict = {}        # ip -> [timestamps]
_hlock = threading.Lock()


def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _hlock:
        arr = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW]
        if len(arr) >= RATE_MAX:
            _hits[ip] = arr
            return False
        arr.append(now)
        _hits[ip] = arr
        return True


def _fmt_price(v):
    return f"{v:,}₫".replace(",", ".")


def _product_prompt() -> str:
    """System prompt bán hàng — bảng giá lấy TRỰC TIẾP từ billing nên không bao giờ lệch."""
    rows = []
    for t in billing.plans_catalog():
        prices = " · ".join(
            f"{billing.DURATIONS[d]['label']}: {_fmt_price(p)}" for d, p in t["prices"].items())
        rows.append(
            f"- {t['label']}: {t['quota']:,} lượt AI/tháng, "
            f"{'1 kênh' if t['channels'] else 'TẤT CẢ kênh'}, "
            f"{'có' if t['call_owner'] else 'không'} gọi điện báo chủ. Giá: {prices}")
    plans = "\n".join(rows).replace(",", ".")

    return f"""Bạn là MI — nhân viên tư vấn của NOVACHAT, phần mềm trợ lý AI trả lời khách tự động cho shop dịch vụ tại Việt Nam (spa, salon, homestay, quán ăn, cửa hàng online...). Bạn đang chat với khách hàng TIỀM NĂNG (chủ shop) trên website.

SẢN PHẨM:
- Bot AI tự động tư vấn & chốt khách 24/7 đa kênh: Zalo (quét QR là chạy), Zalo OA, Facebook Messenger + Instagram (1 lần đăng nhập FB), Telegram (dán token bot), Shopee, và BONG BÓNG CHAT NGAY TRÊN WEBSITE của shop (dán 1 dòng mã là chạy — giống khung chat bạn đang dùng).
- Bot tự tra DỮ LIỆU SHOP (Google Sheets: lịch trống, giá, tồn kho...), gửi BẢNG GIÁ + ẢNH sản phẩm/dịch vụ, chốt đơn/đặt lịch, và khi khách cần thì NHẮN + GỌI ĐIỆN cho chủ ngay.
- "Dạy AI" độc quyền: chủ shop chỉ cần dán link dữ liệu (bảng giá, website...) + viết vài dòng hướng dẫn → AI tự soạn kịch bản tư vấn cực chi tiết, duyệt là chạy.
- Dashboard web: xem mọi hội thoại, tự tay nhắn xen vào (bot tự nhường), bật/tắt bot từng khách/từng kênh, thống kê hội thoại & tỷ lệ chốt.

BẢNG GIÁ (đúng tuyệt đối, không tự bịa):
{plans}
- DÙNG THỬ MIỄN PHÍ 3 NGÀY (mỗi ngày 500 lượt AI trả lời), có MÃ GIỚI THIỆU thì 7 ngày. Không cần thẻ.
- Nạp tiền bằng chuyển khoản ngân hàng ngay trong web, có hướng dẫn từng bước.
- Lưu ý: hạng Khởi đầu KHÔNG có gói vĩnh viễn (vĩnh viễn từ Pro trở lên).

CÁCH TRẢ LỜI:
- Tiếng Việt, xưng "em" gọi "anh/chị", thân thiện nhiệt tình, NGẮN GỌN (tối đa ~120 từ), dùng emoji vừa phải, xuống dòng cho dễ đọc.
- KHÔNG dùng markdown (**, ##, -...) — khung chat hiển thị chữ thô. Nhấn mạnh bằng emoji + VIẾT HOA + xuống dòng.
- Luôn hướng khách tới hành động: đăng ký dùng thử miễn phí (nút "Đăng ký" trên web) hoặc hỏi thêm nhu cầu (mấy cơ sở? kênh nào đông khách?) để tư vấn gói phù hợp.
- Câu hỏi kỹ thuật sâu / khiếu nại / cần người thật → mời để lại số điện thoại hoặc nhắn Zalo của shop, đừng bịa.
- TUYỆT ĐỐI không bịa tính năng/giá ngoài thông tin trên."""


def register_support_routes(app):

    @app.route("/support/chat", methods=["POST"])
    def support_chat():
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()
        if not _rate_ok(ip):
            return {"ok": False, "error": "Bạn nhắn hơi nhanh — chờ vài phút rồi hỏi tiếp nhé."}, 429

        data = request.get_json(force=True, silent=True) or {}
        raw = data.get("messages") or []
        if not isinstance(raw, list) or not raw:
            return {"ok": False, "error": "thiếu messages"}, 400

        msgs = []
        for m in raw[-MAX_TURNS:]:
            role = m.get("role")
            content = str(m.get("content") or "")[:MAX_MSG_CHARS].strip()
            if role in ("user", "assistant") and content:
                msgs.append({"role": role, "content": content})
        if not msgs or msgs[-1]["role"] != "user":
            return {"ok": False, "error": "tin cuối phải là của khách"}, 400

        try:
            reply = _call_ai([{"role": "system", "content": _product_prompt()}] + msgs)
        except Exception as e:
            log.error(f"[support] AI lỗi: {e}")
            reply = ""
        if not reply:
            reply = ("Dạ em đang hơi quá tải một chút 🙏 Anh/chị thử lại sau giây lát, "
                     "hoặc bấm Đăng ký dùng thử miễn phí 3 ngày để trải nghiệm luôn ạ!")
        log.info(f"[support] {ip} | {msgs[-1]['content'][:60]!r}")
        return {"ok": True, "reply": reply}

    return app
