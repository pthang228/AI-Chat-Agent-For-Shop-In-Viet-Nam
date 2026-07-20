import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { currentUser, isStaff } from "./auth.js";

// CODE-SPLITTING: mỗi trang lớn 1 chunk riêng (React.lazy) — người dùng chỉ tải
// đúng trang đang mở thay vì cả bundle ~1MB. Login/Landing cũng lazy để khách
// lạ không phải tải Dashboard/Admin và ngược lại.
const Landing = lazy(() => import("./pages/Landing.jsx"));
const Login = lazy(() => import("./pages/Login.jsx"));
const Register = lazy(() => import("./pages/Register.jsx"));
const ForgotPassword = lazy(() => import("./pages/ForgotPassword.jsx"));
const AppDetail = lazy(() => import("./pages/AppDetail.jsx"));
const Settings = lazy(() => import("./pages/Settings.jsx"));
const Billing = lazy(() => import("./pages/Billing.jsx"));
const PromptBuilder = lazy(() => import("./pages/PromptBuilder.jsx"));
const Overview = lazy(() => import("./pages/Overview.jsx"));
const AdminDashboard = lazy(() => import("./pages/AdminDashboard.jsx"));
const AdminShopDetail = lazy(() => import("./pages/AdminShopDetail.jsx"));
const ChatWidget = lazy(() => import("./components/ChatWidget.jsx"));
const AdminCopilot = lazy(() => import("./components/AdminCopilot.jsx"));

// Fallback khi chunk trang đang tải — dùng spinner sẵn có của design (index.css)
function PageLoading() {
  return (
    <div className="stats-loading" style={{ minHeight: "60vh" }}>
      <span className="stats-spinner" />
    </div>
  );
}

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
      <Suspense fallback={<PageLoading />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route path="/forgot" element={<ForgotPassword />} />
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
            quyền copilot — backend chặn nên ẩn luôn FAB); chưa → Mi tư vấn bán hàng.
            Widget nổi tải nền (lazy) — fallback null, không chặn trang chính. */}
        <Suspense fallback={null}>
          {currentUser() ? (!isStaff() && <AdminCopilot />) : <ChatWidget />}
        </Suspense>
      </Suspense>
    </BrowserRouter>
  );
}
