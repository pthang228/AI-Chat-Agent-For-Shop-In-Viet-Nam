#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_crm_plus.py — CRM nâng cấp (tag / stage / gộp trùng / nhắc việc / loyalty):
  A. Tags: update_customer(tags) chuẩn hoá + audit; list_customers lọc tag; all_tags
  B. Stage: derive_stage (lead/customer/repeat/dormant), override tay, phễu stage_counts
  C. Merge: find_duplicates theo SĐT chuẩn hoá (+84→0); merge_customers dồn
     field/tags/points/memory/history; hồ sơ con ẩn khỏi list; stats gộp; resolve_customer
  D. Followups: create/list_for/list_pending (overdue)/mark_done/remove; validate
  E. Loyalty voucher: create/validate (hết hạn, hết lượt, min_total, %), áp vào đơn
     (total giảm + used+1 + redemption + timeline), chặn áp 2 lần / đơn đã thanh toán
  F. Điểm: đơn done → award_points (10.000đ = 1 điểm), không cộng lặp, về hồ sơ
     CHÍNH khi đã gộp; adjust_points không âm + audit
  G. Broadcast audience segment tag/stage (hồ sơ gộp dùng tag hồ sơ chính)
  H. API bridge: /customers?tag/stage, /customers/tags, /duplicates, /merge,
     /followups CRUD, /points, /vouchers CRUD + /orders/<id>/voucher

Chạy (TỪ GỐC):  python tests/test_crm_plus.py
"""

import os, sys
from unittest.mock import MagicMock

sys.modules.update({
    'gspread': MagicMock(),
    'google': MagicMock(), 'google.oauth2': MagicMock(),
    'google.oauth2.service_account': MagicMock(),
    'openai': MagicMock(), 'groq': MagicMock(), 'winsound': MagicMock(),
    'requests': MagicMock(), 'dotenv': MagicMock(),
})
os.environ.setdefault('REPLY_DELAY', '0')
os.environ.setdefault('OWNER_ZALO_ID', 'OWNER123')
os.environ['HOMESTAY_DB_PATH'] = 'test_db_crmplus_tmp.sqlite'
os.environ['API_AUTH_GUARD'] = '0'
os.environ['WORKER_SYNC'] = '1'
sys.path.insert(0, '.')

from datetime import datetime, timedelta

from app.core.conversation import ConversationManager
from app.core import customers as crm
from app.core import followups as fu
from app.core import loyalty, orders, broadcast
from app.core.db import get_db

PASS = FAIL = 0
def check(cond, name, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ✓ {name}")
    else: FAIL += 1; print(f"  ✗ FAIL {name}: {detail}")

db = get_db()
for t in ("customers", "customer_memory", "customer_history", "orders",
          "followups", "vouchers", "voucher_redemptions"):
    db.execute(f"DELETE FROM {t}")
db.execute("DELETE FROM sessions")

# Seed: cùng 1 khách nhắn Zalo + Meta, 1 khách khác Telegram
cm_zalo = ConversationManager(account="1")
cm_meta = ConversationManager(account="meta")
cm_tg = ConversationManager(account="telegram")
for cm in (cm_zalo, cm_meta, cm_tg):
    cm._sessions.clear()
c1 = cm_zalo.get("Z001"); c1.name = "Cường Zalo"; c1.add_user_message("hỏi giá")
c2 = cm_meta.get("fb:PG:U9"); c2.name = "Cường FB"; c2.add_user_message("còn hàng ko")
c3 = cm_tg.get("tg:B:77"); c3.name = "Lan TG"; c3.add_user_message("ship ko")
cm_zalo.save(); cm_meta.save(); cm_tg.save()

# ══ A. Tags ══════════════════════════════════════════════════════════
print("\nA. TAGS")
p = crm.update_customer("1", "Z001", {"tags": ["VIP", " vip ", "khách sỉ", ""]})
check(p["tags"] == ["VIP", "khách sỉ"], "A1 tags chuẩn hoá (bỏ trùng case-insensitive + rỗng)", p["tags"])
hist = crm.list_history("1", "Z001")
check(any(h["field"] == "tags" and "VIP" in h["new_value"] for h in hist), "A2 audit tags")
r = crm.list_customers(tag="vip")
check(r["total"] == 1 and r["items"][0]["user_id"] == "Z001", "A3 lọc tag không phân biệt hoa thường")
tags = crm.all_tags()
check({t["tag"] for t in tags} == {"VIP", "khách sỉ"}, "A4 all_tags", tags)
check(crm.list_customers(tag="khong-co")["total"] == 0, "A5 tag lạ → rỗng")

# ══ B. Stage ═════════════════════════════════════════════════════════
print("\nB. STAGE")
now = datetime.now().isoformat()
old = (datetime.now() - timedelta(days=60)).isoformat()
check(crm.derive_stage(0, now) == "lead", "B1 chưa mua + mới nhắn = lead")
check(crm.derive_stage(1, now) == "customer", "B2 1 đơn = customer")
check(crm.derive_stage(2, old) == "repeat", "B3 2 đơn = repeat (kể cả im lâu)")
check(crm.derive_stage(0, old) == "dormant", "B4 chưa mua + im 60 ngày = dormant")
r = crm.list_customers()
check(r["stages"]["lead"] == 3, "B5 phễu đếm đúng (3 lead)", r["stages"])
crm.update_customer("telegram", "tg:B:77", {"stage": "repeat"})
r = crm.list_customers(stage="repeat")
check(r["total"] == 1 and r["items"][0]["stage_manual"], "B6 override tay + lọc stage")
crm.update_customer("telegram", "tg:B:77", {"stage": ""})   # về auto
g = crm.get_customer("telegram", "tg:B:77")
check(g["stage"] == "lead" and not g["stage_manual"], "B7 stage='' quay về tự suy")
p = crm.update_customer("telegram", "tg:B:77", {"stage": "hacker"})
check(p["stage"] == "", "B8 stage lạ bị bỏ qua")

# ══ C. Merge trùng SĐT ═══════════════════════════════════════════════
print("\nC. MERGE")
crm.update_customer("1", "Z001", {"phone": "0912345678", "note": "khách ruột"})
crm.update_customer("meta", "fb:PG:U9", {"phone": "+84912345678", "email": "cuong@gmail.com"})
crm.adjust_points("meta", "fb:PG:U9", 5, reason="seed")
crm.add_memory("meta", "fb:PG:U9", "Thích phòng view biển")
d = crm.find_duplicates()
check(len(d) == 1 and d[0]["phone"] == "0912345678" and len(d[0]["customers"]) == 2,
      "C1 find_duplicates chuẩn hoá +84→0", d)
prim = crm.merge_customers("1", "Z001", "meta", "fb:PG:U9")
check(prim["email"] == "cuong@gmail.com" and prim["note"] == "khách ruột",
      "C2 field trống lấy của dup, field có giữ nguyên")
check(prim["points"] == 5, "C3 điểm dồn về hồ sơ chính")
r = crm.list_customers()
ids = [i["user_id"] for i in r["items"]]
check("fb:PG:U9" not in ids and "Z001" in ids, "C4 hồ sơ con ẩn khỏi danh sách")
row = next(i for i in r["items"] if i["user_id"] == "Z001")
check(row["merged_count"] == 1, "C5 merged_count")
g = crm.get_customer("1", "Z001")
check(any(m["content"] == "Thích phòng view biển" for m in g["memory"]),
      "C6 memory chuyển về hồ sơ chính")
check(g["merged"] and g["merged"][0]["user_id"] == "fb:PG:U9", "C7 get_customer trả kênh đã gộp")
check(crm.resolve_customer("fb:PG:U9") == ("1", "Z001"), "C8 resolve_customer về hồ sơ chính")
try:
    crm.merge_customers("1", "Z001", "meta", "fb:PG:U9")
    check(False, "C9 gộp lại lần 2 phải raise")
except ValueError:
    check(True, "C9 gộp lại lần 2 raise ValueError")
check(crm.find_duplicates() == [], "C10 hết trùng sau gộp")

# ══ D. Followups ═════════════════════════════════════════════════════
print("\nD. FOLLOWUPS")
f1 = fu.create("1", "Z001", "Gọi chốt phòng 301", "2020-01-01", created_by="chu")
f2 = fu.create("1", "Z001", "Báo hàng về", (datetime.now() + timedelta(days=3)).isoformat()[:10])
check(f1["status"] == "pending", "D1 create pending")
lst = fu.list_for("1", "Z001")
check(len(lst) == 2 and lst[0]["id"] == f1["id"], "D2 list_for sắp theo hạn")
pend = fu.list_pending()
check(pend["due_count"] == 1 and pend["items"][0]["overdue"], "D3 đếm việc quá hạn", pend)
check(pend["items"][0]["customer_name"] == "Cường Zalo", "D4 kèm tên khách")
fu.mark_done(f1["id"])
check(fu.get(f1["id"])["status"] == "done", "D5 mark_done")
check(fu.list_pending()["due_count"] == 0, "D6 done không đếm nữa")
fu.remove(f2["id"])
check(fu.get(f2["id"]) is None, "D7 remove")
try:
    fu.create("1", "Z001", "", "2026-01-01"); check(False, "D8 note trống raise")
except ValueError: check(True, "D8 note trống raise")
try:
    fu.create("1", "Z001", "x", "khong-phai-ngay"); check(False, "D9 ngày rác raise")
except ValueError: check(True, "D9 ngày rác raise")

# ══ E. Voucher ═══════════════════════════════════════════════════════
print("\nE. VOUCHER")
v = loyalty.create_voucher("GIAM50K", "amount", 50000, min_total=200000, max_uses=2)
check(v["code"] == "GIAM50K" and v["active"] == 1, "E1 tạo voucher")
try:
    loyalty.create_voucher("GIAM50K", "amount", 1); check(False, "E2 code trùng raise")
except ValueError: check(True, "E2 code trùng raise")
try:
    loyalty.create_voucher("x", "amount", 1); check(False, "E3 code ngắn raise")
except ValueError: check(True, "E3 code ngắn raise")
try:
    loyalty.create_voucher("QUA100", "percent", 150); check(False, "E4 percent >100 raise")
except ValueError: check(True, "E4 percent >100 raise")
check(not loyalty.check("GIAM50K", 100000)["ok"], "E5 dưới min_total bị chặn")
r = loyalty.check("giam50k", 380000)
check(r["ok"] and r["discount"] == 50000, "E6 check ok (code thường hoá HOA)")
vp = loyalty.create_voucher("SALE10", "percent", 10)
check(loyalty.check("SALE10", 380000)["discount"] == 38000, "E7 percent tính đúng")
vexp = loyalty.create_voucher("HETHAN", "amount", 10000, expires_at="2020-01-01")
check(not loyalty.check("HETHAN", 380000)["ok"], "E8 hết hạn bị chặn")

o = orders.create(channel="zalo", user_id="Z001", customer_name="Cường",
                  total=380000, status="draft")
r = loyalty.apply_to_order(o["id"], "GIAM50K")
check(r["ok"] and r["order"]["total"] == 330000 and r["order"]["voucher_code"] == "GIAM50K",
      "E9 áp mã: total giảm + lưu code", r)
check(any("GIAM50K" in e["event"] for e in r["order"]["timeline"]), "E10 timeline ghi áp mã")
check(loyalty.get_by_code("GIAM50K")["used"] == 1, "E11 used+1")
red = db.query("SELECT * FROM voucher_redemptions")
check(len(red) == 1 and red[0]["amount"] == 50000, "E12 redemption ghi lại")
r = loyalty.apply_to_order(o["id"], "SALE10")
check(not r["ok"] and "đã áp" in r["error"], "E13 chặn áp mã 2 lần / đơn")
o2 = orders.create(channel="zalo", user_id="Z001", total=500000, status="paid")
check(not loyalty.apply_to_order(o2["id"], "SALE10")["ok"], "E14 đơn đã thanh toán bị chặn")

# ══ F. Điểm thưởng ═══════════════════════════════════════════════════
print("\nF. ĐIỂM")
before = crm.get_customer("1", "Z001")["points"]
orders.update(o["id"], status="awaiting_payment")
orders.update(o["id"], status="paid")
orders.update(o["id"], status="fulfilled")
orders.update(o["id"], status="done")
after = crm.get_customer("1", "Z001")["points"]
check(after - before == 33, "F1 đơn done 330k → +33 điểm (10k=1đ)", f"{before}→{after}")
check(orders.get(o["id"])["points_awarded"] == 33, "F2 đơn ghi points_awarded")
orders.update(o["id"], note="chạm lại đơn done")
check(crm.get_customer("1", "Z001")["points"] == after, "F3 không cộng lặp")
# Đơn của hội thoại ĐÃ GỘP (fb:PG:U9) → điểm về hồ sơ chính Z001
o3 = orders.create(channel="meta", user_id="fb:PG:U9", total=100000, status="draft")
orders.update(o3["id"], status="done")
check(crm.get_customer("1", "Z001")["points"] == after + 10, "F4 điểm đơn kênh đã gộp về hồ sơ chính")
n = crm.adjust_points("1", "Z001", -100000, reason="đổi ưu đãi")
check(n == 0, "F5 trừ quá tay chặn ở 0")
check(any(h["field"] == "points" for h in crm.list_history("1", "Z001")), "F6 audit điểm")

# ══ G. Broadcast segment tag/stage ═══════════════════════════════════
print("\nG. BROADCAST SEGMENT")
aud = broadcast.audience(["zalo"], {"type": "tag", "tag": "vip"})
check(len(aud) == 1 and aud[0]["user_id"] == "Z001", "G1 segment tag", aud)
# hội thoại meta đã gộp vào Z001 (có tag VIP) → chọn kênh meta theo tag vip vẫn ra fb:PG:U9
aud = broadcast.audience(["meta"], {"type": "tag", "tag": "VIP"})
check(len(aud) == 1 and aud[0]["user_id"] == "fb:PG:U9", "G2 hội thoại gộp dùng tag hồ sơ chính", aud)
aud = broadcast.audience(["telegram"], {"type": "stage", "stage": "lead"})
check(len(aud) == 1 and aud[0]["user_id"] == "tg:B:77", "G3 segment stage lead")
check(broadcast.audience(["zalo"], {"type": "tag", "tag": ""}) == [], "G4 tag rỗng → không gửi ai")
# Z001 giờ có 2 đơn done → stage repeat
aud = broadcast.audience(["zalo"], {"type": "stage", "stage": "repeat"})
check(len(aud) == 1 and aud[0]["user_id"] == "Z001", "G5 stage tự suy từ đơn (repeat)")

# ══ H. API bridge ════════════════════════════════════════════════════
print("\nH. API")
from flask import Flask
from app.web_api.customers_api import register_customers_routes
from app.web_api.loyalty_api import register_loyalty_routes
app = Flask(__name__)
register_customers_routes(app)
register_loyalty_routes(app)
cl = app.test_client()

r = cl.get("/customers?tag=vip")
check(r.status_code == 200 and r.get_json()["total"] == 1, "H1 GET /customers?tag=")
r = cl.get("/customers/tags")
check(r.status_code == 200 and len(r.get_json()) >= 1, "H2 GET /customers/tags")
r = cl.get("/customers/duplicates")
check(r.status_code == 200 and r.get_json() == [], "H3 GET /duplicates (đã gộp hết)")
r = cl.post("/customers/merge", json={"primary": {"account": "1", "user_id": "Z001"},
                                      "duplicate": {"account": "1", "user_id": "Z001"}})
check(r.status_code == 400, "H4 merge vào chính nó → 400")
r = cl.post("/customers/1/Z001/followups", json={"note": "gọi lại", "due_at": "2030-01-01"})
check(r.status_code == 200 and r.get_json()["followup"]["note"] == "gọi lại", "H5 POST followup")
fid = r.get_json()["followup"]["id"]
r = cl.get("/followups")
check(r.status_code == 200 and len(r.get_json()["items"]) == 1, "H6 GET /followups")
r = cl.post(f"/followups/{fid}/done")
check(r.status_code == 200 and r.get_json()["followup"]["status"] == "done", "H7 done")
r = cl.delete(f"/followups/{fid}")
check(r.status_code == 200, "H8 delete followup")
r = cl.post("/customers/1/Z001/points", json={"delta": 3, "reason": "test"})
check(r.status_code == 200 and r.get_json()["points"] == 3, "H9 POST points")
r = cl.post("/customers/1/Z001/points", json={"delta": "abc"})
check(r.status_code == 400, "H10 delta rác → 400")
r = cl.post("/vouchers", json={"code": "APIV1", "kind": "amount", "value": 20000})
check(r.status_code == 200 and r.get_json()["voucher"]["code"] == "APIV1", "H11 POST /vouchers")
vid = r.get_json()["voucher"]["id"]
r = cl.get("/vouchers")
check(r.status_code == 200 and any(v["code"] == "APIV1" for v in r.get_json()), "H12 GET /vouchers")
r = cl.post("/vouchers/check", json={"code": "APIV1", "total": 100000})
check(r.status_code == 200 and r.get_json()["discount"] == 20000, "H13 POST /vouchers/check")
o4 = orders.create(channel="zalo", user_id="Z001", total=90000, status="draft")
r = cl.post(f"/orders/{o4['id']}/voucher", json={"code": "APIV1"})
check(r.status_code == 200 and r.get_json()["order"]["total"] == 70000, "H14 áp mã qua API")
r = cl.patch(f"/vouchers/{vid}", json={"active": 0})
check(r.status_code == 200 and r.get_json()["voucher"]["active"] == 0, "H15 PATCH tắt mã")
r = cl.post("/vouchers/check", json={"code": "APIV1", "total": 100000})
check(r.status_code == 400, "H16 mã tắt → check 400")
r = cl.delete(f"/vouchers/{vid}")
check(r.status_code == 200 and loyalty.get_voucher(vid) is None, "H17 DELETE voucher")
r = cl.post("/vouchers", json={"code": "x", "value": 0})
check(r.status_code == 400, "H18 voucher rác → 400")

print(f"\n{'='*40}\nKẾT QUẢ: {PASS} pass / {FAIL} fail\n{'='*40}")
sys.exit(1 if FAIL else 0)
