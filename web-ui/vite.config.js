import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
})
