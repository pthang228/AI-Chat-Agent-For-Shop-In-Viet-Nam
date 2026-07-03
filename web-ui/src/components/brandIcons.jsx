// Logo thương hiệu THẬT của các kênh + glyph tính năng — dùng cho orbit & ticker ở Landing.
// Mỗi icon vẽ mark trắng (fill #fff) để nổi trên nền tile màu thương hiệu; nhận spread props (className...).

// ── Kênh chat ──
// Zalo — bong bóng chat trắng + chữ "Z" đậm (đọc rõ ở kích thước nhỏ, nền tile xanh Zalo)
export const IcZalo = (p) => (
  <svg viewBox="0 0 24 24" fill="none" {...p}>
    <path fill="#fff" d="M12 3.5c-4.8 0-8.7 3.1-8.7 7 0 2.3 1.3 4.3 3.4 5.6-.1.9-.5 1.9-.9 2.6-.2.4.1.7.5.6 1.3-.4 2.5-.9 3.4-1.5.7.1 1.5.2 2.3.2 4.8 0 8.7-3.1 8.7-7s-3.9-7-8.7-7Z"/>
    <path stroke="#0068ff" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" d="M9.1 8.8h5l-5 5.3h5.3"/>
  </svg>
);

// Messenger — chat bubble + tia sét (nền tile gradient Messenger)
export const IcMessenger = (p) => (
  <svg viewBox="0 0 24 24" fill="none" {...p}>
    <path fill="#fff" d="M12 2.2C6.3 2.2 2 6.4 2 11.7c0 2.9 1.3 5.5 3.4 7.2v3.4c0 .3.3.5.6.4l3.4-1.5c.8.2 1.7.3 2.6.3 5.7 0 10-4.2 10-9.5S17.7 2.2 12 2.2Zm5.9 7.4-2.9 4.6c-.4.7-1.3.9-1.9.4l-2.3-1.7a.6.6 0 0 0-.7 0l-3.1 2.4c-.4.3-.9-.2-.7-.6l2.9-4.6c.4-.7 1.3-.9 1.9-.4l2.3 1.7c.2.2.5.2.7 0l3.1-2.4c.4-.3.9.2.7.6Z"/>
  </svg>
);

// Instagram — camera (nền tile gradient IG)
export const IcInstagram = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.9" {...p}>
    <rect x="3.4" y="3.4" width="17.2" height="17.2" rx="5"/>
    <circle cx="12" cy="12" r="4.1"/>
    <circle cx="17.2" cy="6.8" r="1.15" fill="#fff" stroke="none"/>
  </svg>
);

// Telegram — máy bay giấy (nền tile xanh Telegram)
export const IcTelegram = (p) => (
  <svg viewBox="0 0 24 24" fill="none" {...p}>
    <path fill="#fff" d="M21.9 4.3 18.8 19c-.2 1-.8 1.2-1.7.8l-4.7-3.5-2.3 2.2c-.3.3-.5.5-1 .5l.3-4.9 8.9-8c.4-.3-.1-.5-.6-.2L6.9 12.8l-4.7-1.5c-1-.3-1-1 .2-1.5l18.4-7.1c.8-.3 1.5.2 1.1 1.6Z"/>
  </svg>
);

// TikTok — nốt nhạc (nền tile đen)
export const IcTikTok = (p) => (
  <svg viewBox="0 0 24 24" fill="none" {...p}>
    <path fill="#fff" d="M16.7 2h-3.3v13.1c0 1.4-.8 2.4-2.1 2.5-1.3.1-2.4-.7-2.5-2-.1-1.2.7-2.2 2-2.4.5-.1 1 0 1.5.1V9.6c-3.2-.4-5.9 1.7-6.1 4.7-.2 3.1 1.9 5.6 5 5.9 3.5.3 6.2-2.2 6.2-5.8V8.9c1.2.7 2.5 1.1 3.8 1v-2.7c-2.2-.2-3.6-1.9-3.9-4.1-.1-.4-.3-.9-.6-1Z"/>
  </svg>
);

// ── Glyph tính năng (nét trắng, đồng bộ style app) ──
// AI / Dạy AI — tia sáng
export const IcAI = (p) => (
  <svg viewBox="0 0 24 24" fill="#fff" {...p}>
    <path d="M12 2.5l1.9 5.1 5.1 1.9-5.1 1.9L12 16.5l-1.9-5.1L5 9.5l5.1-1.9z"/>
    <path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>
  </svg>
);

// Lịch trống — calendar
export const IcCalendar = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.9" strokeLinecap="round" {...p}>
    <rect x="3.5" y="5" width="17" height="15.5" rx="2.5"/>
    <path d="M3.5 9.5h17M8 3v4M16 3v4"/>
  </svg>
);

// Gọi chủ — điện thoại
export const IcPhone = (p) => (
  <svg viewBox="0 0 24 24" fill="#fff" {...p}>
    <path d="M7 2.8c.6 0 1.1.4 1.3 1l1 3c.2.6 0 1.2-.5 1.6l-1.3 1c.9 1.8 2.3 3.2 4.1 4.1l1-1.3c.4-.5 1-.7 1.6-.5l3 1c.6.2 1 .7 1 1.3v3c0 .8-.7 1.5-1.5 1.4C10.9 20.1 3.9 13.1 3.1 5.7 3 4.9 3.7 4.2 4.5 4.2h.1L7 2.8Z"/>
  </svg>
);

// Gửi ảnh — hình ảnh
export const IcImage = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.9" strokeLinejoin="round" {...p}>
    <rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/>
    <circle cx="8.5" cy="9.5" r="1.7" fill="#fff" stroke="none"/>
    <path d="M20.5 15.5 15.5 10.5 6 20"/>
  </svg>
);
