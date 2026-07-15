"""
HỒ SƠ NGÀNH (industry pack) — để "Dạy AI" hiểu MỌI ngành nghề:
  - detect(text)          : đoán ngành từ dữ liệu shop (keyword, 0 lượt AI; mơ hồ → AI 1 lượt rẻ)
  - checklist(key)        : các thông tin SỐNG CÒN ngành đó phải có → soi GAPS lúc sinh não
  - test_questions(key)   : bộ câu khách hay hỏi nhất → chấm điểm não (health check)

Thêm ngành mới = thêm 1 entry INDUSTRIES — không đụng code nơi khác.
Ngành lưu ở users.industry (theo workspace chủ shop), detect lại mỗi lần dạy.
"""

import re
import unicodedata

# key → {label, hints (từ khoá KHÔNG DẤU nhận diện), checklist, test_questions}
INDUSTRIES = {
    "homestay": {
        "label": "Homestay / Khách sạn",
        "hints": ["homestay", "khach san", "phong nghi", "checkin", "check in", "dat phong",
                  "qua dem", "view", "can ho", "villa", "staycation"],
        "checklist": [
            "Giá từng loại phòng (ngày thường / cuối tuần / lễ)",
            "Giờ nhận phòng (check-in) và trả phòng (check-out); nhận sớm/trả muộn có phụ thu không",
            "Chính sách đặt cọc & hoàn/hủy khi khách đổi ý",
            "Tiện ích trong phòng (máy lạnh, bếp, máy giặt, bồn tắm...) và tiện ích chung (gửi xe, thang máy)",
            "Có nhận thú cưng / trẻ em / thêm người (phụ thu bao nhiêu) không",
            "Địa chỉ chính xác + hướng dẫn đường đi / chỗ gửi xe",
            "Giấy tờ cần khi nhận phòng (CCCD?)",
        ],
        "test_questions": [
            "phòng rẻ nhất giá nhiêu vậy", "tối nay còn phòng không", "mấy giờ nhận phòng",
            "checkout trễ 1 tiếng được không", "đặt cọc bao nhiêu, hủy có hoàn không",
            "phòng có bếp nấu ăn không", "cho mang chó mèo theo không", "ở 3 người phụ thu nhiêu",
            "chỗ mình có gửi xe ô tô không", "địa chỉ ở đâu", "cần mang giấy tờ gì không",
            "cuối tuần giá có tăng không", "xin ảnh phòng", "gần chỗ mình có gì ăn không",
        ],
    },
    "spa": {
        "label": "Spa / Salon / Nail",
        "hints": ["spa", "massage", "goi dau", "nail", "toc", "salon", "trieu chung", "da mat",
                  "triet long", "phun xam", "duong da", "lam dep", "cat toc", "uon", "nhuom"],
        "checklist": [
            "Bảng giá từng dịch vụ (và combo nếu có)",
            "Thời lượng mỗi dịch vụ; có cần đặt lịch trước không, trước bao lâu",
            "Có nhận khách nam / khách vãng lai không",
            "Giờ mở cửa, ngày nghỉ",
            "Chính sách hủy/dời lịch hẹn; đến trễ xử lý sao",
            "Địa chỉ + chỗ gửi xe",
            "Thẻ liệu trình / gói tháng: giá, thời hạn, chuyển nhượng được không",
        ],
        "test_questions": [
            "gội đầu bao nhiêu tiền", "massage body 90 phút giá nhiêu", "chiều nay còn slot không",
            "có cần đặt lịch trước không", "bên mình nhận khách nam không", "mấy giờ đóng cửa",
            "lỡ bận dời lịch được không", "làm nail bộ này bao lâu", "có combo nào rẻ hơn không",
            "địa chỉ ở đâu, có chỗ gửi xe máy không", "mua thẻ liệu trình có giảm không",
            "đến trễ 15 phút có sao không", "chủ nhật có mở không", "thanh toán chuyển khoản được không",
        ],
    },
    "fnb": {
        "label": "Quán ăn / Cafe / Trà sữa",
        "hints": ["quan an", "cafe", "ca phe", "tra sua", "menu", "mon", "com", "bun", "pho",
                  "do uong", "nuoc ep", "banh", "ship do an", "giao do an", "dat ban"],
        "checklist": [
            "Menu + giá từng món / size; món đặc trưng (best-seller)",
            "Giờ mở cửa, giờ nghỉ trưa (nếu có), ngày nghỉ",
            "Có ship không: khu vực, phí ship, đơn tối thiểu, thời gian giao",
            "Có nhận đặt bàn / đặt tiệc / số lượng lớn không, cần báo trước bao lâu",
            "Địa chỉ + chỗ gửi xe; có chỗ ngồi nhóm đông không",
            "Món chay / dị ứng / tuỳ chỉnh (ít đường, ít đá...) đáp ứng được không",
        ],
        "test_questions": [
            "menu có gì ngon", "món này giá nhiêu", "ship về khu X được không phí nhiêu",
            "mấy giờ mở cửa", "đặt bàn 10 người tối nay được không", "có món chay không",
            "trà sữa size L bao nhiêu", "đơn tối thiểu bao nhiêu mới ship", "quán có chỗ gửi ô tô không",
            "làm ít đường được không", "giao trong bao lâu", "địa chỉ quán ở đâu",
            "có bán mang về không", "ngày lễ có mở cửa không",
        ],
    },
    "fashion": {
        "label": "Shop thời trang / Phụ kiện",
        "hints": ["quan ao", "thoi trang", "size", "ao", "vay", "giay", "tui", "phu kien",
                  "freesize", "form", "chat vai", "dam", "so mi"],
        "checklist": [
            "Bảng size chi tiết (chiều cao/cân nặng mặc size nào); form rộng hay ôm",
            "Giá từng mẫu; có sẵn hàng hay order (order chờ bao lâu)",
            "Phí ship, thời gian giao từng khu vực; có ship COD / cho kiểm hàng không",
            "Chính sách đổi/trả: điều kiện, trong bao nhiêu ngày, ai chịu ship",
            "Chất liệu, cách giặt/bảo quản các mẫu chính",
            "Có cửa hàng thử đồ trực tiếp không, địa chỉ",
        ],
        "test_questions": [
            "mẫu này còn size M không", "cao 1m6 55kg mặc size gì", "bao nhiêu tiền vậy shop",
            "ship COD được không", "cho kiểm hàng trước khi nhận không", "mặc không vừa đổi được không",
            "đổi hàng ai chịu phí ship", "vải này có nhăn không", "bao lâu nhận được hàng",
            "có cửa hàng thử trực tiếp không", "hàng có sẵn hay order", "mẫu này còn màu nào",
            "giặt máy được không", "mua 2 cái có giảm không",
        ],
    },
    "cosmetics": {
        "label": "Mỹ phẩm / Skincare",
        "hints": ["my pham", "skincare", "serum", "kem chong nang", "toner", "son", "trang diem",
                  "da dau", "da kho", "mun", "duong am", "chinh hang"],
        "checklist": [
            "Giá + dung tích từng sản phẩm; hạn dùng",
            "Cam kết chính hãng: nguồn nhập, bill/tem phụ, chính sách nếu phát hiện fake",
            "Tư vấn theo loại da (dầu/khô/nhạy cảm/mụn) — sản phẩm nào cho da nào",
            "Phí ship, COD, kiểm hàng; đổi/trả khi lỗi/dị ứng",
            "Cách dùng / thứ tự các bước cho sản phẩm chính",
        ],
        "test_questions": [
            "da dầu mụn nên dùng gì", "serum này giá nhiêu", "hàng có chính hãng không",
            "có bill mua hàng không", "dùng bị kích ứng đổi được không", "ship COD không",
            "kem này dùng sáng hay tối", "da nhạy cảm dùng được không", "hạn sử dụng còn dài không",
            "mua combo có giảm giá không", "bao lâu nhận hàng", "sản phẩm này dùng sao",
        ],
    },
    "fitness": {
        "label": "Gym / Yoga / Fitness",
        "hints": ["gym", "yoga", "fitness", "pt ", "hoi vien", "tap luyen", "the hinh",
                  "goi tap", "lop hoc", "huan luyen vien"],
        "checklist": [
            "Giá các gói (tháng/quý/năm; theo lớp/PT); phí ghi danh",
            "Lịch lớp / giờ mở cửa; có lớp cho người mới không",
            "PT riêng: giá, đặt lịch thế nào",
            "Chính sách bảo lưu / chuyển nhượng gói",
            "Tiện ích: tủ đồ, tắm, giữ xe; địa chỉ",
            "Có buổi tập thử miễn phí không",
        ],
        "test_questions": [
            "gói tháng bao nhiêu tiền", "có được tập thử không", "lịch lớp yoga thế nào",
            "thuê PT riêng giá nhiêu", "bận đi công tác bảo lưu được không", "mấy giờ mở cửa",
            "có tủ để đồ với chỗ tắm không", "người mới chưa tập bao giờ có lớp nào hợp",
            "gói năm có trả góp không", "chuyển gói cho bạn được không", "địa chỉ phòng tập ở đâu",
        ],
    },
    "education": {
        "label": "Trung tâm / Lớp học",
        "hints": ["khoa hoc", "lop hoc", "trung tam", "hoc phi", "giao vien", "tieng anh",
                  "luyen thi", "hoc vien", "buoi hoc", "ielts", "toeic"],
        "checklist": [
            "Học phí từng khoá/lớp; sĩ số; số buổi và thời lượng",
            "Lịch khai giảng; lịch học các lớp",
            "Trình độ đầu vào — có kiểm tra xếp lớp / học thử không",
            "Giáo viên (Việt/bản ngữ), giáo trình, cam kết đầu ra (nếu có)",
            "Chính sách bảo lưu / hoàn phí khi nghỉ giữa chừng",
            "Địa chỉ / học online được không",
        ],
        "test_questions": [
            "học phí khoá này bao nhiêu", "khi nào khai giảng lớp mới", "có học thử không",
            "mất gốc học được không", "1 lớp bao nhiêu học viên", "giáo viên người Việt hay bản ngữ",
            "học nửa chừng bận thì bảo lưu được không", "có cam kết đầu ra không",
            "lịch học tối có không", "học online được không", "địa chỉ trung tâm ở đâu",
        ],
    },
    "retail": {
        "label": "Bán lẻ / Online khác",
        "hints": ["ban hang", "san pham", "don hang", "si le", "kho hang", "order"],
        "checklist": [
            "Danh mục sản phẩm + giá; hàng có sẵn hay order",
            "Phí ship / thời gian giao / COD / kiểm hàng",
            "Chính sách đổi trả, bảo hành",
            "Giá sỉ (mua nhiều) nếu có",
            "Cách thanh toán; địa chỉ cửa hàng (nếu có)",
        ],
        "test_questions": [
            "sản phẩm này còn hàng không", "giá bao nhiêu vậy", "ship bao lâu tới",
            "COD được không", "hàng lỗi đổi thế nào", "bảo hành bao lâu",
            "mua sỉ có giá tốt hơn không", "thanh toán kiểu gì", "có cửa hàng trực tiếp không",
        ],
    },
}

DEFAULT_KEY = "retail"


def _norm(s: str) -> str:
    s = (s or "").lower().replace("đ", "d")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def detect_by_keywords(text: str) -> str | None:
    """Đoán ngành bằng đếm keyword không dấu — 0 lượt AI, đủ đúng khi dữ liệu rõ.
    Trả key ngành, hoặc None khi mơ hồ (điểm thấp/2 ngành sát nhau)."""
    tn = _norm(text)[:60_000]
    scores = {}
    for key, ind in INDUSTRIES.items():
        s = 0
        for h in ind["hints"]:
            s += len(re.findall(re.escape(h), tn))
        scores[key] = s
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_key, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if top >= 3 and top >= second * 2:   # thắng rõ ràng mới tin
        return top_key
    return None


def detect(text: str, model_key: str = None, owner: str = None) -> str:
    """Nhận diện ngành: keyword trước (miễn phí), mơ hồ → hỏi AI 1 lượt rẻ.
    Luôn trả 1 key hợp lệ (mặc định 'retail')."""
    k = detect_by_keywords(text)
    if k:
        return k
    try:
        from app.core.claude_ai import _call_ai
        keys = ", ".join(INDUSTRIES.keys())
        raw = _call_ai([
            {"role": "system", "content":
                f"Phân loại ngành của shop từ dữ liệu. Trả về DUY NHẤT 1 từ trong: {keys}"},
            {"role": "user", "content": (text or "")[:6_000]},
        ], owner=owner)
        k = _norm(raw or "").strip().split()[0] if raw else ""
        if k in INDUSTRIES:
            return k
    except Exception:
        pass
    return DEFAULT_KEY


def label(key: str) -> str:
    return INDUSTRIES.get(key, INDUSTRIES[DEFAULT_KEY])["label"]


def checklist(key: str) -> list:
    return INDUSTRIES.get(key, INDUSTRIES[DEFAULT_KEY])["checklist"]


def test_questions(key: str) -> list:
    return INDUSTRIES.get(key, INDUSTRIES[DEFAULT_KEY])["test_questions"]


def checklist_block(key: str) -> str:
    """Block nhét vào meta-prompt/kiểm phủ: các mục ngành này BẮT BUỘC phải phủ."""
    items = "\n".join(f"- {c}" for c in checklist(key))
    return f"CHECKLIST NGÀNH {label(key).upper()} (thông tin khách chắc chắn sẽ hỏi):\n{items}"
