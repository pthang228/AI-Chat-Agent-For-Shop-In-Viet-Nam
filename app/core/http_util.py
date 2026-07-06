"""
Tiện ích HTTP dùng chung cho MỌI kênh — gửi tin có RETRY + BACKOFF.

Lý do: mạng chớp 1 cái hoặc nền tảng trả 429/5xx tạm thời → tin trả lời khách
BIẾN MẤT (các kênh cũ chỉ POST 1 lần rồi log lỗi). Đây là cách các platform lớn
làm: thử lại vài lần với thời gian chờ tăng dần, tôn trọng header Retry-After.

`post_with_retry` trả về đối tượng Response cuối cùng (kể cả khi 4xx không đáng
retry) hoặc None nếu hết lần thử mà vẫn lỗi mạng. KHÔNG ném exception ra ngoài
để chỗ gọi (channel) giữ nguyên hành vi "lỗi thì log, không sập bot".

Chỉ retry khi ĐÁNG: lỗi mạng (không có response) hoặc HTTP 429 / 5xx. 4xx khác
(400 sai token, 403…) retry vô ích → trả về ngay để chỗ gọi log.
"""

import logging
import time

import requests

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def _retry_after_seconds(resp, attempt: int, base_backoff: float) -> float:
    """Số giây chờ trước lần thử kế: ưu tiên header Retry-After của nền tảng,
    nếu không có → backoff luỹ thừa (base * 2^attempt), chặn trần 30s."""
    if resp is not None:
        ra = resp.headers.get("Retry-After")
        if ra:
            try:
                return min(float(ra), 30.0)
            except (TypeError, ValueError):
                pass
    return min(base_backoff * (2 ** attempt), 30.0)


def post_with_retry(url, *, retries: int = 2, base_backoff: float = 1.0,
                    log_tag: str = "HTTP", sleep=time.sleep, **kwargs):
    """POST có retry. `retries` = số lần thử LẠI (tổng số request = retries + 1).
    Mọi tham số requests.post khác (headers/json/data/params/timeout/files)
    truyền qua **kwargs. Trả Response cuối hoặc None (hết lần thử vẫn lỗi mạng)."""
    attempt = 0
    while True:
        resp = None
        try:
            resp = requests.post(url, **kwargs)
        except Exception as e:
            if attempt >= retries:
                log.error(f"[{log_tag}] lỗi mạng sau {attempt + 1} lần thử: {e}")
                return None
            wait = _retry_after_seconds(None, attempt, base_backoff)
            log.warning(f"[{log_tag}] lỗi mạng ({e}) → thử lại sau {wait:.1f}s "
                        f"(lần {attempt + 2}/{retries + 1})")
            sleep(wait)
            attempt += 1
            continue

        if resp.status_code in RETRY_STATUS and attempt < retries:
            wait = _retry_after_seconds(resp, attempt, base_backoff)
            log.warning(f"[{log_tag}] {resp.status_code} → thử lại sau {wait:.1f}s "
                        f"(lần {attempt + 2}/{retries + 1})")
            sleep(wait)
            attempt += 1
            continue

        return resp
