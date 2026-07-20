import { webchat } from "../webchatApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách kênh Website — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
export default function WebChatConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: webchat.sites, conversations: webchat.conversations, conversation: webchat.conversation,
        toggleBot: webchat.toggleBot, resetConv: webchat.resetConv, setOwner: webchat.setOwner, sendMessage: webchat.sendMessage,
      }}
      idKey="site_id"
      tabLabel={(s) => s.name || s.site_id}
      offlineName="Webchat" offlinePort={5011} runModule="app.main_webchat"
      ownerKeys={{ confirm: "cv.set_owner_confirm_site", ok: "cv.set_owner_ok_site", title: "cv.set_owner_title_site" }}
      emptyKey="cv.web_empty"
    />
  );
}
