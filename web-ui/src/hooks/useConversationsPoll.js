import { useEffect } from "react";

// Chu kỳ tự làm mới danh sách hội thoại — dùng chung cho mọi màn kênh.
export const POLL_MS = 8000;

/* Hook polling chung cho các màn danh sách hội thoại:
 * - Gọi refresh(true) NGAY khi deps đổi (lượt tải đầu — component tự reset state).
 * - Sau đó gọi refresh(false) mỗi 8s (lượt tự làm mới — component tự quyết
 *   có tải lại không, vd. đang ở trang sau thì bỏ qua để không giật danh sách).
 * - enabled=false → không làm gì (vd. Meta chưa chọn Page).
 */
export default function useConversationsPoll(refresh, deps, { enabled = true } = {}) {
  useEffect(() => {
    if (!enabled) return;
    refresh(true);
    const timer = setInterval(() => refresh(false), POLL_MS);
    return () => clearInterval(timer);
    // refresh là closure mới mỗi render — deps do caller kiểm soát (giống 6 bản gốc)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);
}
