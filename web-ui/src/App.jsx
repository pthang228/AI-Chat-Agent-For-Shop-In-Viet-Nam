import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import AppDetail from "./pages/AppDetail.jsx";
import Settings from "./pages/Settings.jsx";
import Billing from "./pages/Billing.jsx";
import PromptBuilder from "./pages/PromptBuilder.jsx";
import Overview from "./pages/Overview.jsx";
import AdminDashboard from "./pages/AdminDashboard.jsx";
import AdminShopDetail from "./pages/AdminShopDetail.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import AdminCopilot from "./components/AdminCopilot.jsx";
import { currentUser, isStaff } from "./auth.js";

function Protected({ children }) {
  return currentUser() ? children : <Navigate to="/login" replace />;
}

// Trang quản trị chỉ dành cho CHỦ — nhân viên (staff) gõ URL thẳng cũng bị đẩy về "/"
function OwnerOnly({ children }) {
  if (!currentUser()) return <Navigate to="/login" replace />;
  return isStaff() ? <Navigate to="/" replace /> : children;
}

// "/" = trang bán hàng cho khách lạ, bảng điều khiển (shell + sidebar) cho người đã đăng nhập
function Home() {
  return currentUser() ? <Overview /> : <Landing />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/" element={<Home />} />
        <Route path="/app/:id" element={<Protected><AppDetail /></Protected>} />
        <Route path="/settings" element={<Protected><Settings /></Protected>} />
        <Route path="/billing" element={<OwnerOnly><Billing /></OwnerOnly>} />
        <Route path="/prompt" element={<OwnerOnly><PromptBuilder /></OwnerOnly>} />
        {/* Khu quản trị NỀN TẢNG — trang tự đẩy về "/" nếu backend trả 403 */}
        <Route path="/admin" element={<OwnerOnly><AdminDashboard /></OwnerOnly>} />
        <Route path="/admin/shop/:username" element={<OwnerOnly><AdminShopDetail /></OwnerOnly>} />
        <Route path="/overview" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Đã đăng nhập → Trợ lý QUẢN TRỊ (giúp chủ vận hành; nhân viên không có
          quyền copilot — backend chặn nên ẩn luôn FAB); chưa → Mi tư vấn bán hàng */}
      {currentUser() ? (!isStaff() && <AdminCopilot />) : <ChatWidget />}
    </BrowserRouter>
  );
}
