// TIN NHẮN HÀNG LOẠT (broadcast/remarketing) — bridge 5005, chỉ CHỦ (owner).
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

const json = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const broadcastApi = {
  preview: (channels, segment) => j("/broadcasts/preview", json("POST", { channels, segment })),
  list: () => j("/broadcasts"),
  create: (payload) => j("/broadcasts", json("POST", payload)),
  get: (id) => j("/broadcasts/" + id),
  send: (id) => j(`/broadcasts/${id}/send`, { method: "POST" }),
  cancel: (id) => j(`/broadcasts/${id}/cancel`, { method: "POST" }),
};
