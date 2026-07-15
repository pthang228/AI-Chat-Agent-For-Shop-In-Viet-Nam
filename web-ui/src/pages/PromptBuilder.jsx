import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser, getToken } from "../auth.js";
import { HOST } from "../apiConfig.js";
import { promptApi } from "../promptApi.js";
import { billing as billingApi } from "../billingApi.js";
import { IcHome, IcBack } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import BackLink from "../components/BackLink.jsx";
import { NotifyCard, BankCard, CannedCard } from "../components/ShopConfigCards.jsx";
import StyleLibrary from "../components/StyleLibrary.jsx";
import { InterviewCard, ReportCard, HealthCard } from "../components/TeachCards.jsx";
import { useI18n } from "../i18n.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

/* ── Form gợi ý có cấu trúc — shop không cần biết "viết prompt" ──
 * Chia 5 nhóm, ~20 ô — chi tiết ngang prompt mẫu gốc. Bỏ trống ô không có;
 * hệ thống ghép các ô thành hướng dẫn có nhãn cho AI.
 * Tiêu đề nhóm / nhãn / placeholder HIỂN THỊ qua i18n: pb.sec.* / pb.f.<key> / pb.ph.<key> */
const GUIDE_SECTIONS = [
  { tKey: "pb.sec.basic",  fields: [{ key: "about" }, { key: "branches", rows: 2 }, { key: "hours" }, { key: "contact" }] },
  { tKey: "pb.sec.price",  fields: [{ key: "services", rows: 8 }, { key: "surcharge", rows: 2 }, { key: "promos" }] },
  { tKey: "pb.sec.policy", fields: [{ key: "booking", rows: 2 }, { key: "deposit", rows: 4 }, { key: "reschedule", rows: 2 }, { key: "cancel", rows: 2 }] },
  { tKey: "pb.sec.amen",   fields: [{ key: "amenities", rows: 3 }, { key: "equipment", rows: 3 }, { key: "capacity", rows: 2 }, { key: "forbidden", rows: 2 }] },
  { tKey: "pb.sec.talk",   fields: [{ key: "tone" }, { key: "greeting", rows: 3 }, { key: "rules", rows: 2 }, { key: "faq", rows: 4 }] },
];
const GUIDE_FIELDS = GUIDE_SECTIONS.flatMap((s) => s.fields);
/* NHÃN GỬI CHO AI/BACKEND — buildInstructions() ghép các nhãn này vào hướng dẫn
 * cho AI đọc → GIỮ TIẾNG VIỆT, KHÔNG dịch (UI hiển thị bản dịch pb.f.* riêng). */
const GUIDE_LABEL = {
  about: "Tên shop & loại hình",
  branches: "Địa chỉ các cơ sở",
  hours: "Giờ hoạt động",
  contact: "SĐT · kênh liên hệ",
  services: "Dịch vụ / sản phẩm & GIÁ TỪNG MỤC (quan trọng nhất)",
  surcharge: "Phụ thu (cuối tuần · lễ · thêm người…)",
  promos: "Khuyến mãi đang chạy",
  booking: "Cách đặt chỗ / giữ chỗ",
  deposit: "Đặt cọc & thanh toán (quy trình TỪNG BƯỚC)",
  reschedule: "Đổi / dời lịch",
  cancel: "Huỷ & hoàn tiền",
  amenities: "Tiện ích nổi bật",
  equipment: "Trang thiết bị / đồ dùng có sẵn",
  capacity: "Sức chứa · thêm người · thú cưng",
  forbidden: "Khách KHÔNG được làm",
  tone: "Xưng hô & giọng điệu",
  greeting: "Tin nhắn chào ĐẦU TIÊN (bot gửi đúng đoạn này)",
  rules: "Điều bot KHÔNG được làm",
  faq: "Câu hỏi thường gặp & cách trả lời",
};

/* Mẫu điền sẵn theo ngành — bấm 1 nút có ví dụ hoàn chỉnh để sửa.
 * Mẫu Homestay chi tiết nhất (dữ liệu HƯ CẤU) — làm chuẩn "điền đủ là thế nào". */
const SAMPLES = {
  "💆 Spa / Salon": {
    about: "Mây Spa — spa thư giãn & chăm sóc da",
    branches: "12 Lê Lợi, Quận 1, TP.HCM (có chỗ gửi xe máy trước cửa)",
    hours: "9h–21h hằng ngày, nhận khách cuối cùng 20h",
    contact: "0901 234 567 (gọi/Zalo) · fanpage fb.com/mayspa",
    services: "Massage body 60 phút — 350k\nMassage body 90 phút — 480k\nChăm sóc da mặt cơ bản 45p — 300k\nGội đầu dưỡng sinh 30p — 150k\nCombo massage 90p + chăm sóc da — 700k (giảm từ 780k)",
    surcharge: "Sau 19h phụ thu 50k/lượt · Chọn kỹ thuật viên riêng +50k",
    promos: "Khách lần đầu giảm 10% mọi dịch vụ · Mua gói 10 buổi tặng 1",
    booking: "Đặt lịch trước ít nhất 2 tiếng · Đến trễ 15 phút tự huỷ lượt",
    deposit: "Không cần cọc với dịch vụ lẻ · Gói trên 1 triệu cọc 30%",
    reschedule: "Dời lịch miễn phí nếu báo trước 4 tiếng",
    cancel: "Huỷ trước 4 tiếng không mất phí · Huỷ trễ thu 30% giá dịch vụ",
    amenities: "Phòng riêng máy lạnh · Trà gừng miễn phí sau liệu trình · Wifi + tủ khoá đồ",
    equipment: "Khăn, đồ thay, dụng cụ đều tiệt trùng 1 lần/khách",
    capacity: "Nhận nhóm tối đa 4 khách cùng lúc — nhóm đông đặt trước 1 ngày",
    forbidden: "Không nhận khách say xỉn · Không dịch vụ nhạy cảm (từ chối lịch sự)",
    tone: 'Xưng "em", gọi khách "anh/chị", nhẹ nhàng thư giãn, emoji vừa phải 🌿',
    greeting: "Dạ em chào mình ạ 🌿 Mây Spa có thể giúp mình xem dịch vụ, bảng giá hoặc đặt lịch — mình cần gì cứ nhắn em nha!",
    handoff: "Khách khiếu nại chất lượng · Hỏi gói doanh nghiệp/số lượng lớn → báo đã nhắn chủ spa",
    rules: "Không tự giảm giá ngoài chính sách · Không chẩn đoán bệnh da — khuyên tới soi da trực tiếp",
    faq: "Có chỗ gửi ô tô không? → Gửi bãi cách 50m, spa hỗ trợ phí\nNam có làm được không? → Dạ có, kỹ thuật viên nam/nữ đều có",
  },
  "🍜 Quán ăn / Cà phê": {
    about: "Quán Nhà Mình — quán ăn gia đình",
    branches: "45 Trần Phú, Đà Nẵng (gần cầu Rồng 500m)",
    hours: "10h–22h, nghỉ Thứ 2 · Bếp nhận món cuối 21h15",
    contact: "0905 111 222 (gọi/Zalo)",
    services: "Lẩu gà lá é (2-3 người) — 350k\nGà nướng nguyên con — 280k\nCơm niêu thập cẩm — 65k\nRau xào tỏi — 45k\nNước ép / trà trái cây — 25-35k\nBia chai — 20k",
    surcharge: "Phòng lạnh riêng (10-20 khách) phụ thu 100k · Tết & lễ +10% hoá đơn",
    promos: "Nhóm từ 6 người tặng 1 nước ép/người · Sinh nhật tặng chè + hát mừng",
    booking: "Nhận đặt bàn trước qua chat/điện thoại · Nhóm trên 10 người đặt trước 1 ngày · Giữ bàn tối đa 30 phút",
    deposit: "Tiệc trên 2 triệu cọc 30% · Bàn thường không cần cọc",
    reschedule: "Đổi giờ thoải mái nếu báo trước 2 tiếng",
    cancel: "Tiệc đã cọc huỷ trước 1 ngày hoàn 100% cọc, huỷ trong ngày không hoàn",
    amenities: "Chỗ đậu ô tô trước quán · Phòng lạnh riêng cho nhóm · Ghế trẻ em",
    equipment: "",
    capacity: "Sức chứa 80 khách · Phòng riêng 10-20 khách",
    forbidden: "Không mang đồ ăn/uống ngoài vào · Không hút thuốc khu máy lạnh",
    tone: 'Xưng "quán mình", gần gũi, nhiệt tình như người nhà',
    greeting: "Dạ quán Nhà Mình xin chào! 🍜 Mình muốn xem menu, đặt bàn hay hỏi đường tới quán ạ?",
    handoff: "Đặt tiệc trên 20 người · Khiếu nại món ăn → báo đã nhắn chủ quán, chủ gọi lại ngay",
    rules: "Không hứa còn bàn giờ cao điểm khi chưa chắc · Không nhận ship (chỉ dặn khách đặt qua app)",
    faq: "Có ship không? → Quán chưa tự ship, mình đặt qua GrabFood/ShopeeFood nha\nĐi 15 người ngồi được không? → Được ạ, có phòng riêng, quán xếp trước cho mình",
  },
  "🏡 Homestay / Lưu trú": {
    about: "Ban Mai Home & Hướng Dương Home — homestay cho cặp đôi, thuê theo ca hoặc qua đêm (thông tin VÍ DỤ — thay bằng shop của bạn)",
    branches: "Ban Mai Home: 12 Đường Hoa Ban, Phường 3, TP. Đà Lạt\nHướng Dương Home: 45 Đường Đồi Thông, Phường 10, TP. Đà Lạt\nCả 2 cách chợ đêm trung tâm chỉ 2km — đi lại cực tiện",
    hours: "Check-in tự động 24/7, không cần lễ tân, check-in muộn không sao",
    contact: "Nhắn tin fanpage/Zalo này là nhanh nhất",
    services: "BAN MAI — Phòng 201: ca trưa 12h-16h 260k · ca chiều 16h30-20h30 260k · qua đêm 21h-10h30 380k · combo trưa+chiều 490k · combo ca+đêm 590k · nguyên ngày 750k\nBAN MAI — Phòng 202: trưa 11h30-15h30 240k · chiều 16h-20h 240k · đêm 20h30-10h 330k · combo 390k/490k · nguyên ngày 650k\nBAN MAI — Phòng 301: trưa 11h-15h 240k · chiều 15h30-19h30 240k · đêm 20h-10h 330k · combo 390k/490k · nguyên ngày 650k\nHƯỚNG DƯƠNG — Phòng 111: trưa 13h-17h 260k · chiều 17h30-21h30 260k · đêm 22h-11h 370k · combo 450k/550k · nguyên ngày 750k\nHƯỚNG DƯƠNG — Phòng 112: trưa 12h-16h 230k · chiều 16h30-20h30 230k · đêm 21h-10h 330k · combo 390k/490k · nguyên ngày 650k\nHƯỚNG DƯƠNG — Phòng 211: trưa 12h30-16h30 260k · chiều 17h-21h 260k · đêm 21h30-10h30 370k · combo 450k/550k · nguyên ngày 750k\nHƯỚNG DƯƠNG — Phòng 212: trưa 11h30-15h30 230k · chiều 16h-20h 230k · đêm 20h30-10h 330k · combo 390k/490k · nguyên ngày 650k\nHƯỚNG DƯƠNG — Phòng 311: trưa 11h-15h 240k · chiều 15h30-19h30 240k · đêm 20h-10h 340k · combo 400k/500k · nguyên ngày 670k",
    surcharge: "Cuối tuần & ngày lễ +35k/ca (tính trên từng ca kể cả trong combo) · Chuẩn 2 người/phòng, phụ thu từ người thứ 3 · Thú cưng làm bẩn/hư phụ thu 500k",
    promos: "",
    booking: "Booking chỉ giữ 30 phút — chưa cọc sẽ tự huỷ",
    deposit: "Cọc 50% giá phòng (hoặc thanh toán full luôn)\n1. Ngày đặt: cọc 50% + gửi CCCD của 2 người (bắt buộc)\n2. Sau cọc: chốt ca & hẹn ngày → nhận thông tin check-in\n3. 21h đêm trước check-in: thanh toán đủ (bắt buộc trước ít nhất 12 tiếng để nhận mã code)",
    reschedule: "Miễn phí dời 1 lần (báo trước ít nhất 7 ngày) · Dời trước 48h phí 30% tiền phòng · Dời lần 2 phí 30% (dù trước 7 ngày)",
    cancel: "Huỷ trước 5 ngày hoàn 50% cọc · Trước 3 ngày không hoàn cọc · Trước 12 tiếng không hoàn bất kỳ khoản nào",
    amenities: "Check-in tự động không cần lễ tân · Giờ ra vào tự do · Bãi giữ xe riêng (cả ô tô lẫn xe máy) · Được mang đồ ăn vào (làm bẩn giường phụ thu) · 100% không camera ẩn · Cho mang thú cưng",
    equipment: "Mọi phòng: cách âm tốt, máy chiếu + Netflix, máy lạnh, board game cho cặp đôi\nBan Mai KHÔNG có bếp (chỉ bình siêu tốc + chén đũa) · Hướng Dương TẤT CẢ phòng có bếp đủ gia vị\nCả 2 nơi chỉ có nước lọc miễn phí, KHÔNG bán đồ ăn thức uống\nCa qua đêm có sẵn kem đánh răng/bàn chải/khăn tắm; ca ngày yêu cầu thì chuẩn bị · Máy sấy tóc liên hệ mang lên",
    capacity: "Tiêu chuẩn 2 người/phòng — phụ thu từ người thứ 3",
    forbidden: "Hút thuốc trong phòng · Mang chất cấm · Vật dễ cháy nổ · Cố tình phá hoại sẽ báo chính quyền địa phương",
    tone: 'Xưng "mình", thân thiện tự nhiên như bạn bè, câu ngắn, emoji vừa phải 😊 🏠 📅 ✅',
    greeting: 'Admin bên home có thể đang bận nên chưa rep được, để AI tư vấn trước cho mình nhen 😊\nMình có thể giúp bạn:\n📅 Xem lịch trống → nhắn "tối nay còn phòng không"\n💰 Xem bảng giá → nhắn "bảng giá"\n📸 Xem ảnh phòng → nhắn "ảnh phòng 201"\n🏠 Đặt phòng → nhắn "đặt phòng 301 tối nay"',
    handoff: "Khách muốn gặp người thật/admin · Đổi ca-giờ đã đặt (không tự quyết, hỏi chủ giúp) · Câu hỏi ngoài kiến thức → báo đã nhắn chủ nhà, chủ phản hồi sớm",
    rules: "Không tự xác nhận booking cuối cùng — chủ nhà quyết định · Không nhận tiền cọc trực tiếp · Không bịa thông tin, thiếu thì nói chưa có và báo chủ · Không tiết lộ mã cửa qua chat",
    faq: "Gần trung tâm không? → Cả 2 chi nhánh cách chợ đêm trung tâm chỉ 2km\nCó camera không? → 100% không camera ẩn, riêng tư tuyệt đối\nMang đồ ăn vào được không? → Được nha, làm bẩn giường thì phụ thu nhẹ\nCheck-in muộn được không? → Tự động 24/7, muộn mấy cũng được",
  },
  "🛍️ Shop online": {
    about: "Nắng Store — thời trang nữ phong cách tối giản",
    branches: "Kho tại Gò Vấp, TP.HCM (chỉ bán online, không có cửa hàng)",
    hours: "Chốt đơn 8h–22h hằng ngày · Đơn sau 21h ship ngày hôm sau",
    contact: "0912 333 444 (Zalo) · IG @nangstore",
    services: "Váy hoa nhí — 250k (S/M/L)\nÁo sơ mi linen — 220k (trắng/be/xanh)\nSet đồ công sở — 380k\nQuần culottes — 260k\nPhụ kiện túi/khăn — 90-150k",
    surcharge: "Ship nội thành 20k, tỉnh 30k · Freeship đơn từ 300k",
    promos: "Mua 2 sản phẩm giảm 5% · Follow IG giảm thêm 10k",
    booking: "Chốt đơn qua chat: tên + SĐT + địa chỉ + size/màu",
    deposit: "COD toàn quốc — không cần cọc · CK trước giảm 10k phí ship",
    reschedule: "Đổi size/màu trước khi shop bàn giao đơn cho ship (thường trong 2 tiếng)",
    cancel: "Huỷ thoải mái trước khi gửi hàng · Bom hàng 2 lần shop từ chối phục vụ",
    amenities: "Đổi size trong 7 ngày (hàng chưa qua sử dụng, còn tag) · Kiểm hàng trước khi nhận",
    equipment: "",
    capacity: "",
    forbidden: "",
    tone: 'Xưng "shop" — gọi khách "nàng/bạn", ngọt ngào, chốt đơn khéo, emoji 🌸✨',
    greeting: "Nắng Store xin chào nàng 🌸 Nàng muốn xem mẫu nào, shop gửi ảnh + bảng size liền nè!",
    handoff: "Khiếu nại hàng lỗi/thiếu → xin lỗi, xin ảnh/video mở hộp, báo đã chuyển chủ shop xử lý trong ngày",
    rules: "Không hứa ngày giao chính xác — chỉ nói khoảng 2-4 ngày · Không cam kết còn hàng khi chưa check kho · Size ngoài bảng → khuyên inbox số đo để tư vấn",
    faq: "Có được kiểm hàng không? → Dạ được, nàng kiểm thoải mái rồi mới thanh toán\nHàng lỗi thì sao? → Quay video mở hộp, shop đổi mới 100% + chịu phí ship",
  },
};
// Nhãn nút mẫu hiển thị qua i18n — khoá & NỘI DUNG của SAMPLES là dữ liệu điền
// vào form (sẽ GỬI CHO AI khi tạo bộ não) nên giữ nguyên tiếng Việt, không dịch.
const SAMPLE_TKEY = {
  "💆 Spa / Salon": "pb.sample.spa",
  "🍜 Quán ăn / Cà phê": "pb.sample.food",
  "🏡 Homestay / Lưu trú": "pb.sample.home",
  "🛍️ Shop online": "pb.sample.shop",
};

// Trang "Dạy AI": điền form gợi ý (hoặc dán link) → AI viết persona + mẩu tri
// thức → shop duyệt + test thử → dùng. Càng điền đủ ô, bộ não càng chuẩn.
export default function PromptBuilder() {
  const nav = useNavigate();
  const { t } = useI18n();
  const user = currentUser();
  const hostName = user?.homestay || user?.username || "";

  const [cur, setCur] = useState(null);        // prompt đang dùng
  const [showCur, setShowCur] = useState(false);
  const [tpl, setTpl] = useState("");          // prompt mẫu chuẩn
  const [showTpl, setShowTpl] = useState(false);
  // Link dữ liệu: mỗi dòng = {url, note}. note = shop TỰ GHI mục đích/nội dung link
  // → đưa cho AI đọc. Link Google Sheets tự nhận ra qua URL → nối /sheets cho bot
  // tra lịch trực tiếp (KHÔNG đưa vào generate).
  const [links, setLinks] = useState([{ url: "", note: "" }]);
  const [guide, setGuide] = useState({});      // câu trả lời form gợi ý
  const [extra, setExtra] = useState("");      // hướng dẫn thêm tự do
  const [models, setModels] = useState([]);    // catalog model (từ /billing/me)
  const [genModel, setGenModel] = useState(""); // model dùng để DẠY ("" = mặc định)
  const [draft, setDraft] = useState(null);    // persona AI vừa tạo (chờ duyệt)
  const [chunks, setChunks] = useState([]);    // mẩu tri thức đi kèm (chế độ lai)
  const [gaps, setGaps] = useState([]);        // AI đề nghị bổ sung
  const [sources, setSources] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [svcEmail, setSvcEmail] = useState("");  // email service account để shop share Google Sheet

  async function load() {
    const r = await promptApi.current();
    if (r.status === 401) { nav("/login"); return; }
    if (r.ok) setCur(r.body);
    else setCur("offline");
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);
  useEffect(() => {
    billingApi.me().then((r) => {
      if (r.ok && Array.isArray(r.body?.ai_models)) setModels(r.body.ai_models);
    });
    // Email service account (để shop share Google Sheet lịch đặt chỗ cho bot đọc)
    fetch(HOST.bridge + "/sheets", { headers: { Authorization: `Bearer ${getToken()}` } })
      .then((r) => r.json()).then((b) => { if (b?.service_email) setSvcEmail(b.service_email); })
      .catch(() => {});
  }, []);

  async function loadTemplate() {
    if (tpl) { setShowTpl((v) => !v); return; }
    const r = await promptApi.template();
    if (r.ok && r.body?.template) { setTpl(r.body.template); setShowTpl(true); }
    else setMsg(t("pb.tpl.load_fail"));
  }
  function editFromTemplate() {
    if (draft !== null && !confirm(t("pb.tpl.confirm"))) return;
    setDraft(tpl); setChunks([]); setGaps([]); setSources([]); setMsg("");
    setTimeout(() => document.querySelector(".draft-box")?.scrollIntoView({ behavior: "smooth" }), 50);
  }

  function setLink(i, k, v) { setLinks((ls) => ls.map((x, j) => (j === i ? { ...x, [k]: v } : x))); }
  function addLink() { setLinks((ls) => [...ls, { url: "", note: "" }]); }
  function rmLink(i) { setLinks((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [{ url: "", note: "" }])); }
  // Google Sheets: BACKEND tự nhận diện lịch/dữ liệu (đọc mô tả shop ghi +
  // nội dung sheet + AI phân loại khi mơ hồ) — frontend chỉ gửi link + mô tả.
  const isSheetUrl = (u) => /docs\.google\.com\/spreadsheets/i.test(u || "");

  function setG(key, v) { setGuide((g) => ({ ...g, [key]: v })); }
  function fillSample(name) {
    const hasContent = Object.values(guide).some((v) => (v || "").trim());
    if (hasContent && !confirm(t("pb.s1.fill_confirm", { name: t(SAMPLE_TKEY[name]) }))) return;
    setGuide({ ...SAMPLES[name] });
    setMsg("");
  }

  // Ghép form + hướng dẫn thêm thành 1 đoạn hướng dẫn có nhãn rõ ràng cho AI
  function buildInstructions() {
    const parts = [];
    for (const { key } of GUIDE_FIELDS) {
      const v = (guide[key] || "").trim();
      if (v) parts.push(`${GUIDE_LABEL[key].toUpperCase()}:\n${v}`);
    }
    if (extra.trim()) parts.push(`HƯỚNG DẪN THÊM:\n${extra.trim()}`);
    return parts.join("\n\n");
  }

  async function doGenerate() {
    const instructions = buildInstructions();
    // Gửi HẾT link (kể cả Google Sheets) — backend tự nhận diện lịch/dữ liệu
    // theo mô tả + nội dung sheet, kết quả báo lại trong "Kết quả đọc link"
    const linkList = links.filter((l) => l.url.trim())
      .map((l) => ({ url: l.url.trim(), note: (l.note || "").trim() }));
    if (!instructions && linkList.length === 0) {
      setMsg(t("pb.s3.need_input"));
      return;
    }
    setMsg(""); setDraft(null); setChunks([]); setGaps([]); setSources([]);
    setBusy(true);
    const r = await promptApi.generate(linkList, instructions, genModel);
    setBusy(false);
    if (r.ok && r.body?.draft) {
      setDraft(r.body.draft);
      setChunks(r.body.chunks || []);
      setGaps(r.body.gaps || []);
      setSources(r.body.sources || []);
      setTimeout(() => document.querySelector(".draft-box")?.scrollIntoView({ behavior: "smooth" }), 80);
    } else {
      setMsg("❌ " + (r.body?.error || (r.status === 0 ? t("pb.s3.no_server") : t("pb.s3.gen_fail"))));
    }
  }

  async function doApply() {
    if (!confirm(t("pb.apply.confirm"))) return;
    setMsg("");
    const r = await promptApi.apply(draft, chunks.length ? chunks : null);
    if (r.ok) {
      setMsg(t("pb.apply.ok"));
      setDraft(null); setChunks([]); setSources([]);
      load();
    } else {
      setMsg("❌ " + (r.body?.error || t("pb.apply.fail")));
    }
  }

  async function doRestore() {
    if (!confirm(t("pb.restore.confirm"))) return;
    const r = await promptApi.restoreDefault();
    if (r.ok) { setMsg(t("pb.restore.ok")); load(); }
  }

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <LogoMark size={28} /> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title={t("pb.acct_settings")}>
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
        </div>
      </header>

      <main className="content narrow" style={{ maxWidth: 780 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">{t("pb.hello")}</div>
            <h1 className="page-title">{t("pb.title")}</h1>
            <p className="page-sub">{t("pb.sub")}</p>
          </div>
        </div>

        {/* Bộ não đang dùng */}
        {cur && cur !== "offline" && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <b>{t("pb.cur.label")}</b>{" "}
                {cur.source === "custom"
                  ? <span className="badge bot">
                      {cur.mode === "hybrid"
                        ? t("pb.cur.hybrid", { n: cur.chunk_count })
                        : t("pb.cur.custom")}
                      {cur.updated_at ? " " + t("pb.cur.saved", { d: new Date(cur.updated_at).toLocaleString("vi-VN") }) : ""}
                    </span>
                  : <span className="badge stage">{t("pb.cur.default")}</span>}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn-mini" onClick={() => setShowCur((v) => !v)}>
                  {showCur ? t("pb.cur.hide") : t("pb.cur.show")}
                </button>
                {cur.source === "custom" && (
                  <button className="btn-mini danger" onClick={doRestore}>{t("pb.cur.restore")}</button>
                )}
              </div>
            </div>
            {showCur && <pre className="prompt-pre">{cur.prompt}</pre>}
          </div>
        )}
        {cur === "offline" && (
          <div className="empty"><p>{t("pb.offline")}</p></div>
        )}

        {msg && <div className="savemsg" style={{ marginBottom: 14 }}>{msg}</div>}

        {/* ❓ Báo cáo câu bot bí tuần — chỉ hiện khi có (actionable, đặt đầu) */}
        {cur && cur !== "offline" && <ReportCard />}

        {/* 🎙️ AI phỏng vấn — cách dạy không cần điền form; tổng hợp đổ vào ô hướng dẫn */}
        {cur && cur !== "offline" && (
          <InterviewCard onDone={(s) => setExtra((prev) => (prev ? prev + "\n\n" : "") + s)} />
        )}

        {/* Bước 1: kể về shop — form gợi ý theo 5 nhóm */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>{t("pb.s1.title")}</h3>
          <p className="hint">{t("pb.s1.hint")}</p>

          <div className="gw-samples">
            <span className="hint">{t("pb.s1.samples")}</span>
            {Object.keys(SAMPLES).map((name) => (
              <button key={name} type="button" className="gw-sample" onClick={() => fillSample(name)}>
                {t(SAMPLE_TKEY[name])}
              </button>
            ))}
          </div>

          {GUIDE_SECTIONS.map((sec, si) => {
            const filled = sec.fields.filter((f) => (guide[f.key] || "").trim()).length;
            return (
              <details key={sec.tKey} className="gw-sec" open={si === 0 || filled > 0}>
                <summary>
                  {t(sec.tKey)}
                  <span className="gw-sec-n">{filled}/{sec.fields.length}</span>
                </summary>
                {sec.fields.map(({ key, rows }) => (
                  <div key={key} className="gw-field">
                    <label>{t(`pb.f.${key}`)}</label>
                    {rows ? (
                      <textarea rows={rows} placeholder={t(`pb.ph.${key}`)} value={guide[key] || ""}
                                onChange={(e) => setG(key, e.target.value)} />
                    ) : (
                      <input placeholder={t(`pb.ph.${key}`)} value={guide[key] || ""}
                             onChange={(e) => setG(key, e.target.value)} />
                    )}
                  </div>
                ))}
              </details>
            );
          })}

          <div className="gw-field" style={{ marginTop: 14 }}>
            <label>{t("pb.s1.extra")} <span className="hint" style={{ fontWeight: 400 }}>{t("pb.opt")}</span></label>
            <textarea rows={2} placeholder={t("pb.s1.extra_ph")}
                      value={extra} onChange={(e) => setExtra(e.target.value)} />
          </div>
        </div>

        {/* Bước 2: link dữ liệu (tuỳ chọn) */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>{t("pb.s2.title")} <span className="hint" style={{ fontWeight: 400 }}>{t("pb.s2.opt")}</span></h3>
          <p className="hint">{t("pb.s2.h1")}<b>{t("pb.s2.h2")}</b>{t("pb.s2.h3")}<b>{t("pb.s2.h4")}</b>{t("pb.s2.h5")}<b>{t("pb.s2.h6")}</b>{t("pb.s2.h7")}</p>
          {links.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <input style={{ flex: "1 1 240px" }} placeholder="https://…" value={l.url}
                     onChange={(e) => setLink(i, "url", e.target.value)} />
              <input style={{ flex: "2 1 320px" }}
                     placeholder={isSheetUrl(l.url) ? t("pb.s2.note_ph_sheet") : t("pb.s2.note_ph")}
                     value={l.note} onChange={(e) => setLink(i, "note", e.target.value)} />
              <button className="btn-mini danger" onClick={() => rmLink(i)} title={t("pb.s2.rm")}>✕</button>
            </div>
          ))}
          {links.some((l) => isSheetUrl(l.url)) && (
            <div className="prompt-help" style={{ marginTop: 10, borderColor: "var(--brand, #7C3AED)" }}>
              <b style={{ color: "var(--brand, #7C3AED)" }}>
                {t("pb.s2.sheet_note")}
              </b>
              {svcEmail
                ? <p className="hint" style={{ margin: "6px 0 0" }}>
                    {t("pb.s2.share1")}<b>Share</b>{t("pb.s2.share2")}<b>{t("pb.s2.viewer")}</b>{t("pb.s2.share3")}{" "}
                    <code style={{ wordBreak: "break-all" }}>{svcEmail}</code>{" "}
                    <button type="button" className="btn-mini"
                            onClick={() => { navigator.clipboard?.writeText(svcEmail); setMsg(t("pb.copied")); }}>
                      {t("pb.s2.copy")}
                    </button>
                  </p>
                : <p className="hint" style={{ margin: "6px 0 0" }}>
                    {t("pb.s2.no_svc")}
                  </p>}
            </div>
          )}
          <button className="btn-mini" style={{ marginTop: 10 }} onClick={addLink}>{t("pb.s2.add")}</button>

          {/* Hướng dẫn công khai link — bấm mở khi cần */}
          <details className="prompt-help" style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 13.5 }}>
              {t("pb.s2.help_q")}
            </summary>
            <div className="hint" style={{ marginTop: 8, lineHeight: 1.7 }}>
              {svcEmail && (
                <>• <b>{t("pb.s2.g1")}</b>{t("pb.s2.g2")}
                  <b>Share</b>{t("pb.s2.share2")}<b>{t("pb.s2.viewer")}</b>{t("pb.s2.g4")}{" "}
                  <code style={{ wordBreak: "break-all" }}>{svcEmail}</code>{" "}
                  <button type="button" className="btn-mini"
                          onClick={() => { navigator.clipboard?.writeText(svcEmail); setMsg(t("pb.copied")); }}>
                    {t("pb.s2.copy")}
                  </button>
                  <br /></>
              )}
              • <b>{t("pb.s2.o1")}</b>{t("pb.s2.o2")}<b>{t("pb.s2.o3")}</b>{t("pb.s2.o4")}
              <br />• {t("pb.s2.p1")}<b>{t("pb.s2.p2")}</b>{t("pb.s2.p3")}
            </div>
          </details>
        </div>

        {/* ⚙️ Cấu hình bot — AI ĐỌC các mục này khi tạo bộ não nên đặt TRƯỚC nút tạo.
            (QR nhận tiền KHÔNG đưa cho AI → để riêng dưới cùng) */}
        <div style={{ marginTop: 8, marginBottom: 20 }}>
          <h3 style={{ fontSize: 18, marginBottom: 4 }}>{t("pb.cfg.title")}</h3>
          <p className="hint">{t("pb.cfg.hint")}</p>
          <NotifyCard />
          <CannedCard />
        </div>

        {/* Bước 3: tạo — kèm chọn model AI dùng để dạy */}
        <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 8, flexWrap: "wrap" }}>
          <label className="hint" style={{ margin: 0 }}>{t("pb.s3.model")}</label>
          <select value={genModel} onChange={(e) => setGenModel(e.target.value)} style={{ flex: "1 1 260px", maxWidth: 420 }}>
            <option value="">{t("pb.s3.model_default")}</option>
            {models.map((m) => (
              <option key={m.key} value={m.key} disabled={!m.available}>
                {m.label} (in {(m.in_vnd ?? 0).toLocaleString("vi-VN")}₫ / out {(m.out_vnd ?? 0).toLocaleString("vi-VN")}₫ {t("pb.s3.per_1m")}){m.available ? "" : t("pb.s3.no_key")}
              </option>
            ))}
          </select>
        </div>
        <button className="btn-primary" onClick={doGenerate} disabled={busy}
                style={{ width: "100%", marginBottom: 16 }}>
          {busy ? t("pb.s3.busy") : t("pb.s3.go")}
        </button>

        {/* Kết quả link đã đọc */}
        {sources.length > 0 && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, marginBottom: 6 }}>{t("pb.src.title")}</h3>
            {sources.map((s, i) => (
              <div key={i} className="hint" style={{ padding: "2px 0" }}>
                {s.ok ? "✅" : "❌"} {s.url} {!s.ok && <i>— {s.error}</i>}
                {s.ok && s.info && <i> — {s.info}</i>}
              </div>
            ))}
          </div>
        )}

        {/* AI đề nghị bổ sung (gaps) */}
        {gaps.length > 0 && (
          <div className="panel set-card gaps-box" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, marginBottom: 6 }}>{t("pb.gaps.title")}</h3>
            <ul className="gaps-list">
              {gaps.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
            <p className="hint">{t("pb.gaps.h1")}<b>{t("pb.d.regen")}</b>{t("pb.gaps.h3")}</p>
          </div>
        )}

        {/* Bước 4: duyệt */}
        {draft !== null && (
          <div className="panel set-card draft-box">
            <h3 style={{ fontSize: 16, marginBottom: 6 }}>
              3️⃣ {chunks.length ? t("pb.d.title_hybrid") : t("pb.d.title_prompt")}
            </h3>
            <p className="hint">
              {chunks.length
                ? <>{t("pb.d.hint_h1")}<b>{t("pb.d.hint_h2")}</b>{t("pb.d.hint_h3")}{t("pb.d.hint_c1")}<b>{t("pb.d.hint_c2")}</b>{t("pb.d.hint_c3")}</>
                : <>{t("pb.d.hint_p")}{t("pb.d.hint_c1")}<b>{t("pb.d.hint_c2")}</b>{t("pb.d.hint_c3")}</>}
            </p>
            <textarea className="chat-input prompt-draft" value={draft}
                      onChange={(e) => setDraft(e.target.value)} />
            <div className="hint" style={{ textAlign: "right" }}>{t("pb.d.chars", { n: draft.length.toLocaleString("vi-VN") })}</div>

            {/* Mẩu tri thức (chế độ lai) — bot chỉ tra mẩu liên quan mỗi tin nhắn */}
            {chunks.length > 0 && (
              <div className="kn-box">
                <div className="kn-head">
                  {t("pb.kn.head")}<b>{t("pb.kn.count", { n: chunks.length })}</b>
                  <span className="hint" style={{ fontWeight: 400 }}>
                    {" "}{t("pb.kn.note")}
                  </span>
                </div>
                <div className="kn-list">
                  {chunks.map((c, i) => (
                    <details key={i} className="kn-item">
                      <summary>
                        {c.pinned ? "📌 " : ""}{c.title || t("pb.kn.chunk", { n: i + 1 })}
                        <span className="kn-kw">{(c.keywords || []).slice(0, 4).join(" · ")}</span>
                      </summary>
                      <pre className="kn-content">{c.content}</pre>
                    </details>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn-primary sm" onClick={doApply}>{t("pb.d.use")}</button>
              <button className="btn-outline sm" style={{ width: "auto" }} onClick={doGenerate} disabled={busy}>{t("pb.d.regen")}</button>
              <button className="btn-mini danger" onClick={() => { setDraft(null); setChunks([]); setGaps([]); setSources([]); }}>{t("pb.d.cancel")}</button>
            </div>
          </div>
        )}

        {/* 🩺 Chấm điểm não — chạy bộ câu hỏi ngành qua não thật (sau khi đã dạy) */}
        {cur && cur !== "offline" && <HealthCard />}

        {/* Bot học từ hội thoại — đề xuất tri thức chờ chủ duyệt (sau luồng dạy chính) */}
        {cur && cur !== "offline" && <SuggestionsCard onChanged={load} />}

        {/* Kho MẪU HỘI THOẠI (style RAG) — dạy giọng + cách xử lý tình huống */}
        {cur && cur !== "offline" && <StyleLibrary />}

        {/* Prompt mẫu chuẩn — nâng cao, ít dùng → gần cuối */}
        {cur && cur !== "offline" && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <b>{t("pb.tpl.title")}</b>{" "}
                <span className="hint" style={{ fontWeight: 400 }}>{t("pb.tpl.hint")}</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn-mini" onClick={loadTemplate}>
                  {showTpl ? t("pb.tpl.hide") : t("pb.tpl.show")}
                </button>
                {tpl && (
                  <button className="btn-mini" onClick={editFromTemplate} title={t("pb.tpl.edit_tip")}>
                    {t("pb.tpl.edit")}
                  </button>
                )}
              </div>
            </div>
            {showTpl && tpl && <pre className="prompt-pre">{tpl}</pre>}
          </div>
        )}

        {/* 💳 Tài khoản nhận tiền (QR) — KHÔNG đưa cho AI, chỉ dùng lúc chốt đơn,
            nên để riêng DƯỚI CÙNG (Notify + Canned đã chuyển lên trên nút tạo) */}
        <div style={{ marginTop: 28 }}>
          <BankCard />
        </div>
      </main>
    </div>
  );
}

/*
 * Bot học từ hội thoại: khi bạn TRẢ LỜI TAY một câu bot không biết (gửi từ web
 * hoặc gõ trên điện thoại), AI bóc thành mẩu tri thức ĐỀ XUẤT. Duyệt ở đây thì
 * mẩu mới vào kho — bot lần sau tự trả lời được. Sửa được nội dung trước khi duyệt.
 */
function SuggestionsCard({ onChanged }) {
  const { t } = useI18n();
  const [sugs, setSugs] = useState(null);   // null=đang tải | mảng
  const [edits, setEdits] = useState({});   // id → {title, content} chủ sửa trước khi duyệt
  const [busyId, setBusyId] = useState(null);
  const [note, setNote] = useState("");

  async function loadSugs() {
    const r = await promptApi.suggestions();
    if (r.ok && Array.isArray(r.body?.suggestions)) setSugs(r.body.suggestions);
    else setSugs([]);
  }
  useEffect(() => {
    loadSugs();
    const t = setInterval(loadSugs, 30000);   // chủ đang mở trang → thấy đề xuất mới
    return () => clearInterval(t);
  }, []);

  function edited(s) {
    return { title: edits[s.id]?.title ?? s.title, content: edits[s.id]?.content ?? s.content };
  }
  async function doApprove(s) {
    setBusyId(s.id);
    const r = await promptApi.approveSuggestion(s.id, edited(s));
    setBusyId(null);
    if (r.ok) { setNote(t("pb.sug.ok")); loadSugs(); onChanged?.(); }
    else setNote("❌ " + (r.body?.error || t("pb.sug.fail")));
  }
  async function doReject(s) {
    setBusyId(s.id);
    const r = await promptApi.rejectSuggestion(s.id);
    setBusyId(null);
    if (r.ok) loadSugs();
  }

  if (!sugs || sugs.length === 0) return null;   // không có đề xuất → không chiếm chỗ

  return (
    <div className="panel set-card" style={{ marginBottom: 16 }}>
      <h3 style={{ fontSize: 16, marginBottom: 4 }}>
        {t("pb.sug.title")} <span className="badge bot">{t("pb.sug.badge", { n: sugs.length })}</span>
      </h3>
      <p className="hint">{t("pb.sug.desc")}</p>
      {note && <div className="savemsg" style={{ marginBottom: 8 }}>{note}</div>}
      <div className="kn-list">
        {sugs.map((s) => (
          <div key={s.id} className="sug-item">
            <div className="sug-qa">
              <div><b>{t("pb.sug.q")}</b> {s.question}</div>
              <div><b>{t("pb.sug.a")}</b> {s.answer}</div>
            </div>
            <input
              className="sug-title"
              value={edited(s).title}
              placeholder={t("pb.sug.title_ph")}
              onChange={(e) => setEdits((m) => ({ ...m, [s.id]: { ...edited(s), title: e.target.value } }))}
            />
            <textarea
              rows={3}
              value={edited(s).content}
              onChange={(e) => setEdits((m) => ({ ...m, [s.id]: { ...edited(s), content: e.target.value } }))}
            />
            {s.keywords?.length > 0 && (
              <div className="kn-kw" style={{ marginTop: 4 }}>🔎 {s.keywords.slice(0, 6).join(" · ")}</div>
            )}
            <div style={{ display: "flex", gap: 6, marginTop: 8, justifyContent: "flex-end" }}>
              <button className="btn-mini danger" disabled={busyId === s.id} onClick={() => doReject(s)}>
                {t("pb.sug.skip")}
              </button>
              <button className="btn-primary sm" disabled={busyId === s.id} onClick={() => doApprove(s)}>
                {busyId === s.id ? t("pb.sug.saving") : t("pb.sug.approve")}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
