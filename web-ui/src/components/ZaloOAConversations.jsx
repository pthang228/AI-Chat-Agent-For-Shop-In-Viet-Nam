import { zalooa } from "../zaloOaApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách hàng kênh Zalo OA — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
export default function ZaloOAConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: zalooa.accounts, conversations: zalooa.conversations, conversation: zalooa.conversation,
        toggleBot: zalooa.toggleBot, resetConv: zalooa.resetConv, setOwner: zalooa.setOwner, sendMessage: zalooa.sendMessage,
      }}
      idKey="oa_id"
      tabLabel={(s) => s.name || s.oa_id}
      offlineName="Zalo OA" offlinePort={5010} runModule="app.main_zalo_oa"
      ownerKeys={{ confirm: "cv.set_owner_confirm_oa", ok: "cv.set_owner_ok_oa", title: "cv.set_owner_title_oa" }}
    />
  );
}
