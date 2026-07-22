import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// Proxy dev: mọi API cùng origin với web (5173) → vite chuyển tiếp về đúng cổng
// backend PHÍA SERVER. Nhờ vậy khi chạy HTTPS (dev:https) KHÔNG dính mixed-content
// và KHÔNG dính CORS → test được luồng Đăng nhập Facebook ngay trên máy.
// Bảng prefix khớp deploy/Caddyfile (production). LƯU Ý: /billing/ và /prompt/ để
// DẤU "/" cuối → chỉ nuốt subpath API, KHÔNG nuốt route trang SPA /billing, /prompt.
function proxyFor(prefixes, port) {
  const out = {}
  for (const p of prefixes)
    out[p] = { target: `http://127.0.0.1:${port}`, changeOrigin: true, secure: false }
  return out
}
const proxy = {
  ...proxyFor(['/meta', '/fb/webhook', '/payhook', '/posts', '/comments', '/media'], 5006),
  ...proxyFor([
    '/auth', '/conversations', '/orders', '/notify', '/caller', '/broadcasts',
    '/team', '/teammates', '/customers', '/followups', '/copilot', '/canned',
    '/support', '/bot-status', '/bot-toggle', '/stats', '/health', '/photos',
    '/vouchers', '/sheets', '/zalo', '/zalo-node', '/admin/shops', '/billing/',
    '/prompt/',
  ], 5005),
  ...proxyFor(['/tg'], 5007),
  ...proxyFor(['/shopee'], 5009),
  ...proxyFor(['/zalooa'], 5010),
  ...proxyFor(['/webchat', '/widget.js'], 5011),
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  // `vite --mode https` → serve HTTPS (cert tự ký) cho luồng cần HTTPS như FB Login.
  plugins: [react(), ...(mode === 'https' ? [basicSsl()] : [])],
  server: { proxy },
  build: {
    rollupOptions: {
      output: {
        // Tách vendor (react/react-dom/router) ra chunk riêng: đổi code app
        // không làm khách tải lại vendor (cache trình duyệt giữ nguyên hash).
        // Vite 8 (rolldown) chỉ nhận DẠNG HÀM, không nhận object.
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
        },
      },
    },
  },
}))
