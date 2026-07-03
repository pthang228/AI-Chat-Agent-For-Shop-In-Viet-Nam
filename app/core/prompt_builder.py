"""
Prompt Builder — shop gửi LINK dữ liệu (không giới hạn) + HƯỚNG DẪN bằng lời
→ AI đọc hết và viết ra 1 system prompt CỰC KỲ CHI TIẾT cho bot của shop
→ shop xem trước, đồng ý thì lưu (data/custom_prompt.txt) → bot dùng ngay
  (claude_ai đọc lại prompt mỗi request, không cần restart).

Prompt gốc đi kèm code (app/core/system_prompt.txt) KHÔNG bị đụng — dùng làm
khung tham chiếu khi sinh prompt mới + để "khôi phục mặc định".
"""

import re
import logging
from datetime import datetime
from pathlib import Path

import requests
from openai import OpenAI

from app.core.config import Config

log = logging.getLogger(__name__)

CUSTOM_FILE = Config.DATA_DIR / "custom_prompt.txt"
BACKUP_DIR = Config.DATA_DIR / "prompt_backups"
DEFAULT_FILE = Path(__file__).parent / "system_prompt.txt"

MAX_LINK_CHARS = 15_000     # cắt bớt mỗi link để không tràn context AI
MAX_TOTAL_CHARS = 120_000   # tổng dữ liệu đưa vào AI
FETCH_TIMEOUT = 20


# ── Lấy nội dung link ───────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """HTML → text thô (đủ tốt cho Google Docs publish, trang giới thiệu...)."""
    html = re.sub(r"(?is)<(script|style|noscript|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h[1-6]>", "\n", html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<") \
               .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def fetch_link(url: str) -> dict:
    """Tải 1 link dữ liệu → {url, ok, text|error}."""
    url = (url or "").strip()
    if not url:
        return {"url": url, "ok": False, "error": "link trống"}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (NovaChat prompt-builder)"})
        if r.status_code >= 400:
            return {"url": url, "ok": False, "error": f"HTTP {r.status_code}"}
        ctype = (r.headers.get("Content-Type") or "").lower()
        raw = r.text
        text = _strip_html(raw) if "html" in ctype or raw.lstrip()[:1] == "<" else raw.strip()
        if not text:
            return {"url": url, "ok": False, "error": "trang không có nội dung chữ"}
        if len(text) > MAX_LINK_CHARS:
            text = text[:MAX_LINK_CHARS] + "\n…(đã cắt bớt)"
        return {"url": url, "ok": True, "text": text}
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:200]}


# ── Gọi AI sinh prompt (max_tokens lớn hơn _call_ai thường) ─────────

def _call_ai_long(messages: list) -> str:
    if Config.DEEPSEEK_API_KEY:
        try:
            client = OpenAI(api_key=Config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
            r = client.chat.completions.create(
                model="deepseek-chat", messages=messages, max_tokens=6000, temperature=0.4)
            log.info("[PromptBuilder] dùng DeepSeek")
            return r.choices[0].message.content or ""
        except Exception as e:
            log.error(f"[PromptBuilder] DeepSeek lỗi: {e}")
    if Config.GROQ_API_KEY:
        try:
            client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
            r = client.chat.completions.create(
                model="llama-3.3-70b-versatile", messages=messages, max_tokens=6000, temperature=0.4)
            log.info("[PromptBuilder] dùng Groq")
            return r.choices[0].message.content or ""
        except Exception as e:
            log.error(f"[PromptBuilder] Groq lỗi: {e}")
    raise RuntimeError("Không gọi được AI (kiểm tra DEEPSEEK_API_KEY/GROQ_API_KEY trong .env)")


_META_PROMPT = """Bạn là CHUYÊN GIA viết system prompt cho chatbot bán hàng/chăm sóc khách của shop dịch vụ Việt Nam (spa, salon, homestay, quán ăn, cửa hàng online...).

NHIỆM VỤ: từ (1) DỮ LIỆU CỦA SHOP và (2) HƯỚNG DẪN CỦA CHỦ SHOP bên dưới, hãy viết MỘT system prompt hoàn chỉnh, CỰC KỲ CHI TIẾT và TRỰC QUAN để chatbot tư vấn khách qua tin nhắn (Zalo/Messenger/Telegram/TikTok).

YÊU CẦU BẮT BUỘC với prompt bạn viết ra:
1. Viết bằng tiếng Việt, xưng "mình" với khách, giọng thân thiện có emoji vừa phải.
2. Cấu trúc RÕ RÀNG theo mục lớn có tiêu đề: VAI TRÒ · THÔNG TIN CƠ SỞ (địa chỉ, phòng, giá, tiện ích, chính sách…) · QUY TRÌNH TƯ VẤN & CHỐT PHÒNG · CÂU HỎI THƯỜNG GẶP · QUY TẮC ỨNG XỬ (điều cấm, khi nào chuyển cho chủ).
3. NHỒI TOÀN BỘ dữ liệu hữu ích từ DỮ LIỆU CỦA SHOP vào prompt (giá từng phòng, mô tả, chính sách nhận/trả phòng, địa chỉ, số điện thoại…) — trình bày dạng bảng/gạch đầu dòng dễ tra.
4. Tôn trọng tuyệt đối HƯỚNG DẪN CỦA CHỦ SHOP (giọng điệu, điều được/không được nói, khuyến mãi…). Hướng dẫn của chủ shop được ưu tiên hơn dữ liệu nếu mâu thuẫn.
5. GIỮ NGUYÊN các quy ước kỹ thuật trong PROMPT MẪU (định dạng JSON trả về, các intent, cách đặt checkin/checkout…) nếu có — bot cần chúng để hoạt động.
6. Không bịa thông tin không có trong dữ liệu; chỗ thiếu thì ghi rõ "(chủ shop bổ sung sau)".
7. CHỈ trả về nội dung prompt hoàn chỉnh — không lời dẫn, không giải thích, không markdown code fence.
"""


def generate(links: list, instructions: str) -> dict:
    """Tải các link + gộp hướng dẫn → AI viết prompt chi tiết. Trả {draft, sources}."""
    results = [fetch_link(u) for u in (links or []) if (u or "").strip()]
    ok_parts, total = [], 0
    for r in results:
        if not r["ok"]:
            continue
        chunk = f"\n===== NGUỒN: {r['url']} =====\n{r['text']}\n"
        if total + len(chunk) > MAX_TOTAL_CHARS:
            break
        ok_parts.append(chunk)
        total += len(chunk)

    instructions = (instructions or "").strip()
    if not ok_parts and not instructions:
        raise ValueError("Cần ít nhất 1 link đọc được hoặc 1 đoạn hướng dẫn")

    default_prompt = DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else ""
    user_msg = (
        "PROMPT MẪU HIỆN TẠI (tham chiếu cấu trúc + quy ước kỹ thuật PHẢI GIỮ):\n"
        "-----------------------------------------------\n"
        f"{default_prompt[:20000]}\n"
        "-----------------------------------------------\n\n"
        "DỮ LIỆU CỦA SHOP (từ các link):\n"
        + ("".join(ok_parts) if ok_parts else "(không có link nào đọc được)")
        + "\n\nHƯỚNG DẪN CỦA CHỦ SHOP:\n"
        + (instructions or "(không có)")
        + "\n\nHãy viết system prompt hoàn chỉnh theo đúng YÊU CẦU BẮT BUỘC."
    )
    draft = _call_ai_long([
        {"role": "system", "content": _META_PROMPT},
        {"role": "user", "content": user_msg},
    ]).strip()
    # AI đôi khi vẫn bọc ```...``` → bóc ra
    draft = re.sub(r"^```[a-z]*\n?", "", draft)
    draft = re.sub(r"\n?```$", "", draft).strip()
    if not draft:
        raise RuntimeError("AI trả về rỗng — thử lại")
    return {
        "draft": draft,
        "sources": [{"url": r["url"], "ok": r["ok"], "error": r.get("error", "")} for r in results],
    }


# ── Lưu / khôi phục ─────────────────────────────────────────────────

def current() -> dict:
    if CUSTOM_FILE.exists():
        return {
            "prompt": CUSTOM_FILE.read_text(encoding="utf-8"),
            "source": "custom",
            "updated_at": datetime.fromtimestamp(CUSTOM_FILE.stat().st_mtime).isoformat(),
        }
    return {
        "prompt": DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else "",
        "source": "default",
        "updated_at": None,
    }


def apply(text: str) -> dict:
    text = (text or "").strip()
    if len(text) < 200:
        raise ValueError("Prompt quá ngắn (<200 ký tự) — có vẻ chưa đúng")
    BACKUP_DIR.mkdir(exist_ok=True)
    if CUSTOM_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / f"custom_prompt-{stamp}.txt").write_text(
            CUSTOM_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    CUSTOM_FILE.write_text(text, encoding="utf-8")
    log.info(f"[PromptBuilder] đã lưu prompt tuỳ chỉnh ({len(text)} ký tự)")
    return current()


def restore_default() -> dict:
    if CUSTOM_FILE.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        CUSTOM_FILE.replace(BACKUP_DIR / f"custom_prompt-{stamp}.txt")
        log.info("[PromptBuilder] đã khôi phục prompt mặc định")
    return current()
