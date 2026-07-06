"""
BÀI VIẾT & BÌNH LUẬN Facebook — logic lõi (không dính Flask, test dễ).

Gồm 3 phần:
  1. contains_phone(text)  — phát hiện SĐT Việt Nam trong bình luận (kể cả viết
     tách "09 12 34 56 78" / chấm gạch) → dùng cho tự động ẨN (chống đối thủ
     inbox cướp khách từ comment lộ số).
  2. Graph API helpers     — list bài viết / bình luận, trả lời, ẩn/hiện,
     nhắn riêng (private reply). Mọi mapping Graph gói ở đây.
  3. handle_feed_change    — webhook field "feed" đẩy bình luận mới về →
     áp cài đặt tự động của Page (ẩn SĐT / trả lời / nhắn riêng).

Trả lời bình luận dùng MẪU CÂU (placeholder {name}) — không gọi AI nên không
tốn quota; AI vẫn tiếp quản khi khách nhắn tiếp trong inbox (luồng Messenger).
"""

import logging
import re

import requests

from app.core.config import Config
from app.core.http_util import post_with_retry

log = logging.getLogger(__name__)


# ── 1. Phát hiện SĐT Việt Nam ────────────────────────────────────────

# Bỏ ký tự chèn giữa số (khách hay viết "09.12-34 56.78" để né bộ lọc)
_SEPARATORS = re.compile(r"[\s.\-_,;:()\[\]{}·•*'\"/\\|]+")
# DI ĐỘNG VN: 0/+84 + đầu số 3|5|7|8|9 + 8 số nữa (đúng 10 số). Lookaround chặn
# dính vào dãy số dài hơn (mã đơn DH00012345678, số tài khoản → KHÔNG phải SĐT).
# Chủ đích chỉ bắt di động — số bàn (02x) hiếm ai comment, đổi lại 0 false-positive.
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?84|0)[35789]\d{8}(?!\d)")


def contains_phone(text: str) -> bool:
    """True nếu bình luận chứa số điện thoại VN (kể cả viết tách/chèn ký tự)."""
    cleaned = _SEPARATORS.sub("", text or "")
    return bool(_PHONE_RE.search(cleaned))


# ── 2. Graph API (bài viết / bình luận) ──────────────────────────────

def _graph() -> str:
    return f"https://graph.facebook.com/{Config.FB_GRAPH_VERSION}"


def list_posts(page_id: str, token: str, limit: int = 25) -> list:
    """Bài viết của Page (mới nhất trước) kèm số bình luận + ảnh + link."""
    r = requests.get(f"{_graph()}/{page_id}/posts", params={
        "access_token": token,
        "fields": "id,message,created_time,permalink_url,full_picture,"
                  "comments.limit(0).summary(true)",
        "limit": limit,
    }, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph /posts {r.status_code}: {r.text[:200]}")
    out = []
    for p in (r.json().get("data") or []):
        out.append({
            "id": p.get("id"),
            "message": p.get("message") or "",
            "created_time": p.get("created_time"),
            "permalink_url": p.get("permalink_url") or "",
            "picture": p.get("full_picture") or "",
            "comment_count": ((p.get("comments") or {}).get("summary") or {}).get("total_count", 0),
        })
    return out


def list_comments(post_id: str, token: str, limit: int = 100) -> list:
    """Bình luận của 1 bài (mới nhất trước), kèm trạng thái ẩn."""
    r = requests.get(f"{_graph()}/{post_id}/comments", params={
        "access_token": token,
        "fields": "id,from,message,created_time,is_hidden,like_count",
        "filter": "stream", "order": "reverse_chronological", "limit": limit,
    }, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Graph /comments {r.status_code}: {r.text[:200]}")
    out = []
    for c in (r.json().get("data") or []):
        frm = c.get("from") or {}
        out.append({
            "id": c.get("id"),
            "from_id": str(frm.get("id") or ""),
            "from_name": frm.get("name") or "",
            "message": c.get("message") or "",
            "created_time": c.get("created_time"),
            "is_hidden": bool(c.get("is_hidden")),
            "like_count": c.get("like_count", 0),
            "has_phone": contains_phone(c.get("message") or ""),
        })
    return out


def _post_ok(r) -> bool:
    if r is None:
        return False
    if r.status_code >= 400:
        log.error(f"[Comments] Graph POST lỗi {r.status_code}: {r.text[:200]}")
        return False
    return True


def reply_comment(comment_id: str, token: str, message: str) -> bool:
    """Trả lời CÔNG KHAI dưới bình luận."""
    return _post_ok(post_with_retry(
        f"{_graph()}/{comment_id}/comments",
        params={"access_token": token}, json={"message": message},
        timeout=20, retries=Config.SEND_RETRIES, log_tag="CmtReply"))


def hide_comment(comment_id: str, token: str, hidden: bool = True) -> bool:
    """Ẩn/hiện bình luận (khách vẫn thấy comment của chính họ — không gây war)."""
    return _post_ok(post_with_retry(
        f"{_graph()}/{comment_id}",
        params={"access_token": token}, json={"is_hidden": bool(hidden)},
        timeout=20, retries=Config.SEND_RETRIES, log_tag="CmtHide"))


def private_reply(comment_id: str, token: str, message: str) -> bool:
    """Nhắn TIN RIÊNG cho người bình luận (comment → inbox Messenger).
    Meta chỉ cho 1 private reply / bình luận — gửi lần 2 sẽ bị Graph từ chối."""
    return _post_ok(post_with_retry(
        f"{_graph()}/{comment_id}/private_replies",
        params={"access_token": token}, json={"message": message},
        timeout=20, retries=Config.SEND_RETRIES, log_tag="CmtPriv"))


# ── 3. Xử lý webhook feed (bình luận mới) ────────────────────────────

def _fill(template: str, name: str) -> str:
    return (template or "").replace("{name}", name or "bạn").strip()


def handle_feed_change(page_id: str, value: dict, token: str, settings: dict,
                       notify=None) -> dict:
    """Bình luận mới từ webhook (changes field="feed") → áp tự động hoá của Page.
    Trả dict các hành động đã làm (phục vụ log/test): {hidden, replied, private_replied}.

    QUAN TRỌNG: bình luận do CHÍNH PAGE viết (kể cả câu tự trả lời của mình)
    phải bỏ qua — không thì bot tự trả lời chính nó vòng lặp vô hạn.
    """
    done = {"hidden": False, "replied": False, "private_replied": False}
    if str(value.get("item") or "") != "comment" or str(value.get("verb") or "") != "add":
        return done
    comment_id = str(value.get("comment_id") or "")
    if not comment_id or not token:
        return done
    frm = value.get("from") or {}
    from_id = str(frm.get("id") or "")
    if from_id and from_id == str(page_id):
        return done                      # Page tự bình luận (echo) → bỏ
    name = frm.get("name") or ""
    text = str(value.get("message") or "")

    # (a) Lộ SĐT → ẩn ngay + báo chủ (khách vẫn inbox được, đối thủ không thấy số)
    if settings.get("auto_hide_phone") and contains_phone(text):
        if hide_comment(comment_id, token, True):
            done["hidden"] = True
            log.info(f"[Comments] đã ẨN bình luận lộ SĐT của {name!r} ({comment_id})")
            if notify:
                try:
                    notify(f"🙈 Đã ẩn bình luận lộ SĐT của {name or 'khách'}: "
                           f"\"{text[:80]}\" — nhớ chủ động liên hệ lại khách nhé!")
                except Exception:
                    pass
        # Bình luận đã ẩn thì thôi trả lời công khai (không ai thấy) — vẫn nhắn riêng
        if settings.get("private_reply") and settings.get("private_reply_text"):
            done["private_replied"] = private_reply(
                comment_id, token, _fill(settings["private_reply_text"], name))
        return done

    # (b) Tự trả lời công khai (mẫu câu, không tốn quota AI)
    if settings.get("auto_reply") and settings.get("auto_reply_text"):
        done["replied"] = reply_comment(
            comment_id, token, _fill(settings["auto_reply_text"], name))

    # (c) Nhắn riêng kéo khách vào inbox (bot AI tiếp quản từ đó)
    if settings.get("private_reply") and settings.get("private_reply_text"):
        done["private_replied"] = private_reply(
            comment_id, token, _fill(settings["private_reply_text"], name))

    return done
