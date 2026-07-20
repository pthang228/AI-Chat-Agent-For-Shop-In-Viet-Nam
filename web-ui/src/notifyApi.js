// Liên hệ khẩn cấp & Thông báo — bridge 5005, chỉ CHỦ shop (owner).
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

export const notifyApi = {
  get: () => j("/notify/config"),
  set: (config) => j("/notify/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  }),
};
