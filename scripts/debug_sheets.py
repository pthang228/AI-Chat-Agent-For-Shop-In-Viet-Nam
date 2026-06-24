import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # để import được package app

import gspread
from google.oauth2.service_account import Credentials
from app.core.config import Config

creds = Credentials.from_service_account_file(
    Config.GOOGLE_CREDENTIALS_FILE,
    scopes=['https://www.googleapis.com/auth/spreadsheets.readonly']
)
client = gspread.authorize(creds)
out = []

for name, sid in [('Haru', Config.HARU_SHEET_ID), ('Mochi', Config.MOCHI_SHEET_ID)]:
    sh = client.open_by_key(sid)
    # Tim tab thang 5
    target = None
    for ws in sh.worksheets():
        if '5' in ws.title:
            target = ws
            break
    if not target:
        out.append(f"{name}: khong tim thay tab thang 5\n")
        continue

    out.append(f"\n=== {name} | Tab: {target.title} ===\n")
    rows = target.get_all_values()
    out.append(f"Row1: {rows[0]}\n")
    out.append(f"Row2: {rows[1]}\n")

    # Tat ca ngay tu 22-25/05
    for row in rows[2:]:
        if len(row) > 1 and any(d in str(row[1]) for d in ['22/05','23/05','24/05']):
            out.append(f"  {row[0]} {row[1]}: {row[2:]}\n")

with open('debug_output.txt', 'w', encoding='utf-8') as f:
    f.writelines(out)
print("Xong!")
