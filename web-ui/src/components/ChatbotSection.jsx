import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../i18n.jsx";
import { shopApi, getActiveShop, setActiveShop } from "../shopApi.js";
import AppsGrid from "./AppsGrid.jsx";
import BotTester from "./BotTester.jsx";
import PhotoLibrary from "./PhotoLibrary.jsx";

/*
 * Mục "Chatbot" — SHOP CON THẬT (server /auth/shops, không còn localStorage):
 *   Mỗi shop = 1 workspace ĐỘC LẬP: kênh, hội thoại, khách, đơn, não AI riêng;
 *   gói cước dùng chung tài khoản. Mỗi shop chỉ thêm 1 bot MỖI LOẠI kênh
 *   (backend chặn 409). Đổi tab shop = đổi shop TOÀN APP (header X-Shop) →
 *   reload để mọi mục (Hội thoại/Khách/Đơn/Broadcast/Thống kê) nạp đúng shop.
 */

function QuickAdd({ placeholder, onAdd, onCancel }) {
  const { t } = useI18n();
  const [val, setVal] = useState("");
  function submit(e) {
    e.preventDefault();
    const v = val.trim();
    if (v) { onAdd(v); setVal(""); }
  }
  return (
    <form className="cb-quickadd" onSubmit={submit}>
      <input autoFocus value={val} placeholder={placeholder}
             onChange={(e) => setVal(e.target.value)}
             onKeyDown={(e) => { if (e.key === "Escape") onCancel(); }} />
      <button type="submit" className="btn-primary sm">{t("cb.add")}</button>
      <button type="button" className="btn-ghost sm" onClick={onCancel}>{t("cb.cancel")}</button>
    </form>
  );
}

export default function ChatbotSection() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [shops, setShops] = useState(null);   // null=đang tải | mảng | "offline"
  const [addingShop, setAddingShop] = useState(false);
  const [chStat, setChStat] = useState({ total: null, on: null });
  const [showTester, setShowTester] = useState(false);

  useEffect(() => {
    shopApi.list().then((r) => {
      if (r.ok && Array.isArray(r.body)) setShops(r.body);
      else setShops("offline");
    });
  }, []);

  if (shops === null) return <div className="empty"><p>{t("app.loading_list")}</p></div>;
  if (shops === "offline") return <div className="empty"><p>{t("app.offline")}</p></div>;

  const defaultWs = shops.find((s) => s.is_default)?.ws || "";
  const saved = getActiveShop();
  const activeWs = shops.some((s) => s.ws === saved) ? saved : defaultWs;
  const shop = shops.find((s) => s.ws === activeWs);
  const shopName = (s) => s?.name || t("cb.my_shop");

  // Đổi shop = đổi workspace TOÀN APP → reload cho mọi mục nạp lại đúng shop
  function switchShop(ws) {
    if (ws === activeWs) return;
    setActiveShop(ws === defaultWs ? "" : ws);
    window.location.reload();
  }
  async function addShop(name) {
    const r = await shopApi.create(name);
    if (r.ok && r.body?.ok) { setActiveShop(r.body.shop.ws); window.location.reload(); }
    else alert("❌ " + (r.body?.error || "Lỗi tạo shop"));
  }
  async function renameShop(ws) {
    const cur = shops.find((s) => s.ws === ws);
    const name = prompt(t("cb.rename_prompt"), cur?.name || "");
    if (!name || !name.trim()) return;
    const r = await shopApi.rename(ws, name.trim());
    if (r.ok && r.body?.ok) window.location.reload();
    else alert("❌ " + (r.body?.error || "Lỗi đổi tên"));
  }
  async function removeShop(ws) {
    if (shops.length <= 1) { alert(t("cb.keep_one")); return; }
    if (!confirm(t("cb.del_confirm"))) return;
    const r = await shopApi.remove(ws);
    if (r.ok && r.body?.ok) {
      if (getActiveShop() === ws) setActiveShop("");
      window.location.reload();
    } else alert("❌ " + (r.body?.error || "Lỗi xoá shop"));
  }

  return (
    <div className="cb">
      {/* ── Thanh chọn shop (server) ── */}
      <div className="cb-shops">
        {shops.map((s) => (
          <button key={s.ws}
                  className={"cb-shop-tab" + (s.ws === activeWs ? " active" : "")}
                  onClick={() => switchShop(s.ws)}>
            <span className="cb-shop-ic">🏬</span>
            <span className="cb-shop-name">{shopName(s)}</span>
          </button>
        ))}
        {addingShop
          ? <QuickAdd placeholder={t("cb.new_shop_ph")} onAdd={addShop} onCancel={() => setAddingShop(false)} />
          : <button className="cb-add-shop" onClick={() => setAddingShop(true)}>{t("cb.add_shop")}</button>}
      </div>

      {!shop ? (
        <div className="empty"><p>{t("cb.no_shops")}</p></div>
      ) : (
        <>
          {/* ── Đầu shop: tên + Dạy AI cấp shop ── */}
          <div className="cb-shop-head">
            <div>
              <h3>{shopName(shop)}</h3>
              <span className="page-sub">
                {chStat.total != null
                  ? t("cb.ai_count", { n: chStat.total }) + (chStat.on != null ? t("cb.ai_on", { n: chStat.on }) : "")
                  : t("cb.ai_sub")}
              </span>
            </div>
            <div className="cb-shop-actions">
              <button className="cb-teach" onClick={() => nav("/prompt")}
                      title={t("cb.teach_title")}>
                {t("cb.teach")}
              </button>
              <button className={"btn-outline sm" + (showTester ? " active" : "")}
                      style={{ width: "auto" }}
                      onClick={() => setShowTester((v) => !v)}
                      title={t("cb.test_title")}>
                {t("cb.test")}
              </button>
              <button className="btn-ghost sm" onClick={() => renameShop(shop.ws)}>{t("cb.rename")}</button>
              {!shop.is_default && (
                <button className="btn-mini danger" onClick={() => removeShop(shop.ws)}>{t("cb.del_shop")}</button>
              )}
            </div>
          </div>

          <p className="cb-hint">
            {t("cb.hint1")}<b>{t("cb.hint_b1")}</b>{t("cb.hint2")}<b>{t("cb.hint_b2")}</b>
            {t("cb.hint3")}<b>{t("cb.hint_b3")}</b>{t("cb.hint4")}
          </p>

          {showTester && <BotTester onClose={() => setShowTester(false)} />}

          {/* ── Con AI = kênh CỦA SHOP NÀY (server lọc theo header X-Shop) ── */}
          <AppsGrid key={activeWs} onStats={setChStat} />

          {/* ── Thư viện ảnh — bộ ảnh theo shop (tenant = shop đang chọn) ── */}
          <PhotoLibrary />
        </>
      )}
    </div>
  );
}
