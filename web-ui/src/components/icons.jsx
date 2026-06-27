// Bộ icon line nhỏ dùng chung (kế thừa currentColor).
const s = (p) => ({ width: 18, height: 18, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", ...p });

export const IcHome = (p) => (<svg {...s(p)}><path d="M3 11l9-8 9 8" /><path d="M5 10v10h14V10" /></svg>);
export const IcMail = (p) => (<svg {...s(p)}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>);
export const IcLock = (p) => (<svg {...s(p)}><rect x="4" y="11" width="16" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>);
export const IcUser = (p) => (<svg {...s(p)}><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4 4-6 8-6s8 2 8 6" /></svg>);
export const IcArrow = (p) => (<svg {...s(p)}><path d="M5 12h14" /><path d="M13 6l6 6-6 6" /></svg>);
export const IcSpark = (p) => (<svg {...s(p)}><path d="M12 3l1.8 4.7L18.5 9l-4.7 1.3L12 15l-1.8-4.7L5.5 9l4.7-1.3z" /><path d="M19 14l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" /></svg>);
export const IcShield = (p) => (<svg {...s(p)}><path d="M12 3l7 3v6c0 4-3 7-7 9-4-2-7-5-7-9V6z" /></svg>);
export const IcChev = (p) => (<svg {...s(p)}><path d="M9 6l6 6-6 6" /></svg>);
export const IcBack = (p) => (<svg {...s(p)}><path d="M15 6l-6 6 6 6" /></svg>);
export const IcLogout = (p) => (<svg {...s(p)}><path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3" /><path d="M10 12H3" /><path d="M6 8l-3 4 3 4" /></svg>);
export const IcPlus = (p) => (<svg {...s(p)}><path d="M12 5v14M5 12h14" /></svg>);
export const IcBell = (p) => (<svg {...s(p)}><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 0 1-3.4 0" /></svg>);
export const IcRefresh = (p) => (<svg {...s(p)}><path d="M21 12a9 9 0 1 1-3-6.7L21 8" /><path d="M21 3v5h-5" /></svg>);
export const IcSend = (p) => (<svg {...s(p)}><path d="M4 12l16-7-7 16-2-7z" /></svg>);
export const IcCheck = (p) => (<svg {...s({ ...p, strokeWidth: 3 })}><path d="M5 12l5 5L19 6" /></svg>);
export const IcQr = (p) => (<svg {...s(p)}><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 14h3v3M21 14v7h-7" /></svg>);
