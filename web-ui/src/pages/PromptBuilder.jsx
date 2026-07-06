import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { currentUser } from "../auth.js";
import { promptApi } from "../promptApi.js";
import { IcHome, IcBack } from "../components/icons.jsx";
import LogoMark from "../components/LogoMark.jsx";
import BackLink from "../components/BackLink.jsx";

function initials(name) {
  return (name || "?").trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

/* ── Form gợi ý có cấu trúc — shop không cần biết "viết prompt" ──
 * Chia 5 nhóm, ~20 ô — chi tiết ngang prompt mẫu gốc. Bỏ trống ô không có;
 * hệ thống ghép các ô thành hướng dẫn có nhãn cho AI. */
const GUIDE_SECTIONS = [
  { title: "🏪 Thông tin cơ bản", fields: [
    { key: "about",    label: "Tên shop & loại hình",   ph: "VD: Mây Spa — spa thư giãn ở Quận 1, TP.HCM" },
    { key: "branches", label: "Địa chỉ các cơ sở",      ph: "Mỗi dòng 1 cơ sở:\nCơ sở 1: 12 Lê Lợi, Q1\nCơ sở 2: 3D Trần Phú, Q5 — cách bến xe 2km", rows: 2 },
    { key: "hours",    label: "Giờ hoạt động",          ph: "VD: 9h–21h hằng ngày / check-in tự động 24/7, nghỉ Thứ 2" },
    { key: "contact",  label: "SĐT · kênh liên hệ",     ph: "VD: 0901 234 567 (Zalo) · fanpage fb.com/mayspa" },
  ]},
  { title: "💰 Dịch vụ & giá", fields: [
    { key: "services", label: "Dịch vụ / sản phẩm & GIÁ TỪNG MỤC (quan trọng nhất)",
      ph: "Càng chi tiết càng tốt — từng phòng/món/gói, từng khung giờ nếu có:\nPhòng 201 — ca trưa 12h-16h: 260k · ca chiều 16h30-20h30: 260k · qua đêm 21h-10h30: 380k · nguyên ngày: 750k\nCombo trưa+chiều: 490k\n…", rows: 8 },
    { key: "surcharge", label: "Phụ thu (cuối tuần · lễ · thêm người…)", ph: "VD: Cuối tuần & lễ +35k/ca · Người thứ 3 +100k · Thú cưng làm bẩn +500k", rows: 2 },
    { key: "promos",   label: "Khuyến mãi đang chạy",   ph: "VD: Khách lần đầu giảm 10% · Đặt 2 đêm cuối tuần giảm 10%" },
  ]},
  { title: "📋 Chính sách đặt chỗ & tiền bạc", fields: [
    { key: "booking",  label: "Cách đặt chỗ / giữ chỗ", ph: "VD: Đặt trước ít nhất 2 tiếng · Booking chỉ giữ 30 phút, chưa cọc sẽ tự huỷ", rows: 2 },
    { key: "deposit",  label: "Đặt cọc & thanh toán (quy trình TỪNG BƯỚC)",
      ph: "VD:\n1. Ngày đặt: cọc 50% + gửi CCCD 2 người (bắt buộc)\n2. Sau cọc: chốt ca & ngày → nhận thông tin check-in\n3. 21h đêm trước check-in: thanh toán đủ (trước ít nhất 12 tiếng để nhận mã)", rows: 4 },
    { key: "reschedule", label: "Đổi / dời lịch",        ph: "VD: Miễn phí dời 1 lần (báo trước 7 ngày) · Dời trước 48h phí 30% · Dời lần 2 phí 30%", rows: 2 },
    { key: "cancel",   label: "Huỷ & hoàn tiền",         ph: "VD: Huỷ trước 5 ngày hoàn 50% cọc · Trước 3 ngày không hoàn cọc · Trước 12 tiếng không hoàn bất kỳ khoản nào", rows: 2 },
  ]},
  { title: "🏠 Tiện ích & nội quy", fields: [
    { key: "amenities", label: "Tiện ích nổi bật",       ph: "VD: Check-in tự động không cần lễ tân · Giờ ra vào tự do · Bãi xe riêng (ô tô + xe máy) · Được mang đồ ăn vào · 100% không camera ẩn", rows: 3 },
    { key: "equipment", label: "Trang thiết bị / đồ dùng có sẵn",
      ph: "VD: Máy chiếu + Netflix, máy lạnh, board game · Qua đêm có sẵn kem đánh răng/khăn; ca ngày yêu cầu thì chuẩn bị · Máy sấy liên hệ mang lên · Cơ sở 1 KHÔNG có bếp, cơ sở 2 bếp đầy đủ", rows: 3 },
    { key: "capacity", label: "Sức chứa · thêm người · thú cưng", ph: "VD: Chuẩn 2 người/phòng, phụ thu từ người thứ 3 · Cho thú cưng (phụ thu 500k nếu bẩn/hư)", rows: 2 },
    { key: "forbidden", label: "Khách KHÔNG được làm",    ph: "VD: Hút thuốc trong phòng · Chất cấm · Vật dễ cháy nổ · Vi phạm sẽ báo chính quyền", rows: 2 },
  ]},
  { title: "💬 Cách bot nói chuyện", fields: [
    { key: "tone",     label: "Xưng hô & giọng điệu",    ph: 'VD: xưng "em"/"mình", thân thiện như bạn bè, câu ngắn, emoji vừa phải 😊' },
    { key: "greeting", label: "Tin nhắn chào ĐẦU TIÊN (bot gửi đúng đoạn này)",
      ph: "VD: Admin có thể đang bận nên chưa rep được, để AI tư vấn trước cho mình nhen 😊\nMình có thể giúp bạn: 📅 xem lịch trống · 💰 bảng giá · 📸 xin ảnh · 🏠 đặt chỗ", rows: 3 },
    { key: "handoff",  label: "Khi nào CHUYỂN CHO CHỦ shop", ph: "VD: Khách muốn gặp người thật · Khiếu nại · Đổi lịch đã chốt · Hỏi ngoài kiến thức → báo đã nhắn chủ, chủ sẽ liên hệ sớm", rows: 2 },
    { key: "rules",    label: "Điều bot KHÔNG được làm",  ph: "VD: Không tự xác nhận booking cuối (chủ chốt) · Không nhận tiền cọc trực tiếp · Không tự giảm giá ngoài chính sách · Không bịa thông tin", rows: 2 },
    { key: "faq",      label: "Câu hỏi thường gặp & cách trả lời",
      ph: "Mỗi dòng 1 cặp:\nCó chỗ để xe không? → Có bãi riêng cả ô tô lẫn xe máy\nGần trường ĐH không? → Cách KTX Làng Đại học 2km", rows: 4 },
  ]},
];
const GUIDE_FIELDS = GUIDE_SECTIONS.flatMap((s) => s.fields);
const GUIDE_LABEL = Object.fromEntries(GUIDE_FIELDS.map((g) => [g.key, g.label]));

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

// Trang "Dạy AI": điền form gợi ý (hoặc dán link) → AI viết persona + mẩu tri
// thức → shop duyệt + test thử → dùng. Càng điền đủ ô, bộ não càng chuẩn.
export default function PromptBuilder() {
  const nav = useNavigate();
  const user = currentUser();
  const hostName = user?.homestay || user?.username || "";

  const [cur, setCur] = useState(null);        // prompt đang dùng
  const [showCur, setShowCur] = useState(false);
  const [tpl, setTpl] = useState("");          // prompt mẫu chuẩn
  const [showTpl, setShowTpl] = useState(false);
  const [links, setLinks] = useState([""]);
  const [guide, setGuide] = useState({});      // câu trả lời form gợi ý
  const [extra, setExtra] = useState("");      // hướng dẫn thêm tự do
  const [draft, setDraft] = useState(null);    // persona AI vừa tạo (chờ duyệt)
  const [chunks, setChunks] = useState([]);    // mẩu tri thức đi kèm (chế độ lai)
  const [gaps, setGaps] = useState([]);        // AI đề nghị bổ sung
  const [sources, setSources] = useState([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function load() {
    const r = await promptApi.current();
    if (r.status === 401) { nav("/login"); return; }
    if (r.ok) setCur(r.body);
    else setCur("offline");
  }
  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  async function loadTemplate() {
    if (tpl) { setShowTpl((v) => !v); return; }
    const r = await promptApi.template();
    if (r.ok && r.body?.template) { setTpl(r.body.template); setShowTpl(true); }
    else setMsg("❌ Không tải được prompt mẫu");
  }
  function editFromTemplate() {
    if (draft !== null && !confirm("Thay nháp hiện tại bằng prompt mẫu chuẩn để chỉnh tay?")) return;
    setDraft(tpl); setChunks([]); setGaps([]); setSources([]); setMsg("");
    setTimeout(() => document.querySelector(".draft-box")?.scrollIntoView({ behavior: "smooth" }), 50);
  }

  function setLink(i, v) { setLinks((ls) => ls.map((x, j) => (j === i ? v : x))); }
  function addLink() { setLinks((ls) => [...ls, ""]); }
  function rmLink(i) { setLinks((ls) => (ls.length > 1 ? ls.filter((_, j) => j !== i) : [""])); }

  function setG(key, v) { setGuide((g) => ({ ...g, [key]: v })); }
  function fillSample(name) {
    const hasContent = Object.values(guide).some((v) => (v || "").trim());
    if (hasContent && !confirm(`Điền mẫu "${name}" đè lên nội dung đang nhập?`)) return;
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
    const linkList = links.filter((l) => l.trim());
    if (!instructions && linkList.length === 0) {
      setMsg("❌ Điền ít nhất một ô (hoặc dán 1 link) rồi hãy tạo nhé.");
      return;
    }
    setMsg(""); setDraft(null); setChunks([]); setGaps([]); setSources([]);
    setBusy(true);
    const r = await promptApi.generate(linkList, instructions);
    setBusy(false);
    if (r.ok && r.body?.draft) {
      setDraft(r.body.draft);
      setChunks(r.body.chunks || []);
      setGaps(r.body.gaps || []);
      setSources(r.body.sources || []);
      setTimeout(() => document.querySelector(".draft-box")?.scrollIntoView({ behavior: "smooth" }), 80);
    } else {
      setMsg("❌ " + (r.body?.error || (r.status === 0 ? "Không kết nối được máy chủ (5005)" : "Tạo thất bại")));
    }
  }

  async function doApply() {
    if (!confirm("Dùng bộ não này cho bot? Bot sẽ trả lời khách theo nội dung mới NGAY LẬP TỨC trên mọi kênh.")) return;
    setMsg("");
    const r = await promptApi.apply(draft, chunks.length ? chunks : null);
    if (r.ok) {
      setMsg("✅ Đã lưu — bot đang dùng bộ não mới! Chat thử bằng nút 🧪 Test bot ở mục Chatbot.");
      setDraft(null); setChunks([]); setSources([]);
      load();
    } else {
      setMsg("❌ " + (r.body?.error || "Lưu thất bại"));
    }
  }

  async function doRestore() {
    if (!confirm("Quay về prompt MẶC ĐỊNH của hệ thống? (bộ não tuỳ chỉnh hiện tại được sao lưu lại)")) return;
    const r = await promptApi.restoreDefault();
    if (r.ok) { setMsg("✅ Đã khôi phục prompt mặc định."); load(); }
  }

  return (
    <div className="dash">
      <header className="topbar">
        <div className="brand">
          <Link to="/"><span className="brand-mini"><IcBack width={18} height={18} /></span> <LogoMark size={28} /> NovaChat</Link>
        </div>
        <div className="user">
          <Link to="/settings" className="user-pill" title="Cài đặt tài khoản">
            <span className="avatar">{initials(hostName)}</span>{hostName}
          </Link>
        </div>
      </header>

      <main className="content narrow" style={{ maxWidth: 780 }}>
        <BackLink />
        <div className="dash-head" style={{ marginBottom: 18 }}>
          <div>
            <div className="hello">Trợ lý AI</div>
            <h1 className="page-title">Dạy AI về shop của bạn</h1>
            <p className="page-sub">
              Điền form như dặn nhân viên mới (hoặc dán link dữ liệu). AI tự soạn "bộ não"
              chi tiết — bạn duyệt & chat thử rồi mới dùng.
            </p>
          </div>
        </div>

        {/* Bộ não đang dùng */}
        {cur && cur !== "offline" && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <b>Bộ não đang dùng:</b>{" "}
                {cur.source === "custom"
                  ? <span className="badge bot">
                      {cur.mode === "hybrid"
                        ? `⚡ Lai — persona + ${cur.chunk_count} mẩu tri thức`
                        : "✨ Tuỳ chỉnh"}
                      {cur.updated_at ? ` (lưu ${new Date(cur.updated_at).toLocaleString("vi-VN")})` : ""}
                    </span>
                  : <span className="badge stage">Mặc định hệ thống</span>}
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn-mini" onClick={() => setShowCur((v) => !v)}>
                  {showCur ? "Ẩn nội dung" : "Xem nội dung"}
                </button>
                {cur.source === "custom" && (
                  <button className="btn-mini danger" onClick={doRestore}>Khôi phục mặc định</button>
                )}
              </div>
            </div>
            {showCur && <pre className="prompt-pre">{cur.prompt}</pre>}
          </div>
        )}
        {cur === "offline" && (
          <div className="empty"><p>⚠️ Chưa kết nối được máy chủ (cổng 5005).</p></div>
        )}

        {msg && <div className="savemsg" style={{ marginBottom: 14 }}>{msg}</div>}

        {/* Prompt mẫu chuẩn — shop chỉnh tay cho phù hợp */}
        {cur && cur !== "offline" && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
              <div>
                <b>📄 Prompt mẫu chuẩn</b>{" "}
                <span className="hint" style={{ fontWeight: 400 }}>— khung sẵn cho shop dịch vụ, điền thông tin của bạn vào</span>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                <button className="btn-mini" onClick={loadTemplate}>
                  {showTpl ? "Ẩn mẫu" : "Xem mẫu"}
                </button>
                {tpl && (
                  <button className="btn-mini" onClick={editFromTemplate} title="Đổ mẫu vào ô nháp để bạn chỉnh tay rồi dùng luôn">
                    ✏️ Chỉnh tay từ mẫu
                  </button>
                )}
              </div>
            </div>
            {showTpl && tpl && <pre className="prompt-pre">{tpl}</pre>}
          </div>
        )}

        {/* Bot học từ hội thoại — đề xuất tri thức chờ chủ duyệt */}
        {cur && cur !== "offline" && <SuggestionsCard onChanged={load} />}

        {/* Bước 1: kể về shop — form gợi ý theo 5 nhóm */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>1️⃣ Kể về shop của bạn</h3>
          <p className="hint">Trả lời như dặn một nhân viên mới. Bỏ trống ô nào không có — nhưng càng đủ, bot càng chuẩn. Bấm tiêu đề nhóm để mở/gấp.</p>

          <div className="gw-samples">
            <span className="hint">Điền nhanh theo mẫu ngành:</span>
            {Object.keys(SAMPLES).map((name) => (
              <button key={name} type="button" className="gw-sample" onClick={() => fillSample(name)}>
                {name}
              </button>
            ))}
          </div>

          {GUIDE_SECTIONS.map((sec, si) => {
            const filled = sec.fields.filter((f) => (guide[f.key] || "").trim()).length;
            return (
              <details key={sec.title} className="gw-sec" open={si === 0 || filled > 0}>
                <summary>
                  {sec.title}
                  <span className="gw-sec-n">{filled}/{sec.fields.length}</span>
                </summary>
                {sec.fields.map(({ key, label, ph, rows }) => (
                  <div key={key} className="gw-field">
                    <label>{label}</label>
                    {rows ? (
                      <textarea rows={rows} placeholder={ph} value={guide[key] || ""}
                                onChange={(e) => setG(key, e.target.value)} />
                    ) : (
                      <input placeholder={ph} value={guide[key] || ""}
                             onChange={(e) => setG(key, e.target.value)} />
                    )}
                  </div>
                ))}
              </details>
            );
          })}

          <div className="gw-field" style={{ marginTop: 14 }}>
            <label>Hướng dẫn thêm <span className="hint" style={{ fontWeight: 400 }}>(tuỳ chọn)</span></label>
            <textarea rows={2} placeholder="Điều gì khác bot cần biết mà các ô trên chưa nói tới…"
                      value={extra} onChange={(e) => setExtra(e.target.value)} />
          </div>
        </div>

        {/* Bước 2: link dữ liệu (tuỳ chọn) */}
        <div className="panel set-card" style={{ marginBottom: 16 }}>
          <h3 style={{ fontSize: 16, marginBottom: 4 }}>2️⃣ Link dữ liệu <span className="hint" style={{ fontWeight: 400 }}>(tuỳ chọn — có link thì AI đọc thêm)</span></h3>
          <p className="hint">Bảng giá, trang Facebook/website, Google Docs/Sheets đã "Xuất bản lên web"… Link phải mở được công khai.</p>
          {links.map((l, i) => (
            <div key={i} style={{ display: "flex", gap: 8, marginTop: 8 }}>
              <input style={{ flex: 1 }} placeholder="https://…" value={l}
                     onChange={(e) => setLink(i, e.target.value)} />
              <button className="btn-mini danger" onClick={() => rmLink(i)} title="Xoá link này">✕</button>
            </div>
          ))}
          <button className="btn-mini" style={{ marginTop: 10 }} onClick={addLink}>＋ Thêm link</button>
        </div>

        {/* Bước 3: tạo */}
        <button className="btn-primary" onClick={doGenerate} disabled={busy}
                style={{ width: "100%", marginBottom: 16 }}>
          {busy ? "🪄 AI đang đọc & soạn bộ não… (20–60 giây)" : "🪄 Tạo bộ não bằng AI"}
        </button>

        {/* Kết quả link đã đọc */}
        {sources.length > 0 && (
          <div className="panel set-card" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, marginBottom: 6 }}>Kết quả đọc link</h3>
            {sources.map((s, i) => (
              <div key={i} className="hint" style={{ padding: "2px 0" }}>
                {s.ok ? "✅" : "❌"} {s.url} {!s.ok && <i>— {s.error}</i>}
              </div>
            ))}
          </div>
        )}

        {/* AI đề nghị bổ sung (gaps) */}
        {gaps.length > 0 && (
          <div className="panel set-card gaps-box" style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 14, marginBottom: 6 }}>💡 AI đề nghị bổ sung để bot trả lời tốt hơn</h3>
            <ul className="gaps-list">
              {gaps.map((g, i) => <li key={i}>{g}</li>)}
            </ul>
            <p className="hint">Điền thêm vào các ô ở Bước 1 rồi bấm <b>↺ Tạo lại</b> — hoặc cứ dùng, bổ sung sau cũng được.</p>
          </div>
        )}

        {/* Bước 4: duyệt */}
        {draft !== null && (
          <div className="panel set-card draft-box">
            <h3 style={{ fontSize: 16, marginBottom: 6 }}>
              3️⃣ {chunks.length ? "Bộ não AI đề xuất — kiểm tra rồi duyệt" : "Prompt AI đề xuất — kiểm tra rồi duyệt"}
            </h3>
            <p className="hint">
              {chunks.length
                ? <>Phần <b>tính cách & quy trình</b> sửa trực tiếp bên dưới. Chỉ khi bấm <b>"✅ Dùng bộ não này"</b> bot mới thay đổi.</>
                : <>Bạn sửa trực tiếp bên dưới được. Chỉ khi bấm <b>"✅ Dùng bộ não này"</b> bot mới thay đổi.</>}
            </p>
            <textarea className="chat-input prompt-draft" value={draft}
                      onChange={(e) => setDraft(e.target.value)} />
            <div className="hint" style={{ textAlign: "right" }}>{draft.length.toLocaleString("vi-VN")} ký tự</div>

            {/* Mẩu tri thức (chế độ lai) — bot chỉ tra mẩu liên quan mỗi tin nhắn */}
            {chunks.length > 0 && (
              <div className="kn-box">
                <div className="kn-head">
                  📚 Kiến thức bot sẽ tra cứu — <b>{chunks.length} mẩu</b>
                  <span className="hint" style={{ fontWeight: 400 }}>
                    {" "}(mỗi tin nhắn bot chỉ đọc vài mẩu liên quan → rẻ + chính xác hơn)
                  </span>
                </div>
                <div className="kn-list">
                  {chunks.map((c, i) => (
                    <details key={i} className="kn-item">
                      <summary>
                        {c.pinned ? "📌 " : ""}{c.title || `Mẩu ${i + 1}`}
                        <span className="kn-kw">{(c.keywords || []).slice(0, 4).join(" · ")}</span>
                      </summary>
                      <pre className="kn-content">{c.content}</pre>
                    </details>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "flex", gap: 10, marginTop: 10, flexWrap: "wrap" }}>
              <button className="btn-primary sm" onClick={doApply}>✅ Dùng bộ não này</button>
              <button className="btn-outline sm" style={{ width: "auto" }} onClick={doGenerate} disabled={busy}>↺ Tạo lại</button>
              <button className="btn-mini danger" onClick={() => { setDraft(null); setChunks([]); setGaps([]); setSources([]); }}>Huỷ</button>
            </div>
          </div>
        )}
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
    if (r.ok) { setNote("✅ Đã thêm vào kho tri thức — bot dùng ngay."); loadSugs(); onChanged?.(); }
    else setNote("❌ " + (r.body?.error || "Duyệt thất bại"));
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
        💡 Bot học từ hội thoại <span className="badge bot">{sugs.length} đề xuất chờ duyệt</span>
      </h3>
      <p className="hint">
        Bạn vừa trả lời tay mấy câu bot chưa biết — AI đã soạn sẵn thành tri thức.
        Duyệt để lần sau bot tự trả lời (sửa nội dung trước khi duyệt nếu cần).
      </p>
      {note && <div className="savemsg" style={{ marginBottom: 8 }}>{note}</div>}
      <div className="kn-list">
        {sugs.map((s) => (
          <div key={s.id} className="sug-item">
            <div className="sug-qa">
              <div><b>Khách hỏi:</b> {s.question}</div>
              <div><b>Bạn trả lời:</b> {s.answer}</div>
            </div>
            <input
              className="sug-title"
              value={edited(s).title}
              placeholder="Tiêu đề mẩu tri thức"
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
                ✖ Bỏ qua
              </button>
              <button className="btn-primary sm" disabled={busyId === s.id} onClick={() => doApprove(s)}>
                {busyId === s.id ? "Đang lưu…" : "✅ Duyệt vào kho"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
