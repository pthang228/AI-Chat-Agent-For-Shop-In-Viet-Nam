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


def _compose_system(user_message: str, history: list,
                    user_id: str = None, account: str = None,
                    shop: str = None) -> tuple:
    """Ghép system prompt + thông tin chẩn đoán (cho trang Test bot).
    Chế độ LAI: persona (ngắn) + DỮ LIỆU SHOP tra theo câu hỏi (RAG) + TRÍ NHỚ
    KHÁCH (CRM) + quy ước kỹ thuật. Prompt cũ (không marker): giữ nguyên + memory.
    MULTI-TENANT: persona + tri thức lấy theo SHOP của hội thoại.
    Trả (system_str, debug) — debug = {mode, chunks[], system_chars}."""
    shop = _resolve_shop(user_id, account, shop)
    memory = _memory_block(user_id, account)
    base = _load_system_prompt(shop)
    if not base.startswith(HYBRID_MARKER):
        system = _today_context() + base + (("\n\n" + memory) if memory else "")
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
    # Kho nhỏ → nhồi TOÀN BỘ (0 tra trượt); kho lớn → retrieve top-k liên quan.
    hits, kb_mode = knowledge.context_chunks(f"{prev_user}\n{user_message}".strip(), shop=shop)
    kb_block = knowledge.format_block(hits)
    parts = [_today_context() + persona]
    if kb_block:
        parts.append(kb_block)
    if memory:
        parts.append(memory)
    tech = _load_tech_rules()
    if tech:
        parts.append(tech)
    system = "\n\n".join(parts)
    return system, {
        "mode": "hybrid",
        "kb_mode": kb_mode,   # 'full' (nhồi hết) | 'retrieval' (tra top-k) | 'empty'
        "shop": shop,         # não bot của shop nào (multi-tenant)
        "chunks": [{"title": h.get("title") or "(không tiêu đề)"} for h in hits],
        "system_chars": len(system),
    }


def _build_system_prompt(user_message: str, history: list,
                         user_id: str = None, account: str = None) -> str:
    return _compose_system(user_message, history, user_id, account)[0]


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

    # Thử DeepSeek trước (mặc định — vẫn ghi token nếu biết owner)
    if Config.DEEPSEEK_API_KEY:
        try:
            from app.core import ai_models
            return ai_models.chat(messages, owner=owner,
                                  model_key=ai_models.DEFAULT_MODEL,
                                  timeout=Config.AI_TIMEOUT)
        except Exception as e:
            print(f"[AI] DeepSeek (ai_models) lỗi ({e}), thử client cũ…")
    if Config.DEEPSEEK_API_KEY:
        try:
            client = OpenAI(
                api_key=Config.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
                timeout=Config.AI_TIMEOUT,   # tránh treo thread vô hạn khi AI chậm
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                max_tokens=1024,
                temperature=0.7,
            )
            print("[AI] Dùng DeepSeek")
            return response.choices[0].message.content or ""
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
                    user_id: str = None, account: str = None) -> dict:
    messages = [{"role": "system",
                 "content": _build_system_prompt(user_message, history, user_id, account)}]
    messages += list(history)
    messages.append({"role": "user", "content": user_message})
    owner = _owner_of_shop(_resolve_shop(user_id, account))
    return _parse_ai_output(_call_ai(messages, owner=owner, account=account))


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
