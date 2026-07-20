import { meta } from "../metaApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách hàng kênh Meta — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
// Nét riêng Meta: API trả mảng thẳng (chưa phân trang), TÁCH RIÊNG theo từng Page
// (không có tab "Tất cả", tự chọn Page đầu), không có nút "Đặt làm chủ".
export default function MetaConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: meta.pages, conversations: meta.conversations, conversation: meta.conversation,
        toggleBot: meta.toggleBot, resetConv: meta.resetConv, sendMessage: meta.sendMessage,
      }}
      idKey="page_id"
      tabLabel={(p) => p.name || p.page_id}
      offlineName="Meta" offlinePort={5006} runModule="app.main_meta"
      paged={false}
      allTab={false}
      emptyKey="cv.meta_empty"
      noAccountsKeys={{ msg: "cv.meta_no_pages", pre: "cv.meta_hint_pre", tab: "cv.meta_hint_tab", post: "cv.meta_hint_post" }}
      currentLabelKey="cv.meta_customers_of"
      showCheckin
    />
  );
}
