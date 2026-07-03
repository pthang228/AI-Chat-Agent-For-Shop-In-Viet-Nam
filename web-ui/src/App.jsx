import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Landing from "./pages/Landing.jsx";
import Login from "./pages/Login.jsx";
import Register from "./pages/Register.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import AppDetail from "./pages/AppDetail.jsx";
import Settings from "./pages/Settings.jsx";
import Billing from "./pages/Billing.jsx";
import PromptBuilder from "./pages/PromptBuilder.jsx";
import ChatWidget from "./components/ChatWidget.jsx";
import { currentUser } from "./auth.js";

function Protected({ children }) {
  return currentUser() ? children : <Navigate to="/login" replace />;
}

// "/" = trang bán hàng cho khách lạ, dashboard cho người đã đăng nhập
function Home() {
  return currentUser() ? <Dashboard /> : <Landing />;
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
        <Route path="/billing" element={<Protected><Billing /></Protected>} />
        <Route path="/prompt" element={<Protected><PromptBuilder /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      {/* Bong bóng chat tư vấn dịch vụ — hiện ở MỌI trang */}
      <ChatWidget />
    </BrowserRouter>
  );
}
