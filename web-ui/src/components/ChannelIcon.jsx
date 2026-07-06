// Icon kênh THẬT (logo thương hiệu SVG từ brandIcons.jsx) dùng thống nhất toàn app
// — thay cho emoji tự đặt (💬✉️✈️🎵🛒💼) trước đây.
//
// - CH_ICONS: map key kênh → component logo (mark trắng, nổi trên nền màu brand).
// - <ChannelTile ch size />: ô vuông bo góc màu thương hiệu + logo trắng bên trong
//   (dùng cho chip, tab, tiêu đề, modal chọn kênh...). Nền màu lấy tự động theo
//   kênh, override được qua prop color.

import {
  IcZalo, IcZaloOA, IcMessenger, IcInstagram, IcTelegram, IcTikTok, IcShopee, IcWebChat,
} from "./brandIcons.jsx";

export const CH_ICONS = {
  zalo: IcZalo,
  zalooa: IcZaloOA,
  meta: IcMessenger,
  messenger: IcMessenger,
  instagram: IcInstagram,
  telegram: IcTelegram,
  tiktok: IcTikTok,
  shopee: IcShopee,
  webchat: IcWebChat,
};

export const CH_COLORS = {
  zalo: "#0068ff",
  zalooa: "#005AE0",
  webchat: "#4F46E5",
  meta: "#7b3fb3",
  messenger: "#7b3fb3",
  instagram: "#7b3fb3",
  telegram: "#229ED9",
  tiktok: "#161823",
  shopee: "#EE4D2D",
};

export function ChannelIcon({ ch, size = 20, ...rest }) {
  const C = CH_ICONS[ch] || IcZalo;
  return <C width={size} height={size} {...rest} />;
}

export function ChannelTile({ ch, size = 20, color, style, ...rest }) {
  const C = CH_ICONS[ch] || IcZalo;
  const bg = color || CH_COLORS[ch] || "#0068ff";
  return (
    <span
      className="ch-tile"
      style={{ width: size, height: size, background: bg, borderRadius: Math.max(4, size * 0.26), ...style }}
      {...rest}
    >
      <C width={size * 0.68} height={size * 0.68} />
    </span>
  );
}
