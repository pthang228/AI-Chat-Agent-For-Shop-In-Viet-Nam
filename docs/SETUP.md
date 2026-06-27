# Hướng dẫn cài đặt — Homestay Bot đa kênh

Bot tư vấn đặt phòng tự động, chạy 3 kênh: **Zalo · Messenger/Instagram · Telegram**.
Dữ liệu phòng/giá/lịch lấy từ **Google Sheets**; khi khách chốt phòng bot **báo + gọi điện cho chủ**.
Quản lý tất cả trong **dashboard web** (React).

> Kiến trúc chi tiết: xem [ARCHITECTURE.md](ARCHITECTURE.md).

---

## BƯỚC 0 — Cài môi trường

```powershell
pip install -r requirements.txt        # Python (backend)
cd zalo-node && npm install && cd ..    # Node (kênh Zalo QR)
cd web-ui   && npm install && cd ..     # React (dashboard)
```
Cần: **Python 3.12+**, **Node.js**. Kênh Meta cần thêm **ngrok** (URL public cho webhook).

---

## BƯỚC 1 — File `.env`

Copy `.env.example` → `.env` rồi điền. Các khoá chính:

```ini
# ── LLM (cần ít nhất 1) ──
DEEPSEEK_API_KEY=...           # chính
GROQ_API_KEY=...               # dự phòng

# ── Google Sheets (lịch/giá) ──
HARU_SHEET_ID=...
MOCHI_SHEET_ID=...
# + file google_credentials.json (xem BƯỚC 2)

# ── Zalo (kênh QR qua Node) ──
OWNER_GROUP_ID=...             # nhóm Zalo nhận báo (chọn trong web)

# ── Meta (Messenger + Instagram) ──
FB_APP_ID=...
FB_APP_SECRET=...
FB_VERIFY_TOKEN=haru_verify_token
FB_ENABLE_IG=true
NGROK_DOMAIN=...               # domain ngrok tĩnh (free)
NGROK_AUTHTOKEN=...

# ── Telegram (bot + gọi điện) ──
TELEGRAM_OWNER_SETUP_CODE=chunha     # mã chủ gõ /start <mã> để tự đăng ký
TELEGRAM_API_ID=...                  # đăng ký ở my.telegram.org (BƯỚC 5)
TELEGRAM_API_HASH=...
TELEGRAM_TARGET_ID=...               # (tuỳ chọn) ID chủ nhận gọi cho bản .env 1-bot
```

> Giữ kín `.env` — đừng commit lên git.

---

## BƯỚC 2 — Google Sheets

1. Tạo project ở https://console.cloud.google.com → bật **Google Sheets API** + **Google Drive API**.
2. **Service Account → Keys → Add key → JSON** → tải về, đổi tên `google_credentials.json`, để ở gốc dự án.
3. Mở file đó lấy email `...@...iam.gserviceaccount.com` → **Share** Google Sheet cho email này (quyền Viewer).
4. Lấy **Sheet ID** từ URL (`docs.google.com/spreadsheets/d/<SHEET_ID>/edit`) → dán vào `.env`.

Sheet lịch: hàng 1 = tên phòng (gộp ô), hàng 2 = ca giờ, hàng 3+ = dữ liệu (cột B = ngày, `dd/mm/yyyy`).
Tab đặt theo tháng (vd "Lịch tháng 6/2026"). Ảnh phòng để ở `media/rooms_photos/<số phòng>/`, bảng giá ở `media/price_photos/`.

---

## BƯỚC 3 — Chạy

**Nhanh nhất:** double-click `start-all.bat` (mở Zalo Node 4000 · Brain 5005 · Meta 5006 · Telegram 5007 · Web 5173)
→ mở http://localhost:5173. Chạy ẩn: `start-silent.vbs`. Tắt: `stop-all.bat`.

**Chạy tay từng phần (từ gốc dự án):**
```powershell
cd zalo-node; npm start          # 4000 — Zalo QR + nhận/gửi
python -m app.main_node          # 5005 — não bộ Zalo
python scripts/run_meta.py       # 5006 — Messenger/Instagram + ngrok
python -m app.main_telegram      # 5007 — Telegram (long-poll, không cần tunnel)
cd web-ui; npm run dev           # 5173 — dashboard
```
> Web (5173) và các server kênh **độc lập**: đóng web KHÔNG tắt bot; nhưng server kênh phải chạy thì bot mới trả lời.
> Sau khi sửa `.env`/code Python phải **restart** server kênh (Flask/Node không tự nạp lại).

---

## BƯỚC 4 — Kết nối từng kênh trong web

Mở dashboard → tạo app cho từng kênh → tab **Kết nối** đã có **hướng dẫn từng bước ngay trên giao diện**:

- **Zalo:** quét QR bằng app Zalo → chọn nhóm nhận báo.
- **Messenger/Instagram:** bấm **Đăng nhập với Facebook** → chọn Page homestay. (Khách không cần đụng trang
  lập trình Facebook; vendor lo app + webhook 1 lần.)
- **Telegram (3 bước):** ① dán **token bot** (@BotFather) → Kết nối; ② **Đăng ký chủ** (bấm Start / gõ `/chunha`);
  ③ **📞 Đăng nhập acc gọi** → quét QR bằng tài khoản dùng để gọi cho chủ.

---

## BƯỚC 5 — Telegram: lấy `api_id` / `api_hash` (cho việc gọi điện)

Acc gọi (Telethon) cần app riêng của bạn:

1. Vào https://my.telegram.org → đăng nhập bằng SĐT → **API development tools**.
2. Tạo app (title/short name bất kỳ, platform **Other**) → copy **App api_id** (số) và **App api_hash** (32 ký tự).
3. Dán vào `.env` (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`) → restart `python -m app.main_telegram`.

> Fallback creds Telegram Desktop chỉ để chạy thử — bán đa khách phải dùng creds riêng kẻo bị giới hạn/ban.
> `caller_session` lưu trong `data/telegram_bots.json` = toàn quyền acc khách → cần mã hoá trước khi bán thật.

---

## Cách chủ ngừng bị gọi

Khi khách chốt phòng / đòi gặp người, bot **nhắn + gọi** chủ. **Bắt máy** là chuỗi gọi dừng ngay;
nếu không nghe, máy gọi lại mỗi **3 phút**, tối đa **10 lần** rồi tự dừng.

---

## Xử lý sự cố

| Hiện tượng | Nguyên nhân / Cách xử lý |
|---|---|
| Web hiện "Chưa kết nối máy chủ (cổng 5005/5006/5007)" | Server kênh đó chưa chạy → chạy lệnh tương ứng ở BƯỚC 3 |
| Bot không trả lời | Server kênh tắt, hoặc bot bị tắt toàn cục (nút trên card), hoặc khách đang ở chế độ "chủ xử lý" |
| Telegram không gọi được chủ | Chưa đăng nhập acc gọi (QR), hoặc chưa đăng ký chủ, hoặc `TELEGRAM_API_ID/HASH` sai → xem `bot_telegram.log` |
| Meta: tin không về | Webhook chưa khai đúng URL `<ngrok>/fb/webhook` + verify token; app chưa ở chế độ Live |
| `Lỗi đọc lịch phòng` | Sheet chưa share cho service account, hoặc sai `*_SHEET_ID` |
| Không gửi được ảnh phòng | Sai thư mục `media/rooms_photos/<số phòng>/` |

**Log:** `bot_telegram.log` · `bot_meta.log` · `bot.log` (Zalo). Chạy ẩn thì log ở `data/*.out.log`.
