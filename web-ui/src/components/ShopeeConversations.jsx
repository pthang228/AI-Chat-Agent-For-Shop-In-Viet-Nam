import { shopee } from "../shopeeApi.js";
import ChannelConversations from "./ChannelConversations.jsx";

// Khách hàng kênh Shopee — wrapper mỏng, toàn bộ UI ở ChannelConversations (dedup 6 kênh).
export default function ShopeeConversations() {
  return (
    <ChannelConversations
      api={{
        listAccounts: shopee.shops, conversations: shopee.conversations, conversation: shopee.conversation,
        toggleBot: shopee.toggleBot, resetConv: shopee.resetConv, setOwner: shopee.setOwner, sendMessage: shopee.sendMessage,
      }}
      idKey="shop_id"
      tabLabel={(s) => s.name || s.shop_id}
      offlineName="Shopee" offlinePort={5009} runModule="app.main_shopee"
      ownerKeys={{ confirm: "cv.set_owner_confirm_shop", ok: "cv.set_owner_ok_shop", title: "cv.set_owner_title_shop" }}
    />
  );
}
