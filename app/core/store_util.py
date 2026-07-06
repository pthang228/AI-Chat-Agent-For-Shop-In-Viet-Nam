"""
Ghi JSON AN TOÀN (atomic) dùng chung cho mọi store danh bạ token/cấu hình.

Vì sao cần: các store trước đây ghi thẳng `path.write_text(json)`. Nếu tiến trình
bị kill / đầy đĩa GIỮA CHỪNG khi ghi → file JSON cụt → lần load sau `json.loads`
ném lỗi → store coi như rỗng → MẤT TOÀN BỘ token kênh đó (khách phải kết nối lại).

Cách chuẩn (giống bot_state ở bridge): ghi ra file tạm cùng thư mục rồi
`os.replace` (đổi tên atomic trên cùng volume) — người đọc luôn thấy hoặc bản cũ
nguyên vẹn, hoặc bản mới nguyên vẹn, không bao giờ thấy bản cụt.
"""

import json
import logging
import os

log = logging.getLogger(__name__)


def atomic_write_json(path, data, log_tag: str = "store") -> bool:
    """Ghi `data` thành JSON xuống `path` một cách atomic. Trả True nếu thành công."""
    tmp = None
    try:
        text = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)          # đổi tên atomic trên cùng volume
        return True
    except Exception as e:
        log.error(f"[{log_tag}] atomic save lỗi: {e}")
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)   # dọn file tạm dở dang
            except Exception:
                pass
        return False
