// TEAM — quản lý nhân viên (chủ) + danh sách thành viên workspace (mọi người).
// Backend: bridge 5005 (auth_api). /team* chỉ CHỦ; /teammates cả nhân viên đọc được.
// j = httpClient chung (api/http.js): tự gắn Bearer + bắt 401 + offline → status 0.
import { makeClient } from "./api/http.js";
import { HOST } from "./apiConfig.js";

const j = makeClient(HOST.bridge);

const json = (method, body) => ({
  method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const teamApi = {
  list: () => j("/team"),
  add: (email, name, password) => j("/team", json("POST", { email, name, password })),
  update: (username, patch) => j("/team/" + encodeURIComponent(username), json("PATCH", patch)),
  remove: (username) => j("/team/" + encodeURIComponent(username), { method: "DELETE" }),
  teammates: () => j("/teammates"),
};
