# Triển khai NovaChat lên VPS (Docker + HTTPS) — hướng dẫn A→Z

Mục tiêu: chạy toàn bộ hệ thống trên **1 máy chủ Linux có domain HTTPS cố định** thay
cho ngrok. Sau bước này, **khách lạ dùng được mọi kênh cần webhook** (Meta, Zalo OA,
TikTok, Shopee, website) và bạn có thể nộp **Meta App Review**.

Toàn bộ chạy bằng **Docker Compose**: 7 dịch vụ Python + Zalo Node + Caddy (tự cấp
chứng chỉ TLS Let's Encrypt, phục vụ dashboard, định tuyến mọi kênh trên 1 domain).

---

## 0. Cần chuẩn bị (mất tiền, ~vài trăm k/tháng)

| Thứ | Ở đâu | Chi phí |
|---|---|---|
| **Domain** | Mua ở Namecheap / Porkbun / Tenten / Mắt Bão. Chọn tên `.com`/`.vn`/`.site` | ~200–300k/năm (`.site`/`.online` rẻ ~30k năm đầu) |
| **VPS Linux** (Ubuntu 22.04, ≥2GB RAM) | Vultr / DigitalOcean / Hetzner / hoặc VN: Vietnix, AZDIGI | ~5–10$/tháng (~120–250k) |

> RAM: 8 dịch vụ + Caddy nhẹ nhàng chạy ổn ở **2GB**; 1GB có thể chật khi build. Nên chọn 2GB.

> ### 💡 Chưa muốn mua domain? Dùng subdomain MIỄN PHÍ (DuckDNS)
> Bạn có thể bỏ qua bước mua domain mà vẫn có **HTTPS thật + Meta chấp nhận**:
> 1. Vào [duckdns.org](https://www.duckdns.org) → đăng nhập Google → tạo subdomain, vd `novachat.duckdns.org`.
> 2. Điền **IP VPS** vào ô "current ip" của subdomain đó → Update (hoặc để trống rồi cập nhật sau ở bước 1).
> 3. Ở bước 4 đặt `DOMAIN=novachat.duckdns.org` — **không đổi gì khác**. Caddy tự xin
>    chứng chỉ Let's Encrypt cho subdomain này (HTTPS hợp lệ, webhook Meta/Zalo OA/... nhận hết).
>
> ⚠️ **KHÔNG dùng hosting "deploy bằng git" free** (Render/Railway/Vercel free) cho app này:
> chúng **ngủ khi rảnh** (webhook rơi, bot không rep) và **xoá sạch dữ liệu mỗi lần deploy**
> (mất tài khoản/hội thoại/token). Meta duyệt URL nhưng app không chạy nổi → trượt review.
> Bắt buộc 1 chỗ chạy 24/7 giữ được dữ liệu = VPS (rẻ nhất ~5$/tháng).

---

## 1. Trỏ domain (hoặc subdomain DuckDNS) về VPS (DNS)

1. Lấy **IP public** của VPS (nhà cung cấp cho khi tạo máy).
2. Vào trang quản lý domain → mục **DNS** → thêm bản ghi:
   - Type `A`, Host `@`, Value = `IP VPS`
   - (tùy chọn) Type `A`, Host `www`, Value = `IP VPS`
3. Đợi 5–30 phút cho DNS lan. Kiểm tra: `ping novachat.example.com` phải ra IP VPS.

> Dùng đúng domain gốc (vd `novachat.site`) hoặc 1 subdomain (`app.novachat.site`) — điền vào `DOMAIN` ở bước 4.
> **Nếu dùng DuckDNS**: bỏ qua mục DNS này, chỉ cần đặt IP VPS ở trang duckdns.org là xong.

---

## 2. Cài Docker trên VPS

SSH vào VPS (`ssh root@IP_VPS`) rồi chạy:

```bash
curl -fsSL https://get.docker.com | sh
docker compose version   # kiểm tra có Compose v2
```

Mở tường lửa cổng web (nếu VPS bật ufw):

```bash
ufw allow 80 && ufw allow 443 && ufw allow OpenSSH && ufw --force enable
```

---

## 3. Đưa mã nguồn lên VPS

Cách A — qua Git (khuyến nghị nếu bạn đã push lên GitHub):
```bash
git clone https://github.com/pthang228/AI-Chat-Agent-For-Shop-In-Viet-Nam.git novachat
cd novachat
```

Cách B — copy thẳng từ máy Windows bằng `scp` (chạy trên máy bạn):
```bash
scp -r "F:\New folder\zalo" root@IP_VPS:/root/novachat
```

---

## 4. Điền cấu hình

```bash
cd deploy
cp .env.production.example .env.production
nano .env.production
```

**Bắt buộc** điền: `DOMAIN`, `ACME_EMAIL`, `PUBLIC_BASE_URL` (=`https://<DOMAIN>`),
`ALLOWED_ORIGINS` (=`https://<DOMAIN>`), `DEEPSEEK_API_KEY` (và nên có `GROQ_API_KEY`).
Các khoá kênh (Meta/Telegram/OA/TikTok/Shopee) điền dần khi kết nối — để trống vẫn chạy.

---

## 5. Chạy

```bash
docker compose up -d --build
```

Lần đầu build ~vài phút. Xong kiểm tra:

```bash
docker compose ps                 # tất cả "running"
curl -I https://<DOMAIN>          # ra HTTP/2 200, Caddy đã cấp TLS
docker compose logs -f web        # xem Caddy lấy chứng chỉ (nếu lỗi TLS)
```

Mở trình duyệt `https://<DOMAIN>` → thấy landing NovaChat. Đăng ký tài khoản đầu tiên
= chủ shop chính.

> **Nếu TLS không cấp được**: kiểm tra DNS đã trỏ đúng IP (bước 1) và cổng 80/443 mở
> (bước 2). Caddy cần cổng 80 thông để xác thực Let's Encrypt.

---

## 6. Khai webhook từng kênh (dán URL có domain thật)

Giờ URL công khai là `https://<DOMAIN>`. Vào từng nền tảng khai webhook:

| Kênh | Callback URL | Ghi chú |
|---|---|---|
| **Meta** (Mess+IG) | `https://<DOMAIN>/fb/webhook` | Verify token = `FB_VERIFY_TOKEN`, subscribe `messages` |
| **Meta Data Deletion** | `https://<DOMAIN>/meta/data-deletion` | Settings → Basic (bắt buộc cho App Review) |
| **Meta Deauthorize** | `https://<DOMAIN>/meta/deauthorize` | Settings → Basic |
| **Zalo OA** | `https://<DOMAIN>/zalooa/webhook` | developers.zalo.me |
| **TikTok** | `https://<DOMAIN>/tiktok/webhook` | app Business Messaging |
| **Shopee** | `https://<DOMAIN>/shopee/webhook` | open.shopee.com |
| **SePay** (thu tiền) | `https://<DOMAIN>/payhook` | đặt `SEPAY_API_KEY` trùng key SePay |
| **Website widget** | tự sinh trong app | snippet đã trỏ về `<DOMAIN>` |

Zalo cá nhân & Telegram không cần webhook (quét QR / long-poll).

---

## 7. Mở khoá khách LẠ cho Messenger + Instagram (App Review)

Đây là bước cuối để **người lạ** nhắn được (dev mode chỉ admin/tester):

1. **Business Verification** trong Meta Business Manager (xác minh DN bằng giấy tờ).
2. **App Review** → xin quyền `pages_messaging` + `instagram_manage_messages`, kèm:
   - Mô tả use-case: *"Bot tự động trả lời tin nhắn khách hàng của shop."*
   - **Video quay màn hình** bot nhận & trả lời tin (dùng tài khoản tester).
   - Đã dán sẵn Privacy Policy + Data Deletion + Deauthorize URL (bước 6).
3. App đã **Live**. Meta duyệt xong → khách lạ nhắn được, **không phải sửa gì**.

---

## 8. Vận hành

**Giám sát chủ động (làm 1 lần, ~10 phút — đừng bỏ qua khi có shop trả tiền):**

1. **Uptime monitor**: tạo monitor MIỄN PHÍ ở [uptimerobot.com](https://uptimerobot.com)
   (hoặc BetterStack) ping `https://<DOMAIN>/health` mỗi 1-5 phút. `/health` giờ là
   health SÂU (chạm DB + kiểm disk, trả 503 khi hỏng) nên monitor bắt được cả sự cố
   "container sống nhưng DB nghẹt". Zalo Node cũng có `/health` riêng (503 khi acc
   rớt phiên) — Docker healthcheck đã gắn sẵn.
2. **Alert lỗi qua Telegram**: đặt `ALERT_TG_BOT_TOKEN` + `ALERT_TG_CHAT_ID` trong
   `.env.production` → mọi log ERROR của 7 service Python bắn thẳng vào Telegram
   của bạn (throttle 1 tin/5 phút mỗi nguồn). 2h sáng DeepSeek hết hạn mức là biết liền.
3. (Tuỳ chọn) Sentry free-tier nếu muốn stack trace đầy đủ + gom nhóm lỗi.

```bash
# Xem log 1 dịch vụ
docker compose logs -f meta        # hoặc bridge / telegram / zalo-node ...

# Cập nhật code mới
git pull && docker compose up -d --build

# Khởi động lại 1 dịch vụ
docker compose restart bridge

# Dừng tất cả
docker compose down                # (giữ nguyên volume dữ liệu)
```

**Sao lưu dữ liệu**

DB (ví tiền/billing/hội thoại) được service `backup` **tự sao lưu hằng đêm** bằng
`sqlite3 .backup()` (nhất quán qua WAL — KHÔNG dùng tar/cp file .db đang mở, dễ ra
bản hỏng) sang volume **riêng** `backups` — xoá nhầm `dbdata` vẫn còn bản sao:

```bash
docker compose logs backup                  # xem nhật ký sao lưu
docker compose exec backup ls -lh /backups  # liệt kê các bản (giữ 14 bản gần nhất)

# KHÔI PHỤC (dừng stack → chép bản sao đè DB → bật lại):
docker compose stop
docker compose run --rm backup sh -c 'cp /backups/homestay-<STAMP>.db /app/data/homestay.db && rm -f /app/data/homestay.db-wal /app/data/homestay.db-shm'
docker compose up -d
```

**Offsite (KHUYẾN NGHỊ khi có shop trả tiền)** — VPS cháy/mất là backup trên cùng
máy cũng mất. Cron trên host đẩy `/backups` lên cloud (rclone/S3/Google Drive):

```bash
# crontab -e trên VPS (rclone config trước 1 lần):
0 4 * * * docker cp $(docker compose -f /root/novachat/deploy/docker-compose.yml ps -q backup):/backups /tmp/nb && rclone sync /tmp/nb remote:novachat-backups
```

Media + phiên Zalo (ít quan trọng hơn DB, mất thì kết nối lại):
```bash
docker run --rm -v novachat_media:/d -v $PWD:/b alpine tar czf /b/backup-media.tgz -C /d .
docker run --rm -v novachat_zalosession:/d -v $PWD:/b alpine tar czf /b/backup-zalosession.tgz -C /d .
```

---

## 9. Sự cố thường gặp

- **502 khi mở dashboard**: 1 dịch vụ chưa lên → `docker compose ps`, xem `logs` dịch vụ đó.
- **TLS lỗi / trang không HTTPS**: DNS chưa trỏ đúng hoặc cổng 80 bị chặn → xem `logs web`.
- **Ảnh gửi khách bị gãy**: `PUBLIC_BASE_URL` phải = `https://<DOMAIN>` (đúng domain, có https).
- **Đăng nhập Google không hiện**: đặt `VITE_GOOGLE_CLIENT_ID` rồi `docker compose up -d --build web`
  (biến build-time, phải build lại ảnh web) + thêm origin `https://<DOMAIN>` ở Google Console.
- **Zalo mất phiên sau khi update**: phiên nằm ở volume `zalosession`, `docker compose down`
  KHÔNG xoá volume — chỉ mất nếu chạy `docker compose down -v`.

---

## Kiến trúc tóm tắt

```
Internet ──HTTPS──► Caddy (web, cổng 443)
                      │  định tuyến theo path:
                      ├─ /meta,/fb/webhook,/payhook,/posts,/media ─► meta:5006
                      ├─ /tg/*      ─► telegram:5007
                      ├─ /tiktok/*  ─► tiktok:5008
                      ├─ /shopee/*  ─► shopee:5009
                      ├─ /zalooa/*  ─► zalooa:5010
                      ├─ /webchat/*,/widget.js ─► webchat:5011
                      ├─ /zalo-node/* ─► zalo-node:4000
                      ├─ /auth,/conversations,/billing,... ─► bridge:5005
                      └─ còn lại ─► dashboard React (tĩnh)
Tất cả chung volume: dbdata (SQLite), media. Chỉ Caddy mở cổng ra ngoài.
```
