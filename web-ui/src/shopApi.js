// SHOP CON — nhiều shop trong 1 tài khoản (bridge 5005, /auth/shops).
// Shop đang chọn lưu localStorage hb_shop; http.js tự đính header X-Shop
// vào MỌI request nên đổi shop = đổi workspace toàn app.
import { makeClient, getActiveShop, setActiveShop } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export { getActiveShop, setActiveShop };

export const shopApi = {
  list: () => j("/auth/shops"),
  create: (name) => j("/auth/shops", { method: "POST", json: { name } }),
  rename: (ws, name) =>
    j(`/auth/shops/${encodeURIComponent(ws)}/rename`, { method: "POST", json: { name } }),
  remove: (ws) => j(`/auth/shops/${encodeURIComponent(ws)}`, { method: "DELETE" }),
};
