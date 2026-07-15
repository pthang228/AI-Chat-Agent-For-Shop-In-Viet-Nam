"""
Xử lý AI — ưu tiên DeepSeek, fallback sang Groq.
"""

import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from openai import OpenAI
from app.core.config import Config

_WEEKDAY_VN = ["Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ Nhật"]


def _today_context() -> str:
    now      = datetime.now()
    tomorrow = now + timedelta(days=1)
    d2       = now + timedelta(days=2)
    d3       = now + timedelta(days=3)

    def fmt(d): return f"{_WEEKDAY_VN[d.weekday()]}, {d.strftime('%d/%m/%Y')}"

    # Lịch 14 ngày để AI tra cứu trực tiếp (không cần tự tính)
    calendar_lines = []
    for i in range(14):
        d = now + timedelta(days=i)
        suffix = ""
        if i == 0: suffix = "  ← HÔM NAY"
        elif i == 1: suffix = "  ← NGÀY MAI"
        calendar_lines.append(
            f"  +{i:2d} ngày = {_WEEKDAY_VN[d.weekday()]}, {d.strftime('%d/%m/%Y')}{suffix}"
        )
    calendar_str = "\n".join(calendar_lines)

    return (
        f"!!!QUAN TRỌNG - THỜI GIAN THỰC TẾ TỪ MÁY CHỦ (KHÔNG ĐƯỢC TỰ TÍNH LẠI)!!!\n"
        f"Hôm nay = {fmt(now)}, {now.strftime('%H:%M')}\n"
        f"\n"
        f"LỊCH 14 NGÀY TỚI — dùng bảng này để chuyển mọi cách nói ngày sang dd/mm/yyyy:\n"
        f"{calendar_str}\n"
        f"\n"
        f"BẢNG QUY ĐỔI NHANH:\n"
        f"  'hôm nay' / 'tối nay' / 'chiều nay' / 'sáng nay' / 'đêm nay'  → {now.strftime('%d/%m/%Y')}\n"
        f"  'mai' / 'ngày mai' / 'tối mai' / 'chiều mai' / 'sáng mai'      → {tomorrow.strftime('%d/%m/%Y')}\n"
        f"  'ngày mốt' / 'ngày kia'                                         → {d2.strftime('%d/%m/%Y')}\n"
        f"  'thứ X tuần sau/tới' → tra cột LỊCH 14 NGÀY bên trên, tìm thứ X đó\n"
        f"\n"
        f"QUY TẮC BẮT BUỘC:\n"
        f"  - Khi khách nêu bất kỳ cách nói ngày nào → PHẢI tính ra dd/mm/yyyy và đặt vào checkin\n"
        f"  - TUYỆT ĐỐI KHÔNG hỏi 'bạn có muốn ngày X không?' hay xác nhận lại ngày\n"
        f"  - TUYỆT ĐỐI KHÔNG tự tính ngoài bảng. Chỉ dùng thông tin trên.\n"
        f"  - Giờ hiện tại {now.strftime('%H:%M')} — nếu khách hỏi lịch hôm nay, vẫn set checkin = {now.strftime('%d/%m/%Y')}\n"
        f"{'='*50}\n\n"
    )


# Marker chế độ LAI (persona + tri thức RAG) — đồng bộ với prompt_builder.HYBRID_MARKER
HYBRID_MARKER = "#NOVACHAT-HYBRID-V1"


def _custom_prompt_file(shop: str = "default"):
    """File persona theo SHOP (multi-tenant). 'default' = chủ nền tảng — giữ
    đường dẫn cũ data/custom_prompt.txt; shop khác → data/prompts/<shop>.txt."""
    if not shop or shop == "default":
        return Config.DATA_DIR / "custom_prompt.txt"
    import re as _re
    safe = _re.sub(r"[^A-Za-z0-9._@-]", "_", str(shop))[:80]
    return Config.DATA_DIR / "prompts" / f"{safe}.txt"


def _load_system_prompt(shop: str = "default") -> str:
    # Prompt TUỲ CHỈNH của TỪNG SHOP được ưu tiên; chưa có → prompt mặc định đi
    # kèm code (KHÔNG rơi về prompt của shop khác — cách ly não bot). Đọc lại MỖI
    # request nên lưu prompt mới trong web là áp dụng ngay, không cần restart.
    custom = _custom_prompt_file(shop)
    try:
        if custom.exists():
            text = custom.read_text(encoding="utf-8").strip()
            if text:
                return text
    except Exception:
        pass
    p = Path(__file__).parent / "system_prompt.txt"
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "Bạn là trợ lý chăm sóc khách hàng homestay."


def _load_tech_rules() -> str:
    # Quy ước kỹ thuật (JSON <analysis>, intent, bảo mật) do CODE sở hữu — chế độ
    # lai luôn tự ghép vào để persona AI sinh ra không thể phá máy móc của brain.
    p = Path(__file__).parent / "tech_rules.txt"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _memory_block(user_id: str, account: str) -> str:
    """TRÍ NHỚ AI VỀ KHÁCH (CRM) — có user_id thì tra, lỗi/không có → rỗng.
    Import trễ + nuốt lỗi: đường nóng của bot không được chết vì CRM."""
    if not user_id:
        return ""
    try:
        from app.core import customers
        return customers.memory_block(account or "", user_id)
    except Exception:
        return ""


def _owner_of_shop(shop: str) -> str | None:
    """Username CHỦ SHOP từ khoá não ('default' → chủ nền tảng) — dùng cho billing
    model AI + usage. Lỗi → None (không ghi usage)."""
    try:
        from app.core import tenant as _tenant
        return _tenant.default_owner() if (not shop or shop == "default") else shop
    except Exception:
        return None


def _resolve_shop(user_id: str = None, account: str = None, shop: str = None) -> str:
    """Khoá não bot theo SHOP: shop truyền thẳng (trang Test bot theo workspace)
    thắng; không có → tra tenant của hội thoại (multi-tenant). Lỗi → 'default'."""
    if shop:
        return shop
    if not user_id:
        return "default"
    try:
        from app.core import tenant as _tenant
        return _tenant.shop_key(_tenant.tenant_of_conv(account or "", user_id))
    except Exception:
        return "default"


def _state_block(conv_state: dict) -> str:
    """TRẠNG THÁI TƯ VẤN từ conv (code thuần, 0 lượt AI) — chống bot 'quên'
    khách đang ở bước nào khi lịch sử raw bị cắt cửa sổ."""
    if not conv_state:
        return ""
    lines = []
    stage = conv_state.get("stage")
    if stage:
        stage_vn = {"greeting": "mới chào hỏi", "checking": "đang hỏi lịch",
                    "offering": "đang được tư vấn phòng/dịch vụ",
                    "confirmed": "ĐÃ CHỐT đặt", "owner_notified": "đã báo chủ, chờ chủ xử lý"}
        lines.append(f"- Giai đoạn: {stage_vn.get(stage, stage)}")
    if conv_state.get("checkin"):
        lines.append(f"- Ngày nhận (checkin) khách đã nêu: {conv_state['checkin']}")
    if conv_state.get("checkout"):
        lines.append(f"- Ngày trả (checkout): {conv_state['checkout']}")
    if conv_state.get("selected_room"):
        lines.append(f"- Phòng/dịch vụ đang quan tâm: {conv_state['selected_room']}")
    if not lines:
        return ""
    return "TRẠNG THÁI TƯ VẤN HIỆN TẠI (hệ thống theo dõi — dùng để trả lời nhất quán):\n" \
           + "\n".join(lines)


def _summary_block(conv_state: dict) -> str:
    s = (conv_state or {}).get("summary") or ""
    if not s.strip():
        return ""
    return ("TÓM TẮT HỘI THOẠI TRƯỚC (các tin cũ hơn đã được tóm lại — nội dung "
            "này là NGỮ CẢNH THẬT của khách này, dùng để trả lời liền mạch):\n" + s.strip())


def _compose_system(user_message: str, history: list,
                    user_id: str = None, account: str = None,
                    shop: str = None, conv_state: dict = None) -> tuple:
    """Ghép system prompt + thông tin chẩn đoán (cho trang Test bot).
    Chế độ LAI: persona (ngắn) + DỮ LIỆU SHOP (facts RAG) + VÍ DỤ CÁCH TƯ VẤN
    (style RAG) + quy ước kỹ thuật + TRÍ NHỚ KHÁCH + trạng thái + tóm tắt cuộn.
    THỨ TỰ CÓ CHỦ ĐÍCH cho context cache (DeepSeek cache theo prefix chung):
    phần ỔN ĐỊNH THEO SHOP đứng đầu (persona/kb/tech — giống nhau cho MỌI khách
    của shop), phần theo-khách đứng sau, _today_context (đổi từng phút) CUỐI CÙNG.
    Prompt cũ (không marker): giữ nguyên + memory.
    Trả (system_str, debug) — debug = {mode, chunks[], system_chars}."""
    shop = _resolve_shop(user_id, account, shop)
    memory = _memory_block(user_id, account)
    state = _state_block(conv_state)
    summary = _summary_block(conv_state)
    base = _load_system_prompt(shop)
    if not base.startswith(HYBRID_MARKER):
        parts = [base]
        for b in (memory, state, summary):
            if b:
                parts.append(b)
        parts.append(_today_context())
        system = "\n\n".join(parts)
        return system, {"mode": "legacy", "chunks": [], "system_chars": len(system)}

    from app.core import knowledge  # import trễ — tránh vòng lặp import khi test mock
    persona = base[len(HYBRID_MARKER):].lstrip("\n")
    # Query tra cứu = tin hiện tại + tin user gần nhất (câu follow-up "giá bao nhiêu?"
    # cần ngữ cảnh phòng vừa nhắc ở tin trước)
    prev_user = ""
    for m in reversed(history or []):
        if m.get("role") == "user":
            prev_user = str(m.get("content") or "")
            break
    query = f"{prev_user}\n{user_message}".strip()
    # Kho nhỏ → nhồi TOÀN BỘ (0 tra trượt); kho lớn → retrieve top-k liên quan.
    hits, kb_mode = knowledge.context_chunks(query, shop=shop)
    kb_block = knowledge.format_block(hits)
    # STYLE RAG: 2 mẫu hội thoại khớp tình huống (bonus intent lượt trước)
    style_hits = knowledge.retrieve_style(
        query, shop=shop, k=2, intent=(conv_state or {}).get("intent") or "")
    style = knowledge.format_style_block(style_hits)
    parts = [persona]                    # ổn định theo shop
    if kb_block:
        parts.append(kb_block)           # ổn định khi kb_mode='full'
    if style:
        parts.append(style)
    tech = _load_tech_rules()
    if tech:
        parts.append(tech)               # ổn định theo code
    for b in (memory, state, summary):   # theo khách
        if b:
            parts.append(b)
    parts.append(_today_context())       # đổi từng phút → CUỐI để không phá cache
    system = "\n\n".join(parts)
    return system, {
        "mode": "hybrid",
        "kb_mode": kb_mode,   # 'full' (nhồi hết) | 'retrieval' (tra top-k) | 'empty'
        "shop": shop,         # não bot của shop nào (multi-tenant)
        "chunks": [{"title": h.get("title") or "(không tiêu đề)"} for h in hits],
        "style_chunks": [{"title": h.get("title") or "(không tiêu đề)"} for h in style_hits],
        "system_chars": len(system),
    }


def _build_system_prompt(user_message: str, history: list,
                         user_id: str = None, account: str = None,
                         conv_state: dict = None) -> str:
    return _compose_system(user_message, history, user_id, account,
                           conv_state=conv_state)[0]


def _call_ai(messages: list, owner: str | None = None, account: str | None = None,
             model_key: str | None = None) -> str:
    # Model CHỈ ĐỊNH (vd trang Test bot chọn model) → gọi thẳng model đó, lỗi mới fallback.
    if model_key:
        try:
            from app.core import ai_models
            return ai_models.chat(messages, owner=owner, model_key=model_key,
                                  timeout=Config.AI_TIMEOUT)
        except Exception as e:
            print(f"[AI] Model chỉ định {model_key} lỗi ({e}) → dùng mặc định")

    # MULTI-MODEL: shop chọn model (billing.ai_model) hoặc PER-APP theo kênh
    # (user_apps.ai_model — tra qua account) → gọi qua ai_models (tự ghi token
    # vào billing để hiển thị usage + trừ ví khi vượt quota).
    # Lỗi/không chọn → rơi xuống chuỗi mặc định DeepSeek → Groq như cũ.
    if owner:
        try:
            from app.core import ai_models
            if ai_models.model_for(owner, account) != ai_models.DEFAULT_MODEL:
                return ai_models.chat(messages, owner=owner, account=account,
                                      timeout=Config.AI_TIMEOUT)
        except Exception as e:
            print(f"[AI] Model shop lỗi ({e}) → dùng mặc định")

    # Thử DeepSeek (mặc định — ghi token nếu biết owner). Lỗi → Groq ngay,
    # KHÔNG gọi lại DeepSeek lần 2 (trước đây retry y hệt làm khách chờ gấp đôi)
    if Config.DEEPSEEK_API_KEY:
        try:
            from app.core import ai_models
            return ai_models.chat(messages, owner=owner,
                                  model_key=ai_models.DEFAULT_MODEL,
                                  timeout=Config.AI_TIMEOUT)
        except Exception as e:
            print(f"[AI] DeepSeek lỗi ({e}), chuyển sang Groq...")

    # Fallback: Groq — API TƯƠNG THÍCH OpenAI nên dùng luôn openai SDK, KHÔNG cần
    # package 'groq' (giống prompt_builder). Thiếu key → báo lỗi tiếng Việt rõ ràng.
    if not Config.GROQ_API_KEY:
        raise RuntimeError(
            "Không gọi được AI: model mặc định (DeepSeek) lỗi hoặc thiếu API key, và "
            "chưa có key dự phòng. Kiểm tra DEEPSEEK_API_KEY / OPENAI_API_KEY / "
            "GROQ_API_KEY trong .env (key có thể đã hết hạn/hết tiền).")
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "gemma2-9b-it"]
    last_error = None
    for model in models:
        try:
            client = OpenAI(api_key=Config.GROQ_API_KEY,
                            base_url="https://api.groq.com/openai/v1",
                            timeout=Config.AI_TIMEOUT)
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            print(f"[AI] Groq fallback — model: {model}")
            return response.choices[0].message.content or ""
        except Exception as e:
            if "429" in str(e) or "rate_limit" in str(e).lower():
                last_error = e
                continue
            raise
    raise last_error


def _parse_ai_output(full_text: str) -> dict:
    """Bóc <analysis> JSON + thẻ [BOOKING_CONFIRMED] khỏi output AI."""
    analysis_match = re.search(r"<analysis>(.*?)</analysis>", full_text, re.DOTALL)
    reply = re.sub(r"<analysis>.*?</analysis>", "", full_text, flags=re.DOTALL).strip()

    analysis = {
        "intent": "other",
        "checkin": None,
        "checkout": None,
        "booking_confirmed": False,
    }
    if analysis_match:
        try:
            parsed = json.loads(analysis_match.group(1).strip())
            # AI đôi khi trả JSON array/số/chuỗi trong <analysis> → json.loads
            # KHÔNG raise nhưng parsed không phải dict → `**analysis` sẽ TypeError
            # làm mất câu trả lời của khách. Chỉ nhận khi là dict.
            if isinstance(parsed, dict):
                analysis = parsed
        except (json.JSONDecodeError, ValueError):
            pass

    if "[BOOKING_CONFIRMED]" in reply:
        analysis["booking_confirmed"] = True
        reply = reply.replace("[BOOKING_CONFIRMED]", "").strip()

    return {"reply": reply, **analysis}


def analyze_message(user_message: str, history: list[dict],
                    user_id: str = None, account: str = None,
                    conv_state: dict = None) -> dict:
    messages = [{"role": "system",
                 "content": _build_system_prompt(user_message, history, user_id, account,
                                                 conv_state=conv_state)}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})
    owner = _owner_of_shop(_resolve_shop(user_id, account))
    return _parse_ai_output(_call_ai(messages, owner=owner, account=account))


# ── Tóm tắt cuộn hội thoại ───────────────────────────────────────────

_SUMMARIZE_PROMPT = (
    "Bạn tóm tắt hội thoại giữa KHÁCH và trợ lý shop để trợ lý đọc lại nhanh.\n"
    "Gộp TÓM TẮT CŨ (nếu có) với các TIN MỚI thành MỘT bản tóm tắt duy nhất, "
    "tối đa 6 dòng gạch đầu dòng, tiếng Việt, chỉ giữ điều CÒN GIÁ TRỊ cho các "
    "lượt tư vấn sau:\n"
    "- khách là ai/xưng hô gì, cần gì (ngày, số người, phòng/dịch vụ quan tâm)\n"
    "- đã báo giá gì / khách phản ứng sao (chê đắt, phân vân, đồng ý...)\n"
    "- lời hứa/hẹn còn treo (khách bảo chiều chốt, chờ chủ trả lời...)\n"
    "KHÔNG bịa, KHÔNG thêm lời khuyên, KHÔNG markdown ngoài dấu '-'. "
    "Chỉ trả về nội dung tóm tắt."
)


def summarize_history(old_summary: str, msgs: list[dict],
                      owner: str = None, account: str = None) -> str:
    """Gộp tóm tắt cũ + các tin vừa rời cửa sổ raw thành tóm tắt mới (3-6 dòng).
    Gọi NỀN sau khi đã trả lời khách — lỗi thì trả tóm tắt cũ, không được ném."""
    try:
        convo = "\n".join(
            f"{'Khách' if m.get('role') == 'user' else 'Trợ lý'}: {str(m.get('content') or '')[:400]}"
            for m in msgs if m.get("content"))
        if not convo.strip():
            return old_summary or ""
        user_block = ""
        if old_summary:
            user_block += f"TÓM TẮT CŨ:\n{old_summary}\n\n"
        user_block += f"TIN MỚI:\n{convo}"
        out = _call_ai(
            [{"role": "system", "content": _SUMMARIZE_PROMPT},
             {"role": "user", "content": user_block}],
            owner=owner, account=account)
        out = (out or "").strip()[:1500]
        return out or (old_summary or "")
    except Exception as e:
        print(f"[Summary] Lỗi tóm tắt (giữ tóm tắt cũ): {e}")
        return old_summary or ""


def analyze_with_debug(user_message: str, history: list[dict], shop: str = None,
                       model_key: str = None) -> dict:
    """Như analyze_message nhưng kèm 'debug' (mode, mẩu tri thức đã tra, cỡ context)
    — dùng cho trang Test bot của shop, KHÔNG lưu session, không gửi kênh nào.
    shop: multi-tenant — test bằng NÃO của shop đang đăng nhập.
    model_key: model CHỈ ĐỊNH để thử (rỗng = model shop đang dùng)."""
    system, dbg = _compose_system(user_message, history, shop=shop)
    messages = [{"role": "system", "content": system}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})
    out = _parse_ai_output(_call_ai(messages, owner=_owner_of_shop(shop), model_key=model_key))
    out["debug"] = dbg
    return out
