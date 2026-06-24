# Hướng dẫn cài đặt Zalo Homestay Bot

## Tổng quan
Bot tự động trả lời tin nhắn Zalo cá nhân của bạn bằng Claude AI,
check lịch phòng từ Google Sheets, gửi ảnh phòng trống và thông báo khi khách chốt.

---

## BƯỚC 1 — Cài thư viện Python

Mở PowerShell trong thư mục này và chạy:

```powershell
pip install -r requirements.txt
```

---

## BƯỚC 2 — Lấy Anthropic API Key (Claude)

1. Truy cập: https://console.anthropic.com/settings/keys
2. Đăng ký tài khoản nếu chưa có
3. Nhấn **"Create Key"**
4. Copy key (dạng `sk-ant-...`)
5. Dán vào file `.env` ở mục `ANTHROPIC_API_KEY`

> **Chi phí**: ~$0.003 mỗi cuộc trò chuyện (rất rẻ)

---

## BƯỚC 3 — Cấu hình Google Sheets

### 3a. Tạo Google Cloud Project

1. Vào: https://console.cloud.google.com
2. Tạo project mới (tên bất kỳ)
3. Tìm và bật 2 API:
   - **Google Sheets API**
   - **Google Drive API**

### 3b. Tạo Service Account

1. Vào **IAM & Admin → Service Accounts**
2. Nhấn **"Create Service Account"**
3. Đặt tên bất kỳ → nhấn Done
4. Click vào service account vừa tạo → tab **"Keys"**
5. **Add Key → Create new key → JSON**
6. File JSON sẽ được tải xuống → đổi tên thành `google_credentials.json`
7. Copy file này vào thư mục bot (cùng chỗ với `main.py`)

### 3c. Chia sẻ Google Sheet với Service Account

1. Mở file `google_credentials.json`, tìm email dạng:
   `your-service@your-project.iam.gserviceaccount.com`
2. Mở Google Sheet của bạn
3. Nhấn **Chia sẻ (Share)** → dán email service account → quyền **Viewer**

---

## BƯỚC 4 — Cấu trúc Google Sheets

### Sheet 1: Lịch phòng (tab `Lich_phong`)

| Ngày       | Tên phòng | Trạng thái | Ghi chú |
|------------|-----------|------------|---------|
| 25/05/2026 | Phòng A   | Đã đặt     |         |
| 25/05/2026 | Phòng B   | Trống      |         |
| 26/05/2026 | Phòng A   | Trống      |         |

- **Ngày**: định dạng `dd/mm/yyyy`
- **Trạng thái**: ghi `Đã đặt` hoặc `Trống`

### Sheet 2: Thông tin phòng (tab `Thong_tin_phong`)

| Tên phòng | Giá phòng       | Mô tả              | Link ảnh | Quy định          |
|-----------|-----------------|--------------------|----------|-------------------|
| Phòng A   | 500.000         | View biển, 2 giường| (để trống) | Check-in 14h    |
| Phòng B   | 350.000         | Studio, 1 giường   | (để trống) | Check-out 12h   |

---

## BƯỚC 5 — Cài đặt file .env

1. Copy file `.env.example` → đổi tên thành `.env`
2. Điền đầy đủ thông tin:

```
ZALO_PHONE=0912345678           # Số điện thoại Zalo của bạn
ZALO_PASSWORD=mat_khau_cua_ban  # Mật khẩu Zalo

OWNER_ZALO_ID=1234567890        # ID Zalo của bạn (để nhận thông báo)
# Cách lấy ID: nhắn tin cho bot @devtest hoặc xem trong Zalo web

ANTHROPIC_API_KEY=sk-ant-...    # Key Claude

AVAILABILITY_SHEET_ID=...       # ID sheet (lấy từ URL)
ROOMS_INFO_SHEET_ID=...         # Có thể giống AVAILABILITY nếu cùng file
```

### Cách lấy Sheet ID
URL sheet trông như này:
`docs.google.com/spreadsheets/d/**1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs**74OgVE2upms/edit`

Phần in đậm chính là Sheet ID.

---

## BƯỚC 6 — Thêm ảnh phòng

1. Tạo thư mục `rooms_photos` trong thư mục bot
2. Đặt ảnh theo tên phòng, ví dụ:
   - `rooms_photos/Phòng A.jpg`
   - `rooms_photos/Phòng B.jpg`
   - `rooms_photos/Phòng B_2.jpg` (ảnh thứ 2, tối đa 3 ảnh/phòng)

---

## BƯỚC 7 — Tùy chỉnh system prompt

Mở file `system_prompt.txt` và sửa:
- `[TÊN HOMESTAY CỦA BẠN]` → tên homestay thực của bạn
- Thêm thông tin đặc thù: địa chỉ, tiện ích, chính sách của bạn

---

## BƯỚC 8 — Chạy bot

```powershell
python main.py
```

Lần đầu chạy, Zalo có thể yêu cầu xác thực OTP — nhập mã gửi về điện thoại.

---

## Cấu trúc thư mục hoàn chỉnh

```
zalo/
├── main.py                 # Chạy file này
├── bot.py                  # Logic bot
├── claude_ai.py            # Kết nối Claude
├── sheets.py               # Kết nối Google Sheets
├── conversation.py         # Quản lý hội thoại
├── config.py               # Đọc cài đặt
├── system_prompt.txt       # Cá tính bot (có thể chỉnh)
├── .env                    # ← BẠN TỰ TẠO (không commit lên git)
├── .env.example            # Template
├── google_credentials.json # ← BẠN TỰ TẠO (tải từ Google Cloud)
├── requirements.txt
├── rooms_photos/           # Thư mục ảnh phòng
│   ├── Phòng A.jpg
│   └── Phòng B.jpg
└── bot.log                 # Log tự động tạo khi chạy
```

---

## Xử lý sự cố thường gặp

| Lỗi | Nguyên nhân | Giải pháp |
|-----|-------------|-----------|
| `ModuleNotFoundError: zlapi` | Chưa cài thư viện | `pip install -r requirements.txt` |
| `Thiếu config` | Chưa tạo `.env` | Copy `.env.example` → `.env` |
| `INVALID_CREDENTIALS` | Sai thông tin Zalo | Kiểm tra phone/password |
| `Lỗi đọc lịch phòng` | Sheet chưa được share | Share sheet cho service account email |
| Không gửi được ảnh | Sai tên file ảnh | Tên file phải giống hệt tên phòng trong sheet |
