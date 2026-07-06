import { Link } from "react-router-dom";

/*
 * Sidebar dọc kiểu AloChat — dùng cho trang Overview (bảng điều khiển shop).
 * - `active`     : key mục đang chọn (điều khiển highlight)
 * - `onSelect`   : (key) => void  — bấm mục nội bộ (section trong cùng trang)
 * - `collapsed`  : thu gọn chỉ còn icon
 * - `onToggle`   : bật/tắt thu gọn
 * Mục có `to` → điều hướng route thật (Link). Mục có `key` → section nội bộ.
 */

function svg(children) {
  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  );
}
function IcOverview()  { return svg(<><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>); }
function IcChat()      { return svg(<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />); }
function IcBot()       { return svg(<><rect x="4" y="7" width="16" height="12" rx="2.5" /><path d="M12 7V4M9 12h.01M15 12h.01M2 12h2M20 12h2" /></>); }
function IcBroadcast() { return svg(<path d="M3 11l18-7v16L3 15v-4zM3 11v4M8 13.5V19a1 1 0 0 0 1 1h1a1 1 0 0 0 1-1v-4" />); }
function IcPost()      { return svg(<><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></>); }
function IcStats()     { return svg(<path d="M18 20V10M12 20V4M6 20v-6" />); }
function IcBox()       { return svg(<path d="M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5 9-5V8M12 13v8" />); }
function IcGear()      { return svg(<><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></>); }
function IcCollapse()  { return svg(<><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>); }

// Mục điều hướng nội bộ (section) trong trang Overview
function IcOrders() { return svg(<path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4H6zM3 6h18M16 10a4 4 0 0 1-8 0" />); }
function IcUsers()  { return svg(<><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>); }

const SECTIONS = [
  { key: "overview",  label: "Tổng quan",        icon: IcOverview },
  { key: "chat",      label: "Hội thoại",         icon: IcChat },
  { key: "customers", label: "Khách hàng",        icon: IcUsers },
  { key: "chatbot",   label: "Chatbot",           icon: IcBot,       ownerOnly: true },
  { key: "orders",    label: "Đơn hàng",          icon: IcOrders },
  { key: "broadcast", label: "Tin nhắn hàng loạt", icon: IcBroadcast, ownerOnly: true },
  { key: "posts",     label: "Bài viết & bình luận", icon: IcPost, note: "FB + TikTok" },
  { key: "stats",     label: "Thống kê",          icon: IcStats },
];
// Mục điều hướng route thật
const LINKS = [
  { to: "/billing",  label: "Gói dịch vụ", icon: IcBox, ownerOnly: true },
  { to: "/settings", label: "Cài đặt",     icon: IcGear },
];

// staff (nhân viên) chỉ thấy mục vận hành hộp thư — mục quản trị ẩn đi
export default function Sidebar({ active = "overview", onSelect, collapsed = false, onToggle, staff = false }) {
  const sections = SECTIONS.filter((s) => !(staff && s.ownerOnly));
  const links = LINKS.filter((l) => !(staff && l.ownerOnly));
  return (
    <aside className={"sb" + (collapsed ? " collapsed" : "")}>
      <div className="sb-head">
        <Link to="/" className="sb-logo" title="NovaChat">
          <span className="sb-logo-mark">N</span>
          {!collapsed && <span className="sb-logo-txt">Nova<b>Chat</b></span>}
        </Link>
        <button className="sb-collapse" onClick={onToggle} title={collapsed ? "Mở rộng" : "Thu gọn"}>
          <IcCollapse />
        </button>
      </div>

      <nav className="sb-nav">
        {sections.map(({ key, label, icon: Icon, note }) => (
          <button
            key={key}
            className={"sb-item" + (active === key ? " active" : "")}
            onClick={() => onSelect && onSelect(key)}
            title={label}
          >
            <span className="sb-ico"><Icon /></span>
            {!collapsed && (
              <span className="sb-lbl">
                {label}
                {note && <span className="sb-note">{note}</span>}
              </span>
            )}
          </button>
        ))}

        <div className="sb-sep" />

        {links.map(({ to, label, icon: Icon }) => (
          <Link key={to} to={to} className="sb-item" title={label}>
            <span className="sb-ico"><Icon /></span>
            {!collapsed && <span className="sb-lbl">{label}</span>}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
