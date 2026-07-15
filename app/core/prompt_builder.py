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
DEFAULT_FILE = Path(__file__).parent / "system_prompt.txt"      # não MẪU (shop ví dụ) — mặc định/khôi phục
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


_gcreds = None    # cache credentials — token sống ~1 giờ, khỏi refresh mỗi lượt


def _google_token() -> str:
    """Access token của SERVICE ACCOUNT (scope drive.readonly) — đọc mọi file
    Google (Docs/Drive) shop đã share cho email service account, không cần
    để công khai. Credentials cache module-level, chỉ refresh khi hết hạn.
    Thiếu credentials/lỗi → ''."""
    global _gcreds
    try:
        from google.auth.transport.requests import Request as _GRequest
        if _gcreds is None:
            from google.oauth2.service_account import Credentials
            _gcreds = Credentials.from_service_account_file(
                Config.GOOGLE_CREDENTIALS_FILE,
                scopes=["https://www.googleapis.com/auth/drive.readonly"])
        if not _gcreds.valid:
            _gcreds.refresh(_GRequest())
        return _gcreds.token or ""
    except Exception as e:
        log.info(f"[PromptBuilder] không lấy được token Google ({e})")
        return ""


def _drive_get(file_id: str, export_mime: str = None):
    """Tải file Google Drive qua Drive API bằng service account.
    export_mime: đặt khi là Google Docs (xuất text). Trả (bytes, content_type)
    hoặc (None, '') nếu không share/không lấy được token."""
    token = _google_token()
    if not token:
        return None, ""
    base = f"https://www.googleapis.com/drive/v3/files/{file_id}"
    url = f"{base}/export?mimeType={export_mime}" if export_mime else f"{base}?alt=media"
    try:
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         timeout=FETCH_TIMEOUT)
        if r.status_code >= 400:
            log.info(f"[PromptBuilder] Drive API HTTP {r.status_code} cho {file_id[:10]}… "
                     "(file chưa share cho service account?)")
            return None, ""
        return r.content, (r.headers.get("Content-Type") or "").lower()
    except Exception as e:
        log.info(f"[PromptBuilder] Drive API lỗi: {e}")
        return None, ""


_gsheet_cache = {}          # sheet_id → (timestamp, text)
_GSHEET_CACHE_TTL = 120     # giây — 1 lần Dạy AI: phân loại + fetch chỉ đọc sheet 1 lần


def _gsheet_text(sheet_id: str) -> str:
    """Đọc Google Sheet bằng SERVICE ACCOUNT (sheet chỉ cần share Người xem cho
    email service account — không cần để công khai). Gom tối đa 5 tab, mỗi tab
    300 dòng, dạng CSV thô. Cache 120s để 1 lượt Dạy AI (phân loại rồi fetch)
    không đọc trùng cùng sheet 2 lần. Lỗi (chưa share/thiếu credentials) → ''."""
    import time as _time
    hit = _gsheet_cache.get(sheet_id)
    if hit and _time.time() - hit[0] < _GSHEET_CACHE_TTL:
        return hit[1]
    try:
        from app.core.sheets import _get_client
        ss = _get_client().open_by_key(sheet_id)
        parts = []
        for ws in ss.worksheets()[:5]:
            rows = ws.get_all_values()
            if not rows:
                continue
            parts.append(f"### Tab: {ws.title}")
            parts += [", ".join(cell for cell in row) for row in rows[:300]]
        out = "\n".join(parts).strip()
        if out:
            log.info(f"[PromptBuilder] đọc sheet {sheet_id[:12]}… bằng service account OK")
            _gsheet_cache[sheet_id] = (_time.time(), out)
        return out
    except Exception as e:
        log.info(f"[PromptBuilder] đọc sheet bằng service account lỗi ({e}) → thử CSV công khai")
        return ""


def _pdf_text(data: bytes) -> str:
    """Bóc chữ từ PDF (pypdf; máy cũ có PyPDF2 cũng chạy). Lỗi/scan ảnh → ''."""
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError:
        try:
            from PyPDF2 import PdfReader
        except ModuleNotFoundError:
            return ""
    import io
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages[:40]).strip()
    except Exception:
        return ""


def _docx_text(data: bytes) -> str:
    """Bóc chữ từ .docx (zip chứa XML — chỉ cần stdlib)."""
    import io
    import zipfile
    try:
        xml = zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml") \
                     .decode("utf-8", "ignore")
        return _strip_html(xml.replace("</w:p>", "\n"))
    except Exception:
        return ""


def _clip_ok(url: str, text: str) -> dict:
    """Kết quả đọc link OK — cắt bớt theo MAX_LINK_CHARS ở MỘT chỗ duy nhất."""
    if len(text) > MAX_LINK_CHARS:
        text = text[:MAX_LINK_CHARS] + "\n…(đã cắt bớt)"
    return {"url": url, "ok": True, "text": text}


def fetch_link(url: str) -> dict:
    """Tải 1 link dữ liệu → {url, ok, text|error}.
    Đọc được: trang web/HTML, text, Google Docs (tự chuyển sang bản xuất text),
    PDF (bóc chữ), file .docx. Loại khác → báo lỗi rõ để shop dán nội dung tay."""
    url = (url or "").strip()
    if not url:
        return {"url": url, "ok": False, "error": "link trống"}
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    # Google Docs: ƯU TIÊN Drive API bằng service account (chỉ cần share cho
    # email service account); lỗi → thử bản xuất text công khai
    m = re.search(r"docs\.google\.com/document/d/([A-Za-z0-9_-]+)", url)
    if m:
        data, _ = _drive_get(m.group(1), export_mime="text/plain")
        text = (data or b"").decode("utf-8", "ignore").strip()
        if text:
            return _clip_ok(url, text)
        url = f"https://docs.google.com/document/d/{m.group(1)}/export?format=txt"
    # File up lên Google Drive (PDF/Word/txt…): Drive API bằng service account;
    # lỗi → thử link tải công khai
    m = re.search(r"drive\.google\.com/(?:file/d/|open\?id=|uc\?[^ ]*id=)([A-Za-z0-9_-]+)", url)
    if m:
        data, ctype = _drive_get(m.group(1))
        if data:
            if any(t in ctype for t in ("image/", "video/", "audio/")):
                return {"url": url, "ok": False, "error": "File ảnh/video/âm thanh — AI chỉ "
                        "đọc được CHỮ. Ảnh sản phẩm thì dùng Thư viện ảnh nhé"}
            if data[:5] == b"%PDF-" or "pdf" in ctype:
                text = _pdf_text(data)
            elif data[:2] == b"PK" or "wordprocessingml" in ctype:
                text = _docx_text(data)
            else:
                text = data.decode("utf-8", "ignore")
                # File nhị phân lạ decode ra rác (nhiều ký tự không in được) → bỏ
                head = text[:2000]
                if head and sum(c.isprintable() or c in "\n\t" for c in head) < len(head) * 0.7:
                    text = ""
            text = (text or "").strip()
            if not text:
                return {"url": url, "ok": False, "error": "File Drive không bóc được chữ "
                        "(scan ảnh / định dạng lạ?) — dán nội dung trực tiếp vào ô hướng dẫn"}
            return _clip_ok(url, text)
        url = f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    # Google Sheets DỮ LIỆU (bảng giá, danh mục… — KHÔNG phải lịch đặt chỗ, UI đã
    # tách nhánh đó): ƯU TIÊN đọc bằng SERVICE ACCOUNT (shop chỉ cần share cho
    # email service account, không cần công khai); lỗi → thử bản xuất CSV công khai
    m = re.search(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)", url)
    if m:
        text = _gsheet_text(m.group(1))
        if text:
            return _clip_ok(url, text)
        url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (NovaChat prompt-builder)"})
        if r.status_code >= 400:
            return {"url": url, "ok": False, "error": f"HTTP {r.status_code}"
                    + (" — link chưa để công khai?" if r.status_code in (401, 403) else "")}
        ctype = (r.headers.get("Content-Type") or "").lower()
        path = url.split("?")[0].lower()
        # Nhận diện theo cả ctype LẪN byte đầu file — server hay trả
        # application/octet-stream cho PDF/DOCX (vd link tải Drive công khai)
        if "pdf" in ctype or path.endswith(".pdf") or r.content[:5] == b"%PDF-":
            text = _pdf_text(r.content)
            if not text:
                return {"url": url, "ok": False, "error": "PDF không bóc được chữ "
                        "(file scan ảnh?) — dán nội dung trực tiếp vào ô hướng dẫn"}
        elif "wordprocessingml" in ctype or path.endswith(".docx"):
            text = _docx_text(r.content)
            if not text:
                return {"url": url, "ok": False, "error": "File .docx không đọc được — "
                        "dán nội dung trực tiếp vào ô hướng dẫn"}
        elif any(t in ctype for t in ("image/", "video/", "audio/")):
            return {"url": url, "ok": False, "error": "File ảnh/video/âm thanh — AI chỉ "
                    "đọc được CHỮ. Ảnh sản phẩm thì dùng Thư viện ảnh nhé"}
        elif ("application/" in ctype and "json" not in ctype
              and "xml" not in ctype and "html" not in ctype):
            return {"url": url, "ok": False, "error": f"Định dạng chưa hỗ trợ ({ctype.split(';')[0]}) "
                    "— hãy xuất ra Google Docs/PDF hoặc dán nội dung trực tiếp"}
        else:
            raw = r.text
            text = _strip_html(raw) if "html" in ctype or raw.lstrip()[:1] == "<" else raw.strip()
        if not text:
            return {"url": url, "ok": False, "error": "trang không có nội dung chữ"}
        return _clip_ok(url, text)
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)[:200]}


# ── Gọi AI sinh prompt (max_tokens lớn hơn _call_ai thường) ─────────

GEN_MAX_TOKENS = 8000    # trần MỖI VÒNG (8192 = trần cứng DeepSeek/1 lượt)
GEN_MAX_ROUNDS = 10      # bị cắt → tự "viết tiếp" tối đa 10 vòng ≈ 80k token output


def _gen_full(client, model: str, messages: list,
              owner: str = None, model_key: str = None) -> str:
    """Gọi AI sinh não; output CHẠM TRẦN max_tokens (finish_reason='length') →
    tự nối 'viết tiếp chính xác từ chỗ dừng' tới khi trọn vẹn (tối đa GEN_MAX_ROUNDS).
    Bộ não dài bao nhiêu cũng không bị cắt cụt giữa chừng nữa.
    Có owner+model_key → ghi token vào billing (usage) như mọi lượt AI khác."""
    out, msgs = [], list(messages)
    total_in = total_out = 0
    for i in range(GEN_MAX_ROUNDS):
        r = client.chat.completions.create(
            model=model, messages=msgs, max_tokens=GEN_MAX_TOKENS, temperature=0.4)
        ch = r.choices[0]
        text = ch.message.content or ""
        out.append(text)
        try:
            u = r.usage
            total_in += u.prompt_tokens or 0
            total_out += u.completion_tokens or 0
        except Exception:
            pass
        if getattr(ch, "finish_reason", None) != "length":
            break
        log.info(f"[PromptBuilder] output chạm trần {GEN_MAX_TOKENS} — viết tiếp (vòng {i + 2}/{GEN_MAX_ROUNDS})")
        msgs = msgs + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "(Output vừa rồi bị cắt vì giới hạn độ dài.) "
             "VIẾT TIẾP CHÍNH XÁC từ ký tự đang dừng — không lặp lại phần đã viết, "
             "không lời dẫn, không mở code fence mới."},
        ]
    if owner and model_key and (total_in or total_out):
        try:
            from app.core import billing
            billing.record_token_usage(owner, model_key, total_in, total_out)
        except Exception:
            pass
    return "".join(out)


def _call_ai_long(messages: list, model_key: str = None, owner: str = None) -> str:
    # Shop chọn model để DẠY → gọi model đó (kèm tự-viết-tiếp khi output dài);
    # lỗi → rơi xuống chuỗi DeepSeek→Groq mặc định.
    if model_key:
        try:
            from app.core import ai_models
            client, model_id = ai_models.client_for(model_key, Config.AI_LONG_TIMEOUT)
            r = _gen_full(client, model_id, messages, owner=owner, model_key=model_key)
            log.info(f"[PromptBuilder] dùng model shop chọn: {model_key}")
            return r
        except Exception as e:
            log.error(f"[PromptBuilder] model {model_key} lỗi ({e}) → fallback mặc định")
    if Config.DEEPSEEK_API_KEY:
        try:
            client = OpenAI(api_key=Config.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com",
                            timeout=Config.AI_LONG_TIMEOUT)
            r = _gen_full(client, "deepseek-chat", messages,
                          owner=owner, model_key="deepseek-chat")
            log.info("[PromptBuilder] dùng DeepSeek")
            return r
        except Exception as e:
            log.error(f"[PromptBuilder] DeepSeek lỗi: {e}")
    if Config.GROQ_API_KEY:
        try:
            client = OpenAI(api_key=Config.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1",
                            timeout=Config.AI_LONG_TIMEOUT)
            # Ghi usage như model mặc định (Groq không có trong catalog giá —
            # tính theo giá deepseek-chat để số "đã tiêu" của shop không bị hụt)
            r = _gen_full(client, "llama-3.3-70b-versatile", messages,
                          owner=owner, model_key="deepseek-chat")
            log.info("[PromptBuilder] dùng Groq")
            return r
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
 · PHỦ KÍN 100%: TUYỆT ĐỐI KHÔNG bỏ sót bất kỳ thông tin nào chủ shop đã cung cấp —
   mọi dịch vụ, mọi mức giá, mọi chính sách, mọi ghi chú đều phải nằm trong ít nhất 1 mẩu.
   Thà nhiều mẩu còn hơn thiếu dữ liệu. KHÔNG tóm tắt làm mất chi tiết/số liệu.
 · FAQ: TỪNG DÒNG "câu hỏi → câu trả lời" chủ shop ghi phải vào knowledge — nội dung
   giữ nguyên ý và số liệu, câu hỏi gốc đưa vào keywords của mẩu đó.
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
0. Output phải TRỌN VẸN cả 3 phần (không dừng giữa chừng) — content mỗi mẩu viết CÔ ĐỌNG,
   đủ số liệu nhưng không văn vẻ dài dòng, không lặp lại thông tin giữa các mẩu.
1. Viết tiếng Việt. Tôn trọng tuyệt đối HƯỚNG DẪN CỦA CHỦ SHOP — ưu tiên hơn dữ liệu nếu mâu thuẫn.
2. Tham khảo PROMPT MẪU chỉ để học giọng điệu/quy trình — KHÔNG bê số liệu của prompt mẫu vào (đó là shop khác).
3. CHỈ trả về đúng 3 phần với các dòng phân cách ===PERSONA===, ===KNOWLEDGE===, ===GAPS=== — không lời dẫn, không giải thích, không code fence.
"""


def _loads_json_loose(raw: str):
    """Parse JSON; kèm rác trước/sau → bóc đoạn [...] ngoài cùng. Output bị CẮT CỤT
    (AI chạm max_tokens giữa chừng) → vớt các phần tử còn NGUYÊN VẸN thay vì vứt hết
    (trước đây parse fail → rơi về chế độ cũ, shop thấy nguyên văn JSON thô). Hỏng → None."""
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
    # Cứu mảng bị cắt cụt: cắt tới '}' cuối cùng còn nguyên rồi tự đóng ']'
    start = raw.find("[")
    if start >= 0:
        end = raw.rfind("}")
        if end > start:
            try:
                out = json.loads(raw[start:end + 1] + "]")
                log.warning(f"[PromptBuilder] JSON bị cắt cụt — vớt được {len(out)} phần tử nguyên vẹn")
                return out
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


def _norm_links(links: list) -> list:
    """Mỗi phần tử: string URL hoặc dict {url, note} → list (url, note).
    Giữ tương thích ngược với mảng string cũ."""
    out = []
    for item in (links or []):
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            note = str(item.get("note") or "").strip()
        else:
            url = str(item or "").strip()
            note = ""
        if url:
            out.append((url, note))
    return out


def generate(links: list, instructions: str, model: str = None, owner: str = None,
             extra_context: str = None) -> dict:
    """Tải các link + gộp hướng dẫn → AI viết persona + mẩu tri thức.
    links: string URL hoặc {url, note} (note = shop mô tả link, tuỳ chọn).
    model: key trong ai_models.CATALOG shop chọn để DẠY (None = mặc định hệ thống);
    owner: username chủ shop (ghi token usage khi dùng model);
    extra_context: dữ liệu cấu hình shop hệ thống tự đính kèm (prompt_api gom).
    Trả {draft, chunks, mode, sources} — chunks rỗng nghĩa là chế độ cũ."""
    results = []
    for url, note in _norm_links(links):
        # (Sheet LỊCH ĐẶT CHỖ đã bị prompt_api tách nhánh trước khi tới đây —
        # sheet còn lại là DỮ LIỆU, fetch_link tự đọc bằng service account/CSV)
        r = fetch_link(url)
        r["note"] = note
        results.append(r)
    ok_parts, total = [], 0
    for r in results:
        if not r["ok"]:
            continue
        header = f"\n===== NGUỒN: {r['url']} ====="
        if r.get("note"):
            header += f"\n— Shop mô tả link này: {r['note']}"
        chunk = f"{header}\n{r['text']}\n"
        if total + len(chunk) > MAX_TOTAL_CHARS:
            break
        ok_parts.append(chunk)
        total += len(chunk)

    instructions = (instructions or "").strip()
    if not ok_parts and not instructions:
        raise ValueError("Cần ít nhất 1 link đọc được hoặc 1 đoạn hướng dẫn")

    # Cấu hình shop hệ thống tự gom (liên hệ khẩn, câu mẫu, lịch, bộ ảnh…) —
    # thêm như 1 nguồn dữ liệu bổ sung ngay sau dữ liệu link.
    shop_data = "".join(ok_parts) if ok_parts else "(không có link nào đọc được)"
    if (extra_context or "").strip():
        shop_data += f"\n===== CẤU HÌNH SHOP (tự động) =====\n{extra_context.strip()}\n"

    # NHẬN DIỆN NGÀNH → checklist ngành đi kèm meta-prompt: AI phủ đủ mục sống còn
    # của ngành đó, mục thiếu phải khai ở GAPS (spa ≠ quán ăn ≠ homestay).
    from app.core import industry as _ind
    ind_key = _ind.detect(shop_data + "\n" + instructions, model_key=model, owner=owner)
    ind_block = _ind.checklist_block(ind_key)
    if owner:
        try:   # lưu ngành theo chủ shop — health check/báo cáo dùng lại
            from app.core.db import get_db
            get_db().execute("UPDATE users SET industry=? WHERE username=?", (ind_key, owner))
        except Exception:
            pass
    log.info(f"[PromptBuilder] ngành nhận diện: {ind_key} ({_ind.label(ind_key)})")

    # Tham chiếu MẪU CHUẨN generic (không phải não mẫu homestay) → sinh prompt cho spa/salon/
    # quán ăn… không bị "lây" số liệu homestay. Thiếu file mẫu → dùng tạm mặc định.
    ref_prompt = template() or (DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else "")
    user_msg = (
        "PROMPT MẪU CHUẨN (chỉ tham khảo cấu trúc/giọng điệu/quy trình — KHÔNG bê nội dung mẫu vào):\n"
        "-----------------------------------------------\n"
        f"{ref_prompt[:20000]}\n"
        "-----------------------------------------------\n\n"
        + ind_block
        + "\n(Mục nào trong checklist mà dữ liệu shop KHÔNG có → đưa vào ===GAPS===.)\n\n"
        "DỮ LIỆU CỦA SHOP (từ các link):\n"
        + shop_data
        + "\n\nHƯỚNG DẪN CỦA CHỦ SHOP:\n"
        + (instructions or "(không có)")
        + "\n\nHãy tạo đúng 2 phần ===PERSONA=== và ===KNOWLEDGE=== theo NHIỆM VỤ."
    )
    raw = _call_ai_long([
        {"role": "system", "content": _META_PROMPT},
        {"role": "user", "content": user_msg},
    ], model_key=model, owner=owner).strip()
    # AI đôi khi vẫn bọc ```...``` toàn bộ → bóc ra
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()
    if not raw:
        raise RuntimeError("AI trả về rỗng — thử lại")
    draft, chunks, gaps = _parse_hybrid(raw)
    # KIỂM PHỦ: output dài có thể bị cắt cụt → _loads_json_loose chỉ vớt mẩu
    # nguyên vẹn, phần đuôi MẤT TRONG IM LẶNG. Chạy 1 lượt AI rẻ so dữ liệu gốc
    # với danh sách mẩu đã băm → chủ đề thiếu nhét vào gaps (UI đã hiện sẵn).
    if chunks:
        gaps = _coverage_gaps(shop_data + "\n\n" + ind_block, instructions, chunks, gaps,
                              model=model, owner=owner)
    return {
        "draft": draft,
        "chunks": chunks,
        "gaps": gaps,
        "industry": ind_key,
        "industry_label": _ind.label(ind_key),
        "mode": "hybrid" if chunks else "legacy",
        "sources": [{"url": r["url"], "ok": r["ok"], "error": r.get("error", "")} for r in results],
    }


_COVERAGE_PROMPT = (
    "Bạn kiểm tra ĐỘ PHỦ của cơ sở tri thức chatbot. Cho (1) DỮ LIỆU GỐC của shop "
    "và (2) DANH SÁCH TIÊU ĐỀ mẩu đã băm. Liệt kê những CHỦ ĐỀ QUAN TRỌNG với "
    "khách (dịch vụ, mức giá, chính sách, giờ giấc, địa chỉ...) CÓ trong dữ liệu "
    "gốc nhưng KHÔNG thấy mẩu nào bao phủ.\n"
    "Trả về DUY NHẤT một JSON array các chuỗi ngắn gọn (tối đa 6), đủ phủ rồi thì "
    "trả []. Không giải thích, không markdown."
)


def _coverage_gaps(shop_data: str, instructions: str, chunks: list,
                   gaps: list, model: str = None, owner: str = None) -> list:
    """So dữ liệu gốc với mẩu đã băm — chủ đề bị sót (thường do output cắt cụt)
    thêm vào gaps để shop thấy ngay cạnh preview. Lỗi → giữ gaps cũ, không ném."""
    try:
        titles = "\n".join(f"- {c.get('title') or (c.get('content') or '')[:60]}"
                           for c in chunks)
        raw = _call_ai_long([
            {"role": "system", "content": _COVERAGE_PROMPT},
            {"role": "user", "content":
                f"DỮ LIỆU GỐC (rút gọn):\n{shop_data[:40_000]}\n\n"
                f"HƯỚNG DẪN CHỦ SHOP:\n{(instructions or '')[:4_000]}\n\n"
                f"TIÊU ĐỀ CÁC MẨU ĐÃ BĂM ({len(chunks)} mẩu):\n{titles}"},
        ], model_key=model, owner=owner)
        missing = _loads_json_loose(raw)
        if not isinstance(missing, list):
            return gaps
        missing = [f"(Có thể bị sót) {str(m).strip()}" for m in missing if str(m).strip()][:6]
        if missing:
            log.warning(f"[PromptBuilder] kiểm phủ phát hiện {len(missing)} chủ đề nghi sót")
        # gaps gốc trước, cảnh báo sót sau — trần tổng 10 mục cho gọn UI
        return (gaps + missing)[:10]
    except Exception as e:
        log.warning(f"[PromptBuilder] kiểm phủ lỗi (bỏ qua): {e}")
        return gaps


# ── Lưu / khôi phục (MULTI-TENANT: mỗi shop 1 file persona riêng) ────

def _shop_file(shop: str):
    """File persona của shop. QUAN TRỌNG: 'default' phải trả CUSTOM_FILE (module
    attr) — tests monkeypatch pb.CUSTOM_FILE/BACKUP_DIR sang file tạm; bỏ qua attr
    này từng làm test GHI ĐÈ + XOÁ MẤT file não THẬT data/custom_prompt.txt."""
    if not shop or shop == knowledge.DEFAULT_SHOP:
        return CUSTOM_FILE
    from app.core.claude_ai import _custom_prompt_file
    return _custom_prompt_file(shop)


def current(shop: str = knowledge.DEFAULT_SHOP) -> dict:
    f = _shop_file(shop)
    if f.exists():
        text = f.read_text(encoding="utf-8")
        hybrid = text.startswith(HYBRID_MARKER)
        if hybrid:  # bỏ dòng marker khi hiển thị cho shop
            text = text[len(HYBRID_MARKER):].lstrip("\n")
        return {
            "prompt": text,
            "source": "custom",
            "mode": "hybrid" if hybrid else "legacy",
            "chunk_count": knowledge.count(shop) if hybrid else 0,
            "updated_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
    return {
        "prompt": DEFAULT_FILE.read_text(encoding="utf-8") if DEFAULT_FILE.exists() else "",
        "source": "default",
        "mode": "legacy",
        "chunk_count": 0,
        "updated_at": None,
    }


def _backup_name(shop: str, stamp: str) -> str:
    safe = "default" if shop == knowledge.DEFAULT_SHOP else str(shop).replace("@", "_at_")
    return f"custom_prompt-{safe}-{stamp}.txt"


def apply(text: str, chunks: list = None, shop: str = knowledge.DEFAULT_SHOP) -> dict:
    """Lưu bộ não mới CỦA SHOP. Có chunks → chế độ lai: persona (kèm marker) +
    ingest tri thức theo shop. Không chunks → 1 prompt lớn (legacy)."""
    text = (text or "").strip()
    if len(text) < 200:
        raise ValueError("Prompt quá ngắn (<200 ký tự) — có vẻ chưa đúng")
    f = _shop_file(shop)
    f.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)
    if f.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (BACKUP_DIR / _backup_name(shop, stamp)).write_text(
            f.read_text(encoding="utf-8"), encoding="utf-8")
    if chunks:
        n = knowledge.ingest(chunks, shop)
        f.write_text(HYBRID_MARKER + "\n" + text, encoding="utf-8")
        log.info(f"[PromptBuilder] [{shop}] lưu bộ não LAI (persona {len(text)} ký tự + {n} mẩu)")
    else:
        f.write_text(text, encoding="utf-8")
        log.info(f"[PromptBuilder] [{shop}] lưu prompt tuỳ chỉnh ({len(text)} ký tự)")
    return current(shop)


def restore_default(shop: str = knowledge.DEFAULT_SHOP) -> dict:
    f = _shop_file(shop)
    if f.exists():
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        f.replace(BACKUP_DIR / _backup_name(shop, stamp))
        log.info(f"[PromptBuilder] [{shop}] đã khôi phục prompt mặc định")
    knowledge.clear(shop)   # tri thức lai đi kèm prompt tuỳ chỉnh → dọn cùng
    return current(shop)
