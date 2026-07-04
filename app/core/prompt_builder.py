"""
Prompt Builder — shop gửi LINK dữ liệu (không giới hạn) + HƯỚNG DẪN bằng lời
→ AI đọc hết và viết ra "bộ não" cho bot theo CHẾ ĐỘ LAI (hybrid):
    ① PERSONA ngắn (giọng, vai trò, quy trình sale)  → data/custom_prompt.txt
       (file bắt đầu bằng marker #NOVACHAT-HYBRID-V1 để claude_ai nhận biết)
    ② KNOWLEDGE chunks (facts + keywords khách hay hỏi) → SQLite (app/core/knowledge.py)
       → mỗi tin nhắn chỉ tra 3-4 mẩu liên quan thay vì nhồi cả 13k ký tự.
→ shop xem trước, đồng ý thì lưu → bot dùng ngay (đọc lại mỗi request, không restart).

TƯƠNG THÍCH NGƯỢC: prompt cũ (không marker) chạy y như trước; AI trả về không
parse được 2 phần → fallback coi toàn bộ là prompt kiểu cũ.

Prompt gốc đi kèm code (app/core/system_prompt.txt) KHÔNG bị đụng — dùng làm
khung tham chiếu khi sinh prompt mới + để "khôi phục mặc định".
"""

import json
import re
import logging
from datetime import datetime
from pathlib import Path

import requests
from openai import OpenAI

from app.core.config import Config
from app.core import knowledge

log = logging.getLogger(__name__)

CUSTOM_FILE = Config.DATA_DIR / "custom_prompt.txt"
BACKUP_DIR = Config.DATA_DIR / "prompt_backups"
DEFAULT_FILE = Path(__file__).parent / "system_prompt.txt"      # não Haru — mặc định/khôi phục
TEMPLATE_FILE = Path(__file__).parent / "prompt_template.txt"   # mẫu chuẩn generic mọi shop

HYBRID_MARKER = "#NOVACHAT-HYBRID-V1"


def template() -> str:
    """Prompt mẫu chuẩn generic cho shop dịch vụ (để shop chỉnh tay / AI tham chiếu)."""
    return TEMPLATE_FILE.read_text(encoding="utf-8") if TEMPLATE_FILE.exists() else ""

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


_META_PROMPT = """Bạn là CHUYÊN GIA thiết kế "bộ não" cho chatbot bán hàng/chăm sóc khách của shop dịch vụ Việt Nam (spa, salon, homestay, quán ăn, cửa hàng online...).

NHIỆM VỤ: từ (1) DỮ LIỆU CỦA SHOP và (2) HƯỚNG DẪN CỦA CHỦ SHOP bên dưới, tạo ra HAI PHẦN theo đúng định dạng:

===PERSONA===
(phần 1 — system prompt NGẮN GỌN, TỐI ĐA 3500 ký tự, chỉ gồm:
 · VAI TRÒ: bot là ai, của shop nào, xưng hô thế nào với khách
 · GIỌNG ĐIỆU: thân thiện, câu ngắn dễ đọc trên điện thoại, emoji vừa phải, KHÔNG markdown
 · QUY TRÌNH TƯ VẤN & CHỐT KHÁCH: các bước dẫn khách từ hỏi → chốt đơn/đặt lịch
 · QUY TẮC ỨNG XỬ: điều cấm nói, khi nào chuyển cho chủ shop, cách xử lý khách khó
 · TIN NHẮN CHÀO ĐẦU TIÊN (nếu chủ shop có yêu cầu)
 TUYỆT ĐỐI KHÔNG đưa số liệu cụ thể (giá, địa chỉ, danh sách phòng/dịch vụ, chính sách chi tiết)
 vào phần này — chúng thuộc phần 2. KHÔNG viết quy ước kỹ thuật JSON/intent — hệ thống tự thêm.)
===KNOWLEDGE===
(phần 2 — JSON array các MẨU TRI THỨC tra cứu, băm TOÀN BỘ dữ liệu hữu ích của shop:
[
  {"title": "tiêu đề ngắn của mẩu", "content": "nội dung đầy đủ, số liệu chính xác từ dữ liệu",
   "keywords": ["các cách", "khách hay hỏi", "về mẩu này", "gồm cả từ đồng nghĩa, viết tắt"],
   "pinned": false},
  ...
]
 QUY TẮC phần 2:
 · Mỗi mẩu = MỘT chủ đề gọn (1 phòng/1 dịch vụ/1 chính sách/1 nhóm FAQ) — 10-60 mẩu.
 · "keywords": 5-15 cụm từ khách thật sự gõ khi hỏi về mẩu đó (vd mẩu giá phòng: "giá", "bao nhiêu tiền", "nhiêu 1 đêm", "bảng giá", "phí"...). Nghĩ như KHÁCH, không phải như chủ shop.
 · Mẩu đầu tiên: title "Thông tin chung", content = tên shop, địa chỉ, SĐT, giờ mở cửa, tóm tắt dịch vụ — đặt "pinned": true. Các mẩu khác "pinned": false.
 · Số liệu phải CHÍNH XÁC theo dữ liệu; không bịa; chỗ thiếu ghi "(chủ shop bổ sung sau)".
 · JSON hợp lệ tuyệt đối: dùng nháy kép, không dấu phẩy thừa, không chú thích.)
===GAPS===
(phần 3 — JSON array các THÔNG TIN CÒN THIẾU mà bot sẽ cần nhưng chủ shop CHƯA cung cấp,
 viết thành câu hỏi gợi ý ngắn gọn để chủ shop bổ sung. Ví dụ:
["Giờ mở cửa của shop?", "Chính sách hoàn/huỷ khi khách đổi ý?", "Có nhận khách vãng lai không?"]
 Tối đa 8 mục, chỉ nêu thứ THẬT SỰ quan trọng với khách. Đủ thông tin rồi → trả [].)

YÊU CẦU CHUNG:
1. Viết tiếng Việt. Tôn trọng tuyệt đối HƯỚNG DẪN CỦA CHỦ SHOP — ưu tiên hơn dữ liệu nếu mâu thuẫn.
2. Tham khảo PROMPT MẪU chỉ để học giọng điệu/quy trình — KHÔNG bê số liệu của prompt mẫu vào (đó là shop khác).
3. CHỈ trả về đúng 3 phần với các dòng phân cách ===PERSONA===, ===KNOWLEDGE===, ===GAPS=== — không lời dẫn, không giải thích, không code fence.
"""


def _loads_json_loose(raw: str):
    """Parse JSON; kèm rác trước/sau → bóc đoạn [...] ngoài cùng. Hỏng → None."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return None


def _parse_hybrid(raw: str) -> tuple:
    """Bóc (persona, chunks, gaps) từ output AI. Không tách được → (raw, [], [])
    = fallback chế độ cũ (toàn bộ là 1 prompt lớn). gaps luôn optional."""
    m = re.search(
        r"===\s*PERSONA\s*===(.*?)===\s*KNOWLEDGE\s*===(.*?)(?:===\s*GAPS\s*===(.*))?$",
        raw, re.DOTALL | re.IGNORECASE)
    if not m:
        return raw, [], []
    persona = m.group(1).strip()
    chunks = _loads_json_loose(m.group(2).strip())
    if not isinstance(chunks, list):
        chunks = []
    chunks = [c for c in chunks if isinstance(c, dict) and str(c.get("content") or "").strip()]
    gaps = _loads_json_loose((m.group(3) or "").strip()) if m.group(3) else []
    if not isinstance(gaps, list):
        gaps = []
    gaps = [str(g).strip() for g in gaps if str(g).strip()][:8]
    if not persona or not chunks:
        return raw, [], []      # thiếu persona/chunks → an toàn: chế độ cũ
    return persona, chunks, gaps


def generate(links: list, instructions: str) -> dict:
    """Tải các link + gộp hướng dẫn → AI viết persona + mẩu tri thức.
    Trả {draft, chunks, mode, sources} — chunks rỗng nghĩa là chế độ cũ."""
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

    # Tham chiếu MẪU CHUẨN generic (không phải não Haru) → sinh prompt cho spa/salon/
    # quán ăn… không bị "lây" số liệu homestay. Thiếu file mẫu → dùng tạm mặc định.
    ref_prompt = template() or (DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else "")
    user_msg = (
        "PROMPT MẪU CHUẨN (chỉ tham khảo cấu trúc/giọng điệu/quy trình — KHÔNG bê nội dung mẫu vào):\n"
        "-----------------------------------------------\n"
        f"{ref_prompt[:20000]}\n"
        "-----------------------------------------------\n\n"
        "DỮ LIỆU CỦA SHOP (từ các link):\n"
        + ("".join(ok_parts) if ok_parts else "(không có link nào đọc được)")
        + "\n\nHƯỚNG DẪN CỦA CHỦ SHOP:\n"
        + (instructions or "(không có)")
        + "\n\nHãy tạo đúng 2 phần ===PERSONA=== và ===KNOWLEDGE=== theo NHIỆM VỤ."
    )
    raw = _call_ai_long([
        {"role": "system", "content": _META_PROMPT},
        {"role": "user", "content": user_msg},
    ]).strip()
    # AI đôi khi vẫn bọc ```...``` toàn bộ → bóc ra
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()
    if not raw:
        raise RuntimeError("AI trả về rỗng — thử lại")
    draft, chunks, gaps = _parse_hybrid(raw)
    return {
        "draft": draft,
        "chunks": chunks,
        "gaps": gaps,
        "mode": "hybrid" if chunks else "legacy",
        "sources": [{"url": r["url"], "ok": r["ok"], "error": r.get("error", "")} for r in results],
    }


# ── Lưu / khôi phục ─────────────────────────────────────────────────

def current(shop: str = knowledge.DEFAULT_SHOP) -> dict:
    if CUSTOM_FILE.exists():
        text = CUSTOM_FILE.read_text(encoding="utf-8")
        hybrid = text.startswith(HYBRID_MARKER)
        if hybrid:  # bỏ dòng marker khi hiển thị cho shop
            text = text[len(HYBRID_MARKER):].lstrip("\n")
        return {
            "prompt": text,
            "source": "custom",
            "mode": "hybrid" if hybrid else "legacy",
            "chunk_count": knowledge.count(shop) if hybrid else 0,
            "updated_at": datetime.fromtimestamp(CUSTOM_FILE.stat().st_mtime).isoformat(),
        }
    return {
        "prompt": DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else "",
        "source": "default",
        "mode": "legacy",
        "chunk_count": 0,
        "updated_at": None,
    }


def apply(text: str, chunks: list = None, shop: str = knowledge.DEFAULT_SHOP) -> dict:
    """Lưu bộ não mới. Có chunks → chế độ lai: persona (kèm marker) + ingest tri thức.
    Không chunks → y hệt hành vi cũ (1 prompt lớn)."""
    text = (text or "").strip()
    if len(text) < 200:
        raise ValueError("Prompt quá ngắn (<200 ký tự) — có vẻ chưa đúng")
    BACKUP_DIR.mkdir(exist_ok=True)
    if CUSTOM_FILE.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / f"custom_prompt-{stamp}.txt").write_text(
            CUSTOM_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    if chunks:
        n = knowledge.ingest(chunks, shop)
        CUSTOM_FILE.write_text(HYBRID_MARKER + "\n" + text, encoding="utf-8")
        log.info(f"[PromptBuilder] đã lưu bộ não LAI (persona {len(text)} ký tự + {n} mẩu tri thức)")
    else:
        CUSTOM_FILE.write_text(text, encoding="utf-8")
        log.info(f"[PromptBuilder] đã lưu prompt tuỳ chỉnh ({len(text)} ký tự)")
    return current(shop)


def restore_default(shop: str = knowledge.DEFAULT_SHOP) -> dict:
    if CUSTOM_FILE.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        CUSTOM_FILE.replace(BACKUP_DIR / f"custom_prompt-{stamp}.txt")
        log.info("[PromptBuilder] đã khôi phục prompt mặc định")
    knowledge.clear(shop)   # tri thức lai đi kèm prompt tuỳ chỉnh → dọn cùng
    return current(shop)
