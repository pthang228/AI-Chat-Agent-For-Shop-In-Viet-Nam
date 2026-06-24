#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_sheets.py — Kiểm tra logic đọc/parse Google Sheets (không cần kết nối thật).

Test các hàm trong sheets.py với mock data giả lập cấu trúc sheet thực tế:
  Hàng 1: Tên phòng (ô gộp)
  Hàng 2: Ca giờ
  Hàng 3+: Thứ | Ngày | Trạng thái các ca

Usage: python -X utf8 test_sheets.py
"""

import sys, re, os
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta, date, time as dtime

# ─── Mock deps trước import ─────────────────────────────────────────────
sys.modules.update({
    'gspread':                      MagicMock(),
    'google':                       MagicMock(),
    'google.oauth2':                MagicMock(),
    'google.oauth2.service_account': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
sys.path.insert(0, '.')

from app.core.sheets import (
    _parse_slot_times,
    _parse_column_map,
    _open_tab,
    _query_sheet,
    _dates_in_range,
    get_available_slots,
    format_availability_for_ai,
)

# ─── Helpers ─────────────────────────────────────────────────────────────
PASS = FAIL = 0
FAILURES: list[tuple[str, str]] = []

def check(cond: bool, name: str, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append((name, detail))
        print(f"  ✗ FAIL  [{name}] {detail}")

def section(title: str):
    print(f"\n{'─'*65}")
    print(f"  {title}")
    print(f"{'─'*65}")

# ─── Mock worksheet factory ──────────────────────────────────────────────
def _make_ws(title: str, rows: list[list[str]]):
    ws = MagicMock()
    ws.title = title
    ws.get_all_values.return_value = rows
    return ws

def _make_spreadsheet(worksheets: list):
    ss = MagicMock()
    ss.worksheets.return_value = worksheets
    return ss

# ─── Cấu trúc sheet mẫu ──────────────────────────────────────────────────
# Hàng 1: Thứ | Ngày | Phòng 201 (3 ô) | Phòng 202 (3 ô)
# Hàng 2:  -  |  -   | Ca1 | Ca2 | Ca3  | Ca1 | Ca2 | Ca3
ROOM_ROW = [
    "", "",         # Thứ, Ngày
    "Phòng 201", "", "",   # 3 ca phòng 201
    "Phòng 202", "", "",   # 3 ca phòng 202
    "Phòng 301", "",       # 2 ca phòng 301
]
SLOT_ROW = [
    "", "",
    "12h-16h", "16h30-20h30", "21h-10h30",   # ca phòng 201
    "12h-16h", "16h30-20h30", "21h-10h30",   # ca phòng 202
    "16h30-20h30", "21h-10h30",              # ca phòng 301
]

def _data_row(weekday: str, date_str: str, *statuses):
    """Tạo hàng dữ liệu. statuses điền vào từ cột 2 trở đi."""
    row = [weekday, date_str] + list(statuses)
    # Pad đến 10 cột
    while len(row) < 10:
        row.append("Trống")
    return row


# ════════════════════════════════════════════════════════════════
# A. _parse_slot_times
# ════════════════════════════════════════════════════════════════
section("A. _parse_slot_times — parse chuỗi ca giờ")

cases_slot = [
    ("12h-16h",      dtime(12,0),  dtime(16,0),  "ca trưa thường"),
    ("16h30-20h30",  dtime(16,30), dtime(20,30), "ca chiều"),
    ("21h-10h30",    dtime(21,0),  dtime(10,30), "ca qua đêm"),
    ("8h-12h",       dtime(8,0),   dtime(12,0),  "ca sáng"),
    ("21h30-11h",    dtime(21,30), dtime(11,0),  "ca đêm muộn"),
    ("6h–18h",       dtime(6,0),   dtime(18,0),  "dấu gạch ngang en-dash"),
    ("9h - 13h",     dtime(9,0),   dtime(13,0),  "có khoảng trắng"),
]
for slot_str, exp_start, exp_end, note in cases_slot:
    s, e = _parse_slot_times(slot_str)
    check(s == exp_start and e == exp_end,
          f"A_{note}", f"'{slot_str}' → expected ({exp_start},{exp_end}), got ({s},{e})")

# Chuỗi không hợp lệ
s, e = _parse_slot_times("không có giờ")
check(s is None and e is None, "A_invalid", "chuỗi không hợp lệ → (None, None)")

s, e = _parse_slot_times("")
check(s is None and e is None, "A_empty", "chuỗi rỗng → (None, None)")


# ════════════════════════════════════════════════════════════════
# B. _parse_column_map
# ════════════════════════════════════════════════════════════════
section("B. _parse_column_map — ánh xạ cột → (phòng, ca)")

col_map = _parse_column_map(ROOM_ROW, SLOT_ROW)
# Kỳ vọng: cột 2→(201, 12h-16h), 3→(201, 16h30-20h30), 4→(201, 21h-10h30),
#           5→(202, 12h-16h), ... 8→(301, 16h30-20h30), 9→(301, 21h-10h30)
check(2 in col_map, "B_col2_exists", "cột 2 phải có trong col_map")
check(col_map.get(2) == ("Phòng 201", "12h-16h"),
      "B_col2_value", f"cột 2 = {col_map.get(2)}")
check(col_map.get(4) == ("Phòng 201", "21h-10h30"),
      "B_col4_overnight", f"cột 4 = {col_map.get(4)}")
check(col_map.get(5) == ("Phòng 202", "12h-16h"),
      "B_col5_room202", f"cột 5 = {col_map.get(5)}")
check(col_map.get(8) == ("Phòng 301", "16h30-20h30"),
      "B_col8_room301", f"cột 8 = {col_map.get(8)}")
# Cột 0, 1 (Thứ/Ngày) không được có
check(0 not in col_map and 1 not in col_map,
      "B_skip_weekday_date", "cột 0 và 1 không được map")

# Test ô gộp — khi row1 chỉ có tên phòng ở ô đầu, các ô sau rỗng
row1_merged = ["", "", "Phòng 111", "", "", "", "Phòng 112", "", ""]
row2_merged = ["", "", "12h-16h", "16h30-20h30", "21h-10h30", "12h-16h", "16h30-20h30", "21h-10h30", ""]
cm_merged = _parse_column_map(row1_merged, row2_merged)
check(cm_merged.get(2) == ("Phòng 111", "12h-16h"),    "B_merged_c2", "ô gộp: cột đầu")
check(cm_merged.get(3) == ("Phòng 111", "16h30-20h30"), "B_merged_c3", "ô gộp: cột kế tiếp vẫn là phòng 111")
check(cm_merged.get(4) == ("Phòng 111", "21h-10h30"),   "B_merged_c4", "ô gộp: cột 3 cùng phòng")
check(cm_merged.get(6) == ("Phòng 112", "16h30-20h30"), "B_merged_c6", "phòng 112")


# ════════════════════════════════════════════════════════════════
# C. _open_tab — tìm worksheet theo tháng/năm
# ════════════════════════════════════════════════════════════════
section("C. _open_tab — tìm tab theo tháng/năm (chịu được typo)")

def _test_open_tab(tab_titles: list[str], year: int, month: int) -> str | None:
    ws_list = [_make_ws(t, []) for t in tab_titles]
    ss = _make_spreadsheet(ws_list)
    result = _open_tab(ss, year, month)
    return result.title if result else None

# Tên tab chuẩn
check(_test_open_tab(["Lịch tháng 5/2026", "Lịch tháng 6/2026"], 2026, 5) == "Lịch tháng 5/2026",
      "C_exact_match", "tab chính xác")

# Typo năm: "5/206" thay vì "5/2026" (thiếu 1 số)
check(_test_open_tab(["Lịch tháng 5/206"], 2026, 5) == "Lịch tháng 5/206",
      "C_typo_year", "typo năm '206' vẫn tìm được")

# Chỉ có tháng, không có năm
check(_test_open_tab(["Lịch tháng 5"], 2026, 5) == "Lịch tháng 5",
      "C_month_only", "tab chỉ có tháng")

# Nhiều tab, ưu tiên đúng tháng + năm
check(_test_open_tab(["Tháng 4", "Tháng 5/2026", "Tháng 5"], 2026, 5) == "Tháng 5/2026",
      "C_prefer_year_month", "ưu tiên tab có cả tháng lẫn năm")

# Không tìm thấy
check(_test_open_tab(["Lịch tháng 6/2026"], 2026, 5) is None,
      "C_not_found", "không tìm thấy → None")

# Tháng khác nhau
check(_test_open_tab(["Lịch tháng 5/2026", "Lịch tháng 6/2026"], 2026, 6) == "Lịch tháng 6/2026",
      "C_month_6", "tháng 6")


# ════════════════════════════════════════════════════════════════
# D. _dates_in_range
# ════════════════════════════════════════════════════════════════
section("D. _dates_in_range — tạo list ngày từ checkin đến checkout")

def dates_str(checkin, checkout):
    return [d.strftime("%d/%m/%Y") for d in _dates_in_range(checkin, checkout)]

# 1 ngày
r1 = dates_str("23/05/2026", "23/05/2026")
check(r1 == ["23/05/2026"], "D_same_day", f"cùng ngày → [checkin], got {r1}")

# 3 ngày
r3 = dates_str("23/05/2026", "25/05/2026")
check(r3 == ["23/05/2026", "24/05/2026"], "D_two_nights",
      f"2 đêm → 2 ngày (không gồm checkout), got {r3}")

# 1 đêm
r2 = dates_str("23/05/2026", "24/05/2026")
check(r2 == ["23/05/2026"], "D_one_night", f"1 đêm → chỉ ngày checkin, got {r2}")

# checkin > checkout → coi như cùng ngày
r_rev = dates_str("25/05/2026", "23/05/2026")
check(r_rev == ["25/05/2026"], "D_reversed", f"checkout < checkin → [checkin], got {r_rev}")

# Qua tháng
r_cross = dates_str("30/05/2026", "02/06/2026")
check(len(r_cross) == 3, "D_cross_month", f"qua tháng 30/5→1/6 = 3 ngày, got {len(r_cross)}")
check(r_cross[0] == "30/05/2026" and r_cross[-1] == "01/06/2026",
      "D_cross_month_dates", f"ngày đầu-cuối: {r_cross}")


# ════════════════════════════════════════════════════════════════
# E. _query_sheet — query với mock worksheet
# ════════════════════════════════════════════════════════════════
section("E. _query_sheet — đọc ca trống từ mock sheet")

TODAY       = date.today()
TODAY_STR   = TODAY.strftime("%d/%m/%Y")
TOMORROW    = TODAY + timedelta(days=1)
TOMORROW_STR = TOMORROW.strftime("%d/%m/%Y")

def _build_full_rows(rows_data: list[tuple]) -> list[list[str]]:
    """Tạo sheet rows từ list (weekday, date_str, *statuses)."""
    return [ROOM_ROW, SLOT_ROW] + [
        list(r) + ["Trống"] * (10 - len(r)) for r in rows_data
    ]

def _mock_gspread_client(sheet_rows: list):
    ws = _make_ws(f"Lịch tháng {TODAY.month}/{TODAY.year}", sheet_rows)
    ss = _make_spreadsheet([ws])
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = ss
    return mock_client

def _run_query(rows_data, dates=None, homestay="TestHome", sheet_id="fake_id"):
    """Helper: run _query_sheet với mock."""
    if dates is None:
        dates = [TODAY]
    sheet_rows = _build_full_rows(rows_data)
    mock_client = _mock_gspread_client(sheet_rows)
    with patch('app.core.sheets._get_client', return_value=mock_client):
        dates_found = set()
        result = _query_sheet(sheet_id, homestay, dates, dates_found)
        return result, dates_found

# ── E1: Ngày có ca trống ──────────────────────────────────────
slots_E1, found_E1 = _run_query([
    ("Thứ 6", TODAY_STR, "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống"),
])
check(len(slots_E1) > 0, "E1_has_slots", f"ngày có ca trống → slots không rỗng, got {len(slots_E1)}")
check(TODAY in found_E1, "E1_dates_found", "ngày phải có trong dates_found")
rooms_E1 = {s["phong"] for s in slots_E1}
check("Phòng 201" in rooms_E1, "E1_room201", f"Phòng 201 phải có, got {rooms_E1}")

# ── E2: Ngày bị đặt hết ──────────────────────────────────────
slots_E2, found_E2 = _run_query([
    ("Thứ 6", TODAY_STR, "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt"),
])
check(len(slots_E2) == 0, "E2_all_booked", "ngày đặt hết → slots rỗng")
check(TODAY in found_E2, "E2_dates_found", "ngày vẫn phải có trong dates_found dù hết")

# ── E3: Ngày không có trong sheet ────────────────────────────
other_date = TODAY + timedelta(days=10)
slots_E3, found_E3 = _run_query(
    [("Thứ 6", TODAY_STR, "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống")],
    dates=[other_date]
)
check(len(slots_E3) == 0, "E3_date_not_in_sheet", "ngày không có trong sheet → rỗng")
check(other_date not in found_E3, "E3_not_in_found",
      "ngày không có trong sheet → không có trong dates_found")

# ── E4: Mixed — 1 ngày còn 1 ngày hết ─────────────────────────
slots_E4, found_E4 = _run_query([
    ("Thứ 6", TODAY_STR,     "Trống", "Đã đặt", "Trống",  "Trống", "Trống", "Trống", "Trống", "Trống"),
    ("Thứ 7", TOMORROW_STR,  "Đã đặt","Đã đặt", "Đã đặt", "Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt"),
], dates=[TODAY, TOMORROW])
check(TODAY in found_E4 and TOMORROW in found_E4, "E4_both_dates_found",
      "cả 2 ngày phải có trong dates_found")
slots_today_E4 = [s for s in slots_E4 if s["ngay"] == TODAY_STR]
slots_tmr_E4   = [s for s in slots_E4 if s["ngay"] == TOMORROW_STR]
check(len(slots_today_E4) > 0, "E4_today_has_slots", "hôm nay còn trống")
check(len(slots_tmr_E4) == 0,  "E4_tomorrow_full",   "ngày mai hết phòng → không có slots")

# ── E5: Định dạng ngày linh hoạt d/m/yyyy (không có số 0 đầu) ─
today_no_pad = f"{TODAY.day}/{TODAY.month}/{TODAY.year}"  # "23/5/2026" thay vì "23/05/2026"
slots_E5, found_E5 = _run_query([
    ("Thứ 6", today_no_pad, "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống", "Trống"),
])
check(len(slots_E5) > 0, "E5_no_pad_date",
      f"ngày không có số 0 đầu ('{today_no_pad}') vẫn phải match")

# ── E6: Trạng thái "trong" (thiếu dấu) vẫn coi là trống ──────
slots_E6, _ = _run_query([
    ("Thứ 6", TODAY_STR, "trong", "free", "Trống", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt", "Đã đặt"),
])
check(any(s["ca"] in ("12h-16h","16h30-20h30","21h-10h30") for s in slots_E6),
      "E6_trang_thai_variants", "'trong' và 'free' phải được coi là trống")

# ── E7: Hôm nay — lọc ca đã qua ──────────────────────────────
# Tạo ca kết thúc 1 giờ trước (đã xong)
now_minus_2h = datetime.now() - timedelta(hours=2)
past_slot    = f"{now_minus_2h.hour}h-{(now_minus_2h + timedelta(hours=1)).hour}h"
# Tạo ca bắt đầu 2 giờ nữa (chưa tới)
now_plus_2h  = datetime.now() + timedelta(hours=2)
future_slot  = f"{now_plus_2h.hour}h-{(now_plus_2h + timedelta(hours=2)).hour}h"

# Build custom sheet với ca đã qua và ca sắp tới
row1_today = ["", "", "Phòng 999", ""]
row2_today = ["", "", past_slot,    future_slot]
data_today = [("Thứ", TODAY_STR, "Trống", "Trống")]
all_rows_today = [row1_today, row2_today] + [list(r) for r in data_today]
ws_today = _make_ws(f"Lịch tháng {TODAY.month}/{TODAY.year}", all_rows_today)
ss_today = _make_spreadsheet([ws_today])
mock_cl_today = MagicMock()
mock_cl_today.open_by_key.return_value = ss_today

with patch('app.core.sheets._get_client', return_value=mock_cl_today):
    df_today = set()
    slots_today = _query_sheet("fake", "TestHome", [TODAY], df_today)

past_slots_today   = [s for s in slots_today if s["ca"] == past_slot]
future_slots_today = [s for s in slots_today if s["ca"] == future_slot]
check(len(past_slots_today) == 0,   "E7_past_slot_filtered",
      f"ca đã xong hôm nay ('{past_slot}') phải bị lọc bỏ")
check(len(future_slots_today) > 0,  "E7_future_slot_shown",
      f"ca sắp tới hôm nay ('{future_slot}') phải hiện")


# ════════════════════════════════════════════════════════════════
# F. format_availability_for_ai — kết quả cuối cho AI
# ════════════════════════════════════════════════════════════════
section("F. format_availability_for_ai — kết quả phân biệt 3 trường hợp")

def _run_format(rows_data, checkin=None, checkout=None):
    checkin  = checkin  or TODAY_STR
    checkout = checkout or TODAY_STR
    sheet_rows = _build_full_rows(rows_data)
    mock_client = _mock_gspread_client(sheet_rows)
    with patch('app.core.sheets._get_client', return_value=mock_client), \
         patch('app.core.sheets.HOMESTAYS', [{"name": "TestHome", "sheet_id": "fake"}]):
        return format_availability_for_ai(checkin, checkout)

# ── F1: Ngày không có trong sheet → [CHUA_CO_LICH] ─────────────
result_F1 = _run_format([])  # Sheet rỗng (chỉ có header)
check("[CHUA_CO_LICH]" in result_F1, "F1_chua_co_lich",
      f"sheet rỗng → [CHUA_CO_LICH], got: {result_F1[:80]}")
check("hết phòng" not in result_F1.lower() and "không có ca" not in result_F1.lower(),
      "F1_not_full_message", "không được nói hết phòng khi chưa có dữ liệu")

# ── F2: Ngày có trong sheet, tất cả đặt → thông báo hết ────────
result_F2 = _run_format([
    ("Thứ 6", TODAY_STR, "Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt"),
])
check("KHÔNG có ca trống" in result_F2 or "NGHIÊM CẤM" in result_F2,
      "F2_all_booked", f"tất cả đặt → thông báo hết, got: {result_F2[:100]}")
check("[CHUA_CO_LICH]" not in result_F2, "F2_not_chua_co", "không được là [CHUA_CO_LICH]")

# ── F3: Có ca trống → danh sách cụ thể ─────────────────────────
result_F3 = _run_format([
    ("Thứ 6", TODAY_STR, "Trống", "Đã đặt", "Trống", "Đã đặt", "Trống", "Trống", "Trống", "Trống"),
])
check("✅" in result_F3 or "còn ca" in result_F3.lower(),
      "F3_has_slots", f"có ca trống → hiện danh sách, got: {result_F3[:150]}")
check("TestHome" in result_F3, "F3_has_homestay", "tên homestay phải có trong kết quả")

# ── F4: Multi-ngày — common slots (chỉ ca trống CẢ khoảng) ─────
# Ngày 1: Phòng 201 ca chiều (16h30-20h30) trống, tối (21h-10h30) đã đặt
# Ngày 2: Phòng 201 ca chiều trống, tối trống
# Kỳ vọng: chỉ ca chiều được liệt (ca chung cả 2 ngày)
rows_F4 = [
    ("Thứ 6", TODAY_STR,     "Đã đặt","Trống","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt"),
    ("Thứ 7", TOMORROW_STR,  "Đã đặt","Trống","Trống", "Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt"),
]
result_F4 = _run_format(rows_F4, checkin=TODAY_STR, checkout=TOMORROW_STR)
# Ca chiều (cột 3 = 16h30-20h30) trống cả 2 ngày → phải có
# Ca tối (cột 4 = 21h-10h30): ngày 1 đặt → không phải common → không hiện
check("16h30-20h30" in result_F4 or "còn ca" in result_F4.lower() or "✅" in result_F4,
      "F4_common_slot_shown", "ca trống chung 2 ngày phải hiện")

# ── F5: Ngày tương lai xa (chưa có tab) → [CHUA_CO_LICH] ───────
future_far = (date.today() + timedelta(days=90)).strftime("%d/%m/%Y")
# Sheet chỉ có tab hiện tháng, không có tab tháng xa
with patch('app.core.sheets._get_client', return_value=MagicMock()) as mc, \
     patch('app.core.sheets.HOMESTAYS', [{"name": "TestHome", "sheet_id": "fake"}]):
    mock_client_far = MagicMock()
    ws_this = _make_ws(f"Lịch tháng {TODAY.month}/{TODAY.year}", [ROOM_ROW, SLOT_ROW])
    mock_client_far.open_by_key.return_value = _make_spreadsheet([ws_this])
    mc.return_value = mock_client_far
    result_F5 = format_availability_for_ai(future_far, future_far)
check("[CHUA_CO_LICH]" in result_F5, "F5_future_no_tab",
      f"ngày xa chưa có tab → [CHUA_CO_LICH], got: {result_F5[:80]}")

# ── F6: date format không có số 0 đầu trong sheet ──────────────
today_no_zero = f"{TODAY.day}/{TODAY.month}/{TODAY.year}"
result_F6 = _run_format([
    ("Thứ 6", today_no_zero, "Trống","Trống","Trống","Trống","Trống","Trống","Trống","Trống"),
])
check("[CHUA_CO_LICH]" not in result_F6,
      "F6_no_zero_date_match", f"ngày không có số 0 đầu phải match được, got: {result_F6[:100]}")


# ════════════════════════════════════════════════════════════════
# G. Multi-homestay — 2 sheets cùng lúc
# ════════════════════════════════════════════════════════════════
section("G. Multi-homestay — kết hợp kết quả 2 sheet")

def _run_multi_format(rows_haru, rows_mochi, checkin=None, checkout=None):
    checkin  = checkin  or TODAY_STR
    checkout = checkout or TODAY_STR

    def make_ss_for(rows_data):
        sheet_rows = _build_full_rows(rows_data)
        ws = _make_ws(f"Lịch tháng {TODAY.month}/{TODAY.year}", sheet_rows)
        ss = _make_spreadsheet([ws])
        client = MagicMock()
        client.open_by_key.return_value = ss
        return client

    call_counter = [0]
    def get_client_side_effect():
        i = call_counter[0] % 2
        call_counter[0] += 1
        return [make_ss_for(rows_haru), make_ss_for(rows_mochi)][i]

    with patch('app.core.sheets._get_client', side_effect=get_client_side_effect), \
         patch('app.core.sheets.HOMESTAYS', [
             {"name": "Haru Staycation", "sheet_id": "haru_id"},
             {"name": "Mochi Home",      "sheet_id": "mochi_id"},
         ]):
        return format_availability_for_ai(checkin, checkout)

# G1: Haru còn phòng, Mochi hết
r_G1 = _run_multi_format(
    rows_haru=[("Thứ 6", TODAY_STR, "Trống","Trống","Trống","Trống","Trống","Trống","Trống","Trống")],
    rows_mochi=[("Thứ 6", TODAY_STR, "Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt","Đã đặt")],
)
check("Haru Staycation" in r_G1, "G1_haru_in_result", "Haru phải có trong kết quả")
# Mochi hết → không được liệt vào ca trống
check("Mochi Home" not in r_G1 or "❌" in r_G1, "G1_mochi_not_available",
      "Mochi hết không được liệt ca trống")

# G2: Cả 2 đều còn
r_G2 = _run_multi_format(
    rows_haru=[("Thứ 6", TODAY_STR, "Trống","Trống","Trống","Trống","Trống","Trống","Trống","Trống")],
    rows_mochi=[("Thứ 6", TODAY_STR, "Trống","Trống","Trống","Trống","Trống","Trống","Trống","Trống")],
)
check("Haru Staycation" in r_G2 and "Mochi Home" in r_G2,
      "G2_both_homestays", "Cả 2 homestay phải hiện khi đều có ca trống")

# G3: Cả 2 không có dữ liệu → [CHUA_CO_LICH]
r_G3 = _run_multi_format(rows_haru=[], rows_mochi=[])
check("[CHUA_CO_LICH]" in r_G3, "G3_both_empty", "Cả 2 sheet rỗng → [CHUA_CO_LICH]")


# ════════════════════════════════════════════════════════════════
# FINAL REPORT
# ════════════════════════════════════════════════════════════════
print(f"\n{'═'*65}")
print(f"  KẾT QUẢ SHEETS TESTS")
print(f"{'═'*65}")
print(f"  ✅ PASS : {PASS:4d} / {PASS+FAIL}")
print(f"  ❌ FAIL : {FAIL:4d} / {PASS+FAIL}")
print(f"\n  📊 Pass rate: {PASS/(PASS+FAIL)*100:.1f}%")

if FAILURES:
    print(f"\n{'─'*65}")
    print("  ❌ CHI TIẾT THẤT BẠI:")
    for name, detail in FAILURES:
        print(f"    • [{name}] {detail}")
else:
    print("\n  🎉 Tất cả tests đều PASS!")

print(f"\n  Nhóm:\n"
      f"    A. _parse_slot_times     | B. _parse_column_map\n"
      f"    C. _open_tab (typo)      | D. _dates_in_range\n"
      f"    E. _query_sheet          | F. format_availability_for_ai\n"
      f"    G. Multi-homestay")
print(f"{'═'*65}\n")

sys.exit(0 if FAIL == 0 else 1)
