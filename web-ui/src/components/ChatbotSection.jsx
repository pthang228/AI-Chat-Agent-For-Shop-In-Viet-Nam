import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { useI18n } from "../i18n.jsx";
import AppsGrid from "./AppsGrid.jsx";
import BotTester from "./BotTester.jsx";
import PhotoLibrary from "./PhotoLibrary.jsx";

/*
 * Mục "Chatbot" (mô hình AloChat):
 *   Shop  →  nhiều "con AI" (chính là các KÊNH: Zalo, Meta, Telegram, TikTok).
 *   Mỗi shop DÙNG CHUNG 1 bộ não → nút "Dạy AI" đặt ở cấp SHOP.
 * Danh sách shop lưu localStorage (hb_chatbots); kênh lấy từ AppsGrid (backend 5005).
 * LƯU Ý: backend hiện single-tenant nên mọi shop tạm dùng chung tập kênh — khi có
 * API gắn kênh theo shop_id thì truyền shopId xuống AppsGrid là xong.
 */
const KEY = "hb_chatbots";
const uid = () => Math.random().toString(36).slice(2, 10);

function loadData() {
  try {
    const d = JSON.parse(localStorage.getItem(KEY));
    if (d && Array.isArray(d.shops)) return { shops: d.shops.map((s) => ({ id: s.id, name: s.name })) };
  } catch { /* ignore */ }
  return { shops: [] };
}
function saveData(d) { localStorage.setItem(KEY, JSON.stringify(d)); }

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
  const user = currentUser();
  const [data, setData] = useState(loadData);
  const [activeShop, setActiveShop] = useState(null);
  const [addingShop, setAddingShop] = useState(false);
  const [chStat, setChStat] = useState({ total: null, on: null });
  const [showTester, setShowTester] = useState(false);

  // Seed 1 shop mặc định lần đầu (tên từ tài khoản); nhớ shop đang chọn qua phiên
  useEffect(() => {
    if (data.shops.length === 0) {
      const name = user?.homestay || user?.username || t("cb.my_shop");
      const seed = { shops: [{ id: uid(), name }] };
      setData(seed); saveData(seed); setActiveShop(seed.shops[0].id);
    } else if (!activeShop) {
      const saved = localStorage.getItem("hb_active_shop");
      const found = data.shops.find((s) => s.id === saved);
      setActiveShop(found ? saved : data.shops[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function chooseShop(id) { setActiveShop(id); localStorage.setItem("hb_active_shop", id); }

  function commit(next) { setData(next); saveData(next); }

  function addShop(name) {
    const shop = { id: uid(), name };
    commit({ shops: [...data.shops, shop] });
    setActiveShop(shop.id); setAddingShop(false);
  }
  function renameShop(id) {
    const cur = data.shops.find((s) => s.id === id);
    const name = prompt(t("cb.rename_prompt"), cur?.name || "");
    if (name && name.trim())
      commit({ shops: data.shops.map((s) => s.id === id ? { ...s, name: name.trim() } : s) });
  }
  function removeShop(id) {
    if (data.shops.length <= 1) { alert(t("cb.keep_one")); return; }
    if (!confirm(t("cb.del_confirm"))) return;
    const shops = data.shops.filter((s) => s.id !== id);
    commit({ shops });
    if (activeShop === id) setActiveShop(shops[0]?.id || null);
  }

  const shop = data.shops.find((s) => s.id === activeShop);

  return (
    <div className="cb">
      {/* ── Thanh chọn shop ── */}
      <div className="cb-shops">
        {data.shops.map((s) => (
          <button key={s.id}
                  className={"cb-shop-tab" + (s.id === activeShop ? " active" : "")}
                  onClick={() => chooseShop(s.id)}>
            <span className="cb-shop-ic">🏬</span>
            <span className="cb-shop-name">{s.name}</span>
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
              <h3>{shop.name}</h3>
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
              <button className="btn-ghost sm" onClick={() => renameShop(shop.id)}>{t("cb.rename")}</button>
              <button className="btn-mini danger" onClick={() => removeShop(shop.id)}>{t("cb.del_shop")}</button>
            </div>
          </div>

          <p className="cb-hint">
            {t("cb.hint1")}<b>{t("cb.hint_b1")}</b>{t("cb.hint2")}<b>{t("cb.hint_b2")}</b>
            {t("cb.hint3")}<b>{t("cb.hint_b3")}</b>{t("cb.hint4")}
          </p>

          {showTester && <BotTester onClose={() => setShowTester(false)} />}

          {/* ── Con AI = các kênh CỦA SHOP NÀY (key theo shop → remount khi đổi shop) ── */}
          <AppsGrid key={activeShop} shopId={activeShop}
                    isDefaultShop={data.shops[0]?.id === activeShop}
                    onStats={setChStat} />

          {/* ── Thư viện ảnh — bộ ảnh đặt tên để bot gửi khách ── */}
          <PhotoLibrary />
        </>
      )}
    </div>
  );
}
