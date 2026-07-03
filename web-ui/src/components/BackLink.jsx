import { useNavigate } from "react-router-dom";
import { IcBack } from "./icons.jsx";

// Nút "Quay lại" rõ ràng cho các trang chức năng. Mặc định về Dashboard ("/").
export default function BackLink({ to = "/", label = "Quay lại" }) {
  const nav = useNavigate();
  return (
    <button className="backlink" onClick={() => nav(to)}>
      <span className="backlink-ico"><IcBack width={16} height={16} /></span>
      {label}
    </button>
  );
}
