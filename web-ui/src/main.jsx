import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { I18nProvider } from './i18n.jsx'
import { getTheme, applyTheme } from './theme.js'

// Áp chủ đề TRƯỚC khi render để không chớp nền sáng khi user chọn dark
applyTheme(getTheme())

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <I18nProvider>
      <App />
    </I18nProvider>
  </StrictMode>,
)
