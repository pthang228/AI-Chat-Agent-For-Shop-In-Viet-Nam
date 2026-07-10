import { useNavigate } from "react-router-dom";
import { IcBack } from "./icons.jsx";
import { useI18n } from "../i18n.jsx";

// Nút "Quay lại" cho các trang chức năng — về TRANG TRƯỚC ĐÓ (history back).
// Chỉ khi không có trang trước trong app (mở link trực tiếp/tab mới) mới rơi về
// `to` (mặc định Tổng quan "/"). React Router lưu chỉ số điều hướng ở
// history.state.idx — idx > 0 nghĩa là có trang trước để lùi.
export default function BackLink({ to = "/", label }) {
  const { t } = useI18n();
  if (!label) label = t("back");
  const nav = useNavigate();
  function goBack() {
    if (window.history.state?.idx > 0) nav(-1);
    else nav(to);
  }
  return (
    <button className="backlink" onClick={goBack}>
      <span className="backlink-ico"><IcBack width={16} height={16} /></span>
      {label}
    </button>
  );
}
