"""
Đọc lịch phòng từ 2 Google Sheets (Haru Staycation + Mochi Home).

Cấu trúc sheet thực tế:
  Hàng 1 : Tên phòng (ô gộp, VD: Phòng 201, Phòng 202 ...)
  Hàng 2 : Ca giờ    (VD: 12h-16h, 16h30-20h30, 21h-10h30 ...)
  Hàng 3+: Dữ liệu   (Cột A=Thứ, Cột B=Ngày dd/mm/yyyy, các cột còn lại=Trống/Đã đặt)

Tab theo tháng: "Lịch tháng 5/2026"
"""

import re
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, date, time as dtime
from app.core.config import Config


def _parse_slot_times(slot_str: str):
    """Lấy (giờ_bắt_đầu, giờ_kết_thúc) từ chuỗi ca.
    VD: '16h30-20h30' → (time(16,30), time(20,30))
        '21h-10h30'   → (time(21,0),  time(10,30))  ← ca qua đêm
    """
    m = re.match(r'(\d+)h(\d+)?\s*[-–]\s*(\d+)h(\d+)?', slot_str.strip())
    if m:
        sh = int(m.group(1)); sm = int(m.group(2)) if m.group(2) else 0
        eh = int(m.group(3)); em = int(m.group(4)) if m.group(4) else 0
        return dtime(sh, sm), dtime(eh, em)
    return None, None


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

# Danh sách sheet LEGACY của SHOP GỐC (chủ nền tảng) — cấu hình qua .env.
# Shop khác tự khai sheet riêng trong web (bảng shop_sheets) — xem homestays_for().
HOMESTAYS = [
    {
        "name":     "Haru Staycation",
        "sheet_id": Config.HARU_SHEET_ID,
    },
    {
        "name":     "Mochi Home",
        "sheet_id": Config.MOCHI_SHEET_ID,
    },
]


def extract_sheet_id(link_or_id: str) -> str | None:
    """Bóc sheet ID từ link Google Sheets (hoặc nhận thẳng ID).
    VD: https://docs.google.com/spreadsheets/d/1AbC.../edit#gid=0 → 1AbC..."""
    s = (link_or_id or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{20,}", s):
        return s
    return None


def homestays_for(tenant: str | None) -> list:
    """Danh sách sheet lịch của SHOP sở hữu hội thoại (multi-tenant).
    - Shop gốc (tenant rỗng / chủ nền tảng) → sheet .env legacy + sheet tự khai.
    - Shop khác → CHỈ sheet shop đó tự khai trong web (bảng shop_sheets)."""
    from app.core import tenant as _t
    from app.core.db import get_db
    default = _t.default_owner()
    is_default = (not tenant) or tenant == default
    out = []
    if is_default:
        out += [h for h in HOMESTAYS if h["sheet_id"]]
    try:
        if is_default:
            rows = get_db().query(
                "SELECT name, sheet_id FROM shop_sheets WHERE tenant=? OR tenant='' ORDER BY id",
                (default,))
        else:
            rows = get_db().query(
                "SELECT name, sheet_id FROM shop_sheets WHERE tenant=? ORDER BY id",
                (tenant,))
        out += [{"name": r["name"] or "Chi nhánh", "sheet_id": r["sheet_id"]} for r in rows]
    except Exception as e:
        print(f"[Sheets] lỗi đọc shop_sheets: {e}")
    return out


_client_cache = None    # gspread client tái dùng — google-auth tự refresh token khi hết hạn


def _get_client():
    global _client_cache
    if _client_cache is None:
        creds = Credentials.from_service_account_file(
            Config.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        _client_cache = gspread.authorize(creds)
    return _client_cache


def _open_tab(sheet, year: int, month: int):
    """
    Tìm tab theo tháng — chịu được typo tên tab (vd: '5/206' thay vì '5/2026').
    Ưu tiên tab có chứa cả tháng lẫn năm, nếu không có thì lấy tab chứa tháng.

    Dùng regex (?<!\\d)N(?!\\d) để tránh nhầm:
      tháng 6 ≠ "2026" (vì "6" trong "2026" bị kẹp giữa 2 chữ số)
      tháng 1 ≠ "12" (vì "1" trong "12" bị theo sau bởi chữ số)
    """
    all_ws = sheet.worksheets()
    month_str = str(month)
    year_str  = str(year)

    # Hàm kiểm tra số tháng đứng độc lập (không nằm trong số lớn hơn)
    def _month_in(title: str) -> bool:
        return bool(re.search(rf'(?<!\d){re.escape(month_str)}(?!\d)', title))

    # Ưu tiên: có cả tháng VÀ năm trong tên
    for ws in all_ws:
        if _month_in(ws.title) and year_str in ws.title:
            return ws

    # Fallback: có tháng VÀ phần năm bị rút gọn (vd "206" thay vì "2026")
    for ws in all_ws:
        if _month_in(ws.title) and year_str[-2:] in ws.title:
            return ws

    # Fallback cuối: chỉ có tháng (tab cũ không ghi năm)
    for ws in all_ws:
        if _month_in(ws.title):
            return ws

    return None


def _parse_column_map(row1: list[str], row2: list[str]) -> dict[int, tuple[str, str]]:
    """
    Tạo mapping: chỉ số cột -> (tên phòng, ca giờ)
    Dựa trên hàng 1 (tên phòng gộp ô) và hàng 2 (ca giờ).
    """
    col_map: dict[int, tuple[str, str]] = {}
    current_room = ""
    for i, cell in enumerate(row1):
        if cell.strip():
            current_room = cell.strip()
        if i >= 2 and current_room and row2[i].strip():
            col_map[i] = (current_room, row2[i].strip())
    return col_map


def _query_sheet(sheet_id: str, homestay_name: str,
                 dates: list[date],
                 dates_found: set | None = None) -> list[dict]:
    """
    Đọc một file sheet, trả về danh sách ca trống cho các ngày yêu cầu.
    Kết quả: [{"homestay", "phong", "ca", "ngay"}, ...]
    dates_found: nếu truyền vào, sẽ được cập nhật với các ngày tìm thấy trong sheet
                 (bất kể phòng còn hay hết — để phân biệt "không có row" vs "hết phòng")
    """
    if not sheet_id:
        return []

    try:
        client = _get_client()
        spreadsheet = client.open_by_key(sheet_id)
    except Exception as e:
        print(f"[Sheets] Không mở được sheet {homestay_name}: {e}")
        return []

    # Nhóm ngày theo tháng để mở đúng tab
    months_needed: dict[tuple[int, int], list[date]] = {}
    for d in dates:
        key = (d.year, d.month)
        months_needed.setdefault(key, []).append(d)

    results = []

    for (year, month), month_dates in months_needed.items():
        ws = _open_tab(spreadsheet, year, month)
        if ws is None:
            print(f"[Sheets] Không tìm thấy tab tháng {month}/{year} trong {homestay_name}")
            continue

        all_rows = ws.get_all_values()
        if len(all_rows) < 3:
            continue

        row1 = all_rows[0]   # tên phòng
        row2 = all_rows[1]   # ca giờ
        data = all_rows[2:]  # dữ liệu

        col_map = _parse_column_map(row1, row2)
        print(f"[Sheets] {homestay_name} tab={ws.title} col_map={col_map}")

        # Dùng date object để so sánh, tránh lỗi format "23/5/2026" vs "23/05/2026"
        target_date_set = set(month_dates)

        for row in data:
            if len(row) < 2:
                continue
            ngay_str = row[1].strip()
            # Parse linh hoạt: thử dd/mm/yyyy rồi d/m/yyyy
            row_date = None
            for fmt_try in ("%d/%m/%Y", "%d/%m/%y"):
                try:
                    row_date = datetime.strptime(ngay_str, fmt_try).date()
                    break
                except ValueError:
                    pass
            if row_date is None or row_date not in target_date_set:
                continue
            print(f"[Sheets]   matched row date={ngay_str} raw={row[:6]}")
            # Đánh dấu ngày này ĐÃ CÓ trong sheet (dù phòng còn hay hết)
            if dates_found is not None:
                dates_found.add(row_date)

            today      = date.today()
            now_time   = datetime.now().time()

            for col_idx, (phong, ca) in col_map.items():
                if col_idx >= len(row):
                    continue
                trang_thai = row[col_idx].strip().lower()
                if trang_thai in ("trống", "trong", "", "free"):
                    # Nếu là hôm nay, lọc theo giờ thực tế
                    if row_date == today:
                        start_t, end_t = _parse_slot_times(ca)
                        if start_t and end_t:
                            is_overnight = end_t < start_t  # ca qua đêm (vd 21h-10h30)
                            if is_overnight:
                                # Ca qua đêm: ẩn nếu đã qua giờ kết thúc sáng hôm sau
                                # (vd 10h30 đã qua → ca đêm hôm qua đã xong)
                                # Nhưng nếu chưa tới giờ bắt đầu tối → vẫn hiện
                                if now_time > end_t and now_time < start_t:
                                    pass  # Vẫn hiện — ca bắt đầu tối nay
                                elif now_time > end_t and now_time >= start_t:
                                    pass  # Đang trong ca → hiện
                                # Không ẩn ca qua đêm khi hỏi hôm nay
                            else:
                                # Ca thường: ẩn nếu đã kết thúc hoàn toàn
                                if end_t <= now_time:
                                    print(f"[Sheets]   Bỏ ca đã xong: {phong} {ca} (kết thúc {end_t}, giờ {now_time})")
                                    continue
                    results.append({
                        "homestay": homestay_name,
                        "phong":    phong,
                        "ca":       ca,
                        "ngay":     ngay_str,
                    })

    return results


def _dates_in_range(checkin_str: str, checkout_str: str) -> list[date]:
    """Trả về danh sách ngày từ checkin đến checkout (không bao gồm checkout).
    Nếu checkin == checkout (khách hỏi 1 ngày cụ thể), trả về [checkin]."""
    fmt = "%d/%m/%Y"
    checkin  = datetime.strptime(checkin_str,  fmt).date()
    checkout = datetime.strptime(checkout_str, fmt).date()
    if checkin >= checkout:
        return [checkin]
    result = []
    cur = checkin
    while cur < checkout:
        result.append(cur)
        cur += timedelta(days=1)
    return result


def get_available_slots(checkin_str: str, checkout_str: str,
                        homestays: list | None = None) -> tuple[dict, set]:
    """
    Trả về (summary_dict, dates_found_in_sheet).

    summary_dict: ca trống theo homestay → phòng → ngày → list ca
    dates_found_in_sheet: tập hợp date object của các ngày tìm thấy trong sheet
        (dùng để phân biệt "ngày chưa có trong sheet" vs "ngày có nhưng hết phòng")
    homestays: danh sách sheet của SHOP (None = legacy shop gốc — tương thích cũ)
    """
    try:
        dates = _dates_in_range(checkin_str, checkout_str)
    except ValueError:
        return {}, set()

    summary: dict = {}
    dates_found: set = set()

    for hs in (homestays if homestays is not None else HOMESTAYS):
        slots = _query_sheet(hs["sheet_id"], hs["name"], dates, dates_found)
        if not slots:
            continue

        hs_data: dict = {}
        for slot in slots:
            phong = slot["phong"]
            ca    = slot["ca"]
            ngay  = slot["ngay"]
            hs_data.setdefault(phong, {}).setdefault(ngay, []).append(ca)

        if hs_data:
            summary[hs["name"]] = hs_data

    return summary, dates_found


def format_availability_for_ai(checkin: str, checkout: str,
                               tenant: str | None = None) -> str:
    """
    Tạo đoạn văn bản mô tả lịch trống để bot gửi cho khách.

    Phân biệt 4 trường hợp:
    - [KHONG_CO_SHEET] : SHOP này chưa nối Google Sheet nào → bot không tra được,
                         brain sẽ ghi nhận yêu cầu + báo chủ shop (không bịa lịch)
    - [CHUA_CO_LICH]   : ngày không có trong sheet → chưa có booking, có thể đặt
    - KHÔNG có ca trống: ngày có trong sheet nhưng tất cả đã được đặt
    - Bình thường      : có ca trống cụ thể

    tenant: SHOP sở hữu hội thoại (multi-tenant) — None = legacy shop gốc.
    """
    homestays = homestays_for(tenant)
    if not homestays:
        return "[KHONG_CO_SHEET]\nShop chưa kết nối Google Sheet lịch đặt chỗ nào."

    try:
        queried_dates = set(_dates_in_range(checkin, checkout))
    except ValueError:
        queried_dates = set()

    data, dates_found = get_available_slots(checkin, checkout, homestays=homestays)

    if not data:
        # Không có ca trống nào — phân biệt nguyên nhân
        if not queried_dates.intersection(dates_found):
            # Không tìm thấy row ngày nào trong sheet → ngày tương lai chưa có booking
            return (
                f"[CHUA_CO_LICH]\n"
                f"Ngày {checkin}: chưa có lịch booking nào trong hệ thống — "
                f"các phòng có thể vẫn còn trống, khách có thể đặt được!"
            )
        else:
            # Tìm thấy row nhưng tất cả phòng đều đã đặt → hết phòng thật
            return (
                f"[DỮ LIỆU THỰC TẾ - BẮT BUỘC TUÂN THEO]\n"
                f"Từ {checkin} đến {checkout}: KHÔNG có ca trống nào trong hệ thống.\n"
                f"NGHIÊM CẤM tự liệt kê phòng hoặc ca giờ không có trong dữ liệu này.\n"
                f"Chỉ được thông báo: không còn phòng trống cho ngày đó và đề nghị khách thử ngày khác."
            )

    lines = [f"📅 Lịch ca TRỐNG từ {checkin} đến {checkout}:\n"]

    for homestay_name, rooms in data.items():
        lines.append(f"🏠 {homestay_name}:")
        for phong, ngay_slots in sorted(rooms.items()):
            # Tính các ca trống CHUNG cho tất cả ngày trong khoảng
            # (ca phải trống CẢ khoảng ngày mới tính là đặt được)
            all_dates = list(ngay_slots.keys())
            common_slots = set(ngay_slots[all_dates[0]])
            for d in all_dates[1:]:
                common_slots &= set(ngay_slots[d])

            if common_slots:
                sorted_slots = sorted(common_slots)
                lines.append(f"  ✅ {phong}: còn ca {', '.join(sorted_slots)}")
            else:
                lines.append(f"  ❌ {phong}: không còn ca trống liên tục")

        lines.append("")

    lines.append(
        "Lưu ý: 'ca trống' nghĩa là ca đó trống TOÀN BỘ các ngày trong khoảng khách yêu cầu."
    )
    return "\n".join(lines)
