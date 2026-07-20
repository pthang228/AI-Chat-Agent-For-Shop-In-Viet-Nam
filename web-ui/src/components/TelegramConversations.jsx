import { tg } from "../telegramApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách hàng kênh Telegram — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
export default function TelegramConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: tg.bots, conversations: tg.conversations, conversation: tg.conversation,
        toggleBot: tg.toggleBot, resetConv: tg.resetConv, setOwner: tg.setOwner, sendMessage: tg.sendMessage,
      }}
      idKey="bot_id"
      tabLabel={(b) => `@${b.username || b.bot_id}`}
      offlineName="Telegram" offlinePort={5007} runModule="app.main_telegram"
      ownerKeys={{ confirm: "cv.set_owner_confirm_tg", ok: "cv.set_owner_ok_home", title: "cv.set_owner_title_home" }}
    />
  );
}
