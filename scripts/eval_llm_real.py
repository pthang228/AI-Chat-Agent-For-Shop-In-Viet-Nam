#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EVAL LLM THẬT — lưới an toàn cho system_prompt/tech_rules/model drift.

Khác test_eval_brain (mock 100% LLM, chỉ chấm lớp override + template):
script này gọi DeepSeek/Groq THẬT qua đúng đường production
(claude_ai.analyze_message → _parse_ai_output → brain.apply_intent_overrides)
trên golden set tiếng Việt thật (tests/golden/eval_golden.jsonl), chấm bằng CODE:

  1. intent_acc   — intent SAU override khớp kỳ vọng
  2. date_acc     — checkin bóc đúng (+0/+1/+2 = hôm nay/mai/mốt; "dd/mm" = ngày đó)
  3. booking_acc  — cờ booking_confirmed đúng với case chốt đơn
  4. leak_rate    — reply lộ thẻ <analysis>/JSON thô (phải = 0)

Chạy tay:    python scripts/eval_llm_real.py [--min-intent 0.7] [--limit N]
Nightly CI:  .github/workflows/eval.yml (cần secret DEEPSEEK_API_KEY).
KHÔNG có API key → in cảnh báo, exit 0 (không chặn ai chạy local).
Chi phí: ~50 câu × ~2k token ≈ <$0.02/lượt chạy (DeepSeek).
~10 giây nghỉ giữa các call không cần — DeepSeek chịu tốt tần suất này.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOLDEN = Path(__file__).parent.parent / "tests" / "golden" / "eval_golden.jsonl"

VALID_INTENTS = {"availability_check", "price_list_request", "photo_request",
                 "contact_request", "reschedule_request", "unknown_question",
                 "booking_confirmed", "other"}


def expected_date(spec: str) -> str:
    """'+N' → hôm nay+N (dd/mm/yyyy); 'dd/mm' → ngày đó năm nay (hoặc năm sau nếu đã qua)."""
    now = datetime.now()
    if spec.startswith("+"):
        return (now + timedelta(days=int(spec[1:]))).strftime("%d/%m/%Y")
    d, m = (int(x) for x in spec.split("/")[:2])
    cand = now.replace(day=d, month=m)
    if cand.date() < now.date():
        cand = cand.replace(year=now.year + 1)
    return cand.strftime("%d/%m/%Y")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-intent", type=float, default=0.70,
                    help="ngưỡng intent accuracy để exit 0 (đỏ khi tụt)")
    ap.add_argument("--min-booking", type=float, default=0.80,
                    help="ngưỡng booking_acc — chốt đơn là doanh thu, bar cao hơn")
    ap.add_argument("--min-date", type=float, default=0.70,
                    help="ngưỡng date_acc — bóc sai ngày = đặt nhầm lịch")
    ap.add_argument("--max-error-rate", type=float, default=0.20,
                    help="tỉ lệ lỗi gọi LLM tối đa; vượt → coi eval là ĐỎ (không kết luận "
                         "được, tránh 'xanh giả' khi API/model trục trặc)")
    ap.add_argument("--limit", type=int, default=0, help="chỉ chạy N câu đầu (debug)")
    args = ap.parse_args()

    from app.core.config import Config
    if not (Config.DEEPSEEK_API_KEY or Config.GROQ_API_KEY or Config.OPENAI_API_KEY):
        print("⚠️  Không có API key AI (DEEPSEEK/GROQ/OPENAI) — bỏ qua eval LLM thật.")
        return 0

    from app.core import claude_ai
    from app.core.brain import apply_intent_overrides

    cases = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        cases = cases[:args.limit]

    n = len(cases)
    intent_ok = intent_total = 0
    date_ok = date_total = booking_ok = booking_total = leaks = errors = 0
    failures = []

    for i, c in enumerate(cases, 1):
        text = c["text"]
        has_intent = "intent" in c
        try:
            result = claude_ai.analyze_message(text, [])
        except Exception as e:
            errors += 1                 # lỗi gọi → BỎ mọi metric case này (không tính
            failures.append({"text": text, "error": str(e)[:200]})   # điểm free); tỉ lệ
            continue                     # lỗi cao sẽ bị chặn ở gate error_rate bên dưới
        # đúng đường production: lớp override chạy sau LLM
        intent, _ = apply_intent_overrides(text, result, {
            "stage": "greeting", "checkin": result.get("checkin"),
            "selected_room": None, "is_default": True})

        reply = result.get("reply") or ""
        if "<analysis>" in reply or '"intent"' in reply:
            leaks += 1
            failures.append({"text": text, "leak": reply[:120]})

        if has_intent:                  # CHỈ case có 'intent' mới vào mẫu — booking-only
            intent_total += 1           # KHÔNG còn cộng điểm intent free (thổi phồng acc)
            if intent == c["intent"]:
                intent_ok += 1
            else:
                failures.append({"text": text, "want": c["intent"], "got": intent})

        if "checkin" in c:
            date_total += 1
            want = expected_date(c["checkin"])
            if (result.get("checkin") or "") == want:
                date_ok += 1
            else:
                failures.append({"text": text, "want_date": want, "got_date": result.get("checkin")})

        if c.get("expect_booking"):
            booking_total += 1
            if result.get("booking_confirmed"):
                booking_ok += 1
            else:
                failures.append({"text": text, "want": "booking_confirmed=true"})

        print(f"  [{i}/{n}] {intent:20s} {text[:50]!r}")

    intent_acc = intent_ok / max(1, intent_total)       # chỉ trên case CHẠY ĐƯỢC + có intent
    date_acc = (date_ok / date_total) if date_total else None
    booking_acc = (booking_ok / booking_total) if booking_total else None
    error_rate = errors / max(1, n)
    report = {
        "ran_at": datetime.now().isoformat(),
        "cases": n, "errors": errors, "error_rate": round(error_rate, 3),
        "intent_total": intent_total,
        "intent_acc": round(intent_acc, 3),
        "date_acc": round(date_acc, 3) if date_acc is not None else None,
        "booking_acc": round(booking_acc, 3) if booking_acc is not None else None,
        "leaks": leaks,
        "thresholds": {"intent": args.min_intent, "booking": args.min_booking,
                       "date": args.min_date, "max_error_rate": args.max_error_rate},
        "failures": failures[:40],
    }
    out = Path(os.getenv("EVAL_REPORT", "eval_report.json"))
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n" + "=" * 52)
    print(f"EVAL LLM THẬT: {n} câu | intent {intent_acc:.0%} ({intent_ok}/{intent_total})"
          + (f" | date {date_ok}/{date_total}" if date_total else "")
          + (f" | booking {booking_ok}/{booking_total}" if booking_total else "")
          + f" | leak {leaks} | lỗi gọi {errors} ({error_rate:.0%})")
    print(f"Report: {out}")
    print("=" * 52)

    # ── GATE: đỏ nếu BẤT KỲ trục nào tụt (trước đây chỉ leak + intent gate → chốt
    #    đơn/bóc ngày regress về 0% vẫn báo xanh; run hỏng API cũng xanh giả) ──
    fail = False
    if leaks:
        print("❌ Reply lộ <analysis>/JSON thô — lỗi nghiêm trọng với khách thật.")
        fail = True
    if error_rate > args.max_error_rate:
        print(f"❌ tỉ lệ lỗi gọi {error_rate:.0%} > {args.max_error_rate:.0%} — eval KHÔNG "
              "kết luận được (API/model trục trặc), coi là ĐỎ thay vì 'xanh giả'.")
        fail = True
    if intent_acc < args.min_intent:
        print(f"❌ intent {intent_acc:.0%} < ngưỡng {args.min_intent:.0%} — prompt/model drift.")
        fail = True
    if booking_acc is not None and booking_acc < args.min_booking:
        print(f"❌ booking {booking_acc:.0%} < ngưỡng {args.min_booking:.0%} — bỏ SÓT chốt đơn "
              "(mất doanh thu), xem failures.")
        fail = True
    if date_acc is not None and date_acc < args.min_date:
        print(f"❌ date {date_acc:.0%} < ngưỡng {args.min_date:.0%} — bóc ngày sai (đặt nhầm lịch).")
        fail = True
    if fail:
        return 1
    print("✅ Trên ngưỡng an toàn mọi trục (intent + booking + date + leak + error-rate).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
