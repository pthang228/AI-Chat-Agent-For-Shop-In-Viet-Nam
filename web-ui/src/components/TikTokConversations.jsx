import { tiktok } from "../tiktokApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách hàng kênh TikTok — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
export default function TikTokConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: tiktok.accounts, conversations: tiktok.conversations, conversation: tiktok.conversation,
        toggleBot: tiktok.toggleBot, resetConv: tiktok.resetConv, setOwner: tiktok.setOwner, sendMessage: tiktok.sendMessage,
      }}
      idKey="business_id"
      tabLabel={(a) => a.name || a.username || a.business_id}
      offlineName="TikTok" offlinePort={5008} runModule="app.main_tiktok"
      ownerKeys={{ confirm: "cv.set_owner_confirm_home", ok: "cv.set_owner_ok_home", title: "cv.set_owner_title_home" }}
    />
  );
}
