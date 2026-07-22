import { useEffect, useState } from "react";
import { shopApi, getActiveShop, setActiveShop } from "../shopApi.js";
import { useI18n } from "../i18n.jsx";

/*
 * Chọn SHOP CON đang làm việc — hiện ở topbar khi tài khoản có ≥2 shop.
 * Đổi shop = đổi workspace TOÀN APP (http.js đính header X-Shop) → reload
 * để mọi mục (Hội thoại/Khách/Đơn/Chatbot/Broadcast/Thống kê) nạp đúng shop.
 */
export default function ShopSwitcher() {
  const { t } = useI18n();
  const [shops, setShops] = useState([]);
  useEffect(() => {
    shopApi.list().then((r) => { if (r.ok && Array.isArray(r.body)) setShops(r.body); });
  }, []);
  if (shops.length < 2) return null;
  const defaultWs = shops.find((s) => s.is_default)?.ws || "";
  const saved = getActiveShop();
  const activeWs = shops.some((s) => s.ws === saved) ? saved : defaultWs;
  return (
    <select className="shop-switch" value={activeWs}
            onChange={(e) => {
              const ws = e.target.value;
              setActiveShop(ws === defaultWs ? "" : ws);
              window.location.reload();
            }}>
      {shops.map((s) => (
        <option key={s.ws} value={s.ws}>🏬 {s.name || t("cb.my_shop")}</option>
      ))}
    </select>
  );
}
