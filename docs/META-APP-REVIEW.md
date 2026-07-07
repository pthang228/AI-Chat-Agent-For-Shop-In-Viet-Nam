# Kịch bản xin quyền Meta App Review — NovaChat

> Mục tiêu: để **khách lạ** (shop bất kỳ) bấm "Đăng nhập Facebook" và nối được
> Messenger + Instagram + quản lý bình luận. Chưa duyệt thì chỉ tài khoản có vai
> trò trong app (admin/developer/tester) dùng được.

---

## 0. CHUẨN BỊ TRƯỚC KHI NỘP (thiếu 1 mục là bị trả hồ sơ)

| # | Việc | Ghi chú |
|---|---|---|
| 1 | **Business Verification** | Meta Business Suite → Cài đặt → Trung tâm bảo mật → Xác minh doanh nghiệp. Cần giấy ĐKKD (hộ kinh doanh cũng được) hoặc giấy tờ tương đương + SĐT/email trùng tên. Duyệt 1-5 ngày. KHÔNG có bước này thì các quyền nâng cao không được cấp. |
| 2 | **App icon 1024×1024** | Logo NovaChat nền không trong suốt |
| 3 | **Privacy Policy URL** công khai | Nội dung có sẵn ở `docs/privacy-policy.md` — cần đưa lên web (vd `https://novachatvn.duckdns.org/privacy`). Meta bot sẽ truy cập kiểm tra. |
| 4 | **Data Deletion Callback URL** | Đã có sẵn trong code: `https://novachatvn.duckdns.org/meta/data-deletion` (điền vào App Settings → Basic → Data Deletion). Deauthorize: `/meta/deauthorize`. |
| 5 | **App Domain + Site URL** | `novachatvn.duckdns.org` (Settings → Basic). Lưu ý: domain duckdns miễn phí đôi khi bị reviewer đánh giá thấp — có domain riêng thì tốt hơn. |
| 6 | **Facebook Login → Valid OAuth Redirect URIs** | `https://novachatvn.duckdns.org/` |
| 7 | **Page test + IG test** | 1 Fanpage "NovaChat Demo Store" + 1 tài khoản Instagram **Professional** liên kết Page đó. Đăng sẵn 2-3 bài viết. |
| 8 | **Tài khoản NovaChat demo cho reviewer** | Tạo user riêng vd `reviewer@novachat.vn` / mật khẩu mạnh — reviewer sẽ đăng nhập dashboard để xem luồng. |
| 9 | **App chuyển sang Live mode** | Bật SAU khi được duyệt; lúc quay video để Development vẫn được. |

---

## 1. DANH SÁCH QUYỀN CẦN XIN (đúng scope app đang gọi — `web-ui/src/metaApi.js`)

### Nhóm Messenger (bắt buộc)
1. `public_profile` — mặc định, không cần review
2. `pages_show_list` — liệt kê Page để shop chọn Page cần nối
3. `pages_messaging` — nhận/gửi tin nhắn Messenger thay Page ⭐ quan trọng nhất
4. `pages_manage_metadata` — đăng ký webhook nhận tin nhắn cho Page
5. `business_management` — liệt kê Page nằm trong Business Portfolio

### Nhóm Bình luận
6. `pages_read_user_content` — đọc bình luận/bài viết của khách trên Page
7. `pages_manage_engagement` — trả lời + ẨN bình luận (che SĐT khách khỏi đối thủ)

### Nhóm Instagram
8. `instagram_basic` — thông tin cơ bản tài khoản IG liên kết Page
9. `instagram_manage_messages` — nhận/gửi Instagram DM ⭐
10. `pages_read_engagement` — đọc nội dung Page phục vụ IG

> Mẹo: có thể nộp 2 đợt — đợt 1 nhóm Messenger (2-5), sống trước; đợt 2 bình
> luận + IG. Nộp cả cụm 1 lần cũng được nhưng 1 quyền bị từ chối là phải giải
> trình lại quyền đó.

---

## 2. LỜI KHAI USE-CASE (dán vào form, tiếng Anh — mỗi quyền Meta bắt mô tả riêng)

**pages_show_list**
> NovaChat is a SaaS customer-service chatbot for small Vietnamese businesses.
> After the shop owner logs in with Facebook, we use pages_show_list to display
> the list of Pages they manage so they can select which Page to connect to
> their AI assistant. We only store the Page ID, name and Page access token of
> the selected Page.

**pages_messaging**
> Core feature: when a customer sends a message to the connected Page, our
> webhook receives it and our AI assistant replies on behalf of the Page with
> business information the shop owner has configured (pricing, services,
> booking). The shop owner can also reply manually from our dashboard inbox.
> Messages are only sent within the standard 24-hour messaging window in
> response to user-initiated conversations.

**pages_manage_metadata**
> Used solely to subscribe the selected Page to our webhook (messages,
> messaging_postbacks, feed) so the assistant can receive customer messages and
> comment events in real time.

**business_management**
> Many of our users manage their Pages inside a Business Portfolio. We call
> /me/businesses only to enumerate Pages the user owns through their business,
> so those Pages also appear in the Page picker. No other business asset is
> read or modified.

**pages_read_user_content**
> We read comments that customers leave on the Page's posts so the shop owner
> can see and manage them in one dashboard, and so the system can detect
> comments that expose the customer's phone number.

**pages_manage_engagement**
> Two uses: (1) auto-reply to customer comments with a configurable template;
> (2) auto-HIDE comments that contain a phone number, to protect the customer's
> personal data from scrapers and competitors. The shop owner can unhide any
> comment manually.

**instagram_basic**
> Read the Instagram Professional account linked to the selected Page (ID,
> username) so the shop can confirm which IG account is being connected.

**instagram_manage_messages**
> Same core messaging feature as Messenger, for Instagram Direct: receive
> customer DMs via webhook and let the AI assistant / shop staff reply from our
> unified inbox, within Instagram's messaging window policy.

**pages_read_engagement**
> Required alongside instagram_basic to resolve the Page ↔ Instagram account
> linkage and read basic engagement metadata used by the unified inbox.

---

## 3. KỊCH BẢN QUAY SCREENCAST (1 video ≤ 5 phút, quay màn hình + KHÔNG cắt ghép giữa các bước của cùng 1 quyền)

> Meta yêu cầu video cho TỪNG quyền nhưng cho phép dùng chung 1 video và ghi
> chú mốc thời gian. Quay bằng OBS/Xbox Game Bar, tiếng không bắt buộc, nên
> thêm chú thích chữ (tiếng Anh) từng bước.

**Cảnh 1 — Đăng nhập & kết nối (pages_show_list, business_management, pages_manage_metadata):**
1. Mở `https://novachatvn.duckdns.org` → đăng nhập tài khoản demo
2. Vào **Chatbot → ＋ Thêm app → Mess + Instagram**
3. B