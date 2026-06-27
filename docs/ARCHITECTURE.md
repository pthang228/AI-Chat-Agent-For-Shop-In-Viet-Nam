# Kiến trúc dự án — Homestay Bot ĐA KÊNH (Zalo · Messenger/Instagram · Telegram)

> File này mô tả tổng quan kiến trúc để đọc nhanh, đỡ phải scan lại toàn bộ code.
> Cập nhật khi thay đổi logic lớn.

## 1. Tóm tắt

Bot chat tự động tư vấn đặt phòng homestay, bán dạng **SaaS cho nhiều homestay**, chạy trên **3 kênh**:
**Zalo** (cá nhân, đăng nhập QR qua Node), **Meta** (Messenger + Instagram, 1 lần đăng nhập Facebook),
và **Telegram** (bot, người lạ nhắn được ngay, không cần duyệt).

Khi khách nhắn 1-1, bot tự tư vấn: xem **lịch phòng trống** (Google Sheets), gửi **bảng giá**,
gửi **ảnh phòng**, và khi khách chốt đặt thì **thông báo + gọi điện cho chủ nhà**.

Mỗi homestay tự cấu hình trong **dashboard web**: kết nối kênh, chọn chủ nhận báo, đăng nhập acc gọi,
xem hội thoại và bật/tắt bot cho từng khách.

**Stack:** Python · `zca-js` (Zalo QR, Node) / `zlapi` (Zalo cookie cũ) · Graph API (Meta) ·
Bot API + Telethon (Telegram) · DeepSeek + Groq (LLM) · Google Sheets (gspread) · Flask · React/Vite.

## 2. Kiến trúc channel-agnostic (đã refactor)

Logic bot được tách làm 2 lớp để sau cắm thêm kênh (Instagram, Messenger, web widget...) mà không viết lại logic:

```
        ┌─ ZaloNodeChannel ──────── Zalo QR (zca-js, Node) — đang dùng
Brain ──┼─ MetaChannel ─────────── Messenger + Instagram (Graph API)
(brain.py)─ TelegramChannel ────── Telegram bot (Bot API + Telethon gọi điện)
   │       cùng 1 "não bộ"          (ZaloCookieChannel zlapi — fallback cũ)
   ▼
  Channel (channel.py) — giao diện trừu tượng:
  send_text · send_room_photos · send_price_photos · notify_owner · call_owner
```

→ 3 kênh trên ĐỀU đã chạy thật, cùng dùng chung `brain.py`. Thêm kênh mới vẫn theo nguyên tắc này.

- **Brain** (`brain.py`) = toàn bộ logic xử lý (intent, override regex, Sheets, ảnh, booking). KHÔNG biết gì về Zalo. Chỉ ra lệnh qua giao diện `Channel`.
- **Channel** (`channel.py`) = lớp trừu tượng (ABC) định nghĩa các "primitive" gửi tin.
- **ZaloChannel** (`bot.py`) = 1 cài đặt cụ thể của `Channel` bằng `zlapi`, kèm phần đặc thù Zalo (nhận tin, chống echo, owner-takeover).

→ Thêm kênh mới = viết 1 class implement `Channel` + adapter nhận tin gọi `brain.handle(user_id, text)`. **Không đụng `brain.py`.**

## 3. Luồng xử lý 1 tin nhắn (quan trọng nhất)

```
Khách nhắn Zalo
   │
   ▼
ZaloChannel.onMessage()                          [bot.py]  ← đặc thù Zalo
   │  - Bỏ qua tin từ GROUP (tránh 2 bot loop nhau)
   │  - Nếu author == chính bot → kiểm tra echo:
   │       • echo text/ảnh do bot vừa gửi → bỏ qua
   │       • KHÔNG phải echo → chủ nhà tự nhắn tay → bật owner_active (dừng bot 48h)
   │  - Nếu khách đang được chủ xử lý (owner_active) → bỏ qua
   ▼
Brain.handle(user_id, text)                       [brain.py]  ← dùng chung mọi kênh
   │  1. analyze_message() gọi LLM → trả {intent, checkin, checkout, reply, booking_confirmed}
   │  2. RẤT NHIỀU "override" bằng regex/keyword tiếng Việt để sửa intent của LLM
   │     (vd: nhận diện "còn phòng ko", "bảng giá", "ảnh 201", "gặp chủ"...)
   │  3. Khách mới → luôn gửi greeting cố định + ảnh bảng giá
   │  4. Ra lệnh gửi qua self.channel.* (kênh tự lo cách gửi thật)
   ▼
Phân nhánh theo intent:
   • availability_check → format_availability_for_ai() đọc Sheets → gửi lịch trống
   • price_list_request → gửi text + ảnh bảng giá (price_photos/)
   • photo_request      → gửi ảnh phòng (rooms_photos/<số phòng>/)
   • contact_request    → báo chủ nhà + gọi điện
   • reschedule_request → báo chủ nhà
   • unknown_question   → báo chủ nhà
   • booking_confirmed  → verify lại Sheets → báo chủ + gọi điện
   • other              → trả lời text của LLM
```

**Điểm thiết kế cốt lõi:** LLM dùng để hiểu ngôn ngữ + sinh câu trả lời, nhưng **dữ liệu phòng/giá/lịch
luôn lấy từ nguồn thật (Sheets, thư mục ảnh)**, không để LLM bịa. Phần override intent bằng regex là để
"chốt chặn" khi LLM phân loại sai — đây là lý do `_handle()` dài và nhiều keyword tiếng Việt.

## 4. Cấu trúc thư mục (sau khi tái cấu trúc)

```
F:\New folder\zalo\
├─ app/                          ← BACKEND Python (chạy: python -m app.main_node TỪ GỐC)
│  ├─ core/                      LÕI dùng chung mọi kênh
│  │  ├─ config.py              Config + BASE_DIR/DATA_DIR/MEDIA_DIR (resolve path theo gốc dự án)
│  │  ├─ brain.py               "Não bộ": intent + override + Sheets + ảnh + booking (độc lập kênh)
│  │  ├─ channel.py             Giao diện ABC: send_text/room_photos/price_photos/notify_owner/call_owner
│  │  ├─ conversation.py        ConversationState + Manager (persist data/sessions.json)
│  │  ├─ sheets.py              Đọc Google Sheets lịch phòng
│  │  ├─ claude_ai.py           Gọi LLM (DeepSeek→Groq), đọc system_prompt.txt cùng thư mục
│  │  ├─ owner_call.py          Beep + gọi Telegram (Telethon) báo chủ
│  │  └─ system_prompt.txt
│  │  ├─ telegram_store.py      Token + chủ + caller_session theo từng bot Telegram
│  │  └─ telegram_login.py      Đăng nhập acc gọi (Telethon) bằng QR trong web
│  ├─ channels/
│  │  ├─ zalo_node.py           Kênh Zalo QR — gọi HTTP sang Node service (zca-js)
│  │  ├─ meta.py                Kênh Messenger + Instagram (Graph API)
│  │  ├─ telegram.py            Kênh Telegram bot (Bot API + Telethon gọi điện)
│  │  └─ zalo_cookie/           Kênh Zalo CŨ (zlapi/cookie) — fallback
│  ├─ web_api/                  Flask theo kênh: bridge.py (Zalo 5005) · meta_webhook.py (5006) · telegram_api.py (5007)
│  └─ main_node.py · main_meta.py · main_telegram.py   Entry từng kênh
├─ zalo-node/                   NODE service (zca-js): QR login, nhận/gửi Zalo, /groups, /config, /notify-owner (cổng 4000)
├─ web-ui/                      FRONTEND React (Vite): đăng nhập/đăng ký, quản lý app, QR, chọn nhóm, xem hội thoại (cổng 5173)
├─ scripts/                     get_zalo_id.py · setup_tg_call.py · debug_sheets.py · run.bat (chạy kênh cũ)
├─ tests/                       test_flow.py · test_intent.py · test_sheets.py · test_bridge.py
├─ data/                        sessions*.json · zalo_cookies*.json · tg_caller_session.session
├─ media/                       price_photos/ · rooms_photos/<số phòng>/
├─ docs/                        SETUP.md · ARCHITECTURE.md
├─ .env · google_credentials.json · requirements.txt · start-all.bat
```

**3 runtime, 3 cổng:** Node (4000) ↔ Python bridge (5005) ↔ React (5173). Xem mục 2 cho sơ đồ.

**Import:** mọi module Python dùng import tuyệt đối `app.core.X`, `app.channels.X`, `app.web_api.X`.
Đường dẫn data/media tính theo `Config.BASE_DIR` nên chạy từ đâu cũng đúng (entry chuẩn: `python -m app.main_node` từ gốc).

## 5. Khái niệm quan trọng

### owner_active (Owner Takeover)
Khi **chủ nhà tự tay nhắn** cho khách từ app Zalo (không phải bot), `onMessage` phát hiện tin đó
không khớp echo của bot → bật `owner_active=True` cho khách đó. Bot sẽ **ngừng tự trả lời** khách
này trong **48 giờ** (tự reset). Chủ nhà cũng bật/tắt thủ công qua dashboard.

### Chống echo (echo detection)
`zlapi` trả về cả tin do chính bot gửi (`author_id == self.uid()`). Để không xử lý nhầm tin của
mình như tin chủ nhà:
- **Text:** lưu MD5 fingerprint (`_bot_sent_cache`, 60s) → khớp thì bỏ qua.
- **Ảnh:** override `sendLocalImage()` để ghi nhận `(thread_id, time)` (`_bot_image_threads`) →
  MessageObject echo về trong 60s thì bỏ qua.

### intent (do LLM gán + override)
`other`, `availability_check`, `price_list_request`, `photo_request`, `contact_request`,
`reschedule_request`, `unknown_question`. Cờ `booking_confirmed` và `use_ai_reply` đi kèm.
`use_ai_reply=True` = LLM tự tin, bỏ qua phần override availability/price (nhưng contact/photo vẫn chạy).

### stage (vòng đời hội thoại)
`greeting → checking → offering → confirmed → owner_notified`. Lưu trong `ConversationState`,
hiển thị trên dashboard.

### Xử lý ngày tiếng Việt
2 lớp: (1) `claude_ai._today_context()` đưa bảng lịch 14 ngày + quy đổi cho LLM;
(2) `bot._infer_date_from_text()` là fallback Python suy ra ngày từ "tối nay", "mai", "thứ 5 tuần sau"...
nếu LLM chưa extract được.

### Đọc lịch Sheets (`sheets.py`)
Cấu trúc sheet: hàng 1 = tên phòng (gộp ô), hàng 2 = ca giờ, hàng 3+ = dữ liệu (cột B = ngày).
Tab theo tháng ("Lịch tháng 5/2026"), `_open_tab()` chịu được typo tên tab. Với ca "hôm nay"
còn lọc theo giờ thực tế (ẩn ca đã kết thúc), xử lý cả ca qua đêm (vd `21h-10h30`).

## 6. Tích hợp ngoài

- **LLM:** DeepSeek (`deepseek-chat`) chính → fallback Groq (`llama-3.3-70b` → `llama-3.1-8b` → `gemma2-9b`).
  Đều gọi qua OpenAI-compatible API. Cần `DEEPSEEK_API_KEY` hoặc `GROQ_API_KEY`.
- **Google Sheets:** service account read-only, 2 sheet `HARU_SHEET_ID` / `MOCHI_SHEET_ID`.
- **Thông báo chủ nhà (`notify_owner`):** Zalo → nhóm `OWNER_GROUP_ID` (fallback DM); Meta → DM PSID;
  Telegram → DM chủ đã đăng ký (`/chunha` hoặc nút trong web).
- **Gọi điện (`call_owner`):** beep loa máy (`winsound`) + gọi qua **Telegram bằng Telethon**.
  - **Acc gọi (người gọi):** 1 tài khoản Telegram THẬT (bot không gọi thoại được). Phiên đăng nhập lưu
    dạng StringSession. Đăng nhập **bằng QR ngay trong web** (`telegram_login.py`, mỗi bot/homestay 1 acc) —
    thay cho `scripts/setup_tg_call.py` (terminal) trước đây.
  - **Người nghe (chủ):** chủ đã đăng ký của bot (`store.get_owner_chat_id`) hoặc `.env TELEGRAM_TARGET_ID`.
  - **Logic dừng:** gọi lại mỗi 3 phút, tối đa 10 lần; **dừng khi chủ BẮT MÁY** (sự kiện `PhoneCallAccepted`).
  - `api_id/api_hash` đọc từ `.env` (`TELEGRAM_API_ID/HASH`), không còn hardcode.

### Kênh Telegram (đa khách)
`channels/telegram.py` (`TelegramChannel`, user_id `tg:<bot_id>:<chat>`) + `web_api/telegram_api.py`
(LONG-POLLING getUpdates, 1 poller/bot, Flask 5007) + `core/telegram_store.py` (token + chủ + **caller_session**
theo từng bot → `data/telegram_bots.json`) + `core/telegram_login.py` (đăng nhập acc gọi bằng QR).
Onboarding: khách **dán token bot** (@BotFather) trong web → tự lưu + poll. Chủ tự đăng ký `/chunha` hoặc
nút "Đăng ký chủ". Acc gọi: nút "📞 Đăng nhập acc gọi" → quét QR.

## 7. Chạy

**Cách nhanh nhất:** double-click `start-all.bat` ở gốc → tự bật Node + Python + React rồi mở `http://localhost:5173`.

**Chạy tay (kênh QR Node — khuyến nghị):**
```bash
# Terminal 1 — Node (QR + nhận/gửi Zalo)
cd zalo-node && npm start                 # http://localhost:4000

# Terminal 2 — não bộ Python (TỪ GỐC dự án)
python -m app.main_node                    # bridge http://127.0.0.1:5005

# Terminal 3 — giao diện React
cd web-ui && npm run dev                    # http://localhost:5173
```
→ Mở web 5173 → đăng nhập → thêm app Zalo → tab **Kết nối** (quét QR, chọn nhóm) + tab **Khách hàng** (xem chat, bật/tắt bot).

**Kênh Zalo cũ (zlapi/cookie — fallback):**
```bash
python scripts/get_zalo_id.py              # 1 lần: tạo data/zalo_cookies.json
python -m app.channels.zalo_cookie.main    # hoặc scripts/run.bat
```

## 8. Lưu ý / nợ kỹ thuật

- **Đa runtime:** kênh QR cần cả Node (zca-js) lẫn Python; React là frontend riêng. Trình duyệt không tự bật backend → phải qua `start-all.bat`.
- **Chống echo kênh Node:** `selfListen` bật nên tin bot tự gửi vọng về; Node đánh dấu `lastBotSendAt` theo thread (15s) + msgId để lọc, tránh nhầm thành chủ-gõ-tay (từng gây bug tắt bot 48h).
- **Auth web tạm thời:** đăng nhập/đăng ký + danh sách app lưu **localStorage trình duyệt** (chưa backend, mật khẩu chưa hash). Cần thay bằng backend + DB khi bán thật.
- **Đơn tenant:** Node service hiện 1 instance/1 tài khoản Zalo dùng chung; multi-tenant chưa làm.
- `requirements.txt` còn thiếu vài gói runtime (`groq`, `telethon`, `flask`, `pillow`); Node cần `npm install` trong `zalo-node/` và `web-ui/`.
- Telegram `api_id/api_hash` lấy từ `.env` (`TELEGRAM_API_ID/HASH`); fallback creds TG Desktop CHỈ để chạy thử —
  đa khách phải đăng ký riêng ở my.telegram.org kẻo bị giới hạn/ban.
- **Bảo mật:** `caller_session` (toàn quyền acc Telegram của khách) đang lưu THÔ trong `data/telegram_bots.json` —
  cần mã hoá trước khi bán thật.
- Bot chỉ xử lý chat **1-1**, mọi tin nhóm bị bỏ qua (trừ gửi thông báo vào nhóm chủ).
- `sheets.py` còn 1 test phụ thuộc giờ thực tế (E7/F4) — không phải lỗi cấu trúc.
